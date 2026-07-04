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
| **中文 Prompt** | 所有 Prompt 使用中文 |
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
| 故事设定 | 共创 Step 3 | `=== story_config ===` | §3.2 |
| 变量定义 | 共创 Step 3.5 | `=== variables ===` | §3.3 |
| 大纲生成 | 共创 Step 4 | `=== outline ===` | §3.4 |
| 叙事循环 | 每轮 | XML 文档（`<story>` + `<seg>`/`<choice>`/`<set>`/`<checkpoint>`/`<bridge/>`/`<branch>`） | §4 |
| 冒险日志 | 结局 | Markdown 纯文本 | §5 |

---

## §3 共创阶段 Prompt

### 3.1 追问循环

#### 规范

- **角色**：故事共创助手。通过提问收集信息，不直接生成故事。
- **五大维度**：世界观、主角、基调、冲突方向、故事长度。Prompt 中列明，禁止涉及具体情节。
- **终止条件**：LLM 信息足够时在回复末尾询问"是否开始生成故事？"；用户输入"开始"→ 程序退出循环。

#### Prompt

```
你是一个故事共创助手。通过提问帮助用户明确他想体验的故事。

提问聚焦五大维度，不得询问具体情节：
- 世界观设定（时代、地点、科技/魔法水平、社会结构）
- 主角设定（姓名、身份、性格特质、背景）
- 故事基调（黑暗/轻松、史诗/个人、严肃/幽默）
- 冲突方向（核心矛盾是什么，不透露具体事件）
- 故事长度（短篇约 10 轮 / 中篇约 20 轮 / 长篇约 40 轮）

禁止询问具体情节、暗示剧情走向、使用引导性措辞。

信息足够后（通常 3-5 个问题），在回复末尾问：
"信息已经足够了，是否开始生成故事？"
```

---

### 3.2 故事设定生成

#### 规范

- **输入**：追问阶段完整对话历史（User Message）。
- **输出**：`=== story_config ===` 后的结构化文本。
- **字段**：题材（自由文本）、档位（short/medium/long）、标签（5-15 字）、世界观、主角姓名/身份/特质、叙事风格、核心冲突、主要角色（至少 1 个）。
- **解析失败**：重试 MAX_RETRIES 次后用户决策。不向用户展示设定内容。

#### Prompt

```
你是一个故事设定生成器。根据对话内容生成结构化故事设定。

=== story_config ===
题材：{自由文本，如"赛博朋克冒险"、"古风悬疑"}
档位：{short / medium / long}
标签：{5-15字简短命名，用于存档文件名}
世界观：{一句话，时代、地点、核心设定}
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
- **约束**：number [0,100]、string 替代枚举、list 元素为 string。5-8 个。中文变量名 2-5 字。
- **程序校验**：变量名唯一、类型合法、初始值合规。失败 → 重试。

#### Prompt

```
你是一个游戏变量设计师。根据故事设定设计 5-8 个状态变量。

类型约束：
- number：[0, 100]，用于体力、好感度、理智值等
- string：自由文本，替代枚举，用于状态标记、所属势力等
- list：元素为文本，用于背包、线索、技能等
- 变量名中文，2-5 字

输出格式：

=== variables ===
体力: number, 初始 80
信任度: number, 初始 5
所属势力: string, 初始 "中立"
线索: list, 初始 []
```

---

### 3.4 大纲生成

#### 规范

- **输入**：story_config + 可用变量名列表（来自 §3.3）。
- **输出**：`=== outline ===` 后的大纲树。节点数 short 3-5 / medium 5-8 / long 8-15。
- **格式**：node_id 为 `ch{序号}_{英文缩写}`。分支条件只能引用已声明变量。最后节点为结局。
- **程序校验**：route 目标存在、变量引用合法、最后节点无分支。失败 → 重试。

#### Prompt

```
你是一个故事大纲规划师。根据故事设定和可用变量设计关键节点路线图。

约束：
- 节点数：short 3-5 / medium 5-8 / long 8-15
- 每个节点有明确叙事目标
- 允许分支（if 条件 → route），条件只能引用已声明的变量
- 最后节点为结局
- node_id 格式：ch{序号}_{英文缩写}

可用变量：{variables_name_list}

输出格式：

=== outline ===
节点1：{标题} | ch1_{缩写}
目标：{本章叙事目标}
分支：无

节点2：{标题} | ch2_{缩写}
目标：{本章叙事目标}
分支：if 信任度 >= 10 → ch3_ally
分支：if 信任度 < 10 → ch3_betrayal

（最后节点分支留空或写"（结局）"）
```

---

## §4 叙事循环 Prompt

> 最频繁调用的 Prompt。每轮至少一次。以下为 `prompt_builder` 和 `context_manager` 的开发标准。
>
> **架构**：对话式消息数组。Round 1 永久锚定（格式规范 + 故事上下文 + 完整 XML 示例），
> Round N 仅发送轻量上下文（进度、状态、bridge_text、错误反馈）。
> `ContextManager` 管理 messages 数组结构，`XmlParser` 解析 LLM 的 XML 输出。

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

| 部分 | 模块 | 说明 |
|------|------|------|
| Round 1 user | `PromptBuilder.build_round1()` | 角色定义 + XML 格式规范 + 完整示例 + 核心规则 + 故事上下文 |
| Round 1 assistant | LLM 输出 | 永久保留的 few-shot 范例（~1500 tokens） |
| 压缩摘要 | `ContextManager._build_compression_messages()` | 滑出窗口轮次的 checkpoint 摘要列表 |
| 窗口轮次 | `ContextManager` 维护 | 最近 WINDOW_SIZE=3 轮的完整 user/assistant 消息对 |
| 当前 Round N | `PromptBuilder.build_round_n()` | 轻量上下文（不含格式规范和故事上下文） |

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
user: 以下是之前发生的主要事件：

- ch1_bar：在霓虹深渊酒吧与耗子接头，选择了直截了当的接触方式
- ch2_confrontation：与耗子完成芯片交易，耗子透露芯片来自荒坂R&D

assistant: （以上为已发生事件的摘要。当前故事继续推进。）
```

#### 格式错误纠正

仅当上一轮解析出现格式错误时，在当前 Round N 消息末尾追加纠正提示：
```
上一轮输出存在格式问题——{format_error}。请严格遵循 XML 格式规范。
```
正确时不追加。不删除 Round 1 中的格式范例——LLM 自然从最近的正确输出学习。

#### 边界情况

| 情况 | 处理 |
|------|------|
| 首轮（round_count=0） | 调用 `build_round1()` 而非 `build_round_n()`，bridge_text 为空 |
| compressed_summaries 为空 | 不注入压缩摘要消息对 |
| rejected_changes 为空 | 不注入反馈节 |
| format_error 为空 | 不注入纠正提示 |
| ending_flag=true | 不组装叙事 Prompt，组装冒险日志 Prompt（§5） |

### 4.2 Round 1 Prompt 模板

> `ROUND1_TEMPLATE` 在 `prompt_builder.py` 中定义。`{占位符}` 由 `build_round1()` 替换。
> 永久保留在 messages[0]，不压缩不删除。

```
你是文字冒险游戏的叙事引擎。根据大纲和状态生成下一段交互式剧情。

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
- 对话不加引号，不用代词做角色名，不段内混动作描写
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

请开始故事。
```

### 4.3 Round N 上下文

> Round N（N ≥ 2）的 user 消息由 `PromptBuilder.build_round_n()` 构建。
> 不含角色定义、格式规范、故事上下文——这些已在 Round 1 中永久锚定。

#### 消息内容

| 内容 | 来源 | 说明 |
|------|------|------|
| 当前节点 | `current_node` | 当前大纲节点 ID |
| 目标 | `goal` | 当前节点的叙事目标 |
| 已完成节点 | `completed_nodes` | 已通过的 checkpoint 列表 |
| 压缩摘要 | `compressed_summaries` | 滑出窗口轮次的 checkpoint 摘要 |
| 状态快照 | `state_vars` | 所有变量的当前值 |
| 被拒变更 | `rejected_changes` | 仅当非空时注入 |
| 格式错误 | `format_error` | 仅当存在时注入 |
| bridge_text | 上一轮 assistant 输出 | 从 `<bridge/>` 之后提取的纯文本 |

#### 格式示例（Round N）

```
当前节点：ch3_ally — 通过地下网络逃离
已完成节点：ch1_bar, ch2_confrontation

已完成的章节摘要：
- 在霓虹深渊酒吧与耗子接头，选择了直截了当的接触方式
- 与耗子完成芯片交易，耗子透露芯片来自荒坂R&D

当前状态：
  体力：60 / 100
  信任度：25 / 100
  所属势力：自由佣兵

上一轮结尾：
你对耗子点了点头。
耗子: 跟我来。
```

#### 状态变量格式化

| 类型 | 格式 |
|------|------|
| number | `变量名：当前值 / 100` |
| string | `变量名：当前值` |
| list | `变量名：元素1, 元素2`（空则 `（无）`） |

#### 大纲格式化

与旧架构一致（未变）：
- 每节点一行：`node_id [status] — 标题：目标`
- 分支缩进：`├→ target [status]`
- status：`[completed]` / `[active]` / `[pending]`

### 4.4 Round 1 Prompt 示例

> Round 1，赛博朋克 medium 故事。`{MIN}=60` `{MAX}=120`。

```

你是文字冒险游戏的叙事引擎。根据大纲和状态生成下一段交互式剧情。

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
- 60-120 个叙事段。bridge 放在交互与叙事分界处，约总段数一半
- bridge 之后只能有 <seg> 或 <branch>，严格禁止 <choice>/<set>/<checkpoint>
- <checkpoint> 的 node 和 <route> 的 target 必须严格复制大纲节点 ID，禁止修改或拼接后缀
- 有 <choice> 时，每个 <opt> 的 branch 必须在 bridge 之后有对应 <branch name>
- 对话不加引号，不用代词做角色名，不段内混动作描写
- 文本中 & 须转义为 &amp;

# 质量要求

每段只做一件事——描写一个画面或表达一句对白。对话与旁白交替出现，避免连续 3 段以上纯描写。选项的后果在叙事中铺垫。bridge 之后制造悬念。

# 故事

**背景：** 赛博朋克冒险 · 2087年新东京地下城，企业控制数据流，芯片即权力
**主角：** 林焰，前荒坂安全顾问，现自由佣兵。冷静、道德灰色，有过载神经接口
**风格：** 黑暗冷峻
**冲突：** 一枚从企业R&D部门流出的神秘芯片正在寻找宿主
**角色：** 耗子（地下情报贩子，亦敌亦友）、美智子（荒坂安全主管，前上司）

**大纲：**
ch1_bar [completed] — 霓虹深渊：在酒吧获取情报
  → ch2_confrontation [active]
ch2_confrontation [active] — 地下交易：与耗子会面
  ├→ ch3_ally [pending]
  └→ ch3_betrayal [pending]
ch3_ally [pending] — 盟友之路：通过地下网络逃离
ch3_betrayal [pending] — 背叛之路：杀出重围
ch4_safehouse [pending] — 安全屋：揭开芯片秘密（结局）
[completed]=已完成 [active]=当前 [pending]=待推进

**当前状态：**
体力：80 / 100
理智值：55 / 100
信任度：10 / 100
芯片完整度：100 / 100
线索：（无）
所属势力：自由佣兵

当前节点目标：与耗子完成交易

请开始故事。
```

## §5 冒险日志 Prompt

### 5.1 规范

- **调用时机**：结局轮 bridge 处（ending_flag=true）或 Q 键结束后。独立调用，不流式。
- **输入**：story_config 全文、state_vars 当前值、checkpoint_summaries、checkpoint_history。
- **输出**：Markdown 格式，500-1000 字。面向玩家回顾性口吻。不加区块分隔符。

### 5.2 Prompt 模板

```
你是冒险回顾作者。为刚完成的文字冒险游戏撰写冒险日志。

用 Markdown 格式：

## 冒险回顾：{story_label}

### 第X章：{node_title}
（根据摘要扩写 2-3 句章节回顾）

（每个 checkpoint 一节）

### 结局：{ending_title}
（故事收束）

### 最终状态
- 各变量最终值及评语

要求：面向玩家口吻（"你选择了……"），纯文本，不加区块分隔符，500-1000 字。
```

### 5.3 Prompt 示例

```
你是冒险回顾作者。为刚完成的文字冒险游戏撰写冒险日志。

用 Markdown 格式：

## 冒险回顾：霓虹深渊

### 第X章：{节点标题}
（根据摘要扩写 2-3 句）

### 结局：安全屋
（故事收束）

### 最终状态
- 各变量最终值及评语

要求：面向玩家口吻，纯文本，不加区块分隔符，500-1000 字。

---

故事信息：
标签：霓虹深渊 · 题材：赛博朋克冒险

已完成的章节：
- ch1_bar：在霓虹深渊酒吧与耗子接头
- ch2_confrontation：完成芯片交易
- ch3_ally：通过地下网络逃离追捕
- ch4_safehouse：揭开芯片秘密，加入抵抗组织（结局）

最终状态：
体力：25 / 100
理智值：50 / 100
信任度：20 / 100
线索：神秘芯片
所属势力：抵抗组织
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
