# 对话式 Prompt 架构 — 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 实现基于 messages 数组的对话式 Prompt 架构（Round 1 锚定 + 滑动窗口 + checkpoint 压缩），替换当前每轮独立 system prompt 方案。

**架构：** 新建 `ContextManager` 管理 messages 数组、滑动窗口和压缩逻辑；新建 `PromptBuilder` 构建 Round 1 和 Round N 消息；新建 `XmlParser` 解析 LLM XML 输出并提取 bridge_text。每个模块独立可测试。

**技术栈：** Python 3（标准库优先），xml.etree.ElementTree，pytest

---

## 文件结构

| 文件 | 职责 | 状态 |
|------|------|------|
| `src/storyloom/__init__.py` | 包初始化 | 新建 |
| `src/storyloom/config.py` | 可配置常量（窗口大小、段数范围等） | 新建 |
| `src/storyloom/context_manager.py` | messages 数组管理、滑动窗口、压缩 | 新建 |
| `src/storyloom/prompt_builder.py` | 组装 Round 1 和 Round N 消息内容 | 新建 |
| `src/storyloom/xml_parser.py` | 解析 LLM XML 输出，提取结构化数据 | 新建 |
| `tests/test_context_manager.py` | ContextManager 单元测试 | 新建 |
| `tests/test_prompt_builder.py` | PromptBuilder 单元测试 | 新建 |
| `tests/test_xml_parser.py` | XmlParser 单元测试 | 新建 |

---

### 任务 1：创建项目骨架

**文件：**
- 创建：`src/storyloom/__init__.py`
- 创建：`src/storyloom/config.py`

- [ ] **步骤 1：创建包初始化文件**

```bash
mkdir -p src/storyloom
```

```python
# src/storyloom/__init__.py
"""Storyloom — AI-powered interactive text fiction game engine."""
```

- [ ] **步骤 2：创建配置常量模块**

```python
# src/storyloom/config.py
"""Configurable constants for Storyloom."""

# ── Sliding window ─────────────────────────────────────────────
WINDOW_SIZE = 3          # full rounds to keep in window
FIRST_COMPRESSION_AT = 5  # round number to trigger first compression

# ── Segment ranges ────────────────────────────────────────────
SEGMENTS_PER_ROUND_MIN = 60
SEGMENTS_PER_ROUND_MAX = 120
SEGMENTS_HARD_CAP = 120

# ── Bridge ─────────────────────────────────────────────────────
BRIDGE_POSITION_RATIO = 0.5  # target bridge position (fraction of total)
MIN_TAIL_SEGMENTS = 15       # minimum segments per branch after bridge

# ── Context budget ────────────────────────────────────────────
MAX_CONTEXT_TOKENS = 50_000   # target ceiling

# ── API defaults ──────────────────────────────────────────────
DEFAULT_MODEL = "deepseek-chat"
STREAM_STALL_TIMEOUT_SEC = 60
```

- [ ] **步骤 3：Commit**

```bash
git add src/storyloom/__init__.py src/storyloom/config.py
git commit -m "feat: add project skeleton with config constants"
```

---

### 任务 2：实现 XmlParser — 解析 LLM XML 输出

**文件：**
- 创建：`tests/test_xml_parser.py`
- 创建：`src/storyloom/xml_parser.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_xml_parser.py
"""Tests for xml_parser module."""

import pytest
from src.storyloom.xml_parser import XmlParser, ParsedOutput, ParseError


VALID_XML = """<story>
<seg n="1">炉火在石砌的壁炉里噼啪作响。</seg>
<seg n="2">旅店老板: 这么晚了还赶路？</seg>
<choice id="approach">
  <opt key="A" branch="take_lead">先开口</opt>
  <opt key="B" branch="wait">保持沉默</opt>
</choice>
<set var="声望" op="+" val="5" if="approach==1"/>
<checkpoint node="ch2_meeting" summary="在旅店接头。">
  <route if="approach==1" target="ch3_lead"/>
</checkpoint>
<bridge/>
<branch name="take_lead">
<seg n="3">你在他对面坐下。</seg>
</branch>
<branch name="wait">
<seg n="4">你站着没动。</seg>
</branch>
</story>"""


class TestXmlParser:
    def test_parse_valid_xml_returns_parsed_output(self):
        result = XmlParser.parse(VALID_XML)
        assert isinstance(result, ParsedOutput)

    def test_parse_extracts_choice_id(self):
        result = XmlParser.parse(VALID_XML)
        assert result.choice_id == "approach"

    def test_parse_extracts_opt_branches(self):
        result = XmlParser.parse(VALID_XML)
        assert result.opt_branches == ["take_lead", "wait"]

    def test_parse_extracts_set_operations(self):
        result = XmlParser.parse(VALID_XML)
        assert len(result.sets) == 1
        assert result.sets[0].var == "声望"
        assert result.sets[0].op == "+"
        assert result.sets[0].val == "5"
        assert result.sets[0].condition == "approach==1"

    def test_parse_extracts_checkpoint_node(self):
        result = XmlParser.parse(VALID_XML)
        assert result.checkpoint_node == "ch2_meeting"
        assert result.checkpoint_summary == "在旅店接头。"

    def test_parse_extracts_route_targets(self):
        result = XmlParser.parse(VALID_XML)
        assert len(result.routes) == 1
        assert result.routes[0].target == "ch3_lead"

    def test_parse_finds_exactly_one_bridge(self):
        result = XmlParser.parse(VALID_XML)
        assert result.bridge_found is True

    def test_parse_counts_segments(self):
        result = XmlParser.parse(VALID_XML)
        assert result.total_segments == 4

    def test_parse_extracts_bridge_text(self):
        result = XmlParser.parse(VALID_XML)
        assert "你在他对面坐下" in result.bridge_text
        assert "你站着没动" in result.bridge_text

    def test_parse_preserves_segment_order(self):
        result = XmlParser.parse(VALID_XML)
        numbers = [s.n for s in result.segments]
        assert numbers == [1, 2, 3, 4]

    def test_parse_rejects_missing_story_tag(self):
        with pytest.raises(ParseError, match="Missing <story>"):
            XmlParser.parse("<seg n='1'>text</seg>")

    def test_parse_rejects_multiple_bridges(self):
        xml = VALID_XML.replace("<bridge/>", "<bridge/><bridge/>", 1)
        with pytest.raises(ParseError, match="Multiple <bridge/>"):
            XmlParser.parse(xml)

    def test_parse_rejects_missing_bridge(self):
        xml = VALID_XML.replace("<bridge/>", "")
        with pytest.raises(ParseError, match="No <bridge/>"):
            XmlParser.parse(xml)

    def test_parse_rejects_post_bridge_prohibited_elements(self):
        xml = VALID_XML.replace(
            "</branch>",
            "</branch><choice id='x'><opt key='A' branch='b'>o</opt></choice>",
            1
        )
        with pytest.raises(ParseError, match="Prohibited"):
            XmlParser.parse(xml)

    def test_extract_bridge_text_strips_xml_tags(self):
        result = XmlParser.parse(VALID_XML)
        assert "<seg" not in result.bridge_text
        assert "<branch" not in result.bridge_text

    def test_parse_handles_no_choice(self):
        xml = VALID_XML.replace(
            "<choice id=\"approach\">\n  <opt key=\"A\" branch=\"take_lead\">先开口</opt>\n  <opt key=\"B\" branch=\"wait\">保持沉默</opt>\n</choice>\n",
            ""
        )
        result = XmlParser.parse(xml)
        assert result.choice_id is None
        assert result.opt_branches == []

    def test_parse_extracts_pre_bridge_segments(self):
        result = XmlParser.parse(VALID_XML)
        pre_segs = [s for s in result.segments if s.position == "pre"]
        assert len(pre_segs) == 2

    def test_parse_handles_unordered_seg_numbers(self):
        xml = VALID_XML.replace('n="3"', 'n="5"')
        result = XmlParser.parse(xml)
        # seg numbers are preserved as-is; ordering is reported but not enforced
        assert result.numbering_issues  # non-sequential
```

- [ ] **步骤 2：运行测试验证失败**

```bash
python3 -m pytest tests/test_xml_parser.py -v
```
预期：全部 FAIL（模块不存在）

- [ ] **步骤 3：实现 XmlParser**

```python
# src/storyloom/xml_parser.py
"""Parse LLM XML output into structured data."""

import re
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET


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
    choice_id: str | None = None
    opt_branches: list[str] = field(default_factory=list)
    sets: list[SetOperation] = field(default_factory=list)
    checkpoint_node: str | None = None
    checkpoint_summary: str | None = None
    routes: list[RouteTarget] = field(default_factory=list)
    bridge_found: bool = False
    bridge_text: str = ""
    numbering_issues: list[str] = field(default_factory=list)
    pre_branches: list[str] = field(default_factory=list)
    post_branches: list[str] = field(default_factory=list)
    parse_error: str | None = None


class XmlParser:
    """Parse LLM XML narrative output."""

    PROHIBITED_POST_BRIDGE = {"choice", "set", "checkpoint"}

    @staticmethod
    def parse(text: str) -> ParsedOutput:
        """Parse LLM output text into ParsedOutput.

        Args:
            text: Raw LLM output, may contain markdown fences.

        Returns:
            ParsedOutput with structured data.

        Raises:
            ParseError: If XML is malformed or violates rules.
        """
        xml_str = XmlParser._extract_xml(text)
        if xml_str is None:
            raise ParseError("No XML content found")

        root = XmlParser._parse_xml(xml_str)
        children = list(root)

        # Find bridge
        bridge_idx = XmlParser._find_bridge(children)

        pre_children = children[:bridge_idx]
        post_children = children[bridge_idx + 1:]

        result = ParsedOutput()
        result.bridge_found = True

        # Check post-bridge prohibited
        prohibited = []
        for el in post_children:
            if el.tag in XmlParser.PROHIBITED_POST_BRIDGE:
                prohibited.append(el.tag)
        if prohibited:
            raise ParseError(
                f"Prohibited elements after bridge: {', '.join(prohibited)}"
            )

        # Collect segments
        XmlParser._collect_segments(pre_children, "pre", result)
        XmlParser._collect_segments(post_children, "post", result)
        result.total_segments = len(result.segments)
        result.pre_segments = sum(1 for s in result.segments if s.position == "pre")
        result.post_segments = sum(1 for s in result.segments if s.position == "post")

        # Check numbering
        numbers = [s.n for s in result.segments]
        if numbers:
            if numbers[0] != 1:
                result.numbering_issues.append(f"starts at {numbers[0]}")
            for i in range(1, len(numbers)):
                if numbers[i] <= numbers[i - 1]:
                    result.numbering_issues.append(
                        f"non-sequential: {numbers[i-1]}→{numbers[i]}"
                    )
                    break

        # Extract choice
        XmlParser._extract_choice(pre_children, result)

        # Extract sets
        XmlParser._extract_sets(root, result)

        # Extract checkpoint
        XmlParser._extract_checkpoint(pre_children, result)

        # Extract bridge text (all post-bridge text, stripped of XML)
        result.bridge_text = XmlParser._extract_bridge_text(post_children)

        return result

    @staticmethod
    def _extract_xml(text: str) -> str | None:
        """Extract XML from LLM output, removing markdown fences."""
        # Split on "---" separator in test output files
        parts = text.split('\n---\n', 1)
        llm_out = parts[1] if len(parts) > 1 else text

        # Strip markdown code fences
        llm_out = re.sub(r'^```(?:xml)?\s*\n', '', llm_out, flags=re.MULTILINE)
        llm_out = re.sub(r'\n```\s*$', '', llm_out)

        # Find <story>...</story>
        story_start = llm_out.find('<story>')
        story_end = llm_out.rfind('</story>')

        if story_start < 0:
            return None
        if story_end < 0:
            story_end = len(llm_out)
        else:
            story_end += len('</story>')

        xml_str = llm_out[story_start:story_end].strip()
        if not xml_str:
            return None

        # Fix unescaped ampersands
        xml_str = re.sub(
            r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)',
            '&amp;',
            xml_str
        )
        return xml_str

    @staticmethod
    def _parse_xml(xml_str: str) -> ET.Element:
        """Parse XML string into ElementTree."""
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError as e:
            raise ParseError(f"XML parse error: {e}")

        if root.tag != "story":
            raise ParseError(f"Root is <{root.tag}>, expected <story>")

        if not list(root):
            raise ParseError("Empty <story>")
        return root

    @staticmethod
    def _find_bridge(children: list[ET.Element]) -> int:
        """Find bridge index, raise on 0 or 2+."""
        bridge_indices = [
            i for i, el in enumerate(children) if el.tag == "bridge"
        ]
        if len(bridge_indices) == 0:
            raise ParseError("No <bridge/> found")
        if len(bridge_indices) > 1:
            raise ParseError("Multiple <bridge/> elements")
        return bridge_indices[0]

    @staticmethod
    def _collect_segments(
        children: list[ET.Element],
        position: str,
        result: ParsedOutput,
    ) -> None:
        """Collect <seg> elements from children, including nested in <branch>."""
        for el in children:
            if el.tag == "seg":
                n = int(el.get("n", 0))
                result.segments.append(
                    Segment(n=n, text=(el.text or "").strip(), position=position)
                )
            elif el.tag == "branch":
                branch_name = el.get("name", "")
                if position == "pre":
                    result.pre_branches.append(branch_name)
                else:
                    result.post_branches.append(branch_name)
                for seg_el in el.findall("seg"):
                    n = int(seg_el.get("n", 0))
                    result.segments.append(
                        Segment(
                            n=n,
                            text=(seg_el.text or "").strip(),
                            position=position,
                            branch=branch_name,
                        )
                    )

    @staticmethod
    def _extract_choice(
        pre_children: list[ET.Element],
        result: ParsedOutput,
    ) -> None:
        """Extract <choice> from pre-bridge children."""
        for el in pre_children:
            if el.tag == "choice":
                result.choice_id = el.get("id")
                for opt_el in el.findall("opt"):
                    result.opt_branches.append(opt_el.get("branch", ""))

    @staticmethod
    def _extract_sets(root: ET.Element, result: ParsedOutput) -> None:
        """Extract all <set> elements."""
        for el in root.iter("set"):
            result.sets.append(SetOperation(
                var=el.get("var", ""),
                op=el.get("op", ""),
                val=el.get("val", ""),
                condition=el.get("if"),
            ))

    @staticmethod
    def _extract_checkpoint(
        pre_children: list[ET.Element],
        result: ParsedOutput,
    ) -> None:
        """Extract <checkpoint> from pre-bridge children."""
        for el in pre_children:
            if el.tag == "checkpoint":
                result.checkpoint_node = el.get("node")
                result.checkpoint_summary = el.get("summary")
                for route_el in el.findall("route"):
                    result.routes.append(RouteTarget(
                        condition=route_el.get("if"),
                        target=route_el.get("target", ""),
                    ))

    @staticmethod
    def _extract_bridge_text(post_children: list[ET.Element]) -> str:
        """Extract plain text from post-bridge elements."""
        texts = []
        for el in post_children:
            if el.tag == "seg":
                if el.text:
                    texts.append(el.text.strip())
            elif el.tag == "branch":
                for seg_el in el.findall("seg"):
                    if seg_el.text:
                        texts.append(seg_el.text.strip())
        return "\n".join(texts)
```

- [ ] **步骤 4：运行测试验证通过**

```bash
python3 -m pytest tests/test_xml_parser.py -v
```
预期：全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add src/storyloom/xml_parser.py tests/test_xml_parser.py
git commit -m "feat: add XmlParser for LLM XML output parsing"
```

---

### 任务 3：实现 ContextManager — 消息数组与滑动窗口

**文件：**
- 创建：`tests/test_context_manager.py`
- 创建：`src/storyloom/context_manager.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_context_manager.py
"""Tests for context_manager module."""

from src.storyloom.context_manager import ContextManager
from src.storyloom.config import WINDOW_SIZE


class TestContextManagerInit:
    def test_initial_state_has_no_messages(self):
        cm = ContextManager()
        assert cm.round_count == 0
        assert len(cm.get_messages()) == 0

    def test_initial_state_has_no_compressed_rounds(self):
        cm = ContextManager()
        assert cm.get_compressed_rounds() == []

    def test_initial_state_window_is_empty(self):
        cm = ContextManager()
        assert cm.get_window_rounds() == []


class TestRound1Setup:
    def test_set_round1_stores_messages(self):
        cm = ContextManager()
        cm.set_round1(
            user_content="你是叙事引擎...",
            assistant_content="<story>...</story>",
        )
        assert cm.round_count == 1
        msgs = cm.get_messages()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_set_round1_raises_if_already_set(self):
        cm = ContextManager()
        cm.set_round1("prompt", "output")
        with pytest.raises(RuntimeError, match="Round 1 already set"):
            cm.set_round1("prompt2", "output2")

    def test_round1_messages_are_never_compressed(self):
        cm = ContextManager()
        cm.set_round1("prompt", "output")
        for _ in range(10):
            cm.add_round("ctx", "<story><bridge/><seg n='1'>t</seg></story>")
        msgs = cm.get_messages()
        assert msgs[0]["content"] == "prompt"
        assert msgs[1]["content"] == "output"


class TestAddRound:
    def test_add_round_increments_count(self):
        cm = ContextManager()
        cm.set_round1("prompt", "output")
        cm.add_round("Round 2 context", "<story><bridge/><seg n='1'>t</seg></story>")
        assert cm.round_count == 2

    def test_add_round_appends_user_message(self):
        cm = ContextManager()
        cm.set_round1("prompt", "output")
        cm.add_round("Round 2 context", "<story><bridge/><seg n='1'>t</seg></story>")
        msgs = cm.get_messages()
        user_messages = [m for m in msgs if m["role"] == "user"]
        assert any("Round 2 context" in m["content"] for m in user_messages)

    def test_add_round_raises_without_round1(self):
        cm = ContextManager()
        with pytest.raises(RuntimeError, match="Round 1 not set"):
            cm.add_round("ctx", "<story><bridge/><seg n='1'>t</seg></story>")


class TestSlidingWindow:
    def test_no_compression_before_threshold(self):
        cm = ContextManager()
        cm.set_round1("p", "o")
        cm.add_round("r2", "<story><bridge/><seg n='1'>t</seg></story>")
        cm.add_round("r3", "<story><bridge/><seg n='1'>t</seg></story>")
        cm.add_round("r4", "<story><bridge/><seg n='1'>t</seg></story>")
        assert cm.get_compressed_rounds() == []

    def test_compression_starts_at_round_5(self):
        cm = ContextManager()
        cm.set_round1("p", "o")
        cm.add_round("r2", "<story><checkpoint node='ch2' summary='接头'/><bridge/><seg n='1'>t</seg></story>")
        cm.add_round("r3", "<story><checkpoint node='ch3' summary='交易'/><bridge/><seg n='1'>t</seg></story>")
        cm.add_round("r4", "<story><bridge/><seg n='1'>t</seg></story>")
        cm.add_round("r5", "<story><bridge/><seg n='1'>t</seg></story>")
        compressed = cm.get_compressed_rounds()
        assert len(compressed) >= 1


class TestWindowRounds:
    def test_window_contains_last_n_rounds(self):
        cm = ContextManager()
        cm.set_round1("p", "o")
        for i in range(2, 8):
            cm.add_round(
                f"r{i}",
                "<story><bridge/><seg n='1'>t</seg></story>"
            )
        window = cm.get_window_rounds()
        assert len(window) <= WINDOW_SIZE


class TestCheckpointExtraction:
    def test_extract_checkpoint_summaries_from_output(self):
        cm = ContextManager()
        xml = (
            '<story>'
            '<checkpoint node="ch2" summary="在旅店接头。"/>'
            '<bridge/>'
            '<seg n="1">tail text</seg>'
            '</story>'
        )
        summaries = cm._extract_checkpoint_summaries(xml)
        assert "在旅店接头" in summaries

    def test_extract_returns_empty_for_no_checkpoint(self):
        cm = ContextManager()
        xml = '<story><bridge/><seg n="1">t</seg></story>'
        summaries = cm._extract_checkpoint_summaries(xml)
        assert summaries == ""


class TestCompressionFormat:
    def test_build_compression_message(self):
        cm = ContextManager()
        summaries = ["在旅店接头", "完成芯片交易", "选择信任耗子"]
        user_msg, asst_msg = cm._build_compression_messages(summaries)
        assert "已发生的主要事件" in user_msg
        assert "在旅店接头" in user_msg
        assert "完成芯片交易" in user_msg
        assert asst_msg == "（以上为已发生事件的摘要。当前故事继续推进。）"


class TestGetMessagesForRound:
    def test_returns_messages_array_for_api_call(self):
        cm = ContextManager()
        cm.set_round1("Round 1 prompt", "<story>...</story>")
        cm.add_round("r2 ctx", "<story><checkpoint node='c2' summary='接头'/><bridge/><seg n='1'>t</seg></story>")
        msgs = cm.get_messages()
        assert len(msgs) >= 2
        assert msgs[0]["role"] == "user"
        assert msgs[-1]["role"] == "user"  # last is current round context


class TestBridgeText:
    def test_bridge_text_is_stored_for_next_round(self):
        cm = ContextManager()
        cm.set_round1("p", "o")
        xml = (
            '<story>'
            '<bridge/>'
            '<seg n="1">你对耗子点了点头。</seg>'
            '<seg n="2">耗子: 跟我来。</seg>'
            '</story>'
        )
        cm.add_round("r2 context", xml)
        # bridge_text should be available for next round
        bridge = cm.get_last_bridge_text()
        assert "你对耗子点了点头" in bridge
        assert "耗子: 跟我来" in bridge
```

- [ ] **步骤 2：运行测试验证失败**

```bash
python3 -m pytest tests/test_context_manager.py -v
```
预期：全部 FAIL（模块不存在）

- [ ] **步骤 3：实现 ContextManager**

```python
# src/storyloom/context_manager.py
"""Manages conversation messages array with sliding window + compression."""

from src.storyloom.config import WINDOW_SIZE, FIRST_COMPRESSION_AT
from src.storyloom.xml_parser import XmlParser


class ContextManager:
    """Manages the messages array for conversation-based LLM interaction.

    Architecture:
      [0] Round 1 user (permanent anchor — format + story)
      [1] Round 1 assistant (permanent anchor — story opening)
      [... compressed rounds as user/assistant pair ...]
      [... last WINDOW_SIZE full rounds (user + assistant each) ...]
      [last] Current round user message

    Round 1 messages are NEVER removed or compressed.
    Rounds 2..N-WINDOW_SIZE-1 are compressed into checkpoint summaries.
    Rounds N-WINDOW_SIZE..N-1 are kept as full conversation history.
    """

    def __init__(self):
        self._round1_user: str | None = None
        self._round1_assistant: str | None = None
        self._rounds: list[dict] = []  # [{round_num, user_content, assistant_content}, ...]
        self._compressed_summaries: list[str] = []
        self._round_count: int = 0
        self._last_bridge_text: str = ""

    @property
    def round_count(self) -> int:
        return self._round_count

    def set_round1(self, user_content: str, assistant_content: str) -> None:
        """Set Round 1 messages (permanent anchor). Can only be called once.

        Args:
            user_content: Full Round 1 prompt (format spec + story context).
            assistant_content: LLM XML output from Round 1.
        """
        if self._round1_user is not None:
            raise RuntimeError("Round 1 already set")
        self._round1_user = user_content
        self._round1_assistant = assistant_content
        self._round_count = 1

    def add_round(self, user_content: str, assistant_content: str) -> None:
        """Add a new round's messages and trigger compression if needed.

        Args:
            user_content: Round N context (progress, state, bridge_text, etc.).
            assistant_content: LLM XML output from this round.
        """
        if self._round1_user is None:
            raise RuntimeError("Round 1 not set — call set_round1 first")

        # Extract checkpoint summaries for potential compression
        checkpoint_text = self._extract_checkpoint_summaries(assistant_content)

        self._rounds.append({
            "round_num": self._round_count + 1,
            "user_content": user_content,
            "assistant_content": assistant_content,
            "checkpoint": checkpoint_text,
        })
        self._round_count += 1

        # Extract bridge_text from this round's output for next round
        try:
            parsed = XmlParser.parse(assistant_content)
            self._last_bridge_text = parsed.bridge_text
        except Exception:
            self._last_bridge_text = ""

        # Trigger compression if needed
        self._maybe_compress()

    def get_messages(self) -> list[dict]:
        """Build the full messages array for the next API call.

        Returns:
            List of {"role": str, "content": str} dicts.
        """
        messages = []

        # 1. Round 1 anchor (permanent)
        if self._round1_user:
            messages.append({"role": "user", "content": self._round1_user})
        if self._round1_assistant:
            messages.append({"role": "assistant", "content": self._round1_assistant})

        # 2. Compressed rounds
        if self._compressed_summaries:
            user_msg, asst_msg = self._build_compression_messages(
                self._compressed_summaries
            )
            messages.append({"role": "user", "content": user_msg})
            messages.append({"role": "assistant", "content": asst_msg})

        # 3. Window rounds (complete)
        window_rounds = self._get_window_rounds()
        for r in window_rounds:
            messages.append({"role": "user", "content": r["user_content"]})
            messages.append({"role": "assistant", "content": r["assistant_content"]})

        return messages

    def get_compressed_rounds(self) -> list[int]:
        """Return list of round numbers that have been compressed."""
        # Calculate from stored summaries vs total rounds
        total_rounds = len(self._rounds) + 1  # +1 for Round 1
        window_count = min(WINDOW_SIZE, len(self._rounds))
        compressed_count = max(0, total_rounds - 1 - window_count - 1)
        if compressed_count > 0:
            return list(range(2, 2 + compressed_count))
        return []

    def get_window_rounds(self) -> list[int]:
        """Return list of round numbers currently in the window."""
        total_rounds = len(self._rounds) + 1
        window_count = min(WINDOW_SIZE, len(self._rounds))
        start = total_rounds - window_count
        return list(range(start, total_rounds))

    def get_last_bridge_text(self) -> str:
        """Return bridge_text from the most recent round."""
        return self._last_bridge_text

    def _maybe_compress(self) -> None:
        """Compress rounds that have fallen out of the window."""
        total_rounds = len(self._rounds) + 1  # +1 for Round 1
        if total_rounds < FIRST_COMPRESSION_AT:
            return

        # Calculate how many rounds should be in window
        window_count = min(WINDOW_SIZE, len(self._rounds))

        # Rounds to keep in full: indices [total_rounds - window_count - 1, total_rounds - 1] in _rounds
        keep_start = len(self._rounds) - window_count
        if keep_start < 0:
            keep_start = 0

        # Collect checkpoint summaries from rounds before keep_start
        for i in range(keep_start):
            cp = self._rounds[i].get("checkpoint", "")
            if cp and cp not in self._compressed_summaries:
                self._compressed_summaries.append(cp)

    def _get_window_rounds(self) -> list[dict]:
        """Get the rounds currently in the sliding window."""
        window_count = min(WINDOW_SIZE, len(self._rounds))
        return self._rounds[-window_count:] if window_count > 0 else []

    @staticmethod
    def _extract_checkpoint_summaries(xml: str) -> str:
        """Extract checkpoint summary from XML output."""
        import re
        match = re.search(r'<checkpoint[^>]*summary="([^"]*)"', xml)
        return match.group(1) if match else ""

    @staticmethod
    def _build_compression_messages(
        summaries: list[str],
    ) -> tuple[str, str]:
        """Build user/assistant message pair for compressed rounds.

        Args:
            summaries: List of checkpoint summary strings.

        Returns:
            (user_message, assistant_message) tuple.
        """
        items = "\n".join(f"- {s}" for s in summaries)
        user_msg = f"以下是之前发生的主要事件：\n\n{items}"
        asst_msg = "（以上为已发生事件的摘要。当前故事继续推进。）"
        return user_msg, asst_msg
```

- [ ] **步骤 4：运行测试验证通过**

```bash
python3 -m pytest tests/test_context_manager.py -v
```
预期：全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add src/storyloom/context_manager.py tests/test_context_manager.py
git commit -m "feat: add ContextManager with sliding window and compression"
```

---

### 任务 4：实现 PromptBuilder — 组装 Prompt 内容

**文件：**
- 创建：`tests/test_prompt_builder.py`
- 创建：`src/storyloom/prompt_builder.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_prompt_builder.py
"""Tests for prompt_builder module."""

import pytest
from src.storyloom.prompt_builder import PromptBuilder


SAMPLE_STORY_CONFIG = {
    "genre": "赛博朋克冒险",
    "tier": "medium",
    "label": "霓虹深渊",
    "setting": "2087年新东京地下城",
    "protagonist_name": "林焰",
    "protagonist_identity": "前荒坂安全顾问，现自由佣兵",
    "protagonist_traits": "冷静、道德灰色",
    "tone": "黑暗冷峻",
    "conflict": "一枚神秘芯片正在寻找宿主",
    "characters": "耗子（地下情报贩子）、美智子（荒坂安全主管）",
    "variables": [
        {"name": "体力", "type": "number", "initial": 80},
        {"name": "信任度", "type": "number", "initial": 10},
        {"name": "所属势力", "type": "string", "initial": "自由佣兵"},
    ],
}

SAMPLE_OUTLINE = """
ch1_bar [completed] — 霓虹深渊：在酒吧获取情报
  → ch2_confrontation [active]
ch2_confrontation [active] — 地下交易：与耗子会面
  ├→ ch3_ally [pending]
  └→ ch3_betrayal [pending]
ch3_ally [pending] — 盟友之路：通过地下网络逃离
ch3_betrayal [pending] — 背叛之路：杀出重围
ch4_safehouse [pending] — 安全屋：揭开芯片秘密（结局）
"""


class TestBuildRound1:
    def test_round1_contains_role_definition(self):
        pb = PromptBuilder()
        result = pb.build_round1(SAMPLE_STORY_CONFIG, SAMPLE_OUTLINE, "ch2_confrontation", "与耗子完成交易")
        assert "叙事引擎" in result

    def test_round1_contains_xml_format_spec(self):
        pb = PromptBuilder()
        result = pb.build_round1(SAMPLE_STORY_CONFIG, SAMPLE_OUTLINE, "ch2_confrontation", "与耗子完成交易")
        assert "<story>" in result
        assert "<seg n=" in result
        assert "<bridge/>" in result

    def test_round1_contains_format_example(self):
        pb = PromptBuilder()
        result = pb.build_round1(SAMPLE_STORY_CONFIG, SAMPLE_OUTLINE, "ch2_confrontation", "与耗子完成交易")
        assert "炉火" in result  # example content
        assert "旅店老板" in result

    def test_round1_contains_story_context(self):
        pb = PromptBuilder()
        result = pb.build_round1(SAMPLE_STORY_CONFIG, SAMPLE_OUTLINE, "ch2_confrontation", "与耗子完成交易")
        assert "赛博朋克冒险" in result
        assert "林焰" in result
        assert "ch2_confrontation" in result

    def test_round1_contains_state_variables(self):
        pb = PromptBuilder()
        result = pb.build_round1(SAMPLE_STORY_CONFIG, SAMPLE_OUTLINE, "ch2_confrontation", "与耗子完成交易")
        assert "体力" in result
        assert "信任度" in result

    def test_round1_ends_with_start_instruction(self):
        pb = PromptBuilder()
        result = pb.build_round1(SAMPLE_STORY_CONFIG, SAMPLE_OUTLINE, "ch2_confrontation", "与耗子完成交易")
        assert "请开始故事" in result


class TestBuildRoundN:
    def test_round_n_does_not_contain_format_spec(self):
        pb = PromptBuilder()
        result = pb.build_round_n(
            current_node="ch3_ally",
            goal="通过地下网络逃离",
            completed_nodes=["ch1_bar", "ch2_confrontation"],
            state_vars={"体力": 60, "信任度": 25, "所属势力": "自由佣兵"},
            bridge_text="你对耗子点了点头。\n耗子: 跟我来。",
            compressed_summaries=["在旅店接头", "完成芯片交易"],
        )
        assert "<story>" not in result
        assert "<seg n=" not in result

    def test_round_n_contains_progress(self):
        pb = PromptBuilder()
        result = pb.build_round_n(
            current_node="ch3_ally",
            goal="通过地下网络逃离",
            completed_nodes=["ch1_bar", "ch2_confrontation"],
            state_vars={"体力": 60},
            bridge_text="tail...",
        )
        assert "ch3_ally" in result
        assert "通过地下网络逃离" in result
        assert "ch1_bar" in result

    def test_round_n_contains_state_snapshot(self):
        pb = PromptBuilder()
        result = pb.build_round_n(
            current_node="ch3_ally",
            goal="逃",
            completed_nodes=[],
            state_vars={"体力": 60, "信任度": 25},
            bridge_text="tail...",
        )
        assert "体力" in result
        assert "60" in result
        assert "信任度" in result

    def test_round_n_contains_bridge_text(self):
        pb = PromptBuilder()
        result = pb.build_round_n(
            current_node="ch3_ally",
            goal="逃",
            completed_nodes=[],
            state_vars={"体力": 60},
            bridge_text="你对耗子点了点头。",
        )
        assert "上一轮结尾" in result
        assert "你对耗子点了点头" in result

    def test_round_n_contains_compressed_summaries(self):
        pb = PromptBuilder()
        result = pb.build_round_n(
            current_node="ch4",
            goal="结局",
            completed_nodes=["ch1", "ch2", "ch3"],
            state_vars={"体力": 30},
            bridge_text="tail...",
            compressed_summaries=["在旅店接头", "完成芯片交易"],
        )
        assert "在旅店接头" in result
        assert "完成芯片交易" in result

    def test_round_n_contains_rejected_feedback_when_present(self):
        pb = PromptBuilder()
        result = pb.build_round_n(
            current_node="ch3",
            goal="逃",
            completed_nodes=[],
            state_vars={"体力": 60},
            bridge_text="tail...",
            rejected_changes=["体力变更被拒：超出范围[0,100]"],
        )
        assert "体力变更被拒" in result

    def test_round_n_omits_rejected_section_when_empty(self):
        pb = PromptBuilder()
        result = pb.build_round_n(
            current_node="ch3",
            goal="逃",
            completed_nodes=[],
            state_vars={"体力": 60},
            bridge_text="tail...",
            rejected_changes=[],
        )
        assert "被拒" not in result

    def test_round_n_format_error_adds_correction_hint(self):
        pb = PromptBuilder()
        result = pb.build_round_n(
            current_node="ch3",
            goal="逃",
            completed_nodes=[],
            state_vars={"体力": 60},
            bridge_text="tail...",
            format_error="checkpoint 的 node 值与大纲不匹配",
        )
        assert "格式提醒" in result or "checkpoint" in result
```

- [ ] **步骤 2：运行测试验证失败**

```bash
python3 -m pytest tests/test_prompt_builder.py -v
```
预期：全部 FAIL（模块不存在）

- [ ] **步骤 3：实现 PromptBuilder**

```python
# src/storyloom/prompt_builder.py
"""Build Round 1 and Round N prompt content for conversation-based architecture."""

from src.storyloom.config import SEGMENTS_PER_ROUND_MIN, SEGMENTS_PER_ROUND_MAX


# ── Round 1 fixed template ──────────────────────────────────────

ROUND1_TEMPLATE = """你是文字冒险游戏的叙事引擎。根据大纲和状态生成下一段交互式剧情。

# 输出格式

你的输出必须是 XML 文档。以 <story> 开头，以 </story> 结尾。
不要输出 markdown 代码围栏、XML 声明、或 XML 之外的任何文本。

## 结构

<story>
  <seg n="1">叙事文本</seg>
  <seg n="2">叙事文本</seg>
  ...
  <branch name="分支名">
    <seg n="N">局部小分支叙事</seg>
  </branch>
  <choice id="变量名">
    <opt key="A" branch="分支名">选项文本</opt>
    <opt key="B" branch="分支名">选项文本</opt>
  </choice>
  <set var="变量" op="操作" val="值"/>
  <set var="变量" op="操作" val="值" if="条件"/>
  <checkpoint node="节点ID" summary="摘要">
    <route if="条件" target="目标节点"/>
  </checkpoint>
  <bridge/>
  <!-- bridge 之后：纯叙事，禁止交互元素 -->
  <branch name="分支名">
    <seg n="N">分支叙事</seg>
    ...
  </branch>
</story>

## 元素说明

**<seg n="N">** — 叙事段。n 从 1 开始全局连续。旁白（纯叙述，15-40 字）或对话（`角色名: 内容`，英文冒号+空格，无引号，≤50字）。每段只做一件事，禁止混合。

**<choice id="变量名">** — 玩家选项。内含 2-5 个 `<opt>`。opt 的 key 为字母键（A/B/C/D），branch 对应 bridge 之后的 `<branch name="...">`。

**<set>** — 状态变更。var/op/val 必填。number 用 +/-/=/=N，string 用 =，list 用 +/-。if 属性可选，格式 `变量名 运算符 值`，用 and/or 组合（最多一个）。

**<checkpoint>** — 关键节点。node 必须原样复制大纲节点 ID，summary 为 1-2 句中文摘要。内含 0-N 个 `<route>` 元素。

**<bridge/>** — 自闭合，恰好一次。前：交互区（可含 seg/branch/choice/set/checkpoint）。后：纯叙事区（只有 seg 或 branch），禁止 choice/set/checkpoint。

**<branch name>** — 分支叙事容器。bridge 之前用于局部小分支，bridge 之后用于选项后果分支。name 与 `<opt>` 的 branch 属性精确对应。

## 完整格式示例

以下为格式示例（内容为虚构的奇幻故事）：

<story>
<seg n="1">炉火在石砌的壁炉里噼啪作响，旅店大堂里弥漫着麦酒和松木的气味。</seg>
<seg n="2">你推开厚重的橡木门，冷风裹挟着雪花卷入室内。</seg>
<seg n="3">旅店老板: 这么晚了还赶路？</seg>
<seg n="4">角落里一个裹着斗篷的身影动了动。</seg>
<seg n="5">疤脸人摘下兜帽，眼神出奇的平静。</seg>
<seg n="6">疤脸人: 坐。听说你在找一样东西。</seg>
<choice id="approach">
  <opt key="A" branch="take_lead">先开口</opt>
  <opt key="B" branch="wait">保持沉默</opt>
</choice>
<set var="声望" op="+" val="5" if="approach==1"/>
<set var="谨慎度" op="+" val="10" if="approach==2"/>
<checkpoint node="ch2_meeting" summary="在旅店与神秘线人接头，选择了接触策略。">
  <route if="approach==1" target="ch3_lead"/>
  <route if="approach==2" target="ch3_wait"/>
</checkpoint>
<bridge/>
<branch name="take_lead">
<seg n="7">你在他对面坐下，指尖在木桌上轻轻敲了两下。</seg>
<seg n="8">林焰: 听说你手里有我要的情报。</seg>
<seg n="9">疤脸人微微一笑，从斗篷里掏出蜡封的羊皮纸卷。</seg>
</branch>
<branch name="wait">
<seg n="10">你站着没动，不动声色地啜了一口麦酒。</seg>
<seg n="11">沉默像一根绷紧的弦，疤脸人先沉不住气了。</seg>
<seg n="12">他把羊皮纸卷推到桌子中央。</seg>
</branch>
</story>

（以上为格式示例。你的输出是全新的剧情段——从 1 开始编号，不要复制示例内容或编号。）

# 核心规则

- 所有 <seg> 的 n 从 1 开始，全局连续递增，不重复不跳号
- {MIN}-{MAX} 个叙事段。bridge 放在交互与叙事分界处，约总段数一半
- bridge 之后只能有 <seg> 或 <branch>，严格禁止 <choice>/<set>/<checkpoint>
- <checkpoint> 的 node 和 <route> 的 target 必须严格复制大纲节点 ID，禁止修改或拼接后缀
- 有 <choice> 时，每个 <opt> 的 branch 必须在 bridge 之后有对应 <branch name>
- 对话不加引号，不用代词做角色名，不断内混动作描写
- 文本中 & 须转义为 &amp;

# 质量要求

每段只做一件事——描写一个画面或表达一句对白。对话与旁白交替出现，避免连续 3 段以上纯描写。选项的后果在叙事中铺垫。bridge 之后制造悬念。

# 故事

**背景：** {genre} · {setting}
**主角：** {name}，{identity}。{traits}
**风格：** {tone}
**冲突：** {conflict}
**角色：** {characters}

**大纲：**
{outline_text}
[completed]=已完成 [active]=当前 [pending]=待推进

**当前状态：**
{state_vars_text}

当前节点目标：{goal}

请开始故事。"""


class PromptBuilder:
    """Build prompt content for conversation-based architecture.

    Round 1: Full format spec + story context + format example.
    Round N: Lightweight context (progress, state, bridge_text, errors).
    """

    @staticmethod
    def build_round1(
        story_config: dict,
        outline_text: str,
        current_node: str,
        goal: str,
    ) -> str:
        """Build Round 1 prompt (permanent anchor).

        Args:
            story_config: Story configuration dict with keys:
                genre, tier, label, setting, protagonist_name,
                protagonist_identity, protagonist_traits,
                tone, conflict, characters, variables.
            outline_text: Formatted outline tree text.
            current_node: Current outline node ID.
            goal: Current node narrative goal.

        Returns:
            Full Round 1 prompt string.
        """
        state_vars_text = PromptBuilder._format_state_vars(
            story_config.get("variables", [])
        )

        return ROUND1_TEMPLATE.format(
            MIN=SEGMENTS_PER_ROUND_MIN,
            MAX=SEGMENTS_PER_ROUND_MAX,
            genre=story_config.get("genre", ""),
            setting=story_config.get("setting", ""),
            name=story_config.get("protagonist_name", ""),
            identity=story_config.get("protagonist_identity", ""),
            traits=story_config.get("protagonist_traits", ""),
            tone=story_config.get("tone", ""),
            conflict=story_config.get("conflict", ""),
            characters=story_config.get("characters", ""),
            outline_text=outline_text,
            state_vars_text=state_vars_text,
            goal=goal,
        )

    @staticmethod
    def build_round_n(
        current_node: str,
        goal: str,
        completed_nodes: list[str],
        state_vars: dict[str, int | str | list],
        bridge_text: str,
        compressed_summaries: list[str] | None = None,
        rejected_changes: list[str] | None = None,
        format_error: str | None = None,
    ) -> str:
        """Build Round N context message (N >= 2).

        Args:
            current_node: Current outline node ID.
            goal: Current node narrative goal.
            completed_nodes: List of completed node IDs.
            state_vars: Current state variable values.
            bridge_text: Plain text from last round's bridge tail.
            compressed_summaries: Checkpoint summaries from compressed rounds.
            rejected_changes: Rejected state change descriptions from last round.
            format_error: Format error hint from last round (if any).

        Returns:
            Round N context string for user message.
        """
        parts = []

        # Progress
        parts.append(f"当前节点：{current_node} — {goal}")
        if completed_nodes:
            parts.append(f"已完成节点：{', '.join(completed_nodes)}")

        # Compressed summaries
        if compressed_summaries:
            parts.append("\n已完成的章节摘要：")
            for s in compressed_summaries:
                parts.append(f"- {s}")

        # State snapshot
        parts.append("\n当前状态：")
        for name, value in state_vars.items():
            parts.append(f"  {name}：{value}")

        # Rejected changes feedback
        if rejected_changes:
            parts.append("\n上一轮状态变更被拒：")
            for rc in rejected_changes:
                parts.append(f"  - {rc}")

        # Format error correction
        if format_error:
            parts.append(f"\n格式提醒：上一轮输出存在格式问题——{format_error}。请严格遵循 XML 格式规范。")

        # Bridge text
        parts.append(f"\n上一轮结尾：\n{bridge_text}")

        return "\n".join(parts)

    @staticmethod
    def _format_state_vars(variables: list[dict]) -> str:
        """Format variable definitions for display in Round 1 prompt.

        Args:
            variables: List of {"name", "type", "initial"} dicts.

        Returns:
            Formatted string, one variable per line.
        """
        lines = []
        for v in variables:
            name = v["name"]
            initial = v["initial"]
            if v["type"] == "number":
                lines.append(f"{name}：{initial} / 100")
            elif v["type"] == "list":
                if initial:
                    lines.append(f"{name}：{', '.join(initial)}")
                else:
                    lines.append(f"{name}：（无）")
            else:
                lines.append(f"{name}：{initial}")
        return "\n".join(lines)
```

- [ ] **步骤 4：运行测试验证通过**

```bash
python3 -m pytest tests/test_prompt_builder.py -v
```
预期：全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add src/storyloom/prompt_builder.py tests/test_prompt_builder.py
git commit -m "feat: add PromptBuilder for Round 1 and Round N messages"
```

---

### 任务 5：集成验证 — 多轮对话模拟

**文件：**
- 创建：`tests/test_integration.py`

- [ ] **步骤 1：编写端到端集成测试**

```python
# tests/test_integration.py
"""Integration tests for conversation-based prompt architecture."""

from src.storyloom.context_manager import ContextManager
from src.storyloom.prompt_builder import PromptBuilder


SAMPLE_STORY = {
    "genre": "赛博朋克冒险",
    "tier": "medium",
    "label": "霓虹深渊",
    "setting": "2087年新东京地下城",
    "protagonist_name": "林焰",
    "protagonist_identity": "前荒坂安全顾问",
    "protagonist_traits": "冷静、道德灰色",
    "tone": "黑暗冷峻",
    "conflict": "一枚神秘芯片正在寻找宿主",
    "characters": "耗子（情报贩子）、美智子（安全主管）",
    "variables": [
        {"name": "体力", "type": "number", "initial": 80},
        {"name": "信任度", "type": "number", "initial": 10},
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

# Simulated LLM outputs for each round
ROUND1_OUTPUT = """<story>
<seg n="1">霓虹灯在潮湿的巷道地面上投下破碎的倒影。</seg>
<seg n="2">耗子的酒吧藏在第三层地下通道的尽头。</seg>
<seg n="3">林焰: 芯片在哪儿？
<choice id="approach">
  <opt key="A" branch="direct">直接问价</opt>
  <opt key="B" branch="careful">先探口风</opt>
</choice>
<set var="信任度" op="+" val="5" if="approach==1"/>
<set var="信任度" op="-" val="5" if="approach==2"/>
<checkpoint node="ch2_confrontation" summary="在霓虹深渊酒吧与耗子接头，选择了接触策略。">
  <route if="approach==1" target="ch3_ally"/>
  <route if="approach==2" target="ch3_betrayal"/>
</checkpoint>
<bridge/>
<branch name="direct">
<seg n="4">你把信用棒拍在吧台上。</seg>
<seg n="5">耗子: 痛快。不过我得提醒你——荒坂的人在找你。</seg>
</branch>
<branch name="careful">
<seg n="6">你先要了杯酒，耗子在你身边坐下。</seg>
<seg n="7">耗子: 最近生意不好做啊。</seg>
</branch>
</story>"""

ROUND2_OUTPUT = """<story>
<seg n="1">耗子领着你穿过酒吧后厨，推开一扇标着"员工通道"的门。</seg>
<seg n="2">门后是一条狭窄的走廊，荧光灯管嗡嗡作响。</seg>
<seg n="3">耗子: 芯片在安全屋里。不过去之前——我们得谈谈价。
<choice id="negotiation">
  <opt key="A" branch="pay">按原价支付</opt>
  <opt key="B" branch="haggle">讨价还价</opt>
</choice>
<set var="信任度" op="+" val="5" if="negotiation==1"/>
<set var="体力" op="-" val="10" if="negotiation==2"/>
<checkpoint node="ch3_ally" summary="与耗子前往安全屋，途中谈判交易价格。">
</checkpoint>
<bridge/>
<branch name="pay">
<seg n="4">你点头同意，耗子咧嘴一笑。</seg>
</branch>
<branch name="haggle">
<seg n="5">你皱起眉头，耗子的义眼红光闪烁了一下。</seg>
</branch>
</story>"""


class TestIntegration:
    def test_full_5_round_conversation_flow(self):
        """Simulate 5 rounds and verify message structure at each step."""
        pb = PromptBuilder()
        cm = ContextManager()

        # Round 1
        r1_prompt = pb.build_round1(
            SAMPLE_STORY, SAMPLE_OUTLINE, "ch2_confrontation", "与耗子完成交易"
        )
        cm.set_round1(r1_prompt, ROUND1_OUTPUT)
        msgs = cm.get_messages()
        assert len(msgs) == 2
        assert cm.round_count == 1
        assert cm.get_compressed_rounds() == []

        # Round 2
        bridge1 = cm.get_last_bridge_text()
        assert len(bridge1) > 0
        r2_prompt = pb.build_round_n(
            current_node="ch3_ally",
            goal="与耗子前往安全屋",
            completed_nodes=["ch1_bar", "ch2_confrontation"],
            state_vars={"体力": 80, "信任度": 15},
            bridge_text=bridge1,
        )
        cm.add_round(r2_prompt, ROUND2_OUTPUT)
        assert cm.round_count == 2
        assert cm.get_compressed_rounds() == []

        # Round 3
        cm.add_round("r3 context", ROUND2_OUTPUT)
        assert cm.round_count == 3

        # Round 4
        cm.add_round("r4 context", ROUND2_OUTPUT)
        assert cm.round_count == 4
        assert cm.get_compressed_rounds() == []  # No compression yet

        # Round 5 — triggers compression
        cm.add_round("r5 context", ROUND2_OUTPUT)
        assert cm.round_count == 5
        compressed = cm.get_compressed_rounds()
        assert len(compressed) >= 1  # Round 2 should be compressed

        # Verify message structure
        msgs = cm.get_messages()
        assert msgs[0]["role"] == "user"      # Round 1 prompt
        assert msgs[1]["role"] == "assistant"  # Round 1 output
        # Should have compression messages + window rounds + current round

    def test_context_manager_preserves_round1(self):
        """Round 1 messages should never be removed."""
        pb = PromptBuilder()
        cm = ContextManager()

        r1 = pb.build_round1(
            SAMPLE_STORY, SAMPLE_OUTLINE, "ch2_confrontation", "与耗子交易"
        )
        cm.set_round1(r1, ROUND1_OUTPUT)

        for i in range(2, 10):
            cm.add_round(f"r{i}", ROUND2_OUTPUT)

        msgs = cm.get_messages()
        assert msgs[0]["content"] == r1
        assert "叙事引擎" in msgs[0]["content"]
        assert "<story>" in msgs[0]["content"]

    def test_bridge_text_flows_between_rounds(self):
        """Bridge text extracted from round N feeds into round N+1 context."""
        pb = PromptBuilder()
        cm = ContextManager()

        cm.set_round1(
            pb.build_round1(SAMPLE_STORY, SAMPLE_OUTLINE, "ch2", "交易"),
            ROUND1_OUTPUT,
        )

        bridge1 = cm.get_last_bridge_text()
        r2 = pb.build_round_n("ch3", "前往安全屋", ["ch1", "ch2"],
                              {"体力": 80, "信任度": 15}, bridge1)
        assert "信用棒" in r2 or "耗子" in r2  # bridge text appears in context

    def test_compression_format(self):
        """Compressed messages use the correct format."""
        pb = PromptBuilder()
        cm = ContextManager()

        cm.set_round1(
            pb.build_round1(SAMPLE_STORY, SAMPLE_OUTLINE, "ch2", "交易"),
            ROUND1_OUTPUT,
        )

        for i in range(2, 6):
            cm.add_round(f"r{i}", ROUND2_OUTPUT)

        msgs = cm.get_messages()
        # Find compression messages
        contents = [m["content"] for m in msgs]
        has_summary = any("已发生的主要事件" in c for c in contents)
        assert has_summary or cm.round_count < 5
```

- [ ] **步骤 2：运行测试验证**

```bash
python3 -m pytest tests/test_integration.py -v
```
预期：全部 PASS

- [ ] **步骤 3：Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration tests for conversation flow"
```

---

### 任务 6：运行全部测试并最终验证

- [ ] **步骤 1：运行完整测试套件**

```bash
python3 -m pytest tests/ -v
```
预期：全部 PASS

- [ ] **步骤 2：验证对现有测试无影响**

```bash
python3 tests/run_prompt_test.py --help
python3 tests/analyze_frame.py --help
```
预期：现有工具仍可正常使用

- [ ] **步骤 3：Commit**

```bash
git add -A
git commit -m "test: final verification — all tests passing"
```

---

## 自检

### 1. 规格覆盖度

| 规格章节 | 对应任务 |
|---------|---------|
| 消息数组结构 | 任务 3 (ContextManager) |
| Round 1 Prompt | 任务 4 (PromptBuilder.build_round1) |
| Round N 上下文 | 任务 4 (PromptBuilder.build_round_n) |
| 压缩策略 (触发时机、格式) | 任务 3 (ContextManager._maybe_compress, _build_compression_messages) |
| 格式范例生命周期 | 任务 4 (Round 1 template 含格式范例，永久保留) |
| 格式错误纠正 | 任务 4 (build_round_n format_error 参数) |
| bridge_text 提取 | 任务 2 (XmlParser._extract_bridge_text) |
| checkpoint 摘要提取 | 任务 3 (ContextManager._extract_checkpoint_summaries) |

### 2. 占位符扫描

无 TODO/TBD/待定。所有步骤包含具体代码。

### 3. 类型一致性

- `ParsedOutput` → 在 XmlParser 中定义，被 ContextManager 使用 ✓
- `PromptBuilder.build_round1` 参数与设计文档一致 ✓
- `PromptBuilder.build_round_n` 参数与设计文档一致 ✓
- `ContextManager.set_round1` / `add_round` 签名简洁 ✓
