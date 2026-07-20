# Prompt 设计规范

> **定位**：所有 LLM 调用的 Prompt 规范与全文。本文档是 `prompt_builder` 模块的实现标准。
> **配套文档**：
> - [`exec-flow.md`](./exec-flow.md) — 何时调用、调用结果如何流转
> - [`block-spec.md`](./block-spec.md) — XML 元素语法（LLM 侧遵守，程序侧解析）
> - [`data-model.md`](./data-model.md) — 常量引用
>
> **架构变更（2026-07-04）**：从每轮独立 system prompt 迁移到**对话式消息数组**（Round 1 永久锚定 + 滑动窗口）。`prompt_builder.py` 现在构建单个消息的内容，`context_manager.py` 管理 messages 数组结构。
>
> **迭代策略**：每次 LLM 生成质量问题的根因分析与 Prompt 调整，均记录到 §6 迭代日志。
>
> **阅读约定**：
> - **规范**：描述 Prompt 的结构、各部分的作用、占位符的来源和填充规则。是 `prompt_builder` 的开发标准。
> - **Prompt**：代码块中的文本即程序实际发送给 LLM 的内容。模板含 `{占位符}`，示例含具体值。可直接复制测试。

---

## §1 设计原则

### 1.1 结构原则

| 原则 | 说明 |
|------|------|
| **示例先行** | Prompt 中先放完整格式示例，再用简短规则补充约束。LLM 模仿示例比遵循文字规则更准确 |
| **信息分层** | System Prompt 三段式：示例（格式模板）→ 规则（量化约束）→ 上下文（故事素材） |
| **英文 Prompt** | 所有 Prompt 使用英文（以 `tests/prompt_lab/data/prompts/round1-linenum.txt` 为准），通过 `{language}` 占位符指示 LLM 以故事语言输出 |
| **紧凑但完整** | 重要信息一个字不能少，不重要信息一个字不多 |
| **持续迭代** | 每次发现系统性偏离时，分析原因、调整 Prompt、记录日志 |

### 1.2 约束有效性原则（2026-07-04 实验验证）

> 以下原则经 6 轮迭代、30+ 次测试验证。核心洞察：**LLM 对"不能做什么"的学习依赖显式规则，而非从示例推断。**

| # | 原则 | 说明 | 示例 |
|---|------|------|------|
| 1 | **反例约束** | 对每个关键约束给出具体的错误案例。只说"禁止修改"不够——给出会被拒绝的具体写法 | `禁止 ch2_confrontation_resolved（拼接后缀）` |
| 2 | **正反双重覆盖** | 关键约束在正面规则和负面禁止中各出现一次。单次提及的被漏看概率 ~30%，双重覆盖后 ~0% | 正面：`必须使用 :main 分支`；负面：`禁止使用非 :main 分支` |
| 3 | **注意力标签** | 用 `（重要）` 标记最易出错的规则节。LLM 的注意力资源有限，标签指引优先分配 | `**checkpoint（重要）**`、`**options（重要）**` |
| 4 | **示例-规则屏障** | 格式示例结束后加一行显式提醒，防止 LLM 将示例当作自己的输出继续编号 | `（以上为格式示例。你的输出是全新的剧情段，必须从 1 开始编号。）` |
| 5 | **具体优于抽象** | 给出具体数字和案例，而非比例或一般性描述。LLM 对"40%"的计算不可靠，但看到"32 段后"就能执行 | `总 80 段 → bridge 在第 32 段后 ✓` |
| 6 | **显式禁止优于隐式模式** | 不要依赖示例教会 LLM"不能做什么"。示例展示正确格式，规则定义禁止边界 | 独立的 `**禁止**` 节，逐条列出禁止行为 |
| 7 | **关键处不吝笔墨** | 整体追求紧凑，但在反复出错的规则上多花 tokens。checkpoint 和 options 的正确率从 33%→100% 靠的是规则更详细，不是更短 |

### 1.3 迭代方法论

每轮 Prompt 测试关注三个维度：
- **正确性**：choice 声明、分支命名、node 引用、编号起始
- **无缝性**：TTFT vs tail 段的 gap
- **一致性**：bridge 位置、段数范围的离散度

发现问题 → 定位根因 → 应用 §1.2 原则 → 对比测试 → 记录日志。

---

## §2 各阶段 Prompt 一览

| 阶段 | 调用时机 | 输出格式 | 详见 |
|------|---------|---------|------|
| 追问循环 | 共创 Step 2（多轮） | 自由对话 | §3.1 |
| 故事生成 | 共创 Step 3（单次调用） | `=== story_config ===` + `=== variables ===` + `=== outline ===` | §3.2–3.4 |
| 叙事循环 | 每轮 | XML 文档（`<story>` + `<seg>`/`<choice>`/`<set>`/`<checkpoint>`/`<bridge/>`/`<branch>`） | §4 |
| 冒险日志 | 结局 | Markdown 纯文本 | §5 |

---

## §3 共创阶段 Prompt

### 3.1 追问循环

#### 规范

- **角色**：故事共创助手。通过提问帮助用户明确想体验的故事，自由、真诚地与用户对话。
- **参考维度**：世界观、主角设定、基调、冲突方向、故事长度——作为引导而非清单。
- **终止条件**：用户通过 UI 决定何时进入生成阶段（如 `/go` 或点击按钮）。LLM 可自然表达信息已足够，但最终由用户决定。引擎侧不做关键词检测。

#### Prompt

> 实际 Prompt 为 `CO_CREATE_SYSTEM_PROMPT`（`co_create.py`），通过 `string.Template` 注入语言上下文。以下为中文环境下的等效内容：

```
你是一个故事共创助手。你的任务是通过对话收集信息——不是生成故事。对话结束后，后续步骤会将我们的讨论作为素材生成故事设定。

以下是一些可参考的探索维度——作为引导而非清单：
- 世界观设定（时代、地点、科技/魔法水平、社会结构）
- 主角设定（姓名、性别、身份、性格特质、背景）
- 故事基调（黑暗/轻松、史诗/个人、严肃/幽默）
- 冲突方向（核心矛盾是什么，不透露具体事件）
- 故事长度（短篇约 10 轮 / 中篇约 20 轮 / 长篇约 40 轮）

每个问题后附 2-3 个示例建议帮助用户表达——他们也可以写自己的答案。

重要规则：
- 此阶段禁止生成故事内容、叙事或大纲。你的唯一任务是提问和了解玩家偏好。
- 没有固定提问数量——自然对话，由玩家决定何时进入生成阶段。
- 不要自行总结或结束对话，持续提问直到玩家示意准备完毕。

对每个回答展现好奇心，在提问前先回应上一轮的内容——让对话自然流动，不填表。
```

---

> §3.2–3.4 的三个 section 合并在 `CO_CREATE_GENERATION_PROMPT`（`co_create.py`）中，由 `generate()` 单次调用一并生成。以下为各 section 的格式规范。

### 3.2 故事设定生成

#### 规范

- **输入**：追问阶段完整对话历史 + 生成 Prompt（单次 user 消息）。
- **输出**：`=== story_config ===` 后的结构化文本。
- **字段**：题材（自由文本）、档位（short/medium/long）、标签（5-15 字）、语言（language）、世界观、主角姓名/身份/特质、叙事风格、核心冲突、主要角色（至少 1 个）。
- **解析失败**：引擎通过 `CoCreateError` 异常向 UI 报告具体错误，由用户决定重试或退出。

#### Prompt

```
你是一个故事设定生成器。根据对话内容生成结构化故事设定。

=== story_config ===
题材：{自由文本，如"赛博朋克冒险"、"古风悬疑"}
档位：{short / medium / long}
标签：{5-15字简短命名，用于存档文件名}
世界观：{一段有吸引力的故事简介——介绍世界、主角与核心冲突}
主角姓名：{中文姓名或代号}
主角身份：{一句话}
主角特质：{2-3个关键词或短语}
叙事风格：{如"黑暗冷峻"、"轻松幽默"、"诗意抒情"}
核心冲突：{一句话}
主要角色：
- 角色名 | 角色定位 | 与主角关系
- （至少1个）

约束：题材为自由文本；档位从对话提取；角色格式严格按上述。
```

---

### 3.3 变量定义生成

#### 规范

- **输入**：已确认的 story_config。
- **输出**：`=== variables ===` 后每行一个变量。
- **约束**：number [0,100]、string 替代枚举。≤3 个（≤2 number + ≤1 string）。中文变量名 2-5 字。
- **程序校验**：变量名唯一、类型合法、初始值合规。失败 → 重试。

#### Prompt

```
你是一个游戏变量设计师。根据故事设定设计状态变量。

类型约束：
- number：[0, 100]，用于体力、好感度、理智值等
- string：自由文本，替代枚举，用于状态标记、所属势力等
- 变量名中文，2-5 字

输出格式：

=== variables ===
体力: number, 80
信任度: number, 5
所属势力: string, "中立"
```

---

### 3.4 大纲生成

#### 规范

- **输入**：story_config + 可用变量名列表（来自 §3.3）。
- **输出**：`=== outline ===` 后的大纲树，使用 `[node]` block 格式。节点数 short 3-5 / medium 5-8 / long 8-15。
- **格式**：node_id 为 `ch{序号}_{英文缩写}`。分支条件只能引用已声明变量。结局节点 routes 为空（无文本），系统通过空 routes 判定结局。
- **程序校验**：route 目标存在、变量引用合法、最后节点 routes 为空。失败 → 重试。

#### Prompt

```
你是一个故事大纲规划师。根据故事设定和可用变量设计关键节点路线图。

约束：
- 节点数：short 3-5 / medium 5-8 / long 8-15
- 每个节点的 goal 是章节弧线，非单一场景，跨越数轮展开。2-4 句。
- 允许分支（if 条件 → route），条件只能引用已声明的变量
- 最后节点为结局——其 routes: 留空（不写任何文本）。系统通过空 routes 检测结局，不要写"（结局）"等标记。
- node_id 格式：ch{序号}_{英文缩写}

可用变量：{variables_name_list}

输出格式：

=== outline ===
[node]
id: ch1_intro
title: {节点标题}
goal: {本章叙事目标}
routes: → ch2_next

[node]
id: ch2_branch
title: {节点标题}
goal: {本章叙事目标}
routes:
  if {variable} >= 30 → ch3_ally
  if {variable} < 30 → ch3_betrayal

[node]
id: ch3_ending
title: {节点标题}
goal: {本章叙事目标，结局}
routes:
```

---

## §4 叙事循环 Prompt

> 最频繁调用的 Prompt。每轮至少一次。以下为 `prompt_builder` 和 `context_manager` 的开发标准。
>
> **架构**：对话式消息数组。Round 1 永久锚定（格式规范 + 故事上下文 + 完整 XML 示例），
> Round N 仅发送轻量上下文（进度、状态、bridge_text、错误反馈）。
> `ContextManager` 管理 messages 数组结构，`StreamingXmlParser` 解析 LLM 的 XML 输出。

### 4.1 消息数组架构

#### 数组结构

```
messages = [
  {role: "user",      content: Round1_完整Prompt},      // 永久锚定（不压缩不删除）
  {role: "assistant", content: Round1_XML输出},          // 永久锚定（story opening）
  // ── 以下为滑出窗口的轮次 → 压缩为摘要 ──
  {role: "user",      content: "已发生的主要事件：..."},
  {role: "assistant", content: "（以上为已发生事件的摘要。当前故事继续推进。）"},
  // ── 窗口内轮次 → 完整保留 ──
  {role: "user",      content: Round_N-3_上下文},
  {role: "assistant", content: Round_N-3_XML输出},
  {role: "user",      content: Round_N-2_上下文},
  {role: "assistant", content: Round_N-2_XML输出},
  {role: "user",      content: Round_N-1_上下文},
  {role: "assistant", content: Round_N-1_XML输出},
  // ── 当前轮 ──
  {role: "user",      content: Round_N_上下文},           // 由 PromptBuilder.build_round_n() 构建
]
```

#### 各部分职责

Round 1 的 user 消息由两部分组成：一个**前缀块**（角色、格式规范、示例、规则、故事背景）和一个**回合块**（大纲进度、当前状态、量化约束、续写锚点）。前缀块只发送一次，永久锚定；回合块每轮都发，首轮和后继轮内容结构一致。

| 部分 | 说明 |
|------|------|
| Round 1 user | 前缀块 + 回合块（首轮：bridge_text 为空，无错误反馈） |
| Round 1 assistant | LLM 输出，永久保留的 few-shot 范例 |
| 压缩摘要 | 滑出窗口轮次的 checkpoint 摘要，作为独立的 user/assistant 消息对注入 |
| 窗口轮次 | 最近 WINDOW_SIZE=3 轮的完整 user/assistant 消息对 |
| 当前轮 user | 回合块（bridge_text 和错误反馈按实际情况填充） |

#### 滑动窗口与压缩

| 参数 | 值 | 说明 |
|------|-----|------|
| `WINDOW_SIZE` | 3 | 保留的完整历史轮数 |
| `FIRST_COMPRESSION_AT` | 5 | 首次触发压缩的轮次 |
| 压缩来源 | checkpoint summary | 从 `<checkpoint summary="...">` 属性提取 |

**压缩时序**：

```
Round 1:  无压缩（仅锚定 + 输出）
Round 2:  无压缩（窗口内）
Round 3:  无压缩（窗口内）
Round 4:  无压缩（窗口内）
Round 5:  压缩 Round 2 → 窗口保持 3 轮
Round N:  压缩 Round 2~N-4 → 窗口保留 [N-3, N-2, N-1]
```

压缩摘要格式：
```
user: Key events so far:

- ch1_bar：在霓虹深渊酒吧与耗子接头，选择了直截了当的接触方式
- ch2_confrontation：与耗子完成芯片交易，耗子透露芯片来自荒坂R&D

assistant: (Summary of previous events. The story continues.)
```

#### 格式错误纠正

仅当上一轮解析出现格式错误时，在当前 Round N 消息末尾追加纠正提示：
```
Format reminder: last round had format issues — {format_error}. Please strictly follow the XML format specification.
```
正确时不追加。不删除 Round 1 中的格式范例——LLM 自然从最近的正确输出学习。

#### 边界情况

| 情况 | 处理 |
|------|------|
| 首轮 | 回合块中 bridge_text 为空，无错误反馈；末尾附首轮标记 |
| 窗口未满 | 不触发压缩，不注入压缩摘要消息对 |
| rejected_changes 为空 | 不注入反馈节 |
| format_error 为空 | 不注入纠正提示 |
| ending_flag=true | 不组装叙事 Prompt，组装冒险日志 Prompt（§5） |

### 4.2 首轮前缀

> 首轮 user 消息的前半段——角色定义、格式规范、示例、核心规则、故事背景。只发送一次，永久锚定。
> 后半段（大纲进度、当前状态、量化约束、续写锚点）见 §4.3 回合提示词——首轮和后继轮共享同一模板。

```
You are the narrative engine for a text adventure game. Generate the next interactive story segment based on the outline and current state.

# Output Format

Prefix every line with a line number: `001| `, `002| `, `003| ` ... incrementing continuously.
The program strips these prefixes before parsing — they are NOT part of the XML.
Start at 001 for this round.

Your output MUST be an XML document. Start with `<story>`, end with `</story>`.
Do NOT output markdown code fences, XML declarations, or any text outside the XML.

## Structure

001| <story>
002| <seg>narration text</seg>
003| <seg>narration text</seg>
004| ...
005| <!-- pre-bridge local branch (merges back). opt with no branch stays on main path -->
006| <choice id="minor">
007|   <opt key="1" branch="path_a">takes a branch</opt>
008|   <opt key="2">stays on main</opt>
009| </choice>
010| <branch name="path_a">
011| <seg>local variant — merges back after</seg>
012| </branch>
013| <!-- main interaction — not every choice needs consequences -->
014| <choice id="variable_name">
015|   <opt key="1">option text</opt>
016|   <opt key="2">option text</opt>
017| </choice>
018| <!-- node still in progress — no <checkpoint> yet -->
019| <bridge/>
020| <seg>narration continues on a single path</seg>
021| ...
022| </story>

## Elements

**Line numbers** — `NNN| ` prefix on every line, zero-padded to 3 digits. Increment each line. Not part of the XML.

**<seg>** — A narrative segment. The basic unit of the story — a single beat of narration or dialogue. One thing per segment.

**<choice id="variable_name">** — Player choice. Contains 2-4 `<opt>` elements with `key` (number), `branch` (optional, assigned to `current_branch`), and `if` (optional, availability condition).

**<set>** — State change. Modifies a state variable. `var`, `op`, `val` required. `if` (optional): conditional execution.

**<checkpoint>** — Key story node and save point. Appears 0-1 times. Always a direct child of `<story>`. Records outline progress with a `summary`. May contain `<route>` elements for outline branching.

**<bridge/>** — Self-closing. Always a direct child of `<story>`. Exactly ONCE per output. The signal point where the program triggers the next API call. Divides output into interactive zone (before) and narrative zone (after).

**<branch name>** — Branch narrative container. Before bridge: local branches that merge back. After bridge: key branches selected by `current_branch`. `name` is matched against `current_branch`.

## Format Example

Below is a format example (content is a short fictional fantasy story in English):

001| <story>
002| <seg>Snow fell on the empty road</seg>
003| <seg>Kael stamped the snow from his boots</seg>
004| <seg>He pushed through the heavy oak door</seg>
005| <seg>Innkeeper: Room for the night?</seg>
006| <choice id="inn_choice">
007|   <opt key="1" branch="take_room">Take a room</opt>
008|   <opt key="2">Just a drink</opt>
009| </choice>
010| <branch name="take_room">
011| <seg>A key slid across the counter</seg>
012| </branch>
013| <choice id="drink">
014|   <opt key="1">Somethin' strong</opt>
015|   <opt key="2">Just water</opt>
016| </choice>
017| <seg>A stranger sat alone at the corner table</seg>
018| <seg>Stranger: You're the one I've been waiting for</seg>
019| <seg>Stranger: Word is you handle things quietly</seg>
020| <choice id="approach">
021|   <opt key="1" branch="accept">I'm listening</opt>
022|   <opt key="2" branch="decline">Not interested</opt>
023| </choice>
024| <set var="reputation" op="+" val="5" if="approach==1"/>
025| <checkpoint node="ch2_meeting" summary="A stranger made contact at the inn.">
026|   <route if="approach==1" target="ch3_job"/>
027|   <route if="approach==2" target="ch3_alone"/>
028| </checkpoint>
029| <bridge/>
030| <branch name="accept">
031| <seg>The stranger leaned closer</seg>
032| <seg>Stranger: There's a shipment. Tomorrow night. Old pass</seg>
033| <seg>Stranger: Payment on delivery. Half up front</seg>
034| </branch>
035| <branch name="decline">
036| <seg>The stranger shrugged</seg>
037| <seg>Stranger: Suit yourself. But you'll be back</seg>
038| </branch>
039| </story>
(This is a format example ONLY. Your output is an entirely new story segment.)

# Core Rules

**Segment Format**
- Each `<seg>` is EITHER narration OR dialogue.
- Narration: one scene per segment. Short — a single observation, action, or beat.
- Dialogue: `Name: text` format, no quotation marks. One line per segment.
- Put character actions, expressions, and tone in separate narration segments.
- Use actual character names in dialogue.

**Line Count & Bridge Position**
- **Output {MIN_LINES}-{MAX_LINES} total lines.** The format example is deliberately short (35 lines) to show structure only — your output MUST reach {MIN_LINES}-{MAX_LINES}.
- Place `<bridge/>` roughly {BRIDGE_PCT:.0f}% through — about 3/4 of lines before, 1/4 after.
- Each post-bridge `<branch>` must span at least {MIN_TAIL} lines.
- Post-bridge content is selected by `current_branch`: use `<branch>` containers for multiple possible paths, bare `<seg>` for a single path.

**Choice → current_branch**
- `<opt branch="X">` sets `current_branch = X`. Branch selection is based on `current_branch`: `<branch name="X">` will match.
- Reference the choice in conditions using its `id` with the `key` number: `variable_name==1`.
- Conditions support `and` / `or` (max one combinator) and reference variables from "Current State".

**Set — State Changes**
- `var` MUST use the exact names from "Current State" below. Do NOT invent, translate, or substitute them.
- number: `op="+"` / `op="-"` / `op="="` with `val` as the number; string: `op="="`.
- Condition syntax: same as Choice above.

**Checkpoint**
- Trigger the checkpoint as soon as the active node's goal is achieved — don't delay.
- If the goal has NOT been reached, omit `<checkpoint>` entirely. The node may take several rounds.
- Copy the `node` attribute verbatim from the outline — exact character-for-character match.
  Outline has `ch2_confrontation` → write `node="ch2_confrontation"`.
- Copy `<route>` `target` attributes verbatim from outline node IDs.

**XML Rules**
- Match every opening tag with a closing tag. Use `/>` for self-closing elements.
- Wrap attribute values in double quotes.
- Escape `<` `>` `&` in text as `&lt;` `&gt;` `&amp;`. Example: "R&D" → "R&amp;D".

**Prohibited**
- `<bridge/>` count not equal to 1.
- `<choice>`, `<set>`, or `<checkpoint>` after bridge.
- More than one `<checkpoint>`.
- Outputting anything outside the XML document (markdown fences, comments, explanatory text).
- `<checkpoint>` `node` or `<route>` `target` not matching an outline node ID exactly.
- `<checkpoint>` when the active node's goal has not been reached.
- `<set>` `var` referencing a variable not listed in "Current State".
- Dialogue with quotation marks, pronouns as character names, or inline action descriptions.
- Addressing the player directly ("You choose...", "What do you do?").

# Quality Requirements

One thing per segment. Alternate dialogue and narration. Make each branch narratively distinct. Create suspense after bridge.

Rough guide: ~lines 001-{REF_PRE} before bridge + ~{REF_SINGLE} after (single path) or ~{REF_HALF} per branch-tail.

# Story Context
**Language:** {LANGUAGE}
**Seg limits:** narration ≤{NARR_LIMIT} characters, dialogue ≤{DIAL_LIMIT} characters
**Background:** {background}
**Protagonist:** {protagonist}
**Tone:** {tone}
**Conflict:** {conflict}
**Characters:**
{characters}
```

### 4.3 回合提示词

> 每轮都发送的 user 消息内容。首轮和后继轮共享同一结构：首轮时 bridge_text 填入起始占位符（如 `(Story begins)`）、无错误反馈；后继轮按实际情况填充。
>
> 包含：大纲进度（完整树 + 状态标记）、当前节点与目标、状态快照、可选的错误反馈、输出量化约束、续写锚点。

#### 模板

```
**Outline:**
{outline_text}

**Active Node:** {active_node} — {node_goal}

**Current State:**
{state_vars_text}{error_feedback}
Output {MIN_LINES}-{MAX_LINES} total lines. Exactly one `<bridge/>`. Less is fine — do not pad to hit the upper bound.
Choices aren't just for branching — place them freely as moments of play and interaction.
The active node may take several rounds to reach. Do not force progress — simply continue from where the story left off.
{bridge_text}
```

#### 各字段说明

| 字段 | 说明 |
|------|------|
| `outline_text` | 完整大纲树，含 `[completed]`/`[active]`/`[pending]` 状态标记和路由关系 |
| `active_node` / `node_goal` | 当前节点 ID 及其叙事目标 |
| `state_vars_text` | 所有变量的当前值。number 类型带 `/ 100` 上限后缀，string 类型不带 |
| `error_feedback` | 可选。上轮被拒的变量变更 + 格式错误提醒。首轮留空 |
| `bridge_text` | 上轮 `<bridge/>` 之后过滤出的纯文本。首轮填入起始占位符 |
| `MIN_LINES` / `MAX_LINES` | 输出行数范围，与首轮前缀中的约束一致 |

#### 格式示例

首轮（无 bridge_text、无错误反馈）：

```
**Outline:**
ch1_bar [active] — 霓虹深渊：在酒吧获取情报
  → ch2_confrontation [pending]
ch2_confrontation [pending] — 地下交易：与耗子会面
  ├→ ch3_ally [pending]
  └→ ch3_betrayal [pending]
ch3_ally [pending] — 盟友之路：通过地下网络逃离
ch3_betrayal [pending] — 背叛之路：杀出重围
ch4_safehouse [pending] — 安全屋：揭开芯片秘密（结局）

**Active Node:** ch1_bar — 霓虹深渊：在酒吧获取情报

**Current State:**
体力: 80 / 100
信任度: 10 / 100
所属势力: 自由佣兵

Output 150-300 total lines. Exactly one `<bridge/>`. Less is fine — do not pad to hit the upper bound.
Choices aren't just for branching — place them freely as moments of play and interaction.
The active node may take several rounds to reach. Do not force progress — simply continue from where the story left off.

```

中盘轮次（有 bridge_text、有错误反馈）：

```
**Outline:**
ch1_bar [completed] — 霓虹深渊：在酒吧获取情报
  → ch2_confrontation [active]
ch2_confrontation [active] — 地下交易：与耗子会面
  ├→ ch3_ally [pending]
  └→ ch3_betrayal [pending]
ch3_ally [pending] — 盟友之路：通过地下网络逃离
ch3_betrayal [pending] — 背叛之路：杀出重围
ch4_safehouse [pending] — 安全屋：揭开芯片秘密（结局）

**Active Node:** ch2_confrontation — 地下交易：与耗子会面完成芯片交易

**Current State:**
体力: 60 / 100
信任度: 25 / 100
所属势力: 自由佣兵

Rejected state changes from last round:
  - 体力变更被拒：超出范围[0,100]

Output 150-300 total lines. Exactly one `<bridge/>`. Less is fine — do not pad to hit the upper bound.
Choices aren't just for branching — place them freely as moments of play and interaction.
The active node may take several rounds to reach. Do not force progress — simply continue from where the story left off.

你对耗子点了点头。
耗子: 跟我来。
他转身推开一扇锈迹斑斑的铁门。
```

### 4.4 完整示例

> Round 1，赛博朋克 medium 故事（zh-CN）。`{MIN_LINES}=150` `{MAX_LINES}=300` `{BRIDGE_PCT}=75`。
> 以下为 §4.2 首轮前缀 + §4.3 回合提示词拼接后的完整 messages[0]，也就是实际发送给 LLM 的内容。
>
> 前缀和回合块之间的分隔线（`---`）仅为阅读标注，实际 Prompt 中不存在，两者直接拼接。

#### 首轮前缀

```
You are the narrative engine for a text adventure game. Generate the next interactive story segment based on the outline and current state.

# Output Format

Prefix every line with a line number: `001| `, `002| `, `003| ` ... incrementing continuously.
The program strips these prefixes before parsing — they are NOT part of the XML.
Start at 001 for this round.

Your output MUST be an XML document. Start with `<story>`, end with `</story>`.
Do NOT output markdown code fences, XML declarations, or any text outside the XML.

## Structure

001| <story>
002| <seg>narration text</seg>
003| <seg>narration text</seg>
004| ...
005| <!-- pre-bridge local branch (merges back). opt with no branch stays on main path -->
006| <choice id="minor">
007|   <opt key="1" branch="path_a">takes a branch</opt>
008|   <opt key="2">stays on main</opt>
009| </choice>
010| <branch name="path_a">
011| <seg>local variant — merges back after</seg>
012| </branch>
013| <!-- main interaction — not every choice needs consequences -->
014| <choice id="variable_name">
015|   <opt key="1">option text</opt>
016|   <opt key="2">option text</opt>
017| </choice>
018| <!-- node still in progress — no <checkpoint> yet -->
019| <bridge/>
020| <seg>narration continues on a single path</seg>
021| ...
022| </story>

## Elements

**Line numbers** — `NNN| ` prefix on every line, zero-padded to 3 digits. Increment each line. Not part of the XML.

**<seg>** — A narrative segment. The basic unit of the story — a single beat of narration or dialogue. One thing per segment.

**<choice id="variable_name">** — Player choice. Contains 2-4 `<opt>` elements with `key` (number), `branch` (optional, assigned to `current_branch`), and `if` (optional, availability condition).

**<set>** — State change. Modifies a state variable. `var`, `op`, `val` required. `if` (optional): conditional execution.

**<checkpoint>** — Key story node and save point. Appears 0-1 times. Always a direct child of `<story>`. Records outline progress with a `summary`. May contain `<route>` elements for outline branching.

**<bridge/>** — Self-closing. Always a direct child of `<story>`. Exactly ONCE per output. The signal point where the program triggers the next API call. Divides output into interactive zone (before) and narrative zone (after).

**<branch name>** — Branch narrative container. Before bridge: local branches that merge back. After bridge: key branches selected by `current_branch`. `name` is matched against `current_branch`.

## Format Example

Below is a format example (content is a short fictional fantasy story in English):

001| <story>
002| <seg>Snow fell on the empty road</seg>
003| <seg>Kael stamped the snow from his boots</seg>
004| <seg>He pushed through the heavy oak door</seg>
005| <seg>Innkeeper: Room for the night?</seg>
006| <choice id="inn_choice">
007|   <opt key="1" branch="take_room">Take a room</opt>
008|   <opt key="2">Just a drink</opt>
009| </choice>
010| <branch name="take_room">
011| <seg>A key slid across the counter</seg>
012| </branch>
013| <choice id="drink">
014|   <opt key="1">Somethin' strong</opt>
015|   <opt key="2">Just water</opt>
016| </choice>
017| <seg>A stranger sat alone at the corner table</seg>
018| <seg>Stranger: You're the one I've been waiting for</seg>
019| <seg>Stranger: Word is you handle things quietly</seg>
020| <choice id="approach">
021|   <opt key="1" branch="accept">I'm listening</opt>
022|   <opt key="2" branch="decline">Not interested</opt>
023| </choice>
024| <set var="reputation" op="+" val="5" if="approach==1"/>
025| <checkpoint node="ch2_meeting" summary="A stranger made contact at the inn.">
026|   <route if="approach==1" target="ch3_job"/>
027|   <route if="approach==2" target="ch3_alone"/>
028| </checkpoint>
029| <bridge/>
030| <branch name="accept">
031| <seg>The stranger leaned closer</seg>
032| <seg>Stranger: There's a shipment. Tomorrow night. Old pass</seg>
033| <seg>Stranger: Payment on delivery. Half up front</seg>
034| </branch>
035| <branch name="decline">
036| <seg>The stranger shrugged</seg>
037| <seg>Stranger: Suit yourself. But you'll be back</seg>
038| </branch>
039| </story>
(This is a format example ONLY. Your output is an entirely new story segment.)

# Core Rules

**Segment Format**
- Each `<seg>` is EITHER narration OR dialogue.
- Narration: one scene per segment. Short — a single observation, action, or beat.
- Dialogue: `Name: text` format, no quotation marks. One line per segment.
- Put character actions, expressions, and tone in separate narration segments.
- Use actual character names in dialogue.

**Line Count & Bridge Position**
- **Output 150-300 total lines.** The format example is deliberately short (35 lines) to show structure only — your output MUST reach 150-300.
- Place `<bridge/>` roughly 75% through — about 3/4 of lines before, 1/4 after.
- Each post-bridge `<branch>` must span at least 25 lines.
- Post-bridge content is selected by `current_branch`: use `<branch>` containers for multiple possible paths, bare `<seg>` for a single path.

**Choice → current_branch**
- `<opt branch="X">` sets `current_branch = X`. Branch selection is based on `current_branch`: `<branch name="X">` will match.
- Reference the choice in conditions using its `id` with the `key` number: `variable_name==1`.
- Conditions support `and` / `or` (max one combinator) and reference variables from "Current State".

**Set — State Changes**
- `var` MUST use the exact names from "Current State" below. Do NOT invent, translate, or substitute them.
- number: `op="+"` / `op="-"` / `op="="` with `val` as the number; string: `op="="`.
- Condition syntax: same as Choice above.

**Checkpoint**
- Trigger the checkpoint as soon as the active node's goal is achieved — don't delay.
- If the goal has NOT been reached, omit `<checkpoint>` entirely. The node may take several rounds.
- Copy the `node` attribute verbatim from the outline — exact character-for-character match.
  Outline has `ch2_confrontation` → write `node="ch2_confrontation"`.
- Copy `<route>` `target` attributes verbatim from outline node IDs.

**XML Rules**
- Match every opening tag with a closing tag. Use `/>` for self-closing elements.
- Wrap attribute values in double quotes.
- Escape `<` `>` `&` in text as `&lt;` `&gt;` `&amp;`. Example: "R&D" → "R&amp;D".

**Prohibited**
- `<bridge/>` count not equal to 1.
- `<choice>`, `<set>`, or `<checkpoint>` after bridge.
- More than one `<checkpoint>`.
- Outputting anything outside the XML document (markdown fences, comments, explanatory text).
- `<checkpoint>` `node` or `<route>` `target` not matching an outline node ID exactly.
- `<checkpoint>` when the active node's goal has not been reached.
- `<set>` `var` referencing a variable not listed in "Current State".
- Dialogue with quotation marks, pronouns as character names, or inline action descriptions.
- Addressing the player directly ("You choose...", "What do you do?").

# Quality Requirements

One thing per segment. Alternate dialogue and narration. Make each branch narratively distinct. Create suspense after bridge.

Rough guide: ~lines 001-225 before bridge + ~75 after (single path) or ~38 per branch-tail.

# Story Context
**Language:** zh-CN
**Seg limits:** narration ≤40 characters, dialogue ≤50 characters
**Background:** 赛博朋克冒险 · 2087年新东京地下城
**Protagonist:** 林焰，前荒坂安全顾问，现自由佣兵。冷静、道德灰色，有过载神经接口
**Tone:** 黑暗冷峻
**Conflict:** 一枚从企业R&D部门流出的神秘芯片正在寻找宿主
**Characters:**
耗子（地下情报贩子，亦敌亦友）、美智子（荒坂安全主管，前上司）
```

---

#### 回合提示词

```
**Outline:**
ch1_bar [completed] — 霓虹深渊：在酒吧获取情报
  → ch2_confrontation [active]
ch2_confrontation [active] — 地下交易：与耗子会面
  ├→ ch3_ally [pending]
  └→ ch3_betrayal [pending]
ch3_ally [pending] — 盟友之路：通过地下网络逃离
ch3_betrayal [pending] — 背叛之路：杀出重围
ch4_safehouse [pending] — 安全屋：揭开芯片秘密（结局）

**Active Node:** ch2_confrontation — 与耗子完成交易

**Current State:**
体力: 80 / 100
理智值: 55 / 100
信任度: 10 / 100
芯片完整度: 100 / 100
线索: （无）
所属势力: 自由佣兵

Output 150-300 total lines. Exactly one `<bridge/>`. Less is fine — do not pad to hit the upper bound.
Choices aren't just for branching — place them freely as moments of play and interaction.
The active node may take several rounds to reach. Do not force progress — simply continue from where the story left off.

```

#### 拼接

首轮完整 Prompt = 首轮前缀 + 回合提示词 + `(This is the start of the whole story.)`

> 实际发送给 LLM 时，前缀和回合块之间没有分隔线，就是一个整体文本。首轮末尾的 `(This is the start of the whole story.)` 仅首轮出现，后续轮次不追加。

## §5 冒险日志 Prompt

### 5.1 规范

- **调用时机**：结局轮 bridge 处（ending_flag=true）。独立调用，不流式。
- **输入**：story_config 全文、state_vars 当前值、outline_text（含各节点 status 和 summary）。
- **输出**：Markdown 格式，500-1000 字。面向玩家回顾性口吻。不加区块分隔符。
- **Prompt 语言**：英文（与所有系统 Prompt 一致）。通过 `{language}` 占位符指示 LLM 以故事语言输出。

### 5.2 Prompt 模板

```
You are an adventure log author. Write a player-facing recap for a completed text adventure game.

Use Markdown format. Write in the story's language ({language}).

## Adventure Recap: {story_label}

### Chapter 1: {title}
(Expand based on this summary: {summary})

...

## Ending
(Write a warm, satisfying conclusion based on the chapter summaries above.)

## Final State
{state_vars}
(For each variable, write a brief one-sentence reflection.)

Requirements:
- Address the player directly ("You chose...", "In the end you...")
- Plain text only, no XML or block separators
- 500-1000 words
```

### 5.3 Prompt 示例

```
You are an adventure log author. Write a player-facing recap for a completed text adventure game.

Use Markdown format. Write in the story's language (zh-CN).

## Adventure Recap: 霓虹深渊

### Chapter 1: 霓虹深渊
(Expand based on this summary: 在霓虹深渊酒吧与耗子接头)

### Chapter 2: 地下交易
(Expand based on this summary: 完成芯片交易)

### Chapter 3: 盟友之路
(Expand based on this summary: 通过地下网络逃离追捕)

### Chapter 4: 安全屋
(Expand based on this summary: 揭开芯片秘密，加入抵抗组织)

## Ending
(Write a warm, satisfying conclusion based on the chapter summaries above.)

## Final State
- 体力: 25
- 理智值: 50
- 信任度: 20
- 线索: 神秘芯片
- 所属势力: 抵抗组织
(For each variable, write a brief one-sentence reflection.)

Requirements:
- Address the player directly ("You chose...", "In the end you...")
- Plain text only, no XML or block separators
- 500-1000 words
```

---

## §6 迭代日志

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-04 | 初始版本 | — |
| 2026-07-04 | v4 模板重构：示例精简(18→11段)、规则结构化、新增6条设计原则 | 6轮30+次测试验证。正确率33%→83%，TTFT 38s→11s。关键改进：(1)独立options节+choice显式规则 (2)checkpoint反例约束 (3)pre-bridge的:main双重覆盖 (4)示例后防续写屏障 (5)bridge/bridge段数上下限+反例 (6)(重要)注意力标签 |
| 2026-07-04 | 跨题材泛化测试：恋爱/悬疑/古风各3轮 | v4模板在4题材下正确率波动大（1/3~3/3）。发现2个跨题材共性问题：(1) **bridge-before-options** — LLM在options之前插入bridge；(2) **bridge位置偏离** — 慢节奏叙事推迟了交互断点 |
| 2026-07-04 | **架构迁移：对话式消息数组 + XML 输出格式** | 从每轮 system prompt 迁移到 messages 数组架构。(1) **XML 格式**（`<seg>`/`<choice>`/`<set>`/`<checkpoint>`/`<bridge/>`/`<branch>`）替代 `--- block ---`，frame-v1 测试正确率 100%；(2) **对话式** Round 1 永久锚定 + 滑动窗口（WINDOW_SIZE=3）+ checkpoint 压缩；(3) `context_manager.py`、`prompt_builder.py`、`xml_parser.py` 替代旧 prompt 组装管线。旧格式 prompt 文件清理归档 |

---

*本文档为活文档。Prompt 是系统的核心——每次生成质量问题都应追溯至 Prompt，分析原因并迭代。*
