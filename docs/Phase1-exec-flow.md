# Phase 1 程序执行流程详解

> **定位**：精准、简洁的程序执行逻辑描述，供开发者/AI 快速把握 Phase 1 该做什么。  
> **配套文档**：Prompt 模板、格式示例等完整技术细节见 [`Storyloom-phased.md`](./Storyloom-phased.md)。  
> **权威性**：本文档与 phased doc 如有冲突，以本文档为准。本文档的讨论结论将回溯修正 phased doc。

---

## §1 总览

### 1.1 术语速查

**共创与大纲**

| 术语 | 含义 | 详见 |
|------|------|------|
| **story_config** | 共创阶段产出的故事设定，包含题材、档位、世界观、角色等字段 | §3.4 |
| **大纲** | 由关键节点组成的有向图，描述故事骨架。节点间可有分支，分支可在后期节点汇合 | §3.5 |
| **状态模板** | 硬编码三套：恋爱 (romance)、冒险 (adventure)、悬疑 (mystery)。提供 state_vars 初始值和类型定义 | §3.4 |
| **冒险日志 (adventure_log)** | 结局时独立生成的冒险回顾，不走正常叙事循环 | §5.4 |

**剧情段与路由**

| 术语 | 含义 | 详见 |
|------|------|------|
| **剧情段** | 每轮 LLM 生成的一段叙事文本，为循环基本单位 | §4 |
| **关键节点 (checkpoint)** | 大纲上的里程碑节点。到达时触发进度推进和自动存档 | §4.9 |
| **段内分支** | 同一剧情段内的叙事分支，通过 `@branch` 路由实现，不影响大纲走向 | §4.2.2 |
| **大纲分支** | 大纲层面的分叉路线，各分支经历独立 checkpoint，可在后期汇合。通过 `if -> route` 实现 | §4.9 |
| **bridge** | `--- bridge ---` 分隔符，标记交互区块结束、尾部叙事开始。程序执行到此触发下一轮 Prompt 组装 | §4.2.3 |
| **bridge_text** | bridge 之后至段末的正文内容，作为下一轮 User Message 实现衔接 | §4.2.3 |
| **区块分隔符** | LLM 输出的结构化标记，格式 `--- 区块名:分支名 ---` | §4.2.1 |
| **current_branch** | 当前段内分支名，决定程序匹配哪些命名区块。初始 `"main"` | §4.2.2 |
| **choice_dict** | 本轮选项结果，key 为 `choice:` 声明值，value 为玩家选择的编号 | §4.2.2 |

**状态与存档**

| 术语 | 含义 | 详见 |
|------|------|------|
| **状态变量 (state_vars)** | 游戏内可变数据，LLM 通过 `--- state ---` 建议变更，程序校验后应用 | §4.8 |
| **GameState** | 程序内存中维护的完整游戏状态，包含 state_vars、outline、progress 等 | §3.6 |
| **rejected_changes** | `--- state ---` 中被校验拒绝的变更条目，下轮 Prompt 反馈给 LLM | §4.8 |
| **checkpoint_summaries** | 累积的 checkpoint 情节摘要列表，注入每轮 Prompt | §4.3 |
| **游戏存档** | `saves/` 下的独立 `.json` 文件，每次游玩一个 | §6 |

> **注**：术语表随文档编写持续补充。

### 1.2 程序生命周期总览

```
程序启动（加载 .env、模板文件）
  │
  ▼
主菜单
  ├── [1] 新游戏 → 共创 → init GameState → 叙事循环(N轮) → 结局 → 返回主菜单
  ├── [2] 继续   → 选档 → restore GameState → 叙事循环(N轮) → 结局 → 返回主菜单
  ├── [3] 管理   → 查看/删除存档 → 返回主菜单
  └── [4] 退出   → exit(0)
```

### 1.3 核心原则

> 以下原则贯穿 Phase 1 全部流程，后续章节中的具体逻辑均基于这些原则展开。

| 原则 | 说明 |
|------|------|
| **最多一个关键节点** | 同一个剧情段最多只能包含一个关键节点，若包含多个关键节点，尤其是多分支节点时，程序负担大大增加 |
| **本地数据为唯一真相源** | 一切游戏数据以本地 GameState 为准。LLM 只能*建议*变更，程序校验通过后方可应用。选项条件基于本地 state_vars 判定；Prompt 数据取自本地；LLM 输出与本地冲突时以本地为准（如引用不存在的变量 → 拒绝；node_id 不在 outline 中 → 忽略） |
| **bridge 之后无底层数据变更** | 程序执行到 `--- bridge ---` 时触发下一轮 Prompt 组装。bridge 之后不得出现 `--- state ---`、`--- checkpoint ---` 或 `--- options ---`。允许命名 `--- narrative ---` 作为路径过渡变体——程序仅提取匹配 `current_branch` 的那一条正文，剥离分隔符后包装为 `--- narrative:main ---` 注入下一轮 User Message（冒险日志由独立 Prompt 生成，见 §5.4） |
| **交互内容前置于 bridge** | options / state / checkpoint 等交互和变更区块集中在段前部，bridge 之后为纯叙事缓冲，确保提前提交 Prompt，LLM 有充裕响应时间 |
| **超时截断由 LLM 收束** | 程序超时截断时，通知 LLM 快速收束已有内容、插入 bridge 后返回——截断后的内容仍由 LLM 决定 |
| **用户体验无缝衔接** | 前一个剧情段展示结束前，后一个剧情段应已生成完毕。bridge 标记触发提前请求——程序展示 bridge_text 的同时后台等待 LLM 响应。剧情段是 LLM 的划分，但用户体感上不应感知到段边界 |
| **程序拥有最终控制权** | LLM 负责叙事，程序负责数据完整性和流程控制。API 失败、解析错误、内容异常——告知用户并等待决策。LLM 输出错误（如死路分支）不属于程序错误，不设兜底 |
| **条件变量解析优先级** | `if` 条件中的变量名优先匹配 choice_dict（本轮选项结果），其次匹配 state_vars。同名时 choice_dict 优先 |

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
用户按 1 → 直接进入共创阶段（§3）
（不检查覆盖，每个新游戏生成独立存档文件）
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
    逐个读取存档，校验完整性（§6 判定标准）
    ├── 损坏文件 → 跳过，记录警告
    └── 有效文件 → 收集 { filename, label, round_count, updated_at }
         ▼
    有效存档数 = 0？
    ├── 是 → 打印 "没有有效存档" → 返回主菜单
    └── 否
         ▼
    展示存档列表 → 用户选择 → 加载 → 恢复 GameState → 进入叙事循环（§4）
```

> **优化**：仅 1 个有效存档时可跳过列表直接加载。实现时自行决定。

#### 路径 [3]：存档管理

```
用户按 3
    │
    ▼
无有效存档 → 打印 "没有可管理的存档" → 返回主菜单
有存档 → 展示列表 → 用户选择 → 展示详情 → [1] 删除 [2] 返回列表 [0] 返回
删除需二次确认："确定删除存档'{label}'？此操作不可恢复。(y/n)"
```

#### 路径 [4]：退出

```
用户按 4 → exit(0)
```

---

## §3 共创阶段

### 3.1 阶段总览

```
用户输入初始想法
      ↓
┌─────────────────┐
│ Step 1-2: 追问循环 │ ← 同一对话上下文累积
│ （LLM 提问→用户回答）│
└────────┬────────┘
         ↓ 用户确认"开始" / LLM 认为足够
┌─────────────────┐
│ Step 3: 生成故事设定 │ ← 静默（用户看等待提示）
│ 解析题材→加载模板    │
└────────┬────────┘
         ↓
┌─────────────────┐
│ Step 4: 生成大纲树  │ ← 静默
│ 静态校验            │
└────────┬────────┘
         ↓
┌─────────────────┐
│ Step 5: 初始化      │
│ GameState → 叙事循环│
└─────────────────┘
```

**耗时提示**：Step 2 以用户交互为主，Step 3-4 各需一次 LLM 调用（数秒至十数秒），程序显示等待文案。

### 3.2 Step 1: 用户输入初始想法

```
程序打印：
  "请描述你想玩的故事（如'赛博朋克背景下的爱情故事'）"

用户输入自由文本 → raw_idea
```

无校验——任何非空文本均接受。空输入提示重新输入。用户可能一开始就有详细想法，不限制输入长度。

### 3.3 Step 2: 追问循环

**流程**：

```
将 raw_idea 发送给 LLM（追问 Prompt）
    │
    ▼
┌────────────────────────────────────────────┐
│ 循环：                                       │
│   LLM 回复（提问 + 可选参考选项）               │
│   → 程序展示回复                              │
│   → 用户回复 / "开始" / "不玩了"               │
│   → 追加到对话历史                             │
│   → 若用户说"开始"或 LLM 在回复末尾询问         │
│     "是否开始生成故事？" 且用户确认 → 退出循环    │
└────────────────────────────────────────────┘
```

**终止条件**（任一满足即退出）：

| 条件 | 行为 |
|------|------|
| 用户在任意回复中输入"开始"或同义词 | → 进入 Step 3 |
| LLM 在回复末尾主动询问"是否开始生成故事？"，用户回复肯定 | → 进入 Step 3 |
| 用户输入"不玩了" | → 确认 "确定退出共创，返回主菜单？(y/n)" → y 回主菜单，n 继续 |
| Ctrl+C | → 直接退出程序，不提示确认，不留存档 |

> 追问不做轮数上限——由 LLM 判断信息是否足够。追问过程中用户可自然修正之前的回答，无需回退机制。

> ⚠️ **追问范围约束（关键）**：LLM 必须聚焦于**世界观、主角设定、故事基调、冲突方向、故事长度**五大维度。故事长度从 §A.3 三档中选择（短篇/中篇/长篇），由用户明确选择或 LLM 根据题材判断。严格禁止涉及具体情节走向或透露后续内容——以保持玩家对故事的新鲜度。此约束以醒目方式写入追问 Prompt。

### 3.4 Step 3: 生成故事设定

**流程**：

```
1. 程序展示等待文案："正在编织故事世界……"

2. 发送设定生成 Prompt 给 LLM
   → LLM 返回 === story_config === 格式文本

3. 解析（正则按 === story_config === 分割，逐字段提取）：
   ├── 解析成功？
   │   └── 否 → 重试（附带缺失字段提示），最多 MAX_RETRIES 次
   │            → 耗尽 → 告知用户，询问：重试 / 返回主菜单
   └── 是
        ▼
4. 题材映射：
   story_config.genre ∈ ["romance", "adventure", "mystery"]？
   ├── 否 → 重试（附带合法值列表），最多 MAX_RETRIES 次
   │        → 耗尽 → 告知用户，询问：重试 / 返回主菜单
   └── 是
        ▼
5. 加载状态模板：
   templates = load_json(TEMPLATES_PATH)
   state_template = templates[story_config.genre]
   → 模板不存在？→ 告知用户（严重错误，模板文件被修改），返回主菜单

6. 故事设定不向用户展示（保持新鲜度）
```

**`=== story_config ===` 解析字段**：

| 字段 | 必需 | 说明 |
|------|------|------|
| `题材` | ✅ | `romance` / `adventure` / `mystery` |
| `档位` | ✅ | `short` / `medium` / `long`，控制故事总段数、段长和选项数（对应 §A.3 常量组） |
| `标签` | ✅ | `STORY_LABEL_MIN_CHARS`-`STORY_LABEL_MAX_CHARS` 字简短命名，用于存档文件名和列表展示 |
| `世界观` | ✅ | 一句话世界观描述 |
| `主角姓名` | ✅ | |
| `主角身份` | ✅ | |
| `主角特质` | ✅ | |
| `叙事风格` | ✅ | |
| `核心冲突` | ✅ | |
| `主要角色` | ✅ | 至少 1 个，每行 `- 角色名 \| 角色定位 \| 与主角关系` |

> **可拓展性**：题材映射表在 `config.py` 中维护（`GENRE_TEMPLATE_MAP`），新增题材只需加映射条目和对应模板。

### 3.5 Step 4: 生成大纲树

**流程**：

```
1. 程序展示等待文案："正在绘制故事脉络……"

2. 发送大纲生成 Prompt 给 LLM
   → Prompt 中注入 story_config + 可用状态变量名列表
   → LLM 返回 === outline === 格式文本

3. 解析（正则按 === outline === 分割，逐节点提取）：
   ├── 解析成功？
   │   └── 否 → 重试，最多 MAX_RETRIES 次
   │            → 耗尽 → 告知用户，询问：重试 / 返回主菜单
   └── 是
        ▼
4. 静态校验：
   ┌─────────────────────────────────────────────────────┐
   │ a. 所有 if ... -> route <target_node_id> 的目标      │
   │    节点是否存在于大纲中？                               │
   │ b. 分支条件引用的变量是否存在于当前状态模板？             │
   │    （不存在仅记日志警告，不强制拒绝——LLM 可在运行时补充）  │
   │ c. 最后一个节点的 branches 是否为空（结局节点）？        │
   │ d. 节点数是否 ≥ 1？（有没有起点）                       │
   │ e. 第一个节点是否为唯一入口？（无其他节点指向它）          │
   └─────────────────────────────────────────────────────┘
   ├── 校验通过？→ 继续
   └── 校验失败？→ 重试（附带具体错误提示），最多 MAX_RETRIES 次
                   → 耗尽 → 告知用户具体校验失败原因，
                     询问：重试 / 返回主菜单

5. 大纲不向用户展示
```

**`=== outline ===` 解析字段**（每个节点）：

| 字段 | 必需 | 说明 |
|------|------|------|
| `节点N：标题 \| node_id` | ✅ | N 从 1 递增；node_id 格式 `ch序号_英文缩写` |
| `目标` | ✅ | 本章叙事目标（内部指引，不给玩家看） |
| `分支说明` | 可选 | 人类可读的分支方向描述 |
| `分支：条件 → node_id` | 可选 | 0-2 条；无分支写 `分支：无` |

### 3.6 Step 5: 初始化 GameState

大纲校验通过后，初始化内存中的 GameState：

```
game_state = GameState()
game_state.story_config   = story_config           // Step 3 解析结果
game_state.state_template = genre                  // "romance"|"adventure"|"mystery"
game_state.state_vars     = templates[genre].vars  // 模板默认初始值（深拷贝）
game_state.outline        = outline                // Step 4 解析+校验结果
  → 第一个节点 status = "active"，其余 = "pending"
game_state.progress = {
    current_node:         outline[0].node_id,
    round_count:          0,
    checkpoint_history:   [],
    checkpoint_summaries: [],
    checkpoint_snapshots: {}
}
game_state.bridge_text    = ""                     // 首轮为空
game_state.rejected_changes = []

进入叙事循环（§4）
```

---

## §4 叙事循环

### 4.1 单轮总览

```
Round N 开始
    │
    ▼
┌─────────────────────────────┐
│ 1. Prompt 组装（§4.3）       │
│   system + user(bridge_text) │
└─────────────┬───────────────┘
              ▼
┌─────────────────────────────┐
│ 2. API 调用（§4.4）          │
│   流式接收 / 超时截断         │
└─────────────┬───────────────┘
              ▼
┌─────────────────────────────┐
│ 3. 响应解析（§4.5）          │
│   分割→路由过滤→逐区块解析    │
└─────────────┬───────────────┘
              ▼
┌─────────────────────────────┐
│ 4. 内容展示（§4.6）          │
│   逐段展示正文 + 分支路由     │
└─────────────┬───────────────┘
              ▼
┌─────────────────────────────┐
│ 5. 玩家交互（§4.7）          │
│   选项选择 / 自动推进 / Q键   │
└─────────────┬───────────────┘
              ▼
┌─────────────────────────────┐
│ 6. 状态变更校验（§4.8）       │
│   逐条校验→应用/拒绝          │
└─────────────┬───────────────┘
              ▼
┌─────────────────────────────┐
│ 7. 节点推进与存档（§4.9）     │
│   分支评估→更新current_node  │
│   →checkpoint快照→自动存档   │
└─────────────┬───────────────┘
              ▼
┌─────────────────────────────┐
│ 8. 下一轮准备（§4.10）       │
│   bridge_text 提取→          │
│   round_count++→结局检测     │
└─────────────────────────────┘
```

> 以上 8 步每轮执行一次。LLM 响应先完整接收再解析（非流式解析），正文展示用缓冲控制节奏（见 §4.6）。

### 4.2 区块分隔符与执行模型

#### 4.2.1 分隔符速查

> 全部使用英文命名。LLM 输出时必须严格使用以下区块名。程序按正则 `^--- (\w+)(?::(\w+))? ---$` 提取区块类型和分支名。
> 部分区块支持**分支名**：`--- block:branch ---`（缺省 branch 即为 `main`），用于段内路由（见 §4.2.2）。

| 区块标记 | 必需 | 支持分支名 | 说明 |
|----------|------|----------|------|
| `--- narrative ---` | ✅ 必选 | ✅ | 故事叙述正文 |
| `--- options ---` | 可选 | ✅ | 选项列表。第一行 `choice: 选择名` |
| `--- state ---` | 可选 | ✅ | 数据变更 + 段内路由 |
| `--- checkpoint ---` | 可选 | ❌ 固定 main | 大纲路由。`node <id>` 或 `end` |
| `--- bridge ---` | 通常必选 | ❌ 固定 main | 下一轮衔接标记。结局轮除外 |
| `--- adventure_log ---` | 结局可选 | ❌ 固定 main | 冒险回顾，由独立 Prompt 生成（§5.4），不嵌入剧情段 |
| `=== story_config ===` | 共创必选 | — | 故事设定（共创阶段） |
| `=== outline ===` | 共创必选 | — | 大纲树（共创阶段） |

> **共创 vs 叙事**：共创用 `=== xxx ===`，叙事用 `--- xxx ---`。两者不会同时出现。

#### 4.2.2 分支路由机制

程序每轮维护两个临时变量（轮次结束时清空）：

| 变量 | 初始值 | 说明 |
|------|--------|------|
| `current_branch` | `"main"` | 当前执行的分支名 |
| `choice_dict` | `{}` | 选项选择值 |

**路由规则**：

```
程序从头到尾顺序扫描区块标记行：
  区块 branch == current_branch 或 branch == "main"？
  ├── 是 → 执行该区块内容
  └── 否 → 跳过，继续
```

**`current_branch` 修改来源**：

| 来源 | 语法 | 示例 |
|------|------|------|
| options 选项行 | `-> branch` | `1. 接过芯片 -> took_chip` |
| state 无条件 | `@branch 值` | `@branch desperate` |
| state 条件结果 | `if ... -> @branch 值` | `if 体力 < 20 -> @branch desperate` |

**`choice_dict` 修改来源**：options 第一行声明 choice，玩家选择后 `choice_dict["选择名"] = 选择编号`。

> checkpoint、bridge 固定为 `main`，不参与段内路由。

#### 4.2.3 各区块语法

**`--- narrative ---`**

纯叙事文本，支持分支名实现段内分支：
```
--- narrative:main ---
（主分支叙事……）

--- narrative:took_chip ---
（仅 current_branch=="took_chip" 时展示……）
```

**`--- options ---`**

第一行必须声明 `choice`。选项行可附带 `@if:条件` 和 `-> branch`：
```
--- options:main ---
choice: chip_choice
1. 接过芯片 -> took_chip
2. 暂时离开 @if: 理智值 >= 30 -> left
```
处理：展示选项 → 玩家选择 → `choice_dict["chip_choice"] = N` → 若选项有 `-> branch`，设置 `current_branch = branch`。

> **约束**：同一剧情段内所有 `--- options ---` 的 choice 必须唯一。

**`--- state ---`**

无条件变更直接执行；条件变更每行独立评估，命中即执行：
```
--- state:main ---
@var 理智值 -10
if chip_choice == 1 -> @var 线索 +神秘芯片, @branch took_chip
if 信任度 >= 50 and 好感度 >= 30 -> @var 关系阶段 =朋友
```

**条件语法规则**：

| 元素 | 说明 |
|------|------|
| 变量名 | 中文，必须引用 state_vars 中存在的变量或同段 options 的 `choice:` 声明值。程序按 §1.3 优先级解析（choice_dict > state_vars） |
| 运算符 | `==` `>=` `<=` `>` `<` `has` |
| 组合 | `and` / `or`。每条条件最多使用一次 and 或一次 or，不允许混合 |
| 动作 | `@var 变量 操作 值` / `@branch 值` / `route node_id`（仅 checkpoint） |
| 关键字 | `if` `->` `@var` `@branch` 固定英文 |

**`@var` 操作符**：

| 操作 | 语法 | 示例 | 适用类型 |
|------|------|------|----------|
| 加减 | `@var 变量 +N` / `@var 变量 -N` | `@var 体力 -10` | number |
| 赋值 | `@var 变量 =值` | `@var 关系阶段 =朋友` | number / string |
| 追加 | `@var 变量 +元素` | `@var 线索 +神秘芯片` | list |
| 移除 | `@var 变量 -元素` | `@var 背包 -旧钥匙` | list |

> **choice 条件规范**：`if 芯片选择 == 1` 中的 `芯片选择` 必须与同段 `--- options ---` 的 `choice:` 声明值完全一致。禁止使用 `选择1`、`选项1` 等占位词——程序校验时引用不存在的变量名将被拒绝并记入 rejected_changes。
>
> 条件语法为建议语法，调整须兼顾：(1) 程序可准确解析；(2) LLM 能稳定生成。

**`--- checkpoint ---`**

仅做大纲路由，**不修改 state_vars**。如需数据变更，先执行 `--- state ---`：
```
--- checkpoint ---
node ch2_discovery
if 信任度 >= 50 -> route ch3_ally
if 信任度 < 50 -> route ch3_betrayal
summary: 在酒吧获得加密芯片……
```
结局节点：
```
--- checkpoint ---
end
summary: 所有线索汇集……
```
- `node <id>` 或 `end`：标记到达的节点
- `if 条件 -> route <next_node_id>`：分支路由，取首个命中。无条件命中 → 取第一个分支的 next_node
- `summary:`：checkpoint 摘要（必填）

**`--- bridge ---`**

标记下一轮 Prompt 组装的触发点。LLM 应先完整生成所有内容块，再选择合适位置插入 bridge。bridge 之后至段末为 bridge_text。

**bridge 之后的区块限制**：

| 区块 | 允许 | 说明 |
|------|------|------|
| `--- state ---` | ❌ | 底层数据变更必须在 bridge 之前 |
| `--- checkpoint ---` | ❌ | 大纲路由必须在 bridge 之前 |
| `--- options ---` | ❌ | 选项交互必须在 bridge 之前 |
| `--- narrative:any_branch ---` | ✅ | 作为不同路径的过渡/悬念文本变体。程序仅提取匹配 `current_branch` 的那一条 |

**bridge_text 提取流程**：

```
程序解析到 --- bridge --- 后：
  1. 记录 bridge 之后至段末的全部内容
  2. 扫描其中的 --- narrative:xxx --- 区块
  3. 取 branch == current_branch 或 branch == "main" 的那一条（取第一个匹配）
  4. 剥离该区块的分隔符标记行，保留纯正文
  5. 组装下轮 User Message：
       "--- narrative:main ---\n（提取的正文）"
  6. 其余命名 narrative 跳过（不展示、不注入下轮 Prompt）
```

> **效果**：玩家看到其选择路径对应的过渡文本；下一轮 LLM 收到的 User Message 是干净的 `--- narrative:main ---`，不含其他分支残留。

**多分支场景**：若本段 checkpoint 为多分支节点（在 bridge 之前已处理），bridge 之后可包含多个命名 `--- narrative ---`，分别对应各分支的承接文本。提取机制保证只有当前路径的那一条被注入下一轮。

**结局轮的 bridge 位置**：当 checkpoint 为 `end` 时，bridge 插入在 `end` 之后、尾部缓冲 narrative 之前：

```
--- checkpoint ---
end
summary: ...
--- bridge ---               ← 必选，触发冒险日志请求
--- narrative:main ---       ← 缓冲叙事（用户无感知）
（缓冲正文……）
```

程序处理到 bridge 时检测到 `ending_flag`，提交冒险日志 Prompt（§5.4）。尾部 narrative 作为缓冲确保 LLM 有充裕响应时间，展示时用户体感连续。

> **设计考量**：bridge 位置不宜太靠后，确保 bridge_text 有足够长度供 LLM 响应；可通过 `BRIDGE_MIN_RATIO_BEFORE_END` 常量约束（段目标字数 × 比例 = 最少 bridge_text 长度）。

### 4.3 每轮 Prompt 的组成

每轮发送给 LLM 的完整 Prompt = System Prompt + User Message：

```
完整 Prompt:
  ├── System Prompt（由 prompt_builder 组装）:
  │     ├── 固定部分：游戏规则 + 输出格式要求 + 格式示例
  │     ├── 故事背景：story_config 全部字段
  │     ├── 大纲：outline_text（所有节点 + [completed]/[active]/[pending] 标注）
  │     ├── 进度：current_node + goal + completed_nodes_summary
  │     ├── 重要事件：checkpoint_summaries_text
  │     ├── 当前状态：state_summary（所有 state_vars 格式化）
  │     └── 拒绝反馈：rejected_changes_feedback（仅当非空）
  │
  └── User Message:
        └── bridge_text（上一轮 bridge 之后至段末的正文；首轮为空）
```

### 4.4 API 调用与响应接收

**流程**：

```
1. prompt_builder.assemble() → system_prompt, user_message
2. api_client.stream_chat(system_prompt, user_message)
   │
   ├── 正常完成 → 完整 LLM 响应文本
   │
   ├── 流式停顿超时（STREAM_STALL_TIMEOUT_SEC）
   │   └── 程序截断流 → 取已接收内容
   │       → 在最后一个完整段落处截断
   │       → 截取内容 ≥ MIN_NARRATION_CHARS？
   │           ├── 是 → 继续解析
   │           └── 否 → 提示用户：重试 / 用当前内容继续 / 返回主菜单
   │
   └── API 错误（网络 / rate limit / server error）
       └── 告知用户具体错误信息
           → 用户选择：重试 / 返回主菜单
```

> API 调用失败**不自动重试**，始终由用户决策。

### 4.5 响应解析

采用**边遍历边执行 + 显示缓冲**模式：程序遍历区块时，state/checkpoint 等数据区块立即执行，narrative/options 等显示区块缓存后按节奏展示。

**解析流程**：

```
1. 预处理
   → 去除首尾空白
   → 去除 markdown 代码块围栏（```...``` 或 ```text...```）
   → 检测阶段标记：
       === xxx === → 共创阶段（本循环不应出现，视为错误）
       --- xxx --- → 叙事阶段，继续

2. 按正则 ^--- (\w+)(?::(\w+))? ---$ 分割
   → 得到 [(block_type, block_branch, block_content), ...] 列表

3. 遍历列表（按物理顺序）：
   对每个区块：
     block_branch == current_branch 或 block_branch == "main"？
     ├── 否 → 跳过
     └── 是 → 按类型分发：
         "narrative" → 缓存到展示队列
         "options"   → 缓存到展示队列（等 narrative 展示完再展示）
         "state"     → 立即执行（§4.8）
         "checkpoint"→ 立即执行（§4.9）
         "bridge"    → 触发下一轮组装 + 提取 bridge_text（§4.10）
```

> **关键**：程序执行快于展示。遍历时 state/checkpoint 立即生效（数据层），而 narrative 缓存后逐段展示（表现层）。两者异步，互不阻塞。

**各区块内容解析**：见 §4.2.3 各区块语法。解析失败处理见下文各节。

### 4.6 内容展示

**展示模式**：支持自动和手动两种，用户可随时切换。

| 模式 | 行为 | 切换键 |
|------|------|--------|
| **自动**（默认） | 每段之间延迟 AUTO_ADVANCE_DELAY_MS 后自动继续 | 按 `M` 切换至手动 |
| **手动** | 每段展示后等待用户按任意键继续 | 按 `M` 切换回自动 |

**展示流程**：

```
1. 从展示队列取 --- narrative --- 正文
2. 按空行分割为段落
3. 逐段展示：
   ├── 自动模式：打印段落 → 延迟 → 继续下一段
   └── 手动模式：打印段落 → 等待按键 → 继续下一段

4. narrative 展示完毕后：
   ├── 有 --- options ---？→ 展示选项面板（§4.7）
   └── 无 → 展示 bridge_text → 自动进入下一轮
```

**命名 narrative 展示**：遍历时仅 `current_branch` 匹配的 narrative 进入展示队列。玩家看到的是其选择路径的叙事，其余分支的 narrative 不展示。

**bridge_text 展示**：bridge 之后的内容继续从展示队列输出，用户无感知——体感上是连续叙事。

### 4.7 玩家交互

**选项展示**：

```
  [1] 接过芯片                        ← 正常可选
  [2] 暂时离开（需理智值≥30，当前：20）  ← dim 样式，不可选
  [3] 先发制人                        ← 正常可选
```

**选项处理**：

```
展示选项面板 → 等待键盘输入（1-5 或 Q 或 M）
  ├── 数字键 → 对应选项
  │   ├── enabled → choice_dict[choice] = N，若选项有 -> branch 则更新 current_branch
  │   └── disabled → 短暂提示"条件不满足"，重新等待输入
  ├── Q → 主动结束流程（见 §5.3）
  └── M → 切换自动/手动展示模式
```

**置灰逻辑**：

```
对每个选项：
  有 @if:条件？
  ├── 否 → enabled
  └── 是 → 用本地 state_vars 评估条件
      ├── 满足 → enabled
      └── 不满足 → disabled（dim 颜色 + 显示当前值）

全部 disabled？
  → 全部以 enabled 样式展示，移除条件标注（兜底防卡死）
```

**无选项时的自动推进**：`--- options ---` 缺失 → 正文展示完毕后自动进入下一轮，不等待输入。

### 4.8 状态变更校验与应用

处理 `--- state ---` 中每条变更，逐条独立执行（一条失败不影响其他）。

**校验规则**：

| 校验 | 失败处理 |
|------|---------|
| 变量名不存在于当前模板 | 静默忽略，记入 rejected_changes |
| number 类型操作越界 | clamp 到 `[min, max]`，静默处理 |
| list `+` 元素已存在 | 静默忽略 |
| list `-` 元素不存在 | 静默忽略 |
| 操作符与类型不匹配 | 拒绝，记入 rejected_changes |

**伪代码**：

```
for each line in state_block:
    parse: @var var_name operator value

    if var_name not in state_template.vars:
        rejected_changes.append({line, reason: "变量不存在"})
        continue

    var_def = state_template.vars[var_name]
    valid = validate(var_def.type, var_def, operator, value)

    if not valid:
        rejected_changes.append({line, reason: valid.error})
        continue

    apply(state_vars[var_name], operator, value)
```

> **静默处理**：list 增删重复/不存在的元素、number 越界取上下限——不中断流程，不展示给用户，但记入 rejected_changes，在下一轮 Prompt 中告知 LLM。

### 4.9 节点推进与存档

`--- checkpoint ---` 区块触发。

**流程**：

```
1. 提取第一行：
   ├── "node <node_id>" → 标记关键节点
   └── "end" → 结局节点：设置 ending_flag = true，其余推进逻辑相同（标记 completed、存入摘要和快照、触发存档）。后续 bridge 处检测到此标志时走结局路径（§4.10.1）

2. 验证 node_id 存在于 outline：
   ├── 否 → 记日志，忽略该 checkpoint，继续
   └── 是

3. 标记旧 current_node 为 "completed"

4. 若有 if 条件行：
   逐条评估（按物理顺序，取首个命中）：
     if 条件 -> route <target_node_id>
     ├── 条件命中 → 目标节点 = target_node_id
     ├── 条件中引用的变量不存在 → 该条视为无效，跳过
     ├── 多个命中 → 取第一个
     └── 全部不命中 → 取第一条分支的 target_node_id（兜底）

   若无分支 → 目标节点 = outline 中下一个节点

5. 标记目标节点为 "active"，更新 progress.current_node

6. 存入 checkpoint_summaries（summary 字段）

7. 存储 checkpoint_snapshots[current_node] = deep_copy(state_vars)

8. 触发自动存档 → 覆盖 saves/{label}.json（原子写入）
```

**兜底策略说明**：分支条件全部不命中 → 取 LLM 列出的第一个分支。这要求 LLM 按优先级排列分支条件。

### 4.10 下一轮准备与结局检测

#### 4.10.1 bridge 处理与结局检测

```
程序执行到 --- bridge ---：
    │
    ├── ending_flag == true？
    │   └── 是 → 组装冒险日志 Prompt（§5.4）→ 发 LLM → 继续展示 bridge_text
    │           → bridge_text 展示完毕 + 响应就绪 → 展示 adventure_log → 返回主菜单
    │
    └── 否 → 正常准备：
        1. bridge_text 提取（§4.2.3 bridge 节）
        2. round_count += 1
        3. 组装下一轮 Prompt → Round N+1
```

> `ending_flag` 由 §4.9 中 checkpoint 处理为 `end` 时设置。

---

## §5 结局阶段

### 5.1 结局触发路径

| 路径 | 触发条件 | 说明 |
|------|---------|------|
| **自然结局** | `--- checkpoint ---` 中为 `end` | 大纲终点，最后一轮由 LLM 自然收束 |
| **主动结束** | 玩家在选项面板按 Q | 随时中断，跳过后续大纲 |

两条路径最终汇聚：展示冒险日志 → 返回主菜单。

> 结局后不删除存档——玩家可通过"继续"重新查看冒险日志，或通过"存档管理"删除。

### 5.2 自然结局（checkpoint `end`）流程

```
倒数第二轮（Round N-1）：
  --- narrative:main ---
  （结局叙事段落……）
  --- checkpoint ---
  end
  summary: 所有线索在此交汇……
  --- bridge ---
  （最后的衔接文本——缓冲用，保持与正常剧情段一致的结构）

程序处理：

  1. 正常解析 → 展示 narrative → 处理 state（如有）
  2. 处理 checkpoint：
     a. 检测到 "end" → 标记 outline 最后一个节点为 completed
     b. 设置 ending_flag = true
     c. 存入 checkpoint_summaries
     d. 存储 checkpoint_snapshots
     e. 触发自动存档（与其他 checkpoint 行为一致）
  3. 执行到 bridge：
     a. 检测到 ending_flag == true
     b. 不组装正常下一轮 Prompt
     c. 组装"冒险日志 Prompt"（§5.4）
     d. 发送给 LLM → 等待响应
  4. 继续展示 bridge_text（缓冲叙事）——与正常轮次无差异
  5. bridge_text 展示完毕 + LLM 响应已就绪：
     → 展示 adventure_log 内容
     → 打印 "按任意键返回主菜单……"
     → 等待按键 → 返回主菜单
```

> **关键**：bridge 放在 checkpoint `end` 之后、尾部 narrative 之前。程序在 bridge 处检测到 ending_flag，提交冒险日志请求。尾部 narrative 作为缓冲，确保 LLM 有足够响应时间。

### 5.3 Q 键主动结束流程

```
玩家在选项面板按 Q
    │
    ▼
打印 "确定结束游戏？(y/n)"
├── n → 返回选项面板
└── y
     ▼
打印 "是否查看冒险日志？(y/n)"
├── n → 直接返回主菜单
└── y
     ▼
组装"冒险日志 Prompt"（§5.4）
→ 发送给 LLM → 等待响应
→ 展示 adventure_log 内容
→ 打印 "按任意键返回主菜单……"
→ 等待按键 → 返回主菜单
```

> Q 键主动结束时，当前段可能尚未到达 checkpoint `end`。程序以当前状态生成冒险日志（包含已完成的 checkpoint_summaries）。

### 5.4 冒险日志 Prompt

**触发时机**：checkpoint `end` 轮 bridge 处 / Q 键确认后。

**Prompt 注入数据**：

| 数据 | 来源 |
|------|------|
| 故事设定全文 | `story_config` |
| 最终状态快照 | `state_vars`（当前值） |
| 已完成的 checkpoint 摘要 | `checkpoint_summaries` |
| checkpoint 节点列表 | `checkpoint_history`（node_id + 标题） |

**Prompt 要点**：要求 LLM 生成面向玩家的冒险回顾，包含章节摘要、关键抉择及其影响、结局评语。纯文本格式，不加区块分隔符。

**程序行为**：
```
prompt = build_adventure_log_prompt(story_config, state_vars, checkpoint_summaries, checkpoint_history)
response = api_client.call(prompt)   // 非流式，快速生成
展示 response 正文
```

> 冒险日志为独立 LLM 调用——不走正常叙事循环的解析管线。


---

*下一节：[§6 存档系统](#)*


---

## §6 存档系统

### 6.1 存档文件结构

`saves/` 目录下每个 `.json` 文件代表一次完整游玩。文件名来源于 `story_config.label`（重名追加 `_2`、`_3`）。

核心结构：
```
{
  version: 1,
  metadata: { label, created_at, updated_at, round_count },
  config: { temperature, ... },          // 不存储模型标识，模型以 .env 为准
  story_config: { ... },
  state_template: "romance",
  state_vars: { ... },
  outline: [{ node_id, title, goal, status, branches[] }],
  progress: {
    current_node, round_count,
    checkpoint_history[], checkpoint_summaries[], checkpoint_snapshots{}
  },
  bridge_text: "..."
}
```

> **概念区分**：「游戏存档」是 `saves/` 下的文件；「checkpoint 快照」是存档内部的 `checkpoint_snapshots`。

**存档命名**：文件名来源于 `story_config.label`。非法字符（`/` `\` `:` `*` `?` `"` `<` `>` `|`）替换为 `_`。重名时追加 `_2`、`_3`（取最小未占用编号）。统一存放在 `SAVE_DIR` 下。

### 6.2 自动存档时机

**仅在 checkpoint 到达时触发**（§4.9 步骤 8）。不设手动存档、不在每轮结束时存档。

| 触发条件 | 行为 |
|----------|------|
| `--- checkpoint ---` 中 `node <id>` 或 `end` 被成功处理 | 覆盖 `saves/{label}.json` |
| 其他时机 | 不存档 |

### 6.3 原子写入

```
1. 序列化 GameState → JSON 字符串（indent=2，确保可读）
2. 确保 SAVE_DIR 存在（不存在则 os.makedirs）
3. 写入临时文件：saves/{label}.tmp
4. os.replace(tmp, saves/{label}.json)   // 原子 rename，跨平台安全
```

> 整个过程不涉及 LLM，仅本地文件操作。

### 6.4 存档加载流程

```
load_save(filepath):
  1. 读取 + JSON 解析
     ├── 解析失败 → 存档损坏（JSON 不合法）

  2. 校验 version 字段存在且 == 1
     ├── 不匹配 → 存档损坏（版本不支持）

  3. 校验关键字段存在：
     story_config, state_vars, outline, progress, state_template
     ├── 任一缺失 → 存档损坏（结构不完整）

  4. 校验 state_template 值在 TEMPLATES_PATH 中存在
     ├── 不存在 → 存档损坏（模板被删除）

  5. 校验 progress.current_node 指向的 node_id 在 outline 中存在
     ├── 不存在 → 存档损坏（数据不一致）

  6. 校验通过 → 构建 GameState：
     ├── 状态变量值以存档为准（模板仅提供类型定义校验）
     ├── outline 节点状态以存档为准
     └── config（temperature 等）以存档为准，模型以 .env 为准

  7. 返回 GameState → 进入叙事循环（§4）

  以上任一校验失败 → 存档损坏（致命），永久失效，提示用户后删除文件并返回主菜单。
```

> **模板独立性**：存档自包含——一次游戏创建后，其状态变量集、大纲结构均以存档为准。`templates/states.json` 的后续变更不影响已有存档。模板文件仅在加载时用于验证 `state_template` 标识存在、运行时用于校验 state 变更的类型合法性。

### 6.5 存档内容说明

存档中存储的完整字段列表见 §6.1。补充说明：

| 字段 | 存储时机 | 说明 |
|------|---------|------|
| `metadata.label` | 共创结束后首次存档时写入 | 来源于 `story_config.label` |
| `metadata.created_at` | 首次存档时写入 | 之后不变 |
| `metadata.updated_at` | 每次覆盖存档时更新 | |
| `metadata.round_count` | 每次覆盖存档时更新 | = 当前 `progress.round_count` |
| `progress.checkpoint_snapshots` | 每次 checkpoint 时追加 | 为 Phase 2 回档预留，Phase 1 仅存储不读取 |
| `bridge_text` | 每次覆盖存档时更新 | 加载后作为首轮 User Message |

---

## §A 可配置常量参考

> 以下常量集中在 `config.py` 中定义。所有模块引用常量名，不硬编码数值。参考值可根据实际运行调整。

### A.1 路径常量

| 常量 | 参考值 | 说明 |
|------|--------|------|
| `TEMPLATES_PATH` | `templates/states.json` | 状态模板文件路径 |
| `SAVE_DIR` | `saves/` | 存档目录 |

### A.2 共创阶段

| 常量 | 参考值 | 说明 |
|------|--------|------|
| `MAX_RETRIES` | 2 | 格式解析/校验失败后的最大重试次数（所有 LLM 调用共用） |
| `STORY_LABEL_MIN_CHARS` | 5 | 故事标签最短字符数 |
| `STORY_LABEL_MAX_CHARS` | 15 | 故事标签最长字符数 |

### A.3 故事规模档位

> 共创阶段由用户选择或 LLM 判断，写入 `story_config.tier`（`short` / `medium` / `long`）。影响 Prompt 中的字数指引和大纲节点数推荐。

| 档位 | 适用 | 目标总段数 | 每段目标字数 | 每段选项数 |
|-----------|------|-----------|-------------|-----------|
| `STORY_TIER_SHORT` | 短篇 | 5-10 | 2000 | 0-3 |
| `STORY_TIER_MEDIUM` | 中篇 | 15-20 | 2500 | 0-4 |
| `STORY_TIER_LONG` | 长篇 | 25-50 | 3000 | 0-4 |

档位选定后在 Prompt 中注入对应指引。

### A.4 叙事与运行时

| 常量 | 参考值 | 说明 |
|------|--------|------|
| `STREAM_STALL_TIMEOUT_SEC` | 3 | 流式输出停顿超时秒数 |
| `MIN_NARRATION_CHARS` | 200 | 截取内容最低字符数，低于此值判定异常 |
| `MAX_NARRATION_CHARS` | 4000 | 正文长度上限，超出则程序在完整段落处截断 |
| `BRIDGE_MIN_RATIO_BEFORE_END` | 0.25 | bridge 距段末最少字符数比例（段目标字数 × 此比例 = 最少 bridge_text 长度） |
| `AUTO_ADVANCE_DELAY_MS` | 500 | 自动展示模式下段落间延迟（毫秒） |
| `GENRE_TEMPLATE_MAP` | `{"romance": "恋爱", "adventure": "冒险", "mystery": "悬疑"}` | 题材到模板的映射表，在 `config.py` 中维护 |
| `SAVE_VERSION` | 1 | 存档格式版本号。不匹配则判定存档损坏 |

---

*下一节：[§B 全局约定](#)*

---

## §B 全局约定

> 以下为 Phase 1 全流程的实现规则，与 §1.3 核心原则互补——原则解释"为什么"，约定定义"怎么做"。

| # | 约定 | 说明 |
|---|------|------|
| 1 | **Prompt 语言** | 所有 LLM Prompt 使用中文 |
| 2 | **区块分隔符** | 全部英文（`--- narrative ---`、`--- checkpoint ---` 等），详见 §4.2.1 |
| 3 | **变量命名** | 状态变量名、choice 名使用中文 |
| 4 | **正文限制** | `---` 不得在 narrative 正文中单独成行，避免解析歧义 |
| 5 | **重试策略** | 格式/校验错误最多 `MAX_RETRIES` 次，附带格式纠正提示重试；API 调用失败**不**自动重试——告知用户，用户决定 |
| 6 | **用户决策** | 重试耗尽、API 失败、内容过短等异常——告知用户具体信息，由用户选择（重试 / 继续 / 返回主菜单） |
| 7 | **错误隔离** | state 逐条校验、options 逐行解析——单条失败不影响同轮其余有效条目 |
| 8 | **静默错误** | 微小校验错误（list 增删不存在元素、number 越界 clamp 到限值）不展示给用户，但记入 `rejected_changes` 在下轮 Prompt 告知 LLM |
| 9 | **常量引用** | 统一使用 §A 中定义的常量名，禁止在业务代码中硬编码数值 |
| 10 | **存档原子写入** | 先写 `{label}.tmp`，再 `os.replace` 到目标文件 |

---

*文档持续编写中……*
