"""DevObserver — writes raw prompt/response/check data to files."""
from pathlib import Path
from datetime import datetime, timezone

from storyloom.core.game_loop import RoundRecord


class DevObserver:
    """Records per-round raw data to dev_output/ files (append mode).

    Creates three files:
      - prompts.txt   — full user messages sent to LLM
      - responses.txt — raw LLM response text
      - checks.txt    — parsed summary (segments, bridge, sets, etc.)
    """

    def __init__(self, output_dir: str = "dev_output"):
        self._dir = Path(output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._co_create_started = False

    # ── Game round ──

    def record_round(self, record: RoundRecord) -> None:
        """Called after each round completes. Appends to all three files."""
        ts = record.timestamp or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        self._append_prompts(record, ts)
        self._append_response(record, ts)
        self._append_checks(record, ts)

    # ── private helpers ──

    def _append_prompts(self, record: RoundRecord, ts: str) -> None:
        lines = [f"── Round {record.round_number} ── {ts} ──"]
        for msg in record.messages_sent:
            if msg.get("role") == "user":
                lines.append(msg.get("content", ""))
        lines.append("")
        self._append("prompts.txt", "\n".join(lines))

    def _append_response(self, record: RoundRecord, ts: str) -> None:
        parts = [f"── Round {record.round_number} ── {ts}"]
        if record.ttft is not None:
            parts.append(f" ttft={record.ttft:.1f}s")
        if record.tokens:
            p = record.tokens.get("prompt", "?")
            c = record.tokens.get("completion", "?")
            t = record.tokens.get("total", "?")
            parts.append(f" tokens=prompt:{p},completion:{c},total:{t}")
        parts.append(" ──")
        header = "".join(parts)

        lines = [header, record.raw_response, ""]
        self._append("responses.txt", "\n".join(lines))

    def _append_checks(self, record: RoundRecord, ts: str) -> None:
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
                lines.append(
                    f"Checkpoint: {p.checkpoint_node}"
                    + (
                        f" → {[r.target for r in p.routes]}"
                        if p.routes
                        else ""
                    )
                )
                if p.checkpoint_summary:
                    lines.append(f"  Summary: {p.checkpoint_summary}")
            if p.sets:
                set_lines = []
                for s in p.sets:
                    cond = f" [if {s.condition}]" if s.condition else ""
                    set_lines.append(f"  {s.var} {s.op} {s.val}{cond}")
                lines.append("Sets:\n" + "\n".join(set_lines))
            if p.choices:
                c = p.choices[-1]
                lines.append(
                    f"Choice: {c.get('id', '?')} → {c.get('branches', [])}"
                )

        if record.ttft is not None:
            lines.append(f"TTFT: {record.ttft:.1f}s")
        if record.tokens:
            lines.append(
                f"Tokens: prompt={record.tokens.get('prompt', '?')} "
                f"completion={record.tokens.get('completion', '?')} "
                f"total={record.tokens.get('total', '?')}"
            )
        lines.append("")
        self._append("checks.txt", "\n".join(lines))

    # ── Co-creation ──

    def record_co_create_start(self) -> None:
        """Mark the start of a co-creation session in prompts/responses."""
        header = "══ Co-Create Session ══\n"
        self._append("prompts.txt", header)
        self._append("responses.txt", header)

    def record_co_create_prompt(self, user_input: str) -> None:
        """Record user input sent during co-creation Q&A."""
        self._append("prompts.txt", f"[User]\n{user_input}\n\n")

    def record_co_create_response(self, text: str) -> None:
        """Record LLM response during co-creation Q&A."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._append("responses.txt", f"── {now} ──\n{text}\n\n")

    def record_co_create_result(self, story_config: dict, outline_text: str) -> None:
        """Record the final generated story setup."""
        import json
        self._append(
            "checks.txt",
            "══ Co-Create Result ══\n"
            f"Label: {story_config.get('label', '?')}\n"
            f"Genre: {story_config.get('genre', '?')}\n"
            f"Tier: {story_config.get('tier', '?')}\n"
            f"Outline:\n{outline_text}\n"
            f"Variables: {json.dumps(story_config.get('variables', []), ensure_ascii=False, indent=2)}\n"
            "\n",
        )

    # ── I/O ──

    def _append(self, filename: str, content: str) -> None:
        path = self._dir / filename
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
            f.flush()
