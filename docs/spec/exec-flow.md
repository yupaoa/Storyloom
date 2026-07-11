# Phase 1 程序执行流程详解

> **定位**：Phase 1 程序执行管线——从启动到结局的完整流程。  
> **配套文档**：
> - [`block-spec.md`](./block-spec.md) — XML 元素语法、分支路由、状态校验规则
> - [`data-model.md`](./data-model.md) — GameState 结构、存档系统、可配置常量、全局约定
> - [`prompt-design.md`](./prompt-design.md) — Prompt 模板与对话式消息数组设计

---

## §1 总览

### 1.1 术语速查

**共创与大纲**

| 术语 | 含义 | 详见 |
|------|------|------|
| **story_config** | 共创阶段产出的故事设定与变量定义，包含题材、档位、世界观、角色、variables 等字段 | §3.4, §3.5 |
| **大纲** | 由关键节点组成的有向图，描述故事骨架。节点间可有分支 | §3.6 |
| **变量定义 (variables)** | 共创阶段 LLM 自定义的游戏变量列表，每项含名称、类型、初始值 | §3.5 |
| **冒险日志 (adventure_log)** | 结局时独立 LLM 调用生成，不走正常叙事循环 | §5.4 |

**剧情段与路由**

| 术语 | 含义 | 详见 |
|------|------|------|
| **剧情段** | 每轮 LLM 生成的一段叙事文本，为循环基本单位 | §4 |
| **关键节点 (checkpoint)** | 大纲上的里程碑节点。到达时触发进度推进和自动存档 | [data-model.md](./data-model.md) |
| **段内分支** | 同一剧情段内的叙事分支，不影响大纲走向 | [block-spec.md](./block-spec.md) |
| **大纲分支** | 大纲层面的分叉路线，通过 `if -> route` 实现 | [block-spec.md](./block-spec.md) |
| **bridge** | `<bridge/>` 自闭合 XML 元素，标记下一轮 Prompt 组装触发点 | [block-spec.md](./block-spec.md) |
| **bridge_text** | `<bridge/>` 之后至 `</story>` 的纯文本内容，作为下一轮 User Message 中的 bridge_text 字段 | [block-spec.md](./block-spec.md) |
| **XML 元素** | LLM 输出使用 XML 格式，根元素 `<story>`，内含 `<seg>`/`<choice>`/`<set>`/`<checkpoint>`/`<bridge/>`/`<branch>` | [block-spec.md](./block-spec.md) |
| **current_branch** | 当前段内分支名，决定程序匹配哪些命名区块 | [block-spec.md](./block-spec.md) |
| **choice_dict** | 本轮选项结果，key 为 `choice:` 声明值 | [block-spec.md](./block-spec.md) |

**状态与存档**

| 术语 | 含义 | 详见 |
|------|------|------|
| **状态变量 (state_vars)** | 游戏内可变数据，由共创阶段 variables 定义初始化 | [data-model.md](./data-model.md) |
| **GameState** | 程序内存中维护的完整游戏状态 | [data-model.md](./data-model.md) |
| **rejected_changes** | 被校验拒绝的 state 变更条目 | [block-spec.md](./block-spec.md) |
| **checkpoint_summaries** | 累积的 checkpoint 情节摘要列表 | §4.3 |
| **游戏存档** | `saves/` 下的独立 `.json` 文件 | [data-model.md](./data-model.md) |

### 1.2 程序生命周期总览

```
程序启动（加载 .env）
  │
  ▼
主菜单
  ├── [1] 新游戏 → 共创 → init GameState → 叙事循环(N轮) → 结局 → 返回主菜单
  ├── [2] 继续   → 选档 → restore GameState → 叙事循环(N轮) → 结局 → 返回主菜单
  ├── [3] 管理   → 查看/删除存档 → 返回主菜单
  └── [4] 退出   → exit(0)
```

### 1.3 核心原则

> 以下原则贯穿 Phase 1 全部流程。

| 原则 | 说明 |
|------|------|
| **最多一个关键节点** | 同一个剧情段最多只能包含一个关键节点 |
| **本地数据为唯一真相源** | 一切游戏数据以本地 GameState 为准。LLM 只能*建议*变更 |
| **bridge 之后无底层数据变更** | bridge 之后不得出现 state / checkpoint / options 区块 |
| **交互内容前置于 bridge** | 交互和变更区块集中在段前部，bridge 之后为纯叙事缓冲 |
| **超时截断由 LLM 收束** | 程序超时截断时，通知 LLM 快速收束已有内容 |
| **用户体验无缝衔接** | bridge 标记触发提前请求，用户体感不感知段边界 |
| **程序拥有最终控制权** | API 失败、解析错误、内容异常——告知用户并等待决策 |
| **条件变量解析优先级** | `if` 条件中的变量名优先匹配 choice_dict，其次匹配 state_vars |

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
│ 2. 进入主菜单        │
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
    逐个读取存档，校验完整性（见 data-model.md 判定标准）
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
└────────┬────────┘
         ↓
┌─────────────────┐
│ Step 3.5: 生成变量  │ ← 静默（新增）
│ 定义（=== var...）   │
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

**耗时提示**：Step 2 以用户交互为主，Step 3/3.5/4 各需一次 LLM 调用（数秒至十数秒），程序显示等待文案。

### 3.2 Step 1: 用户输入初始想法

```
程序打印：
  "请描述你想玩的故事（如'赛博朋克背景下的爱情故事'）"

用户输入自由文本 → raw_idea
```

无校验——任何非空文本均接受。空输入提示重新输入。

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

> 追问不做轮数上限——由 LLM 判断信息是否足够。

> ⚠️ **追问范围约束（关键）**：LLM 必须聚焦于**世界观、主角设定、故事基调、冲突方向、故事长度**五大维度。故事长度从三档中选择（短篇/中篇/长篇），由用户明确选择或 LLM 根据题材判断。严格禁止涉及具体情节走向或透露后续内容。

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
4. 故事设定不向用户展示（保持新鲜度）
```

> 解析字段定义和 LLM 输出格式见 [`prompt-design.md` §3.2](./prompt-design.md)。

### 3.5 Step 3.5: 生成变量定义

**流程**：

```
1. 程序展示等待文案："正在构筑命运之网……"

2. 发送变量生成 Prompt 给 LLM
   → Prompt 中注入 story_config（LLM 据此设计变量）
   → Prompt 约束：
     - 数值型变量范围统一 [0, 100]
     - 字符串型替代枚举（不设枚举类型，枚举归入 string）
     - 列表型元素为 string
     - ≤3 个变量（≤2 number + ≤1 string/list）
   → LLM 返回 === variables === 格式文本

3. 解析（正则按 === variables === 分割，逐行提取）：
   ├── 解析成功？
   │   └── 否 → 重试（附带格式提示），最多 MAX_RETRIES 次
   │            → 耗尽 → 告知用户，询问：重试 / 返回主菜单
   └── 是
        ▼
4. 校验：
   ┌─────────────────────────────────────────────────────┐
   │ a. 变量名唯一、非空、不含非法字符（\n, :）             │
   │ b. 类型仅限 number / string / list                   │
   │ c. number 初始值在 [0, 100] 范围内                    │
   │ d. string 初始值非空                                  │
   │ e. list 初始值可为空数组 []，元素须为 string            │
   └─────────────────────────────────────────────────────┘
   ├── 校验通过？→ 继续
   └── 校验失败？→ 重试（附带具体错误提示），最多 MAX_RETRIES 次
                   → 耗尽 → 告知用户具体校验失败原因，
                     询问：重试 / 返回主菜单

5. 存储到 story_config.variables = [{name, type, initial}] 列表
```

> 输出格式和完整示例见 [`prompt-design.md` §3.3](./prompt-design.md)。校验失败处理：拒绝 → 重试（附带错误提示），最多 MAX_RETRIES 次。

### 3.6 Step 4: 生成大纲树

**流程**：

```
1. 程序展示等待文案："正在绘制故事脉络……"

2. 发送大纲生成 Prompt 给 LLM
   → Prompt 中注入 story_config（含 variables）
   → Prompt 中注入可用变量名列表（来自 Step 3.5 variables）
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
   │ b. 分支条件引用的变量是否存在于 Step 3.5 variables？     │
   │    （不存在仅记日志警告，不强制拒绝）                    │
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

> 输出格式和完整示例见 [`prompt-design.md` §3.4](./prompt-design.md)。

### 3.7 Step 5: 初始化 GameState

> GameState 完整结构定义见 [`data-model.md`](./data-model.md)。

变量校验通过后，从 `story_config.variables` 初始化 `state_vars`（初始值深拷贝）。

初始化后进入叙事循环（§4）。

---

## §4 叙事循环

### 4.1 单轮总览

> **引擎视角**：以下 6 阶段描述引擎侧每轮的工作内容。内容展示和玩家交互是 **UI 层**职责（§4.5-4.6），引擎通过事件流（`segment` / `options` / `state` / `error` / `done` / `ending`）向 UI 提供数据，不直接控制展示节奏。

```
Round N 开始
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ 1. TTFT 等待                                          │
│   UI 展示上一轮 bridge_text（首轮无）；引擎等待 API     │
│   返回第一个 token。TTFT 通常 10-30s。                 │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│ 2. <story> 开始                                       │
│   StreamingXmlParser 收到 <story> 标签——解析生命周期   │
│   正式入口。触发 STORY_BEGIN 事件。                     │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│ 3. 流式解析（§4.4）                                    │
│   逐行 XML 解析，与 LLM 生成流几乎同步：                 │
│   • Pre-bridge：正常处理 seg/choice/set/checkpoint     │
│   • 遇到 choice 点：yield options 给 UI，等待玩家输入    │
│   • segment 文本实时以事件形式发给 UI                    │
│   • UI 层使用队列缓冲——非阻塞接收，按自身节奏展示         │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│ 4. <bridge/> — 模式切换（非时序触发器）                  │
│   • 解析器切到 post_bridge 模式（_post_bridge = True）  │
│   • 后续内容快速解析（纯叙事，无 UI 反馈等待）            │
│   • post-bridge 违规元素记入 _format_errors，不传给 UI   │
│   • bridge_text 按分支归属累积（§4.7）                   │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│ 5. </story> — 解析完成，打包 + 发送（§4.7）             │
│   • get_result() → ParsedOutput                       │
│   • add_round() → ContextManager                      │
│   • 应用无条件 set（block-spec.md §5）                   │
│   • 节点推进与存档（data-model.md §2）                   │
│   • 自动推进 + 非结局：组装下轮 Prompt → 后台 API 调用    │
│   • 结局：组装冒险日志 Prompt → 后台 LLM 调用（§5）      │
│   • 触发 STORY_END 事件                                │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│ 6. 错误处理（两级）                                     │
│   • 严重（API 失败 / 解析失败）：通知 UI → 用户决策       │
│     （重试 / 用当前内容继续 / 返回主菜单）                │
│   • 普通（格式错误 / 状态拒绝）：程序内部处理，下轮        │
│     Prompt 反馈（format_error / rejected_changes）      │
└──────────────────────────────────────────────────────┘
```

> **职责边界**：阶段 1-5 是引擎职责（数据产出），阶段 6 是错误分类策略。UI 层（§4.5-4.6）独立消费引擎产出的事件流——内容展示速度、选项面板渲染、自动/手动模式切换均为 UI 层决策，引擎不感知。
>
> LLM 响应使用 `StreamingXmlParser` 逐行流式解析（见 §4.4）。流式解析的必要性见 §4.3。XML 元素语法、分支路由、状态校验的完整规则见 [`block-spec.md`](./block-spec.md)。节点推进与存档见 [`data-model.md`](./data-model.md)。

### 4.1.1 错误严重等级分类

引擎侧对所有异常采用两级分类，决定处置策略和 UI 通知方式：

| 等级 | 范畴 | 处理策略 | UI 行为 | 示例 |
|------|------|---------|---------|------|
| **严重** | 影响本轮可用性的致命故障 | 停止当前处理，通知 UI，**由用户决策** | 展示错误信息，等待用户选择（重试 / 继续 / 返回） | API 网络错误、响应完全无法解析、TTFT 超时且内容不足 |
| **普通** | 不影响本轮展示的可恢复问题 | **程序内部处理**，不在当前轮打断用户体验 | 不展示给用户，仅在下一轮 Prompt 中反馈 | 格式错误（post-bridge 违规元素）、状态变更被拒绝、行号偏差 |

**严重错误的用户决策路径**：

```
API 错误 / 解析失败
    → 通知 UI 具体错误信息
    → 用户选择：
      ├── 重试：重新发送相同 Prompt
      ├── 用当前内容继续：取已接收的部分内容展示（仅流式截断场景）
      └── 返回主菜单：放弃本轮，回到主菜单
```

> **关键原则**：API 调用失败**不自动重试**——始终由用户决策。程序只提供信息和选项，不做自动恢复。这与 data-model.md §B 约定 #6 一致。
>
> **实现**：严重错误通过 generator 的 `yield {"type": "error", "message": str}` 传递给 UI 层。普通错误在引擎内部处理——格式错误记入 `_format_error`，状态拒绝记入 `_rejected_changes`——均在下一轮 `build_round_n()` 时注入 Prompt。

### 4.2 每轮 Prompt 的组成

采用**对话式消息数组架构**，由 `ContextManager` 管理。每轮发送给 LLM 的 requests 格式为 messages 数组：

```
messages = [
  {role: "user",      content: Round1_完整Prompt},      // 永久锚定，不压缩不删除
  {role: "assistant", content: Round1_XML输出},          // 永久锚定，作为格式 few-shot 范例
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

#### Round 1（永久锚定）

由 `PromptBuilder.build_round1()` 构建，内容：

- 角色定义 + XML 输出格式规范（元素结构 + 完整格式示例 + 核心规则）
- 质量要求
- 故事上下文（背景、主角、风格、冲突、角色、大纲、当前状态变量）

`ContextManager.set_round1(user, assistant)` 存储 Round 1 消息对。Round 1 永不压缩、永不删除。

#### Round N 上下文（N ≥ 2）

由 `PromptBuilder.build_round_n()` 构建，作为自然消息追加在对话末尾。不含角色定义、格式规范、故事上下文：

| 内容 | 来源 |
|------|------|
| 当前节点 ID 与目标 | `outline` 进度 |
| 已完成节点列表 | `progress` |
| 压缩摘要（滑出窗口轮次） | `ContextManager` 的压缩列表 |
| 当前状态快照 | `state_vars` |
| 被拒变更反馈 | `rejected_changes`（仅当非空） |
| 格式错误纠正 | `format_error`（仅当存在） |
| 上一轮结尾 | `bridge_text`（从上一轮 assistant XML 输出中提取） |

> 完整的 Prompt 模板与示例见 [`prompt-design.md`](./prompt-design.md) §4.2-4.4。

### 4.3 API 调用与响应接收

**流式接收与 bridge 时序**：

bridge 机制依赖流式 API（`stream=True`）。当程序解析到 `<bridge/>` 时，对于无选项（auto-advance）的轮次，立即通过 **bridge pre-fetch** 在后台线程发起下一轮 API 调用 — 同时继续展示 post-bridge 段落（bridge_text）。后台响应在 bridge_text 展示期间到达并缓冲，用户体感上无段边界停顿。

这意味着 bridge 机制的真正时限不是 LLM 总生成时间，而是后台 API 调用的 TTFT + 生成时间 vs. bridge_text 的展示时长。

> **流式解析要求**：所有轮次使用 `StreamingXmlParser` 逐行解析。全量 `ElementTree` 解析要求全部行生成完毕才能展示首段（TTFT + 生成 ≈ 35-80s），流式解析仅需首行（TTFT + 首行 ≈ 10-30s）。bridge_text 阅读时间（10-20s）可覆盖 TTFT 但不可覆盖完整生成——全量解析在 pre-fetch 路径下必然导致空白等待。

> **关键**：TTFT 主要受 Prompt 大小（输入 tokens 数）影响，而非输出长度。精简 System Prompt 可显著缩短 TTFT。
>
> **实现**：bridge pre-fetch 在 `GameLoop._launch_prefetch()` 中实现 — daemon 线程通过 `queue.Queue` 流式传输 API chunks。仅对无选项轮次触发（choice 轮次无法预计算下一轮的 messages 数组）。详见 `game_loop.py`。

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

**三层时序模型**：

bridge pre-fetch 的时序依赖三个独立流的速率关系：

```
LLM 生成流（token 产出）
    ≥
程序解析流（StreamingXmlParser 逐行解析）
    ≥
UI 展示流（用户阅读 / 自动推进）
```

| 流 | 负责层 | 说明 |
|------|---------|------|
| LLM 生成流 | API 服务端 | token 逐块产出，TTFT 10-30s + 生成 25-50s |
| 程序解析流 | 引擎（`game_loop.py`） | 逐行流式解析，与生成流几乎同步（生成即解析） |
| UI 展示流 | UI 层（CLI / Web） | 消费引擎产出的事件，按自身节奏展示 |

**流间同步规则**：

- **生成→解析**：几乎同步。token 到达后立即经 `LineBuffer`→`StreamingXmlParser.feed_line()` 产出事件。
- **解析→展示**：通常同步（每段解析后立即 yield 给 UI）。**例外**：选择点处解析流暂停等待 UI 反馈（玩家输入），之后继续快速解析。
- **bridge→`</story>` 区间**：解析流**不需要等待 UI 反馈**——post-bridge 仅含纯叙事（`<seg>`/`<branch>`），无交互元素。解析此区间极快（微秒级）。

> **关键洞察**：程序解析到 `<bridge/>` 时，LLM 生成流通常已完成 post-bridge 内容的产出（生成流领先于解析流）。因此 bridge→`</story>`→pre-fetch 启动这一路径在引擎侧是**几乎不间断的同步执行**。引擎在 `</story>`（解析完成）处立即组装 Prompt 并启动后台 API 调用。

> **UI 队列缓冲建议**：UI 层应使用队列缓冲接收引擎产出的事件——一侧持续接收（非阻塞），一侧按自身节奏展示（固定间隔 / 用户确认）。这样引擎的 bridge→`</story>`→pre-fetch 路径不会被 UI 展示延迟阻塞。

### 4.4 响应解析

利用 `NNN| ` 行号前缀使每行成为自包含的 XML 片段，逐行正则匹配产出事件，不等完整文档。

```
1. 预处理：剥离 NNN| 前缀 → 跳过空行和注释

2. 逐行正则匹配 → ParseEvent：
   <seg>text</seg>           → SEGMENT(text)
   <choice id="X">           → CHOICE_BEGIN(id)
   <opt key="1" branch="X">  → OPT(key, branch, text)
   </choice>                 → CHOICE_END
   <set var="X" op="+" .../> → SET(var, op, val, if)
   <checkpoint node="X" ...> → CHECKPOINT(node, summary)
   <route if="X" target="Y"/>→ ROUTE(if, target)
   <bridge/>                 → BRIDGE（触发 pre-fetch）
   <branch name="X">         → BRANCH_ENTER(name)
   </branch>                 → BRANCH_EXIT
   <story> / </story>        → STORY_BEGIN / STORY_END

3. 解析过程中同步累积结构化数据 → get_result() 返回 ParsedOutput
```

> **各元素语法**：见 [`block-spec.md`](./block-spec.md) §4。

### 4.5 内容展示

**展示模式**：支持自动和手动两种，用户可随时切换。

| 模式 | 行为 | 切换键 |
|------|------|--------|
| **自动**（默认） | 每段之间延迟 AUTO_ADVANCE_DELAY_MS 后自动继续 | 按 `M` 切换至手动 |
| **手动** | 每段展示后等待用户按任意键继续 | 按 `M` 切换回自动 |

**展示流程**：

```
1. 从展示队列取匹配 current_branch 的 narrative 正文
2. 按数字编号分割为展示段（见 block-spec.md §2）
3. 剥离编号前缀，逐段展示纯文本：
   ├── 自动模式：打印段文本 → delay(AUTO_ADVANCE_DELAY_MS) → 继续下一段
   └── 手动模式：打印段文本 → 等待按键 → 继续下一段

4. narrative 展示完毕后：
   ├── 有 <choice>？→ 展示选项面板（§4.6）
   └── 无 → 展示 bridge_text → 自动进入下一轮
```

**bridge_text 展示**：`<bridge/>` 之后的 `<seg>` 和 `<branch>` 内的 `<seg>` 按元素边界分割展示。用户无感知——体感上是连续叙事。

**命名 narrative 展示**：遍历时仅 `current_branch` 匹配的 narrative 进入展示队列。

> **UI 队列缓冲模式（推荐）**：引擎通过 generator 逐段 yield 事件给 UI 层。为避免引擎的 bridge→`</story>`→pre-fetch 路径被 UI 展示延迟阻塞，UI 层应使用队列缓冲：
> - **接收侧**：非阻塞地从 generator 取出事件，立即放入内部队列（`collections.deque`）
> - **展示侧**：按自身节奏从队列取出并展示（固定间隔 / 用户确认）
> - 这样引擎的 post-bridge 解析和 pre-fetch 启动不会因 UI 展示而暂停，实现真正的"解析完成即发送"。

### 4.6 玩家交互

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
  有 opt 的 if 属性？
  ├── 否 → enabled
  └── 是 → 用本地 state_vars 评估条件
      ├── 满足 → enabled
      └── 不满足 → disabled（dim 颜色 + 显示当前值）

全部 disabled？
  → 全部以 enabled 样式展示，移除条件标注（兜底防卡死）
```

**无选项时的自动推进**：`<choice>` 元素缺失 → 正文展示完毕后自动进入下一轮，不等待输入。

### 4.7 下一轮准备与结局检测

`<bridge/>` 元素具有**双重角色**：

**对 LLM 的结构约束**（主要方面）：
- 标记交互区与叙事区的硬分界——bridge 之后严格禁止 `<choice>`、`<set>`、`<checkpoint>`
- 强制 LLM 在交互断点之前完成所有状态变更和路由声明
- Post-bridge 仅提供叙事缓冲（`<seg>`、`<branch>`），为下一轮 Prompt 组装争取时间

**对程序的行为切换**（桥接解析阶段）：
- **模式切换**：解析器从"交互+叙事"模式切换到"纯叙事"模式（`_post_bridge = True`）
- **快速解析**：Post-bridge 区间无交互元素，不需要等待 UI 反馈，全速解析
- **错误捕获**：Post-bridge 区间出现的 `<choice>`/`<set>`/`<checkpoint>` 记入 `_format_errors`，不传递给 UI
- **bridge_text 捕获**：Post-bridge 的 `<seg>` 文本按 `current_branch` 过滤后存储，注入下一轮 Prompt

**Prompt 组装与 Pre-fetch 触发**：

程序的实际触发点是**解析完成**（`</story>`），而非 `<bridge/>` 本身。但 bridge→`</story>` 区间解析极快（纯叙事、无 UI 阻塞），两者可视为几乎同时：

```
解析到 <bridge/>
    │  ← 模式切换（微秒级）
    │  ← 快速解析 post-bridge 内容（微秒级，无 UI 反馈等待）
    ▼
解析到 </story>（解析完成）
    │
    ├── ending_flag == true？
    │   └── 是 → 组装冒险日志 Prompt（§5.4）→ 发 LLM → 继续展示 bridge_text
    │           → bridge_text 展示完毕 + 响应就绪 → 展示 adventure_log → 返回主菜单
    │
    └── 否 → 正常准备：
        1. bridge_text 提取（见 block-spec.md §4 `<bridge/>` 节）
        2. round_count += 1
        3. 组装下一轮 Prompt → 启动后台 API 调用 → Round N+1
```

> `ending_flag` 由 checkpoint 处理为 `end` 时设置（见 data-model.md）。
>
> **时序说明**：此处"解析完成"指引擎侧流式接收完毕、`StreamingXmlParser.get_result()` 返回的时刻。Prompt 组装和后台 API 调用在此刻立即执行（不间断同步代码块），与 UI 展示 post-bridge 段落并发进行。

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
  <story>
  <seg>（结局叙事段落……）</seg>
  <checkpoint node="end" summary="所有线索在此交汇……"/>
  <bridge/>
  <seg>（最后的衔接文本——缓冲用，保持与正常剧情段一致的结构）</seg>
  </story>

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

> **关键**：bridge 放在 checkpoint `end` 之后、尾部 narrative 之前。程序在 bridge 处检测到 ending_flag，提交冒险日志请求。尾部 narrative 作为缓冲。

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

### 5.4 冒险日志 Prompt

**触发时机**：checkpoint `end` 轮 bridge 处 / Q 键确认后。

**程序行为**：
```
prompt = build_adventure_log_prompt(story_config, state_vars, checkpoint_summaries, checkpoint_history)
response = api_client.call(prompt)   // 非流式，快速生成
展示 response 正文
```

> 冒险日志为独立 LLM 调用——不走正常叙事循环的解析管线。Prompt 模板与示例见 [`prompt-design.md` §5](./prompt-design.md)。
