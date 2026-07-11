"""DevObserver — writes raw prompt/response/check data to dev_output/.

Three fixed files:
  prompts.txt   — messages array sent to LLM [overwrite]
  responses.txt — raw LLM response text [overwrite]
  checks.txt    — round inspection summary [append]
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from storyloom.core.game_loop import RoundRecord


class DevObserver:
    """Records per-round raw data to dev_output/.

    Delete this file (and the dev_cli directory) for release builds.
    """

    def __init__(self, output_dir: str = "dev_output"):
        self._dir = Path(output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── Game round ─────────────────────────────────────────────────

    def record_round(self, record: RoundRecord) -> None:
        ts = record.timestamp or self._now()
        self._write_messages(record.messages_sent, f"── Round {record.round_number} ── {ts} ──")
        self._write_response(record.raw_response, record, ts)
        self._write_checks(record, ts)

    # ── Co-creation ────────────────────────────────────────────────

    def record_co_create_prompt(
        self, messages: list[dict], user_input: str
    ) -> None:
        """Write prompt at send time — called BEFORE ``flow.send()``."""
        prompt_msgs = list(messages) + [{"role": "user", "content": user_input}]
        self._write_messages(prompt_msgs, f"══ Co-Create ══ {self._now()}")

    def record_co_create_response(self, messages: list[dict]) -> None:
        """Write LLM response — called AFTER ``flow.send()``."""
        if messages and messages[-1].get("role") == "assistant":
            self._write_response(messages[-1]["content"], None, self._now())

    # ── Adventure log ──────────────────────────────────────────────

    def record_adventure_log(self, prompt: str, response: str) -> None:
        """Record adventure log prompt + response (separate API call)."""
        ts = self._now()
        self._write_messages(
            [{"role": "user", "content": prompt}],
            f"── Adventure Log ── {ts} ──",
        )
        self._write_response(response, None, ts)

    # ── Prompt-at-send-time (called from game_driver) ──────────────

    def write_prompt_at_send(self, messages: list[dict], round_num: int) -> None:
        """Write prompt immediately after engine sends it.

        Called right after ``start_game()`` and after each
        ``stream_round()`` iteration — engine has stored the next
        round's prompt in ``_pending_messages`` at that point.
        """
        self._write_messages(
            messages,
            f"── Round {round_num} ── {self._now()} ──",
        )

    def record_co_create_result(self, story_config: dict, outline_text: str) -> None:
        """Record final co-creation result → checks.txt."""
        self._write_file(
            "checks.txt",
            f"══ Co-Create Result ══\n"
            f"Label: {story_config.get('label', '?')}\n"
            f"Genre: {story_config.get('genre', '?')}\n"
            f"Tier: {story_config.get('tier', '?')}\n"
            f"Outline:\n{outline_text}\n"
            f"Variables: {json.dumps(story_config.get('variables', []), ensure_ascii=False, indent=2)}\n\n",
            mode="a",
        )

    # ── Private writers ────────────────────────────────────────────

    def _write_messages(self, messages: list[dict], header: str) -> None:
        parts = []
        for msg in messages:
            parts.append(f"[{msg.get('role', '?')}]")
            parts.append(msg.get("content", ""))
            parts.append("")
        self._write_file("prompts.txt", f"{header}\n" + "\n".join(parts))

    def _write_response(self, text: str, record: RoundRecord | None, ts: str) -> None:
        if record is not None:
            meta = ""
            if record.ttft is not None:
                meta += f" ttft={record.ttft:.1f}s"
            if record.tokens:
                t = record.tokens
                meta += f" tokens=prompt:{t.get('prompt','?')},completion:{t.get('completion','?')},total:{t.get('total','?')}"
            header = f"── Round {record.round_number} ── {ts}{meta} ──"
        else:
            header = f"── Co-Create ── {ts} ──"
        self._write_file("responses.txt", f"{header}\n{text}\n")

    def _write_checks(self, record: RoundRecord, ts: str) -> None:
        lines = ["", f"── Round {record.round_number} ── {ts} ──"]
        lines.append(f"Node: {record.node or '(none)'} | Branch: {record.selected_branch or '(none)'}")
        if record.parsed:
            p = record.parsed
            lines.append(f"Segments: {p.total_segments} total (pre={p.pre_segments}, post={p.post_segments}) | Bridge: {'Y' if p.bridge_found else 'N'}")
            if p.checkpoint_node:
                lines.append(f"Checkpoint: {p.checkpoint_node}{' -> ' + str([r.target for r in p.routes]) if p.routes else ''}")
                if p.checkpoint_summary:
                    lines.append(f"  Summary: {p.checkpoint_summary}")
            if p.sets:
                lines.append("Sets:")
                for s in p.sets:
                    cond = f" [if {s.condition}]" if s.condition else ""
                    lines.append(f"  {s.var} {s.op} {s.val}{cond}")
            if p.choices:
                c = p.choices[-1]
                lines.append(f"Choice: {c.get('id','?')} -> {c.get('branches',[])}")
        if record.ttft is not None:
            lines.append(f"TTFT: {record.ttft:.1f}s")
        if record.tokens:
            t = record.tokens
            lines.append(f"Tokens: prompt={t.get('prompt','?')} completion={t.get('completion','?')} total={t.get('total','?')}")
        lines.append("")
        self._write_file("checks.txt", "\n".join(lines), mode="a")

    # ── Helpers ───────────────────────────────────────────────────

    def _write_file(self, filename: str, content: str, mode: str = "w") -> None:
        path = self._dir / filename
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)
            f.flush()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
