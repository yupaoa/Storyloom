# 数据模型与基础设施

> **定位**：GameState 结构、存档系统、可配置常量、全局约定。  
> **配套文档**：
> - [`exec-flow.md`](./exec-flow.md) — 程序执行管线
> - [`block-spec.md`](./block-spec.md) — XML 元素与状态校验
>
>

---

## §1 GameState 初始化

共创阶段 Step 5（大纲校验通过后），初始化内存中的 GameState：

```
game_state = GameState()
game_state.story_config   = story_config           // Step 3 + Step 3.5 解析结果（含 variables）
game_state.state_vars     = init_from_variables(story_config.variables)  // 初始值深拷贝
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

进入叙事循环（见 exec-flow.md §4）
```

---

## §2 节点推进与存档触发

`<checkpoint>` 元素触发（由 exec-flow.md §4.4 响应解析分发至此）。

**流程**：

```
1. 提取 node 属性值：
   ├── node_id → 标记关键节点
   └── "end" → 结局节点：设置 ending_flag = true，其余推进逻辑相同
      （标记 completed、存入摘要和快照、触发存档）。
      后续 bridge 处检测到此标志时走结局路径（见 exec-flow.md §4.7）

2. 验证 node_id 存在于 outline：
   ├── 否 → 记日志，忽略该 checkpoint，继续
   └── 是

3. 标记旧 current_node 为 "completed"

4. 若有 if 条件行：
   逐条评估（按物理顺序，取首个命中）。
   条件中的变量名按优先级解析（choice_dict > state_vars，见 block-spec.md §2）：
     if 条件 -> route <target_node_id>
     ├── 条件命中 → 目标节点 = target_node_id
     ├── 条件中引用的变量不存在 → 该条视为无效，跳过
     ├── 多个命中 → 取第一个
     └── 全部不命中 → 取第一条分支的 target_node_id（兜底）

   若无分支 → 目标节点 = outline 中下一个节点

5. 标记目标节点为 "active"，更新 progress.current_node

6. 存入 checkpoint_summaries（summary 字段）

7. 存储 checkpoint_snapshots[current_node] = deep_copy(state_vars)

8. 触发自动存档 → 覆盖 saves/{label}.json（原子写入，见 §3.3）
```

**兜底策略说明**：分支条件全部不命中 → 取 LLM 列出的第一个分支。这要求 LLM 按优先级排列分支条件。

---

## §3 存档系统

### 3.1 存档文件结构

`saves/` 目录下每个 `.json` 文件代表一次完整游玩。文件名来源于 `story_config.label`（重名追加 `_2`、`_3`）。

核心结构：
```
{
  version: 1,
  metadata: { label, created_at, updated_at, round_count },
  config: { temperature, ... },          // 不存储模型标识，模型以 .env 为准
  story_config: { ..., variables: [...] },
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

### 3.2 自动存档时机

**仅在 checkpoint 到达时触发**（§2 步骤 8）。不设手动存档、不在每轮结束时存档。

| 触发条件 | 行为 |
|----------|------|
| `<checkpoint>` 的 `node` 属性被成功处理 | 覆盖 `saves/{label}.json` |
| 其他时机 | 不存档 |

### 3.3 原子写入

```
1. 序列化 GameState → JSON 字符串（indent=2，确保可读）
2. 确保 SAVE_DIR 存在（不存在则 os.makedirs）
3. 写入临时文件：saves/{label}.tmp
4. os.replace(tmp, saves/{label}.json)   // 原子 rename，跨平台安全
```

> 整个过程不涉及 LLM，仅本地文件操作。

### 3.4 存档加载流程

```
load_save(filepath):
  1. 读取 + JSON 解析
     ├── 解析失败 → 存档损坏（JSON 不合法）

  2. 校验 version 字段存在且 == 1
     ├── 不匹配 → 存档损坏（版本不支持）

  3. 校验关键字段存在：
     story_config (含 variables), state_vars, outline, progress
     ├── 任一缺失 → 存档损坏（结构不完整）

  4. 校验 progress.current_node 指向的 node_id 在 outline 中存在
     ├── 不存在 → 存档损坏（数据不一致）

  5. 校验通过 → 构建 GameState：
     ├── 状态变量值以存档为准（story_config.variables 提供类型定义用于运行时校验）
     ├── outline 节点状态以存档为准
     └── config（temperature 等）以存档为准，模型以 .env 为准

  6. 返回 GameState → 进入叙事循环（见 exec-flow.md §4）

  以上任一校验失败 → 存档损坏（致命），永久失效，提示用户后删除文件并返回主菜单。
```

> **变量自包含**：存档自包含——一次游戏创建后，其变量定义（`story_config.variables`）、大纲结构均以存档为准。运行时校验 state 变更的类型合法性时，以存档内的 `story_config.variables` 为类型定义来源。

### 3.5 存档字段说明

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

> 以下常量集中在 `config.py` 中定义。所有模块引用常量名，不硬编码数值。
> **当前值以 `config.py` 为准**——本文档反映最近一次审计（2026-07-07）时的状态。

### A.1 路径常量

| 常量 | 参考值 | 说明 |
|------|--------|------|
| `SAVE_DIR` | `saves/` | 存档目录（在 `SaveManager` 构造时传入，非 `config.py` 常量） |

### A.2 共创阶段

| 常量 | 参考值 | 说明 |
|------|--------|------|
| `MAX_RETRIES` | 2 | 格式解析/校验失败后的最大重试次数（所有 LLM 调用共用） |
| `STORY_LABEL_MIN_CHARS` | 5 | 故事标签最短字符数 |
| `STORY_LABEL_MAX_CHARS` | 15 | 故事标签最长字符数 |
| `VARIABLE_CAP` | 3 | 变量总数上限（per 2026-07-05 variable-cap spec） |
| `VARIABLE_NUMERIC_CAP` | 2 | number 型变量上限 |
| `VARIABLE_LABEL_CAP` | 1 | string/list 型变量上限 |

### A.3 故事规模档位

> 共创阶段由用户选择或 LLM 判断，写入 `story_config.tier`（`short` / `medium` / `long`）。影响大纲节点数和总轮数推荐。每轮行数和 bridge 位置由 `LINES_PER_ROUND_*` 控制，不随档位变化。

| 常量 | 参考值 | 说明 |
|------|--------|------|
| `OUTLINE_NODE_RANGES` | `{"short": (3,5), "medium": (5,8), "long": (8,15)}` | 各档位大纲节点数范围 |

档位选定后在 Prompt 中注入对应指引。**通过限制轮次来控制总长，而非限制每段字数。**

### A.4 叙事行控制

> **架构说明**：Prompt 输出格式经历了两次迭代——
> 1. 初版：`<seg n="N">` 编号段（`SEGMENTS_PER_ROUND_*`，60-120 段，bridge 40%）
> 2. 2026-07-05 实验优化：`<seg n="N">` 增至 120-200 段，bridge 移至 75%（见 memory `segment-length-ttft-optimization`）
> 3. 行号迁移（`ce5a776`）：改为 `NNN|` 行号前缀格式，`LINES_PER_ROUND_*` 替代 `SEGMENTS_PER_ROUND_*`。每段消耗约 1.25 行（XML tag + 行号前缀），故行数 ≈ 段数 × 1.25 + headroom。

| 常量 | 参考值 | 说明 |
|------|--------|------|
| `LINES_PER_ROUND_MIN` | 150 | 每轮最少行数（含 NNN\| 前缀和 XML 标签） |
| `LINES_PER_ROUND_MAX` | 300 | 每轮最多行数。Prompt 建议上限，LLM 可少于此值 |
| `BRIDGE_POSITION_RATIO` | 0.75 | bridge 前比例（pre-bridge 占总行数比）。75% 经 2026-07-05 实验验证为最优 |
| `MIN_TAIL_LINES` | 25 | bridge 后每个 `<branch>` 最少行数 |
| `LANGUAGE_SEG_LIMITS` | `{"zh-CN": {narration:40, dialogue:50}, "en": {narration:120, dialogue:160}}` | 各语言每段字数上限（注入 Round 1 Prompt） |

### A.5 对话窗口与上下文

| 常量 | 参考值 | 说明 |
|------|--------|------|
| `WINDOW_SIZE` | 3 | 保留的完整历史轮数 |
| `FIRST_COMPRESSION_AT` | 5 | 首次触发压缩的轮次 |
| `MAX_CONTEXT_TOKENS` | 50_000 | 上下文 token 预算上限（目标值，非硬限制） |

### A.6 API 与运行时

| 常量 | 参考值 | 说明 |
|------|--------|------|
| `DEFAULT_MODEL` | `"deepseek-v4-pro"` | 默认模型标识。可通过 `.env` 的 `DEEPSEEK_MODEL` 覆盖 |
| `STREAM_STALL_TIMEOUT_SEC` | 180 | 流式输出停顿超时秒数。当前 context ~50K tokens 时 TTFT 通常 10-30s，180s 提供充足 margin |
| `SAVE_VERSION` | 1 | 存档格式版本号。不匹配则判定存档损坏（当前硬编码在 `save_manager.py`，待提取到 `config.py`） |

### A.7 已废弃常量

> 以下常量在初版 spec 中定义，因架构变更不再使用。

| 常量 | 原值 | 废弃原因 |
|------|------|---------|
| `SEGMENTS_PER_ROUND_MIN` | 60 | 迁移到 `LINES_PER_ROUND_*`（行号格式） |
| `SEGMENTS_PER_ROUND_MAX` | 120 | 迁移到 `LINES_PER_ROUND_*`（行号格式） |
| `BRIDGE_SEGMENT_RATIO` | 0.4 | 重命名为 `BRIDGE_POSITION_RATIO`，值更新为 0.75 |
| `MIN_NARRATION_CHARS` | 200 | 行号格式下每行即一段，字数由 Prompt 端 `LANGUAGE_SEG_LIMITS` 约束 |
| `AUTO_ADVANCE_DELAY_MS` | 500 | 仅 CLI 测试工具使用（控制自动推进间隔）。Web UI 自行管理展示节奏 |

---

## §B 全局约定

> 以下为 Phase 1 全流程的实现规则，与 core principles 互补——原则解释"为什么"，约定定义"怎么做"。

| # | 约定 | 说明 |
|---|------|------|
| 1 | **Prompt 语言** | 所有系统/叙事 LLM Prompt 使用英文。冒险日志 Prompt 使用中文 |
| 2 | **XML 元素名** | 全部英文（`<seg>`、`<checkpoint>` 等） |
| 3 | **变量命名** | 状态变量名、choice 名使用中文 |
| 4 | **XML 转义** | narrative 正文中的 `<` `>` `&` 必须转义为 `&lt;` `&gt;` `&amp;` |
| 5 | **重试策略** | 格式/校验错误最多 `MAX_RETRIES` 次，附带纠正提示重试；API 调用失败**不**自动重试——告知用户，用户决定 |
| 6 | **用户决策** | 重试耗尽、API 失败、内容过短等异常——告知用户具体信息，由用户选择（重试 / 继续 / 返回主菜单） |
| 7 | **错误隔离** | state 逐条校验、options 逐行解析——单条失败不影响同轮其余有效条目 |
| 8 | **静默错误** | 微小校验错误（list 增删不存在元素、number 越界 clamp）不展示给用户，但记入 `rejected_changes` 在下轮 Prompt 告知 LLM |
| 9 | **常量引用** | 统一使用 §A 中定义的常量名，禁止在业务代码中硬编码数值 |
| 10 | **编号宽容** | 叙事段编号偏差（跳号、重复、起始非 1）不触发重试——内容质量优先于编号准确性 |
| 11 | **存档原子写入** | 先写 `{label}.tmp`，再 `os.replace` 到目标文件 |
