"""Build Round 1 and Round N prompt content for conversation-based architecture."""

from src.storyloom.config import SEGMENTS_PER_ROUND_MIN, SEGMENTS_PER_ROUND_MAX


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
            story_config: Story configuration dict.
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
            rejected_changes: Rejected state change descriptions.
            format_error: Format error hint from last round.

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
            parts.append(
                f"\n格式提醒：上一轮输出存在格式问题——{format_error}。"
                f"请严格遵循 XML 格式规范。"
            )

        # Bridge text
        parts.append(f"\n上一轮结尾：\n{bridge_text}")

        return "\n".join(parts)

    @staticmethod
    def _format_state_vars(variables: list[dict]) -> str:
        """Format variable definitions for display in Round 1 prompt."""
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
