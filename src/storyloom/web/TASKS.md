# Storyloom Web — 实施任务清单

> 2026-07-13 | 按依赖链排序 | 每步完成必须验证

---

## ⚠️ 全局注意事项（写代码时反复检查）

### 引擎调用顺序
- [ ] `GameLoop.start_game()` 必须在 `stream_round()` **之前**调用。不调→RuntimeError。
- [ ] `CoCreateFlow.send()` **之前**必须先 `start()`。不调→RuntimeError。
- [ ] `send()` 参数不能为空字符串。API 层要在调引擎之前拦截。

### Choice 双向通信（最容易出错的点）
- [ ] `gen.send(key)` 必须在迭代 generator 的**同一线程**中执行。用 `queue.Queue` + daemon 线程桥接。
- [ ] Choice key 是 **1-indexed 字符串**：`"1"`, `"2"`, `"3"`。不是 `0, 1, 2`，不是 `int`。
- [ ] 服务端收到 choice key 后必须校验：是数字、在选项范围内。

### JSON 序列化（历史 Bug 来源）
- [ ] Python `None` → JSON `null`。前端检查 `!== null` 而非 `!data.field`（会误判空字符串）。
- [ ] `segment.branch` 是 `None`（裸 seg）或 `str`（命名 branch）。前端不要假定默认值是 `"main"`。
- [ ] `options.choices[].conditions[i]` 是 `null` 时表示**无条件**（选项可用）。非 null 的字符串是置灰条件。
- [ ] `state.changes[].val` **始终是字符串**。不要做 `parseInt()`。
- [ ] `ending.adventure_log` **始终是 `null`**。冒险日志必须单独调 `GET /adventure-log` 获取。
- [ ] `outline_nodes[].routes` 为 `[]`（空列表）时是该节点是结局——这是合法值，不是缺失数据。
- [ ] `variables[].initial` 类型取决于 `type` 字段：number→int, string→str, list→list。
- [ ] `story_config.characters` 是含 `\n` 的多行文本，不是数组。
- [ ] SSE `data:` 行可能为空字符串。`e.data` 为空时跳过不处理。

### 服务端状态管理
- [ ] `_co_create_flows` 和 `_game_sessions` 是内存 dict。不持久化，重启丢失。单用户场景够用。
- [ ] 同一 game_id 不能同时有两个 `stream_round()` 在跑。用 `round_active` 标志防重入。
- [ ] 每轮结束（`done` 事件）后，`choice_queue` 和 `event_queue` 里的残留数据要清干净。

### i18n
- [ ] `.mo` 文件必须存在（`pip install -e .` 执行过一次）。否则 `_()` 静默回退英文。
- [ ] 前端 UI 文本需要一套独立的 JS 翻译字典，与 `.po` 保持同步。
- [ ] 语言切换在游戏中锁定——`story_config.language` 已写入 LLM 上下文，不可改。

### 文件边界
- [ ] 不修改 `src/storyloom/core/`、`parser/`、`io/`、`config.py`、`i18n.py`。只读调用。
- [ ] Web 文件全部放在 `src/storyloom/web/` 下。

---

## Step 1：服务器骨架

**目标**：FastAPI 启动 + 静态文件服务 + 空白页面

### 文件
- [ ] `__init__.py` — 包标记
- [ ] `server.py` — FastAPI app、`/health`、静态文件挂载、uvicorn 启动
- [ ] `static/index.html` — 最小 HTML 壳（`<div id="app">` + 引入 JS/CSS）
- [ ] `static/css/main.css` — 暗色背景、CSS 变量（颜色、字体）

### 验证
```bash
curl http://localhost:8000/health
# → {"status": "ok"}

curl http://localhost:8000/
# → 返回 index.html 内容
```

---

## Step 2：共创阶段

**目标**：浏览器端完成完整共创流程（想法 → Q&A → 生成设定）

### 文件
- [ ] `sessions.py` — `co_create_sessions: dict[str, CoCreateFlow]`、创建/获取/删除
- [ ] `server.py` 新增路由：
  - `POST /api/co-create/start` → `flow.start()`
  - `POST /api/co-create/send` → `flow.send()` （⚠️ 空输入拦截）
  - `POST /api/co-create/generate` → `flow.generate()` （⚠️ 捕获 CoCreationAborted）
  - `POST /api/co-create/abort` → `flow.abort()`
- [ ] `static/js/api.js` — `postJSON(url, body)` 基础函数
- [ ] `static/js/router.js` — 简易 hash router（`#menu` / `#co-create`）
- [ ] `static/index.html` — 两个视图：
  - 主菜单：新游戏 / 继续 / 管理 按钮
  - 共创页：对话历史区 + 输入框 + 发送按钮 + `/go 生成` `/quit 退出` 按钮

### 注意事项
- [ ] `send()` 服务端拦截空字符串 → HTTP 400，不等引擎 ValueError
- [ ] 生成阶段有等待时间（LLM 调用），前端显示 loading 状态
- [ ] `story_config` 返回后暂存在前端 `localStorage` 或 session 变量，供 Step 3 使用

### 验证
```
菜单 → 点"新游戏"
→ 看到 prompt "请描述你想玩的故事"
→ 输入"赛博朋克爱情" → 发送
→ 看到 LLM 回复（追问）
→ 反复 3 轮
→ 点"生成设定"
→ 页面显示 story_config JSON（手动验证字段完整性）
```

---

## Step 3：叙事 SSE 流 + Choice 暂停 ⚡ 核心难点

**目标**：创建游戏后逐段看到叙事，选项出现时可点击并继续

### 文件
- [ ] `sessions.py` 新增：
  - `GameSessionState` dataclass（`game_loop`, `event_queue`, `choice_queue`, `round_thread`, `round_active`）
  - `game_sessions: dict[str, GameSessionState]`
- [ ] `server.py` 新增路由：
  - `POST /api/game/new` — 从 story_config 创建 GameLoop + `start_game()` + 启动后台线程
  - `GET /api/game/{id}/stream` — SSE response，从 `event_queue` 消费
  - `POST /api/game/{id}/choice` — 向 `choice_queue` 注入 key
  - `POST /api/game/{id}/retry` — `gl.retry()`
- [ ] `static/js/sse-client.js` — EventSource 封装：
  - 自动重连（SSE 自带）
  - 每种 event type 的事件监听注册
  - options 事件 → 暂停 SSE 消费 → 等用户点击 → POST choice
- [ ] `static/js/display.js` — 渲染函数：
  - `appendSegment(text)` — 追加段落
  - `renderOptions(choices)` — 渲染选项按钮
  - `updateState(vars)` — 更新状态显示
- [ ] `static/index.html` 新增游戏视图：
  - 故事区域（`#story-area`）
  - 选项面板（`#choice-panel`）
  - 顶部状态栏（节点名、轮次）

### ⚠️ gen.send 线程桥接（不能出错）

后台线程结构：
```python
def _run_round(state):
    gen = state.game_loop.stream_round()
    state.current_gen = gen
    for event in gen:
        if event["type"] == "options":
            state.event_queue.put(event)       # 推给 SSE
            key = state.choice_queue.get()     # 阻塞等前端 POST
            gen.send(key)                      # 同线程恢复
        else:
            state.event_queue.put(event)
    state.event_queue.put({"type": "__round_done__"})
```

SSE 端点：
```python
async def _event_stream():
    while True:
        try:
            event = state.event_queue.get_nowait()
        except:
            await asyncio.sleep(0.05)
            continue
        if event["type"] == "__round_done__":
            return
        yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
```

### 注意事项
- [ ] `start_game()` 在 `new` 端点里调。如果 Load game 也要调。
- [ ] 后台线程是 daemon——进程退出时自动终止
- [ ] SSE 端点返回后客户端检查 `ending_flag`——false 时自动重新 GET `/stream` 开始下一轮
- [ ] `__round_done__` 是内部事件，不会发给前端
- [ ] 每轮启动前 `_drain_queue(event_queue)` 清理残留

### 验证
```
用 test_story.json 或共创结果 → POST /api/game/new
→ GET /api/game/{id}/stream
→ 看到 event: segment... 逐段出现
→ 看到 event: options → 前端显示选项按钮
→ 点按钮 → POST /api/game/{id}/choice
→ SSE 继续推送更多 segment
→ event: done → 状态更新
```

---

## Step 4：状态面板 + 大纲侧边栏

**目标**：游戏界面侧边栏实时显示变量和大纲进度

### 文件
- [ ] `server.py` 新增：`GET /api/game/{id}/state`
- [ ] `static/js/state.js` — 前端状态管理：
  - `fetchState(gameId)` → 更新全局 state 对象
  - `renderOutline(nodes)` → 侧边栏大纲列表
  - `renderVars(vars)` → 变量面板
- [ ] `static/css/main.css` — 侧边栏样式（右栏或左栏）
- [ ] `static/index.html` — 游戏视图新增侧边栏 DOM

### 注意事项
- [ ] `outline_nodes[].status` 是引擎动态计算的（active/completed/pending），不是存储值
- [ ] 状态变量值类型混搭：number→int, string→str, list→list。前端展示时做类型判断
- [ ] 大纲节点用图标区分状态：● completed, ○ active, · pending

### 验证
```
游戏中 GET /api/game/{id}/state
→ outline_nodes 数组各含 status 字段
→ state_vars 与游戏进程一致
前端侧边栏渲染正确
```

---

## Step 5：存档 + 结局

**目标**：完整的存档生命周期 + 结局冒险日志

### 文件
- [ ] `server.py` 新增路由：
  - `GET /api/saves` — `GameSession().list_saves()`
  - `POST /api/game/{id}/save` — `gl.to_save_dict()` + `sm.save()`
  - `POST /api/saves/{label}/load` — `session.load_game()` + `gl.start_game()`
  - `DELETE /api/saves/{label}` — `session.delete_save()`
  - `GET /api/game/{id}/adventure-log` — `gl.get_adventure_log()`
- [ ] `static/js/api.js` — 存档 API 函数
- [ ] `static/js/display.js` — `renderAdventureLog(markdown)` — 简易 Markdown 渲染
- [ ] `static/index.html` — 存档列表 modal、冒险日志展示区

### 注意事项
- [ ] Load game 后要调 `gl.start_game()` — 和 New game 一样
- [ ] `get_adventure_log(timeout)` 可能返回 `None`（超时/错误时）。先查 `adventure_log_error` 属性
- [ ] 冒险日志是 Markdown 格式。可以引入 marked.js（CDN）或手写简易版
- [ ] 存档的 label 可能含特殊字符，URL 需要 `encodeURIComponent()`

### 验证
```
游戏第 3 轮 → 点"存档" → 成功
→ 回主菜单 → 点"继续" → 看到存档列表
→ 选择刚才的存档 → 加载 → 回到第 3 轮同一节点
→ 玩到结局 → 冒险日志展示
```

---

## Step 6：前端体验打磨

**目标**：打字机效果、暗色主题完成、展示模式切换、语言切换

### 文件
- [ ] `static/js/display.js` 更新：
  - token 事件 → 逐字追加到 `<span class="current-segment">`
  - segment 事件 → 锁存当前段落，开新段落
- [ ] `static/css/main.css` 完善：
  - 段落淡入动画
  - 选项按钮 hover 发光
  - 侧边栏半透明
  - 滚动条样式
- [ ] 展示模式 toggle（自动 0.5s / 手动点击 / 即时）
- [ ] 语言切换 `<select>`：
  - 菜单和共创阶段可用
  - 游戏中置灰 + tooltip "游戏结束后可切换语言"
  - JS 端 UI 文本翻译字典
- [ ] `static/js/state.js` — 前端 UI 文本翻译函数 `t(key)`

### 注意事项
- [ ] token 事件的文本直接 append 到 DOM，不做 `innerHTML`（防 XSS，虽然 LLM 输出可控）
- [ ] 展示模式切换不涉及引擎——纯前端控制段落展示节奏
- [ ] JS 翻译字典只覆盖 UI 文本（按钮、标签），不涉及故事内容

### 验证
```
视觉：暗色背景 + 绿色文字 + 段落淡入
功能：打字机逐字出现 → 段落锁存 → 新段落开始
模式：自动/手动/即时 切换
语言：菜单切换 en/zh-CN → 按钮文本变化
```

---

## Step 7：错误处理 + 边界情况

**目标**：异常场景不崩溃，用户有操作路径

### 任务
- [ ] SSE `error` 事件 → 模态框展示错误信息 + [重试] [返回主菜单] 按钮
- [ ] 网络断线 → SSE 自动重连（EventSource 自带）→ 恢复后继续
- [ ] `send()` 空输入 — 前端按钮置灰 + 服务端 400 双重拦截
- [ ] Choice key 非法 — 服务端校验 + 前端忽略无效点击
- [ ] API 超时 → 错误事件 → 用户点重试 → `gl.retry()` → 重新 GET stream
- [ ] 共创阶段 CoCreationAborted → 展示错误 + 返回菜单按钮
- [ ] 冒险日志超时 → `adventure_log_error` 非空时展示错误信息
- [ ] 浏览器刷新 → 游戏状态丢失（内存存储限制，显示提示文字）

### 注意事项
- [ ] `retry()` 调完后要重新进入 SSE 循环——不能假设旧的 generator 还能用
- [ ] 错误模态框要有明确的关闭/操作路径，不阻塞用户

### 验证
```
断网 → SSE error → 看到错误提示
  → 恢复网络 → 点重试 → 故事继续
空输入 → 按钮不可点 + 输入框 shake 动画
非法 choice key → 400 返回 + 选项不变
```

---

## 文件最终清单

```
src/storyloom/web/
├── DESIGN.md              ← 架构与接口规格（参考用）
├── TASKS.md               ← 本文件（实施清单）
├── __init__.py
├── server.py              ← FastAPI 应用 + 全部路由 (~350 行)
├── sessions.py            ← 服务端会话管理 (~80 行)
└── static/
    ├── index.html         ← 单页应用 (~200 行)
    ├── css/
    │   └── main.css       ← 暗色主题 (~250 行)
    └── js/
        ├── api.js         ← HTTP/SSE 封装 (~80 行)
        ├── router.js      ← Hash 路由 (~60 行)
        ├── sse-client.js  ← SSE 消费 + choice 通信 (~100 行)
        ├── display.js     ← 渲染函数 (~150 行)
        └── state.js       ← 状态管理 + i18n (~100 行)
```

## 进度追踪

| Step | 状态 | 开始 | 完成 | 备注 |
|------|------|------|------|------|
| 1: 骨架 | ⬜ | — | — | |
| 2: 共创 | ⬜ | — | — | |
| 3: 游戏流 | ⬜ | — | — | MVP 边界 |
| 4: 状态面板 | ⬜ | — | — | |
| 5: 存档结局 | ⬜ | — | — | |
| 6: 体验打磨 | ⬜ | — | — | |
| 7: 错误处理 | ⬜ | — | — | |
