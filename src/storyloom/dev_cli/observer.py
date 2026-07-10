"""DevObserver — writes raw prompt/response/check data to files."""
import json
from pathlib import Path
from datetime import datetime, timezone

from storyloom.core.game_loop import RoundRecord


class DevObserver:
    """Records per-round raw data to dev_output/.

    prompts.txt   — full messages array sent to LLM [overwrite]
    responses.txt — raw LLM response text [overwrite]
    checks.txt    — parsed summary [append]
    """

    def __init__(self, output_dir: str = "dev_output"):
        self._dir = Path(output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── Game round ──

    def record_round(self, record: RoundRecord) -> None:
        ts = record.timestamp or self._now()
        self._write_messages(record, ts)
        self._write_response(record, ts)
        self._write_checks(record, ts)

    # ── Co-creation ──

    def record_co_create_messages(self, phase: str, messages: list[dict]) -> None:
        """User + system only — assistant contains LLM-generated content."""
        header = f"══ Co-Create [{phase}] ══ {self._now()}"
        body = self._format_messages(messages, skip_assistant=True)
        self._write_file("prompts.txt", f"{header}\n{body}")

    def record_co_create_response(self, text: str) -> None:
        self._write_file(
            "responses.txt",
            f"── Co-Create ── {self._now()} ──\n{text}\n\n",
        )

    def record_co_create_result(self, story_config: dict, outline_text: str) -> None:
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

    # ── Private: message formatting ─────────────────────────────

    @staticmethod
    def _format_messages(messages: list[dict], skip_assistant: bool = False) -> str:
        """Format messages array to [role]\\ncontent\\n blocks."""
        lines = []
        for msg in messages:
            role = msg.get("role", "?")
            if skip_assistant and role == "assistant":
                continue
            lines.append(f"[{role}]")
            lines.append(msg.get("content", ""))
            lines.append("")
        return "\n".join(lines)

    # ── Private: per-file writers ───────────────────────────────

    def _write_messages(self, record: RoundRecord, ts: str) -> None:
        header = f"── Round {record.round_number} ── {ts} ──"
        body = self._format_messages(record.messages_sent)
        self._write_file("prompts.txt", f"{header}\n{body}")

    def _write_response(self, record: RoundRecord, ts: str) -> None:
        meta = ""
        if record.ttft is not None:
            meta += f" ttft={record.ttft:.1f}s"
        if record.tokens:
            t = record.tokens
            meta += (
                f" tokens=prompt:{t.get('prompt', '?')}"
                f",completion:{t.get('completion', '?')}"
                f",total:{t.get('total', '?')}"
            )
        header = f"── Round {record.round_number} ── {ts}{meta} ──"
        self._write_file("responses.txt", f"{header}\n{record.raw_response}\n")

    def _write_checks(self, record: RoundRecord, ts: str) -> None:
        lines = [f"── Round {record.round_number} ── {ts} ──"]
        lines.append(
            f"Node: {record.node or '(none)'} | "
            f"Branch: {record.selected_branch or '(none)'}"
        )

        if record.parsed:
            p = record.parsed
            lines.append(
                f"Segments: {p.total_segments} total "
                f"(pre={p.pre_segments}, post={p.post_segments}) "
                f"| Bridge: {'✓' if p.bridge_found else '✗'}"
            )
            if p.checkpoint_node:
                targets = (
                    f" → {[r.target for r in p.routes]}" if p.routes else ""
                )
                lines.append(f"Checkpoint: {p.checkpoint_node}{targets}")
                if p.checkpoint_summary:
                    lines.append(f"  Summary: {p.checkpoint_summary}")
            if p.sets:
                lines.append("Sets:")
                for s in p.sets:
                    cond = f" [if {s.condition}]" if s.condition else ""
                    lines.append(f"  {s.var} {s.op} {s.val}{cond}")
            if p.choices:
                c = p.choices[-1]
                lines.append(f"Choice: {c.get('id', '?')} → {c.get('branches', [])}")

        if record.ttft is not None:
            lines.append(f"TTFT: {record.ttft:.1f}s")
        if record.tokens:
            t = record.tokens
            lines.append(
                f"Tokens: prompt={t.get('prompt', '?')} "
                f"completion={t.get('completion', '?')} "
                f"total={t.get('total', '?')}"
            )
        lines.append("")
        self._write_file("checks.txt", "\n".join(lines), mode="a")

    # ── I/O helpers ─────────────────────────────────────────────

    def _write_file(self, filename: str, content: str, mode: str = "w") -> None:
        path = self._dir / filename
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)
            f.flush()

    def _now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
