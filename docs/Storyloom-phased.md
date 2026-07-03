# Storyloom: AI 交互式文字小说游戏引擎（分阶段实施）

> **权威执行文档**：[`Phase1-exec-flow.md`](./Phase1-exec-flow.md)  
> 程序执行逻辑、术语定义、常量参考等以该文档为准。本文档与其冲突时以 exec-flow 为准。  
> **本文档定位**：补充材料——Prompt 模板、状态模板定义、技术栈、实现路线图，以及 Phase 2/3 远期规划。

---

## 项目总览

**一句话定位**：以 LLM 为叙事大脑、程序为流程管理器的 AI 交互式文字冒险游戏引擎。

```
Phase 1 ──── CLI 纯文本 MVP ──── 单模型、硬编码状态、规范自然语言输出 ──── 🎯 当前
Phase 2 ──── Web UI + 动态系统 ── 动态状态、向量记忆、多模型
Phase 3 ──── 完整体验 ────────── 图像生成、云同步、TTS、导出
```

---

## Phase 1: 纯文本单模型 MVP

### 1.1 范围定义

**Phase 1 是什么**：
- 终端 CLI 文字冒险游戏，用户通过键盘选择选项推进故事
- 使用单一 OpenAI 兼容 API（一个 key 覆盖所有 LLM 调用）
- 三套硬编码状态模板（恋爱/冒险/悬疑），用户选题材即载入
- 大纲树 + 剧情段：大纲为有向图，每轮 LLM 生成一个"剧情段"
- 极简上下文：大纲树 + 进度 + 状态快照 + checkpoint 摘要 + bridge_text，不做对话历史累积
- 多文件自动存档：到达 checkpoint 时覆盖保存

**Phase 1 不是什么**：
- ❌ 没有图像生成、Web 界面、向量数据库
- ❌ 没有多模型调度（叙事、追问、大纲生成用同一模型）
- ❌ 没有自定义文本输入（仅固定选项，留到 Phase 2）
- ❌ 不做主动 token 计数与预算控制
- ❌ 不做对话轮次历史累积

### 1.2 技术选型

| 层面 | 选择 | 说明 |
|------|------|------|
| 语言 | Python 3.10+ | 标准库丰富，生态成熟 |
| LLM SDK | `openai` (Python) | 兼容 OpenAI / 本地 llama.cpp / 多数代理 |
| 终端 UI | `rich` | Markdown 渲染、Panel 布局、逐段展示控制 |
| 数据存储 | JSON 文件 | 存档即单个 `.json`，可读可调试 |
| 文本解析 | `re`（正则） | 按 `--- 区块名 ---` 分隔符提取 |
| 配置管理 | `.env` + `python-dotenv` | API key 不进仓库 |

**依赖** (`requirements.txt`)：
```
openai>=1.0.0
rich>=13.0.0
python-dotenv>=1.0.0
```

**配置** (`.env`)：
```
STORYLOOM_API_KEY=sk-xxx
STORYLOOM_API_BASE=https://api.openai.com/v1
STORYLOOM_MODEL=gpt-4o
```

### 1.3 核心架构

单进程事件驱动，模块划分：

```
用户输入 → UI (rich) → GameLoop → PromptBuilder → APIClient (stream) → Parser → GameState → 循环
```

| 模块 | 职责 |
|------|------|
| `main.py` | 入口：主菜单、新建/继续 |
| `config.py` | 读取 `.env`，管理模型参数与可配置常量 |
| `api_client.py` | 封装 OpenAI SDK，流式输出 + 超时截断 |
| `game_state.py` | GameState 数据模型 + 多槽存档读写 + checkpoint 快照 |
| `prompt_builder.py` | 组装各阶段 System/User Prompt |
| `parser.py` | 解析 LLM 输出的 `--- 区块 ---` 格式 |
| `game_loop.py` | 共创阶段 + 叙事循环 + 结局处理 |
| `ui.py` | `rich` 终端界面：逐段展示正文、选项面板（含置灰）、状态显示 |

### 1.4 状态模板定义

文件 `templates/states.json`，三套硬编码模板。程序在共创阶段解析出题材后载入。

**模板 A：恋爱**
```json
{
  "genre": "romance",
  "label": "恋爱",
  "vars": {
    "好感度": {"value": 0, "type": "int", "min": -100, "max": 100},
    "信任度": {"value": 0, "type": "int", "min": 0, "max": 100},
    "当前情绪": {"value": "平静", "type": "enum", "options": ["平静", "喜悦", "悲伤", "愤怒", "紧张"]},
    "关系阶段": {"value": "初识", "type": "enum", "options": ["初识", "朋友", "暧昧", "恋人", "疏远"]}
  }
}
```

**模板 B：冒险**
```json
{
  "genre": "adventure",
  "label": "冒险",
  "vars": {
    "体力": {"value": 100, "type": "int", "min": 0, "max": 100},
    "金币": {"value": 500, "type": "int", "min": 0, "max": 999999},
    "声望": {"value": 0, "type": "int", "min": -100, "max": 100},
    "背包": {"value": [], "type": "list"},
    "队伍": {"value": [], "type": "list"}
  }
}
```

**模板 C：悬疑**
```json
{
  "genre": "mystery",
  "label": "悬疑",
  "vars": {
    "理智值": {"value": 100, "type": "int", "min": 0, "max": 100},
    "线索": {"value": [], "type": "list"},
    "时间进度": {"value": "第1天 上午", "type": "string"},
    "嫌疑度": {"value": 0, "type": "int", "min": 0, "max": 100}
  }
}
```

### 1.5 Prompt 模板

> 所有 Prompt 使用中文。区块名全部英文。`{...}` 为程序填充的占位符。

---

#### A. 叙事循环 System Prompt

```
你是一个交互式文字冒险游戏的叙事引擎。你必须严格按照以下规则运作：

## 故事背景
- 题材：{genre_label}
- 档位：{tier}（目标每段 {tier_words} 字，{tier_options} 个选项）
- 世界观：{world_setting}
- 主角：{protagonist_name}，{protagonist_role}，{protagonist_trait}
- 叙事风格：{tone}
- 核心冲突：{central_conflict}

## 大纲树
{outline_text}

## 剧情进度
当前章节：{current_node_title}（{current_node_id}）
章节目标：{current_node_goal}
已完成章节：{completed_nodes_summary}

## 已发生的重要事件
{checkpoint_summaries_text}

## 当前状态
{state_summary}

## 上一轮被拒绝的状态变更（如有）
{rejected_changes_feedback}

## 输出格式要求
你必须严格按照以下格式回复。每个区块以 "--- 区块名 ---" 开头，可附带分支名。
不要在格式区块之外输出任何内容。正文中禁止出现单独成行的 "---"。

### 可用区块：

--- narrative ---
（必选）故事叙述正文。支持分支名：--- narrative:main ---、--- narrative:took_chip --- 等。
自然段之间用空行分隔。叙事必须与当前状态数值自然结合。

--- options ---
（可选）选项列表。支持分支名。第一行声明 choice：
choice: 选择名
1. 选项描述 -> branch_name
2. 选项描述 @if: 变量>=值 -> branch_name
（提供 0-4 个选项。@if: 条件不满足时置灰。-> branch 切换段内分支。）

--- state ---
（可选）状态变更 + 段内路由。支持分支名：
@var 变量名 +10
@var 变量名 =新值
if 条件 -> @var 变量 操作, @branch 分支名
（条件运算符：== >= <= > < has。可组合 and / or，最多一次。
 @branch 切换段内分支。条件中变量名优先匹配 choice_dict，其次 state_vars。）

--- checkpoint ---
（仅在到达大纲关键节点时出现。固定 main，不支持分支名）：
node ch2_discovery
if 信任度 >= 50 -> route ch3_ally
if 信任度 < 50 -> route ch3_betrayal
summary: 从上一checkpoint到当前节点的情节概述（必填）
（结局节点使用 end 替代 node <id>。if 条件最多一个 and 或 or。）

--- bridge ---
（通常必选，结局轮除外）标记下一轮 Prompt 组装的触发点。
bridge 之后只能出现 --- narrative:xxx ---，不得出现 state/checkpoint/options。
程序提取匹配 current_branch 的 narrative 作为下轮 User Message。

--- adventure_log ---
（仅结局时出现）面向玩家的冒险回顾，纯文本。由独立 Prompt 生成，不嵌入剧情段。

## 完整格式示例

--- narrative:main ---
夜幕降临，新东京的霓虹灯在雨雾中晕开一片迷离的光。

你推开地下酒吧的门，潮湿的空气混杂着合成酒精和烧焦电路的气味扑面而来。
吧台深处，一个戴着全息面具的人朝你招了招手。他的手中捏着一枚闪着幽蓝光芒的芯片。

"这就是你要的东西。"

--- options:main ---
choice: chip_choice
1. 接过芯片 -> took_chip
2. 暂时离开 @if: 理智值 >= 50 -> left
3. 先发制人 -> attack

--- state:main ---
@var 理智值 -5
if chip_choice == 1 -> @var 线索 +神秘芯片, @branch took_chip
if chip_choice == 2 -> @branch left
if chip_choice == 3 -> @var 嫌疑度 +10, @branch attack

--- narrative:took_chip ---
冰凉的金属触感从指尖传来，一道微弱的电流让你打了个激灵。
芯片上的数据开始自动解码，全息面具人的嘴角扬起一丝难以察觉的弧度。

--- narrative:left ---
你推开椅子起身。"我需要时间考虑。"身后传来芯片在桌面上旋转的细微声响。

--- narrative:attack ---
你猛地伸手按住芯片，反手将他的手腕压在吧台上。
"先告诉我，AIKO在哪？"酒吧里的音乐戛然而止。

--- checkpoint ---
node ch2_discovery
if 信任度 >= 50 -> route ch3_ally
if 信任度 < 50 -> route ch3_betrayal
summary: 在酒吧从神秘委托人处获得加密芯片，得知AIKO的真实身份是觉醒的AI。

--- bridge ---

--- narrative:main ---
你站在地下酒吧的门口，雨还在下。芯片在口袋里微微发烫，像是在提醒你——
从这一刻起，一切都将不同。

## 核心规则
1. --- narrative --- 必须存在。正文中不要出现单独成行的 "---"
2. 叙事和选项必须与当前状态数值自然结合
3. --- state --- 仅在状态确实变化时出现。注意类型匹配操作符
4. --- checkpoint --- 仅在到达大纲关键节点或结局时出现，summary 必填
5. bridge 之前完成所有交互/变更区块；bridge 之后仅 narrative
6. 同一剧情段最多一个 checkpoint；checkpoint 含多分支时，bridge 后可含多个命名 narrative 对应各分支承接文本
7. 不要在格式区块之外输出任何内容
```

---

#### B. 共创阶段：追问 Prompt

```
你正在帮助玩家创建一个文字冒险游戏的故事设定。

玩家说："{user_input}"

请针对这个想法提出关键问题，帮助完善故事设定。你需要聚焦于以下方面：
- 世界观的具体设定（时代、地点、社会背景）
- 主角的性格与背景
- 故事的基调与风格
- 主要冲突方向
- 故事长度（短篇/中篇/长篇）

规则：
1. 不要直接给出建议，以提问方式引导玩家思考
2. 每个问题可附带 2-3 个参考选项供玩家选择
3. 不要透露具体情节走向，保持内容新鲜度
4. 不要过度追问细节——聚焦于世界观、主角、基调、冲突方向、故事长度即可
5. 如果用户最初的想法已经暗示了题材类型，在第一次互动中确认；
   否则第一个问题就是"你想玩什么类型？目前可选：恋爱 / 冒险 / 悬疑"
6. 故事长度从短篇/中篇/长篇中选择，由用户明确选择或你根据题材判断
7. 如果你认为信息已经足够生成故事设定和大纲，在回复末尾明确询问玩家：
   "我认为信息已经足够，是否开始生成故事？你也可以继续补充。"
8. 如果玩家在任何时候说"开始"或类似词语，停止追问

对话历史：
{co_creation_history}
```

---

#### C. 共创阶段：生成故事设定

```
根据以下讨论内容，生成结构化的故事设定。

讨论记录：
{co_creation_history}

请严格按照以下格式输出（不要输出任何格式之外的内容）。
题材必须从以下三个中选择一个：romance（恋爱）、adventure（冒险）、mystery（悬疑）。
档位从以下选择：short（短篇）、medium（中篇）、long（长篇）。

=== story_config ===
题材：romance
档位：medium
标签：（5-15字简短命名，用于存档文件名和列表展示）
世界观：（一句话世界观描述）
主角姓名：（角色名）
主角身份：（角色定位）
主角特质：（性格与特征描述）
叙事风格：（叙事风格描述）
核心冲突：（核心冲突一句话描述）
主要角色：
  - 角色名 | 角色定位 | 与主角关系
  - （可多行，至少1个）

注意：
- "题材"字段只能写 romance / adventure / mystery 中的一个英文单词
- "档位"字段只能写 short / medium / long 中的一个英文单词
- "主要角色"每行格式：两个空格 + 短横 + 空格 + 角色名 + 空格 + | + 空格 + 角色定位 + 空格 + | + 空格 + 与主角关系
```

---

#### D. 共创阶段：生成大纲树

```
根据以下故事设定，生成大纲树（节点有向图）。

故事设定：
{story_config_text}

可用状态变量（你可以在分支条件中引用这些变量）：
{state_vars_list}

请严格按照以下格式输出（不要输出任何格式之外的内容）：

=== outline ===
节点1：章节标题 | ch1_xxx
  目标：本章叙事目标（给AI看的内部指引，不透露给玩家）
  分支：无

节点2：章节标题 | ch2_xxx
  目标：本章目标
  分支说明：（可选）分支方向的人类可读描述
  分支：变量名 运算符 值 → 目标node_id
  分支：变量名 运算符 值 → 目标node_id
（若只有一个后续节点则写"分支：无"；若有分支则列出所有分支条件）

规则：
1. 总节点数控制在 5-8 个（短篇可更少）
2. 每个节点最多 2 个分支
3. 最后一个节点必须写"分支：无"（即结局节点，branches 为空）
4. 分支条件尽可能引用上面列出的可用状态变量
5. 若当前阶段无法确定具体条件，可写"分支说明"作为方向指引，
   具体条件留到运行时由叙事 LLM 在 --- checkpoint --- 中补充
6. 节点标题隐晦，不要剧透关键情节
7. node_id 使用 ch序号_英文缩写 格式（如 ch1_intro、ch2_discovery）
8. 分支条件的目标 node_id 必须是大纲中存在的节点
```

---

#### E. 结局冒险日志 Prompt

```
游戏已到达结局。请根据以下信息生成冒险日志。

## 故事设定
{story_config_text}

## 最终状态
{state_summary}

## 已发生的重要事件
{checkpoint_summaries_text}

## 关键节点回顾
{checkpoint_history_text}

请按以下格式输出：

--- adventure_log ---
（包含以下内容，纯文本，面向玩家）：

## 章节回顾
（每个章节的简短摘要——请基于上方"已发生的重要事件"撰写）

## 关键抉择
（玩家在重要节点做出的选择及其影响）

## 结局评语
（对本段冒险旅程的整体评价和感悟）
```

---

### 1.6 选项条件运算符

> 条件语法详见 [`Phase1-exec-flow.md`](./Phase1-exec-flow.md) §4.2.3。以下为运算符与类型映射。

| 运算符 | 适用类型 | 含义 | 示例 |
|--------|---------|------|------|
| `>=` | int | 大于等于 | `@if: 好感度>=30` |
| `<=` | int | 小于等于 | `@if: 嫌疑度<=50` |
| `>` | int | 大于 | `@if: 金币>100` |
| `<` | int | 小于 | `@if: 体力<30` |
| `==` | int, enum, string | 等于 | `@if: 关系阶段==恋人` |
| `has` | list | 列表包含 | `@if: 线索 has 神秘芯片` |

组合：`and` / `or`，每条条件最多使用一次。Phase 1 不支持 `!=`、括号嵌套。

### 1.7 建议文件结构

```
storyloom/
├── main.py                 # 入口：主菜单调度
├── config.py               # 环境变量、模型参数、常量、模板加载
├── api_client.py           # OpenAI SDK 封装 + 流式调用 + 超时截断
├── game_state.py           # GameState 数据类 + 存档读写 + checkpoint 快照
├── prompt_builder.py       # 各阶段 Prompt 组装
├── parser.py               # 按 --- 区块 --- 分隔符解析 LLM 响应
├── game_loop.py            # 共创阶段 + 叙事循环 + 结局处理
├── ui.py                   # rich 终端界面：逐段展示、选项面板、状态显示
├── templates/
│   └── states.json         # 三套硬编码状态模板
├── saves/                  # 存档目录（gitignore）
├── .env.example            # 配置模板
├── requirements.txt        # Python 依赖
└── README.md               # 快速开始指南
```

### 1.8 实现路线图

| 步序 | 内容 | 产出 | 可验证 |
|------|------|------|--------|
| 1 | **项目骨架** | `main.py` + `config.py` + `.env` + `templates/states.json` | 启动打印配置和可用模板 |
| 2 | **API 客户端** | `api_client.py`：流式调用 + 超时截断 | 发一条消息，流式打印，模拟超时截断 |
| 3 | **状态模型** | `game_state.py` + 状态校验 + 存档读写 | 创建 GameState → 修改 → 存档 → 读档 → 验证 |
| 4 | **文本解析器** | `parser.py`：按 `--- 区块 ---` 分割 + 各区块提取 | 模拟 LLM 响应测试边界情况 |
| 5 | **Prompt 构建** | `prompt_builder.py`：5 类 Prompt 模板 | 打印组装后的 Prompt，检查占位符 |
| 6 | **共创阶段** | `game_loop.py` 共创部分 + `ui.py` 基础组件 | 跑通"输入→追问→设定→大纲"完整流程 |
| 7 | **叙事循环** | `game_loop.py` 叙事部分 + 选项面板 + 状态变更 | 完整跑通一局游戏 |
| 8 | **结局 & 冒险日志** | 结局处理 + 冒险日志生成 + 展示 | 触发结局 → 冒险日志 → 返回主菜单 |

---

## Phase 2: 动态系统与增强交互

> Phase 1 稳定后逐步引入。

### 2.1 动态状态定义
- 移除硬编码模板，共创阶段由 LLM 根据题材自动生成状态变量
- 变量定义格式与 Phase 1 相同，生成方从预设文件变为 LLM 输出
- 需增加校验步骤：变量名不重复、类型合法等

### 2.2 Web 界面
- **FastAPI + SSE** 替换 CLI
- 前端轻量 HTML/JS：打字机效果流式渲染、选项按钮、侧边栏（状态+日志+设置）、移动端适配
- Phase 1 的 `game_loop.py` 核心逻辑保留，只替换 `ui.py`

### 2.3 向量记忆
- 引入 `sentence-transformers` 或 API embedding
- 角色、地点、道具、关键事件 embed 后存 SQLite + `sqlite-vec`
- 每轮检索最相关条目拼入 Prompt，作为上下文增强

### 2.4 多模型支持
- 抽象 LLM 接口层，支持为不同任务配置不同模型
- 叙事：主力模型（高创意）；审查/追问：便宜模型（低成本）

### 2.5 自定义输入
- 实装自定义输入管线：合理性检查模型判断玩家输入是否越界
- 合理输入转化为"玩家行动描述"注入 Prompt

### 2.6 一致性检查
- 可选的审查者模型：检查新剧情与大纲一致性、状态变更合理性

### 2.7 存档增强
- 多槽位支持（可命名）、手动存档、存档文件版本兼容（schema 迁移）

### 2.8 回档记忆隔离
- 从 checkpoint 回档后，之前路线的对话历史不混入当前上下文
- 保留所有路线冒险日志用于结局回顾

### 2.9 API 容错增强
- 自动重试（可配置次数和间隔）、优雅降级、断点续传

---

## Phase 3: 完整体验

> 长期愿景，Phase 2 成熟后按需启动。

### 3.1 图像生成集成
- 异步调用 Stable Diffusion / DALL·E API
- 关键场景自动/手动触发生成插画，嵌入对话流

### 3.2 云同步
- 存档加密上传至云端，跨设备同步

### 3.3 语音合成（TTS）
- 可选朗读叙事文本，不同角色不同声线

### 3.4 剧本导出
- 将冒险历史格式化为小说/剧本格式，支持 Markdown / PDF 导出

### 3.5 多人模式
- 不同玩家扮演不同角色，AI 居中叙述协调互动

---

## 附录：与原始文档的映射

| 原始文档章节 | Phase 1 | Phase 2 | Phase 3 |
|-------------|---------|---------|---------|
| 一、核心理念 | ✅ 完全覆盖 | — | — |
| 二、整体游戏流程 | ✅ 简化版（极简上下文） | ✅ 完整版 | — |
| 三、动态状态系统 | ⚠️ 硬编码模板 | ✅ LLM 动态生成 | — |
| 四、上下文与成本管理 | ⚠️ 仅 bridge_text | ✅ 向量记忆+多模型 | — |
| 五、内容质量保障体系 | ⚠️ 格式解析+校验 | ✅ 审查者模型 | — |
| 六、用户交互与选项系统 | ⚠️ 固定选项+条件置灰 | ✅ 自定义输入+Web UI | — |
| 七、图像生成集成 | ❌ | ❌ | ✅ |
| 八、存档与持久化 | ⚠️ 多槽自动存档 | ✅ 多槽+手动 | ✅ 云同步 |
| 九、非功能性需求 | ⚠️ 基础覆盖 | ✅ 全面 | ✅ 增强 |
| 十、未来增强方向 | ❌ | ❌ | ✅ |

> ✅ = 完整覆盖　⚠️ = 简化覆盖　❌ = 未覆盖

---

*文档版本：v3.0 | 最后更新：2026-07-04（以 Phase1-exec-flow 为权威重构，去重纠错）*
