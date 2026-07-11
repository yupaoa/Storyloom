"""Line-by-line streaming parser for XML narrative output.

Processes LLM output as a stream of lines rather than requiring a complete
XML document.  Yields ``ParseEvent`` objects as it encounters elements;
the caller (GameLoop) consumes events to drive display, state updates, and
user interaction.

Single-pass architecture: one ``feed_line()`` call per line, no
pre-processor step.  Dual-line processing (pre-processor indices +
independent consumer) was considered but is unnecessary at current scale
(2-4 branches, ~200 segments); see plan for analysis.

Usage::

    parser = StreamingXmlParser()
    for line in lines:
        for event in parser.feed_line(line):
            handle(event)
    result = parser.get_result()
"""

import re
from dataclasses import dataclass, field
from enum import Enum, auto


# ── Shared data types ─────────────────────────────────────────────
# Owned by the streaming parser (the canonical parser).  xml_parser.py
# imports these from here so the file can be deleted safely later.


class ParseError(Exception):
    """Raised when XML output is malformed or violates rules."""
    pass


@dataclass
class Segment:
    """A single narrative segment."""
    n: int
    text: str
    position: str  # "pre" or "post"
    branch: str | None = None


@dataclass
class SetOperation:
    """A state change operation."""
    var: str
    op: str
    val: str
    condition: str | None = None


@dataclass
class RouteTarget:
    """A checkpoint route target."""
    condition: str | None
    target: str


@dataclass
class ParsedOutput:
    """Structured result of parsing LLM XML output."""
    segments: list[Segment] = field(default_factory=list)
    total_segments: int = 0
    pre_segments: int = 0
    post_segments: int = 0
    choice_id: str | None = None        # deprecated: use choices[-1]["id"]
    opt_branches: list[str] = field(default_factory=list)  # deprecated
    choices: list[dict] = field(default_factory=list)  # [{"id": str, "branches": [str]}]
    sets: list[SetOperation] = field(default_factory=list)
    checkpoint_node: str | None = None
    checkpoint_summary: str | None = None
    routes: list[RouteTarget] = field(default_factory=list)
    bridge_found: bool = False
    bridge_text: str = ""
    numbering_issues: list[str] = field(default_factory=list)
    pre_branches: list[str] = field(default_factory=list)
    post_branches: list[str] = field(default_factory=list)


# ── Event types ───────────────────────────────────────────────────


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
    # BRANCH_ENTER / SEGMENT
    branch_name: str | None = None
    # PARSE_ERROR
    error_msg: str | None = None
    # Position
    line_number: int = 0
    position: str = "pre"             # "pre" or "post" (bridge relative)


# ── Line regex patterns ───────────────────────────────────────────
# Each line may start with NNN|  (line-number prefix), which is
# stripped before matching.

_RE_STORY_OPEN = re.compile(r'^<story>\s*$')
_RE_STORY_CLOSE = re.compile(r'^</story>\s*$')
_RE_SEG = re.compile(r'^<seg(?: n="(\d+)")?>(.*)</seg>\s*$')
_RE_CHOICE_OPEN = re.compile(r'^<choice id="([^"]+)">\s*$')
_RE_CHOICE_CLOSE = re.compile(r'^</choice>\s*$')
_RE_OPT = re.compile(
    r'^<opt key="(\d+)" branch="([^"]+)"(?: if="([^"]+)")?>(.*)</opt>\s*$'
)
_RE_SET = re.compile(
    r'^<set var="([^"]+)" op="([^"]+)" val="([^"]+)"'
    r'(?: if="([^"]+)")?\s*/>\s*$'
)
_RE_CHECKPOINT_OPEN = re.compile(
    r'^<checkpoint node="([^"]+)" summary="([^"]+)">\s*$'
)
_RE_CHECKPOINT_SELF_CLOSE = re.compile(
    r'^<checkpoint node="([^"]+)" summary="([^"]+)"\s*/>\s*$'
)
_RE_CHECKPOINT_CLOSE = re.compile(r'^</checkpoint>\s*$')
_RE_ROUTE = re.compile(
    r'^<route(?: if="([^"]+)")? target="([^"]+)"/>\s*$'
)
_RE_BRIDGE = re.compile(r'^<bridge\s*/>\s*$')
_RE_BRANCH_OPEN = re.compile(r'^<branch name="([^"]+)">\s*$')
_RE_BRANCH_CLOSE = re.compile(r'^</branch>\s*$')


class StreamingXmlParser:
    """Line-by-line streaming parser for XML narrative output.

    Maintains a lightweight state machine (tracking current container:
    story / branch / checkpoint / choice) and recognises element types
    line by line to produce ``ParseEvent`` objects.

    ``get_result()`` returns a ``ParsedOutput`` dataclass compatible
    with the existing ``XmlParser.parse()`` interface.
    """

    def __init__(self):
        # ── State machine ──────────────────────────────────────────
        self._in_story = False
        self._in_branch: str | None = None
        self._in_checkpoint = False
        self._in_choice: str | None = None
        self._post_bridge = False
        self._bridge_seen = False

        # ── Format errors ──────────────────────────────────────────
        self._format_errors: list[str] = []

        # ── Accumulated structured data ────────────────────────────
        self._segments: list[Segment] = []
        self._pending_choices: list[dict] = []  # [{id, branches, labels, conditions}]
        self._sets: list[SetOperation] = []
        self._checkpoint_node: str | None = None
        self._checkpoint_summary: str | None = None
        self._routes: list[RouteTarget] = []
        self._pre_branches: list[str] = []
        self._post_branches: list[str] = []
        self._bridge_text_items: list[tuple[str, str | None]] = []  # (text, branch_name)
        self._line_count = 0
        self._seg_count = 0

    # ── Public API ──────────────────────────────────────────────────

    def feed_line(self, line: str) -> list[ParseEvent]:
        """Process one line and return any events it generates.

        Args:
            line: Raw line from LLM output (may include ``NNN| `` prefix).

        Returns:
            List of ``ParseEvent`` objects (may be empty for whitespace
            or comments).
        """
        # Strip line-number prefix (NNN| )
        clean = re.sub(r'^\d{3}\| ', '', line).strip()
        if not clean:
            return []

        # Skip XML comments
        if clean.startswith('<!--'):
            return []

        self._line_count += 1

        # ── Container open/close ────────────────────────────────────
        if _RE_STORY_OPEN.match(clean):
            self._in_story = True
            return [ParseEvent(type=EventType.STORY_BEGIN,
                               line_number=self._line_count)]

        if _RE_STORY_CLOSE.match(clean):
            self._in_story = False
            return [ParseEvent(type=EventType.STORY_END,
                               line_number=self._line_count)]

        if not self._in_story:
            return []

        m = _RE_CHOICE_OPEN.match(clean)
        if m:
            self._in_choice = m.group(1)
            if self._post_bridge:
                self._format_errors.append(
                    f"<choice> found after <bridge/> (line {self._line_count})"
                )
            return [ParseEvent(type=EventType.CHOICE_BEGIN,
                               choice_id=m.group(1),
                               line_number=self._line_count,
                               position=self._position)]

        if _RE_CHOICE_CLOSE.match(clean):
            self._in_choice = None
            return [ParseEvent(type=EventType.CHOICE_END,
                               line_number=self._line_count,
                               position=self._position)]

        m = _RE_CHECKPOINT_OPEN.match(clean)
        if m:
            self._in_checkpoint = True
            self._checkpoint_node = m.group(1)
            self._checkpoint_summary = m.group(2)
            if self._post_bridge:
                self._format_errors.append(
                    f"<checkpoint> found after <bridge/>"
                    f" (line {self._line_count})"
                )
            return [ParseEvent(type=EventType.CHECKPOINT,
                               cp_node=m.group(1),
                               cp_summary=m.group(2),
                               line_number=self._line_count,
                               position=self._position)]

        m = _RE_CHECKPOINT_SELF_CLOSE.match(clean)
        if m:
            self._checkpoint_node = m.group(1)
            self._checkpoint_summary = m.group(2)
            if self._post_bridge:
                self._format_errors.append(
                    f"<checkpoint> found after <bridge/>"
                    f" (line {self._line_count})"
                )
            return [ParseEvent(type=EventType.CHECKPOINT,
                               cp_node=m.group(1),
                               cp_summary=m.group(2),
                               line_number=self._line_count,
                               position=self._position)]

        if _RE_CHECKPOINT_CLOSE.match(clean):
            self._in_checkpoint = False
            return [ParseEvent(type=EventType.CHECKPOINT_END,
                               line_number=self._line_count,
                               position=self._position)]

        m = _RE_BRANCH_OPEN.match(clean)
        if m:
            branch_name = m.group(1)
            self._in_branch = branch_name
            pos = self._position
            if self._post_bridge:
                self._post_branches.append(branch_name)
            else:
                self._pre_branches.append(branch_name)
            return [ParseEvent(type=EventType.BRANCH_ENTER,
                               branch_name=branch_name,
                               line_number=self._line_count,
                               position=pos)]

        if _RE_BRANCH_CLOSE.match(clean):
            branch_name = self._in_branch
            self._in_branch = None
            return [ParseEvent(type=EventType.BRANCH_EXIT,
                               branch_name=branch_name,
                               line_number=self._line_count,
                               position=self._position)]

        # ── Bridge ──────────────────────────────────────────────────
        if _RE_BRIDGE.match(clean):
            self._bridge_seen = True
            self._post_bridge = True
            return [ParseEvent(type=EventType.BRIDGE,
                               line_number=self._line_count)]

        # ── Leaf elements ───────────────────────────────────────────
        m = _RE_SEG.match(clean)
        if m:
            n_val = m.group(1)  # None if no n="N" attribute
            text = m.group(2).strip()
            self._seg_count += 1
            seg_n = int(n_val) if n_val else self._seg_count
            pos = self._position

            seg = Segment(n=seg_n, text=text, position=pos,
                          branch=self._in_branch)
            self._segments.append(seg)

            if self._post_bridge:
                self._bridge_text_items.append((text, self._in_branch))

            return [ParseEvent(type=EventType.SEGMENT, text=text,
                               branch_name=self._in_branch,
                               line_number=self._line_count,
                               position=pos)]

        m = _RE_OPT.match(clean)
        if m:
            key = m.group(1)       # "1", "2", ...
            branch = m.group(2)
            if_cond = m.group(3)   # None if no if="..." attribute
            text = m.group(4).strip()

            # Accumulate into pending choices (not post-hoc consolidation)
            if self._in_choice is not None:
                pending = self._pending_choices
                if not pending or pending[-1]["id"] != self._in_choice:
                    pending.append({
                        "id": self._in_choice,
                        "branches": [],
                        "labels": [],
                        "conditions": {},
                    })
                pending[-1]["branches"].append(branch)
                pending[-1]["labels"].append(text)
                if if_cond:
                    pending[-1]["conditions"][branch] = if_cond

            return [ParseEvent(type=EventType.OPT, text=text,
                               opt_key=key, opt_branch=branch,
                               opt_if=if_cond,
                               line_number=self._line_count,
                               position=self._position)]

        m = _RE_SET.match(clean)
        if m:
            var = m.group(1)
            op = m.group(2)
            val = m.group(3)
            if_cond = m.group(4)  # None if no if="..."

            set_op = SetOperation(var=var, op=op, val=val,
                                  condition=if_cond)
            self._sets.append(set_op)

            if self._post_bridge:
                self._format_errors.append(
                    f"<set> found after <bridge/> (line {self._line_count})"
                )

            return [ParseEvent(type=EventType.SET,
                               set_var=var, set_op=op, set_val=val,
                               set_if=if_cond,
                               line_number=self._line_count,
                               position=self._position)]

        m = _RE_ROUTE.match(clean)
        if m:
            if_cond = m.group(1)  # None if no if="..."
            target = m.group(2)
            self._routes.append(RouteTarget(condition=if_cond,
                                            target=target))
            return [ParseEvent(type=EventType.ROUTE,
                               route_if=if_cond, route_target=target,
                               line_number=self._line_count,
                               position=self._position)]

        # ── Unrecognized line ───────────────────────────────────────
        if self._post_bridge:
            for tag in ("choice", "set", "checkpoint"):
                if f"<{tag}" in clean:
                    self._format_errors.append(
                        f"<{tag}> found after <bridge/>"
                        f" (line {self._line_count})"
                    )

        return []

    def get_result(self) -> ParsedOutput:
        """Build ``ParsedOutput`` from accumulated data.

        Returns a ``ParsedOutput`` compatible with the existing
        ``XmlParser.parse()`` interface.
        """
        pre_segments = sum(1 for s in self._segments
                           if s.position == "pre")
        post_segments = sum(1 for s in self._segments
                            if s.position == "post")

        # Build backward-compat fields from pending_choices
        choice_id: str | None = None
        opt_branches: list[str] = []
        if self._pending_choices:
            last = self._pending_choices[-1]
            choice_id = last["id"]
            for pc in self._pending_choices:
                opt_branches.extend(pc["branches"])

        return ParsedOutput(
            segments=list(self._segments),
            total_segments=len(self._segments),
            pre_segments=pre_segments,
            post_segments=post_segments,
            choice_id=choice_id,
            opt_branches=opt_branches,
            choices=list(self._pending_choices),
            sets=list(self._sets),
            checkpoint_node=self._checkpoint_node,
            checkpoint_summary=self._checkpoint_summary,
            routes=list(self._routes),
            bridge_found=self._bridge_seen,
            bridge_text="\n".join(t for t, _ in self._bridge_text_items),
            numbering_issues=[],
            pre_branches=list(self._pre_branches),
            post_branches=list(self._post_branches),
        )

    def get_bridge_text(self, branch_name: str | None = None) -> str:
        """Extract bridge text, optionally filtered by branch.

        Per block-spec.md §4, bare ``<seg>`` elements (no enclosing
        ``<branch>``) are the implicit "main" branch and are always
        included.  ``<seg>`` elements inside ``<branch name=\"X\">`` are
        included only when *branch_name* is ``None`` (no filter) or
        matches *branch_name*.

        Args:
            branch_name: If not ``None``, only include text from the
                         matching ``<branch>`` (plus bare ``<seg>``).

        Returns:
            Filtered bridge text string.
        """
        if branch_name is None:
            return "\n".join(t for t, _ in self._bridge_text_items)
        texts: list[str] = []
        for text, br in self._bridge_text_items:
            if br is None or br == branch_name:
                texts.append(text)
        return "\n".join(texts)

    # ── Properties ──────────────────────────────────────────────────

    @property
    def _position(self) -> str:
        """Current position relative to bridge."""
        return "post" if self._post_bridge else "pre"

    @property
    def format_errors(self) -> list[str]:
        """Format errors detected during parsing (post-bridge prohibited
        elements, etc.)."""
        return list(self._format_errors)

    @property
    def bridge_seen(self) -> bool:
        """Whether ``<bridge/>`` has been encountered."""
        return self._bridge_seen


# ── LineBuffer ────────────────────────────────────────────────────


class LineBuffer:
    """Accumulates token chunks and yields complete lines.

    The API streams individual tokens (sub-word chunks).  The streaming
    parser needs complete lines delimited by ``\\n``.  This adapter sits
    between the token stream and the parser.

    Usage::

        lb = LineBuffer()
        for chunk in api_stream:
            for line in lb.feed(chunk):
                process(line)
        remaining = lb.flush()
        if remaining:
            process(remaining)
    """

    def __init__(self):
        self._buffer: str = ""

    def feed(self, text: str) -> list[str]:
        """Feed a token chunk; return any completed lines.

        Lines are stripped of leading / trailing whitespace.  Empty
        lines are omitted from the return list.
        """
        self._buffer += text
        if "\n" not in self._buffer:
            return []

        # Split on newline.  The last element is either an incomplete
        # line (buffer didn't end with \n) or empty (buffer ended with
        # \n).
        parts = self._buffer.split("\n")
        if text.endswith("\n"):
            self._buffer = ""
            complete = parts
        else:
            self._buffer = parts[-1]
            complete = parts[:-1]

        return [s.strip() for s in complete if s.strip()]

    def flush(self) -> str | None:
        """Return any remaining buffered text (end-of-stream).

        Returns ``None`` if the buffer is empty.
        """
        if self._buffer:
            result = self._buffer.strip()
            self._buffer = ""
            return result if result else None
        return None
