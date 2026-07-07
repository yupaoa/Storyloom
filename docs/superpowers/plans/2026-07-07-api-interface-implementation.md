# API Interface Implementation Plan

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 为 Web UI 集成扩展 3 个 API 接口：GameLoop 公开访问器、CoCreateFlow 状态机、GameSession 编排器。

**架构：** 在现有引擎层外新增薄封装层。GameLoop 新增 2 个只读 property（checkpoint_history、outline_nodes）；CoCreateFlow 新增步进式状态机 API（start/send/abort）与现有 run() 并存；新建 GameSession 协调 ApiClient、SaveManager、CoCreateFlow、GameLoop 的生命周期。零核心流程变更。

**技术栈：** Python 3.10+，标准库，pytest

**规格文档：** `docs/superpowers/specs/2026-07-07-api-audit-and-interface-design.md`

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `src/storyloom/core/game_loop.py` | 修改 | 新增 `checkpoint_history`、`outline_nodes` 属性 |
| `src/storyloom/core/co_create.py` | 修改 | `ui` 可选；新增 `phase`、`result`、`start()`、`send()`、`abort()` |
| `src/storyloom/core/session.py` | 创建 | `GameSession` 编排器——ApiClient + SaveManager 生命周期管理 |
| `tests/test_game_loop.py` | 修改 | 测试新属性 |
| `tests/test_co_create.py` | 修改 | 测试状态机 API |
| `tests/test_session.py` | 创建 | 测试 GameSession |

---

### 任务 1：GameLoop.checkpoint_history 属性

**文件：**
- 修改：`src/storyloom/core/game_loop.py`
- 测试：`tests/test_game_loop.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_game_loop.py` 末尾添加：

```python
class TestCheckpointHistory:
    """Tests for GameLoop.checkpoint_history property."""

    def test_returns_empty_list_when_no_checkpoints(self):
        """checkpoint_history returns [] before any checkpoints occur."""
        api = make_mock_api()
        gl = GameLoop(
            story_config=make_story_config(),
            outline_text=make_outline_text(),
            api_client=api,
        )
        assert gl.checkpoint_history == []
        assert isinstance(gl.checkpoint_history, list)

    def test_returns_copy_not_internal_reference(self):
        """checkpoint_history returns a copy, not the internal list."""
        api = make_mock_api()
        gl = GameLoop(
            story_config=make_story_config(),
            outline_text=make_outline_text(),
            api_client=api,
        )
        history = gl.checkpoint_history
        history.append({"node": "fake", "title": "x", "summary": "x", "round": 99})
        assert gl.checkpoint_history == []  # internal list unchanged
```

- [ ] **步骤 2：运行测试验证失败**

```bash
pytest tests/test_game_loop.py::TestCheckpointHistory -v
```

预期：`AttributeError: 'GameLoop' object has no attribute 'checkpoint_history'`

- [ ] **步骤 3：实现属性**

在 `src/storyloom/core/game_loop.py` 的 `GameLoop` 类中，`round_count` property 之后添加：

```python
@property
def checkpoint_history(self) -> list[dict]:
    """Return checkpoint history for UI progress display.

    Returns a copy. Each entry: {node, title, summary, round}.
    """
    return list(self._checkpoint_history)
```

- [ ] **步骤 4：运行测试验证通过**

```bash
pytest tests/test_game_loop.py::TestCheckpointHistory -v
```

预期：2 passed

- [ ] **步骤 5：Commit**

```bash
git add src/storyloom/core/game_loop.py tests/test_game_loop.py
git commit -m "feat: add GameLoop.checkpoint_history public property"
```

---

### 任务 2：GameLoop.outline_nodes 属性

**文件：**
- 修改：`src/storyloom/core/game_loop.py`
- 测试：`tests/test_game_loop.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_game_loop.py` 末尾添加：

```python
class TestOutlineNodes:
    """Tests for GameLoop.outline_nodes property."""

    def test_returns_list_of_nodes_with_required_keys(self):
        """outline_nodes returns list of dicts with id, title, goal, status, branches."""
        api = make_mock_api()
        outline_nodes = [
            {"id": "ch1_intro", "title": "Intro", "goal": "Start the story",
             "routes": [{"condition": None, "target": "ch2_next"}]},
        ]
        gl = GameLoop(
            story_config=make_story_config(),
            outline_text=make_outline_text(),
            api_client=api,
            current_node="ch1_intro",
            outline_nodes=outline_nodes,
        )
        result = gl.outline_nodes
        assert len(result) == 1
        node = result[0]
        assert node["id"] == "ch1_intro"
        assert node["title"] == "Intro"
        assert node["goal"] == "Start the story"
        assert node["status"] == "active"
        assert node["branches"] == ["ch2_next"]

    def test_returns_copy_not_internal_reference(self):
        """outline_nodes returns a copy."""
        api = make_mock_api()
        outline_nodes = [
            {"id": "ch1_intro", "title": "Intro", "goal": "Start",
             "routes": []},
        ]
        gl = GameLoop(
            story_config=make_story_config(),
            outline_text=make_outline_text(),
            api_client=api,
            outline_nodes=outline_nodes,
        )
        result = gl.outline_nodes
        result[0]["id"] = "hacked"
        assert gl.outline_nodes[0]["id"] == "ch1_intro"  # internal unchanged

    def test_status_computed_correctly(self):
        """Status is active/completed/pending based on current_node and _completed_nodes."""
        api = make_mock_api()
        outline_nodes = [
            {"id": "ch1", "title": "One", "goal": "First",
             "routes": [{"condition": None, "target": "ch2"}]},
            {"id": "ch2", "title": "Two", "goal": "Second",
             "routes": [{"condition": None, "target": "ch3"}]},
            {"id": "ch3", "title": "Three", "goal": "Third", "routes": []},
        ]
        gl = GameLoop(
            story_config=make_story_config(),
            outline_text=make_outline_text(),
            api_client=api,
            current_node="ch2",
            outline_nodes=outline_nodes,
        )
        # Mark ch1 as completed
        gl._completed_nodes = ["ch1"]

        result = gl.outline_nodes
        assert result[0]["status"] == "completed"  # ch1
        assert result[1]["status"] == "active"      # ch2 (current)
        assert result[2]["status"] == "pending"     # ch3

    def test_normalizes_loaded_save_format(self):
        """Nodes from save format (node_id, branches keys) are normalized to id, branches."""
        api = make_mock_api()
        # Simulate save-format nodes (from from_save_dict)
        save_format_nodes = [
            {"node_id": "ch1_intro", "title": "Intro", "goal": "Start",
             "status": "completed", "branches": ["ch2_next"]},
        ]
        gl = GameLoop(
            story_config=make_story_config(),
            outline_text=make_outline_text(),
            api_client=api,
            current_node="ch2_next",
            outline_nodes=save_format_nodes,
        )
        # Mark ch1 as completed (it is in save format, but status computed dynamically)
        gl._completed_nodes = ["ch1_intro"]

        result = gl.outline_nodes
        assert len(result) == 1
        node = result[0]
        assert node["id"] == "ch1_intro"       # normalized from node_id
        assert node["branches"] == ["ch2_next"]  # normalized from branches
        assert node["status"] == "completed"     # computed dynamically
```

- [ ] **步骤 2：运行测试验证失败**

```bash
pytest tests/test_game_loop.py::TestOutlineNodes -v
```

预期：`AttributeError: 'GameLoop' object has no attribute 'outline_nodes'`

- [ ] **步骤 3：实现属性**

在 `src/storyloom/core/game_loop.py` 的 `GameLoop` 类中，`checkpoint_history` property 之后添加：

```python
@property
def outline_nodes(self) -> list[dict]:
    """Current outline with computed node statuses.

    Returns a copy. Each entry: {id, title, goal, status, branches}.
    Format matches the save file outline structure (data-model.md §3.1).

    Status is computed dynamically: 'active' | 'completed' | 'pending'.
    branches: list of target node ID strings (conditions excluded).

    Normalizes the two internal formats:
      - Fresh: {id, routes: [{condition, target}]}
      - Loaded: {node_id, branches: [str]}
    into a single consistent public shape.
    """
    result = []
    for node in self._outline_nodes:
        nid = node.get("id") or node.get("node_id", "")
        result.append({
            "id": nid,
            "title": node.get("title", ""),
            "goal": node.get("goal", ""),
            "status": (
                "active" if nid == self.current_node
                else "completed" if nid in self._completed_nodes
                else "pending"
            ),
            "branches": [
                r.get("target", r) if isinstance(r, dict) else r
                for r in node.get("routes", node.get("branches", []))
            ],
        })
    return result
```

- [ ] **步骤 4：运行测试验证通过**

```bash
pytest tests/test_game_loop.py::TestOutlineNodes -v
```

预期：4 passed

- [ ] **步骤 5：运行全部现有测试确认无回归**

```bash
pytest tests/test_game_loop.py -v
```

预期：全部通过（新测试 + 已有测试）

- [ ] **步骤 6：Commit**

```bash
git add src/storyloom/core/game_loop.py tests/test_game_loop.py
git commit -m "feat: add GameLoop.outline_nodes public property with format normalization"
```

---

### 任务 3：CoCreateFlow — ui 参数改为可选

**文件：**
- 修改：`src/storyloom/core/co_create.py`
- 测试：`tests/test_co_create.py`

- [ ] **步骤 1：修改构造函数签名**

在 `src/storyloom/core/co_create.py` 中，修改 `CoCreateFlow.__init__`：

```python
# 将:
def __init__(self, api_client: ApiClient, ui: UiInterface):
    self._api = api_client
    self._ui = ui

# 改为:
def __init__(self, api_client: ApiClient, ui: UiInterface | None = None):
    self._api = api_client
    self._ui = ui
```

- [ ] **步骤 2：在 run() 中添加断言**

在 `run()` 方法开头添加：

```python
def run(self) -> CoCreationResult:
    """Run the full co-creation flow.

    Returns:
        CoCreationResult with story_config (including variables)
        and formatted outline_text.

    Raises:
        CoCreationAborted: If user chooses to abort.
        RuntimeError: If initialized without a UiInterface.
    """
    if self._ui is None:
        raise RuntimeError(
            "CoCreateFlow.run() requires a UiInterface. "
            "Pass ui= at construction, or use the state machine API "
            "(start()/send()) for UI-agnostic co-creation."
        )
    self._step1_get_idea()
    self._step2_questioning()
    return self._step3_generate_all()
```

- [ ] **步骤 3：编写测试验证**

在 `tests/test_co_create.py` 末尾添加：

```python
class TestCoCreateFlowUiOptional:
    """Tests for ui=None support."""

    def test_construct_without_ui(self):
        """CoCreateFlow can be constructed with ui=None."""
        api = make_mock_api_client()
        flow = CoCreateFlow(api)  # no ui
        assert flow._ui is None

    def test_run_raises_without_ui(self):
        """run() raises RuntimeError when ui is None."""
        api = make_mock_api_client()
        flow = CoCreateFlow(api)
        with pytest.raises(RuntimeError, match="requires a UiInterface"):
            flow.run()

    def test_construct_with_ui_still_works(self):
        """Existing usage with ui= still works."""
        api = make_mock_api_client()
        ui = make_mock_ui()
        flow = CoCreateFlow(api, ui)
        assert flow._ui is ui
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/test_co_create.py::TestCoCreateFlowUiOptional -v
```

预期：3 passed

- [ ] **步骤 5：运行全部现有测试确认无回归**

```bash
pytest tests/test_co_create.py -v
```

预期：全部通过

- [ ] **步骤 6：Commit**

```bash
git add src/storyloom/core/co_create.py tests/test_co_create.py
git commit -m "feat: make CoCreateFlow ui parameter optional for state machine API"
```

---

### 任务 4：CoCreateFlow — phase 和 result 属性

**文件：**
- 修改：`src/storyloom/core/co_create.py`
- 测试：`tests/test_co_create.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_co_create.py` 末尾添加：

```python
class TestCoCreateFlowStateMachineProperties:
    """Tests for phase, result properties."""

    def test_initial_phase_is_init(self):
        """phase returns 'init' before start() is called."""
        api = make_mock_api_client()
        flow = CoCreateFlow(api)
        assert flow.phase == "init"

    def test_result_is_none_initially(self):
        """result is None before co-creation completes."""
        api = make_mock_api_client()
        flow = CoCreateFlow(api)
        assert flow.result is None

    def test_phase_transitions_after_start(self):
        """phase changes to 'awaiting_idea' after start()."""
        api = make_mock_api_client()
        flow = CoCreateFlow(api)
        flow.start()
        assert flow.phase == "awaiting_idea"

    def test_abort_changes_phase(self):
        """abort() sets phase to 'aborted'."""
        api = make_mock_api_client()
        flow = CoCreateFlow(api)
        flow.abort()
        assert flow.phase == "aborted"
```

- [ ] **步骤 2：运行测试验证失败**

```bash
pytest tests/test_co_create.py::TestCoCreateFlowStateMachineProperties -v
```

预期：AttributeError

- [ ] **步骤 3：实现属性和 abort()**

在 `CoCreateFlow.__init__` 末尾添加：

```python
self._phase: str = "init"
self._result: CoCreationResult | None = None
```

添加属性和 abort() 方法：

```python
@property
def phase(self) -> str:
    """Current phase: 'init' | 'awaiting_idea' | 'awaiting_answer'
       | 'generating' | 'complete' | 'aborted'."""
    return self._phase

@property
def result(self) -> CoCreationResult | None:
    """Result when phase == 'complete', None otherwise."""
    return self._result

def abort(self) -> None:
    """Abort co-creation immediately."""
    self._phase = "aborted"
```

- [ ] **步骤 4：运行测试验证通过**

```bash
pytest tests/test_co_create.py::TestCoCreateFlowStateMachineProperties -v
```

预期：4 passed

- [ ] **步骤 5：Commit**

```bash
git add src/storyloom/core/co_create.py tests/test_co_create.py
git commit -m "feat: add CoCreateFlow phase, result properties and abort() method"
```

---

### 任务 5：CoCreateFlow — start() 方法

**文件：**
- 修改：`src/storyloom/core/co_create.py`
- 测试：`tests/test_co_create.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_co_create.py` 末尾添加：

```python
class TestCoCreateFlowStart:
    """Tests for start() method."""

    def test_start_returns_awaiting_idea_event(self):
        """start() returns {phase: 'awaiting_idea', prompt: str}."""
        api = make_mock_api_client()
        flow = CoCreateFlow(api)
        event = flow.start()
        assert event["phase"] == "awaiting_idea"
        assert "prompt" in event
        assert isinstance(event["prompt"], str)
        assert len(event["prompt"]) > 0

    def test_start_sets_phase(self):
        """start() transitions phase from 'init' to 'awaiting_idea'."""
        api = make_mock_api_client()
        flow = CoCreateFlow(api)
        assert flow.phase == "init"
        flow.start()
        assert flow.phase == "awaiting_idea"

    def test_start_raises_if_already_started(self):
        """Calling start() twice raises RuntimeError."""
        api = make_mock_api_client()
        flow = CoCreateFlow(api)
        flow.start()
        with pytest.raises(RuntimeError, match="already started"):
            flow.start()
```

- [ ] **步骤 2：运行测试验证失败**

```bash
pytest tests/test_co_create.py::TestCoCreateFlowStart -v
```

预期：AttributeError: 'CoCreateFlow' object has no attribute 'start'

- [ ] **步骤 3：实现 start()**

在 `CoCreateFlow` 类中添加：

```python
def start(self) -> dict:
    """Begin co-creation. Returns {phase: 'awaiting_idea', prompt: str}.

    Must be called once before any send().

    Raises:
        RuntimeError: If already started.
    """
    if self._phase != "init":
        raise RuntimeError(
            f"Co-creation already started (phase: {self._phase})"
        )
    self._phase = "awaiting_idea"
    return {
        "phase": "awaiting_idea",
        "prompt": _("Describe the story you'd like to play.\n"
                     "e.g. 'A cyberpunk love story' or 'A wuxia adventure'"),
    }
```

- [ ] **步骤 4：运行测试验证通过**

```bash
pytest tests/test_co_create.py::TestCoCreateFlowStart -v
```

预期：3 passed

- [ ] **步骤 5：Commit**

```bash
git add src/storyloom/core/co_create.py tests/test_co_create.py
git commit -m "feat: add CoCreateFlow.start() method"
```

---

### 任务 6：CoCreateFlow — send() 方法（基础路径）

**文件：**
- 修改：`src/storyloom/core/co_create.py`
- 测试：`tests/test_co_create.py`

`send()` 是最复杂的方法，分两层：基础路径（idea → Q&A → go → complete）和错误路径（API 失败、解析失败）。

- [ ] **步骤 1：编写测试 — idea 收集**

```python
class TestCoCreateFlowSend:
    """Tests for send() method."""

    def test_send_idea_transitions_to_questioning(self, mock_api_with_response):
        """send(user_idea) stores idea, calls LLM, returns first question."""
        api = mock_api_with_response("What era would you like?")
        flow = CoCreateFlow(api)
        flow.start()

        event = flow.send("A cyberpunk romance in Neo Tokyo")

        assert event["phase"] == "awaiting_answer"
        assert "question" in event
        assert event["question"] == "What era would you like?"
        assert event["round"] == 1
        assert flow.phase == "awaiting_answer"

    def test_send_empty_input_prompts_retry(self):
        """Empty input returns awaiting_idea again."""
        api = make_mock_api_client()
        flow = CoCreateFlow(api)
        flow.start()

        event = flow.send("")

        assert event["phase"] == "awaiting_idea"
        assert flow.phase == "awaiting_idea"
```

- [ ] **步骤 2：编写测试 — go 触发生成**

```python
    def test_send_go_triggers_generation(self, mock_co_create_for_generation):
        """send('go') triggers generation and returns complete event."""
        api, flow = mock_co_create_for_generation
        flow.start()
        flow.send("A story idea")  # sends idea, gets first question
        # flow is now in 'awaiting_answer' phase

        event = flow.send("开始")

        assert event["phase"] == "complete"
        assert "result" in event
        assert isinstance(event["result"], CoCreationResult)
        assert flow.phase == "complete"
        assert flow.result is not None

    def test_send_quit_aborts(self):
        """send('quit') returns aborted phase."""
        api = make_mock_api_client()
        flow = CoCreateFlow(api)
        flow.start()
        flow.send("A story idea")  # → awaiting_answer

        event = flow.send("quit")

        assert event["phase"] == "aborted"
        assert flow.phase == "aborted"
```

- [ ] **步骤 3：编写测试 — 边界条件**

```python
    def test_send_before_start_raises(self):
        """send() before start() raises RuntimeError."""
        api = make_mock_api_client()
        flow = CoCreateFlow(api)
        with pytest.raises(RuntimeError, match="call start\\(\\) first"):
            flow.send("anything")

    def test_send_after_complete_raises(self):
        """send() after completion raises RuntimeError."""
        api, flow = mock_co_create_for_generation
        flow.start()
        flow.send("idea")
        flow.send("开始")  # → complete
        with pytest.raises(RuntimeError, match="already complete"):
            flow.send("anything")
```

- [ ] **步骤 4：运行测试验证失败**

```bash
pytest tests/test_co_create.py::TestCoCreateFlowSend -v
```

预期：全部 FAIL（send 未实现）

- [ ] **步骤 5：实现 send()**

在 `CoCreateFlow` 类中添加：

```python
# Co-creation keywords (matching _step2_questioning behavior)
_START_KEYWORDS = {"开始", "开始吧", "可以", "好的", "行", "ok", "OK", "yes", "go", "start", "begin", "ready"}
_QUIT_KEYWORDS = {"不玩了", "退出", "quit", "exit", "q", "stop", "abort"}

def send(self, user_input: str) -> dict:
    """Send user input, advance one step, return next event dict.

    Handles phase transitions: awaiting_idea → awaiting_answer →
    complete/aborted. Blocking during LLM generation.

    Args:
        user_input: User's text input. Recognizes 'go'/'quit' keywords.

    Returns:
        Event dict with 'phase' key and phase-specific data.

    Raises:
        RuntimeError: If called before start() or after completion.
    """
    if self._phase == "init":
        raise RuntimeError("call start() first before send()")
    if self._phase == "complete":
        raise RuntimeError("co-creation already complete")
    if self._phase == "aborted":
        raise RuntimeError("co-creation was aborted")

    # ── Phase: awaiting_idea ──
    if self._phase == "awaiting_idea":
        if not user_input.strip():
            return {"phase": "awaiting_idea",
                    "prompt": _("Please share some thoughts to begin.")}

        self._messages.append({"role": "user", "content": user_input.strip()})

        # Get first LLM question
        self._phase = "generating"
        try:
            response = self._api.chat(self._messages)
        except Exception as e:
            self._phase = "awaiting_idea"
            return {"phase": "error", "message": str(e), "recoverable": True}

        self._messages.append({"role": "assistant", "content": response})
        self._phase = "awaiting_answer"
        self._qa_round = 1
        return {"phase": "awaiting_answer", "question": response, "round": 1}

    # ── Phase: awaiting_answer ──
    if self._phase == "awaiting_answer":
        # Check quit keywords
        if user_input.strip() in self._QUIT_KEYWORDS:
            self._phase = "aborted"
            return {"phase": "aborted"}

        # Check start keywords
        if user_input.strip() in self._START_KEYWORDS:
            self._phase = "generating"
            try:
                result = self._generate_all()
            except CoCreationAborted:
                self._phase = "aborted"
                return {"phase": "aborted"}
            except Exception as e:
                self._phase = "awaiting_answer"
                return {"phase": "error", "message": str(e), "recoverable": True}

            self._phase = "complete"
            self._result = result
            return {"phase": "complete", "result": result}

        # Normal answer → next Q&A round
        self._messages.append({"role": "user", "content": user_input.strip()})
        self._phase = "generating"
        try:
            response = self._api.chat(self._messages)
        except Exception as e:
            self._phase = "awaiting_answer"
            return {"phase": "error", "message": str(e), "recoverable": True}

        self._messages.append({"role": "assistant", "content": response})
        self._phase = "awaiting_answer"
        self._qa_round += 1

        # Check round limit
        if self._qa_round > 15:
            self._phase = "generating"
            try:
                result = self._generate_all()
            except CoCreationAborted:
                self._phase = "aborted"
                return {"phase": "aborted"}
            except Exception as e:
                self._phase = "awaiting_answer"
                return {"phase": "error", "message": str(e), "recoverable": True}

            self._phase = "complete"
            self._result = result
            return {"phase": "complete", "result": result}

        return {"phase": "awaiting_answer", "question": response,
                "round": self._qa_round}

    # Fallback (generating phase or unknown)
    return {"phase": self._phase}
```

在 `__init__` 中添加：

```python
self._qa_round = 0
```

- [ ] **步骤 6：实现测试辅助函数**

在 `tests/test_co_create.py` 中添加 mock 工具：

```python
def make_mock_api_client():
    """Create a mock ApiClient that returns empty string."""
    api = Mock()
    api.chat = Mock(return_value="")
    return api


def mock_api_with_response(response_text: str):
    """Create a mock ApiClient that returns a fixed response."""
    api = Mock()
    api.chat = Mock(return_value=response_text)
    return api


@pytest.fixture
def mock_co_create_for_generation():
    """Create a CoCreateFlow set up for a complete generation cycle.
    
    Returns (api, flow) where api is pre-configured to return valid
    co-creation blocks.
    """
    from storyloom.core.co_create import (
        CoCreateParser,
        CoCreationResult,
    )
    # Build valid LLM response for generation
    gen_response = """=== story_config ===
genre: cyberpunk
tier: short
label: 测试故事
setting: Test setting
protagonist_name: Test
protagonist_identity: Tester
protagonist_traits: Brave
tone: Dark
conflict: A test
characters:
  Foo | ally | friend
=== variables ===
体力: number, 初始 80
=== outline ===
[node]
id: ch1_start
title: Start
goal: Begin
routes: → ch2_end
[node]
id: ch2_end
title: End
goal: Finish
routes: （结局）
"""
    first_question = "What kind of story?"
    api = Mock()
    # First call returns the question, second returns the generation
    api.chat = Mock(side_effect=[first_question, gen_response])
    flow = CoCreateFlow(api)
    return api, flow
```

- [ ] **步骤 7：运行测试**

```bash
pytest tests/test_co_create.py::TestCoCreateFlowSend -v
```

预期：全部通过

- [ ] **步骤 8：运行全部测试确认无回归**

```bash
pytest tests/test_co_create.py -v
```

预期：全部通过

- [ ] **步骤 9：Commit**

```bash
git add src/storyloom/core/co_create.py tests/test_co_create.py
git commit -m "feat: add CoCreateFlow.send() state machine method"
```

---

### 任务 7：CoCreateFlow.send() — 错误恢复路径

**文件：**
- 修改：`tests/test_co_create.py`

`send()` 已经包含错误处理（`{phase: "error", recoverable: True}`）。此任务补充错误路径测试。

- [ ] **步骤 1：编写错误恢复测试**

```python
class TestCoCreateFlowSendErrors:
    """Tests for send() error handling."""

    def test_api_error_returns_error_event(self):
        """API failure returns {phase: 'error', recoverable: True}."""
        api = Mock()
        api.chat = Mock(side_effect=Exception("Connection refused"))
        flow = CoCreateFlow(api)
        flow.start()

        event = flow.send("A story idea")

        assert event["phase"] == "error"
        assert "Connection refused" in event["message"]
        assert event["recoverable"] is True
        # Flow should remain recoverable — still in awaiting_idea
        assert flow.phase == "awaiting_idea"

    def test_retry_after_error_works(self):
        """After error, user can send again and succeed."""
        api = Mock()
        api.chat = Mock(side_effect=[
            Exception("fail"),
            "What kind of story?",  # succeeds on retry
        ])
        flow = CoCreateFlow(api)
        flow.start()

        # First attempt fails
        event1 = flow.send("idea")
        assert event1["phase"] == "error"

        # Second attempt succeeds
        event2 = flow.send("idea")
        assert event2["phase"] == "awaiting_answer"

    def test_generation_error_returns_error_event(self, mock_co_create_for_generation):
        """Generation failure in send('go') returns error event."""
        api, flow = mock_co_create_for_generation
        # Override chat to fail on generation call
        api.chat = Mock(side_effect=[
            "First question",           # Q&A round
            Exception("API timeout"),   # generation fails
        ])
        flow.start()
        flow.send("idea")  # → awaiting_answer

        event = flow.send("开始")

        assert event["phase"] == "error"
        assert event["recoverable"] is True
```

- [ ] **步骤 2：运行错误路径测试**

```bash
pytest tests/test_co_create.py::TestCoCreateFlowSendErrors -v
```

预期：3 passed

- [ ] **步骤 3：运行全部测试**

```bash
pytest tests/test_co_create.py -v
```

预期：全部通过

- [ ] **步骤 4：Commit**

```bash
git add tests/test_co_create.py
git commit -m "test: add CoCreateFlow.send() error recovery test coverage"
```

---

### 任务 8：GameSession 类

**文件：**
- 创建：`src/storyloom/core/session.py`
- 创建：`tests/test_session.py`

- [ ] **步骤 1：编写失败的集成测试**

创建 `tests/test_session.py`：

```python
"""Tests for GameSession orchestrator."""
import pytest
from unittest.mock import Mock, patch

from storyloom.core.session import GameSession
from storyloom.core.co_create import CoCreateFlow, CoCreationResult
from storyloom.core.game_loop import GameLoop


class TestGameSessionInit:
    """Tests for GameSession construction."""

    @patch("storyloom.core.session.ApiClient")
    def test_creates_api_client_on_init(self, mock_api):
        """GameSession creates an ApiClient on construction."""
        session = GameSession()
        mock_api.assert_called_once()

    def test_creates_save_manager(self):
        """GameSession creates a SaveManager."""
        session = GameSession(saves_dir="/tmp/test_saves")
        assert session._save_manager is not None

    def test_game_loop_is_none_initially(self):
        """game_loop is None before any game is started."""
        session = GameSession()
        assert session.game_loop is None


class TestGameSessionSaveManagement:
    """Tests for save management delegation."""

    def test_list_saves_delegates(self):
        """list_saves() delegates to SaveManager."""
        session = GameSession()
        session._save_manager = Mock()
        session._save_manager.list_saves.return_value = [
            {"label": "test", "round_count": 5}
        ]
        result = session.list_saves()
        assert len(result) == 1
        assert result[0]["label"] == "test"

    def test_delete_save_delegates(self):
        """delete_save() delegates to SaveManager."""
        session = GameSession()
        session._save_manager = Mock()
        session._save_manager.delete.return_value = True
        assert session.delete_save("test") is True
        session._save_manager.delete.assert_called_once_with("test")


class TestGameSessionLifecycle:
    """Tests for game lifecycle methods."""

    def test_new_co_create_returns_flow(self):
        """new_co_create() returns a CoCreateFlow with session's ApiClient."""
        session = GameSession()
        session._api_client = Mock()

        flow = session.new_co_create()

        assert isinstance(flow, CoCreateFlow)
        assert flow._api is session._api_client

    def test_start_game_creates_game_loop(self):
        """start_game() creates GameLoop from CoCreationResult."""
        session = GameSession()
        session._api_client = Mock()
        session._save_manager = Mock()

        result = CoCreationResult(
            story_config={
                "genre": "test", "tier": "short", "label": "测试",
                "setting": "", "protagonist_name": "T",
                "protagonist_identity": "Tester",
                "protagonist_traits": "Brave",
                "tone": "Dark", "conflict": "Test",
                "characters": "Foo | ally",
                "variables": [
                    {"name": "体力", "type": "number", "initial": 80},
                ],
            },
            outline_text="ch1_start [active] — Start：Begin",
            outline_nodes=[
                {"id": "ch1_start", "title": "Start", "goal": "Begin",
                 "routes": []},
            ],
        )

        gl = session.start_game(result)

        assert isinstance(gl, GameLoop)
        assert session.game_loop is gl
        # Verify save manager was configured
        assert gl._save_manager is session._save_manager

    def test_load_game_restores_game_loop(self):
        """load_game() restores GameLoop from save."""
        session = GameSession()
        session._api_client = Mock()
        session._save_manager = Mock()

        # Prepare save data in the format SaveManager.load() returns
        save_data = {
            "version": 1,
            "metadata": {"label": "test", "created_at": "", "updated_at": "",
                         "round_count": 3},
            "config": {},
            "story_config": {
                "genre": "test", "tier": "short", "label": "test",
                "setting": "", "protagonist_name": "T",
                "protagonist_identity": "Tester",
                "protagonist_traits": "Brave",
                "tone": "Dark", "conflict": "Test",
                "characters": "Foo | ally",
                "variables": [
                    {"name": "体力", "type": "number", "initial": 80},
                ],
            },
            "state_vars": {"体力": 80},
            "outline": [
                {"node_id": "ch1_start", "title": "Start", "goal": "Begin",
                 "status": "active", "branches": []},
            ],
            "progress": {
                "current_node": "ch1_start",
                "round_count": 3,
                "checkpoint_history": [],
                "checkpoint_summaries": [],
                "checkpoint_snapshots": {},
            },
            "bridge_text": "",
        }
        session._save_manager.load.return_value = save_data

        gl = session.load_game("test")

        assert isinstance(gl, GameLoop)
        assert session.game_loop is gl
        session._save_manager.load.assert_called_once_with("test")

    def test_load_game_raises_on_bad_save(self):
        """load_game() propagates FileNotFoundError/ValueError."""
        session = GameSession()
        session._save_manager = Mock()
        session._save_manager.load.side_effect = FileNotFoundError("no save")

        with pytest.raises(FileNotFoundError):
            session.load_game("nonexistent")
```

- [ ] **步骤 2：运行测试验证失败**

```bash
pytest tests/test_session.py -v
```

预期：ModuleNotFoundError（session.py 不存在）

- [ ] **步骤 3：实现 GameSession**

创建 `src/storyloom/core/session.py`：

```python
"""GameSession — lightweight lifecycle coordinator for the Storyloom engine.

Owns ApiClient and SaveManager. Wires CoCreateFlow → GameLoop transitions
so the UI doesn't need to know internal dependency order.

UI retains full control over rendering and interaction flow.
"""

from storyloom.io.api_client import ApiClient
from storyloom.core.save_manager import SaveManager
from storyloom.core.co_create import CoCreateFlow, CoCreationResult
from storyloom.core.game_loop import GameLoop, GameState


class GameSession:
    """Lightweight lifecycle coordinator.

    Does NOT control UI flow. UI calls methods at its own pace.

    Usage:
        session = GameSession()
        # New game:
        flow = session.new_co_create()
        # ... drive flow.start() / flow.send() ...
        gl = session.start_game(flow.result)
        # ... drive gl.start_round1_stream() / continue_round_stream() ...

        # Load game:
        gl = session.load_game("save_label")
    """

    def __init__(self, saves_dir: str = "saves"):
        """Initialize ApiClient (.env) and SaveManager.

        Args:
            saves_dir: Directory for save files.
        """
        self._api_client = ApiClient()
        self._save_manager = SaveManager(saves_dir)
        self._game_loop: GameLoop | None = None

    # ── Save management ─────────────────────────────────────────

    def list_saves(self) -> list[dict]:
        """List all saves with metadata.

        Returns:
            List of {label, round_count, created_at, updated_at, current_node}.
        """
        return self._save_manager.list_saves()

    def delete_save(self, label: str) -> bool:
        """Delete a save file. Returns True if deleted, False if not found."""
        return self._save_manager.delete(label)

    # ── Lifecycle ───────────────────────────────────────────────

    def new_co_create(self) -> CoCreateFlow:
        """Start a new co-creation session.

        Returns:
            CoCreateFlow ready for step-by-step UI interaction
            via start()/send()/abort().
        """
        return CoCreateFlow(self._api_client)

    def start_game(self, result: CoCreationResult) -> GameLoop:
        """Transition from co-creation to gameplay.

        Creates GameState and GameLoop from the co-creation result.
        Configures auto-save on checkpoint.

        Args:
            result: Completed CoCreationResult from CoCreateFlow.

        Returns:
            GameLoop ready for start_round1_stream().
        """
        story_config = result.story_config
        game_state = GameState(story_config)

        outline_nodes = result.outline_nodes
        first_node = ""
        first_goal = ""
        if outline_nodes:
            first_node = outline_nodes[0].get("id", "")
            first_goal = outline_nodes[0].get("goal", "")

        gl = GameLoop(
            story_config=story_config,
            outline_text=result.outline_text,
            api_client=self._api_client,
            game_state=game_state,
            current_node=first_node or None,
            goal=first_goal or None,
            outline_nodes=outline_nodes,
        )
        gl.set_save_manager(self._save_manager)
        self._game_loop = gl
        return gl

    def load_game(self, label: str) -> GameLoop:
        """Restore a game from save.

        Args:
            label: Save label (matches story_config.label).

        Returns:
            GameLoop ready for start_round1_stream().

        Raises:
            FileNotFoundError: Save does not exist.
            ValueError: Save is corrupt.
        """
        data = self._save_manager.load(label)
        gl = GameLoop.from_save_dict(data, self._api_client)
        gl.set_save_manager(self._save_manager)
        self._game_loop = gl
        return gl

    # ── State ───────────────────────────────────────────────────

    @property
    def game_loop(self) -> GameLoop | None:
        """Current active game, or None if not in-game."""
        return self._game_loop
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/test_session.py -v
```

确认通过后调试直到全部通过。

- [ ] **步骤 5：Commit**

```bash
git add src/storyloom/core/session.py tests/test_session.py
git commit -m "feat: add GameSession lifecycle coordinator"
```

---

### 任务 9：全覆盖回归测试与最终 Commit

- [ ] **步骤 1：运行全部测试**

```bash
pytest -v
```

预期：全部通过（新测试 + 已有 228 个测试）

- [ ] **步骤 2：检查类型注解**

```bash
python3 -c "
from storyloom.core.session import GameSession
from storyloom.core.co_create import CoCreateFlow
from storyloom.core.game_loop import GameLoop
print('All imports OK')
print(f'checkpoint_history: {hasattr(GameLoop, \"checkpoint_history\")}')
print(f'outline_nodes: {hasattr(GameLoop, \"outline_nodes\")}')
print(f'CoCreateFlow.start: {hasattr(CoCreateFlow, \"start\")}')
print(f'CoCreateFlow.send: {hasattr(CoCreateFlow, \"send\")}')
print(f'CoCreateFlow.abort: {hasattr(CoCreateFlow, \"abort\")}')
print(f'CoCreateFlow.phase: {hasattr(CoCreateFlow, \"phase\")}')
print(f'CoCreateFlow.result: {hasattr(CoCreateFlow, \"result\")}')
print(f'GameSession: {GameSession is not None}')
"
```

- [ ] **步骤 3：最终 Commit**

```bash
git add -A
git commit -m "test: full regression — all 228+ tests pass with new API surface"
```
