# Storyloom 工程日志

> 按时间线记录每个设计决策的背景、动机与依据。倒序排列（最新在前），新日志插入文首。
>
> 格式约定：**背景**（为什么此时需要决策）→ **决策**（做了什么选择）→ **依据**（commit / spec 章节 / memory 文件）。

---

## 2026-07-11（周六）

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

**背景**：`exec-flow.md` §5.2 要求冒险日志在 bridge 时刻发起，与 bridge_text 展示并发执行。实际代码中 `run_adventure_log()` 在所有 segment 展示完毕后同步调用。

**决策**：
1. 提取 `_accumulate_checkpoint()` 辅助方法（消除 3 处重复）
2. Post-parse "end" 检测——Step 7 后立即检查 `parsed.checkpoint_node == "end"`
3. Adventure log 在 `_emit_parsed()` 前启动 daemon 线程，segment 展示期间并发执行
4. Early-return guard 防止结局后被重复调用

**依据**：
- commit `980ec2f` — `fix(engine): adventure log now runs concurrently with bridge_text display`
- [[2026-07-10-adventure-log-timing-fix]]
- [[2026-07-10-spec-compliance-audit]]（10/10 全部修复）

---

## 2026-07-10（周五）

### bridge pre-fetch 实现

**背景**：Bridge 机制要求程序在展示 post-bridge 缓冲文本期间发起下一轮 API 调用，以消除段边界停顿。exec-flow.md §4.3 描述了时序模型，但此前实现侧一直是串行等待。

**决策**：在 `GameLoop._launch_prefetch()` 中实现 daemon 线程 + `queue.Queue` 架构。仅对无选项（auto-advance）轮次触发——choice 轮次的下一轮 messages 数组取决于玩家选择，无法预计算。

**依据**：
- commit `663b9f2` — `feat(engine): implement bridge pre-fetch for auto-advance rounds`
- exec-flow.md §4.3 描述的时序模型
- [[2026-07-10-bridge-prefetch-work-log]]

### 规范合规审计与修复

**背景**：对代码实现与 4 份权威 spec 文档进行逐条对照审计。

**决策**：发现并修复 1 P0 + 3 P1 + 4 P2 问题：

| 等级 | 问题 | 修复 commit |
|------|------|-------------|
| P0 | unconditional set 双重应用 | `4715904` |
| P1 | emit_parsed 未传递 current_branch | `4715904` |
| P1 | AUTO_ADVANCE_DELAY_MS spec 引用同步 | `4715904` |
| P1 | Round 1 parse 失败缺少 observer 通知 | `951145c` |
| P2 | adventure log 与 bridge_text 并发执行 | `980ec2f` |
| P2 | 其他 spec 同步 | `642465f` |

**依据**：
- [[2026-07-10-spec-compliance-audit]]
- [[2026-07-10-spec-compliance-followup]]
- [[2026-07-10-adventure-log-timing-fix]]

### StreamingXmlParser 删除 **【07-11 推翻，见当日日志】**

**背景**：2026-07-05 的 narrative flow refactor 设计规划了 `StreamingXmlParser`——基于 `NNN| ` 行号前缀的逐行流式解析器，含状态机（`IN_STORY | IN_BRANCH | IN_CHECKPOINT | IN_CHOICE | POST_BRIDGE`）和预处理/实际处理双重线。该模块曾被实现（commit `39c049d`）。

**决策（07-10）**：删除 `streaming_parser.py`。

**理由（07-10）**：
1. bridge pre-fetch 在后台线程完成完整 API 调用 + `ElementTree` 解析——流式解析的"边收边处理"优势被覆盖
2. 状态机 + 双重处理线的复杂度与 `ElementTree` 全量解析的 millisecond 级耗时不成比例
3. 两套解析器需保持语义一致——维护负担 > 理论收益

**推翻（07-11）**：上述分析聚焦在错误的指标上（已完成的 XML 解析耗时 234 μs）。正确指标是从 pre-fetch 启动到**首个可展示内容就绪**的墙上时间——全量解析需等待完整生成（25-50s），流式解析仅需等待首行生成（<1s）。见 [[2026-07-11-streaming-parser-timing-flaw]]。

**依据**：
- [[2026-07-10-adventure-log-and-parser-architecture]]（部分分析被推翻）
- [[2026-07-11-streaming-parser-timing-flaw]]（修正分析）
- `src/storyloom/parser/streaming_parser.py` 已不存在，需从 `7fe2278` 恢复

### CoCreateFlow.run() 删除

**背景**：`CoCreateFlow.run()` 是遗留的同步方法，内部直接调用 `Display` 进行终端 I/O。状态机 API（`start()`/`send()`，07-07 实现）已完全覆盖其功能，Terminal UI 已移至 `dev_cli`。

**决策**：删除 `run()` 方法及所有 UI 耦合代码。

**依据**：
- commit `a6d941f` — `2 files changed, 268 insertions(+), 566 deletions(-)`（净 -298 行）
- CLAUDE.md §UI Territory 明确引擎不应依赖 UI 层文件

### Dev CLI 完整实现

**背景**：07-07 将 CLI 降级为测试工具后，需要一个最小化的 CLI 来验证引擎端到端能力，同时提供开发者检查（记录原始 Prompt/响应/解析数据）。

**决策**：实现 `src/storyloom/dev_cli/` 包（`__init__.py` / `args.py` / `ui.py` / `observer.py`）。核心约束：零引擎变更。通过 `GameLoop._observers`（Python 约定私有属性）注册 DevObserver。输出文件追加模式写入 `dev_output/{prompts,responses,checks}.txt`。

**依据**：
- 设计：`docs/superpowers/specs/2026-07-10-dev-cli-design.md`
- 计划：`docs/superpowers/plans/2026-07-10-dev-cli.md`
- Commits：`45ebd25` → `93c6020`（17 个 commits）

### 系统 Prompt 英文化

**背景**：部分 Prompt 残留中文，违反 prompt-design.md §1.1 "英文 Prompt"原则。

**决策**：全面清理——所有系统/叙事 Prompt 切换为英文；冒险日志 Prompt 改为英文 + 引擎中立信号。

**依据**：
- commit `048ab53` — `refactor: purge Chinese from system prompts and format spec`
- commit `77314b7` — `refactor: rewrite adventure log prompt in English`
- prompt-design.md §1.1：英文 Prompt 原则

---

## 2026-07-07（周一）

### API 审计与界面集成设计

**背景**：引擎声称 UI 无关，但审计发现 Web UI 开发者需要重新实现大量业务逻辑才能接入。

**决策**：识别 5 个缺口并逐一解决：

| # | 缺口 | 解决方案 |
|---|------|---------|
| 1 | UiInterface 过于极简 | 保持 3 方法不变，通过状态机 API 弥补 |
| 2 | CoCreateFlow 不可被 Web UI 复用 | 实现 `start()`/`send()` 状态机 API |
| 3 | 无顶层会话编排器 | 新增 `GameSession` 类 |
| 4 | GameLoop 缺少公开访问器 | 新增 `checkpoint_history`/`outline_nodes` 属性 |
| 5 | SaveManager 未统一 | `GameSession` 封装生命周期 |

**关键发现**：`outline_nodes` 存在两种内部格式（新鲜创建 vs. 从 save 恢复），需在公开访问器中做格式归一化——这是在设计过程中发现的预存 bug。

**依据**：
- `docs/superpowers/specs/2026-07-07-api-audit-and-interface-design.md`（完整审计报告，v2 自我审查修正版）
- 实现 commits：`03d992f`（start）、`e3a6750`（send）、`2ba92ea`（GameSession）、`7d08624`/`f8667df`（accessors）

### CLI 降级与观察者统一

**背景**：`main.py` 中的 CLI 原本是"主界面"，但 Web 界面已成为主要 UI 层。`Display` 类混入了 GameLoop——违反 UI-引擎解耦原则。

**决策**：
- CLI 从"主界面"降级为"测试/维护工具"
- `Display` 从 `GameLoop` 中移除——GameLoop 改为 generator yield 事件流
- 观察者系统统一到 `cli_utils.py`

**依据**：
- commit `2127350` — `refactor: demote CLI to test-only harness, unify observer system`
- [[2026-07-07-cli-observer-refactor]]

### 3 个 P0 引擎 Bug 修复

**背景**：代码审查发现条件变量解析逻辑存在优先级不一致。

**决策**：
1. 所有条件求值场景统一 `choice_dict > state_vars` 优先级
2. number 操作结果 clamp 到 [0, 100]
3. 分支条件全部不命中 → 取第一条 route 的 target（兜底）

**依据**：
- commit `6533e10`
- block-spec.md §3："条件变量解析优先级：choice_dict > state_vars"
- [[2026-07-07-audit-and-bugfix]]

### 规范文档 NNN| 格式同步

**背景**：代码已迁移到 `NNN| ` 行号前缀格式（07-05），但 block-spec.md 和 prompt-design.md 仍使用旧的 `<seg n="N">` 描述。

**决策**：同步全部核心文档到新格式，修复 8 处不一致。

**依据**：
- commit `f283d24` — `docs: sync spec format to NNN| line-number prefix, fix 8 issues`
- [[2026-07-07-doc-audit-and-format-sync]]

---

## 2026-07-06（周日）

### 后端完备化：存档、结局、解耦

**背景**：引擎核心缺失三个关键能力——(1) 存档系统仅存设计文档，(2) 结局检测和冒险日志未实现，(3) CoCreateFlow 直接依赖 `Display` 类，Web UI 无法复用。

**决策**（11 项任务，一次性交付）：

1. **SaveManager**（新模块）：原子写入（`.tmp` → `os.replace`），加载校验（version + 字段完整 + current_node 存在），文件名从 `story_config.label` 派生
2. **ending_flag 机制**：checkpoint `node="end"` → `ending_flag=True` → bridge 处组装冒险日志 Prompt → 独立 LLM 调用（不走叙事循环解析管线）
3. **UiInterface 协议**：极简 3 方法（`write`/`show_error`/`ask`），CoCreateFlow 全部替换 `Display` 调用
4. **GameState/GameLoop 序列化**：`to_dict()`/`from_dict()`——为存档和加载提供数据契约
5. **冒险日志 Prompt**：`build_adventure_log_prompt()`，注入 story_config + state_vars + checkpoint_summaries + checkpoint_history。Markdown 格式，500-1000 字

**依据**：
- 设计：`docs/superpowers/specs/2026-07-06-backend-completion-design.md`（经自我审查修订）
- 计划：`docs/superpowers/plans/2026-07-06-backend-completion.md`（11 任务）
- 核心 commits：`c18fb71`（SaveManager）、`acfd7c9`（UiInterface）、`9f67ac6`（ending）、`06b49ba`（冒险日志）、`50a5057`/`6646a60`（序列化）

### Narrative Flow 重构

**背景**：xml_parser.py 存在 5 个问题：(1) bridge_text 未按 current_branch 过滤，(2) 全量解析违背顺序处理，(3) `run_full_test.py` 重写了生产逻辑，(4) 无观察者机制，(5) `format_error` 从未被赋值。

**决策**：
1. `_extract_bridge_text()` 改为按 `current_branch` 过滤——统一逻辑，不再区分"全量/分支"模式
2. 实现 `StreamingXmlParser`（状态机驱动的流式逐行解析器）**【注：该模块于 07-10 删除，见当日日志】**
3. 新增 `RoundRecord` + observer 回调
4. 修复 `format_error`——流式解析异常时设置，下一轮 Prompt 注入纠正提示
5. `run_full_test.py` 全量重写为 GameLoop 驱动

**依据**：
- 设计：`docs/superpowers/specs/2026-07-05-narrative-flow-refactor-design.md`
- commit `39c049d` — `refactor: narrative flow — branch-aware bridge_text, observer pattern, streaming parser`

### 国际化迁移：Display.UI → gettext

**背景**：`Display.UI` dict 存储 UI 文本——翻译者需编辑 Python 字典。

**决策**：迁移到 gettext `.po/.mo` 文件体系。`_()` 调用替代 `display.t("key")`。

**依据**：
- 设计：`docs/superpowers/specs/2026-07-06-i18n-gettext-design.md`
- 计划：`docs/superpowers/plans/2026-07-06-i18n-gettext-migration.md`
- [[i18n-migration-follow-up]]

### 包结构重构

**背景**：原 `src/storyloom/` 是扁平结构。

**决策**：拆分为 `core/`（引擎核心）、`io/`（API 客户端）、`parser/`（XML 解析器）三个子包。

**依据**：
- commit `7fe2278` — `refactor: split flat package into core/io/parser subpackages`
- CLAUDE.md 文件管辖表格反映此结构

---

## 2026-07-05（周六）

### 行号格式迁移（NNN| 前缀）

**背景**：`<seg n="N">` 属性编号方案下，LLM 需在生成 XML 属性同时维护编号——认知负担高。

**决策**：改为 `NNN| ` 行号前缀（零填充 3 位，全局连续）。每行是自包含单元——`NNN| <element>content</element>`。

**连锁变更**：
- `SEGMENTS_PER_ROUND_*` → `LINES_PER_ROUND_*`（行数 ≈ 段数 × 1.25）
- `LINES_PER_ROUND_MIN` = 150，`LINES_PER_ROUND_MAX` = 300
- `<seg n="N">` → 裸 `<seg>`

**依据**：
- commit `ce5a776` — `feat: migrate to English line-numbered prompt format`
- `tests/prompt_lab/data/prompts/round1-linenum.txt`（权威 Prompt 标准，9758 字节）
- data-model.md §A.4（行控制常量）+ §A.7（废弃的 `SEGMENTS_PER_ROUND_*`）
- block-spec.md §2（行号规范）

### 段长-TTFT 实验

**背景**：Bridge 无缝约束 `TTFT < N × RATE × t`（RATE=50%, t=0.5s/段）。需找到使约束成立的段长范围。

**假设**：TTFT 由思考时间主导，而非输出长度。

**实验**：4 档（60-120 / 120-200 / 180-280 / 240-360），每档 3 次运行。

**结果**：假设部分成立（段数 3×，TTFT 仅增 ~20%）。最优范围：**120-200 段，75% bridge 位置，12,288 tokens**。关键因素：Prompt 大小（输入 tokens）对 TTFT 的影响 > 输出长度。

**依据**：
- 设计：`docs/superpowers/specs/2026-07-05-segment-length-test-design.md`
- 实验数据：commits `fb73c9d`（配置应用）、`867d16e`（Phase 2 RATE）、`af1b6df`（4 档结果）
- [[segment-length-ttft-optimization]]

### Bridge 位置：40% → 75%

**背景**：`BRIDGE_SEGMENT_RATIO = 0.4`，post-bridge 缓冲文本太短（~15-30s），TTFT 平均 48-60s 导致用户感知停顿。

**决策**：`BRIDGE_POSITION_RATIO = 0.75`（常量重命名 + 值更新）。新增 `MIN_TAIL_LINES = 25`。

**依据**：
- commit `aa2b8fe` — `fix: bump post-bridge branch minimum to 25 lines`
- data-model.md §A.4（当前常量 0.75）+ §A.7（废弃常量 0.4）

### 变量上限收紧：5-8 → ≤3

**背景**：初始设计建议 5-8 个变量。多变量 → 更多 `<set>` 操作 → 更多条件路由 → 更高错误率。

**决策**：≤3 总计（≤2 number + ≤1 string/list）。新增 `VARIABLE_CAP=3`、`VARIABLE_NUMERIC_CAP=2`、`VARIABLE_LABEL_CAP=1`。原则："如果一个变量从不触发分支或选项，它就是噪音"。

**依据**：
- `docs/superpowers/specs/2026-07-05-variable-cap-design.md`
- `src/storyloom/config.py` 中 `VARIABLE_CAP = 3`

### 共创阶段实现（CoCreateFlow）

**背景**：叙事循环已迭代 6+ 轮，但共创阶段代码为零。`main.py` 用硬编码 `DEFAULT_STORY_CONFIG` 绕过整个流程。

**关键决策 1 — 三步合一**：单次 API 调用生成 story_config + variables + outline（`=== xxx ===` 分隔），而非 3 次独立调用。延迟降低 2/3；LLM 在单次上下文中有完整信息。

> spec 文档（exec-flow.md §3）保留 Step 3/3.5/4 的逻辑分步——为概念清晰，不代表 3 次独立调用。

**关键决策 2 — 静态全上下文窗口**：共创阶段 ~6-12 条消息，无需滑动窗口和压缩。

**关键决策 3 — INI 风格区块**：`=== xxx ===` 分隔符经叙事 Prompt 测试验证稳定。

**实现**：`CoCreateFlow`（`start()`/`send()` 状态机 + `_generate_all()`）+ `CoCreateParser`（`split_blocks()` / 各 `parse_*()` / 各 `validate_*()`）。

**依据**：
- 设计：`docs/superpowers/specs/2026-07-05-co-creation-implementation-design.md`
- 计划：`docs/superpowers/plans/2026-07-05-co-creation-implementation.md`
- 单次调用验证：`_generate_all()` 使用 `self._api.chat(self._messages)` 单次调用 + `CoCreateParser.split_blocks(response)` 拆分

### 叙事流程 5 缺陷修复

**背景**：对话式架构实现存在流程缺陷（completed_nodes 派生、压缩摘要注入、选项标签、节点注入、结局检测）。

**决策**：5 项修复，commit `88f489e`。

---

## 2026-07-04（周五）

### XML 格式替换文本块（frame-v1）

**背景**：初版使用 `--- block ---` 分隔符。经测试暴露系统性问题——node ID 后缀拼接 ~80%、分支叙事缺失 ~60%、双重 bridge ~30%、解析正确率 20-74%。

**决策**：采用 XML 格式（`<story>` 根元素，6 种子元素）。

**核心洞察**：LLM 将自定义文本块视为"外语"——从 Prompt 文本重新学习。XML 是 LLM 的"母语"——无处不在的训练数据。

**首次测试**（frame-v1，DeepSeek v4-pro）：**3/3 (100%)** 正确率，对比文本块 20-74%。

**关键设计规则**（经用户反馈修正）：
- `<branch>` 允许在 bridge 之前（段内小分支）
- bridge 之后仅 `<seg>` 和 `<branch>`，禁止 `<choice>`/`<set>`/`<checkpoint>`

**依据**：
- [[xml-format-decision]] — 测试数据（TTFT 12.6-80.3s, 段数 74/101/75）
- block-spec.md §1（XML 元素速查表 + 结构示例）

### Prompt v4 模板：6 轮迭代

**背景**：XML 格式确定后，Prompt 质量成为核心瓶颈。

**迭代结果**（6 轮，30+ 次测试）：正确率 33%→83%，TTFT 38s→11s，checkpoint 正确率 33%→100%。

**核心洞察**：**LLM 对"不能做什么"的学习依赖显式规则，而非从示例推断。** 催生了 7 条约束有效性原则。

**依据**：
- prompt-design.md §1.2（7 条原则）+ §6（迭代日志）
- commit `78b35d4`

### 对话式消息数组架构

**背景**：旧架构每轮独立 System Prompt（~3000 tokens），LLM 每轮重新学习格式。

**决策**：messages 数组架构——Round 1 永久锚定 + 滑动窗口（WINDOW_SIZE=3）+ checkpoint 压缩（FIRST_COMPRESSION_AT=5）。目标 ≤50K tokens。

**上下文预估**（medium ~20 轮）：~23,000 tokens。

**依据**：
- [[conversation-architecture]] — 设计讨论
- `docs/superpowers/specs/2026-07-04-conversation-prompt-design.md`
- prompt-design.md §4.1 + data-model.md §A.5

### 变量系统：从硬编码到 LLM 自定义

**背景**：三套硬编码状态模板（romance/adventure/mystery，`templates/states.json`）——变量有限，换题材即失效。

**决策**：
1. 砍掉模板系统（删除 `templates/states.json`、`TEMPLATES_PATH`、`GENRE_TEMPLATE_MAP`、`state_template`）
2. 新增 Step 3.5：LLM 自定义变量生成（`=== variables ===`）
3. 同时修复 4 处规范矛盾（结局 bridge 必选、adventure_log 独立调用、声明关键字统一、条件优先级统一）

**依据**：
- `docs/superpowers/specs/2026-07-04-variable-system-and-spec-fixes-design.md`
- commit `56847d8`
- exec-flow.md §3.5 + data-model.md §B 约定 #8

---

## 2026-07-02 ~ 2026-07-03（周三~周四）

### Phase 1 规范体系建立与项目启动

**背景**：项目从零开始。

**关键活动**：
- 07-02：项目骨架 + 文档目录 + Phase 1 MVP 需求 spec + 分阶段路线图
- 07-03：26 题 grill-me 审查 → 10 项决定 → 规范成形
- 执行流程文档 5 章节建立（§1-§5）
- 命名规范两次迭代：括号→冒号格式、key→choice、name→branch
- 常量体系确立（§A + §B）

**依据**：
- commits `64d2a8b`（Initial commit）→ `1942360`（MVP spec）→ `4287193`（grill-me 后修订）
- `docs/spec/exec-flow.md`、`docs/spec/data-model.md` 的核心结构在此阶段成形

---

## 附录：日志编写约定

- **格式**：`## YYYY-MM-DD（周X）` → `### 主题` → 背景/决策/依据三段式
- **依据**：优先引用 commit hash + message、spec 文档章节号、memory 文件名。避免模糊表述
- **跨日引用**：同一主题跨多日时，最早出现日写完整背景，后续日用"见 X 日日志"链接
- **废弃决策**：保留不删，在后续日期标注"推翻/替代"并交叉引用
- **扩充**：新日志追加在最新日期上方（倒序），保持最近工作最先可见

---

*持续更新。每个设计决策都可追溯到 `docs/superpowers/specs/`（设计文档）、`docs/superpowers/plans/`（实现计划）、或 git 历史中的具体 commit。*
