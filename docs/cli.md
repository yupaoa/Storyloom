# CLI Test Harness & Observer System

> 面向维护者。CLI 是纯测试工具，观察者是它的全部输出机制。

## 设计理念

CLI 不做游戏交互——没有菜单、没有共创、没有玩家输入。它只做一件事：**创建 GameLoop → 注入观察者 → 自动运行 N 轮 → 退出**。

观察者是 CLI 与引擎之间的唯一桥梁。引擎每完成一轮，通知所有观察者；观察者决定如何处理数据（写文件、打印终端、发网络请求……）。

```
┌──────────┐     RoundRecord      ┌──────────────┐
│ GameLoop │ ─────────────────→   │ make_debug    │ → tests/data/output/debug-{ts}/round-{N}/
│          │                      ├──────────────┤
│          │ ─────────────────→   │ make_print    │ → stderr: [Round 1] node=... ✓
└──────────┘                      └──────────────┘
```

## 快速开始

```bash
# 最简：运行 1 轮，终端输出摘要
python -m src.storyloom.main --quick --print

# 运行 3 轮，每轮数据落盘 + 终端摘要
python -m src.storyloom.main --quick --debug --print --rounds 3

# 详细模式：显示段数和 token 用量
python -m src.storyloom.main --quick --print --verbose --rounds 5

# 指定每轮的选择序列（1-indexed）
python -m src.storyloom.main --quick --debug --rounds 4 --choices 2,1,1,2
```

## 参数参考

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `--quick` | flag | — | **必需**。使用内置默认故事（赛博朋克）。共创功能不在 CLI 中 |
| `--debug` | flag | off | 每轮数据写入 `tests/data/output/debug-{timestamp}/` |
| `--print` | flag | off | 每轮完成时在 stderr 打印一行摘要 |
| `--verbose`, `-v` | flag | off | 配合 `--print`，摘要中包含段数和 token 统计 |
| `--rounds N` | int | 1 | 运行轮数。自动选第一个选项（除非指定 `--choices`） |
| `--choices 1,2,1` | str | — | 逗号分隔的选择序列（1-indexed），覆盖自动选择 |
| `--lang zh-CN\|en` | str | zh-CN | UI 字符串语言 |

## 观察者架构

### RoundRecord

引擎每轮完成后生成一个 `RoundRecord` 数据快照，传给所有观察者：

```python
@dataclass
class RoundRecord:
    round_number: int              # 当前轮次编号
    messages_sent: list[dict]      # 发送给 API 的完整 messages 数组
    raw_response: str              # LLM 原始输出文本
    parsed: ParsedOutput | None    # 解析结果（解析失败时为 None）
    ttft: float | None             # 首 token 延迟（秒）
    tokens: dict | None            # {"prompt": N, "completion": N, "total": N}
    timestamp: str                 # ISO 8601 时间戳
    node: str | None               # 当前大纲节点 ID
    selected_branch: str | None    # 玩家选择的分支名（无选择时为 None）
```

### 内置观察者

所有观察者工厂函数位于 `src/storyloom/cli_utils.py`。

#### `make_debug_observer(output_dir)` — 文件系统

每轮数据写入结构化目录：

```
tests/data/output/debug-20260707-143052/
├── round-1/
│   ├── messages.json    # 完整 messages 数组（含 Round 1 prompt）
│   ├── response.txt     # LLM 原始 XML 输出
│   ├── metrics.json     # 时间、token、节点、分支
│   ├── parsed.json      # 结构化解析结果
│   └── analysis.md      # 人类可读摘要
├── round-2/
│   └── ...
└── round-3/
    └── ...
```

**各文件用途：**

| 文件 | 调试场景 |
|------|---------|
| `messages.json` | 检查 Prompt 是否正确组装；上下文窗口大小是否合理 |
| `response.txt` | 检查 LLM 原始输出格式；XML 是否合法 |
| `metrics.json` | 性能分析：TTFT 趋势、token 消耗曲线 |
| `parsed.json` | 检查解析是否正确：段数、桥位置、选项、状态变更 |
| `analysis.md` | 快速浏览每轮概况，无需打开 JSON |

#### `make_print_observer(stream, verbose)` — 终端

每轮一行摘要输出到 stderr：

```
# 普通模式
[Round 1]  node=ch1_intro  ttft=1.2s  ✓
[Round 2]  node=ch2_meeting  ttft=0.9s  ✓

# verbose 模式
[Round 1]  node=ch1_intro  segs=8  ttft=1.2s  tok=1520  ✓
[Round 2]  node=ch2_meeting  segs=12  ttft=0.9s  tok=1840  ✓

# 解析失败
[Round 3]  node=?  ✗
```

### 观察者注入

```python
# 方式 1：构造时注入列表（推荐）
observers = [
    make_debug_observer("tests/data/output/my-test"),
    make_print_observer(verbose=True),
]
game_loop = GameLoop(..., observers=observers)

# 方式 2：单个回调（向后兼容）
game_loop = GameLoop(..., observer=make_print_observer())
```

观察者异常被静默捕获，不会中断游戏循环。

## 维护工作流

### 场景 1：调试 Prompt 是否正确

```bash
python -m src.storyloom.main --quick --debug --rounds 1
cat tests/data/output/debug-*/round-1/messages.json | python3 -m json.tool | head -100
```

检查 Round 1 prompt 中是否包含正确的格式规范、故事上下文、状态变量。

### 场景 2：分析解析失败

```bash
python -m src.storyloom.main --quick --debug --print --rounds 5
# 第 3 轮报错
cat tests/data/output/debug-*/round-3/response.txt
# 检查 LLM 原始输出 — XML 是否缺少 <bridge/>？是否有非法元素在 bridge 之后？
```

### 场景 3：追踪 token 消耗

```bash
python -m src.storyloom.main --quick --debug --rounds 10
# 用一行命令提取每轮 token 用量
for f in tests/data/output/debug-*/round-*/metrics.json; do
  echo "$(dirname $f | xargs basename): $(python3 -c "import json; d=json.load(open('$f')); print(d.get('tokens',{}).get('total','?'))")"
done
```

### 场景 4：对比两次运行的差异

```bash
# 运行 A：默认选项
python -m src.storyloom.main --quick --debug --rounds 3
mv tests/data/output/debug-* tests/data/output/run-A

# 运行 B：不同选择序列
python -m src.storyloom.main --quick --debug --rounds 3 --choices 2,2,1
mv tests/data/output/debug-* tests/data/output/run-B

# 对比
diff <(cat tests/data/output/run-A/round-2/parsed.json | python3 -m json.tool) \
     <(cat tests/data/output/run-B/round-2/parsed.json | python3 -m json.tool)
```

### 场景 5：在 `--debug` 模式下容错运行

```bash
# 即使某轮失败也继续（数据已保存，失败轮无新数据）
python -m src.storyloom.main --quick --debug --print --rounds 10
# 输出示例：
# [Round 1] node=ch1_intro ✓
# [Round 2] node=ch2_meeting ✓
# [Round 3] ✗ parse error
# [Round 4] node=ch2_meeting ✓  ← 继续运行
# Completed 10 round(s) — 1 failed.
```

非 `--debug` 模式下，任何失败立即退出。

## 自定义观察者

观察者就是一个接受 `RoundRecord` 的函数：

```python
from storyloom.core.game_loop import RoundRecord

def my_observer(record: RoundRecord) -> None:
    """发送 round 数据到外部监控系统。"""
    import requests
    requests.post("http://monitor.local/api/rounds", json={
        "round": record.round_number,
        "ttft": record.ttft,
        "tokens": record.tokens,
        "parse_ok": record.parsed is not None,
    })

# 注入
game_loop = GameLoop(..., observers=[my_observer])
```

更复杂的例子（累积统计）：

```python
class TokenTracker:
    """累积追踪 token 消耗。"""

    def __init__(self):
        self.total_prompt = 0
        self.total_completion = 0
        self.rounds = 0

    def __call__(self, record: RoundRecord) -> None:
        self.rounds += 1
        if record.tokens:
            self.total_prompt += record.tokens.get("prompt", 0)
            self.total_completion += record.tokens.get("completion", 0)

    def summary(self) -> str:
        return (
            f"Rounds: {self.rounds}  "
            f"Prompt: {self.total_prompt}  "
            f"Completion: {self.total_completion}  "
            f"Avg/round: {(self.total_prompt + self.total_completion) / max(1, self.rounds):.0f}"
        )

tracker = TokenTracker()
game_loop = GameLoop(..., observers=[tracker])
# ... 运行 N 轮 ...
print(tracker.summary())
```

## 代码位置

| 文件 | 内容 |
|------|------|
| `src/storyloom/cli_utils.py` | `make_debug_observer()`, `make_print_observer()`, `_build_analysis_lines()` |
| `src/storyloom/main.py` | CLI 入口、参数解析、GameLoop 创建和运行 |
| `src/storyloom/core/game_loop.py` | `RoundRecord` 数据类、`_notify()` 通知机制 |
| `tests/prompt_lab/run_full_test.py` | 使用 `make_debug_observer` 的多轮集成测试脚本 |
