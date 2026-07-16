# dev_cli

极简 CLI 游戏界面 + 开发者观察工具。删除此目录即可从发布版本移除。

## 快速开始

```bash
python -m storyloom.dev_cli                  # 游玩模式（默认）：手动 pacing，无文件输出
python -m storyloom.dev_cli --observer        # 观察者模式：手动 pacing + 写 dev_output/
python -m storyloom.dev_cli -o --instant      # 观察者模式：instant 展示（无延迟，不可切换）
```

## 模式

### 游玩模式（默认）

零参数入口。手动 pacing（每段按 Enter 推进），Tab 切换为 auto。不写任何文件。

### 观察者模式（`--observer` / `-o`）

录制每轮原始数据到 `dev_output/`（已 gitignore）。默认行为与游玩模式一致（手动 pacing，Tab 可切换）。`--instant` 禁用所有 pacing 和游戏内切换，全速输出。

| 参数 | 展示 | Tab 切换 | 录制 |
|------|------|----------|------|
| （无，默认） | manual | ✅ | — |
| `--observer` | manual | ✅ | dev_output/ |
| `-o --instant` | instant | — | dev_output/ |

## 快捷键

| 按键 | 行为 |
|------|------|
| `1`–`9` | 选择分支 |
| `Tab` | 切换 auto ↔ manual 展示模式（instant 下无效） |
| `Ctrl+C` | 退出 |
| `q` / `quit` | 选项时退出 |

auto ↔ manual 切换本身就是暂停机制——切到 manual 自然停止自动推进。
选项阶段自然暂停（等待输入），无需额外操作。

## 架构

```
Receiver (fast)              Deque buffer           Display (paced)
─────────────────────       ──────────────         ──────────────────
for event in gen:           collections.deque      _display_loop()
  event_queue.append()      event_queue.pop()      instant: no delay
  if options → inline                               auto:    fixed delay/seg
                                                    manual:  Enter/seg
```

引擎通过 `queue.Queue` + daemon 线程预取 API 响应，Receiver 全速入队，
Display 按选定节奏出队展示。两者通过 `collections.deque` 解耦。

## 观察者输出（两阶段录制）

`dev_output/` 目录（已 gitignore）：

| 文件 | 阶段 | 内容 | 写入模式 |
|------|------|------|---------|
| `prompts.txt` | 提交时 | 发送给 LLM 的完整 messages 数组 | 覆盖 |
| `responses.txt` | 接收完 | LLM 返回的原始文本（含 ttft / token） | 覆盖 |
| `checks.txt` | 接收完 | 每轮解析摘要（segment、checkpoint、set、choice、TTFT） | 追加 |

**两阶段录制契约：**

```
Phase 1（Prompt 提交时） → write_prompt_at_send()
    prompts.txt   = 完整 messages 数组
    responses.txt = "[waiting for response...]"（清空旧数据）

Phase 2（响应完整接收 + 解析后）→ record_round()
    responses.txt = 原始 LLM 文本 + ttft / token 统计
    checks.txt   += 解析摘要
```

`prompts.txt` 和 `responses.txt` 始终只保留最新一轮。
`checks.txt` 跨轮累积。格式错误可通过下一轮的 `prompts.txt` 自查。

## 文件结构

```
dev_cli/
    __init__.py       — 导出：dev_main, DevObserver
    __main__.py       — 入口点
    observer.py       — DevObserver（两阶段录制，3 个固定文件输出）
    game_driver.py    — 游戏流程驱动 + CLI I/O + DisplayController + deque 缓冲
    README.md         — 本文件
```
