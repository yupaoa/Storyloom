# dev_cli

极简 CLI 游戏界面 + 开发者观察工具。删除此目录即可从发布版本移除。

## 快速开始

```bash
python -m storyloom.dev_cli              # 观察者模式（默认）：instant 展示 + 写 dev_output/
python -m storyloom.dev_cli play         # 纯游戏模式：auto 展示（每段 1.0s）
python -m storyloom.dev_cli play manual  # 纯游戏模式：manual 展示（Enter 推进）
python -m storyloom.dev_cli play instant # 纯游戏模式：instant 展示（无延迟）
```

## 展示模式

| 模式 | 行为 | 默认场景 |
|------|------|---------|
| `instant` | 无延迟，全速输出 | 观察者模式 |
| `auto` | 每段后 1.0s 间隔 | 纯游戏模式 |
| `manual` | 每段后等待 Enter | 手动推进 |

## 快捷键

| 按键 | 行为 |
|------|------|
| `1`–`9` | 选择分支 |
| `Space` | 切换暂停（展示冻结，后台 API 继续获取） |
| `Ctrl+C` | 退出 |
| `q` / `quit` | 选项时退出 |

选项阶段自然暂停（等待输入），无需额外暂停操作。

## 架构

```
Receiver (fast)              Deque buffer           Display (paced)
─────────────────────       ──────────────         ──────────────────
for event in gen:           collections.deque      _display_loop()
  event_queue.append()      event_queue.pop()      instant: no delay
  if options → inline                               auto:    1.0s/seg
                                                    manual:  Enter/seg
```

引擎通过 `queue.Queue` + daemon 线程预取 API 响应，Receiver 全速入队，
Display 按选定节奏出队展示。两者通过 `collections.deque` 解耦。

## 观察者输出

`dev_output/` 目录（已 gitignore）：

| 文件 | 内容 | 写入模式 |
|------|------|---------|
| `prompts.txt` | 发送给 LLM 的完整 messages 数组 | 覆盖 |
| `responses.txt` | LLM 返回的原始文本（含 ttft / token 统计） | 覆盖 |
| `checks.txt` | 每轮检查摘要（segment、checkpoint、set、choice、TTFT） | 追加 |

`prompts.txt` 和 `responses.txt` 始终只保留最新一轮。
`checks.txt` 跨轮累积。格式错误可通过下一轮的 `prompts.txt` 自查。

## 文件结构

```
dev_cli/
    __init__.py       — 导出：dev_main, DevObserver
    __main__.py       — 入口点
    observer.py       — DevObserver（3 个固定文件输出）
    game_driver.py    — 游戏流程驱动 + CLI I/O + PauseHandler + deque 缓冲
    README.md         — 本文件
```
