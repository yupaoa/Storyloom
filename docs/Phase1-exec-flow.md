# Phase 1 程序执行流程详解

> **定位**：精准、简洁的程序执行逻辑描述，供开发者/AI 快速把握 Phase 1 该做什么。  
> **配套文档**：完整技术细节、格式示例、Prompt 模板见 [`Storyloom-phased.md`](./Storyloom-phased.md)，本文档引用其章节号（如 "见 phased §1.7"）。  
> **权威性**：本文档与 phased doc 如有冲突，以本文档为准。本文档的讨论结论将回溯修正 phased doc。

---

## §1 总览

### 1.1 术语速查

| 术语 | 含义 | 详参 |
|------|------|------|
| **剧情段** | 每轮 LLM 生成的一段叙事文本，包含正文及可选的结构化区块 | phased §1.4.1 |
| **大纲** | 由若干关键节点组成的有向图，描述故事骨架。节点间可有分支，分支可在后期节点汇合 | phased §1.4.3, §1.7-B |
| **关键节点 (checkpoint)** | 大纲上的里程碑节点。可有 0 个（结束节点，即结局）、1 个（单后续，直线推进）或 n 个（分支）后续节点。到达时必定触发进度推进和自动存档 | phased §1.4.4 |
| **局部小分支** | 不影响大纲走向的即时选择分支。LLM 在 `--- branch ---` 中为每个选项预写短片段 `[N]`，以 `[merge]` 标记汇合文本。玩家选择后只展示对应片段 + 汇合文本 | phased §1.4.3 |
| **关键节点分支** | 大纲层面的路线分叉。各分支走向不同的后续节点，各自经历独立的 checkpoint 和存档。**可以在后期节点汇合**（如不同角色线最终汇入结局章），也可永不汇合（走向不同结局） | phased §1.4.3 |
| **bridge_text** | 上一轮留下的上文衔接片段，作为本轮 User Message，实现无缝衔接。来源：`--- bridge ---` 区块内容，或程序截断正文后的后半部分 | phased §1.4.2 |
| **状态变量 (state_vars)** | 游戏内可变的数据，由状态模板定义类型和范围。LLM 通过 `--- state ---` 声明变更，程序校验后应用 | phased §1.6 |
| **状态模板** | 预定义的变量集合。Phase 1 硬编码三套：恋爱 (romance)、冒险 (adventure)、悬疑 (mystery)。共创阶段选题材后加载 | phased §1.6 |
| **checkpoint_summaries** | 累积的 checkpoint 情节摘要列表。每到达一个 checkpoint，LLM 生成摘要，程序存入此列表，注入每轮 Prompt | phased §1.4.2 |
| **checkpoint_snapshots** | 每个 checkpoint 节点的状态快照（state_vars 副本）。Phase 1 仅存储不使用，为 Phase 2 回档预留 | phased §1.9 |
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
  │ 2.继续   │                                               │
  └──────────┘                                        [结局触发]
       ▲                                                  ▼
       │                                          ┌──────────┐
       └──────────────────────────────────────────│  结局阶段  │
                                                   └──────────┘
```

**两条路径**：

| 路径 | 流程 |
|------|------|
| **新游戏** | 主菜单 → 共创（用户输入→追问→生成设定→生成大纲）→ 初始化 GameState → 叙事循环 → 结局 → 主菜单 |
| **继续** | 主菜单 → 加载存档 → 恢复 GameState → 直接进入叙事循环 → 结局 → 主菜单 |

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

完整结构见 [phased §1.9](./Storyloom-phased.md#存档文件结构)。核心字段与 GameState 对应，额外包含 `version`、`metadata`（label, created_at, updated_at, model, round_count）、`config`（model, temperature）。

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

### 1.4 区块分隔符速查

> 全部使用英文命名。LLM 输出时必须严格使用以下区块名，程序按正则 `^--- (.+?) ---$` 分割。

| 区块名 | 阶段 | 必需 | 说明 |
|--------|------|------|------|
| `--- narrative ---` | 叙事 | ✅ 必选 | 故事叙述正文 |
| `--- options ---` | 叙事 | 可选 | 2-5 个选项，每行 `N. 描述 @if:条件` |
| `--- branch ---` | 叙事 | 可选 | 局部小分支片段 `[N]` + 汇合文本 `[merge]` |
| `--- state ---` | 叙事 | 可选 | 状态变更，每行 `变量名 操作 值` |
| `--- node ---` | 叙事 | 可选 | 关键节点标记 + 分支判定 + 摘要 |
| `--- bridge ---` | 叙事 | 可选 | 下一轮的上文衔接片段 |
| `--- ending ---` | 叙事 | 可选 | 结局触发标记 |
| `--- adventure_log ---` | 结局 | 可选 | 面向玩家的冒险回顾文本 |
| `=== story_config ===` | 共创 | 必选 | 故事设定（仅共创阶段使用） |
| `=== outline ===` | 共创 | 必选 | 大纲树（仅共创阶段使用） |

> **共创 vs 叙事格式区分**：共创阶段用 `=== xxx ===`（双等号），叙事阶段用 `--- xxx ---`（三短横线）。两者不会同时出现。

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
    ├── 否 → 打印 "未配置 API Key，请检查 .env 文件" → 退出
    └── 是
         ▼
┌─────────────────────┐
│ 2. 加载状态模板      │
│   templates/         │
│   states.json       │
└────────┬────────────┘
         ▼
    文件存在且 JSON 合法？
    ├── 否 → 打印 "模板文件缺失或损坏" → 退出
    └── 是
         ▼
    三套模板 (romance/adventure/mystery) 都存在？
    ├── 否 → 打印 "模板定义不完整" → 退出
    └── 是
         ▼
┌─────────────────────┐
│ 3. 进入主菜单        │
└─────────────────────┘
```

**伪代码**：
```
config = load_dotenv()
if not config.api_key:
    print("未配置 API Key...")
    exit(1)

templates = load_json(TEMPLATES_PATH)
for genre in ["romance", "adventure", "mystery"]:
    if genre not in templates:
        print("模板定义不完整...")
        exit(1)
```

### 2.2 主菜单逻辑

```
进入主菜单
    │
    ▼
检查 saves/save.json 是否存在且可解析
    │
    ├── 存在且有效 → 显示 "当前状态：有存档（{label}，第{round_count}轮）"
    ├── 不存在 → 显示 "当前状态：无存档"
    └── 存在但损坏 → 显示 "存档已损坏"，等同于无存档
         ▼
┌─────────────────────────────────────────┐
│           Storyloom - 文字冒险            │
│                                         │
│          [1] 新游戏    [2] 继续           │
│                                         │
│  当前状态：无存档 / 有存档（xxx，第N轮）    │
└─────────────────────────────────────────┘
         │
         ▼
    用户按键
    ├── 1 → 新游戏流程
    └── 2 → 继续流程
```

#### 路径 [1]：新游戏

```
用户按 1
    │
    ▼
saves/save.json 存在？
├── 是 → 打印 "已有存档（{label}），开始新游戏将覆盖旧存档，确定吗？(y/n)"
│        ├── y → 删除旧存档，进入共创阶段（§3）
│        └── n → 返回主菜单
└── 否 → 直接进入共创阶段（§3）
```

#### 路径 [2]：继续

```
用户按 2
    │
    ▼
saves/save.json 存在？
├── 否 → 打印 "没有存档，请开始新游戏" → 返回主菜单
└── 是
         ▼
    JSON 可解析且结构完整？
    ├── 否 → 打印 "存档已损坏，请开始新游戏"
    │        删除或忽略损坏文件 → 返回主菜单
    └── 是
         ▼
    关键字段完整性校验（见 §6.3 存档损坏判定）
    ├── 不通过 → 打印具体原因 + "存档已损坏，请开始新游戏" → 返回主菜单
    └── 通过
         ▼
    加载存档 → 恢复 GameState → 进入叙事循环（§4）
```

**存档损坏判定**（详见 §6.3）：
- JSON 解析失败
- 缺少 `version` / `story_config` / `state_vars` / `outline` / `progress`
- `progress.current_node` 指向的 node_id 在 `outline` 中不存在
- `state_template` 指向的模板在当前 `templates/states.json` 中不存在

---

*下一节：[§3 共创阶段](#)（待编写）*
