#!/usr/bin/env python3
"""Multi-round conversation-mode test with state persistence.

Reuses src production code: ApiClient, XmlParser, PromptBuilder, ContextManager, GameState.

Usage:
  # Round 1 — with manual prompt file
  python3 tests/run_multi_round_test.py --prompt round1-current.txt

  # Round N — continue from previous round (default choice: 1)
  python3 tests/run_multi_round_test.py --continue

  # Round N — continue with specific choice
  python3 tests/run_multi_round_test.py --continue --choice 2
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.storyloom.api_client import ApiClient, ApiError
from src.storyloom.prompt_builder import PromptBuilder
from src.storyloom.context_manager import ContextManager
from src.storyloom.game_loop import GameState
from src.storyloom.xml_parser import XmlParser, ParseError, ParsedOutput

# ── Paths ──────────────────────────────────────────────────────────────

OUTPUT_DIR = PROJECT_ROOT / "tests" / "prompt_lab" / "data" / "output" / "multi-round"
PROMPT_DIR = PROJECT_ROOT / "tests" / "prompt_lab" / "data" / "prompts"
STATE_PATH = OUTPUT_DIR / "state.json"

# ── Test fixture (for auto-generated prompts) ──────────────────────────

SAMPLE_STORY = {
    "genre": "赛博朋克冒险",
    "tier": "medium",
    "label": "霓虹深渊",
    "setting": "2087年新东京地下城，企业控制数据流，芯片即权力",
    "protagonist_name": "林焰",
    "protagonist_identity": "前荒坂安全顾问，现自由佣兵",
    "protagonist_traits": "冷静、道德灰色，有过载神经接口",
    "tone": "黑暗冷峻",
    "conflict": "一枚从企业R&D部门流出的神秘芯片正在寻找宿主",
    "characters": "耗子（地下情报贩子，亦敌亦友）、美智子（荒坂安全主管，前上司）",
    "variables": [
        {"name": "体力", "type": "number", "initial": 80},
        {"name": "理智值", "type": "number", "initial": 55},
        {"name": "信任度", "type": "number", "initial": 10},
        {"name": "芯片完整度", "type": "number", "initial": 100},
        {"name": "线索", "type": "list", "initial": []},
        {"name": "所属势力", "type": "string", "initial": "自由佣兵"},
    ],
}

SAMPLE_OUTLINE = """ch1_bar [completed] — 霓虹深渊：在酒吧获取情报
  → ch2_confrontation [active]
ch2_confrontation [active] — 地下交易：与耗子会面
  ├→ ch3_ally [pending]
  └→ ch3_betrayal [pending]
ch3_ally [pending] — 盟友之路：通过地下网络逃离
ch3_betrayal [pending] — 背叛之路：杀出重围
ch4_safehouse [pending] — 安全屋：揭开芯片秘密（结局）"""

VALID_NODES = {"ch1_bar", "ch2_confrontation", "ch3_ally", "ch3_betrayal", "ch4_safehouse"}
VALID_VARS = {v["name"] for v in SAMPLE_STORY["variables"]}

# Node → goal mapping
NODE_GOALS = {
    "ch2_confrontation": "与耗子完成交易",
    "ch3_ally": "通过地下网络逃离追捕",
    "ch3_betrayal": "杀出重围，摆脱荒坂追兵",
    "ch4_safehouse": "到达安全屋，揭开芯片秘密",
}


# ── Correctness checks ──────────────────────────────────────────────────

def check_correctness(parsed: ParsedOutput | None,
                      parse_error: str | None) -> list[str]:
    issues = []
    if parse_error:
        issues.append(f"PARSE: {parse_error[:80]}")
        return issues
    if parsed is None:
        issues.append("PARSE: returned None")
        return issues

    if not parsed.bridge_found:
        issues.append("no-bridge")
    if not parsed.choices:
        issues.append("no-choice")
    else:
        for c in parsed.choices:
            if len(c["branches"]) < 2:
                issues.append(f"few-opts({c['id']}={len(c['branches'])})")
    if not parsed.checkpoint_node:
        issues.append("no-checkpoint")
    elif parsed.checkpoint_node not in VALID_NODES:
        issues.append(f"bad-node({parsed.checkpoint_node})")
    for rt in parsed.routes:
        if rt.target and rt.target not in VALID_NODES:
            issues.append(f"bad-route({rt.target})")
    all_opt_branches = set()
    for c in parsed.choices:
        for b in c["branches"]:
            if b:
                all_opt_branches.add(b)
    post_set = set(parsed.post_branches)
    if all_opt_branches:
        if all_opt_branches - post_set:
            issues.append(f"miss-branch({','.join(sorted(all_opt_branches - post_set))})")
        if post_set - all_opt_branches:
            issues.append(f"extra-branch({','.join(sorted(post_set - all_opt_branches))})")
    if parsed.numbering_issues:
        issues.append(f"num({';'.join(parsed.numbering_issues)})")
    if parsed.total_segments < 60:
        issues.append(f"too-few-segs({parsed.total_segments})")
    elif parsed.total_segments > 120:
        issues.append(f"too-many-segs({parsed.total_segments})")
    if parsed.total_segments > 0:
        ratio = parsed.pre_segments / parsed.total_segments
        if ratio < 0.2:
            issues.append(f"bridge-early({ratio:.0%})")
        elif ratio > 0.8:
            issues.append(f"bridge-late({ratio:.0%})")
    for s in parsed.sets:
        if s.var and s.var not in VALID_VARS:
            issues.append(f"bad-var({s.var})")
    for c in parsed.choices:
        cid = c["id"]
        for s in parsed.sets:
            if s.condition and cid in s.condition:
                if re.search(r'==[A-E]', s.condition):
                    issues.append(f"choice-letter({s.condition})")
        for rt in parsed.routes:
            if rt.condition and re.search(r'==[A-E]', rt.condition):
                issues.append(f"route-letter({rt.condition})")
    return issues


# ── State persistence ───────────────────────────────────────────────────

def save_state(round_number: int,
               round1_user: str, round1_assistant: str,
               cm: ContextManager, game_state: GameState,
               current_node: str, goal: str,
               completed_nodes: list[str],
               outline_text: str) -> None:
    """Persist conversation state to state.json."""
    rounds_data = []
    for i in range(len(cm._rounds)):
        r = cm._rounds[i]
        rounds_data.append({
            "round_num": r["round_num"],
            "user": r["user_content"],
            "asst": r["assistant_content"],
            "checkpoint": r.get("checkpoint", ""),
        })

    data = {
        "round_number": round_number,
        "round1_user": round1_user,
        "round1_assistant": round1_assistant,
        "rounds": rounds_data,
        "current_node": current_node,
        "goal": goal,
        "completed_nodes": completed_nodes,
        "state_vars": game_state.state_vars,
        "outline_text": outline_text,
    }
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def load_state() -> dict:
    """Load conversation state from state.json."""
    if not STATE_PATH.exists():
        raise FileNotFoundError(f"State file not found: {STATE_PATH}\n"
                                f"Run Round 1 first with --prompt.")
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def rebuild_context_manager(state: dict) -> ContextManager:
    """Rebuild ContextManager from saved state."""
    cm = ContextManager()
    cm.set_round1(state["round1_user"], state["round1_assistant"])
    for r in state.get("rounds", []):
        cm.add_round(r["user"], r["asst"])
    return cm


def rebuild_game_state(state: dict) -> GameState:
    """Rebuild GameState from saved state vars."""
    gs = GameState(SAMPLE_STORY)
    for name, value in state["state_vars"].items():
        if name in gs._state_vars:
            gs._state_vars[name] = value
    return gs


# ── Round execution ─────────────────────────────────────────────────────

def run_round1(prompt_text: str, client: ApiClient) -> dict:
    """Execute Round 1. Returns result dict + saves state."""
    round_num = 1
    t0 = time.perf_counter()

    try:
        content = client.chat([{"role": "user", "content": prompt_text}])
    except ApiError as e:
        return {"error": str(e), "time": time.perf_counter() - t0}

    elapsed = time.perf_counter() - t0

    # Parse
    parsed = None
    parse_error = None
    try:
        parsed = XmlParser.parse(content)
    except ParseError as e:
        parse_error = str(e)

    issues = check_correctness(parsed, parse_error)

    # Write output
    out_path = OUTPUT_DIR / f"round{round_num:02d}-test.md"
    write_output(out_path, round_num, elapsed, client, content, issues)

    # Save state for next round
    if parsed and not parse_error:
        gs = GameState(SAMPLE_STORY)
        cm = ContextManager()
        cm.set_round1(prompt_text, content)

        # Determine next node from routes (default to first route target)
        node = "ch2_confrontation"
        goal = NODE_GOALS.get(node, "")
        if parsed.routes:
            node = parsed.routes[0].target
            goal = NODE_GOALS.get(node, "")

        save_state(round_num, prompt_text, content, cm, gs,
                   node, goal, ["ch1_bar", "ch2_confrontation"],
                   SAMPLE_OUTLINE)

    return {
        "round": round_num, "time": elapsed,
        "segments": parsed.total_segments if parsed else 0,
        "choice_id": parsed.choice_id if parsed else None,
        "cp_node": parsed.checkpoint_node if parsed else None,
        "issues": issues,
    }


def run_round_n(client: ApiClient, choice_key: int = 1) -> dict:
    """Execute Round N (N >= 2) by continuing from saved state."""
    state = load_state()
    round_num = state["round_number"] + 1
    choice_key_str = str(choice_key)

    # Rebuild production objects
    cm = rebuild_context_manager(state)
    gs = rebuild_game_state(state)
    pb = PromptBuilder()

    # Load last parsed output to get choice_id and sets
    last_rounds = state.get("rounds", [])
    if last_rounds:
        last_asst = last_rounds[-1]["asst"]
    else:
        last_asst = state["round1_assistant"]

    last_parsed = XmlParser.parse(last_asst)

    # Build choice_dict from player input
    choice_dict = {}
    if last_parsed.choices:
        main_choice = last_parsed.choices[-1]
        choice_dict[main_choice["id"]] = choice_key

    # Apply state changes from last round
    for set_op in last_parsed.sets:
        gs.apply_set(set_op, choice_dict)

    # Evaluate routes
    current_node = state["current_node"]
    completed_nodes = list(state["completed_nodes"])
    if choice_dict and last_parsed.routes:
        for rt in last_parsed.routes:
            if gs.evaluate_condition(rt.condition, choice_dict):
                if rt.target and rt.target in VALID_NODES:
                    # Mark previous node as completed
                    if current_node not in completed_nodes:
                        completed_nodes.append(current_node)
                    current_node = rt.target
                    break

    goal = NODE_GOALS.get(current_node, "")

    # Get compressed summaries
    compressed_rounds = cm.get_compressed_rounds()
    compressed_summaries = [str(r) for r in compressed_rounds] if compressed_rounds else None

    # Build Round N context
    bridge_text = cm.get_last_bridge_text()
    rn_context = pb.build_round_n(
        current_node=current_node,
        goal=goal,
        completed_nodes=completed_nodes,
        state_vars=gs.state_vars,
        bridge_text=bridge_text,
        compressed_summaries=compressed_summaries,
    )

    # Build messages: existing history + new user message
    messages = cm.get_messages()
    messages.append({"role": "user", "content": rn_context})

    # Call API
    t0 = time.perf_counter()
    try:
        content = client.chat(messages)
    except ApiError as e:
        return {"error": str(e), "time": time.perf_counter() - t0}
    elapsed = time.perf_counter() - t0

    # Parse
    parsed = None
    parse_error = None
    try:
        parsed = XmlParser.parse(content)
    except ParseError as e:
        parse_error = str(e)

    issues = check_correctness(parsed, parse_error)

    # Write output
    out_path = OUTPUT_DIR / f"round{round_num:02d}-test.md"
    write_output(out_path, round_num, elapsed, client, content, issues)

    # Update state
    if parsed and not parse_error:
        cm.add_round(rn_context, content)
        # Determine next node
        next_node = current_node
        if parsed.routes:
            next_node = parsed.routes[0].target
        next_goal = NODE_GOALS.get(next_node, "")
        if current_node not in completed_nodes:
            completed_nodes.append(current_node)

        save_state(round_num,
                   state["round1_user"], state["round1_assistant"],
                   cm, gs, next_node, next_goal,
                   completed_nodes, state["outline_text"])

    return {
        "round": round_num, "time": elapsed,
        "segments": parsed.total_segments if parsed else 0,
        "choice_id": parsed.choice_id if parsed else None,
        "cp_node": parsed.checkpoint_node if parsed else None,
        "issues": issues,
    }


def write_output(path: Path, round_num: int, elapsed: float,
                 client: ApiClient, content: str, issues: list[str]) -> None:
    header = (
        f"# Round {round_num:02d} Test\n\n"
        f"- **Time**: {elapsed:.1f}s\n"
        f"- **Model**: {client.model}\n"
        f"- **Timestamp**: {datetime.now(timezone.utc).isoformat()}\n"
    )
    if issues:
        header += f"- **Issues**: {'; '.join(issues)}\n"
    else:
        header += "- **Issues**: ✓ CLEAN\n"
    header += "\n---\n\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + content, encoding="utf-8")


# ── Main ────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Multi-round conversation architecture test."
    )
    p.add_argument(
        "--prompt", type=str, default=None,
        help="Prompt file for Round 1 (relative to tests/prompt_lab/data/prompts/).",
    )
    p.add_argument(
        "--continue", dest="continue_mode", action="store_true",
        help="Continue from saved state (Round N >= 2).",
    )
    p.add_argument(
        "--choice", type=int, default=1,
        help="Player choice number for --continue mode (default: 1).",
    )
    args = p.parse_args()

    if not args.prompt and not args.continue_mode:
        p.error("Need --prompt (Round 1) or --continue (Round N).")

    client = ApiClient()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.continue_mode:
        print(f"Model:  {client.model}")
        print(f"Output: {OUTPUT_DIR}")
        print(f"Choice: {args.choice}")
        print()
        result = run_round_n(client, args.choice)
    else:
        # Round 1
        prompt_path = Path(args.prompt)
        if not prompt_path.is_absolute():
            prompt_path = PROMPT_DIR / args.prompt
        if not prompt_path.exists():
            print(f"[ERROR] Prompt not found: {prompt_path}")
            sys.exit(1)
        prompt_text = prompt_path.read_text(encoding="utf-8")

        print(f"Model:  {client.model}")
        print(f"Output: {OUTPUT_DIR}")
        print(f"Prompt: {prompt_path} ({len(prompt_text)} chars)")
        print()
        result = run_round1(prompt_text, client)

    # Report
    if "error" in result:
        print(f"ERROR: {result['error']}")
    else:
        status = "✓ CLEAN" if not result["issues"] else f"✗ {len(result['issues'])} issues"
        print(
            f"Round {result['round']}: {result['time']:.1f}s  "
            f"segs={result['segments']}  "
            f"choice={result['choice_id']}  cp={result['cp_node']}  "
            f"{status}"
        )
        if result["issues"]:
            print(f"  Issues: {'; '.join(result['issues'])}")

    print(f"\nState: {STATE_PATH}")


if __name__ == "__main__":
    main()
