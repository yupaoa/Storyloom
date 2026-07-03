# Phase 1 程序执行流程详解

> **定位**：精准、简洁的程序执行逻辑描述，供开发者/AI 快速把握 Phase 1 该做什么。  
> **配套文档**：完整技术细节、格式示例、Prompt 模板见 [`Storyloom-phased.md`](./Storyloom-phased.md)，本文档引用其章节号（如 "见 phased §1.7"）。  
> **权威性**：本文档与 phased doc 如有冲突，以本文档为准。本文档的讨论结论将回溯修正 phased doc。

---

## §1 总览

### 1.1 术语速查

| 术语 | 含义 | 详参 |
|------|------|------|
| **剧情段** | 每轮 LLM 生成的一段叙事文本，为一轮循环的基本单位。结构约束见 §1.4，处理流程见 §4 | phased §1.4.1 |
| **大纲** | 由若干关键节点组成的有向图，描述故事骨架。节点间可有分支，分支可在后期节点汇合 | phased §1.4.3, §1.7-B |
| **关键节点 (checkpoint)** | 大纲上的里程碑节点。可有 0 个（结束节点，即结局）、1 个（单后续，直线推进）或 n 个（分支）后续节点。到达时必定触发进度推进和自动存档 | phased §1.4.4 |
| **段内分支** | 同一剧情段内的叙事分支。通过 named block + `@name` 路由实现，不影响大纲走向。详见 §1.4.2 | phased §1.4.3 |
| **大纲分支** | 大纲层面的路线分叉。各分支走向不同的后续节点，各自经历独立的 checkpoint 和存档。**可以在后期节点汇合**。通过 `--- checkpoint ---` 中的 `if ... -> route ...` 实现 | phased §1.4.3 |
| **current_name** | 每轮临时变量，初始值 `"main"`。控制段内区块路由：仅 name 匹配的区块被执行。由 state（`@name`）或 options（`-> name`）修改 | 本文档 §1.4.2 |
| **key_dict** | 每轮临时变量，初始值 `{}`。存储本轮 options 的选择结果，供 state 条件判断引用。轮次结束时清空 | 本文档 §1.4.2 |
| **bridge_text** | 上一轮中 `--- bridge ---` 之后至段末的正文内容，作为本轮 User Message 实现无缝衔接。详见 §4 | phased §1.4.2 |
| **状态变量 (state_vars)** | 游戏内可变的数据，由状态模板定义类型和范围。LLM 通过 `--- state ---` 声明变更，程序校验后应用 | phased §1.6 |
| **状态模板** | 预定义的变量集合。Phase 1 硬编码三套：恋爱 (romance)、冒险 (adventure)、悬疑 (mystery)。共创阶段选题材后加载 | phased §1.6 |
| **checkpoint_summaries** | 累积的 checkpoint 情节摘要列表。每到达一个 checkpoint，LLM 生成摘要，程序存入此列表，注入每轮 Prompt | phased §1.4.2 |
| **checkpoint_snapshots** | 每个 checkpoint 节点的状态快照（state_vars 副本），存储在存档内部。Phase 1 仅存储不使用，为 Phase 2 回档预留 | phased §1.9 |
| **游戏存档 (Game Save)** | `saves/` 下的独立 `.json` 文件，每个对应一次完整游玩。包含 story_config、state_vars、outline、progress、checkpoint_snapshots 等全部数据。多个存档互不影响 | 本文档 §2.2 |
| **rejected_changes** | 本轮 `--- state ---` 中被程序校验拒绝的变更条目及其原因。下轮 Prompt 中注入反馈告知 LLM | phased §1.6 |
| **区块分隔符** | LLM 输出的结构化标记，格式为 `--- 区块名 ---`（英文命名），程序用正则按分隔符提取各区块内容 | phased §1.7 |

> **注**：术语表随文档编写持续补充。

### 1.2 程序生命周期总览

```
  ┌──────────┐
  │   启动    │  加载 .env、模板文件
  └────┬─────┘
       ▼
  ┌──────────┐     [新游戏]      ┌──────────┐              ┌──────────┐
  │  主菜单   │ ───────────────→ │ 共创阶段  │ ───────────→ │ 叙事循环  │
  │          │                  │ (4步)    │              │ (N轮)    │
  │ 1.新游戏 │                  └──────────┘              └────┬─────┘
  │ 2.继续   │    [继续]                                       │
  │ 3.管理   │ ──→ 选择存档 ──→ 加载 ──→ ──→ ──→ ──→ ──→ ──→ │
  │ 4.退出   │                                        [结局触发]
  └──────────┘                                            ▼
       ▲                                          ┌──────────┐
       └──────────────────────────────────────────│  结局阶段  │
         [存档管理]                                └──────────┘
       ┌──────────┐                                     │
       │ 存档管理  │ ←→ 主菜单                            │
       └──────────┘                                     │
                                                        ▼
                                                  ┌──────────┐
                                                  │  主菜单   │
                                                  └──────────┘
```

**关键路径**：

| 路径 | 流程 |
|------|------|
| **新游戏** | 主菜单 → 共创 → 初始化 GameState → 叙事循环 → 结局 → 主菜单 |
| **继续** | 主菜单 → 选择存档 → 恢复 GameState → 叙事循环 → 结局 → 主菜单 |
| **存档管理** | 主菜单 → 查看/删除存档 → 主菜单 |
| **退出** | 主菜单 → exit(0) |

### 1.3 核心数据结构速览

#### GameState（内存中的游戏状态）

```
GameState:
  story_config   : { genre, world_setting, protagonist_*, tone, central_conflict, key_characters[] }
  state_template : "romance" | "adventure" | "mystery"
  state_vars     : { 变量名: 当前值 }
  outline[]      : [{ node_id, title, goal, status, branches[] }]
  progress       : {
                     current_node, round_count,
                     checkpoint_history[],      // 已完成的 node_id 列表
                     checkpoint_summaries[],    // { node_id, summary }
                     checkpoint_snapshots{}     // { node_id: { state_vars 快照 } }
                   }
  bridge_text    : string
  rejected_changes[]  // [{ change_text, reason }]，本轮被拒绝的变更
```

#### 存档文件

`saves/` 目录下每个 `.json` 文件代表一次完整游玩（一个"游戏存档"）。文件名来源于共创阶段确定的 `story_config.label`（重名自动追加 `_2`、`_3`）。

完整结构见 [phased §1.9](./Storyloom-phased.md#存档文件结构)，核心字段与 GameState 对应，额外包含 `version`、`metadata`（label, created_at, updated_at, round_count）、`config`（temperature 等参数）。**不存储模型标识**——模型以当前 `.env` 为准。

> **概念区分**：「游戏存档」是 `saves/` 下的文件，每个对应一次独立游玩；「checkpoint 快照」是存档内部的节点状态副本（`checkpoint_snapshots`），Phase 1 仅存储，Phase 2 用于回档。

#### 每轮 Prompt 的组成

每轮发送给 LLM 的完整 Prompt = System Prompt + User Message。LLM 据此理解当前故事进展并生成合适后续内容。

```
完整 Prompt:
  ├── System Prompt（由 prompt_builder 组装）:
  │     ├── 固定部分：游戏规则 + 输出格式要求 + 格式示例
  │     ├── 故事背景：story_config 全部字段
  │     ├── 大纲：outline_text（所有节点 + [completed]/[active]/[pending] 标注）
  │     ├── 进度：current_node + goal + completed_nodes_summary
  │     ├── 重要事件：checkpoint_summaries_text（如无则输出占位文本）
  │     ├── 当前状态：state_summary（所有 state_vars 格式化）
  │     └── 拒绝反馈：rejected_changes_feedback（仅当 rejected_changes 非空）
  │
  └── User Message:
        └── bridge_text（上一轮 `--- bridge ---` 或程序截断内容，告诉 LLM "上一轮刚好讲到这里"；首轮为空字符串）
```

### 1.4 区块分隔符与执行模型

#### 1.4.1 分隔符速查

> 全部使用英文命名。LLM 输出时必须严格使用以下区块名，程序按正则 `^--- (\w+)(?::(\w+))? ---$` 提取区块类型和名称。
> 部分区块支持**命名**：`--- block:name ---`，用于段内分支路由（见 §1.4.2）。缺省 name 即为 `main`。

| 区块标记 | 阶段 | 必需 | 支持命名 | 说明 |
|----------|------|------|----------|------|
| `--- narrative ---` | 叙事 | ✅ 必选 | ✅ | 故事叙述正文 |
| `--- options ---` | 叙事 | 可选 | ✅ | 选项列表。第一行为 `key: 键名` |
| `--- state ---` | 叙事 | 可选 | ✅ | 数据变更 + 段内路由。无条件的直接执行；有条件的用 `if 条件 -> 动作` |
| `--- checkpoint ---` | 叙事 | 可选 | ❌ 固定 main | 大纲路由。`node <id>` 或 `end` + `if 条件 -> route <next_node>` |
| `--- bridge ---` | 叙事 | 通常必选 | ❌ 固定 main | 下一轮的上文衔接标记。程序解析到此标记后开始组装下一轮 Prompt。**结局轮除外**（见 §1.4.3 bridge 说明） |
| `--- adventure_log ---` | 结局 | 可选 | ❌ 固定 main | 面向玩家的冒险回顾文本。仅结局轮出现 |
| `=== story_config ===` | 共创 | 必选 | — | 故事设定（仅共创阶段使用） |
| `=== outline ===` | 共创 | 必选 | — | 大纲树（仅共创阶段使用） |

> **共创 vs 叙事格式区分**：共创阶段用 `=== xxx ===`（双等号），叙事阶段用 `--- xxx ---`（三短横线）。两者不会同时出现。
>
> **`--- branch ---` 已删除**：段内分支通过 named narrative + named state 实现，不再需要独立的分支区块。

#### 1.4.2 命名路由机制

程序每轮维护两个临时变量（轮次结束时清空）：

| 变量 | 初始值 | 说明 |
|------|--------|------|
| `current_name` | `"main"` | 当前执行的分支名 |
| `key_dict` | `{}` | 选项键值对，如 `{"chip_choice": 1}` |

**路由规则**：

```
程序从头到尾顺序扫描区块标记行：
  区块的 name == current_name 或 name == "main"（默认）？
  ├── 是 → 执行该区块内容
  └── 否 → 跳过，继续下一个区块
```

**`current_name` 的修改来源**：

| 来源 | 语法 | 示例 |
|------|------|------|
| options 选项行 | `-> name` | `1. 接过芯片 -> took_chip` |
| state 无条件 | `@name 值` | `@name desperate` |
| state 条件结果 | `if ... -> @name 值` | `if 体力 < 20 -> @name desperate` |

**`key_dict` 的修改来源**：

| 来源 | 说明 |
|------|------|
| options | 第一行 `key: 键名` 声明 key；玩家选择后 `key_dict["键名"] = 选择编号` |

> **注意**：checkpoint、bridge 固定为 `main`，不参与段内路由。即 checkpoint 永远在主分支上执行。

#### 1.4.3 各区块语法

**`--- narrative ---`**

纯叙事文本。支持命名以实现段内分支：
```
--- narrative:main ---
（主分支叙事……）

--- narrative:took_chip ---
（仅当 current_name=="took_chip" 时展示……）

--- narrative:left ---
（仅当 current_name=="left" 时展示……）
```

**`--- options ---`**

第一行必须声明 `key`。每个选项行可附带 `@if:条件`（置灰条件）和 `-> name`（设置 current_name）：
```
--- options:main ---
key: chip_choice
1. 接过芯片 -> took_chip
2. 暂时离开 @if: 理智值 >= 30 -> left
3. 先发制人 @if: 体力 >= 50 -> attacked
```
程序处理：展示选项 → 玩家选择 → `key_dict["chip_choice"] = N` → 若选项有 `-> name`，设置 `current_name = name`。

**`--- state ---`**

无条件变更直接执行。条件变更每行独立评估，命中即执行：
```
--- state:main ---
@var 理智值 -10                         ← 无条件，直接执行
if chip_choice == 1 -> @var 线索 +神秘芯片, @var 信任度 +10, @name took_chip
if chip_choice == 2 -> @name left
if 信任度 >= 50 and 好感度 >= 30 -> @var 关系阶段 =朋友
if 体力 < 20 or 金币 < 100 -> @name desperate
```

**条件语法规则**：

| 元素 | 说明 |
|------|------|
| 变量名 | 中文，引用 state_vars 或 key_dict 中的 key |
| 运算符 | `==` `>=` `<=` `>` `<` `has` |
| 组合 | 支持 `and` / `or`。优先级：`and` > `or`。Phase 1 不支持括号 |
| 动作 | `@var 变量 操作 值`（数据变更）、`@name 值`（路由切换）、`route node_id`（仅 checkpoint） |
| 关键字 | `if` `->` `@var` `@name` 固定英文 |

> **条件语法为建议语法**，如需调整须兼顾两个约束：(1) 程序可用正则准确解析；(2) LLM 能稳定生成。

**`--- checkpoint ---`**

仅做大纲路由，**不修改 state_vars**。如需数据变更，先执行 `--- state ---`：
```
--- checkpoint ---
node ch2_discovery
if 信任度 >= 50 -> route ch3_ally
if 信任度 < 50 -> route ch3_betrayal
summary: 在酒吧获得加密芯片，得知AIKO真实身份……
```
结局节点：
```
--- checkpoint ---
end
summary: 所有线索汇集，命运在此交汇……
```
- `node <id>` 或 `end`：标记到达的节点
- `if 条件 -> route <next_node_id>`：分支路由。条件引用当前 state_vars。多个条件取首个命中。无条件命中 → 取第一个分支的 next_node（兜底）
- `summary:`：checkpoint 摘要（必填）

**`--- bridge ---`**

标记下一轮 Prompt 组装的触发点。bridge 之后至段末的内容即为 bridge_text。约束：
- bridge 之后**不得**出现 `--- state ---` 或 `--- checkpoint ---`（底层数据变更必须在 bridge 之前完成）
- bridge 之后**可以**出现 `--- options ---` + `--- narrative(...)`（纯叙事分支，无数据变更）
- bridge 之后**可以**出现 `--- adventure_log ---`

**结局轮的 bridge**：当 `--- checkpoint ---` 标记为 `end` 时，当前轮即为结局轮。结局轮中 bridge 的行为：
- LLM 应**尽量省略** `--- bridge ---`（本段即终点，无需衔接下一轮）
- 若 LLM 仍输出了 bridge，程序**仅展示其内容作为结局叙事的一部分**，不组装下一轮 Prompt
- 程序检测到 checkpoint `end` → 本轮展示完毕后直接进入结局流程（产生 adventure_log、返回主菜单）

**`--- adventure_log ---`**

结局轮中 LLM 可选输出的冒险回顾。程序在结局流程中展示。若 LLM 未在结局轮输出此区块，程序单独发起一次结局 Prompt 请求（见 phased §1.10-E）生成。

#### 1.4.4 约束汇总

| 约束 | 说明 |
|------|------|
| `--- narrative ---` 必须存在，`--- bridge ---` 通常必选 | 结局轮（checkpoint `end`）中 bridge 可选；其余轮次缺一不可 |
| bridge 之后不得有 state / checkpoint | 底层数据变更必须在 bridge 之前完成。纯叙事 options + narrative 分支允许在 bridge 之后 |
| 每轮至多一个 `--- checkpoint ---` | 一个剧情段不应跨越两个 checkpoint |
| checkpoint 固定 main | 不参与段内路由，永远在主分支上执行 |
| state 必须在 checkpoint 之前 | 若同段同时存在，state 先执行（更新数据），checkpoint 后评估（路由基于最新数据） |
| checkpoint `end` = 结局轮 | 程序不再组装下一轮 Prompt。bridge 变为可选，如有则仅展示不触发请求 |
| `--- ending ---` 已删除 | 结局触发由 checkpoint `end` 取代 |

### 1.5 核心原则

> 以下原则贯穿 Phase 1 全部流程。后续章节中的具体逻辑均基于这些原则展开。

| 原则 | 说明 |
|------|------|
| **本地数据为唯一真相源** | 一切游戏数据以本地 GameState 为准。LLM 只能*建议*变更，程序校验通过后方可应用。具体含义：选项条件基于本地 state_vars 判定；Prompt 中所有数据（outline、state、进度）取自本地；LLM 输出与本地数据冲突时，以本地为准（如引用不存在的变量 → 拒绝；node_id 不在 outline 中 → 忽略） |
| **bridge 之后无底层数据变更** | 程序执行到 `--- bridge ---` 时触发下一轮 Prompt 组装。bridge 之后不得出现 `--- state ---` 或 `--- checkpoint ---`（否则下一轮 Prompt 缺少这些数据更新）。但允许 `--- options ---` + named `--- narrative ---` 做纯叙事分支（无数据变更的局部选项） |
| **用户体验无缝衔接** | 前一个剧情段展示结束前，后一个剧情段应已由 LLM 生成完毕。bridge 标记即是提前触发下一轮请求的机制——程序展示 bridge_text 的同时，后台已在等待 LLM 响应 |
| **程序拥有最终控制权** | LLM 负责叙事创意，程序负责数据完整性和流程控制。API 失败、解析错误、内容异常——均由程序告知用户并等待决策，不做自动降级或静默跳过（个别条目校验失败除外，见 phased §1.8.2） |

> **注**：原则列表随文档编写持续补充。

---

## §2 启动与主菜单

### 2.1 启动检查流程

```
程序启动
    │
    ▼
┌─────────────────────┐
│ 1. 加载 .env 文件    │
└────────┬────────────┘
         ▼
    STORYLOOM_API_KEY 存在？
    ├── 否 → 打印 "未配置 API Key，请检查 .env 文件" → exit(1)
    └── 是
         ▼
┌─────────────────────┐
│ 2. 加载状态模板      │
│   TEMPLATES_PATH    │
└────────┬────────────┘
         ▼
    文件存在且 JSON 合法？
    ├── 否 → 打印 "模板文件缺失或损坏" → exit(1)
    └── 是
         ▼
    三套模板 (romance/adventure/mystery) 都存在？
    ├── 否 → 打印 "模板定义不完整" → exit(1)
    └── 是
         ▼
┌─────────────────────┐
│ 3. 进入主菜单        │
└─────────────────────┘
```

**启动时不做的事**：不验证 API Key 有效性（首次调用时暴露）、不创建 `saves/` 目录（首次存档时创建）。

**伪代码**：
```
config = load_dotenv()
if not config.api_key:
    print("未配置 API Key，请检查 .env 文件")
    exit(1)

templates = load_json(TEMPLATES_PATH)
for genre in ["romance", "adventure", "mystery"]:
    if genre not in templates:
        print("模板定义不完整: 缺少 {genre}")
        exit(1)
```

### 2.2 主菜单逻辑

```
扫描 saves/*.json → 收集存档摘要列表
    │
    ▼
┌──────────────────────────────────────────────────┐
│              Storyloom - 文字冒险                  │
│                                                  │
│   [1] 新游戏    [2] 继续    [3] 存档管理    [4] 退出  │
│                                                  │
│   当前共 {N} 个存档                                │
└──────────────────────────────────────────────────┘
    │
    ▼
用户按键
├── 1 → 新游戏
├── 2 → 继续
├── 3 → 存档管理
└── 4 → 退出
```

#### 路径 [1]：新游戏

```
用户按 1
    │
    ▼
直接进入共创阶段（§3）
（不检查覆盖，每个新游戏将生成独立存档文件）
```

#### 路径 [2]：继续

```
用户按 2
    │
    ▼
saves/*.json 存在？
├── 否 → 打印 "没有存档，请开始新游戏" → 返回主菜单
└── 是
         ▼
    逐个读取存档，校验完整性（§6.3 判定标准）
    ├── 损坏文件 → 跳过，记录警告
    └── 有效文件 → 收集 { filename, label, round_count, updated_at }
         ▼
    有效存档数 = 0？
    ├── 是 → 打印 "没有有效存档" → 返回主菜单
    └── 否
         ▼
    展示存档列表：
    ┌──────────────────────────────────────────┐
    │  选择存档：                               │
    │  [1] 赛博朋克爱情故事（第 23 轮，2026-07-03）│
    │  [2] 古堡悬疑（第 5 轮，2026-07-02）        │
    │  [0] 返回                                 │
    └──────────────────────────────────────────┘
         │
         ▼
    用户选择
    ├── 0 → 返回主菜单
    └── N → 加载所选存档 → 恢复 GameState → 进入叙事循环（§4）
```

> **优化**：若仅 1 个有效存档，可跳过列表直接加载。实现时自行决定。

#### 路径 [3]：存档管理

```
用户按 3
    │
    ▼
saves/*.json 存在且在有效存档列表中的文件？
├── 否 → 打印 "没有可管理的存档" → 返回主菜单
└── 是
         ▼
    展示存档列表（同上格式）
         │
         ▼
    用户选择存档
         │
         ▼
    展示存档详情 + 操作选项：
    ┌──────────────────────────────────────────┐
    │  赛博朋克爱情故事                          │
    │  进度：第 23 轮 / checkpoint: ch2_discovery │
    │  模板：恋爱 | 创建：2026-07-03              │
    │                                          │
    │  [1] 删除此存档    [2] 返回列表    [0] 返回  │
    └──────────────────────────────────────────┘
         │
         ▼
    用户按 1
         │
         ▼
    打印 "确定删除存档'{label}'？此操作不可恢复。(y/n)"
    ├── y → 删除文件 → 打印 "已删除" → 返回主菜单
    └── n → 返回存档详情
```

#### 路径 [4]：退出

```
用户按 4 → exit(0)
```

### 2.3 存档命名规则

| 规则 | 说明 |
|------|------|
| 文件名来源 | `story_config.label`（共创阶段生成的故事设定中的标签，如 "赛博朋克爱情故事"） |
| 非法字符处理 | 替换 `/` `\` `:` `*` `?` `"` `<` `>` `|` 为 `_` |
| 重名处理 | 若 `{label}.json` 已存在 → `{label}_2.json`，以此类推（取最小未占用的编号） |
| 目录 | 统一存放在 `SAVE_DIR` 下 |

---

*下一节：[§3 共创阶段](#)（待编写）*
