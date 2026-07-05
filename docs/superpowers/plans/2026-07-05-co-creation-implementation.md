# Co-Creation Phase Implementation Plan

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 实现完整的共创阶段管线（用户输入 → 追问循环 → 单次LLM生成设定+变量+大纲 → 校验），替代 main.py 中的硬编码配置。

**架构：** 新建 `co_create.py` 模块，含 `CoCreateFlow`（流程编排 + Prompt 模板）和 `CoCreateParser`（无状态解析/校验函数）。共创阶段使用静态 messages 数组（无滑动窗口/压缩），输出 INI 风格的三段式格式。

**技术栈：** Python 3 标准库，pytest，与现有叙事循环零耦合。

**设计文档：** `docs/superpowers/specs/2026-07-05-co-creation-implementation-design.md`

---

### 任务 1：添加共创阶段配置常量

**文件：**
- 修改：`src/storyloom/config.py`

- [ ] **步骤 1：在 config.py 末尾追加常量**

```python
# ── Co-creation ──────────────────────────────────────────────────
MAX_RETRIES = 2

# Variable caps (per 2026-07-05 variable-cap spec)
VARIABLE_CAP = 3            # max total variables
VARIABLE_NUMERIC_CAP = 2    # max numeric (number) variables
VARIABLE_LABEL_CAP = 1      # max label (string/list) variables

# Outline node ranges by tier
OUTLINE_NODE_RANGES = {
    "short":  (3, 5),
    "medium": (5, 8),
    "long":   (8, 15),
}
```

- [ ] **步骤 2：验证导入**

运行：`python3 -c "from src.storyloom.config import MAX_RETRIES, VARIABLE_CAP, OUTLINE_NODE_RANGES; print(MAX_RETRIES, VARIABLE_CAP, OUTLINE_NODE_RANGES)"`
预期：`2 3 {'short': (3, 5), 'medium': (5, 8), 'long': (8, 15)}`

- [ ] **步骤 3：Commit**

```bash
git add src/storyloom/config.py
git commit -m "feat: add co-creation config constants (MAX_RETRIES, variable caps, outline ranges)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 2：CoCreateParser.split_blocks — 三段式分割

**文件：**
- 创建：`src/storyloom/co_create.py`
- 创建：`tests/test_co_create.py`

- [ ] **步骤 1：编写失败的测试**

```python
"""Tests for co-create parser and flow."""
import pytest
from src.storyloom.co_create import CoCreateParser


class TestSplitBlocks:
    """Tests for _split_blocks — splitting LLM response into 3 sections."""

    def test_split_three_blocks(self):
        text = """=== story_config ===
genre: fantasy
tier: short

=== variables ===
hp: number, 初始 80

=== outline ===
[node]
id: ch1
title: start
goal: begin
routes: （结局）"""
        result = CoCreateParser.split_blocks(text)
        assert "genre: fantasy" in result["story_config"]
        assert "hp: number" in result["variables"]
        assert "[node]" in result["outline"]

    def test_split_missing_block_sets_empty(self):
        text = """=== story_config ===
genre: fantasy
tier: short"""
        result = CoCreateParser.split_blocks(text)
        assert result["story_config"] != ""
        assert result["variables"] == ""
        assert result["outline"] == ""

    def test_split_empty_text_returns_all_empty(self):
        result = CoCreateParser.split_blocks("")
        assert result == {"story_config": "", "variables": "", "outline": ""}

    def test_split_handles_spurious_delimiters_in_content(self):
        """Lines containing === that are not block delimiters should be kept as content."""
        text = """=== story_config ===
genre: fantasy
note: use === sparingly
tier: short

=== variables ===
hp: number, 初始 80

=== outline ===
[node]
id: ch1"""
        result = CoCreateParser.split_blocks(text)
        assert "use === sparingly" in result["story_config"]
        assert "hp: number" in result["variables"]
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_co_create.py::TestSplitBlocks -v`
预期：FAIL — `CoCreateParser` / `split_blocks` 不存在

- [ ] **步骤 3：实现 split_blocks**

```python
"""Co-creation phase: user input → Q&A loop → story setup generation."""
import re
from dataclasses import dataclass

from src.storyloom.api_client import ApiClient
from src.storyloom.display import Display
from src.storyloom.config import (
    MAX_RETRIES,
    VARIABLE_CAP,
    VARIABLE_NUMERIC_CAP,
    VARIABLE_LABEL_CAP,
    OUTLINE_NODE_RANGES,
)


class CoCreateParser:
    """Stateless helpers for parsing LLM co-creation output."""

    BLOCK_DELIMITER = re.compile(r"^=== (story_config|variables|outline) ===\s*$")

    @staticmethod
    def split_blocks(text: str) -> dict[str, str]:
        """Split LLM response into {story_config, variables, outline} blocks.

        Args:
            text: Raw LLM response text.

        Returns:
            Dict with keys 'story_config', 'variables', 'outline'.
            Missing blocks have empty string values.
        """
        result = {"story_config": "", "variables": "", "outline": ""}
        current_block: str | None = None
        lines: list[str] = []

        for line in text.split("\n"):
            m = CoCreateParser.BLOCK_DELIMITER.match(line.strip())
            if m:
                if current_block and current_block in result:
                    result[current_block] = "\n".join(lines).strip()
                current_block = m.group(1)
                lines = []
            elif current_block:
                lines.append(line)

        if current_block and current_block in result:
            result[current_block] = "\n".join(lines).strip()

        return result
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_co_create.py::TestSplitBlocks -v`
预期：PASS（4 tests）

- [ ] **步骤 5：Commit**

```bash
git add src/storyloom/co_create.py tests/test_co_create.py
git commit -m "feat: add CoCreateParser.split_blocks for three-section LLM output

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 3：CoCreateParser.parse_story_config — 故事设定解析

**文件：**
- 修改：`src/storyloom/co_create.py`
- 修改：`tests/test_co_create.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_co_create.py` 中追加：

```python
class TestParseStoryConfig:
    """Tests for parse_story_config — INI-style key: value parsing."""

    VALID_CONFIG = """genre: 赛博朋克冒险
tier: medium
setting: 2087年新东京地下城
protagonist_name: 林焰
protagonist_identity: 前荒坂安全顾问，现自由佣兵
protagonist_traits: 冷静、道德灰色
tone: 黑暗冷峻
conflict: 一枚神秘芯片正在寻找宿主
characters:
  耗子 | 地下情报贩子 | 亦敌亦友
  美智子 | 荒坂安全主管 | 前上司"""

    def test_parse_complete_valid_config(self):
        result = CoCreateParser.parse_story_config(self.VALID_CONFIG)
        assert result["genre"] == "赛博朋克冒险"
        assert result["tier"] == "medium"
        assert result["setting"] == "2087年新东京地下城"
        assert result["protagonist_name"] == "林焰"
        assert result["protagonist_identity"] == "前荒坂安全顾问，现自由佣兵"
        assert result["protagonist_traits"] == "冷静、道德灰色"
        assert result["tone"] == "黑暗冷峻"
        assert result["conflict"] == "一枚神秘芯片正在寻找宿主"
        assert "耗子" in result["characters"]
        assert "美智子" in result["characters"]

    def test_parse_without_setting_still_works(self):
        text = """genre: fantasy
tier: short
setting:
protagonist_name: Kael
protagonist_identity: mercenary
protagonist_traits: brave
tone: dark
conflict: a war
characters:
  Mouse | spy | friend"""
        result = CoCreateParser.parse_story_config(text)
        assert result["setting"] == ""
        assert result["genre"] == "fantasy"

    def test_missing_required_field_raises_parse_error(self):
        text = """genre: fantasy
tier: short
protagonist_name: Kael
protagonist_identity: mercenary
protagonist_traits: brave
tone: dark
conflict: a war"""
        with pytest.raises(ValueError, match="Missing required fields"):
            CoCreateParser.parse_story_config(text)

    def test_invalid_tier_raises_parse_error(self):
        text = """genre: fantasy
tier: epic
setting: somewhere
protagonist_name: Kael
protagonist_identity: mercenary
protagonist_traits: brave
tone: dark
conflict: a war
characters:
  Mouse | spy | friend"""
        with pytest.raises(ValueError, match="Unknown tier"):
            CoCreateParser.parse_story_config(text)

    def test_empty_text_raises_parse_error(self):
        with pytest.raises(ValueError, match="Empty"):
            CoCreateParser.parse_story_config("")

    def test_characters_single_entry(self):
        text = """genre: fantasy
tier: short
setting: somewhere
protagonist_name: Kael
protagonist_identity: mercenary
protagonist_traits: brave
tone: dark
conflict: a war
characters:
  Mouse | spy | friend"""
        result = CoCreateParser.parse_story_config(text)
        assert "Mouse" in result["characters"]

    def test_language_field_defaults(self):
        """language field defaults to zh-CN if not provided."""
        result = CoCreateParser.parse_story_config(self.VALID_CONFIG)
        assert result.get("language", "zh-CN") == "zh-CN"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_co_create.py::TestParseStoryConfig -v`
预期：FAIL — `parse_story_config` 不存在

- [ ] **步骤 3：实现 parse_story_config**

在 `CoCreateParser` 类中追加：

```python
    REQUIRED_CONFIG_FIELDS = [
        "genre", "tier", "protagonist_name", "protagonist_identity",
        "protagonist_traits", "tone", "conflict", "characters",
    ]
    VALID_TIERS = {"short", "medium", "long"}

    @staticmethod
    def parse_story_config(text: str) -> dict:
        """Parse INI-style story config block into a dict.

        Args:
            text: Raw text of the story_config block.

        Returns:
            Dict with keys: genre, tier, setting, protagonist_name,
            protagonist_identity, protagonist_traits, tone, conflict,
            characters, language.

        Raises:
            ValueError: On missing required fields or invalid tier.
        """
        if not text or not text.strip():
            raise ValueError("Empty story_config block")

        result: dict[str, str] = {}
        result["language"] = "zh-CN"  # default
        current_field: str | None = None

        for line in text.strip().split("\n"):
            # Check for key: value line
            kv_match = re.match(r"^(\w+):\s*(.*)$", line)
            if kv_match:
                current_field = kv_match.group(1)
                value = kv_match.group(2).strip()
                result[current_field] = value
            elif current_field and line.startswith("  "):
                # Continuation line (e.g., characters sub-lines)
                result[current_field] += "\n" + line.strip()

        # Validate required fields
        missing = [f for f in CoCreateParser.REQUIRED_CONFIG_FIELDS
                   if f not in result or not result[f].strip()]
        if missing:
            raise ValueError(
                f"Missing required fields: {', '.join(missing)}"
            )

        # Validate tier
        tier = result.get("tier", "")
        if tier not in CoCreateParser.VALID_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}'. Must be one of: "
                f"{', '.join(sorted(CoCreateParser.VALID_TIERS))}"
            )

        # setting defaults to empty string
        if "setting" not in result:
            result["setting"] = ""

        return result
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_co_create.py::TestParseStoryConfig -v`
预期：PASS（7 tests）

- [ ] **步骤 5：Commit**

```bash
git add src/storyloom/co_create.py tests/test_co_create.py
git commit -m "feat: add CoCreateParser.parse_story_config with validation

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 4：CoCreateParser.parse_variables + validate_variables

**文件：**
- 修改：`src/storyloom/co_create.py`
- 修改：`tests/test_co_create.py`

- [ ] **步骤 1：编写失败的测试**

```python
class TestParseVariables:
    """Tests for parse_variables."""

    VALID_VARS = """体力: number, 初始 80
信任度: number, 初始 10
所属势力: string, 初始 自由佣兵"""

    def test_parse_three_valid_variables(self):
        result = CoCreateParser.parse_variables(self.VALID_VARS)
        assert len(result) == 3
        assert result[0] == {"name": "体力", "type": "number", "initial": 80}
        assert result[1] == {"name": "信任度", "type": "number", "initial": 10}
        assert result[2] == {"name": "所属势力", "type": "string", "initial": "自由佣兵"}

    def test_parse_list_type_empty(self):
        text = "物品: list, 初始 []"
        result = CoCreateParser.parse_variables(text)
        assert result[0]["type"] == "list"
        assert result[0]["initial"] == []

    def test_parse_list_type_with_elements(self):
        text = "线索: list, 初始 芯片, 密钥"
        result = CoCreateParser.parse_variables(text)
        assert result[0]["initial"] == ["芯片", "密钥"]

    def test_parse_single_variable(self):
        text = "理智值: number, 初始 50"
        result = CoCreateParser.parse_variables(text)
        assert len(result) == 1
        assert result[0]["name"] == "理智值"

    def test_empty_text_returns_empty_list(self):
        result = CoCreateParser.parse_variables("")
        assert result == []

    def test_malformed_line_raises_parse_error(self):
        text = "bad line without proper format"
        with pytest.raises(ValueError, match="Cannot parse variable"):
            CoCreateParser.parse_variables(text)

    def test_unknown_type_raises_parse_error(self):
        text = "体力: boolean, 初始 true"
        with pytest.raises(ValueError, match="Unknown type"):
            CoCreateParser.parse_variables(text)

    def test_number_initial_not_integer_raises_parse_error(self):
        text = "体力: number, 初始 high"
        with pytest.raises(ValueError, match="integer"):
            CoCreateParser.parse_variables(text)

    def test_name_with_illegal_colon_raises_parse_error(self):
        text = "体:力: number, 初始 80"
        with pytest.raises(ValueError, match="Cannot parse variable"):
            CoCreateParser.parse_variables(text)


class TestValidateVariables:
    """Tests for validate_variables."""

    def test_all_valid_passes(self):
        vars_list = [
            {"name": "体力", "type": "number", "initial": 80},
            {"name": "信任度", "type": "number", "initial": 10},
            {"name": "所属势力", "type": "string", "initial": "自由佣兵"},
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert errors == []

    def test_count_exceeds_cap(self):
        vars_list = [
            {"name": f"var{i}", "type": "number", "initial": 50}
            for i in range(4)
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert any("exceeds maximum 3" in e for e in errors)

    def test_too_many_numeric(self):
        vars_list = [
            {"name": "a", "type": "number", "initial": 50},
            {"name": "b", "type": "number", "initial": 50},
            {"name": "c", "type": "number", "initial": 50},
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert any("numeric" in e.lower() for e in errors)

    def test_too_many_labels(self):
        vars_list = [
            {"name": "a", "type": "string", "initial": "x"},
            {"name": "b", "type": "list", "initial": []},
            {"name": "c", "type": "number", "initial": 50},
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert any("label" in e.lower() for e in errors)

    def test_number_out_of_bounds(self):
        vars_list = [
            {"name": "体力", "type": "number", "initial": 150},
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert any("超出范围" in e or "out of range" in e for e in errors)

    def test_number_below_zero(self):
        vars_list = [
            {"name": "体力", "type": "number", "initial": -10},
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert len(errors) >= 1

    def test_string_empty_initial(self):
        vars_list = [
            {"name": "tag", "type": "string", "initial": ""},
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert any("非空" in e or "empty" in e.lower() for e in errors)

    def test_duplicate_names(self):
        vars_list = [
            {"name": "体力", "type": "number", "initial": 80},
            {"name": "体力", "type": "number", "initial": 50},
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert any("重复" in e or "duplicate" in e.lower() for e in errors)

    def test_list_element_not_string(self):
        vars_list = [
            {"name": "物品", "type": "list", "initial": ["a", 123]},
        ]
        errors = CoCreateParser.validate_variables(vars_list)
        assert any("string" in e.lower() for e in errors)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_co_create.py::TestParseVariables tests/test_co_create.py::TestValidateVariables -v`
预期：FAIL

- [ ] **步骤 3：实现 parse_variables + validate_variables**

在 `CoCreateParser` 类中追加：

```python
    VAR_LINE_RE = re.compile(
        r"^(\S+):\s*(number|string|list),\s*初始\s+(.+)$"
    )

    @staticmethod
    def parse_variables(text: str) -> list[dict]:
        """Parse variables block into list of {name, type, initial} dicts.

        Format: 变量名: 类型, 初始 值

        Args:
            text: Raw text of the variables block.

        Returns:
            List of variable definition dicts.

        Raises:
            ValueError: On parse errors or invalid types/values.
        """
        if not text or not text.strip():
            return []

        result = []
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            m = CoCreateParser.VAR_LINE_RE.match(line)
            if not m:
                raise ValueError(
                    f"Cannot parse variable line: '{line}'. "
                    f"Expected format: 变量名: 类型, 初始 值"
                )

            name = m.group(1)
            var_type = m.group(2)
            raw_initial = m.group(3).strip()

            if var_type not in ("number", "string", "list"):
                raise ValueError(
                    f"Unknown type '{var_type}' for variable '{name}'. "
                    f"Must be number, string, or list."
                )

            if var_type == "number":
                try:
                    initial = int(raw_initial)
                except ValueError:
                    raise ValueError(
                        f"Number variable '{name}' initial value "
                        f"'{raw_initial}' is not an integer."
                    )
            elif var_type == "list":
                if raw_initial in ("[]", ""):
                    initial = []
                else:
                    initial = [s.strip() for s in raw_initial.split(",") if s.strip()]
            else:
                initial = raw_initial

            result.append({"name": name, "type": var_type, "initial": initial})

        return result

    @staticmethod
    def validate_variables(variables: list[dict]) -> list[str]:
        """Validate parsed variable definitions.

        Args:
            variables: List of {name, type, initial} dicts.

        Returns:
            List of error strings. Empty = valid.
        """
        errors = []

        # f: Total count ≤ 3
        if len(variables) > VARIABLE_CAP:
            errors.append(
                f"Variable count {len(variables)} exceeds maximum {VARIABLE_CAP}"
            )

        # a: Name uniqueness + valid chars
        seen_names = set()
        for v in variables:
            name = v["name"]
            if "\n" in name or ":" in name:
                errors.append(
                    f"Variable name '{name}' contains illegal characters"
                )
            if name in seen_names:
                errors.append(f"Duplicate variable name: '{name}'")
            seen_names.add(name)

        # g: Type counts
        num_count = sum(1 for v in variables if v["type"] == "number")
        label_count = sum(1 for v in variables if v["type"] in ("string", "list"))

        if num_count > VARIABLE_NUMERIC_CAP:
            errors.append(
                f"Numeric variables ({num_count}) exceed maximum "
                f"{VARIABLE_NUMERIC_CAP}"
            )
        if label_count > VARIABLE_LABEL_CAP:
            errors.append(
                f"Label variables ({label_count}) exceed maximum "
                f"{VARIABLE_LABEL_CAP}"
            )

        # c-f: Per-variable validation
        for v in variables:
            name = v["name"]
            var_type = v["type"]
            initial = v["initial"]

            if var_type == "number":
                if not isinstance(initial, int):
                    errors.append(
                        f"'{name}': initial value must be integer, got {type(initial).__name__}"
                    )
                elif initial < 0 or initial > 100:
                    errors.append(
                        f"'{name}': initial value {initial} out of range [0, 100]"
                    )
            elif var_type == "string":
                if not initial or not str(initial).strip():
                    errors.append(
                        f"'{name}': string initial value must be non-empty"
                    )
            elif var_type == "list":
                if not isinstance(initial, list):
                    errors.append(
                        f"'{name}': list initial must be a list"
                    )
                else:
                    for i, elem in enumerate(initial):
                        if not isinstance(elem, str):
                            errors.append(
                                f"'{name}': list element [{i}] must be string, "
                                f"got {type(elem).__name__}"
                            )

        return errors
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_co_create.py::TestParseVariables tests/test_co_create.py::TestValidateVariables -v`
预期：PASS（9 + 8 = 17 tests）

- [ ] **步骤 5：Commit**

```bash
git add src/storyloom/co_create.py tests/test_co_create.py
git commit -m "feat: add parse_variables and validate_variables with ≤3 cap

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 5：CoCreateParser.parse_outline + validate_outline + format_outline

**文件：**
- 修改：`src/storyloom/co_create.py`
- 修改：`tests/test_co_create.py`

- [ ] **步骤 1：编写失败的测试**

```python
class TestParseOutline:
    """Tests for parse_outline — [node] block parsing."""

    VALID_OUTLINE = """[node]
id: ch1_intro
title: 霓虹深渊
goal: 在地下城酒吧感受氛围
routes: → ch2_meeting

[node]
id: ch2_meeting
title: 地下交易
goal: 与耗子会面
routes:
  if 信任度 >= 30 → ch3_ally
  if 信任度 < 30 → ch3_betrayal

[node]
id: ch3_ally
title: 盟友之路
goal: 通过地下网络逃离
routes: → ch4_safehouse

[node]
id: ch3_betrayal
title: 背叛之路
goal: 杀出重围
routes: → ch4_safehouse

[node]
id: ch4_safehouse
title: 安全屋
goal: 揭开芯片秘密（结局）
routes: （结局）"""

    def test_parse_valid_branching_outline(self):
        nodes = CoCreateParser.parse_outline(self.VALID_OUTLINE)
        assert len(nodes) == 5
        assert nodes[0]["id"] == "ch1_intro"
        assert nodes[0]["title"] == "霓虹深渊"
        assert nodes[0]["goal"] == "在地下城酒吧感受氛围"
        assert nodes[0]["routes"] == [{"condition": None, "target": "ch2_meeting"}]

    def test_parse_branching_node(self):
        nodes = CoCreateParser.parse_outline(self.VALID_OUTLINE)
        ch2 = nodes[1]
        assert ch2["id"] == "ch2_meeting"
        assert len(ch2["routes"]) == 2
        assert ch2["routes"][0] == {"condition": "信任度 >= 30", "target": "ch3_ally"}
        assert ch2["routes"][1] == {"condition": "信任度 < 30", "target": "ch3_betrayal"}

    def test_parse_ending_node(self):
        nodes = CoCreateParser.parse_outline(self.VALID_OUTLINE)
        ending = nodes[4]
        assert ending["id"] == "ch4_safehouse"
        assert ending["routes"] == []  # （结局）→ no active routes

    def test_parse_linear_outline(self):
        text = """[node]
id: ch1
title: start
goal: begin
routes: → ch2

[node]
id: ch2
title: end
goal: finish
routes: （结局）"""
        nodes = CoCreateParser.parse_outline(text)
        assert len(nodes) == 2

    def test_parse_no_routes_field(self):
        text = """[node]
id: ch1
title: only
goal: solo"""
        nodes = CoCreateParser.parse_outline(text)
        assert len(nodes) == 1
        assert nodes[0]["routes"] == []

    def test_empty_outline_raises_parse_error(self):
        with pytest.raises(ValueError, match="Empty|No nodes"):
            CoCreateParser.parse_outline("")

    def test_node_without_id_raises_parse_error(self):
        text = """[node]
title: missing id
goal: something"""
        with pytest.raises(ValueError, match="Missing 'id'"):
            CoCreateParser.parse_outline(text)

    def test_node_without_title_raises_parse_error(self):
        text = """[node]
id: ch1
goal: something"""
        with pytest.raises(ValueError, match="Missing 'title'"):
            CoCreateParser.parse_outline(text)


class TestValidateOutline:
    """Tests for validate_outline."""

    def _make_nodes(self, *ids_and_targets):
        """Helper: (id, [(condition, target), ...]) → nodes list."""
        nodes = []
        for node_id, routes in ids_and_targets:
            nodes.append({
                "id": node_id,
                "title": node_id,
                "goal": "test",
                "routes": [
                    {"condition": c, "target": t} for c, t in routes
                ],
            })
        return nodes

    def test_all_valid_passes(self):
        nodes = self._make_nodes(
            ("ch1", [(None, "ch2")]),
            ("ch2", [(None, "ch3")]),
            ("ch3", []),
        )
        errors = CoCreateParser.validate_outline(nodes, ["hp"])
        assert errors == []

    def test_route_target_missing_rejected(self):
        nodes = self._make_nodes(
            ("ch1", [(None, "ch2")]),
            ("ch2", [(None, "ch99")]),  # ch99 doesn't exist
        )
        errors = CoCreateParser.validate_outline(nodes, [])
        assert any("ch99" in e for e in errors)

    def test_final_node_has_branches_rejected(self):
        nodes = self._make_nodes(
            ("ch1", [(None, "ch2")]),
            ("ch2", [(None, "ch3")]),  # last but has route
            ("ch3", [(None, "ch1")]),
        )
        errors = CoCreateParser.validate_outline(nodes, [])
        assert any("final" in e.lower() or "最后" in e for e in errors)

    def test_zero_nodes_rejected(self):
        errors = CoCreateParser.validate_outline([], [])
        assert any("1" in e for e in errors)

    def test_unknown_variable_in_condition_warns_only(self):
        nodes = self._make_nodes(
            ("ch1", [("unknown_var > 10", "ch2")]),
            ("ch2", []),
        )
        errors = CoCreateParser.validate_outline(nodes, ["hp"])
        # Should warn but NOT reject (condition var check is soft)
        assert not errors  # soft warning only, logged not returned


class TestFormatOutline:
    """Tests for format_outline — convert [node] blocks to GameLoop format."""

    def test_format_simple_linear_outline(self):
        nodes = [
            {"id": "ch1", "title": "开始", "goal": "开场",
             "routes": [{"condition": None, "target": "ch2"}]},
            {"id": "ch2", "title": "结局", "goal": "收尾",
             "routes": []},
        ]
        result = CoCreateParser.format_outline(nodes)
        assert "ch1 [active] — 开始：开场" in result
        assert "→ ch2 [pending]" in result
        assert "ch2 [pending] — 结局：收尾" in result

    def test_format_branching_outline(self):
        nodes = [
            {"id": "ch1", "title": "起点", "goal": "start",
             "routes": [
                 {"condition": "a > 5", "target": "ch2a"},
                 {"condition": "a <= 5", "target": "ch2b"},
             ]},
            {"id": "ch2a", "title": "A路", "goal": "path a",
             "routes": []},
            {"id": "ch2b", "title": "B路", "goal": "path b",
             "routes": []},
        ]
        result = CoCreateParser.format_outline(nodes)
        assert "├→ ch2a [pending]" in result
        assert "└→ ch2b [pending]" in result

    def test_format_ending_node_no_routes(self):
        nodes = [
            {"id": "ch1", "title": "终", "goal": "end", "routes": []},
        ]
        result = CoCreateParser.format_outline(nodes)
        # Ending node: just node line, no route indentation
        assert "ch1 [active]" in result
        assert "→" not in result  # no routes on ending node
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_co_create.py::TestParseOutline tests/test_co_create.py::TestValidateOutline tests/test_co_create.py::TestFormatOutline -v`
预期：FAIL

- [ ] **步骤 3：实现 parse_outline + validate_outline + format_outline**

在 `CoCreateParser` 类中追加：

```python
    @staticmethod
    def parse_outline(text: str) -> list[dict]:
        """Parse outline block into list of node dicts.

        Args:
            text: Raw text of the outline block.

        Returns:
            List of node dicts, each with keys: id, title, goal, routes.
            routes: list of {condition: str|None, target: str} dicts.

        Raises:
            ValueError: On parse errors or missing required fields.
        """
        if not text or not text.strip():
            raise ValueError("Empty outline block")

        nodes = []
        current: dict | None = None

        for line in text.strip().split("\n"):
            line_stripped = line.strip()

            if line_stripped == "[node]":
                if current:
                    nodes.append(current)
                current = {"id": "", "title": "", "goal": "", "routes": []}
            elif current is not None:
                if line_stripped.startswith("id:"):
                    current["id"] = line_stripped[3:].strip()
                elif line_stripped.startswith("title:"):
                    current["title"] = line_stripped[6:].strip()
                elif line_stripped.startswith("goal:"):
                    current["goal"] = line_stripped[5:].strip()
                elif line_stripped.startswith("routes:"):
                    route_text = line_stripped[7:].strip()
                    if route_text and route_text not in ("（结局）", "(ending)"):
                        # Single route on same line: → target
                        target = route_text.lstrip("→ ").strip()
                        if target:
                            current["routes"].append(
                                {"condition": None, "target": target}
                            )
                    # Multi-line routes handled below
                elif line_stripped.startswith("if ") and "→" in line_stripped:
                    # Indented route: if condition → target
                    parts = line_stripped.split("→", 1)
                    condition = parts[0].strip()
                    if condition.startswith("if "):
                        condition = condition[3:]
                    target = parts[1].strip() if len(parts) > 1 else ""
                    if condition and target:
                        current["routes"].append(
                            {"condition": condition, "target": target}
                        )

        if current:
            nodes.append(current)

        if not nodes:
            raise ValueError("No nodes found in outline")

        # Validate each node has required fields
        for i, node in enumerate(nodes):
            if not node["id"]:
                raise ValueError(f"Node {i + 1}: Missing 'id' field")
            if not node["title"]:
                raise ValueError(f"Node {i + 1} ('{node['id']}'): Missing 'title' field")
            if not node["goal"]:
                raise ValueError(f"Node {i + 1} ('{node['id']}'): Missing 'goal' field")

        return nodes

    @staticmethod
    def validate_outline(
        nodes: list[dict], variable_names: list[str]
    ) -> list[str]:
        """Validate outline structure.

        Args:
            nodes: List of node dicts from parse_outline.
            variable_names: List of valid variable names.

        Returns:
            List of error strings. Empty = valid.
            Soft warnings (variable references, node count) are logged
            but NOT returned as errors.
        """
        errors = []

        # c: Node count ≥ 1
        if len(nodes) == 0:
            errors.append("Outline must have at least 1 node")
            return errors

        node_ids = {n["id"] for n in nodes}

        # a: All route targets exist
        for node in nodes:
            for route in node["routes"]:
                target = route["target"]
                if target not in node_ids:
                    errors.append(
                        f"Node '{node['id']}': route target "
                        f"'{target}' does not exist in outline"
                    )

        # b: Final node has no routes (is ending)
        if len(nodes) > 0:
            final = nodes[-1]
            if final["routes"]:
                errors.append(
                    f"Final node '{final['id']}' has branches but should "
                    f"be the ending node with no routes"
                )

        # d: Route conditions reference valid variables (soft — log warn only)
        # e: Node count in tier range (soft — checked by caller, not here)
        # These are intentionally not returned as errors.

        return errors

    @staticmethod
    def format_outline(nodes: list[dict]) -> str:
        """Convert parsed [node] blocks into GameLoop-compatible outline text.

        Format matches the existing SAMPLE_OUTLINE in main.py:
            ch1_intro [active] — title：goal
              → ch2_meeting [pending]

        Args:
            nodes: List of node dicts from parse_outline.

        Returns:
            Formatted outline string ready for GameLoop / PromptBuilder.
        """
        lines = []
        for i, node in enumerate(nodes):
            status = "[active]" if i == 0 else "[pending]"
            lines.append(f"{node['id']} {status} — {node['title']}：{node['goal']}")

            routes = node["routes"]
            if not routes:
                continue

            for j, route in enumerate(routes):
                is_last = (j == len(routes) - 1)
                prefix = "  └→" if is_last else "  ├→"
                target = route["target"]
                lines.append(f"{prefix} {target} [pending]")

        return "\n".join(lines)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_co_create.py::TestParseOutline tests/test_co_create.py::TestValidateOutline tests/test_co_create.py::TestFormatOutline -v`
预期：PASS（8 + 5 + 3 = 16 tests）

- [ ] **步骤 5：Commit**

```bash
git add src/storyloom/co_create.py tests/test_co_create.py
git commit -m "feat: add outline parser, validator, and GameLoop format converter

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 6：Prompt 模板定义

**文件：**
- 修改：`src/storyloom/co_create.py`

- [ ] **步骤 1：定义系统提示词和生成提示词**

在 `co_create.py` 中 `CoCreateParser` 类之后追加：

```python
# ── Prompt Templates ────────────────────────────────────────────────

CO_CREATE_SYSTEM_PROMPT = """You are a story co-creation assistant. Help the user define their story world through questions, then generate structured story setup.

# Questioning Phase

Ask questions focused on five dimensions. Do NOT ask about specific plot events or reveal story content:
- World setting (era, location, tech/magic level, society)
- Protagonist (name, identity, personality traits, background)
- Story tone (dark/light, epic/personal, serious/humorous)
- Conflict direction (core tension — do not describe specific events)
- Story length (short ~10 rounds / medium ~20 rounds / long ~40 rounds)

Do not reveal plot details, suggest story direction, or use leading wording.

When you have enough information (usually 3-5 questions), end your reply with:
"Is there enough information to start generating the story?"

When the user indicates they are ready, I will ask you to generate the full setup.

# Generation Phase

When asked to generate the full setup, output ALL THREE sections below in order. Use EXACTLY the format shown.

## Section 1: story_config

```
=== story_config ===
genre: {free text, e.g. "cyberpunk adventure", "historical mystery"}
tier: {short / medium / long}
setting: {one sentence: era, location, key world facts}
protagonist_name: {name}
protagonist_identity: {one sentence}
protagonist_traits: {2-3 key traits}
tone: {e.g. "dark and gritty", "light and humorous"}
conflict: {one sentence, core tension}
characters:
  {name} | {role} | {relationship to protagonist}
  (at least 1)
```

## Section 2: variables

Design state variables for this story. Rules:
- ≤3 variables total. ≤2 numeric (number), ≤1 label (string/list).
- Numeric: range [0, 100]. Use for health, trust, sanity, etc.
- String: for status markers, faction affiliation, etc.
- List: elements are strings. For inventory, clues, skills, etc.
- Variable names in Chinese, 2-5 characters.
- Fewer is better. Only create variables that will drive branching or gate choices.

Genre seed reference (adopt or adapt based on the story; replace if unsuitable):
  Romance → affection
  Mystery → clues_progress
  Cyberpunk → implant_integrity
  Wuxia → inner_power
  Horror → sanity

```
=== variables ===
体力: number, 初始 80
信任度: number, 初始 10
所属势力: string, 初始 自由佣兵
```

## Section 3: outline

Design a directed graph of key story nodes. Rules:
- Node count by tier: short 3-5 / medium 5-8 / long 8-15
- Each node has a clear narrative goal
- Branches use `if {condition} → {target_node}`. Conditions may only reference declared variables.
- Final node is the ending (no branches).
- node_id format: ch{number}_{english_abbreviation}

```
=== outline ===
[node]
id: ch1_intro
title: {node title}
goal: {narrative goal of this node}
routes: → ch2_next

[node]
id: ch2_next
title: {node title}
goal: {narrative goal}
routes:
  if 信任度 >= 30 → ch3_path_a
  if 信任度 < 30 → ch3_path_b

[node]
id: ch3_path_a
title: {node title}
goal: {narrative goal}
routes: → ch4_ending

[node]
id: ch3_path_b
title: {node title}
goal: {narrative goal}
routes: → ch4_ending

[node]
id: ch4_ending
title: {node title}
goal: {narrative goal}（结局）
routes: （结局）
```

Output all three sections in a single response. Do not add commentary before or after."""


GENERATE_ALL_PROMPT = """Based on our conversation above, generate the complete story setup.

Output ALL THREE sections: story_config, variables, and outline.
Follow the format exactly as specified in the system instructions.

Available variables for the outline: {variable_names}"""
```

- [ ] **步骤 2：验证模块可导入且 Prompt 内容正确**

运行：`python3 -c "
from src.storyloom.co_create import CO_CREATE_SYSTEM_PROMPT, GENERATE_ALL_PROMPT
assert 'story_config' in CO_CREATE_SYSTEM_PROMPT
assert 'variables' in CO_CREATE_SYSTEM_PROMPT
assert 'outline' in CO_CREATE_SYSTEM_PROMPT
assert 'questioning' in CO_CREATE_SYSTEM_PROMPT.lower()
assert 'variable_names' in GENERATE_ALL_PROMPT
print('Prompts OK')
"`
预期：`Prompts OK`

- [ ] **步骤 3：Commit**

```bash
git add src/storyloom/co_create.py
git commit -m "feat: add co-creation system prompt and generation prompt templates

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 7：CoCreateFlow — 流程编排类

**文件：**
- 修改：`src/storyloom/co_create.py`
- 修改：`tests/test_co_create.py`

- [ ] **步骤 1：定义 CoCreationResult + CoCreateFlow 框架**

在 `co_create.py` 末尾追加：

```python
# ── Exceptions ──────────────────────────────────────────────────────

class CoCreationAborted(Exception):
    """Raised when user chooses to abort co-creation and return to menu."""
    pass


# ── Result ───────────────────────────────────────────────────────────

@dataclass
class CoCreationResult:
    """Output of the co-creation phase, ready for GameLoop."""
    story_config: dict
    outline_text: str


# ── Flow ─────────────────────────────────────────────────────────────

class CoCreateFlow:
    """Orchestrates the full co-creation phase.

    Flow:
        Step 1: User inputs raw story idea.
        Step 2: Multi-turn Q&A loop with LLM.
        Step 3: Single LLM call generates story_config + variables + outline.
        Step 4: Validate everything, retry on failure, return result.
    """

    def __init__(self, api_client: ApiClient, display: Display):
        """Initialize co-creation flow.

        Args:
            api_client: API client for LLM calls.
            display: Display instance for terminal I/O.
        """
        self._api = api_client
        self._display = display
        self._messages: list[dict] = [
            {"role": "system", "content": CO_CREATE_SYSTEM_PROMPT}
        ]

    def run(self) -> CoCreationResult:
        """Run the full co-creation flow.

        Returns:
            CoCreationResult with story_config (including variables)
            and formatted outline_text.

        Raises:
            CoCreationAborted: If user chooses to abort.
        """
        self._step1_get_idea()
        self._step2_questioning()
        return self._step3_generate_all()
```

- [ ] **步骤 2：验证模块可导入**

运行：`python3 -c "
from src.storyloom.co_create import CoCreateFlow, CoCreationResult, CoCreationAborted
print('Flow classes OK')
"`
预期：`Flow classes OK`

- [ ] **步骤 3：Commit**

```bash
git add src/storyloom/co_create.py
git commit -m "feat: add CoCreateFlow skeleton with CoCreationResult dataclass

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 8：CoCreateFlow._step1_get_idea + _step2_questioning

**文件：**
- 修改：`src/storyloom/co_create.py`

- [ ] **步骤 1：实现 Step 1 和 Step 2**

在 `CoCreateFlow` 类中追加 `_step1_get_idea` 和 `_step2_questioning` 方法：

```python
    def _step1_get_idea(self) -> None:
        """Step 1: Collect user's initial story idea."""
        self._display.output.write("\n")
        self._display.output.write("━" * 50 + "\n")
        self._display.output.write("【共创阶段 — 故事设定】\n\n")
        self._display.output.write(
            "请描述你想玩的故事。\n"
            "例如：'赛博朋克背景下的爱情故事'、'古代仙侠世界的冒险'\n\n"
        )

        while True:
            raw_idea = self._display.get_input("> ")
            if raw_idea and raw_idea.strip():
                break
            self._display.output.write("请输入一些想法来开始。\n")

        self._messages.append({"role": "user", "content": raw_idea.strip()})

    def _step2_questioning(self) -> None:
        """Step 2: Multi-turn Q&A loop with LLM.

        LLM asks questions about 5 dimensions. User responds.
        Loop exits when user types '开始' or LLM indicates readiness.
        """
        self._display.output.write("\n")
        self._display.output.write("━" * 50 + "\n")
        self._display.output.write(
            "【追问阶段】\n"
            "AI 会提出几个问题来了解你想玩的故事。\n"
            "回答完毕后输入 '开始' 即可生成故事设定。\n"
            "输入 '不玩了' 返回主菜单。\n\n"
        )

        while True:
            # Call LLM for next question
            self._display.show_wait_message("思考中...")
            try:
                response = self._api.chat(self._messages)
            except Exception as e:
                self._display.show_error(f"API 调用失败: {e}")
                choice = self._display.get_input(
                    "[R]重试 / [M]返回主菜单: "
                )
                if choice.upper() == 'M':
                    raise CoCreationAborted()
                continue

            self._messages.append({"role": "assistant", "content": response})
            self._display.output.write(f"\n{response}\n\n")

            # Check if LLM is asking to start
            if "是否开始生成故事" in response:
                user_input = self._display.get_input("> ")
            else:
                user_input = self._display.get_input("你的回答（或输入 '开始'/'不玩了'）> ")

            user_input = user_input.strip()
            if not user_input:
                continue

            # Exit conditions
            if user_input in ("开始", "开始吧", "可以", "好的", "行", "ok", "OK", "yes", "go"):
                self._display.output.write("\n")
                break

            if user_input in ("不玩了", "退出", "quit", "exit", "q"):
                confirm = self._display.get_input("确定退出共创，返回主菜单？(y/n): ")
                if confirm.lower() in ("y", "yes", "是"):
                    raise CoCreationAborted()
                continue

            self._messages.append({"role": "user", "content": user_input})
```

- [ ] **步骤 2：验证语法正确**

运行：`python3 -c "from src.storyloom.co_create import CoCreateFlow; print('OK')"`
预期：`OK`

- [ ] **步骤 3：Commit**

```bash
git add src/storyloom/co_create.py
git commit -m "feat: implement co-creation step1 (user idea) and step2 (Q&A loop)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 9：CoCreateFlow._step3_generate_all — 生成 + 解析 + 重试

**文件：**
- 修改：`src/storyloom/co_create.py`

- [ ] **步骤 1：实现 _step3_generate_all 方法**

在 `CoCreateFlow` 类的 `_step2_questioning` 之后追加：

```python
    def _step3_generate_all(self) -> CoCreationResult:
        """Step 3: Single LLM call → parse all three blocks → validate.

        Returns:
            CoCreationResult ready for GameLoop.

        Raises:
            CoCreationAborted: If user aborts after retry exhaustion.
        """
        # Build generation prompt
        var_names = self._build_var_names_hint()

        gen_prompt = GENERATE_ALL_PROMPT.format(variable_names=var_names)
        self._messages.append({"role": "user", "content": gen_prompt})

        # Generate
        self._display.show_wait_message("正在编织故事世界...")
        response = self._generate_with_retry()
        self._messages.append({"role": "assistant", "content": response})

        # Split into blocks
        blocks = CoCreateParser.split_blocks(response)

        # Parse and validate each block
        story_config = self._parse_story_config_with_retry(blocks["story_config"])
        variables = self._parse_variables_with_retry(blocks["variables"])
        outline_nodes = self._parse_outline_with_retry(blocks["outline"])

        # Validate outline against variable names
        var_names_list = [v["name"] for v in variables]
        outline_errors = CoCreateParser.validate_outline(outline_nodes, var_names_list)
        if outline_errors:
            outline_nodes = self._retry_outline_validation(
                outline_errors, var_names_list
            )

        # Assemble result
        story_config["variables"] = variables
        outline_text = CoCreateParser.format_outline(outline_nodes)

        return CoCreationResult(
            story_config=story_config,
            outline_text=outline_text,
        )

    def _build_var_names_hint(self) -> str:
        """Build variable names hint for generation prompt.

        Returns a string like: "Available variables: 暂无（由你设计）"
        since at generation time we haven't parsed variables yet.
        """
        return "由你根据故事设计（≤3个，≤2 numeric + ≤1 string/list）"

    def _generate_with_retry(self) -> str:
        """Call LLM for generation. Handle API errors.

        Returns:
            Raw LLM response text.

        Raises:
            CoCreationAborted: If user chooses to abort.
        """
        while True:
            try:
                return self._api.chat(self._messages)
            except Exception as e:
                self._display.show_error(f"生成失败: {e}")
                choice = self._display.get_input(
                    "[R]重试 / [M]返回主菜单: "
                )
                if choice.upper() == 'M':
                    raise CoCreationAborted()

    def _parse_story_config_with_retry(self, text: str) -> dict:
        """Parse story_config block with retry on failure.

        Args:
            text: Raw story_config block text.

        Returns:
            Parsed story_config dict.

        Raises:
            CoCreationAborted: If user chooses to abort after retries.
        """
        return self._retry_block(
            text=text,
            block_name="story_config",
            parse_fn=CoCreateParser.parse_story_config,
            validate_fn=lambda d: (
                [] if d.get("tier") in {"short", "medium", "long"}
                else ["tier must be short/medium/long"]
            ),
        )

    def _parse_variables_with_retry(self, text: str) -> list[dict]:
        """Parse variables block with retry on failure.

        Args:
            text: Raw variables block text.

        Returns:
            Parsed and validated variables list.

        Raises:
            CoCreationAborted: If user chooses to abort after retries.
        """
        return self._retry_block(
            text=text,
            block_name="variables",
            parse_fn=CoCreateParser.parse_variables,
            validate_fn=CoCreateParser.validate_variables,
        )

    def _parse_outline_with_retry(self, text: str) -> list[dict]:
        """Parse outline block with retry on failure.

        Args:
            text: Raw outline block text.

        Returns:
            Parsed outline node list.

        Raises:
            CoCreationAborted: If user chooses to abort after retries.
        """
        # Parse first, validate after we have variable names
        return self._retry_block(
            text=text,
            block_name="outline",
            parse_fn=CoCreateParser.parse_outline,
            validate_fn=lambda nodes: (
                [] if nodes else ["No nodes found"]
            ),
        )

    def _retry_outline_validation(
        self, errors: list[str], var_names: list[str]
    ) -> list[dict]:
        """Handle outline validation errors with retry.

        Each attempt: append error to messages → LLM regenerates full
        response → re-split → re-parse outline → re-validate.

        Args:
            errors: Initial validation error messages.
            var_names: Valid variable names.

        Returns:
            Validated outline nodes.

        Raises:
            CoCreationAborted: If user aborts.
        """
        for attempt in range(MAX_RETRIES + 1):
            error_msg = "Outline errors: " + "; ".join(errors)
            self._messages.append(
                {"role": "user",
                 "content": f"Outline has errors. {error_msg}\n"
                           f"Please fix and regenerate the outline block."}
            )
            self._display.show_wait_message(
                f"修正大纲中...（第{attempt + 1}次重试）"
            )
            response = self._generate_with_retry()
            self._messages.append({"role": "assistant", "content": response})

            blocks = CoCreateParser.split_blocks(response)
            try:
                nodes = CoCreateParser.parse_outline(blocks["outline"])
            except ValueError as e:
                errors = [str(e)]
                continue

            errors = CoCreateParser.validate_outline(nodes, var_names)
            if not errors:
                return nodes

        # Exhausted retries
        choice = self._display.get_input(
            f"大纲校验失败（{'; '.join(errors)}）。"
            f"[R]重试 / [M]返回主菜单: "
        )
        if choice.upper() == 'R':
            # Remove last retry pair, try fresh cycle
            self._messages = self._messages[:-2]
            return self._retry_outline_validation(errors, var_names)
        raise CoCreationAborted()

    def _retry_block(
        self,
        text: str,
        block_name: str,
        parse_fn,
        validate_fn,
    ):
        """Parse a block with retry on failure.

        On parse/validation failure, appends error to messages and regenerates
        the FULL response (LLM regenerates all three blocks; previously-valid
        blocks serve as in-context anchors).

        Args:
            text: Raw block text (initial attempt).
            block_name: Human-readable block name for error messages.
            parse_fn: Callable that parses text into structured data.
            validate_fn: Callable that returns list of error strings.

        Returns:
            Parsed and validated data.

        Raises:
            CoCreationAborted: If user chooses to abort after retries.
        """
        # First attempt with initial text
        for attempt in range(MAX_RETRIES + 1):
            try:
                parsed = parse_fn(text)
                errors = validate_fn(parsed)
                if not errors:
                    return parsed
            except ValueError as e:
                errors = [str(e)]

            if attempt < MAX_RETRIES:
                error_msg = f"{block_name} errors: {'; '.join(errors)}"
                self._messages.append(
                    {"role": "user",
                     "content": f"Previous {block_name} had errors. {error_msg}\n"
                               f"Please fix and regenerate all three sections."}
                )
                self._display.show_wait_message(
                    f"修正{block_name}中...（第{attempt + 1}次重试）"
                )
                response = self._generate_with_retry()
                self._messages.append({"role": "assistant", "content": response})
                blocks = CoCreateParser.split_blocks(response)
                text = blocks[block_name]
                continue

        # Retries exhausted
        choice = self._display.get_input(
            f"{block_name} 解析失败（{'; '.join(errors)}）。"
            f"[R]重试 / [M]返回主菜单: "
        )
        if choice.upper() == 'R':
            self._messages = self._messages[:-2]  # remove last retry pair
            return self._retry_block(
                text=text,
                block_name=block_name,
                parse_fn=parse_fn,
                validate_fn=validate_fn,
            )
        raise CoCreationAborted()
```

- [ ] **步骤 2：验证语法正确**

运行：`python3 -c "from src.storyloom.co_create import CoCreateFlow; print('OK')"`
预期：`OK`

- [ ] **步骤 3：Commit**

```bash
git add src/storyloom/co_create.py
git commit -m "feat: implement co-creation step3 — generate, parse, validate with retry

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 10：集成测试 — Mock API 端到端流程

**文件：**
- 修改：`tests/test_co_create.py`

- [ ] **步骤 1：编写集成测试**

在 `tests/test_co_create.py` 末尾追加：

```python
# ── Integration Tests ────────────────────────────────────────────────

class MockApiClient:
    """Mock API client that returns predefined responses."""

    def __init__(self, responses=None):
        self.responses = responses or []
        self.call_count = 0
        self.messages_history = []

    def chat(self, messages):
        self.messages_history.append(messages)
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        return ""

    def stream_chat(self, messages):
        return self.chat(messages)


class MockDisplay:
    """Mock display that captures output and returns predefined inputs."""

    def __init__(self, inputs=None):
        self.inputs = list(inputs or [])
        self._input_idx = 0
        self.written = []

    @property
    def output(self):
        return self

    def write(self, text):
        self.written.append(text)

    def flush(self):
        pass

    def get_input(self, prompt=""):
        if self._input_idx < len(self.inputs):
            val = self.inputs[self._input_idx]
            self._input_idx += 1
            return val
        return ""

    def show_wait_message(self, msg):
        pass

    def show_error(self, msg):
        pass


FULL_GENERATION_RESPONSE = """=== story_config ===
genre: 赛博朋克冒险
tier: medium
setting: 2087年新东京地下城
protagonist_name: 林焰
protagonist_identity: 前荒坂安全顾问，现自由佣兵
protagonist_traits: 冷静、道德灰色
tone: 黑暗冷峻
conflict: 一枚神秘芯片正在寻找宿主
characters:
  耗子 | 地下情报贩子 | 亦敌亦友
  美智子 | 荒坂安全主管 | 前上司

=== variables ===
体力: number, 初始 80
信任度: number, 初始 10
所属势力: string, 初始 自由佣兵

=== outline ===
[node]
id: ch1_intro
title: 霓虹深渊
goal: 在地下城酒吧感受氛围
routes: → ch2_meeting

[node]
id: ch2_meeting
title: 地下交易
goal: 与耗子会面
routes:
  if 信任度 >= 30 → ch3_ally
  if 信任度 < 30 → ch3_betrayal

[node]
id: ch3_ally
title: 盟友之路
goal: 通过地下网络逃离
routes: → ch4_safehouse

[node]
id: ch3_betrayal
title: 背叛之路
goal: 杀出重围
routes: → ch4_safehouse

[node]
id: ch4_safehouse
title: 安全屋
goal: 揭开芯片秘密（结局）
routes: （结局）"""


class TestCoCreateFlow:
    """Integration tests for full co-creation flow with mock API."""

    def test_full_flow_success(self):
        """End-to-end: user provides idea, LLM asks one question, generates."""
        mock_api = MockApiClient(responses=[
            "这是一个有趣的题材。主角是男性还是女性？",
            FULL_GENERATION_RESPONSE,
        ])
        mock_display = MockDisplay(inputs=[
            "赛博朋克背景下的冒险故事",  # Step 1: raw idea
            "男性，前雇佣兵",            # Step 2: answer question
            "开始",                     # Step 2: start signal
        ])

        from src.storyloom.co_create import CoCreateFlow
        flow = CoCreateFlow(mock_api, mock_display)
        result = flow.run()

        assert result.story_config["genre"] == "赛博朋克冒险"
        assert result.story_config["tier"] == "medium"
        assert len(result.story_config["variables"]) == 3
        assert result.story_config["variables"][0]["name"] == "体力"
        assert "ch1_intro [active]" in result.outline_text
        assert "ch4_safehouse [pending]" in result.outline_text

    def test_qna_loop_user_says_start_immediately(self):
        """User can say '开始' on first question to skip to generation."""
        mock_api = MockApiClient(responses=[
            "你想玩什么题材的故事？",
            FULL_GENERATION_RESPONSE,
        ])
        mock_display = MockDisplay(inputs=[
            "科幻冒险",
            "开始",
        ])

        from src.storyloom.co_create import CoCreateFlow
        flow = CoCreateFlow(mock_api, mock_display)
        result = flow.run()

        assert result.story_config["genre"] == "赛博朋克冒险"

    def test_qna_loop_user_aborts(self):
        """User types '不玩了' → should raise CoCreationAborted."""
        mock_api = MockApiClient(responses=[
            "你想玩什么题材的故事？",
        ])
        mock_display = MockDisplay(inputs=[
            "科幻",
            "不玩了",
            "y",  # confirm quit
        ])

        from src.storyloom.co_create import CoCreateFlow, CoCreationAborted
        flow = CoCreateFlow(mock_api, mock_display)

        with pytest.raises(CoCreationAborted):
            flow.run()

    def test_generation_parse_error_retry_then_success(self):
        """First generation has bad story_config → retry fixes it."""
        bad_response = """=== story_config ===
genre: fantasy
tier: epic
setting: somewhere

=== variables ===
hp: number, 初始 80

=== outline ===
[node]
id: ch1
title: start
goal: begin
routes: （结局）"""

        good_response = FULL_GENERATION_RESPONSE

        mock_api = MockApiClient(responses=[
            "你想玩什么题材？",
            bad_response,   # generation fails (tier: epic)
            good_response,  # retry succeeds
        ])
        mock_display = MockDisplay(inputs=[
            "科幻",
            "开始",
            "R",  # after first failure, choose retry
        ])

        from src.storyloom.co_create import CoCreateFlow
        flow = CoCreateFlow(mock_api, mock_display)
        result = flow.run()

        assert result.story_config["tier"] == "medium"

    def test_generation_retry_exhausted_user_aborts(self):
        """All retries fail → user chooses menu → CoCreationAborted."""
        bad_response = """=== story_config ===
genre: fantasy

=== variables ===
hp: number, 初始 80

=== outline ===
[node]
id: ch1
title: start
goal: begin
routes: （结局）"""

        # 3 attempts (initial + 2 retries), all fail
        mock_api = MockApiClient(responses=[
            "Question?",
            bad_response,
            bad_response,  # retry 1
            bad_response,  # retry 2
        ])
        mock_display = MockDisplay(inputs=[
            "sci-fi",
            "开始",
            "M",  # after retries exhausted, choose menu
        ])

        from src.storyloom.co_create import CoCreateFlow, CoCreationAborted
        flow = CoCreateFlow(mock_api, mock_display)

        with pytest.raises(CoCreationAborted):
            flow.run()

    def test_empty_input_in_step1_reprompted(self):
        """Empty input in step 1 should reprompt."""
        mock_api = MockApiClient(responses=[
            "What genre?",
            FULL_GENERATION_RESPONSE,
        ])
        mock_display = MockDisplay(inputs=[
            "",           # empty → reprompt
            "   ",        # whitespace → reprompt
            "sci-fi",     # valid
            "开始",
        ])

        from src.storyloom.co_create import CoCreateFlow
        flow = CoCreateFlow(mock_api, mock_display)
        result = flow.run()
        assert result.story_config["genre"] == "赛博朋克冒险"
```

- [ ] **步骤 2：运行集成测试**

运行：`pytest tests/test_co_create.py::TestCoCreateFlow -v`
预期：PASS（6 tests）

- [ ] **步骤 3：运行全部测试确认无回归**

运行：`pytest tests/ -v`
预期：全部 PASS（现有测试 + 新测试）

- [ ] **步骤 4：Commit**

```bash
git add tests/test_co_create.py
git commit -m "test: add co-creation integration tests with mock API

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 11：main.py 集成 — 接入共创 + --quick 模式

**文件：**
- 修改：`src/storyloom/main.py`

- [ ] **步骤 1：修改 main.py**

在 `main.py` 中：

```python
# 在 import 区域追加
from src.storyloom.co_create import CoCreateFlow, CoCreationAborted

# 修改 run_game 函数签名，接受可选的 story_config 和 outline_text
def run_game(
    display: Display,
    api_client: ApiClient,
    story_config: dict | None = None,
    outline_text: str | None = None,
) -> None:
    """Run the narrative game loop.

    Args:
        display: Display instance for output.
        api_client: API client for LLM calls.
        story_config: Story config (from co-creation or default).
        outline_text: Outline text (from co-creation or default).
    """
    if story_config is None:
        story_config = DEFAULT_STORY_CONFIG
    if outline_text is None:
        outline_text = SAMPLE_OUTLINE

    game_state = GameState(story_config)

    game_loop = GameLoop(
        story_config=story_config,
        outline_text=outline_text,
        api_client=api_client,
        display=display,
        game_state=game_state,
        current_node=_extract_first_node(outline_text),
        goal=_extract_first_goal(outline_text),
    )

    try:
        result = game_loop.start_round1()
    except ApiError as e:
        display.show_error(f"API 错误: {e}")
        return

    # Main narrative loop (unchanged)
    while True:
        options = game_loop.get_available_options()

        if not options:
            try:
                result = game_loop.continue_round(choice_key=None)
            except ApiError as e:
                display.show_error(f"API 错误: {e}")
                break
            continue

        choice = display.get_input("\n输入选择 (输入 quit 返回菜单): ")

        if choice and choice.strip().lower() in ("quit", "exit", "q"):
            display.output.write("返回主菜单。\n")
            return

        if choice and choice.strip().isdigit():
            idx = int(choice.strip())
            if 1 <= idx <= len(options):
                try:
                    result = game_loop.continue_round(choice_key=choice.strip())
                except ApiError as e:
                    display.show_error(f"API 错误: {e}")
                    break
            else:
                display.output.write(f"无效选择，请输入 1-{len(options)}。\n")
        elif choice == "0":
            display.show_state(game_loop.game_state.state_vars)
        else:
            display.output.write("请输入数字或 quit。\n")


def _extract_first_node(outline_text: str) -> str:
    """Extract first node ID from outline text."""
    for line in outline_text.strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("├") and not line.startswith("└") and not line.startswith("→"):
            parts = line.split()
            if parts:
                return parts[0]
    return ""


def _extract_first_goal(outline_text: str) -> str:
    """Extract first node goal from outline text."""
    for line in outline_text.strip().split("\n"):
        line = line.strip()
        if "：" in line:
            return line.split("：", 1)[1].strip()
    return ""


# 修改 show_main_menu 中选项 [1] 的处理
def show_main_menu(display: Display, api_client: ApiClient) -> None:
    """Show main menu and route user choices."""
    while True:
        display.show_main_menu(save_count=0)
        choice = display.get_input("请选择: ")

        if choice == "1":
            # Run co-creation flow
            try:
                flow = CoCreateFlow(api_client, display)
                result = flow.run()
                run_game(display, api_client,
                         story_config=result.story_config,
                         outline_text=result.outline_text)
            except CoCreationAborted:
                display.output.write("已返回主菜单。\n")
            except ApiError as e:
                display.show_error(f"API 错误: {e}")
        elif choice == "2":
            display.show_wait_message("继续游戏（加载存档）—— 功能开发中")
        elif choice == "3":
            display.show_wait_message("管理存档 —— 功能开发中")
        elif choice == "4":
            display.output.write("再会。\n")
            break
        else:
            display.output.write("无效选择，请重试。\n")
```

同时在 `parse_args` 中添加 `--quick` 参数：

```python
def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Storyloom — AI-powered interactive text fiction"
    )
    parser.add_argument("--quick", action="store_true",
                        help="Skip co-creation, use default story")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug output")
    return parser.parse_args(argv)
```

在 `main()` 函数中添加 `--quick` 处理：

```python
def main(output=None) -> None:
    args = parse_args()
    display = Display(output=output)

    display.output.write("\n")
    display.output.write("Storyloom — 文字冒险\n")
    display.output.write("=" * 40 + "\n\n")

    try:
        api_client = ApiClient()
    except RuntimeError as e:
        display.show_error(str(e))
        display.show_error("请复制 .env.example 为 .env 并填入 API 配置。")
        return

    if args.quick:
        # Skip co-creation, jump straight to game with defaults
        run_game(display, api_client)
    else:
        show_main_menu(display, api_client)
```

- [ ] **步骤 2：验证语法正确**

运行：`python3 -c "from src.storyloom.main import main, run_game; print('OK')"`
预期：`OK`

- [ ] **步骤 3：运行全部测试**

运行：`pytest tests/ -v`
预期：全部 PASS

- [ ] **步骤 4：Commit**

```bash
git add src/storyloom/main.py
git commit -m "feat: wire co-creation flow into main menu, add --quick flag

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### 任务 12：最终验证

**文件：** 无

- [ ] **步骤 1：运行全部单元测试**

运行：`pytest tests/test_co_create.py tests/test_prompt_builder.py tests/test_context_manager.py tests/test_xml_parser.py tests/test_integration.py tests/test_game_loop.py -v`
预期：全部 PASS，无回归

- [ ] **步骤 2：验证 --quick 模式可导入**

运行：`python3 -m src.storyloom.main --quick --help`
预期：显示 help 信息，不崩溃

- [ ] **步骤 3：验证默认配置仍然有效**

运行：`python3 -c "
from src.storyloom.main import DEFAULT_STORY_CONFIG, SAMPLE_OUTLINE
from src.storyloom.game_loop import GameState
gs = GameState(DEFAULT_STORY_CONFIG)
assert '体力' in gs.state_vars
print('Default config OK')
"`
预期：`Default config OK`

- [ ] **步骤 4：最终 Commit（如有修改）**
