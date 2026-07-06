"""Line-by-line streaming parser for line-numbered XML narrative output.

Based on the NNN| line-number format from round1-linenum.txt, this parser
processes LLM output as a stream of lines rather than requiring a complete
XML document.

Architecture:
  Pre-processor:  Always runs ahead. Builds structural indices (branch
                  ranges, element positions), checks format rules.
  Actual processor: Event consumer. Makes decisions (branch matching,
                     condition evaluation), drives display.

The parser yields ParseEvent objects as it encounters elements. The
caller (GameLoop) consumes events to drive display, state updates, and
user interaction.
"""

import re
from dataclasses import dataclass, field
from enum import Enum, auto

from src.storyloom.xml_parser import (
    ParsedOutput,
    Segment,
    SetOperation,
    RouteTarget,
)


class EventType(Enum):
    """Types of events emitted by the streaming parser."""
    STORY_BEGIN = auto()       # <story>
    STORY_END = auto()         # </story>
    SEGMENT = auto()           # <seg>text</seg>
    CHOICE_BEGIN = auto()      # <choice id="X">
    OPT = auto()               # <opt key="A" branch="X">text</opt>
    CHOICE_END = auto()        # </choice>
    SET = auto()               # <set var="X" op="+" val="5"/>
    CHECKPOINT = auto()        # <checkpoint node="X" summary="...">
    ROUTE = auto()             # <route if="X" target="Y"/>
    CHECKPOINT_END = auto()    # </checkpoint>
    BRIDGE = auto()            # <bridge/>
    BRANCH_ENTER = auto()      # <branch name="X">
    BRANCH_EXIT = auto()       # </branch>
    PARSE_ERROR = auto()       # Unrecognized or invalid element


@dataclass
class ParseEvent:
    """A single event from the streaming parser."""
    type: EventType
    text: str | None = None           # SEGMENT text, OPT text
    # CHOICE_BEGIN / OPT
    choice_id: str | None = None      # <choice id="...">
    opt_key: str | None = None        # <opt key="...">
    opt_branch: str | None = None     # <opt branch="...">
    opt_if: str | None = None         # <opt if="...">
    # SET
    set_var: str | None = None
    set_op: str | None = None
    set_val: str | None = None
    set_if: str | None = None
    # CHECKPOINT
    cp_node: str | None = None
    cp_summary: str | None = None
    # ROUTE
    route_if: str | None = None
    route_target: str | None = None
    # BRANCH_ENTER
    branch_name: str | None = None
    # PARSE_ERROR
    error_msg: str | None = None
    # Position
    line_number: int = 0
    position: str = "pre"             # "pre" or "post" (bridge relative)


# ── Line regex patterns ───────────────────────────────────────────
# Each line starts with NNN|  (stripped before parsing)

_RE_STORY_OPEN = re.compile(r'^<story>\s*$')
_RE_STORY_CLOSE = re.compile(r'^</story>\s*$')
_RE_SEG = re.compile(r'^<seg(?: n="\d+")?>(.*)</seg>\s*$')
_RE_CHOICE_OPEN = re.compile(r'^<choice id="([^"]+)">\s*$')
_RE_CHOICE_CLOSE = re.compile(r'^</choice>\s*$')
_RE_OPT = re.compile(
    r'^<opt key="([^"]+)" branch="([^"]+)"(?: if="([^"]+)")?>(.*)</opt>\s*$'
)
_RE_SET = re.compile(
    r'^<set var="([^"]+)" op="([^"]+)" val="([^"]+)"'
    r'(?: if="([^"]+)")?\s*/>\s*$'
)
_RE_CHECKPOINT_OPEN = re.compile(
    r'^<checkpoint node="([^"]+)" summary="([^"]+)">\s*$'
)
_RE_CHECKPOINT_CLOSE = re.compile(r'^</checkpoint>\s*$')
_RE_ROUTE = re.compile(
    r'^<route(?: if="([^"]+)")? target="([^"]+)"/>\s*$'
)
_RE_BRIDGE = re.compile(r'^<bridge\s*/>\s*$')
_RE_BRANCH_OPEN = re.compile(r'^<branch name="([^"]+)">\s*$')
_RE_BRANCH_CLOSE = re.compile(r'^</branch>\s*$')


class StreamingXmlParser:
    """Line-by-line streaming parser for NNN| line-numbered XML output.

    Usage:
        parser = StreamingXmlParser()
        for line in response.splitlines():
            for event in parser.feed_line(line):
                handle(event)
        result = parser.get_result()
    """

    def __init__(self):
        # State machine
        self._in_story = False
        self._in_branch: str | None = None       # current branch name
        self._in_checkpoint = False
        self._in_choice: str | None = None       # current choice id
        self._post_bridge = False
        self._bridge_seen = False

        # Pre-processor indices (structural mapping)
        self._branch_ranges: dict[str, tuple[int, int]] = {}
        self._branch_start_line: dict[str, int] = {}
        self._format_errors: list[str] = []

        # Accumulated structured data
        self._segments: list[Segment] = []
        self._choices: list[dict] = []
        self._sets: list[SetOperation] = []
        self._checkpoint_node: str | None = None
        self._checkpoint_summary: str | None = None
        self._routes: list[RouteTarget] = []
        self._pre_branches: list[str] = []
        self._post_branches: list[str] = []
        self._bridge_text_segments: list[str] = []
        self._line_count = 0
        self._seg_count = 0

    # ── Public API ──────────────────────────────────────────────────

    def feed_line(self, line: str) -> list[ParseEvent]:
        """Process one line and return any events it generates.

        Args:
            line: Raw line from LLM output (may include NNN|  prefix).

        Returns:
            List of ParseEvent objects (may be empty if the line is
            whitespace or a comment).
        """
        # Strip line number prefix
        clean = re.sub(r'^\d{3}\| ', '', line).strip()
        if not clean:
            return []

        # Skip XML comments
        if clean.startswith('<!--'):
            return []

        self._line_count += 1
        events: list[ParseEvent] = []

        # ── Container open/close ────────────────────────────────────
        m = _RE_STORY_OPEN.match(clean)
        if m:
            self._in_story = True
            events.append(ParseEvent(type=EventType.STORY_BEGIN, line_number=self._line_count))
            return events

        m = _RE_STORY_CLOSE.match(clean)
        if m:
            self._in_story = False
            events.append(ParseEvent(type=EventType.STORY_END, line_number=self._line_count))
            return events

        if not self._in_story:
            return events

        m = _RE_CHOICE_OPEN.match(clean)
        if m:
            self._in_choice = m.group(1)
            return [ParseEvent(
                type=EventType.CHOICE_BEGIN,
                choice_id=m.group(1),
                line_number=self._line_count,
                position="pre" if not self._post_bridge else "post",
            )]

        m = _RE_CHOICE_CLOSE.match(clean)
        if m:
            self._in_choice = None
            return [ParseEvent(
                type=EventType.CHOICE_END,
                line_number=self._line_count,
                position="pre" if not self._post_bridge else "post",
            )]

        m = _RE_CHECKPOINT_OPEN.match(clean)
        if m:
            self._in_checkpoint = True
            self._checkpoint_node = m.group(1)
            self._checkpoint_summary = m.group(2)
            return [ParseEvent(
                type=EventType.CHECKPOINT,
                cp_node=m.group(1),
                cp_summary=m.group(2),
                line_number=self._line_count,
                position="pre" if not self._post_bridge else "post",
            )]

        m = _RE_CHECKPOINT_CLOSE.match(clean)
        if m:
            self._in_checkpoint = False
            return [ParseEvent(
                type=EventType.CHECKPOINT_END,
                line_number=self._line_count,
                position="pre" if not self._post_bridge else "post",
            )]

        m = _RE_BRANCH_OPEN.match(clean)
        if m:
            branch_name = m.group(1)
            self._in_branch = branch_name
            self._branch_start_line[branch_name] = self._line_count
            pos = "post" if self._post_bridge else "pre"
            if self._post_bridge:
                self._post_branches.append(branch_name)
            else:
                self._pre_branches.append(branch_name)
            return [ParseEvent(
                type=EventType.BRANCH_ENTER,
                branch_name=branch_name,
                line_number=self._line_count,
                position=pos,
            )]

        m = _RE_BRANCH_CLOSE.match(clean)
        if m:
            if self._in_branch:
                self._branch_ranges[self._in_branch] = (
                    self._branch_start_line.get(self._in_branch, 0),
                    self._line_count,
                )
            branch_name = self._in_branch
            self._in_branch = None
            return [ParseEvent(
                type=EventType.BRANCH_EXIT,
                branch_name=branch_name,
                line_number=self._line_count,
                position="post" if self._post_bridge else "pre",
            )]

        # ── Bridge ──────────────────────────────────────────────────
        m = _RE_BRIDGE.match(clean)
        if m:
            self._bridge_seen = True
            self._post_bridge = True
            return [ParseEvent(
                type=EventType.BRIDGE,
                line_number=self._line_count,
            )]

        # ── Leaf elements ───────────────────────────────────────────
        m = _RE_SEG.match(clean)
        if m:
            text = m.group(1).strip()
            self._seg_count += 1
            pos = "post" if self._post_bridge else "pre"
            seg = Segment(
                n=self._seg_count,
                text=text,
                position=pos,
                branch=self._in_branch,
            )
            self._segments.append(seg)

            # Collect bridge_text for the in-branch segs
            if self._post_bridge:
                self._bridge_text_segments.append(text)

            return [ParseEvent(
                type=EventType.SEGMENT,
                text=text,
                line_number=self._line_count,
                position=pos,
            )]

        m = _RE_OPT.match(clean)
        if m:
            key = m.group(1)
            branch = m.group(2)
            if_cond = m.group(3) if m.lastindex and m.lastindex >= 3 else None
            text = m.group(m.lastindex).strip() if m.lastindex else ""
            if self._in_choice is not None:
                self._choices.append({
                    "id": self._in_choice,
                    "branches": [branch],
                    "labels": [text],
                })
            return [ParseEvent(
                type=EventType.OPT,
                opt_key=key,
                opt_branch=branch,
                opt_if=if_cond,
                text=text,
                line_number=self._line_count,
                position="pre" if not self._post_bridge else "post",
            )]

        m = _RE_SET.match(clean)
        if m:
            var = m.group(1)
            op = m.group(2)
            val = m.group(3)
            if_cond = m.group(4) if m.lastindex and m.lastindex >= 4 else None
            set_op = SetOperation(var=var, op=op, val=val, condition=if_cond)
            self._sets.append(set_op)

            # Post-bridge check
            if self._post_bridge:
                self._format_errors.append(
                    f"<set> found after <bridge/> (line {self._line_count})"
                )

            return [ParseEvent(
                type=EventType.SET,
                set_var=var,
                set_op=op,
                set_val=val,
                set_if=if_cond,
                line_number=self._line_count,
                position="post" if self._post_bridge else "pre",
            )]

        m = _RE_ROUTE.match(clean)
        if m:
            if_cond = m.group(1)
            target = m.group(2)
            self._routes.append(RouteTarget(condition=if_cond, target=target))
            return [ParseEvent(
                type=EventType.ROUTE,
                route_if=if_cond,
                route_target=target,
                line_number=self._line_count,
                position="pre" if not self._post_bridge else "post",
            )]

        # Unrecognized line
        if self._post_bridge:
            # After bridge: check for prohibited elements
            for tag in ("choice", "set", "checkpoint"):
                if f"<{tag}" in clean:
                    self._format_errors.append(
                        f"<{tag}> found after <bridge/> (line {self._line_count})"
                    )

        return events

    def get_result(self) -> ParsedOutput:
        """Build ParsedOutput from accumulated data.

        Returns a ParsedOutput compatible with the existing XmlParser
        interface, suitable for Display and observer usage.
        """
        pre_segments = sum(1 for s in self._segments if s.position == "pre")
        post_segments = sum(1 for s in self._segments if s.position == "post")

        # Consolidate choices (group opts by choice id)
        consolidated: list[dict] = []
        seen_ids: set[str] = set()
        for c in self._choices:
            cid = c["id"]
            if cid not in seen_ids:
                seen_ids.add(cid)
                consolidated.append(c)

        # Build choice data from opts
        choice_data: list[dict] = []
        choice_id_final: str | None = None
        opt_branches: list[str] = []

        # Re-derive choices from accumulated data
        # (populated from OPT events; consolidated above)
        if consolidated:
            choice_id_final = consolidated[-1]["id"]
            for c in consolidated:
                branches = [o.get("branches", [None])[0]
                           for o in self._choices if o["id"] == c["id"]]
                labels = [o.get("labels", [""])[0]
                         for o in self._choices if o["id"] == c["id"]]
                choice_data.append({
                    "id": c["id"],
                    "branches": branches,
                    "labels": labels,
                })
                opt_branches.extend(branches)

        return ParsedOutput(
            segments=list(self._segments),
            total_segments=len(self._segments),
            pre_segments=pre_segments,
            post_segments=post_segments,
            choice_id=choice_id_final,
            opt_branches=opt_branches,
            choices=choice_data,
            sets=list(self._sets),
            checkpoint_node=self._checkpoint_node,
            checkpoint_summary=self._checkpoint_summary,
            routes=list(self._routes),
            bridge_found=self._bridge_seen,
            bridge_text="\n".join(self._bridge_text_segments),
            numbering_issues=[],
            pre_branches=list(self._pre_branches),
            post_branches=list(self._post_branches),
        )

    @property
    def format_errors(self) -> list[str]:
        """Format errors detected during parsing."""
        return list(self._format_errors)

    @property
    def branch_ranges(self) -> dict[str, tuple[int, int]]:
        """Structural index: branch name → (start_line, end_line)."""
        return dict(self._branch_ranges)

    @property
    def bridge_seen(self) -> bool:
        return self._bridge_seen
