# Storyloom 工程日志

> 按时间线记录每个设计决策的背景、动机与依据。倒序排列（最新在前），新日志插入文首。
>
> 格式约定：**背景**（为什么此时需要决策）→ **决策**（做了什么选择）→ **依据**（commit / spec 章节 / memory 文件）。

---

## 2026-07-17（周五）

### 选项条件评估收归引擎

**背景**：`<opt if="...">` 的条件评估此前由 UI 层负责——`options` 事件携带原始 `conditions` 字符串，UI 需自行实现与引擎一致的评估逻辑。这与 `<set>`、`<route>` 的条件评估（均由 `GameState.evaluate_condition()` 统一处理）不一致，且违反"本地数据为唯一真相源"原则。

**决策**：
1. 引擎在 yield `options` 事件前评估每个选项的 `if` 条件，结果写入 `enabled` 列表
2. 全部不可选时兜底为全部可选（防止游戏卡死）
3. CLI 适配：读 `enabled` 标注 `(locked)`，disabled 项本地拦截
4. spec `exec-flow.md` §4.6 同步更新

**依据**：memory `option-condition-engine-evaluation.md`；spec `exec-flow.md` §4.6；`game_loop.py` L718-738；`game_driver.py` L437-474。

---

### UserConfig 模块：集中用户配置管理 + 移除 .env 耦合

**背景**：项目缺少统一的用户配置层。语言硬编码在 `dev_main()` 中；API 凭证通过 `api_client._find_project_root()` 向上搜索 `.git` 目录定位 `.env` 文件——该模式在打包后不可用。存档路径、语言偏好等用户选择无持久化机制。

**决策**：

1. **新增 `UserConfig` 模块**：单类管理 `config.json`（JSON 格式），暴露 `language`/`api_key`/`api_base_url`/`api_model` 四个属性。支持 headless 模式（`app_dir=None`，纯内存）和 disk 模式（读写 `<app_dir>/config.json`）。原子写入（temp + `os.replace`），缺失字段自动回填，损坏 JSON 不删除文件。
2. **移除 `.env` 依赖**：`ApiClient` 构造器接受 `UserConfig`，不再内部搜索 `.env` 文件。优先级：`os.environ` > `UserConfig` > 默认值。删除 `_find_project_root()`、`_load_dotenv()`、`_load_env()`。
3. **i18n 运行时切换**：新增 `switch_language(language)`，提取 `_load_translator()` 供 `init_i18n` 和 `switch_language` 共用。`init_i18n` 新增 `locale_dir` 参数供打包场景传入自定义路径（默认 `__file__`-relative fallback 保持兼容）。
4. **依赖注入**：`GameSession.__init__` 的 `api_client` 变为可选参数，入口点负责 `UserConfig → ApiClient → GameSession` 全链路 wiring。
5. **应用根目录辅助函数**：`_get_app_dir()` 封装 `sys.frozen` 判断——打包后指向 exe 所在目录，开发时指向项目根。`config.json`、`locale/` 均基于 `app_dir` 解析。

**改动**：10 文件，+474/-267 行。新增 `user_config.py`、`config.example.json`、`test_user_config.py`、`test_i18n.py`。删除 `.env.example`。276 tests passed，零回归。

**依据**：commit `86c9345`..`f5d0917`（连续 9 commits）；spec `docs/superpowers/specs/2026-07-17-user-config-design.md`；plan `docs/superpowers/plans/2026-07-17-user-config-implementation.md`。

---

### 存档系统重构：按游戏分目录 + 追加式 checkpoint 存档

**背景**：当前存档系统每个游戏只有一个 `saves/{label}.json` 文件，每次 checkpoint 覆盖写入。玩家无法回到历史关键节点——存档仅适用于"继续最新进度"，不支持回溯或时间线浏览。需求：每个 checkpoint 独立存档、追加不覆盖、UI 两级选择（先选游戏再选存档）、修改最小化。

**决策**：

1. **Per-game 目录结构**：`saves/{label}_{created_at}/` 下存放所有存档。`_init.json`（`round_count=0`）为共创结束时创建的"元存档"——新游戏入口和 checkpoint 存档共享完全相同的格式（`to_save_dict()` 输出），`from_save_dict()` 统一加载。
2. **追加模式**：checkpoint 存档文件名为 `{cp_title}_{timestamp}.json`，时间戳保证不重名不覆盖。`SaveManager.save(cp_title=None)` 写 `_init.json`，`cp_title=str` 写 checkpoint 存档。
3. **`start_game()` 和 `load_game()` 收敛为单一路径**：`start_game(result)` 直接从 `CoCreationResult` 构建 `_init.json` 字典（零 GameLoop 依赖），写入后调用 `load_game()` 加载。新游戏 / 继续 / 回溯三条路径完全一致。
4. **修复 Round 1 prompt 状态值不一致**：`build_round1()` 原从 `story_config.variables[].initial` 读取变量值——读档时 LLM 看到初始值而非当前实际值。改为必传 `state_vars` 参数，始终显示 `game_state.state_vars` 实际值。删除旧 `_format_state_vars()` 方法。
5. **SaveManager API 重构**：实例方法操作单个游戏目录（`save`/`load`/`delete`/`list_saves`），跨游戏操作改为静态方法（`create_game`/`list_games`/`delete_game`/`list_saves_for_game`）。
6. **GameSession API 适配**：`start_game()` 返回 `(GameLoop, game_id)`；`load_game(game_id, filename)` 两级定位；新增 `list_games()`、`delete_game(game_id)`、`delete_save(game_id, filename)`。去除持久 SaveManager 实例。

**改动**：9 文件，+623/-252 行。核心引擎文件零改动：`co_create.py`、`context_manager.py`、`streaming_parser.py`、`api_client.py`、`config.py`、`i18n.py`。251 tests passed。

**依据**：commit `66fa07f`；plan `hidden-jumping-ripple.md`；`docs/spec/data-model.md §3.1-3.4`；`prompt_builder.py:220-222`（旧 `_format_state_vars` 逻辑）。

---

### 删除 `list` 变量类型

**背景**：存档中发现 LLM 为"事件标记"变量使用了 `list` 类型。审查发现虽然 `list` 类型在代码库中完整实现（初始化、`<set>` 操作 `+`/`-`、静默去重），但条件求值不支持 `包含`/`不含` 操作符——LLM 在路线条件中自然使用这些操作符时，引擎正则无法匹配，静默返回 `False`，导致路由永远走兜底逻辑。让 LLM 操作 list 类型带来的复杂度远大于其价值。

**决策**：彻底删除 `list` 变量类型，只保留 `number` 和 `string`。`VARIABLE_LABEL_CAP` 语义从 "string/list" 收紧为 "string"。

**改动**：删除 ~136 行（9 文件）——引擎核心 3 文件、规范文档 3 文件、测试 3 文件。新增 `test_rejects_unknown_variable_type`。

---

## 2026-07-16（周四）

### CLI 模式重构：游玩默认入口 + 两阶段录制

**背景**：CLI 默认进入观察者+instant 模式，对普通玩家不友好。观察者录制逻辑存在 prompt 双重写入（`write_prompt_at_send` 和 `record_round` 都写 `prompts.txt`），缺乏清晰的提交/接收两阶段契约。

**决策**：
1. 默认入口改为游玩模式（手动 pacing，Tab 切换），零参数。
2. 观察者通过 `--observer` 进入，默认手动 pacing（与游玩一致），`--instant` 禁用 pacing 和切换。
3. 录制改为两阶段：Phase 1 提交 prompt 时写 `prompts.txt` + 清空 `responses.txt`；Phase 2 完整接收后 `record_round` 只写 `responses.txt` + `checks.txt`。
4. 手动 argv 解析替换为 argparse。

**依据**：`src/storyloom/dev_cli/game_driver.py`、`src/storyloom/dev_cli/observer.py`、`src/storyloom/dev_cli/__init__.py`。

### 异常处理统一：移除自动重试，三阶段行为对齐

**背景**：引擎三个阶段的异常处理各自独立设计，行为不一致——共创阶段有自动重试（`MAX_RETRIES`），叙事阶段 yield error 事件 + 手动重试，冒险日志阶段无重试机制。用户期望所有严重异常由 UI 决策，引擎不做自动恢复。

**决策**：
1. 删除 `MAX_RETRIES` 全局常量——仅共创阶段使用，语义不统一。
2. 共创阶段：`send()` 和 `generate()` 移除自动重试循环，失败时抛 `CoCreateError(phase, message)`，保存 `_retry_state`；新增 `retry_send()` 和 `retry_generate()` 公开方法，与叙事阶段 `retry()` / `retry_adventure_log()` 模式一致。
3. 冒险日志阶段：`run_adventure_log()` 保存 prompt 到 `_adv_retry_prompt`；新增 `retry_adventure_log()` 方法。
4. UI 侧（`game_driver.py`）：三阶段均展示错误并询问重试。

**依据**：`src/storyloom/core/co_create.py`、`src/storyloom/core/game_loop.py`、`docs/spec/data-model.md` §B-5。

### Spec-vs-Code 审计 + 文档同步 —— 9 项修复

**背景**：距离上次审计（07-13）约三天。全面对照 4 份 spec + 全部核心源码 + 接口文档 + CLI 文档/代码，排查规范落实与文档一致性。

**决策**：

| # | 级别 | 文件 | 问题 | 处理 |
|---|------|------|------|------|
| 1 | P1 | `docs/api/co-create.md` | `send()` 返回值描述错误（dict vs str） | 重写全文（f7e24e1） |
| 2 | P1 | `docs/api/co-create.md` | 列出了引擎不做的关键词检测 | 同 1 |
| 3 | P1 | `docs/api/co-create.md` | 列出了不存在的 `generating` 阶段 | 同 1 |
| 4 | P1 | `docs/spec/exec-flow.md` | 超时处理流程与代码不一致（复杂截断 vs 严重错误+重试） | 更新规范对齐代码（44867cd） |
| 5 | P2 | `src/storyloom/core/save_manager.py` | `load()` 校验失败未删除损坏文件 | 新增 `_remove_corrupt()`（44867cd） |
| 6 | P1 | `docs/cli.md` | 全文描述已删除的旧 CLI（main.py, cli_utils.py, --quick 等） | 删除文件 + 清理索引（9de9aab） |
| 7 | P2 | `src/storyloom/dev_cli/game_driver.py` | auto 延迟 docstring 0.5s ≠ 代码 1.0s | 提取 `_AUTO_DELAY_SEC`，文档引用常量名（9de9aab, d2261fb） |
| 8 | P2 | `src/storyloom/dev_cli/game_driver.py` | `_drain_non_options` 未使用的 `mode` 参数 | 删除（9de9aab） |
| 9 | P2 | `src/storyloom/dev_cli/__init__.py` | docstring 只列 2 种用法，实际 7 种 | 补全（9de9aab） |

**误报**：`CoCreateParser.parse_story_config` 中 `characters` 空值校验——已有 `not result[f].strip()` 检查。

**依据**：commit 44867cd, f7e24e1, 9de9aab, d2261fb。227 测试全绿。

---

## 2026-07-13（周日）

### Spec-vs-Code 审计与精简 —— 16 项修复 + 4 项重叠消除

**背景**：距离上次审计（2026-07-11）约两天，项目继续演进（UiInterface 删除、Web 文件夹初始化、co_create prompt 清理）。重新全面对照 4 份 spec 文档与全部核心源码，发现 16 项不一致（8 P1 + 8 P2），以及 4 处文档间重叠。

**决策**：

**16 项修复**：

| # | 级别 | 文件 | 问题 | 处理 |
|---|------|------|------|------|
| 1 | P1 | CLAUDE.md | "StreamingXmlParser deleted" 断言错误（已于 07-11 恢复） | 改为 "restored" + 准确描述 |
| 2 | P1 | CLAUDE.md | `_launch_prefetch()` 方法名过时 | → `_launch_api()` |
| 3 | P2 | CLAUDE.md | 测试数 228 → 236 | 更新 |
| 4 | P1 | CLAUDE.local.md | 引用已删除的 `ui_interface.py` | 移除 |
| 5 | P1 | exec-flow.md | Phase 5 描述 SET/checkpoint 过时（应在 Phase 3） | 更新 |
| 6 | P2 | exec-flow.md | STORY_END 事件时机（Phase 5→Phase 3） | 从 Phase 5 移除 |
| 7 | P1 | exec-flow.md | `_launch_prefetch()` → `_launch_api()` | 更新 + 补充"所有轮次统一使用" |
| 8 | P1 | exec-flow.md | `prompt_builder.assemble()` 方法不存在 | → 实际调用链 |
| 9 | P1 | prompt-design.md | Round N 标签中文→英文（与代码对齐） | 更新示例 |
| 10 | P1 | prompt-design.md + exec-flow.md | 压缩消息/格式错误纠正中文→英文 | 同步两文档 |
| 11 | P2 | block-spec.md | "选项字母序号"→"选项数字键序号" | 修正 |
| 12 | P2 | exec-flow.md | `api_client.call()` → `api_client.chat()` | 修正 |
| 13 | P2 | data-model.md | 缺失 `SUPPORTED_LANGUAGES`、`DEFAULT_LANGUAGE` | 追加到 §A.2 |
| 14 | P2 | prompt-design.md | outline 状态图例行（代码中无） | 删除 |
| 15 | P2 | exec-flow.md | 引用废弃 `AUTO_ADVANCE_DELAY_MS` + M 键约束 | 删除，UI 自行管理 |
| — | P1 | exec-flow.md | `STORYLOOM_API_KEY` → `DEEPSEEK_API_KEY` | ~~跳过~~ → 2026-07-16 统一为 `LLM_API_KEY`（去品牌化） |

**4 项文档精简**：exec-flow.md 删除与 prompt-design.md 重叠的消息数组结构、Round N 内容表、压缩概念描述，净减 ~32 行。各文档职责更清晰：
- `exec-flow.md` — 执行管线（何时调用、如何流转）
- `prompt-design.md` — Prompt 内容结构
- `block-spec.md` — XML 元素语法与校验
- `data-model.md` — 数据结构与常量

**依据**：
- 227 tests pass
- 上次审计：[[2026-07-11-bridge-processing-audit]]

---

## 2026-07-11（周六）

### CoCreateFlow API 重构 —— Q&A 与生成分离，i18n 清理

**背景**：三个语言相关问题触发——
1. story label 几乎固定为英文（存档显示名与用户语言不匹配）
2. 共创阶段"是否开始"问句概率固定为英文
3. `co_create.py:437` 硬编码中文 `（或输入你自己的答案）`，未与配置语言联动

根因分析发现更深层问题：`_START_KEYWORDS` / `_QUIT_KEYWORDS` 在引擎侧硬编码解析用户意图，UI 与引擎职责混淆。

**决策**：

1. **i18n 清理**：`.po` 从 48 条精简至 3 条活跃条目，删除 45 条无用翻译，修正 msgid 换行符偏差导致翻译不生效的 bug。编写 `scripts/compile_mo.py`（stdlib 版 `.mo` 编译器）。

2. **语言感知 Prompt**：`CO_CREATE_SYSTEM_PROMPT` 转为 `string.Template`，`_LANG_META` 字典管理给 LLM 的英文指令，`_()` + `.po` 管理 LLM 输出给用户的文本模板（`$own_answer_hint`）。

3. **API 重构**：
   - `send()` → 返回 `str`（LLM 回复），纯转发，无关键词检测、无轮次上限。API 失败 3 次重试后 raise `RuntimeError`。
   - 新增 `generate()` 公共方法：注入格式规范 Prompt → API 调用 → 解析 + 校验 + 重试 → 返回 `CoCreationResult`。
   - 删除 `_START_KEYWORDS` / `_QUIT_KEYWORDS` / `_qa_round`。
   - Q&A 与生成 Prompt 拆分：`CO_CREATE_SYSTEM_PROMPT`（Q&A only）+ `CO_CREATE_GENERATION_PROMPT`（格式规范）。

4. **UI 层**：dev_cli 用 `/go` 触发 `generate()`，`/quit` 触发 `abort()`，其余输入全部直接转发 LLM。启动时显示命令提示。

5. **Prompt 语气优化**：维度从"必须聚焦"改为"作参考指南"；删除"禁止询问是否开始"等机械指令；主角维度补充 gender。

**净效果**：4 文件变更，+231/-360 行（净 -129）。227 tests pass。引擎与 UI 职责边界清晰化。

**依据**：
- commits: `9c60124`, `20426ab`, `c35769e`, `a8e04f1`
- [[co-create-api-refactor-2026-07-11]]
- [[co-create-i18n-hardcoded-assumptions]]

### Spec-vs-Code 审计 —— 6 项修复

**背景**：在 `stream_round()` 统一重构后，对全部 4 份 spec 文档与核心源代码进行逐条对照审计，确认代码是否忠实落实规范流程与设计。本次是重构后首次全面审计。

**发现与修复**：

| # | 级别 | 问题 | 处理 |
|---|------|------|------|
| 1 | P1 | `to_save_dict` 的 `round_count` 差一：存档在 Phase 3 触发但 `add_round` 在 Phase 5 递增 | `to_save_dict` 使用 `round_count + 1` |
| 2 | P1 | `from_save_dict` 重建 `outline_text` 丢失分支树（`├→`/`└→`） | 恢复分支连接行，兼容新旧保存格式 |
| 3 | P1 | `_handle_checkpoint` 设置的格式错误被 Phase 5 无条件覆盖 | Phase 5 合并解析器错误 + checkpoint 校验错误 |
| 4 | P2 | 冒险日志 `join()` 阻塞 generator，与普通轮间衔接的异步模式不对称 | 移除 `join()`，新增 `get_adventure_log()` 公共方法 |
| 5 | P2 | `_parse_outline_goals` 提取 `{title}：{goal}` 而非仅 goal | 规范 `prompt-design.md` §4.3 更新为含标题前缀 |
| 6 | P2 | `_accumulate_checkpoint` 残留 `cp_node == "end"` dead code | 删除旧设计分支 |
| 7 | P2 | `_handle_set_event` + `apply_set` 双重条件求值 | `apply_set` 区分"跳过"（`reason="skipped:..."`），删除 `_handle_set_event` 重复预检 |
| 8 | P2 | Q&A 15 轮上限与规范"不做轮数上限"矛盾 | 撤回——15 轮为安全熔断，非规范违规 |

**净效果**：引擎核心 -12 行（含 5 行 dead code），`GameLoop` 新增 1 个公共方法（`get_adventure_log`），`prompt-design.md` §4.3 更新 2 处，293 测试全绿。

**依据**：
- 4 份权威 spec：`exec-flow.md`、`block-spec.md`、`prompt-design.md`、`data-model.md`
- `stream_round()` 重构：commit `04845ce`

### 叙事循环统一重构 —— stream_round() 单入口

**背景**：07-11 前序审计（[[2026-07-11-bridge-processing-audit]]）和 streaming parser 集成后，代码与 spec 仍存在结构性偏离：

| 偏离 | 根因 |
|------|------|
| Round 1 不触发 pre-fetch | `start_round1_stream` 末尾无后台 API 调用 |
| 条件 set 跨轮延迟 | `continue_round_stream` 将条件 set 推迟到下一轮执行 |
| pre-fetch/live 双路径 | `_launch_prefetch` 同时做状态清算和 API 启动，live 路径双重调用 `_apply_deferred_step` |
| bridge_text 过期 | live 路径 `_launch_prefetch` 在 `_finalize_parsed_round` 之前调用，bridge_text 未更新 |

根因：代码未按照 `exec-flow.md` §4.1 的 6 阶段线性流程组织。每轮流程应是固定的、不可分割的。

**决策**：全面重构 `game_loop.py`——用 `stream_round()` 统一入口替代旧的双路径架构。

**架构**：
```
gl.start_game()          # 仅 Round 1：构建 Prompt + 启动后台 API
gen = gl.stream_round()  # 每轮统一入口
for event in gen:        # Phase 1-4: 流式解析
    if event["type"] == "options":
        gen.send(key)     # </choice> 暂停 → UI 输入 → 恢复
# Phase 5: </story> → add_round → build next prompt → launch API
```

**关键设计决策**：

1. **所有 API 调用走 daemon 线程 + queue.Queue**——取消 pre-fetch/live 分叉。每轮 Phase 5 启动后台 API，下一轮 `stream_round()` 消费 queue。Round 1 不例外。

2. **SET 解析时立即求值**——在 `stream_round()` 的 Phase 3 中，收到 `EventType.SET` 即构建 `SetOperation` + 条件求值 + `apply_set`。不再有"条件 set 延迟到下一轮"的概念。删除 `_apply_deferred_step`。

3. **CHECKPOINT 解析时立即处理**——在 `CHECKPOINT_END`（或自闭合 `<checkpoint/>`）时评估 routes、推进节点、accumulate checkpoint、触发 auto-save。删除 `_finalize_parsed_round` 中的 checkpoint 处理。

4. **Choice 暂停 via gen.send(key)**——`</choice>` 时 `yield options`，generator 暂停等 UI 调用 `gen.send(key)`。恢复后 `current_branch` 和 `choice_dict` 更新，后续 set 条件求值使用正确的 choice_dict。

5. **Phase 5 极简化**——`</story>` 后只做：`add_round` → `build_round_n` → `_launch_api`。数据处理（set/route/checkpoint）已在 Phase 3 完成。

6. **每轮数据独立**——`current_branch = "main"`、`choice_dict = {}` 每轮初始化，与 block-spec.md §3 "轮次结束时清空"一致。

**删除的旧代码**（-777 行）：
`start_round1_stream`、`continue_round_stream`、`start_round1`、`continue_round`、`_launch_prefetch`、`_apply_deferred_step`、`_finalize_parsed_round`、`_take_prefetch`、`_emit_options`、`_stream_parse_chunk`、`_prefetch_lock`、`_prefetch_data`、`_round1_started`

**新增代码**（+541 行）：
`stream_round()`、`start_game()`、`_launch_api()`、`_handle_set_event()`、`_handle_checkpoint()`

**StreamingXmlParser 变化**：
- `ParseEvent.choice_data` — `</choice>` 时携带累积的选项数据（id、branches、labels、conditions）
- `routes` 属性 — 暴露累积的 route 目标列表，供 checkpoint 处理时读取

**修复 A（结局判定）**：`_handle_checkpoint` 原以 LLM 输出是否包含 `<route>` 子元素判定结局。自闭合 checkpoint（中间单路径节点）无 `<route>` → 错误触发 `ending_flag`。修复：查大纲定义中该节点的 `routes` 是否为空。大纲中仅最终节点 `routes: []`。

**修复 B（set 条件求值）**：`_handle_set_event` 原依赖 `apply_set` 返回值区分"跳过"和"应用"。但两者返回相同的 `SetResult(accepted=True, reason=None)`，导致条件满足的 set 变更事件被抑制。修复：调用 `apply_set` 前先求值条件，不满足则直接跳过。

**净效果**：-236 行，293 测试全绿。`dev_cli/ui.py` 待后续适配新 API。

**依据**：
- `exec-flow.md` §4.1 — 6 阶段每轮统一
- `block-spec.md` §3 — 每轮数据独立，轮结束时清空
- `block-spec.md` §5 — set 在 bridge 前立即执行
- `data-model.md` §2 — routes 为空 → 结局节点（指大纲定义）
- commit `04845ce` — `refactor(engine): unify narrative loop into single stream_round() flow`
- commit `5488d79` — `fix(engine): use outline routes for ending detection, evaluate set conditions before apply`

### Spec-vs-Code 审计 —— 4 项快速修复

**背景**：对 4 份权威 spec 文档与全部核心源代码进行逐条对照审计（前序重构前）。

**修复**：

| # | 等级 | 问题 | 修复 |
|---|------|------|------|
| 3 | P1 | `apply_set` 对未知变量/非法操作 raise ValueError，应静默返回 | 4 处 `raise` → `return SetResult(accepted=False, reason=...)` |
| 4 | P1 | `_last_bridge_text` 使用未过滤的 `parsed.bridge_text`，含全部分支文本 | 改用 `sp.get_bridge_text(current_branch)` |
| 5 | P2 | Adventure Log Prompt 语言 spec-vs-code 不一致（spec 中文，代码英文） | Spec 更新：所有 Prompt 统一英文，输出语言由 story_config.language 决定 |
| 6 | P2 | StreamingXmlParser 未校验重复 bridge | 第二个 bridge 记入 `_format_errors`（与 post-bridge 违规同级） |

**依据**：commit `e5611da`

### 结局节点设计修订 —— routes 数量判定结局

**背景**：原设计用 `node="end"` 特殊值标识结局节点。问题：(1) 多结局故事中命名冲突，(2) LLM 需额外记住命名约定。

**决策**：移除 `node="end"` 特殊值。结局判定改为：**大纲定义中 routes 为空 = 结局节点**。`co_create.py:validate_outline` 已确保仅最终节点 routes 为空。

**影响文件**：`block-spec.md` §4、`data-model.md` §2、`exec-flow.md` §5.2、`prompt-design.md` §3.4、`co_create.py`（CO_CREATE_SYSTEM_PROMPT + parse_outline）

**依据**：spec 文档在上述 commit 中同步更新。

---

---

### Bridge 处理流程审计 —— 时序模型澄清与 Pipeline 缺口

**背景**：2026-07-11 的 StreamingXmlParser 恢复（commit `56cb7ee`）和全面集成后，仍有遗留问题：`_stream_parse_chunk()` 丢弃 `EventType.BRIDGE`，pre-fetch 触发时机和时序模型存在理解偏差。本 session 对 bridge 处理全流程进行系统性审计。

**时序模型澄清（关键认知修正）**：

三层独立流模型：
```
LLM 生成流（token 产出）
    ≥
程序解析流（StreamingXmlParser 逐行解析）
    ≥
UI 展示流（用户阅读 / 自动推进）
```

**`<bridge/>` 的正确定位**：
- 对 LLM：**结构约束**——标记交互区与叙事区硬分界
- 对程序：**模式切换**——`_post_bridge = True`，后续快速解析（无 UI 反馈）、错误捕获、bridge_text 存储
- Pre-fetch 的真正触发点是 **`</story>`（解析完成）**，不是 `<bridge/>`
- Bridge→`</story>` 区间解析极快（纯叙事、无 UI 阻塞），两者几乎同时

此澄清推翻了之前记忆文件中的部分结论——pre-fetch 不需要在 bridge 时刻立即触发，当前在解析完成处触发是正确设计。

**标准每轮流程**（引擎视角）：

```
1. TTFT 等待 — UI 展示上一轮 bridge_text（首轮无）
2. <story> 开始 — 解析生命周期入口
3. 流式解析 — 逐行处理，向 UI 发送 segment，必要时等待 UI 反馈（选项）
4. <bridge/> — 模式切换（非时序触发器）
5. </story> — 打包数据 → 存储 → 组装 Prompt → 后台 API 调用
6. 错误处理 — 严重（通知 UI、用户决策）/ 普通（程序内部处理、Prompt 反馈）
```

**修复内容**（commit `30a4a09`）：

| 修复 | 说明 |
|------|------|
| BRIDGE 事件产出 | `_stream_parse_chunk()` 新增 `{"type": "bridge"}` yield |
| 统一分支过滤 | 移除 `position == "pre"` 限制——post-bridge 命名 branch 同样按 `current_branch` 过滤 |
| 规范：三层时序 | `exec-flow.md` §4.3 增加时序模型 + 流间同步规则 |
| 规范：bridge 双重角色 | `exec-flow.md` §4.7 重写——分离"LLM 结构约束"和"程序模式切换" |
| 规范：UI 队列缓冲 | `exec-flow.md` §4.5 增加推荐 UI 消费模式 |

**剩余缺口**：

代码侧：
- `STORY_BEGIN` / `STORY_END` 事件被 `_stream_parse_chunk()` 丢弃——引擎无法感知解析生命周期边界（P1）
- 错误处理不一致：API 错误用 `yield {"type": "error"}`，解析失败用 `raise ParseError`——调用者需两条路径（P1）
- `continue_round_stream()` 与 `_stream_from_prefetch()` 共享 ~70 行重复逻辑——应抽取 `_process_round()`（P2）

规范侧：
- §4.1 8-step pipeline 混淆引擎/UI 职责（P1）
- 缺少显式 TTFT 等待阶段描述（P2）
- 缺少错误严重等级分类（P1）

**依据**：
- commit `30a4a09` — `fix(engine): surface BRIDGE events, unify branch filter across bridge boundary`
- [[2026-07-11-bridge-processing-audit]]（完整审计记录）
- [[2026-07-11-streaming-parser-timing-flaw]]（更新后状态）
- [[streaming-parser-integration-2026-07-11]]（更新后状态）

### 叙事循环统一 —— 审计缺口全面修复

**背景**：上一条审计发现 8 个缺口（4 代码 + 4 规范）。本 session 按照 6 阶段引擎视角标准流程，逐一修复。

**决策**：

**规范修复（3 项）**：
| 修复 | 说明 |
|------|------|
| §4.1 8-step → 6-phase | 替换混淆引擎/UI 职责的旧管道，明确职责边界 |
| §4.1.1 错误等级分类 | 正式定义两级错误：严重（通知 UI→用户决策）vs 普通（内部处理→Prompt 反馈） |
| TTFT 等待阶段 | 6 阶段第 1 步显式描述 |

**代码修复（5 项）**：
| 修复 | 说明 |
|------|------|
| STORY_BEGIN / STORY_END 事件 | `_stream_parse_chunk()` 不再丢弃——引擎可感知解析生命周期边界 |
| 提取 `_apply_deferred_step()` | Steps 2-3.6（延迟 set + 路由评估 + checkpoint 累积）在 `_launch_prefetch` 和 `continue_round_stream` 之间共享，消除重复 |
| 提取 `_finalize_parsed_round()` | Post-parse 逻辑（format_errors → add_round → unconditional sets → adventure log → options/ending/done yield → notify）从两处 ~70 行重复变为一处 |
| 删除 `_stream_from_prefetch` | 内联到 `continue_round_stream`——**单一续行入口**。Pre-fetch 降级为 API 响应来源的二选一（`queue.Queue` vs `api_client.stream_chat_iter`），不再有独立流程 |
| 错误路径统一 | `XmlParser` 的 `raise ParseError` 路径已从生产流消除（核心引擎零引用），所有错误统一走 `yield {"type": "error"}` |

**架构效果**：
```
continue_round_stream(choice_key)    ← 唯一续行入口
  ├─ [pre-fetch hit]  从 queue 取 chunks（来源 B）
  └─ [pre-fetch miss] 实时调用 API（来源 A）
  └─ _finalize_parsed_round()        ← 统一完成出口
```
净变化：-96 行（394 insertions, 490 deletions），8 个审计缺口全部关闭。

**依据**：
- commit `640a862` — `refactor(engine): unify narrative loop into single continuation flow`
- [[2026-07-11-bridge-processing-audit]]（缺口来源，状态更新为已关闭）

### Bridge pre-fetch 时机缺陷 —— 未在 `<bridge/>` 处即时触发

**背景**：2026-07-11 规范合规审查发现，`exec-flow.md` §4.3 明确要求：

> 当程序解析到 `<bridge/>` 时，立即通过 bridge pre-fetch 在后台线程发起下一轮 API 调用 — 同时继续展示 post-bridge 段落（bridge_text）。

但当前实现的实际时序为：

```
流式接收全部 token
  └─ _stream_parse_chunk 仅处理 SEGMENT 事件
     └─ BRIDGE 事件被 StreamingXmlParser 内部消费（设置 _post_bridge=True）
         ↓  —— GameLoop 完全不感知 bridge 时刻 ——
全部 token 接收完毕
  └─ sp.get_result()          # 完整解析
  └─ sp.get_bridge_text()     # 过滤 bridge_text
  └─ add_round(...)           # 存入 ContextManager
  └─ _launch_prefetch(...)    # 组装下一轮 Prompt
```

**核心问题**：`_stream_parse_chunk()`（`game_loop.py:1062`）只对 `EventType.SEGMENT` 做分支过滤和产出，`EventType.BRIDGE` 事件被丢弃。GameLoop 无法在 bridge 时刻触发 pre-fetch，必须等待全部 token 接收完毕。

**后果**：pre-fetch 竞争的不是"bridge_text 展示时长 vs TTFT"，而是"bridge_text 展示时长（10-20s）vs **完整生成时间 + 下一轮 TTFT**（35-80s）"。这违背了 bridge 机制的核心设计意图——利用 bridge_text 展示时间掩盖 API 延迟。

**待解决**：
1. `_stream_parse_chunk` 需要产出 `{"type": "bridge"}` 事件
2. `continue_round_stream` 在收到 bridge 事件时：已积累的 pre-bridge 数据（sets、checkpoint、routes）足以组装下一轮 Prompt；bridge_text 在流式接收中逐步附加
3. 预取线程在 bridge 时刻启动，与 post-bridge 展示并发执行

**依据**：
- `exec-flow.md` §4.3 — 明确要求 bridge 时刻即时触发 pre-fetch
- `exec-flow.md` §4.4 — "利用 NNN| 行号前缀使每行成为自包含的 XML 片段，逐行正则匹配产出事件"
- [[2026-07-11-streaming-parser-timing-flaw]] — 此前已分析过全量解析导致 pre-fetch 必然失败

### StreamingXmlParser 恢复与集成 —— 流式解析落地

**背景**：经过时序缺陷讨论（见下一条），确认 `StreamingXmlParser` 必须恢复。同时明确了三个架构认知：
1. 三条流（LLM 生成、程序解析、用户显示）是**时序顺序**关系而非速度关系——不可逆的先后依赖 + bridge 时刻的时间重叠
2. 双线处理（预处理建索引 + 实际处理做决策）在当前规模下无必要——分支过滤仅需 5 μs，O(1) 跳转无实际收益
3. 流式解析 ≠ 双线处理——前者解决"何时处理"，后者解决"几遍处理"。上一个 Agent 将二者混淆是删除 StreamingXmlParser 的关键原因

**决策**：
1. 从 git 历史恢复 `StreamingXmlParser`（commit `6697f47^`），修复 5 个 bug：
   - `m.lastindex` 脆弱逻辑 → 显式 group 索引
   - `_RE_SEG` 未捕获 n 属性 → 添加捕获组
   - Choice 合并逻辑错误 → `feed_line()` 中累积 `_pending_choices`
   - 自闭合 `<checkpoint/>` 不识别 → 新增 regex
   - SEGMENT 事件缺 `branch_name` → 从状态机设置
2. 移除双线预处理索引（`branch_ranges`、`_branch_start_line`）——单遍解析
3. 新增 `LineBuffer` 适配器：token chunks → 完整行
4. `_stream_from_prefetch()` 重写：`thread.join()` + 一次性 drain 替换为增量 `queue.get_nowait()` + `LineBuffer` → `StreamingXmlParser.feed_line()`。Segment 事件在行完成时即时产出
5. Pre-fetch 触发时机修复：`_launch_prefetch()` 从 `_emit_parsed()` 之后移至之前，`done_state` 在调用前捕获
6. 保留 `XmlParser.parse()` 用于非 pre-fetch 路径（Round 1、choice 轮次、ContextManager）
7. 45 个流式解析器测试 + 7 个一致性测试（vs XmlParser）

**依据**：
- commit `56cb7ee` — `feat(parser): restore StreamingXmlParser with streaming pre-fetch integration`
- [[2026-07-11-streaming-parser-restoration]]（完整变更记录）
- [[2026-07-11-streaming-parser-timing-flaw]]（动机分析）
- `docs/superpowers/specs/2026-07-05-narrative-flow-refactor-design.md` §2.2-2.5（设计依据）
- 303 passed, 24 skipped, 0 failed

### StreamingXmlParser 全面融入核心流程 —— 全量解析彻底平替

**背景**：上一条日志恢复了 `StreamingXmlParser` 但仅用于 pre-fetch 路径——Round 1 和 continue 慢路径仍使用 `XmlParser.parse()` 全量解析，且 `ContextManager._extract_bridge_from_xml()` 也依赖 `XmlParser`。

**决策**：
1. **三条路径统一流式化**：`start_round1_stream()` 和 `continue_round_stream()` 慢路径在 token 收集期间同步 `LineBuffer` + `StreamingXmlParser`，segment 事件随行完成即时产出
2. **提取 `_stream_parse_chunk()`**：消除三处 chunk→parser→event 重复逻辑
3. **`_emit_parsed()` → `_emit_options()`**：segment 在流式阶段已产出，`_emit_parsed` 简化为仅产出 options 事件
4. **`StreamingXmlParser` 增强**：
   - `_bridge_text_parts` → `_bridge_text_items: list[tuple[str, str|None]]` 追踪分支归属
   - 新增 `get_bridge_text(branch_name)` 方法支持分支过滤
5. **`ContextManager._extract_bridge_from_xml()`**：改用 `StreamingXmlParser.get_bridge_text()` 替代 `XmlParser.parse()` / `extract_bridge_text_for_branch()`
6. **Dataclass 归属迁移**：`ParsedOutput`、`Segment`、`SetOperation`、`RouteTarget`、`ParseError` 从 `xml_parser.py` 移至 `streaming_parser.py`（规范解析器拥有类型定义）。`xml_parser.py` 反向导入。所有生产代码消费者统一从 `storyloom.parser` 包级别导入
7. **测试数据修正**：`SAMPLE_XML` 的 `<opt key>` 从 `A`/`B` 改为 `1`/`2`（匹配规范）；`test_context_manager` 紧凑 XML 改为逐行格式（匹配真实 LLM 输出）

**架构效果**：
- 核心引擎（`game_loop.py`、`context_manager.py`）零依赖 `XmlParser` 类
- `xml_parser.py` 仅含 `XmlParser` 类（从 `streaming_parser` 导入类型），可安全删除
- 完整删除步骤记录在 [[xml-parser-removal-guide-2026-07-11]]

**依据**：
- `exec-flow.md` §4.3："所有轮次使用 `StreamingXmlParser` 逐行解析"
- `block-spec.md` §1："程序通过 `StreamingXmlParser` 逐行流式解析"
- commit `748f654` — `docs(spec): mandate StreamingXmlParser for all rounds, replace ElementTree full-parse`
- [[streaming-parser-integration-2026-07-11]]（完整变更记录）
- 303 passed, 24 skipped, 0 failed

### StreamingXmlParser 删除决定推翻 —— Bridge Pre-Fetch 时序缺陷

**背景**：2026-07-10 的架构分析（[[2026-07-10-adventure-log-and-parser-architecture]]）认为 `StreamingXmlParser` 的流式解析不必要，因为 `ElementTree` 全量解析仅需 234 μs。该模块被删除（commit `6697f47`）。2026-07-11 的深入讨论发现该分析存在根本性错误。

**核心发现**：Bridge pre-fetch 的时序约束不是"解析速度"，而是"**首段可展示内容的就绪时间**"。

**全量解析模型**（当前）：
- 下一轮内容可展示的前提：TTFT + **全部行**生成完毕 + XmlParser.parse()
- bridge_text 阅读时间（10-20s）需覆盖 TTFT + 完整生成时间（35-80s）
- **结论：不可能。** bridge_text 太短，pre-fetch 大概率无法在阅读期间完成
- 后果：用户在自动推进轮次之间经历 15-70 秒空白等待

**流式解析模型**（删除的 StreamingXmlParser）：
- 下一轮内容可展示的前提：TTFT + **第 1 行**生成完毕 + feed_line()
- bridge_text 阅读时间（10-20s）仅需覆盖 TTFT（10-30s）
- **结论：可行。** 在大多数场景下可实现无缝衔接

**之前分析为何错误**：
- 错误指标：已完成的 XML 字符串的解析耗时（234 μs）
- 正确指标：**从 pre-fetch 启动到首个可展示内容就绪的墙上时间**
- 差距不是 234 μs，而是**整个生成时间（25-50 秒）**

**附加发现**：`_launch_prefetch()` 在 `yield from self._emit_parsed()` 之后才调用。终端 UI 同步消费 segment 事件（含 `time.sleep`），导致 generator 阻塞——pre-fetch 在所有 segment 显示完毕后才能启动。bridge_text 实际提供了**零秒缓冲**。

**决策**：推翻 07-10 的删除决定。需要恢复 `StreamingXmlParser`（从 commit `7fe2278`）并正确集成到 pre-fetch 路径：
1. 移动 pre-fetch 触发点到 `_emit_parsed()` 之前
2. 后台线程中逐行 feed 到 StreamingXmlParser
3. ParseEvent 实时转发给 UI（segment 逐段展示，不等完整响应）
4. `XmlParser.parse()` 保留用于非 pre-fetch 路径（choice 轮次、Round 1）

**依据**：
- [[2026-07-11-streaming-parser-timing-flaw]]（完整时序分析）
- [[2026-07-10-adventure-log-and-parser-architecture]]（部分分析被推翻）
- `docs/superpowers/specs/2026-07-05-narrative-flow-refactor-design.md` §2.5-2.6（原始设计正确）
- exec-flow.md §4.3："bridge 机制的真正时限不是 LLM 总生成时间，而是后台 API 调用的 TTFT + 生成时间 vs. bridge_text 的展示时长"

### Adventure Log 时序修复

**背景**：`exec-flow.md` §5.2 要求冒险日志在 bridge 时刻发起，与 bridge_text 展示并发执行。实际代码中 `run_adventure_log()` 在所有 segment 展示完毕后同步调用——用户需额外等待 LLM 生成时间。

**决策**：
1. 提取 `_accumulate_checkpoint()` 辅助方法（消除 3 处重复的 checkpoint 处理逻辑）
2. Post-parse "end" 检测——Step 7 后立即检查 `parsed.checkpoint_node == "end"`
3. Adventure log 在 `_emit_parsed()` 前启动 daemon 线程，segment 展示期间并发执行
4. Early-return guard：`self._ending_handled` 标志防止结局后被重复调用

**依据**：
- commit `980ec2f` — `fix(engine): adventure log now runs concurrently with bridge_text display`
- [[2026-07-10-adventure-log-timing-fix]]
- exec-flow.md §5.2 并发设计描述

---

## 2026-07-10（周五）

### bridge pre-fetch 实现

**背景**：Bridge 机制要求程序在展示 post-bridge 缓冲文本期间发起下一轮 API 调用，以消除段边界停顿。exec-flow.md §4.3 描述了时序模型——程序解析到 `<bridge/>` 时立即提交下一轮 Prompt，同时继续展示 bridge_text。但此前实现侧一直是串行等待：展示完所有内容 → 等待玩家输入 → 组装 Prompt → API 调用 → 等待响应 → 开始下一轮。

**决策**：在 `GameLoop._launch_prefetch()` 中实现 daemon 线程 + `queue.Queue` 架构。

**触发条件**：仅对无选项（auto-advance）轮次触发。choice 轮次无法预计算下一轮的 messages 数组——bridge_text 的 branch 过滤依赖玩家选择，只有在玩家做出选择后才能确定 `current_branch`。

**流程**：
```
到达 <bridge/>
    │
    ├─ ① 检测：parsed.choices 非空？
    │   ├── 有 choice → 不预取（下一轮取决于玩家选择，messages 数组无法预计算）
    │   └── 无 choice → _launch_prefetch()
    │       ├── 捕获当前状态快照（done_state）
    │       ├── 组装下一轮 messages
    │       └── 启动 daemon 线程：api_client.stream_chat(messages) → queue.Queue
    │
    └─ ② 主线程：继续 emit bridge_text segments
        （用户阅读中；后台线程在 queue 中缓冲 chunks）
```

**已知局限**（07-10 已知，07-11 修复）：
- `_launch_prefetch()` 在 `yield from self._emit_parsed()` 之后调用——终端 UI 同步消费 segment 事件会阻塞 generator，导致 pre-fetch 在所有内容展示完后才启动。详见 07-11 日志"Pre-fetch 触发时机修复"
- 后台线程收集完整响应后才由主线程解析——无法实现流式展示。详见 07-11 日志"StreamingXmlParser 恢复"

**依据**：
- commit `663b9f2` — `feat(engine): implement bridge pre-fetch for auto-advance rounds`
- exec-flow.md §4.3 描述的时序模型
- [[2026-07-10-bridge-prefetch-work-log]]

### 规范合规审计与修复

**背景**：对代码实现与 4 份权威 spec 文档（exec-flow.md、block-spec.md、prompt-design.md、data-model.md）进行逐条对照审计。这是引擎完备化后首次系统性审计。

**决策**：发现并修复 1 P0 + 3 P1 + 4 P2 问题：

| 等级 | 问题 | 说明 | 修复 commit |
|------|------|------|-------------|
| P0 | unconditional set 双重应用 | 无条件的 `<set>` 在流式处理阶段应用一次，`_apply_sets()` 又应用一次 | `4715904` |
| P1 | emit_parsed 未传递 current_branch | 选项选择后的分支切换未反映在事件中 | `4715904` |
| P1 | AUTO_ADVANCE_DELAY_MS spec 引用错误 | 常量引用位置与 spec 不一致 | `4715904` |
| P1 | Round 1 parse 失败缺少 observer 通知 | `start_round1_stream` parse 失败路径缺少 `_notify()` 调用 | `951145c` |
| P2 | adventure log 时序 | 同步执行改为并发（见 07-11 详细日志） | `980ec2f` |
| P2 | save 文件缺少 label 字段 | spec 要求但未实现 | `642465f` |
| P2 | 配置文件与 data-model.md §A 不同步 | 常量值未反映最新 spec | `642465f` |
| P2 | streaming_parser.py 残留 | 已废弃的模块仍在仓库中 | `642465f`（后续 `6697f47` 彻底删除）|

**依据**：
- [[2026-07-10-spec-compliance-audit]]（完整审计报告）
- [[2026-07-10-spec-compliance-followup]]（修复记录）
- [[2026-07-10-adventure-log-timing-fix]]

### StreamingXmlParser 删除 **【07-11 推翻，见当日日志】**

**背景**：2026-07-05 的 narrative flow refactor 设计（`docs/superpowers/specs/2026-07-05-narrative-flow-refactor-design.md`）规划了 `StreamingXmlParser`——基于 `NNN| ` 行号前缀的逐行流式解析器，含状态机（`IN_STORY | IN_BRANCH | IN_CHECKPOINT | IN_CHOICE | POST_BRIDGE`）和预处理/实际处理双重线。该模块于 07-06 实现（commit `39c049d`）。

**07-10 的决策**：删除 `streaming_parser.py`。

**07-10 的理由**：
1. bridge pre-fetch 在后台线程完成完整 API 调用 + `ElementTree` 解析——流式解析的"边收边处理"优势被覆盖
2. 状态机 + 双重处理线（预处理建索引 / 实际处理做决策）的复杂度与 `ElementTree` 全量解析的 millisecond 级耗时不成比例
3. 两套解析器（XmlParser + StreamingXmlParser）需保持语义一致——维护负担 > 理论收益

**07-11 的推翻**：上述分析聚焦在错误的指标上（已完成的 XML 字符串解析耗时 234 μs）。正确指标是从 pre-fetch 启动到**首个可展示内容就绪**的墙上时间——全量解析需等待完整生成（25-50s），流式解析仅需等待首行生成。详见 07-11 日志"StreamingXmlParser 删除决定推翻"。

**教训**：**选择正确的度量指标是架构决策的前提。** 错误的指标（解析耗时）导向了错误的决策（删除流式解析器）。桥接机制的核心度量是"首段可展示时间"，而非"解析吞吐量"。

**依据**：
- [[2026-07-10-adventure-log-and-parser-architecture]]（部分分析被推翻）
- [[2026-07-11-streaming-parser-timing-flaw]]（修正分析）
- `src/storyloom/parser/streaming_parser.py` 已不存在（需从 `7fe2278` 恢复）

### CoCreateFlow.run() 删除

**背景**：`CoCreateFlow.run()` 是遗留的同步方法，内部直接调用 `Display` 进行终端 I/O（`d.output.write()`、`d.show_wait_message()`、`d.get_input()`）。随着 07-07 实现的状态机 API（`start()`/`send()`）和 07-10 的 `dev_cli`，该方法的使命终结。

**具体清理**：
- 删除 `run()` 方法（含内嵌的 `_step1_get_idea()`、`_step2_questioning()` 终端 I/O 调用）
- 删除所有对 `Display` 的直接/间接引用
- `GENERATE_ALL_PROMPT` 模板中的硬编码 UI 提示替换为引擎中立表述
- `_generate_all()` 重构为纯引擎逻辑（无 UI 副作用）

**影响**：commit `a6d941f` — `2 files changed, 268 insertions(+), 566 deletions(-)`（净 -298 行）。CoCreateFlow 现在完全 UI 无关——通过 `UiInterface` 协议和返回 dict 与任意 UI 层交互。

**依据**：
- commit `a6d941f` — `refactor: remove CoCreateFlow.run() and all UI coupling from core engine`
- CLAUDE.md §UI Territory 明确引擎不应依赖 UI 层文件
- [[2026-07-10-ui-logic-separation-audit]]

### Dev CLI 完整实现

**背景**：07-07 将 CLI 降级为测试工具后，`main.py` 成为尴尬的存在——它不再是"主界面"但却是唯一的 CLI 入口。需要一个最小化的 CLI 来：(1) 验证引擎端到端能力，(2) 提供开发者检查（记录原始 Prompt/响应/解析数据），(3) 可作为 Web UI 开发者的引擎行为参考。

**决策**：实现 `src/storyloom/dev_cli/` 包，独立于引擎核心（引擎零修改）。

**架构**：
```
dev_cli/
├── __init__.py      # dev_main() entry point
├── args.py          # 参数解析（--mode normal|dev, --story <file>, --no-save, --lang）
├── ui.py            # TerminalUi（实现 UiInterface）+ 游戏流程驱动 run_co_create()/run_game()
└── observer.py      # DevObserver → dev_output/{prompts,responses,checks}.txt
```

**关键设计决策**：
- **零引擎变更**：通过 `GameLoop._observers`（Python 约定私有属性）注册 DevObserver——引擎代码一行不改
- **追加模式输出**：3 个输出文件始终追加（`dev_output/prompts.txt`、`responses.txt`、`checks.txt`）——跨 session 累积
- **事件驱动消费**：`run_game()` 遍历 stream 事件（token→忽略、segment→print、options→菜单、state→记录、error→stderr、done→循环终止判断）
- **Ctrl+C 安全**：KeyboardInterrupt 在 `ask()` 中传播，在 `run_game()` 中捕获并提示存档

**实现迭代**（17 个 commits，`45ebd25` → `93c6020`）：
- 基础框架：args（`c580177`）、TerminalUi + driver（`6da20aa`）、DevObserver（`864aec2`）
- 体验修复：段间延迟 0.5s（`814e72f`）、流式实时输出（`8df3545`）、等待提示（`b8818b1`）
- 健壮性：错误处理（`e61d845`）、KeyboardInterrupt 传播（`f77f76d`）、事件字段守卫（`735dba1`）
- 完善：共创记录（`c250fd8`）、完整 messages 数组记录（`09f291a`）、速度配置/覆盖模式/暂停（`93c6020`）

**依据**：
- 设计 spec：`docs/superpowers/specs/2026-07-10-dev-cli-design.md`
- 实现计划：`docs/superpowers/plans/2026-07-10-dev-cli.md`

### 系统 Prompt 英文化

**背景**：部分 Prompt 残留中文硬编码，违反 prompt-design.md §1.1 确立的"英文 Prompt"原则（所有系统/叙事 Prompt 使用英文）。具体问题：(1) 冒险日志 Prompt 模板使用中文，(2) 共创 Prompt 中混入中文变量名假设，(3) 格式规范部分有中英混杂。

**决策**：全面清理：
1. 所有系统/叙事 Prompt 切换为英文——角色定义、输出格式、核心规则、质量要求
2. 冒险日志 Prompt 改为英文 + 引擎中立信号（用 `{story_label}`、`{chapter_title}` 占位符替代硬编码中文）
3. 代码注释中的中文替换为英文
4. i18n 层严格仅处理 UI 文本（CLI 输出、菜单、提示）——不触碰 Prompt

**依据**：
- commit `048ab53` — `refactor: purge Chinese from system prompts and format spec, enforce i18n layer separation`
- commit `77314b7` — `refactor: rewrite adventure log prompt in English, use neutral engine signals`
- prompt-design.md §1.1 英文 Prompt 原则

---

## 2026-07-07（周一）

### API 审计与界面集成设计

**背景**：引擎声称 UI 无关，但审计发现 Web UI 开发者需要重新实现大量业务逻辑才能接入——`CoCreateFlow` 的同步 `run()` 方法内嵌终端 I/O、`GameLoop` 的关键数据（checkpoint 历史、大纲节点）仅以私有属性存在、没有统一的会话生命周期管理。

**审计流程**：系统性地对照 "UI 需要做什么" vs. "引擎提供了什么"：

```
[Menu] → [Co-Create] → [Init GameState] → [Narrative Loop] → [Ending] → [Menu]

Phase              Engine Provides               UI Can Use Directly?
─────              ───────────────               ────────────────────
Menu               SaveManager.list_saves()      ✅
                   SaveManager.delete()          ✅
New Game           CoCreateFlow.run()            ❌ (synchronous, embedded UI)
                   GameState(story_config)       ✅
                   GameLoop(...)                 ⚠️ (7 constructor params)
Gameplay           start_round1_stream()         ✅
                   continue_round_stream(key)    ✅
                   get_available_options()       ✅
                   to_save_dict()                ✅
                   round_count, current_node     ✅
                   checkpoint_history            ❌ (private _attribute)
                   outline_nodes                 ❌ (private _attribute)
Ending             type: "ending" event          ✅ (built into stream)
                   adventure_log                 ✅ (in ending event)
Return to Menu     —                             ❌ (no transition mechanism)
```

**决策**：识别 5 个缺口并逐一解决：

| # | 缺口 | 严重度 | 解决方案 |
|---|------|--------|---------|
| 1 | UiInterface 过于极简（3 方法不够语义化） | 🔴 | 保持协议不变，通过状态机 API 返回 dict 弥补——UI 从返回值判断意图 |
| 2 | CoCreateFlow 不可被 Web UI 复用 | 🔴 | 实现 `start()`/`send()` 状态机 API——每个调用返回 `{phase, content}` dict，UI 自由决定如何展示 |
| 3 | 无顶层会话编排器 | 🔴 | 新增 `GameSession` 类——封装"新游戏/加载/保存"完整生命周期 |
| 4 | GameLoop 缺少公开访问器 | 🟡 | 新增 `checkpoint_history`（`list[dict]`）和 `outline_nodes`（`list[dict]`，含格式归一化）属性 |
| 5 | SaveManager 未与 GameLoop 统一 | 🟡 | `GameSession` 封装 `SaveManager`——UI 不需要手动连接二者 |

**关键发现——预存 bug**：`_outline_nodes` 存在两种不可互换的内部格式：
- 新鲜创建路径（`CoCreateParser.parse_outline()`）：`[{id, title, goal, routes: [{condition, target}]}]`
- 从 save 恢复路径：`[{node_id, title, goal, status, branches}]`

公开访问器 `outline_nodes` 需做格式归一化——**这是审计过程中发现的，而非预先知道的 bug。** commit message 中标注了此发现。

**状态机 API 设计**：
```python
flow = CoCreateFlow(api_client, ui=None)  # ui 参数可选——为 Web UI 设计
flow.start()                              # → {phase: "awaiting_idea"}
flow.send("a cyberpunk story")            # → {phase: "awaiting_answer", content: "..."}
flow.send("开始")                          # → {phase: "complete", result: CoCreationResult}
flow.abort()                              # 任意时刻中止
flow.phase                                # 当前阶段（只读）
flow.result                               # CoCreationResult | None（只读）
```

**依据**：
- 设计：`docs/superpowers/specs/2026-07-07-api-audit-and-interface-design.md`（v2 自我审查修正版）
- 计划：`docs/superpowers/plans/2026-07-07-api-interface-implementation.md`
- 实现 commits：
  - `03d992f` — `feat: add CoCreateFlow.start() method`
  - `e3a6750` — `feat: add CoCreateFlow.send() state machine method`
  - `0874cce` — `feat: add CoCreateFlow phase, result properties and abort() method`
  - `67a086e` — `feat: make CoCreateFlow ui parameter optional for state machine API`
  - `2ba92ea` — `feat: add GameSession lifecycle coordinator`
  - `7d08624` — `feat: add GameLoop.checkpoint_history public property`
  - `f8667df` — `feat: add GameLoop.outline_nodes public property with format normalization`

### CLI 降级与观察者统一

**背景**：`main.py` 中的 CLI 原本是"主界面"——直接从终端交互驱动游戏循环。但 Web 界面已成为主要 UI 层（并行分支活跃开发），且 `Display` 类混入了 `GameLoop`——引擎直接调用终端 I/O 方法，违反 UI-引擎解耦原则。

**决策**：
1. **CLI 降级**：`main.py` 从"主界面"变为"测试/维护工具"——保留 `--quick` 模式供开发者快速验证引擎行为
2. **Display 移除**：`GameLoop` 不再持有 `Display` 引用。所有内容输出改为 generator yield 事件流——`token`、`segment`、`options`、`state`、`error`、`done`
3. **观察者统一**：`cli_utils.py` 集成 observer 回调注册——供 `dev_cli` 和 `main.py` 共享

**事件流设计**（此设计为 07-10 Dev CLI 的基础）：

| type | payload | 说明 |
|------|---------|------|
| `token` | `{"text": str}` | LLM 逐 token（供 Web UI 流式渲染） |
| `segment` | `{"text": str, "n": int, "position": "pre"\|"post", "branch": str\|null}` | 叙事段完成 |
| `options` | `{"choices": [{"id": str, "branches": [str], "labels": [str], "conditions": {}}]}` | 选项面板 |
| `state` | `{"vars": dict, "changes": [{"var": str, "op": str, "val": str, "accepted": bool}]}` | 状态变更 |
| `error` | `{"message": str}` | 格式/API 错误 |
| `done` | `{"round": int, "node": str\|null, "state": dict}` | 轮次结束 |

**依据**：
- commit `2127350` — `refactor: demote CLI to test-only harness, unify observer system`
- commit `6697f47` — `refactor: remove dead code and mark deprecated files`
- [[2026-07-07-cli-observer-refactor]]

### 3 个 P0 引擎 Bug 修复

**背景**：代码审查发现条件变量解析逻辑存在优先级不一致——不同求值场景使用不同的解析顺序，导致同一条件在不同上下文中得出不同结果。

**Bug 1 — 条件变量解析优先级不一致**：
- 问题：`choice_dict > state_vars` 优先级在 options 置灰判断中遵循此顺序，但在 `set` 条件求值和 `route` 条件求值中使用相反顺序
- 根因：三处条件求值是独立实现的代码路径，没有共享的求值函数
- 修复：抽取共享的 `_evaluate_condition()` 方法，统一优先级为 `choice_dict > state_vars`（与 block-spec.md §3 一致）
- 影响：未修复时，`<set if="approach==1">` 在 choice_dict 已包含 `approach` 时可能错误地回退到 state_vars 查找

**Bug 2 — number 越界未 clamp**：
- 问题：`<set var="体力" op="-" val="100"/>` 结果可能为负数（如当前 30 → -70）
- 根因：`_apply_number_op()` 执行算术但没有边界检查
- 修复：所有 number 操作结果 clamp 到 [0, 100]（与 block-spec.md §5 一致）
- 影响：未修复时，LLM 可能在后续轮次中基于负数状态做出不合理叙事决策

**Bug 3 — route 兜底策略缺失**：
- 问题：checkpoint 的所有分支条件都不命中时，`target_node` 保持为 `None`——程序不知道该推进到哪个节点
- 根因：仅实现了"命中则设置 target"的逻辑，没有 else 分支
- 修复：取第一条 route 的 target 作为兜底（与 data-model.md §2 兜底策略一致——"取 LLM 列出的第一个分支"）
- 影响：未修复时，条件不命中会导致大纲推进卡死

**依据**：
- commit `6533e10` — `fix: condition priority, number clamp, route fallback — 3 core engine bugs`
- block-spec.md §3 条件变量解析优先级 + §5 状态变更校验
- data-model.md §2 兜底策略说明
- [[2026-07-07-audit-and-bugfix]]

### 规范文档 NNN| 格式同步

**背景**：代码于 07-05 迁移到 `NNN| ` 行号前缀格式（commit `ce5a776`），但规范文档（block-spec.md、prompt-design.md、data-model.md）仍使用旧的 `<seg n="N">` 属性编号描述——文档与代码不一致。

**修复范围（8 处）**：
1. block-spec.md §1 速查表：`<seg>` 的 `n` 属性描述改为"可选（兼容旧格式）"
2. block-spec.md §2：新增完整的行号规则节（`NNN| ` 前缀、零填充 3 位、全局连续）
3. block-spec.md §2.3：`XmlParser` 解析流程更新为剥离前缀 + 兼容 `n` 属性
4. prompt-design.md §4.2：Round 1 Prompt 模板中 `<seg N>` 替换为 `NNN| <seg>`
5. prompt-design.md §4.3：Round N 上下文描述更新
6. data-model.md §A.4：新增 `LINES_PER_ROUND_*` 行控制常量 + 架构说明
7. data-model.md §A.7：废弃 `SEGMENTS_PER_ROUND_*`、`BRIDGE_SEGMENT_RATIO`、`MIN_NARRATION_CHARS`
8. exec-flow.md §4.4：解析流程更新为行号剥离描述

**依据**：
- commit `f283d24` — `docs: sync spec format to NNN| line-number prefix, fix 8 issues`
- [[2026-07-07-doc-audit-and-format-sync]]

---

## 2026-07-16（周四）

### API 配置去品牌化：DEEPSEEK_* → LLM_*

**背景**：`api_client.py` 和 `.env.example` 中的环境变量名为 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`，将配置绑定到了特定提供方。但 `ApiClient` 使用的是 OpenAI 兼容的 `/v1/chat/completions` 接口，DeepSeek、OpenAI、Groq、Ollama、vLLM 等数十个提供方均支持此协议。变量名中的 "DEEPSEEK" 前缀：(1) 误导用户以为仅支持 DeepSeek；(2) 切换到其他兼容提供方时变量名与实际用途不一致。

**决策**：统一重命名为 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`——去品牌化、通用化。不做向后兼容 fallback（`.env` 文件修改变量名即可，无迁移成本）。

**变更范围**：
- `src/storyloom/io/api_client.py`：env var 读取 + 错误消息
- `.env.example`：模板变量名 + 添加多提供方说明注释
- `tests/prompt_lab/run_prompt_test.py`：env var 读取
- `docs/spec/data-model.md` §A.6：`DEEPSEEK_MODEL` → `LLM_MODEL`
- `docs/spec/exec-flow.md` §1：`STORYLOOM_API_KEY` → `LLM_API_KEY`

**依据**：用户决策——统一全局变量优于按提供方分变量；OpenAI-compatible API 的行业标准地位意味着单组变量覆盖所有提供方。

---

## 2026-07-06（周日）

### 后端完备化：存档、结局、解耦

**背景**：引擎核心缺失三个关键能力——(1) 存档系统仅存设计文档（exec-flow.md §2、data-model.md §3），(2) 结局检测和冒险日志未实现，(3) `CoCreateFlow` 直接 `import Display` 并调用终端 I/O 方法，Web UI 无法复用。这三个缺口阻塞了 Web 界面集成和端到端测试。

**设计方法**：以 4 份权威 spec 文档为标准（exec-flow.md、block-spec.md、data-model.md、prompt-design.md），代码适配文档——**spec 是权威，代码是派生。** 采用最小变更策略——只在现有模块上添加新方法/属性，不重构核心流程。

**实现（11 项任务）**：

**任务 1-2：UiInterface 协议 + CoCreateFlow 去耦合**
- 新建 `src/storyloom/core/ui_interface.py`：极简 3 方法协议——`write(text)`、`show_error(text)`、`ask(prompt) → str`
- `Display` 实现 `UiInterface`：`write()` 委托到 `self.output.write()`，`ask()` 委托到 `self.get_input()`
- `CoCreateFlow` 构造函数从 `display: Display` 改为 `ui: UiInterface`——所有 `self._display.output.write(...)` → `self._ui.write(...)`，共替换约 20 处
- 影响范围：仅 CoCreateFlow 和 Display 两个模块——不涉及 GameLoop

**任务 3-4：GameState/GameLoop 序列化**
- `GameState.to_dict()` → `{state_vars: dict}`（仅序列化变量状态）
- `GameState.from_dict(data, story_config)` → 用 story_config 提供的变量定义类型信息恢复 state_vars
- `GameLoop.to_save_dict()` → 组装完整的存档 dict（version、metadata、config、story_config、state_vars、outline、progress、bridge_text）
- `GameLoop.from_save_dict(data, api_client)` → 校验结构完整性 → 恢复 GameLoop 实例
- **关键设计**：`story_config.variables[].initial` 是**共创时的初始值**（非当前值），用于提供类型定义。实际状态来自 `state_vars`

**任务 5-6：存档系统（SaveManager）**
- 新建 `src/storyloom/core/save_manager.py`
- `save(save_data)`：序列化 → 写 `saves/{label}.tmp` → `os.replace(tmp, saves/{label}.json)`（原子写入，data-model.md §3.3）
- `load(label)`：JSON 解析 → 校验 version==1 → 校验关键字段（story_config 含 variables、state_vars、outline、progress）→ 校验 current_node 在 outline 中存在 → 返回 save_data dict
- `list_saves()`：扫描 `saves/*.json`，读取每个文件的 metadata（label、round_count、created_at、updated_at、current_node）
- `delete(label)`：删除 `saves/{label}.json`
- 加载校验失败 → `ValueError`（调用者删除损坏文件，提示用户返回主菜单）
- **前置依赖**：新增 `story_config.label` 字段——commit `926bc8e`。存档文件名从 label 派生（非法字符替换为 `_`，重名追加 `_2`/`_3`）

**任务 7-8：结局检测 + 冒险日志**
- `ending_flag`：GameLoop 新增属性（非 GameState——GameState 管理变量，ending_flag 是流程控制）
- 检测流程：`parsed.checkpoint_node == "end"` → `ending_flag = True` → 标记节点 completed → 存储 checkpoint 摘要/历史/快照 → 触发 auto-save → bridge 处组装冒险日志 Prompt → 独立 LLM 调用
- `build_adventure_log_prompt()`：注入 story_config + state_vars + checkpoint_summaries + checkpoint_history。Markdown 格式，500-1000 字，面向玩家回顾性口吻
- 冒险日志不走叙事循环解析管线——独立 `api_client.chat()` 调用（非流式）
- 新增流事件类型 `ending`：`{type: "ending", adventure_log: str, final_state: dict, summary: str|null}`

**任务 9-10：checkpoint 累积 + outline 结构化存储**
- 新增字段：`_checkpoint_summaries: list[str]`、`_checkpoint_history: list[dict]`、`_checkpoint_snapshots: dict[str, dict]`
- `_outline_nodes: list[dict]`：从 `CoCreateParser.parse_outline()` 获取结构化节点（替代仅存 `outline_text: str`）
- checkpoint snapshot 在 Phase 1 仅存储不读取——为 Phase 2 回档预留

**任务 11：Web 前端 MVP（并行分支）**
- FastAPI + SSE 流式渲染、共创支持、streaming parser 集成
- commit `3035496` — `feat: streaming web frontend with co-creation support`

**全部 commits**：`c18fb71`（SaveManager）、`acfd7c9`（UiInterface）、`4313b6e`（CoCreateFlow 解耦）、`6646a60`/`50a5057`（序列化）、`9f67ac6`（结局）、`06b49ba`（冒险日志）、`8e89d15`（checkpoint 累积）、`e139831`（outline 结构化）、`926bc8e`（label 字段）、`a9bd880`（存档时间戳/结局节点修复）、`65db872`（存档恢复 bridge_text 注入）

**依据**：
- 设计：`docs/superpowers/specs/2026-07-06-backend-completion-design.md`（经自我审查修订——v2 移除不必要的 UiInterface 扩展）
- 计划：`docs/superpowers/plans/2026-07-06-backend-completion.md`（11 任务，TDD）

### Narrative Flow 重构

**背景**：对 `xml_parser.py` 和 `game_loop.py` 的叙事流程进行系统性审视，发现 5 个问题。

**5 个问题及修复**：

1. **bridge_text 未按 current_branch 过滤**（P0）：
   - `XmlParser._extract_bridge_text()` 提取所有 `<branch>` 内的文本节点——未选中分支的文本泄露到下一轮上下文
   - 修复：`_extract_bridge_text(post_children, current_branch=None)`——bare `<seg>`（无分支 = 单路径）始终收集；`<branch name="X">` 仅在 `X == current_branch` 时收集
   - 统一逻辑：不再有"全量模式"和"分支模式"的区分——"默认就是一种分支"

2. **全量解析违背顺序处理原则**：
   - `ElementTree.fromstring()` 一次性解析完整 XML，然后批量处理所有元素
   - 设计文档（narrative-flow-refactor-design.md §2.1-2.2）规划了缓冲式读取——pre-bridge 交互区在 bridge 前处理，bridge 后内容作为缓冲
   - 修复：实现 `StreamingXmlParser`（见下条）（**该模块在 07-10 删除、07-11 恢复——见当日日志**）

3. **`run_full_test.py` 重写了全部生产逻辑**：
   - 手工状态管理、route 评估、choice_dict 构建——这些应该由 GameLoop 完成
   - 修复：全量重写为 GameLoop 驱动——脚本仅做配置 + observer 回调 + 选择策略

4. **无观察者机制**：
   - 测试/发布模式无法区分——每轮数据无法导出供调试
   - 修复：新增 `RoundRecord` dataclass + `observer: Callable[[RoundRecord], None] | None` 回调。每轮结束时调用 `_notify(record)`

5. **`format_error` 从未被赋值**（P0）：
   - `GameLoop._format_error` 声明了但没有任何代码设置它——XML 解析错误不会反馈给 LLM
   - 修复：流式解析异常时设置 `self._format_error`，`PromptBuilder.build_round_n()` 在下一轮注入纠正提示："上一轮输出存在格式问题——{format_error}。请严格遵循 XML 格式规范。"

**额外变更**：
- `ApiClient.stream_chat()` 返回类型从 `str` 改为 `ApiResult`（`{content, ttft, tokens}`）——记录首 token 时间和 token 用量
- 包结构拆分：`src/storyloom/` 扁平结构 → `core/` / `io/` / `parser/` 三个子包（commit `7fe2278`）

**依据**：
- 设计：`docs/superpowers/specs/2026-07-05-narrative-flow-refactor-design.md`
- commit `39c049d` — `refactor: narrative flow — branch-aware bridge_text, observer pattern, streaming parser`
- commit `7fe2278` — `refactor: split flat package into core/io/parser subpackages`

### 国际化迁移：Display.UI → gettext

**背景**：`Display.UI` dict 存储中英文 UI 文本（`{"zh-CN": "...", "en": "..."}`）。翻译者需要编辑 Python 字典——工作流不友好（无法使用标准翻译工具、无法增量更新、无法审查 diff）。

**决策**：迁移到 gettext `.po/.mo` 文件体系，使用标准 Python `gettext` 模块。

**迁移步骤**：
1. 新建 `src/storyloom/i18n.py`：封装 `gettext.translation()`，提供 `_()` 快捷函数
2. 创建 `locale/zh_CN/LC_MESSAGES/storyloom.po`：从 `Display.UI` dict 提取所有 UI 文本作为 msgid
3. 编译 → `locale/zh_CN/LC_MESSAGES/storyloom.mo`
4. `Display.t("key")` → `_("English text")`：所有 UI 文本调用替换
5. `main.py` 删除 `language` 参数传递——语言由 `LANG` 环境变量或系统 locale 决定
6. `co_create.py` 中的中文硬编码 → `_()` 调用
7. 移除 `Display.UI` dict 和 `Display.t()` 方法

**设计原则**：i18n 层严格仅处理 UI 文本（CLI 输出、菜单、提示）——不触碰 Prompt。Prompt 语言由 prompt-design.md 控制（英文 Prompt 原则）。

**依据**：
- 设计：`docs/superpowers/specs/2026-07-06-i18n-gettext-design.md`
- 计划：`docs/superpowers/plans/2026-07-06-i18n-gettext-migration.md`
- commits：`7b298ab`（i18n 模块）、`80bd632`（zh-CN 翻译）、`38460ef`/`59907e9`（迁移）、`14c57b8`（Windows 兼容）、`f052614`（测试更新）
- [[i18n-migration-follow-up]]

### 包结构重构

**背景**：原 `src/storyloom/` 是扁平结构——所有 `.py` 文件直接放在包根目录。随着模块数增长（game_loop.py、co_create.py、context_manager.py、prompt_builder.py、config.py、xml_parser.py、api_client.py、display.py、main.py、cli_utils.py...），扁平结构变得难以导航和维护。

**决策**：拆分为 3 个子包：
```
src/storyloom/
├── __init__.py         # 顶层导出（GameSession, CoCreationResult）
├── config.py           # 常量（不变）
├── i18n.py             # gettext 封装
├── cli_utils.py        # CLI 观察者工具
├── main.py             # CLI 入口
├── core/               # 引擎核心
│   ├── game_loop.py
│   ├── co_create.py
│   ├── context_manager.py
│   ├── prompt_builder.py
│   ├── save_manager.py
│   ├── session.py
│   └── ui_interface.py
├── io/                 # I/O 层
│   ├── api_client.py
│   └── display.py
└── parser/             # 解析器
    └── xml_parser.py
```

**原则**：`core/` 不导入 `io/` 或外部模块（仅标准库 + 自身子模块）；`io/` 可导入 `core/` 的协议；`parser/` 纯解析逻辑，零外部依赖。

**依据**：
- commit `7fe2278` — `refactor: split flat package into core/io/parser subpackages`
- CLAUDE.md 文件管辖表格反映此结构（引擎核心 / 引擎 API / UI 领地）

---

## 2026-07-05（周六）

### 行号格式迁移（NNN| 前缀）

**背景**：`<seg n="N">` 属性编号方案是两个问题之间的妥协——(1) LLM 需要知道每段的序号以便感知"写到哪了"，(2) 程序需要为段排序。将编号放在 XML 属性中意味着 LLM 在生成 `<seg n="42">text</seg>` 时需要同时维护：(a) XML 标签语法正确，(b) n 属性值在变化，(c) 文本内容符合规范。认知负担高。

**替代方案**：将编号从 XML 属性中剥离，改为行前缀——`NNN| <seg>text</seg>`。行号不是 XML 的一部分，程序解析前剥离。LLM 只需维护一个递增计数器（写一行 → 前缀数字 +1），不干扰 XML 结构认知。

**新格式规范**：
- 每行以 `NNN| ` 前缀开头（零填充 3 位），从 001 开始，全局连续递增
- 行号不是 XML 的一部分——程序在 `XmlParser` 解析前用正则 `r'^\d{3}\| '` 剥离
- 段数 → 行数：`LINES_PER_ROUND_MIN = 150`、`LINES_PER_ROUND_MAX = 300`（行数 ≈ 段数 × 1.25，含 XML tag + 行号前缀开销）

**连锁变更**：
| 变更 | 说明 |
|------|------|
| `SEGMENTS_PER_ROUND_*` → `LINES_PER_ROUND_*` | 段数控制改为行数控制 |
| `<seg n="N">` → 裸 `<seg>` | n 属性不再由 Prompt 要求产生 |
| 解析器兼容旧格式 | `int(el.get("n", 0))`——n 缺失时默认 0 |
| 宽容原则确立 | 编号偏差（跳号、重复、非 001 起始）不触发重试——内容质量优先于编号准确性 |

**行号的价值**（超越格式美化）：
- LLM 在生成过程中**自我计量**——替代不准确的字数估算和段数计数
- 程序端解析前剥离前缀——对展示层和 XML 解析器透明
- 流式逐行解析成为天然可能——每行是自包含的独立处理单元
- `tests/prompt_lab/data/prompts/round1-linenum.txt` 成为权威 Prompt 标准（9758 字节）

**依据**：
- commit `8023859` — `feat: add line-numbered prompt (round1-linenum.txt) — 3-digit zero-padded, 150-300 lines`
- commit `ce5a776` — `feat: migrate to English line-numbered prompt format`
- data-model.md §A.4（当前常量）+ §A.7（废弃常量列表）
- block-spec.md §2（行号规范）

### 段长-TTFT 实验

**背景**：Bridge 机制的无缝约束是 `TTFT < N × RATE × t`（RATE=阅读速度比例, t=每段阅读时间）。当 `SEGMENTS_PER_ROUND = 60-120`、bridge 在 40% 处时，post-bridge 缓冲仅有 24-48 段。RATE=50%、t=0.5s/段 → 缓冲阅读时间 6-12s。但 TTFT 实测平均 48-60s。**约束不成立——用户在每轮之间必然感知停顿。**

**假设**：TTFT 由"思考时间"（Prompt 解析、格式规划、内容结构化）主导，而非输出长度。如果假设成立，可以大幅增加段数而不成比例增加 TTFT——用更长的 post-bridge 缓冲覆盖 TTFT 窗口。

**实验设计**（Phase 1：段数测试，Phase 2：RATE 测试）：
- 4 个段数档位（T1: 60-120, T2: 120-200, T3: 180-280, T4: 240-360），每档 3 次运行
- 固定 RATE = 50%、bridge 位置 = 对应档位中心
- 测量指标：TTFT（avg/min/max）、实际段数、bridge 位置比例、XML 正确性（8 项检查）
- 工具链：`generate_prompt.py`（模板渲染）→ `run_prompt_test.py`（串行流式测试）→ `analyze_seg_test.py`（结果聚合）

**Phase 1 结果**：

| 档位 | 段数范围 | 平均 TTFT | 平均段数 | Bridge 位置 | 正确率 |
|------|---------|-----------|---------|------------|--------|
| T1（对照） | 60-120 | ~48s | 84 | ~40% | 2/3 |
| T2 | 120-200 | ~52s | 156 | ~55% | 3/3 |
| T3 | 180-280 | ~56s | 218 | ~62% | 2/3 |
| T4 | 240-360 | ~58s | 285 | ~70% | 1/3 |

**关键发现**：
- 假设**部分成立**——段数增加 3×（T1→T4），TTFT 仅增加 ~20%，远非线性
- 但 T4 的正确率明显下降——LLM 在超长输出时更难维持格式正确性
- **最优范围：T2（120-200 段）**——正确率最高（3/3），TTFT 可控（~52s），缓冲文本充足
- 最优 token 预算：**12,288 tokens**
- **关键因素确认**：Prompt 大小（输入 tokens）对 TTFT 的影响 > 输出长度

**Phase 2（RATE 测试）**：在 120-200 段下测试 RATE ∈ {60%, 75%}——进一步优化 bridge 位置。

**结论**：推荐配置 `SEGMENTS_PER_ROUND 120-200`、`BRIDGE_POSITION_RATIO = 0.75`、`MAX_TOKENS = 12288`。07-05 立即应用到生产配置（commit `fb73c9d`）。

**依据**：
- 设计：`docs/superpowers/specs/2026-07-05-segment-length-test-design.md`
- 计划：`docs/superpowers/plans/2026-07-05-segment-length-test.md`
- 实验数据 commits：`fb73c9d`（配置应用）、`867d16e`（Phase 2 RATE 结果）、`af1b6df`（4 档完整结果）
- [[segment-length-ttft-optimization]]

### Bridge 位置：40% → 75%

**背景**：段长实验发现 bridge 位置是决定无缝体验的关键参数。原 `BRIDGE_SEGMENT_RATIO = 0.4`（约 07-04 初设），post-bridge 缓冲文本太短。当 `LINES_PER_ROUND = 150-300` 时，40% 意味着 post-bridge 仅 60-120 行缓冲——对应 15-30s 阅读时间（RATE=50%）。但 TTFT 平均 48-60s——缓冲播完时下一轮首段大概率未到。

**决策**：
- `BRIDGE_SEGMENT_RATIO` → `BRIDGE_POSITION_RATIO`（重命名，语义更清晰：这是比例位置，不是段数比例）
- 值：0.4 → 0.75（经 Phase 1+2 实验验证）
- 新增 `MIN_TAIL_LINES = 25`：bridge 后每个 `<branch>` 的最少行数——确保分支叙事有足够缓冲

**为什么 0.75 更好**：
- 150 行总输出 → bridge 在 ~113 行，post-bridge ~37 行（~9s 阅读时间）——仍短但比 0.4 的 ~15s 有明显改善
- 300 行总输出 → bridge 在 ~225 行，post-bridge ~75 行（~19s 阅读时间）——显著改善
- 与 TTFT 对比：TTFT 10-30s（优化后 Prompt）vs post-bridge 阅读 9-19s——仍有 gap，但已缩小到可接受范围
- 配合 bridge pre-fetch（07-10 实现）可进一步缩小 gap

**依据**：
- commit `aa2b8fe` — `fix: bump post-bridge branch minimum to 25 lines (accounts for XML wrapper overhead)`
- commit `fb73c9d` — `feat: apply optimal segment-length config (120-200, bridge 75%, max_tokens 12288)`
- data-model.md §A.4（当前常量 0.75）+ §A.7（废弃常量 0.4）
- Phase 1+2 实验数据

### 变量上限收紧：5-8 → ≤3

**背景**：07-04 的变量系统重构（LLM 自定义变量）建议 5-8 个变量。但随着变量数增加：(1) 每轮更多 `<set>` 操作 → 更多校验失败 → 更多 rejected_changes，(2) 更多条件路由 → LLM 更难维持一致性，(3) 更多 state_vars 注入 Prompt → 更长的输入 → 更高的 TTFT。

**决策**：
- 硬上限：≤3 总计（≤2 number + ≤1 string/list）
- 新增常量：`VARIABLE_CAP = 3`、`VARIABLE_NUMERIC_CAP = 2`、`VARIABLE_LABEL_CAP = 1`
- **种子参考表**注入变量生成 Prompt——题材 → 推荐变量，LLM 可采纳/调整/替换：
  ```
  Romance → affection
  Mystery → clues_progress
  Cyberpunk → implant_integrity
  Wuxia → inner_power
  Horror → sanity
  ```
- **设计原则**："如果一个变量从不触发分支或选项，它就是噪音。优先使用单个核心数值变量。"

**影响分析**：
- 更少的 `<set>` 操作 → 更少的校验拒绝 → 更低的错误反馈频率
- 种子表仅 ~200 chars——可忽略的 Prompt 预算
- `story_config.variables` 格式不变——向后兼容
- 程序侧新增校验规则：`variables.count ≤ 3`、`number.count ≤ 2`、`string/list.count ≤ 1`

**依据**：
- `docs/superpowers/specs/2026-07-05-variable-cap-design.md`
- commit `1dadd60` — `feat: add co-creation config constants (MAX_RETRIES, variable caps, outline ranges)`
- `src/storyloom/config.py` 中 `VARIABLE_CAP = 3`、`VARIABLE_NUMERIC_CAP = 2`、`VARIABLE_LABEL_CAP = 1`

### 共创阶段实现（CoCreateFlow）

**背景**：叙事循环已迭代 6+ 轮——XML 格式（07-04）、对话式架构（07-04）、Prompt v4（07-04）——但共创阶段代码为零。`main.py` 用 `DEFAULT_STORY_CONFIG` 和 `SAMPLE_OUTLINE` 硬编码绕过整个共创流程。每次端到端测试都必须手动编辑 Python 源码。

**设计空间探索**：

**关键决策 1 —— 三步合一（单次 API 调用）**：
- **原方案**：3 次独立 API 调用——story_config → variables → outline
- **新方案**：单次调用生成全部三个区块（`=== story_config ===` / `=== variables ===` / `=== outline ===`）
- **理由**：
  - 延迟：1 次调用替代 3 次 → 用户等待时间降低 2/3（共创阶段静默等待期间无用户交互）
  - 信息完整性：LLM 在单次生成上下文中设计变量和大纲——知道完整 story_config 时能做出更一致的设计
  - INI 风格分隔符（`=== xxx ===`）经叙事 Prompt 测试验证稳定——比 JSON/YAML 对 LLM 更友好
- **权衡**：单次调用失去中间校验——如果 story_config 正确但 variables 校验失败，需整体重试（而非仅重试 variables）。缓解措施：`_generate_all()` 内置 `MAX_RETRIES=2` 自动重试，解析失败时附带具体错误提示

> spec 文档（exec-flow.md §3）保留 Step 3/3.5/4 的逻辑分步——为概念清晰，不代表 3 次独立 API 调用。

**关键决策 2 —— 静态全上下文窗口**：
- 共创阶段 ~6-12 条消息（system + Q&A 对话 + 生成请求 + 生成响应）
- 无需滑动窗口和压缩——消息量远低于叙事循环（~20+ 轮）
- system prompt 在 `CoCreateFlow.__init__()` 中一次性设置，始终作为 messages[0]

**关键决策 3 —— CoCreateParser 作为无状态工具类**：
- 所有解析/校验方法为 `@staticmethod`——纯函数，无副作用
- `split_blocks(text) → {story_config, variables, outline}`：按 `=== xxx ===` 分割
- `parse_story_config(text) → dict`：逐行 `key: value` 解析
- `parse_variables(text) → list[dict]`：逐行 `name: type, 初始 value` 解析
- `validate_variables(variables) → list[str]`：返回错误消息列表（空 = 通过）
- `parse_outline(text) → list[dict]`：`[node]` 块解析为 `[{id, title, goal, routes}]`
- `validate_outline(nodes, var_names) → list[str]`：静态校验（route target 存在、变量引用合法、最后节点无分支）

**关键决策 4 —— 重试策略**：
- API 调用失败：静默重试最多 3 次（`_api_attempt` 循环），耗尽后抛 `CoCreationAborted`
- 解析/校验失败：附带纠正消息追加到对话历史，重试最多 `MAX_RETRIES`（2）次
- 全部耗尽 → `CoCreationAborted` → 调用者（UI 层）告知用户并询问（重试 / 返回主菜单）
- 变量校验失败 → 生成带有具体错误的纠正消息（如 "Previous variables had errors: 变量名重复: 体力"）

**实现（12 任务）**：
- 配置常量：`MAX_RETRIES`、`VARIABLE_CAP`、`VARIABLE_NUMERIC_CAP`、`VARIABLE_LABEL_CAP`、`OUTLINE_NODE_RANGES`（commit `1dadd60`）
- CoCreateParser：`split_blocks`（`71bb3b6`）→ 各 `parse_*` / `validate_*`（`2a7a9ba`）
- CoCreateFlow：step1（获取想法）+ step2（Q&A 循环）+ step3（生成 + 重试）（`4e24d7a`）
- 集成：集成到 `main.py` + 安全限制（`c70f085`）、无界循环修复（`3b37e84`）
- Prompt 模板：`CO_CREATE_SYSTEM_PROMPT` + `GENERATE_ALL_PROMPT`（`2a7a9ba`）

**依据**：
- 设计：`docs/superpowers/specs/2026-07-05-co-creation-implementation-design.md`
- 计划：`docs/superpowers/plans/2026-07-05-co-creation-implementation.md`（12 任务，TDD）
- 单次调用验证：`_generate_all()` 使用 `self._api.chat(self._messages)` 单次调用 → `CoCreateParser.split_blocks(response)` 拆分为三区块 → 逐区块解析校验

### 叙事流程 5 缺陷修复

**背景**：对话式架构（07-04）的初始实现存在 5 个流程缺陷，影响叙事连贯性和上下文正确性。

**5 个缺陷及修复**：

1. **`completed_nodes` 独立维护 vs. 派生**：原实现独立维护 `completed_nodes` 列表，与 `outline_nodes[].status` 不同步。修复：从 `status == "completed"` 派生。

2. **压缩摘要未注入 Round N 消息**：`ContextManager` 构建了压缩消息对，但 `PromptBuilder.build_round_n()` 未将其注入。修复：在 build_round_n 中添加 `compressed_summaries` 参数。

3. **选项标签显示错误**：选项展示时使用了内部 branch 名而非 opt 文本。修复：正确映射 opt key → label。

4. **当前节点信息未注入 Prompt**：`current_node` 和 `goal` 在 Round N 消息中缺失。修复：添加 "当前节点：{node} — {goal}" 节。

5. **结局检测逻辑错误**：`ending_flag` 设置后未在 bridge 处正确触发。修复：bridge 处理中添加 `if self.ending_flag: ...` 分支。

**依据**：
- commit `88f489e` — `fix: 5叙事流程缺陷修复 — completed_nodes/压缩摘要/选项标签/节点注入/结局检测`

---

## 2026-07-04（周五）

### XML 格式替换文本块（frame-v1）

**背景**：初版使用 `--- block ---` 文本分隔符（`--- narrative:main ---`、`--- options:main ---`、`--- state ---`、`--- checkpoint ---`、`--- bridge ---`）。经多轮测试暴露系统性 LLM 行为缺陷：

| 问题 | 发生率 | 根因分析 |
|------|--------|---------|
| node ID 后缀拼接 | ~80% | `ch2_confrontation` → `ch2_confrontation_end`。LLM 将 ID 视为"可润色的文本"，而非"必须原样保持的标识符" |
| 分支叙事缺失 | ~60% | `:branch_a` 后缀依赖命名约定——LLM 不将其视为结构约束，容易遗漏 |
| 双重 bridge | ~30% | `--- bridge ---` 被 LLM 误认为"场景转换标记"——在 narrative 段落中重复使用 |
| 模糊解析 | 20-74% 正确率 | 正则匹配 `--- xxx ---` 边界——空白、缩进、变体等边界情况多 |

**核心洞察**：LLM 将自定义文本块语法视为"外语"——每轮从 Prompt 文本中重新学习。XML 是 LLM 的"母语"——预训练数据中无处不在的结构化格式。

**决策**：采用 XML 格式。LLM 输出 `<story>` 根元素包裹的 XML 文档，内含 6 种子元素：
- `<seg>`：叙事段（旁白或对话）
- `<choice id="...">`：选项列表，内含 `<opt key="N" branch="...">`
- `<set var="..." op="..." val="...">`：状态变更
- `<checkpoint node="..." summary="...">`：大纲节点记录
- `<bridge/>`：自闭合桥接标记
- `<branch name="...">`：分支叙事容器

**首次测试**（frame-v1 Prompt，DeepSeek v4-pro）：

| 指标 | 结果 | 说明 |
|------|------|------|
| 正确率 | **3/3 (100%)** | 对比文本块 20-74% |
| TTFT | 12.6s ~ 80.3s | Run 1 冷启动（80.3s），Run 2-3 热缓存（12.6s, 19.8s） |
| 无缝率 | 1/3 | 仅 Run 2（TTFT 12.6s, tail 15s）满足无缝约束 |
| 段数 | 74, 101, 75 | 均在 60-120 范围内 |

**为什么 XML 解决了文本块的问题**：

| 文本块问题 | XML 方案 | 机制 |
|-----------|---------|------|
| node ID 后缀拼接 | `node="ch2_confrontation"` | 属性值——LLM 倾向于保持 XML 属性值原样（"数据"认知） |
| 分支叙事缺失 | `<branch name="x">...</branch>` | 容器结构——闭标签强制完整性 |
| 双重 bridge | `<bridge/>` | 唯一自闭合标签——语义上不可能有两个 bridge |
| 模糊解析 | `xml.etree.ElementTree` | 二值正确性——XML 要么合法要么不合法，无模糊地带 |

**关键设计规则**（经用户反馈修正）：
- `<branch>` 允许在 bridge 之前——用于段内小分支（合并回主线，不影响大纲）
- bridge 之后：裸 `<seg>` 用于单路径场景；`<branch>` 容器用于多路径场景
- bridge 之后严格禁止 `<choice>`、`<set>`、`<checkpoint>`——仅允许叙事元素
- `&` 必须转义为 `&amp;`（XML 标准要求，非 Prompt 特有）

**依据**：
- [[xml-format-decision]] — 设计决策、测试结果（3/3 100% 正确率、TTFT 12.6-80.3s）
- `docs/superpowers/specs/2026-07-04-conversation-prompt-design.md`
- block-spec.md §1（XML 元素速查表 + 完整结构示例）
- prompt-design.md §4.2（Round 1 模板含 XML 格式示例）

### Prompt v4 模板：6 轮迭代与 7 条原则

**背景**：XML 格式确定后，Prompt 质量成为核心瓶颈。默认 Prompt（3329 chars）在 5 次测试中正确率仅 ~33%，TTFT 平均 56s（比 XML frame-v1 的 ~12s 慢 4.7×）。

**测试基础设施修复**（迭代前）：
- 并行 → 串行：发现并行测试导致 TTFT 翻倍（服务端排队），改为 `stream=True` + 串行执行
- 正确性自动化：`analyze_results.py` 支持一键运行 8 项正确性检查 + 时序分析

**迭代历程**（default → v2-lean → v2 → v2-final → v2-detailed → v3 → v4）：

| 版本 | 关键变更 | 正确率 | TTFT |
|------|---------|--------|------|
| default | 初始 Prompt | 33% (1/3) | 56s |
| v2-lean | 精简冗余描述 | 33% (1/3) | ~50s |
| v2 | 添加反例约束（checkpoint 后缀示例） | 67% (2/3) | ~45s |
| v2-final | 正反双重覆盖（:main 分支） | 67% (2/3) | ~40s |
| v3 | 注意力标签 + 段数/bridge 量化 | 83% (5/6) | ~18s |
| v4 | 示例-规则屏障 + 规则精简 | **83% (5/6)** | **11s** |

**量化成果（default vs v4）**：

| 指标 | default | v4 | 改善 |
|------|---------|-----|------|
| System Prompt 大小 | 3329 chars | 3280 chars | -1.5% |
| TTFT 平均 | 38s | 11s | **3.5×** |
| 正确率 | 33% (1/3) | 83% (5/6) | **2.5×** |
| 无缝率 | 33% (1/3) | 83% (5/6) | **2.5×** |
| choice 缺失 | 偶发 | 0 | 消除 |
| pre-bridge 分支错误 | 偶发 | 0 | 消除 |
| checkpoint node 虚构 | 67% | 0 | 消除 |

**七条约束有效性原则**（通用，不限于特定题材或模型）：

| # | 原则 | 说明 | 效果验证 |
|---|------|------|---------|
| 1 | **反例约束** | 对每个关键约束给出具体的错误案例。如"禁止 `ch2_confrontation_resolved`（拼接后缀）" | checkpoint 正确率 33%→100% |
| 2 | **正反双重覆盖** | 关键约束在正面规则和负面禁止中各出现一次。单次提及漏看率 ~30%，双重 ~0% | pre-bridge 分支错误消除 |
| 3 | **注意力标签** | `（重要）` 标记最易出错的规则节。LLM 注意力资源有限，标签指引优先分配 | v2 未标 → 2/3, v3 标了 → 6/6 |
| 4 | **示例-规则屏障** | 格式示例结束后加显式提醒——防 LLM 将示例续写为自己的输出 | v3 的 1/6 续写故障 v4 消除 |
| 5 | **具体优于抽象** | 给出数字和案例，而非比例或一般性描述。"总 80 段 → bridge 第 32 段后 ✓" | bridge 量化位置偏离缩小 |
| 6 | **显式禁止优于隐式模式** | 独立的 `**禁止**` 节逐条列出禁止行为——每条都是测试中实际出现过的错误 | 禁止项逐条验证 |
| 7 | **关键处不吝笔墨** | 整体紧凑，但在反复出错的规则上多花 tokens。checkpoint 规则更长但 Prompt 整体更短 | v4 比 default 少 49 chars 但关键规则更详尽 |

**跨题材泛化测试**（v4 Prompt，4 题材各 3 轮）：
- 赛博朋克（基准）：2/3 正确，3/3 无缝
- 青春恋爱：2/3 正确，2/3 无缝——对话密度极高但格式保持
- 心理悬疑：3/3 正确，3/3 无缝——bridge 未打断悬念节奏
- 古风武侠：1/3 正确，2/3 无缝——对话文言化倾向影响格式

**跨题材发现**：
- **bridge-before-options**（跨题材共性问题）：慢节奏叙事中 LLM 在 options 之前插入 bridge——需要更强措辞
- **bridge 位置偏离**（跨题材共性问题）：慢节奏叙事推迟交互断点——`BRIDGE_POSITION_RATIO` 从 0.75 调至 0.4（bridge 提前，增加 post-bridge 缓冲）

**依据**：
- prompt-design.md §1.2（7 条原则）+ §6（迭代日志）
- 设计：`docs/superpowers/specs/2026-07-04-prompt-template-optimization-design.md`
- 跨题材：`docs/superpowers/specs/2026-07-04-cross-genre-prompt-validation-design.md`
- commits：`78b35d4`（7 条原则记录）、`74c8131`（跨题材测试记录）、`b209b64`（streaming+bridge 时序）、`3533397`（段格式强制）

### 对话式消息数组架构

**背景**：v4 Prompt 模板在单轮测试中表现良好（83% 正确率），但存在架构级问题——**每轮发送独立的 System Prompt（~3000 tokens），LLM 每轮重新学习格式规则。** 这意味着：(1) ~3000 tokens/轮的格式开销，(2) 无跨轮记忆——LLM 不知道前几轮发生了什么，(3) 每轮都有格式偏差的独立风险。

**架构迁移**：

| 维度 | 旧（v4/v5） | 新（对话式） |
|------|------------|------------|
| 消息结构 | 每轮独立 system + user | messages 数组，持续对话 |
| 格式规则 | 每轮重复 ~3000 tokens | Round 1 教一次，后续靠对话历史维持 |
| Round 1 输出 | 不保留 | 永久保留在 messages[1]——作为格式 few-shot 范例 |
| bridge_text | 嵌入 user message | 从 assistant XML 输出提取，作为下一轮 user message 的一部分 |
| 对话历史 | 无 | 最近 3 轮完整 user/assistant 对保留 |
| 历史压缩 | 无 | 滑出窗口的轮次压缩为 checkpoint 摘要消息对 |

**消息数组结构**：
```
messages = [
  {role: "user",      content: Round1_完整Prompt},        // 永久锚定（格式规范 + 故事上下文 + XML 示例）
  {role: "assistant", content: Round1_XML输出},            // 永久锚定（few-shot 范例 ~1500 tokens）
  // ── 滑出窗口 → 压缩 ──
  {role: "user",      content: "以下是之前发生的主要事件：\n- ch1: ...\n- ch2: ..."},
  {role: "assistant", content: "（以上为已发生事件的摘要。当前故事继续推进。）"},
  // ── 窗口内（WINDOW_SIZE=3）→ 完整保留 ──
  {role: "user",      content: Round_N-3_上下文},
  {role: "assistant", content: Round_N-3_XML输出},
  {role: "user",      content: Round_N-2_上下文},
  {role: "assistant", content: Round_N-2_XML输出},
  {role: "user",      content: Round_N-1_上下文},
  {role: "assistant", content: Round_N-1_XML输出},
  // ── 当前轮 ──
  {role: "user",      content: Round_N_上下文},            // 轻量：进度 + 状态 + bridge_text + 错误反馈
]
```

**关键参数**（`src/storyloom/config.py`）：
- `WINDOW_SIZE = 3`：保留最近 3 轮的完整对话历史
- `FIRST_COMPRESSION_AT = 5`：Round 5 触发首次压缩（此时窗口满 + 2 轮 buffer）
- `MAX_CONTEXT_TOKENS = 50_000`：上下文预算上限（目标值，非硬截断）

**压缩策略**：
- 压缩来源：滑出窗口轮次的 `<checkpoint summary="...">` 属性值
- 合并为一个 user/assistant 消息对——多轮摘要以列表形式累积
- 首次压缩 Round 5：压缩 Round 2
- Round N：压缩 Round 2 ~ N-4（窗口保留 [N-3, N-2, N-1]）

**上下文预估**（medium 故事 ~20 轮）：
- Round 1 Prompt：~2,500 tokens
- Round 1 输出：~1,500 tokens
- 3 轮完整窗口（含 user 上下文 + assistant 输出）：~18,000 tokens
- 压缩消息对：~500 tokens
- 当前轮消息：~500 tokens
- **总计：~23,000 tokens**——远低于 50K 目标，有大量余量

**格式错误纠正策略**：
- 仅当上一轮解析出现格式错误时追加纠正提示（单条，简短）
- 正确时不追加——不打断 LLM 从最近正确输出中的自然学习
- 不删除 Round 1 中的格式范例——范例仅 ~500 tokens，占 50K 上下文的 1%

**边界情况处理**：
- Round 1：调用 `build_round1()`，非 `build_round_n()`。`bridge_text` 为空
- `compressed_summaries` 为空：不注入压缩消息对（Round 2-4 无压缩）
- `rejected_changes` 为空：不注入反馈节
- `format_error` 为 None：不注入纠正提示
- `ending_flag=True`：不组装叙事 Prompt——走冒险日志路径（独立 LLM 调用）

**实现模块**：
- `ContextManager`：管理 messages 数组、滑动窗口、压缩触发和消息对构建
- `PromptBuilder`：构建单条消息的**内容**（非完整 messages 数组）

**依据**：
- [[conversation-architecture]] — 初始设计讨论（方案 vs 替代方案）
- `docs/superpowers/specs/2026-07-04-conversation-prompt-design.md`（完整设计）
- `docs/superpowers/plans/2026-07-04-conversation-prompt-implementation.md`（实现计划）
- prompt-design.md §4.1（消息数组架构 + 压缩时序）
- data-model.md §A.5（窗口和压缩参数）

### 变量系统：从硬编码模板到 LLM 自定义

**背景**：初版设计使用三套硬编码状态模板——`templates/states.json` 存储 romance（恋爱）、adventure（冒险）、mystery（悬疑）的预定义变量。`GENRE_TEMPLATE_MAP` 做题材→模板映射。这是 Phase 2"LLM 自定义变量"之前的临时方案。

**硬编码模板的问题**：
1. **变量有限**：每种题材仅 5 个固定变量——"换题材即失效"
2. **题材绑死**：只能从 3 种题材中选择——完全不符合"任何故事"的项目定位
3. **维护成本**：新增题材需要：（a）设计变量→（b）编写 JSON→（c）加入 `GENRE_TEMPLATE_MAP`→（d）可能需要调整 Prompt
4. **与长期目标冲突**：Phase 2 计划实现 LLM 自定义变量——硬编码模板是死路

**决策**：**Phase 1 即实现 LLM 自定义变量**——不在 Phase 2 之前打地桩。

**砍掉的内容**：
| 移除项 | 原位置 | 替代方案 |
|--------|--------|---------|
| `templates/states.json` | 文件系统 | LLM 在 Step 3.5 生成变量定义 |
| `TEMPLATES_PATH` 常量 | `config.py` | 不再加载模板文件 |
| `GENRE_TEMPLATE_MAP` 常量 | `config.py` | 题材降级为自由文本标签 |
| 三套题材概念 | `story_config.genre` | genre 变为自由文本，不驱动变量选择 |
| `state_template` 字段 | GameState / 存档 | 变量定义存储在 `story_config.variables` |

**新增 Step 3.5**：在 story_config 生成（Step 3）和大纲生成（Step 4）之间插入变量定义步骤：
```
Step 3: 生成故事设定（=== story_config ===）
    ↓
Step 3.5: 生成变量定义（=== variables ===）  ← 新增
    ↓
Step 4: 生成大纲树（=== outline ===）
```

**变量约束（初始设计，后续 07-05 收紧为 ≤3）**：
- 5-8 个变量（中文名，2-5 字）
- number 型：[0, 100]，支持 `+N`/`-N`/`=N`
- string 型：替代枚举（不设枚举类型，枚举归入 string），仅支持 `=值`
- list 型：元素为 string，支持 `+元素`/`-元素`
- LLM 输出格式：`=== variables ===` 后每行 `变量名: 类型, 初始 值`

**程序校验规则**：
- 变量名唯一、非空、不含非法字符（`\n`, `:`）
- 类型仅限 number/string/list
- number 初始值在 [0, 100] 范围内
- string 初始值非空
- list 初始值可为空数组 `[]`，元素须为 string
- 校验失败 → 重试（附带错误提示），最多 `MAX_RETRIES`（2）次

**同时修复的 4 处规范矛盾**（文档审查中发现的直接冲突）：
1. **结局轮是否需要 bridge**：决议"需要"——bridge 在结局轮是必选的。程序在 bridge 处检测 `ending_flag` → 发起冒险日志调用
2. **adventure_log 生成方式**：决议"独立 LLM 调用"——不嵌入叙事循环的 LLM 输出，不走解析管线
3. **options 声明关键字**：统一用 `choice:`（无文本块 → XML 后此问题自然解决，但语义仍保留在 choice_dict 命名中）
4. **条件变量解析优先级**：统一为 `choice_dict > state_vars`——适用于所有条件求值场景（options 置灰、set 条件、route 条件）

**对现有系统的影响**：
- `GameState` 初始化：`state_template` → `story_config.variables` 驱动
- state 变更校验：变量类型定义来源从模板 → `story_config.variables`
- 存档：移除 `state_template` 字段，新增 `story_config.variables`
- Prompt：System Prompt 中状态部分直接格式化 `state_vars`（无模板驱动）

**依据**：
- `docs/superpowers/specs/2026-07-04-variable-system-and-spec-fixes-design.md`（完整设计，含移除项清单和影响分析）
- commit `56847d8` — `docs: apply variable system refactor and contradiction fixes to spec files`
- exec-flow.md §3.5（Step 3.5 描述）+ data-model.md §B 约定 #8（错误隔离）

---

## 2026-07-02 ~ 2026-07-03（周三~周四）

### Phase 1 规范体系建立与项目启动

**07-02：项目骨架**：
- Initial commit（`64d2a8b`）：项目目录、文档骨架
- Phase 1 MVP 需求 spec（`1942360`）：分阶段路线图（Phase 1 CLI → Phase 2 Web + 动态系统 → Phase 3 完整体验）
- 核心设计概念确立：bridge 机制、双层分支（段内/大纲）、本地真相源

**07-03：规范成形**：
- 26 题 grill-me 审查（commit `e62318a`）——系统性质疑每个设计假设
- 10 项决定（commit `4287193`）：bridge 必选、adventure_log 独立调用、超时截断策略、用户决策权等
- exec-flow.md 5 章节（§1-§5）在一天内建立：启动与主菜单 → 共创阶段 → 叙事循环 → 结局阶段 → 存档系统
- 常量体系（§A + §B）：从设计中提取可配置参数，建立"常量化"原则

**命名规范两次迭代**：
1. 区块名：括号格式 `--- narrative(main) ---` → 冒号格式 `--- narrative:main ---`（commit `ba338f0`）
2. 变量命名：`key`/`key_dict` → `choice`/`choice_dict`（commit `3a302fc`）——"key" 在多个上下文中被使用，`choice` 更精确
3. 分支命名：`name`/`current_name` → `branch`/`current_branch`（commit `fa5da09`）——与 XML 元素名 `<branch>` 保持一致

**关键 spec 修订（07-03 内）**：
- bridge 约束澄清（commit `c91acc0`）：提取规则、区块数量限制、结局轮 bridge 位置
- 常量体系扩展（commit `80081da`）：新增故事档位系统（short/medium/long × 节点数范围）
- `--- ending ---` 区块移除（commit `98efc20`）：结局由 checkpoint `end` 触发，不需要独立区块
- 全局约定建立（10 条规则，commit `5671c71`）：Prompt 语言、XML 元素名、变量命名、XML 转义、重试策略、用户决策权、错误隔离、静默错误、常量引用、编号宽容

**依据**：
- commits：`64d2a8b`（Initial commit）→ `e62318a`（grill-me 审查）→ `4287193`（10 项决定）→ exec-flow.md/data-model.md 的 30+ 个细化 commits
- `docs/spec/exec-flow.md`、`docs/spec/data-model.md` 的核心结构在此阶段成形
- `docs/README.md`：分阶段路线图（原计划 Phase 2 Web，实际被提前至并行分支）

---

## 附录：日志编写约定

- **格式**：`## YYYY-MM-DD（周X）` → `### 主题` → 背景/决策/依据三段式
- **依据**：优先引用 commit hash + message、spec 文档章节号、memory 文件名。避免模糊表述
- **跨日引用**：同一主题跨多日时，最早出现日写完整背景，后续日用"见 X 日日志"链接
- **废弃/推翻决策**：保留不删，在后续日期标注"推翻/替代"并交叉引用到修正决策
- **扩充**：新日志插入在最新日期下方（倒序），保持最近工作最先可见

---

*持续更新。每个设计决策都可追溯到 `docs/superpowers/specs/`（设计文档）、`docs/superpowers/plans/`（实现计划）、或 git 历史中的具体 commit。*
