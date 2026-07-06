# Narrative Flow Refactor — Design Spec

> 2026-07-05 | 以 `tests/data/prompts/round1-linenum.txt` 为**唯一正确标准**，重构叙事流程。
> `block-spec.md`、`exec-flow.md`、`prompt-design.md` 是重要参考，但非最终权威。

## §1 问题诊断

| # | 问题 | 说明 |
|---|------|------|
| 1 | **bridge_text 未按 current_branch 过滤** | `XmlParser._extract_bridge_text()` 提取所有分支文本，未选中分支的内容泄露到下一轮 |
| 2 | **全量解析违背顺序处理原则** | `ElementTree.fromstring()` 一次性解析完整 XML，然后批量处理。正确做法是按文档顺序流式处理 |
| 3 | **`run_full_test.py` 重写了全部生产逻辑** | 手工状态管理、route 评估、choice_dict 构建——这些应该由 GameLoop 完成 |
| 4 | **无观察者机制** | 测试/发布模式无法区分，每轮数据无法导出 |
| 5 | **`format_error` 从未被赋值** | `GameLoop._format_error` 声明了但没有任何代码设置它——XML 解析错误不会反馈给 LLM |

## §2 设计原则

### 2.1 缓冲式读取

```
LLM 流式输出 token 序列（程序边收边处理）：
    │
    ▼
┌──────────────────────────────────────────────────┐
│ pre-bridge（交互区）                                │
│   seg × N    → 逐段展示（程序略快于用户阅读）          │
│   <choice>   → 暂停，等待玩家输入                    │
│   <set>      → 即时应用到 GameState                 │
│   <checkpoint> → 记录节点 + 路由                     │
│                                                    │
│ <bridge/> → 触发下一轮 API 调用                       │
│                                                    │
│ post-bridge（叙事缓冲区）                            │
│   选中分支的 seg × N → 继续展示                      │
│   未选中分支 → 预加载但不展示不注入                    │
│   （用户阅读缓冲区时，下一轮已在生成）                   │
└──────────────────────────────────────────────────┘
```

**核心约束**：`<choice>`、`<set>`、`<checkpoint>` 只能在 bridge 之前。bridge 之后只有 `<seg>` 和 `<branch>`。

### 2.2 流式解析

**实现目标**：基于行号的流式逐行解析，而非 `ElementTree` 全量解析。

`round1-linenum.txt` 规定的 `NNN| ` 行号前缀使流式解析天然可行——每行是一个独立的处理单元：

```
001| <story>           → 进入 story 上下文
002| <seg>text</seg>    → 展示
...
025| <bridge/>          → 触发下一轮 API 调用
...
035| </story>           → 本轮结束
```

解析器维护一个轻量状态机（跟踪当前所在容器：story / branch / checkpoint / choice），逐行识别元素类型并产生事件。GameLoop 消费事件（展示 seg、应用 set、暂停 choice、触发 bridge）。

**全量解析保留用于**：快速测试脚本中的离线分析（`XmlParser.parse()` 不变）。

### 2.3 bridge_text 提取：统一逻辑

bridge_text 的提取**只有一种模式**：按 `current_branch` 过滤。

- 如果玩家选了 branch `"betrayal_path"` → 提取 `<branch name="betrayal_path">` 内的文本
- 如果玩家没选（无 choice 的轮次）→ 提取裸 `<seg>`（不属于任何 branch 的 seg）
- Round 1 无上一轮选择 → bridge_text 为空（`set_round1` 不需要 bridge_text）

`current_branch` 默认就是 `"main"` 或空——不存在"全量模式"和"分支模式"的区分。**默认就是一种分支**。

### 2.4 set 处理：无语义区分

在流式解析中，**所有 `<set>` 都按文档顺序即时处理**。`if` 条件能否求值取决于 choice_dict 是否已就绪：

- 文档顺序：`<choice>` → 玩家选择 → choice_dict 就绪 → `<set if="choice==1">` → 条件可求值
- 无条件的 `<set>` 在遇到时直接应用

"unconditional set" 是当前全量解析制造的人为区分。流式模型只认文档顺序。

### 2.5 bridge 时刻：预处理窗口

**时序模型**：

```
LLM 生成速度 ≥ 程序解析速度 ≥ 用户阅读速度
```

当解析器到达 `<bridge/>` 时，post-bridge 内容大概率已全部到达并缓冲在内存中。此时程序立即执行三个动作：

```
到达 <bridge/>
    │
    ├─ ① 触发下一轮 API 调用（不等待用户）
    │
    ├─ ② 快速遍历缓冲区中的 post-bridge 内容：
    │      - 按分支索引 bridge_text（为每个 <branch name> 收集文本）
    │      - 检查禁止元素（<choice>/<set>/<checkpoint> 在 bridge 后 → format_error）
    │      - 记录裸 <seg>（单路径场景的默认分支文本）
    │
    └─ ③ 继续展示 post-bridge 内容（用户阅读中）
```

**为什么不需要多线程**：步骤②是纯文本遍历，耗时远小于步骤①的网络 I/O 和步骤③的用户阅读速度。API 调用本身是异步 I/O（SSE 长连接）。单线程顺序执行即可——扫描在毫秒级完成。

**实际效果**：当用户还在阅读 pre-bridge 最后几段、或面对 `<choice>` 选项思考时，程序已经完成了 post-bridge 的扫描、验证和索引。用户选择后，对应的 bridge_text 立即可用，下一轮 API 已经在路上。

### 2.6 双层处理线：预处理 + 实际处理

解析器内部维护两条线，一前一后推进：

```
token 流 → ┌─ 预处理线（快，不等待）──┐
           │  结构索引、分支区间映射      │
           │  元素类型识别、格式校验      │
           │  永远提前于实际处理线        │
           └──────────┬───────────────┘
                      │ 索引/映射
                      ▼
           ┌─ 实际处理线（按需等待）──┐
           │  展示 seg、应用 set        │
           │  在 choice 处暂停等待用户   │
           │  用索引直接定位目标分支      │
           └──────────────────────────┘
```

**预处理线**（只做结构，不做决策）：
- 识别每个元素的位置和类型
- 为 `<branch name="X">` 建立区间索引：`{"betrayal_path": (line_45, line_77), ...}`
- 检查格式规则（bridge 后禁止 choice/set/checkpoint）
- 不评估条件、不匹配分支——这些都是实际处理线的决策

**实际处理线**（做决策，按需等待）：
- 逐段展示叙事（略快于用户阅读）
- 在 `<choice>` 处暂停，等待用户输入
- 用户选择后，从预处理索引直接定位到对应 `<branch>` 区间，跳过不匹配的分支
- 遇到 `<set>` 时，用当前 state + choice_dict 评估条件

**关键价值**（以选项接分支为例）：

```
不预处理：用户选择 → 逐行扫描第一个<branch> → 不匹配 → 继续扫描
          → 找到匹配分支 → 开始展示  （用户感知延迟）

有预处理：用户选择 → 查索引 {"branch_a": (45,77), "branch_b": (78,110)}
          → 选了 branch_b → 直接跳到 line_78  （瞬间）
```

> 预处理线是单线程内的快速扫描——不引入多线程复杂度。它利用"解析快于阅读"的时间差，在用户阅读当前内容时悄悄完成后续内容的索引。

## §3 架构总览

```
┌─────────────────────────────────────────────────────┐
│ GameLoop (编排器)                                     │
│                                                       │
│   start_round1() / continue_round(choice_key)         │
│     │                                                 │
│     ├─ PromptBuilder → Round N context                │
│     ├─ ContextManager → messages 数组                 │
│     ├─ ApiClient.stream_chat() → token 流             │
│     ├─ StreamingXmlParser → 逐行解析 → 事件流          │
│     ├─ Display → 用户可见输出                          │
│     ├─ GameState → 即时状态变更                        │
│     └─ Observer ← RoundRecord（每轮结束）              │
│                                                       │
└─────────────────────────────────────────────────────┘
```

## §4 模块设计

### 4.1 StreamingXmlParser（新模块）

**文件**：`src/storyloom/streaming_parser.py`

**职责**：接收行（已剥离 `NNN| ` 前缀），逐行识别元素，产出事件。

**状态机**：

```
状态: IN_STORY | IN_BRANCH | IN_CHECKPOINT | IN_CHOICE | POST_BRIDGE
```

**事件类型**：

```
SEGMENT(text)            — 叙事段，应立即展示/缓冲
CHOICE_BEGIN(id)         — 进入 choice 容器
OPT(key, branch, text)   — 单个选项
CHOICE_END               — choice 结束，GameLoop 暂停等待输入
SET(var, op, val, if)    — 状态变更，立即应用
CHECKPOINT(node, summary)— 节点记录
ROUTE(if, target)        — 路由条目
BRIDGE                   — 桥接触发点
BRANCH_ENTER(name)       — 进入分支容器
BRANCH_EXIT              — 退出分支容器
STORY_BEGIN              — <story> 开始
STORY_END                — </story> 结束
PARSE_ERROR(msg)         — 格式错误
```

**处理逻辑**：

```python
class StreamingXmlParser:
    def feed_line(self, line: str) -> list[ParseEvent]:
        """处理一行，返回零到多个事件。"""
        # 用简单正则识别元素类型（不依赖完整 XML 解析）
        # <seg>text</seg>        → SEGMENT
        # <set var="X" op="+" /> → SET
        # <bridge/>              → BRIDGE
        # <choice id="X">        → CHOICE_BEGIN
        # </choice>              → CHOICE_END
        # <branch name="X">      → BRANCH_ENTER
        # </branch>              → BRANCH_EXIT
        # <checkpoint node="X">  → CHECKPOINT
        # <route if="X" />       → ROUTE
        # ...
```

逐行正则匹配而非完整 XML 解析——这恰好利用了 `NNN| ` 行号格式的优势。每行是自包含的 XML 片段。

**最终结果收集**：解析完成后，`get_result()` 返回 `ParsedOutput`（与现有 `XmlParser.parse()` 返回类型兼容，但数据是在解析过程中逐步填充的）。

### 4.2 XmlParser（修改）

**文件**：`src/storyloom/xml_parser.py`

**改动**：`_extract_bridge_text()` 改为接受 `current_branch` 参数，过滤逻辑统一：

```python
@staticmethod
def _extract_bridge_text(post_children, current_branch=None):
    """Extract bridge text from post-bridge elements.

    Always filters by current_branch when provided. If current_branch
    is None/empty, extracts from bare <seg> elements (not inside any
    <branch>). This is the single-path case.
    """
    texts = []
    for el in post_children:
        if el.tag == "seg":
            if not current_branch:  # bare seg = default path
                if el.text:
                    texts.append(el.text.strip())
        elif el.tag == "branch":
            if current_branch and el.get("name") == current_branch:
                for seg_el in el.findall("seg"):
                    if seg_el.text:
                        texts.append(seg_el.text.strip())
    return "\n".join(texts)
```

`ParsedOutput.bridge_text` 保留全量（`parse()` 中不传 `current_branch`），用于调试。分支过滤由 ContextManager 在存储时调用。

### 4.3 ContextManager（修改）

**文件**：`src/storyloom/context_manager.py`

**改动**：`add_round()` 接受 `selected_branch`，存储时过滤 bridge_text。

```python
def add_round(self, user_content, assistant_content, selected_branch=None):
    # ... existing ...
    self._last_bridge_text = self._extract_bridge_from_xml(
        assistant_content, selected_branch
    )
    self._maybe_compress()
```

`set_round1()` 不变——Round 1 没有上一轮选择，bridge_text 为空是正确的。

### 4.4 ApiClient（修改）

**文件**：`src/storyloom/api_client.py`

**改动**：`stream_chat()` 返回类型从 `str` 改为 `ApiResult`。

```python
@dataclass
class ApiResult:
    content: str
    ttft: float | None       # seconds to first token
    tokens: dict | None      # {"prompt": N, "completion": N, "total": N}
```

在 SSE 循环中记录首 token 时间和最后的 usage 信息。

### 4.5 GameLoop（重构）

**文件**：`src/storyloom/game_loop.py`

**改动**：

a) **RoundRecord + observer**：
```python
@dataclass
class RoundRecord:
    round_number: int
    messages_sent: list[dict]
    raw_response: str
    parsed: ParsedOutput | None
    ttft: float | None
    tokens: dict | None
    timestamp: str
    node: str | None
    selected_branch: str | None

# __init__ 增加 observer 参数
def __init__(self, ..., observer: Callable[[RoundRecord], None] | None = None):
```

b) **流程重构**：`continue_round()` 内部改为清晰的顺序流程，反映缓冲式读取：

```
continue_round(choice_key):
  [基于上一轮结果]
  1. choice_dict ← 上一轮 choice_id + choice_key
  2. 应用上一轮全部 <set>（用 choice_dict 求值条件）
  3. 评估 <route> → 推进 current_node
  [组装当前轮]
  4. build_round_n(..., bridge_text=ContextManager.get_last_bridge_text(), ...)
  5. messages ← ContextManager.get_messages() + Round N context
  [API + 流式解析]
  6. ApiClient.stream_chat(messages) → 开始接收 token 流
  7. 逐行喂给 StreamingXmlParser，随到随处理：
     Pre-bridge:
       SEGMENT → 展示/缓冲
       CHOICE_BEGIN/OPT/CHOICE_END → 缓存选项，暂停等待玩家
       SET → GameState.apply_set() 即时应用
       CHECKPOINT/ROUTE → 记录
     ── <bridge/> ──
       ① 触发下一轮 API 调用
       ② 预处理线已在后台完成 post-bridge 的结构索引：
          - 每个 <branch name> 的起止行区间
          - 裸 <seg>（默认路径）的位置
          - 禁止元素检查 → self._format_error
       ③ 实际处理线：按用户所选分支的索引，直接展示对应 seg
          （用户阅读中；索引已就绪，无需等待）
  8. ContextManager.add_round(context, response, selected_branch)
  9. notify observer → RoundRecord
```

c) **修复 format_error**：步骤 7 中解析异常时设置 `self._format_error`，下一轮 `build_round_n()` 会将其注入 prompt。

d) **set 处理统一**：不再区分 conditional/unconditional。在步骤 2（上一轮 sets）中，所有 set 都用 choice_dict 求值——条件满足的执行，不满足的跳过，choice_dict 未就绪的条件自然跳过。在步骤 7（当前轮 sets 流式处理）中，由于 `<choice>` 在文档顺序中出现在条件 set 之前，流式到达条件 set 时 choice_dict 已就绪。

### 4.6 run_full_test.py（重写）

**文件**：`tests/run_full_test.py`

全量重写。删除所有手工实现的 GameLoop 逻辑。只做：

```python
# 1. 配置
gs = GameState(STORY_CONFIG)
api_client = ApiClient()

# 2. observer：保存每轮完整数据
def save_round(record: RoundRecord):
    out = OUT_DIR / f"round-{record.round_number}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "messages.json").write_text(json.dumps(
        record.messages_sent, ensure_ascii=False, indent=2))
    (out / "response.txt").write_text(record.raw_response)
    (out / "metrics.json").write_text(json.dumps({
        "round": record.round_number,
        "ttft": record.ttft,
        "tokens": record.tokens,
        "node": record.node,
        "branch": record.selected_branch,
        "timestamp": record.timestamp,
    }, ensure_ascii=False, indent=2))

# 3. GameLoop
game_loop = GameLoop(
    story_config=STORY_CONFIG,
    outline_text=OUTLINE,
    api_client=api_client,
    game_state=gs,
    current_node="ch1_bar",
    goal=goal_map["ch1_bar"],
    observer=save_round,
)

# 4. 循环
result = game_loop.start_round1()
for rn in range(2, max_rounds + 1):
    options = game_loop.get_available_options()
    choice = pick(options) if options else None
    result = game_loop.continue_round(choice_key=choice)
    if result.ending_triggered:
        break
```

### 4.7 main.py（修改）

**文件**：`src/storyloom/main.py`

**改动**：
- 增加 `--debug` flag
- `run_game()` 注入 observer：

```python
def run_game(..., debug=False):
    observer = make_debug_observer(OUT_DIR) if debug else None
    game_loop = GameLoop(..., observer=observer)
```

## §5 追加提示词与错误传递

状态变更和格式问题通过以下机制在轮次间传递：

| 信息 | 来源 | 注入位置 | 注入条件 |
|------|------|---------|---------|
| **rejected_changes** | `GameState.apply_set()` 拒绝原因 | Round N 消息中 "Rejected state changes from last round:" 节 | 仅当非空 |
| **format_error** | StreamingXmlParser 解析异常 | Round N 消息中 "Format reminder:" 节 | 仅当存在 |

两者在 `PromptBuilder.build_round_n()` 中作为可选参数，条件注入。`build_round_n()` 格式不变。

**当前缺陷**：`GameLoop._format_error` 声明但从未赋值。流式解析器修复此问题——解析异常时设置 `_format_error`，下一轮注入。

每轮开始时，上一轮的 `_rejected_changes` 和 `_format_error` 被新值替换（不累积）。

## §6 不变模块与并行迁移

| 模块 | 说明 |
|------|------|
| `prompt_builder.py` | 模板与 `round1-linenum.txt` 一致 |
| `config.py` | 常量定义正确 |
| `xml_parser.py` (parse 主流程) | 解析逻辑正确，仅改 bridge_text 提取 |

### 并行迁移注意事项

`docs/superpowers/specs/2026-07-06-i18n-gettext-design.md` 将同时执行，涉及以下模块变更：

| 模块 | i18n 改动 | 本方案影响 |
|------|----------|-----------|
| `display.py` | 删除 `UI`/`t()`/`language`，全部改用 `_()` | 无冲突——GameLoop 通过高层方法（`show_segments`、`show_options`）调用 display，不直接使用 `display.t()` |
| `main.py` | `display.t("key")` → `_("English")`；删除 `language` 参数传递 | 本方案的 `--debug` + observer 注入应**在 i18n 改动完成后**叠加 |
| `co_create.py` | `display.t("key")` → `_("English")` | 本方案不修改 co_create.py |

**实施建议**：i18n 迁移先完成 → 本方案在此基础上叠加 `main.py` 的 `--debug` flag 和 observer 注入。

## §7 实现顺序

| 步骤 | 模块 | 内容 |
|------|------|------|
| 1 | `xml_parser.py` | `_extract_bridge_text` 增加 branch 过滤 |
| 2 | `context_manager.py` | `add_round` 接受 `selected_branch` |
| 3 | `api_client.py` | `stream_chat` 返回 `ApiResult`（含 TTFT + tokens） |
| 4 | `streaming_parser.py` | **新模块**：行号格式的流式逐行解析器 |
| 5 | `game_loop.py` | RoundRecord + observer + 流程重构 + fix format_error |
| 6 | `main.py` | `--debug` flag + observer 注入 |
| 7 | `run_full_test.py` | 全量重写为 GameLoop 驱动 |
| 8 | 回归测试 | 现有 unit tests + integration tests + 端到端 |

## §8 验证标准

1. **现有 113 个单元测试全部通过**
2. **`run_full_test.py` 3 轮端到端**：每轮数据保存到 `tests/data/output/full-test/round-N/`
3. **bridge_text 正确性**：选 branch X → 下一轮 bridge_text 只含 X 的内容
4. **observer 隔离**：observer 异常不中断游戏循环
5. **format_error 生效**：模拟含格式错误的 LLM 输出 → 下一轮 prompt 含纠正提示
6. **`main.py --quick --debug`**：手动交互 ≥2 轮，数据完整保存
