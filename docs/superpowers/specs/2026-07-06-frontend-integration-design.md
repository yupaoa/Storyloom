# Frontend Integration Design

> 2026-07-06 | 双人开发 — 后端提供可 pip install 的库，前端自行构建 HTTP/SSE 层。

## 目标

Storyloom 作为 Python 库被前端项目导入。前端负责 API 服务层（FastAPI/Express/等），后端只暴露生成器接口。CLI 保持兼容，未来逐步淘汰。

## 改动范围

| 类型 | 文件 | 行数 |
|------|------|------|
| 新增 | `pyproject.toml` | ~20 |
| 修改 | `src/storyloom/api_client.py` | +~15 |
| 修改 | `src/storyloom/game_loop.py` | +~35 |
| 新增 | `docs/api/co-create.md` | ~30 |

## 详细设计

### 1. pyproject.toml — 包化

让前端通过 `pip install -e .` 或 `pip install git+...` 安装。

```toml
[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "storyloom"
version = "0.1.0"
requires-python = ">=3.10"

[tool.setuptools.packages.find]
where = ["src"]
```

### 2. api_client.py — stream_chat_iter()

新增生成器方法，逐 token yield。`stream_chat()` 改为调用此方法后 join。

```python
def stream_chat_iter(self, messages: list[dict]) -> Iterator[dict]:
    """Yield streaming chat tokens one by one.

    Yields:
        {"delta": str, "ttft": float | None}   # content token
        {"usage": dict, "done": True}            # final chunk
    """
```

实现：将现有 `stream_chat()` 中 `while True: readline()` 循环体提取为生成器。`stream_chat()` 包装：

```python
def stream_chat(self, messages: list[dict]) -> ApiResult:
    collected = []
    ttft = None
    tokens = None
    for chunk in self.stream_chat_iter(messages):
        if chunk.get("done"):
            tokens = chunk.get("usage")
        else:
            if chunk.get("ttft") is not None:
                ttft = chunk["ttft"]
            collected.append(chunk["delta"])
    return ApiResult(content="".join(collected), ttft=ttft, tokens=tokens)
```

### 3. game_loop.py — start_round1_stream() / continue_round_stream()

新增两个生成器方法。每个 yield 结构化事件 dict。

**事件类型：**

| type | payload | 说明 |
|------|---------|------|
| `token` | `{"text": str}` | LLM 逐 token |
| `segment` | `{"text": str, "n": int, "position": "pre"\|"post", "branch": str\|null}` | 段落完成 |
| `options` | `{"choices": [{"id": str, "branches": [str], "labels": [str]}]}` | 选项面板 |
| `state` | `{"vars": dict, "changes": [{"var": str, "op": str, "val": str, "accepted": bool}]}` | 状态变更 |
| `error` | `{"message": str}` | 格式/解析错误 |
| `done` | `{"round": int, "node": str\|null, "parsed_summary": dict}` | 轮次结束 |

**向后兼容：** `start_round1()` / `continue_round()` 改为内部调用对应 stream 方法，消费生成器后返回 `RoundResult`。签名和返回值不变。

```python
def start_round1(self) -> RoundResult:
    parsed = None
    for event in self.start_round1_stream():
        if event["type"] == "done":
            parsed = event["parsed_summary"]  # internal
    return RoundResult(parsed=parsed, round_number=1)
```

### 4. docs/api/co-create.md — 共创参考

最小化文档，包含：
- 共创 prompt 模板（从 `co_create.py` 提取 `CO_CREATE_SYSTEM_PROMPT` 和 `GENERATE_ALL_PROMPT`）
- 输出格式说明（`=== story_config ===` / `=== variables ===` / `=== outline ===` 三块）
- 字段约束（变量上限 3、outline 格式等）

不提供任何实现建议，不限制前端自由发挥。

## API 端点（前端实现参考）

以下为建议端点，后端不实现。前端自行决定。

```
POST   /api/game/new          body: {story_config, outline_text} → SSE stream
POST   /api/game/{id}/choice  body: {choice_key} → SSE stream
GET    /api/game/{id}/state   → {vars, node, round}
POST   /api/saves              CRUD
GET    /api/saves
POST   /api/saves/{id}/load
DELETE /api/saves/{id}
```

### SSE 流格式

```
event: token
data: {"text": "霓"}

event: segment
data: {"text": "...", "n": 1, "position": "pre"}

event: options
data: {"choices": [{"id": "approach", "branches": ["direct"], "labels": ["直接问价"]}]}

event: done
data: {"round": 1, "node": "ch2_confrontation", "state": {"体力": 80}}
```

## 前端集成示例

```python
# 前端自己的 FastAPI/Starlette 服务中
from storyloom import GameLoop, GameState, ApiClient
from starlette.responses import StreamingResponse

async def game_new_endpoint(body: dict):
    api = ApiClient()
    state = GameState(body["story_config"])
    loop = GameLoop(
        story_config=body["story_config"],
        outline_text=body["outline_text"],
        api_client=api,
        display=None,  # 不需要终端 display
        game_state=state,
    )
    
    async def event_stream():
        for event in loop.start_round1_stream():
            yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

## 不变的部分

以下模块无需修改，前端可直接复用：

- `GameState` — 状态管理（local source of truth）
- `ContextManager` — 消息数组 + 滑动窗口
- `PromptBuilder` — Round 1 / Round N prompt 构建
- `XmlParser` — LLM XML 输出解析
- `Display` — 前端不需要（自行渲染），CLI 继续使用
- `CoCreateFlow` — 共创逻辑移至前端
- `main.py` — CLI 入口，保持不变
