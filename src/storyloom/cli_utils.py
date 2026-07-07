"""CLI utility functions for the Storyloom test harness.

Observers and helpers shared between main.py and prompt_lab test scripts.
No dependency on Display or any UI module — pure data observers.
"""

import json
from pathlib import Path
from typing import Callable

from storyloom.core.game_loop import RoundRecord


# ── File-system observer ────────────────────────────────────────────

def make_debug_observer(output_dir: str) -> Callable[[RoundRecord], None]:
    """Create an observer that saves per-round data to disk.

    Writes to {output_dir}/round-{N}/:
      - messages.json   — full messages array sent to API
      - response.txt    — raw LLM response
      - metrics.json    — timing, token usage, node, branch
      - parsed.json     — structured parse summary (segments, choices, sets, routes)
      - analysis.md     — human-readable round summary

    Args:
        output_dir: Base directory for round data output.

    Returns:
        Callable suitable as a GameLoop observer.
    """
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)

    def observer(record: RoundRecord) -> None:
        rd = base / f"round-{record.round_number}"
        rd.mkdir(parents=True, exist_ok=True)

        # Full messages array
        (rd / "messages.json").write_text(
            json.dumps(record.messages_sent, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Raw LLM response
        (rd / "response.txt").write_text(record.raw_response, encoding="utf-8")

        # Metrics
        metrics = {
            "round": record.round_number,
            "ttft": record.ttft,
            "tokens": record.tokens,
            "node": record.node,
            "branch": record.selected_branch,
            "timestamp": record.timestamp,
        }
        (rd / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Parsed summary
        if record.parsed:
            parsed_summary = {
                "total_segs": record.parsed.total_segments,
                "pre_segs": record.parsed.pre_segments,
                "post_segs": record.parsed.post_segments,
                "bridge": record.parsed.bridge_found,
                "checkpoint": record.parsed.checkpoint_node,
                "checkpoint_summary": record.parsed.checkpoint_summary,
                "choices": record.parsed.choices,
                "sets": [
                    {"var": s.var, "op": s.op, "val": s.val, "if": s.condition}
                    for s in record.parsed.sets
                ],
                "routes": [
                    {"target": r.target, "condition": r.condition}
                    for r in record.parsed.routes
                ],
            }
            (rd / "parsed.json").write_text(
                json.dumps(parsed_summary, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # Human-readable analysis
            lines = _build_analysis_lines(record)
            (rd / "analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    return observer


def _build_analysis_lines(record: RoundRecord) -> list[str]:
    """Build human-readable analysis lines for a round record."""
    p = record.parsed
    lines = [
        f"# Round {record.round_number} — Analysis",
        f"- Node: {record.node or '(none)'}",
        f"- Branch: {record.selected_branch or '(none)'}",
    ]
    if record.ttft is not None:
        lines.append(f"- TTFT: {record.ttft:.1f}s")
    else:
        lines.append("- TTFT: N/A")

    if record.tokens:
        prompt_tok = record.tokens.get("prompt", "?")
        comp_tok = record.tokens.get("completion", "?")
        total_tok = record.tokens.get("total", "?")
        lines.append(f"- Tokens: prompt={prompt_tok} completion={comp_tok} total={total_tok}")

    lines.append(
        f"- Segments: {p.total_segments} "
        f"(pre={p.pre_segments}, post={p.post_segments})"
    )
    lines.append(f"- Bridge: {'✓' if p.bridge_found else '✗'}")

    if p.checkpoint_node:
        targets = [r.target for r in p.routes]
        lines.append(
            f"- Checkpoint: {p.checkpoint_node}"
            + (f" → {targets}" if targets else "")
        )
        if p.checkpoint_summary:
            lines.append(f"  Summary: {p.checkpoint_summary}")

    if p.choices:
        c = p.choices[-1]
        lines.append(f"- Choice: {c.get('id', '?')} → {c.get('branches', [])}")

    lines.append("")
    return lines


# ── Terminal observer ───────────────────────────────────────────────

def make_print_observer(stream=None, verbose: bool = False):
    """Create an observer that prints round summaries to a stream.

    Args:
        stream: Output stream (defaults to sys.stderr so it doesn't
                mix with data output on stdout).
        verbose: If True, include segment counts and token info.

    Returns:
        Callable suitable as a GameLoop observer.
    """
    import sys
    out = stream or sys.stderr

    def observer(record: RoundRecord) -> None:
        status = "✗" if record.parsed is None else "✓"
        parts = [
            f"[Round {record.round_number}]",
            f"node={record.node or '?'}",
        ]
        if verbose and record.parsed:
            parts.append(f"segs={record.parsed.total_segments}")
        if record.ttft is not None:
            parts.append(f"ttft={record.ttft:.1f}s")
        if verbose and record.tokens:
            parts.append(f"tok={record.tokens.get('total', '?')}")
        parts.append(status)
        print("  ".join(parts), file=out)

    return observer
