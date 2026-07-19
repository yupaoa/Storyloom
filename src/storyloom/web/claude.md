# Storyloom Web — Claude 上下文文件

> 自动加载于进入 `src/storyloom/web/` 目录时。
> 2026-07-13 | 实施完成，已测试通过

---

## 项目定位

Storyloom Web 是 Storyloom 引擎的浏览器 UI 层。引擎是库，Web 是消费者——通过公开 API（`GameSession` / `CoCreateFlow` / `GameLoop`）调用引擎，不修改引擎核心逻辑。

## 已确认的引擎接口契约

### 调用顺序（不能乱）

```
CoCreateFlow:
  start() → send()×N → generate()  （严格顺序）

GameLoop:
  start_game() → stream_round()×N  （不调 start_game 就调 stream_round → RuntimeError）
```

### stream_round() 事件类型

10 种事件：`story_begin` / `story_end` / `token` / `segment` / `bridge` / `options` / `state` / `error` / `ending` / `done`

### ⚠️ 关键类型细节（实地踩坑确认）

| 字段 | 实际类型 | 容易误以为 |
|------|---------|-----------|
| `options.choices[].conditions` | `dict[str, str\|null]`（branch→condition） | `list[str\|null]` |
| `state.changes[].val` | 始终 `str` | `int` |
| `ending.adventure_log` | 始终 `null` | 直接可用 |
| `segment.branch` | `str \| None` | 默认 `"main"` |
| `variables[].initial` | 取决于 `type`（number→int, string→str, list→list） | JSON 往返可能丢类型 |
| Choice key | 1-indexed 字符串 `"1"` | 0-indexed int |

### Choice 暂停机制

`gen.send(key)` 必须在迭代 `stream_round()` 的**同一线程**中调用。解决方案：后台 daemon 线程 + `queue.Queue` 桥接。

## 架构

```
Browser (原生 HTML/CSS/JS, 零框架, Hash SPA)
    │
    ├── SSE (text/event-stream)  ← /api/game/{id}/stream
    └── POST (JSON)              ← /api/co-create/*, /api/game/{id}/choice, /api/saves/*
    │
FastAPI (server.py) + sessions.py (内存会话)
    │
Storyloom Engine (core/)
```

## 文件清单

```
src/storyloom/web/
├── claude.md               ← 本文件
├── DESIGN.md               ← 原始设计文档（部分过时，以本文件为准）
├── ISSUES.md               ← 13 个已修复问题的根因记录
├── TASKS.md                ← 原始 7 步实施计划
├── __init__.py
├── __main__.py             ← python -m storyloom.web 入口
├── server.py               ← FastAPI (15 端点) + SSE + uvicorn
├── sessions.py             ← co_create/game 内存会话管理
└── static/
    ├── index.html           ← SPA 入口
    ├── css/main.css         ← 暗色终端主题
    └── js/
        ├── api.js           ← fetch 封装 (post/get/del)
        ├── state.js         ← GameState + T 翻译字典
        ├── display.js       ← segment/options/error/adventure-log 渲染
        ├── sse-client.js    ← SSE 消费 + choice 注入 + close 安全
        └── router.js        ← Hash 路由 + 游戏循环 + 展示速度控制
```

## 关键实现细节

### 展示速度控制

速度预设（fast/normal/slow/instant/manual）在**主菜单**选择，存储在 `GameState.speedPreset`。游戏内固定不变——不做热切换（曾尝试热切换，`_segTimer`/`_manualWaiting` 状态交织产生边界 bug，见 ISSUES.md #12）。

实现：`_enqueue()` → `_processNext()` → `setTimeout` 链。Manual 模式用 `_manualWaiting` 标志阻止新 segment 自动触发显示。

### token 事件

**不显示。** token 是 LLM 原始输出（含 XML 标签、行号前缀），只用于 debug。显示只走 `segment` 事件。

### conditions 字段

引擎输出为 `{branch_name: condition_string | null}` 的 **dict**。前端 `showChoices()` 用 `conds[branch]` 取值，**不能**当数组用 `.every()`。

### SSE close() 安全

`SSEClient.close()` 手动调用 `_resolve("closed")`，不依赖 `onerror` 触发（关闭时间早于 onerror 触发时间，导致 Promise 永不 resolve）。

---

## API 路由

```
POST /api/co-create/start        → {"session_id", "phase", "prompt"}
POST /api/co-create/send         ← {"session_id", "message"}  → {"reply", "phase"}
POST /api/co-create/generate     ← {"session_id"}  → {"story_config", "outline_text", "outline_nodes"}
POST /api/co-create/abort        ← {"session_id"}  → {"status"}

POST /api/game/new               ← {story_config, outline_text, outline_nodes}  → {game_id, status}
GET  /api/game/{id}/stream       → SSE (text/event-stream)
POST /api/game/{id}/choice       ← {"key": "1"}  → {"status"}   ⚠️ 1-indexed string
POST /api/game/{id}/retry        → {"status"}
GET  /api/game/{id}/state        → {round_count, current_node, outline_nodes, state_vars, ending_flag}
GET  /api/game/{id}/adventure-log → {"text", "pending"}
POST /api/game/{id}/save         → {"status", "label", "round_count"}

GET  /api/saves                  → [{label, round_count, ...}]
POST /api/saves/{label}/load     → {game_id, status, ...}
DELETE /api/saves/{label}        → {"status"}
```

## 本地运行

```bash
pip install -e .            # 确保 .mo 编译
python -m storyloom.web     # → http://127.0.0.1:8000
```
