# i18n gettext Migration — Implementation Plan

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将 UI 字符串从 `Display.UI` 字典迁移到标准 gettext `.po`/`.mo` 架构

**架构：** `src/storyloom/i18n.py` 封装 gettext，导出 `init_i18n()` 和 `_()`；`Display` 去除 UI 字典/t()/language 参数变为纯终端 IO；所有 UI 字符串（共创+菜单+叙事）统一用 `_("English original")` 包裹

**技术栈：** Python 3 `gettext` 标准库，GNU `msgfmt`/`xgettext`

---

### 任务 1：创建 locale 目录结构和中文翻译 .po 文件

**文件：**
- 创建：`locale/zh_CN/LC_MESSAGES/storyloom.po`
- 创建：`locale/.gitkeep`

- [ ] **步骤 1：创建目录结构**

```bash
mkdir -p locale/zh_CN/LC_MESSAGES
```

- [ ] **步骤 2：编写 zh-CN .po 文件**

编写 `locale/zh_CN/LC_MESSAGES/storyloom.po`，包含全部 UI 字符串的中文翻译：

```po
# Chinese (Simplified) translations for Storyloom
# Copyright (C) 2026 Storyloom
# This file is distributed under the same license as the Storyloom project.
#
msgid ""
msgstr ""
"Project-Id-Version: Storyloom\n"
"Language: zh_CN\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"

# ── Menu ──
msgid "Storyloom — Interactive Fiction"
msgstr "Storyloom — 文字冒险"

msgid "[1] New Game"
msgstr "[1] 新游戏"

msgid "[2] Continue"
msgstr "[2] 继续"

msgid "[3] Manage Saves"
msgstr "[3] 管理存档"

msgid "[4] Exit"
msgstr "[4] 退出"

msgid "Choose: "
msgstr "请选择: "

msgid "Invalid choice, try again."
msgstr "无效选择，请重试。"

msgid "Goodbye."
msgstr "再会。"

msgid "Returning to menu."
msgstr "返回主菜单。"

# ── In-game ──
msgid "[{min}-{max}] Choose an option (0 for status, Q to quit): "
msgstr "[{min}-{max}] 选择选项 (0 查看状态, Q 退出): "

msgid "Invalid choice. Enter {min}-{max}, 0, or Q."
msgstr "无效选择，请输入 {min}-{max}、0 或 Q。"

msgid "Choose an option (type quit to return to menu): "
msgstr "选择选项 (输入 quit 返回菜单): "

msgid "Invalid choice, please enter 1-{n}."
msgstr "无效选择，请输入 1-{n}。"

msgid "Enter a number or quit."
msgstr "请输入数字或 quit。"

msgid "────────────────────────────────────"
msgstr "────────────────────────────────────"

msgid "···"
msgstr "···"

# ── Status / errors ──
msgid "Error: {msg}"
msgstr "错误: {msg}"

msgid "Generating story..."
msgstr "故事生成中..."

msgid "Under development"
msgstr "功能开发中"

msgid "API error: {msg}"
msgstr "API 错误: {msg}"

msgid "Loading: {feature}"
msgstr "{feature} —— 功能开发中"

# ── Co-creation ──
msgid "[Co-Creation — Story Setup]"
msgstr "【共创阶段 — 故事设定】"

msgid ""
"Describe the story you'd like to play.\n"
"e.g. 'A cyberpunk love story' or 'A wuxia adventure'\n"
msgstr ""
"请描述你想玩的故事。\n"
"例如：'赛博朋克背景下的爱情故事'、'古代仙侠世界的冒险'\n"

msgid "Please share some thoughts to begin."
msgstr "请输入一些想法来开始。"

msgid "[Q&A Phase]"
msgstr "【追问阶段】"

msgid ""
"I'll ask a few questions to understand the story you want.\n"
"When you're ready, type 'go' to generate the story setup.\n"
"Type 'quit' to return to the main menu.\n"
msgstr ""
"AI 会提出几个问题来了解你想玩的故事。\n"
"回答完毕后输入 '开始' 即可生成故事设定。\n"
"输入 '不玩了' 返回主菜单。\n"

msgid "Thinking..."
msgstr "思考中..."

msgid "Your answer (or type 'go'/'quit')> "
msgstr "你的回答（或输入 '开始'/'不玩了'）> "

msgid "Weaving your story world..."
msgstr "正在编织故事世界..."

msgid "Fixing {block}... (attempt {n})"
msgstr "修正{block}中...（第{n}次重试）"

msgid "{block} parsing failed ({errors})."
msgstr "{block} 解析失败（{errors}）。"

msgid "[R]etry / [M]enu: "
msgstr "[R]重试 / [M]返回主菜单: "

msgid "API call failed: {error}"
msgstr "API 调用失败: {error}"

msgid "Abort co-creation and return to menu? (y/n): "
msgstr "确定退出共创，返回主菜单？(y/n): "

msgid "Generation failed: {error}"
msgstr "生成失败: {error}"

msgid "Outline validation failed ({errors})."
msgstr "大纲校验失败（{errors}）。"
```

- [ ] **步骤 3：编译 .mo 文件**

```bash
msgfmt -o locale/zh_CN/LC_MESSAGES/storyloom.mo locale/zh_CN/LC_MESSAGES/storyloom.po
```

验证：`file locale/zh_CN/LC_MESSAGES/storyloom.mo` 应输出 `GNU message catalog`

- [ ] **步骤 4：gitignore .mo 文件**

确认 `.gitignore` 包含：
```
*.mo
```

如不包含则添加。

- [ ] **步骤 5：Commit**

```bash
git add locale/ .gitignore
git commit -m "feat: add zh-CN gettext translation catalog"
```

---

### 任务 2：创建 i18n 模块

**文件：**
- 创建：`src/storyloom/i18n.py`

- [ ] **步骤 1：编写 i18n.py**

```python
"""Internationalization support via gettext.

Provides module-level _() function for UI string translation.
Call init_i18n() once at startup.
"""

import gettext
import os

from src.storyloom.config import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE

_translators: dict[str, gettext.NullTranslations] = {}
_current_lang: str = DEFAULT_LANGUAGE


def init_i18n(language: str | None = None) -> None:
    """Initialize gettext for the given language.

    Must be called once at startup, before any _() calls.
    After calling, _() is available globally for all modules.

    Args:
        language: Language code (zh-CN, en). Falls back to DEFAULT_LANGUAGE.
    """
    global _current_lang
    _current_lang = language or DEFAULT_LANGUAGE
    if _current_lang not in SUPPORTED_LANGUAGES:
        _current_lang = DEFAULT_LANGUAGE

    locale_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "locale"
    )

    try:
        trans = gettext.translation(
            "storyloom", locale_dir,
            languages=[_current_lang, "en"],
            fallback=True,
        )
    except FileNotFoundError:
        trans = gettext.NullTranslations()

    _translators[_current_lang] = trans


def get_current_lang() -> str:
    """Return the currently active language code."""
    return _current_lang


def _(message: str) -> str:
    """Mark string for translation.

    Args:
        message: English source string (msgid).

    Returns:
        Translated string in the current language, or the original
        if no translation is available.
    """
    trans = _translators.get(_current_lang)
    if trans is None:
        return message
    return trans.gettext(message)
```

- [ ] **步骤 2：验证模块可导入**

```bash
python3 -c "from src.storyloom.i18n import init_i18n, _; init_i18n('en'); print(_('Storyloom — Interactive Fiction'))"
```

预期：`Storyloom — Interactive Fiction`

```bash
python3 -c "from src.storyloom.i18n import init_i18n, _; init_i18n('zh-CN'); print(_('Storyloom — Interactive Fiction'))"
```

预期：`Storyloom — 文字冒险`

- [ ] **步骤 3：Commit**

```bash
git add src/storyloom/i18n.py
git commit -m "feat: add i18n module with gettext wrapper"
```

---

### 任务 3：重写 Display 为纯终端 IO

**文件：**
- 修改：`src/storyloom/display.py`

**说明：** 删除 `UI` 字典、`t()` 方法、`language` 参数/属性，将所有硬编码字符串替换为 `_()` 调用。`show_main_menu` 用 `_()` 消息重写去掉 ASCII 框线。`show_error`/`show_wait_message`/`show_section_break` 由统一模板替代。

- [ ] **步骤 1：修改 Display 类 — 导入和初始化**

删除第 13 行 `Display.UI` 字典（约 80 行），添加 `_` 导入。修改 `__init__`：

```python
"""Terminal display management for Storyloom.

Handles all user-facing output: narrative segments, options, state display,
main menu, and user input. All translatable strings use _() from i18n module.
"""

import readline  # enables line editing, cursor movement, CJK-aware deletion
import sys
import time

from src.storyloom.i18n import _
from src.storyloom.xml_parser import Segment


class Display:
    """Manage terminal output for the interactive fiction engine.

    All output methods write to the configured output stream (default sys.stdout).
    """

    def __init__(self, output=None, auto_advance: bool = True):
        """Initialize display.

        Args:
            output: Output stream (defaults to sys.stdout).
            auto_advance: If True, auto-advance between segments with a short
                          delay instead of waiting for keypress.
        """
        self.output = output or sys.stdout
        self.auto_advance = auto_advance
```

- [ ] **步骤 2：重写 show_main_menu**

```python
    def show_main_menu(self, save_count: int) -> None:
        """Show the main menu with save count.

        Args:
            save_count: Number of existing save files.
        """
        self.output.write("\n")
        self.output.write(_("Storyloom — Interactive Fiction") + "\n")
        self.output.write("=" * 40 + "\n\n")
        self.output.write(_("  [1] New Game\n"))
        self.output.write(_("  [2] Continue\n"))
        if save_count > 0:
            self.output.write("      ({n} save(s))\n".format(n=save_count))
        self.output.write(_("  [3] Manage Saves\n"))
        self.output.write(_("  [4] Exit\n\n"))
        self.output.flush()
```

- [ ] **步骤 3：重写 show_options 和 show_state**

`show_options` 去掉硬编码中文，选项提示用 `_()` 包裹：

```python
    def show_options(
        self, choice_id: str, branches: list[str], labels: list[str]
    ) -> None:
        """Render the option panel."""
        self.output.write(_("────────────────────────────────────\n"))
        self.output.write("【选择】\n\n")
        for i, (branch, label) in enumerate(zip(branches, labels)):
            self.output.write(f"  [{i + 1}] {label}\n")
        self.output.write("\n")
        self.output.write(
            _("[{min}-{max}] Choose an option (0 for status, Q to quit): ")
            .format(min=1, max=len(branches)) + "\n"
        )
        self.output.write(_("────────────────────────────────────\n"))
        self.output.flush()
```

`show_state` 不变（无硬编码 UI 文本）。

- [ ] **步骤 4：替换 show_error、show_wait_message、show_section_break**

```python
    def show_error(self, msg: str) -> None:
        """Display an error message."""
        self.output.write(_("Error: {msg}").format(msg=msg) + "\n\n")
        self.output.flush()

    def show_wait_message(self, msg: str) -> None:
        """Show a waiting/progress message."""
        self.output.write(f"\n  {msg}\n\n")
        self.output.flush()

    def show_section_break(self) -> None:
        """Display a section break."""
        self.output.write(_("────────────────────────────────────\n\n"))
        self.output.flush()
```

- [ ] **步骤 5：重写 show_separator**

```python
    def show_separator(self) -> None:
        """Display a separator between segments within a round."""
        self.output.write(_("···") + "\n\n")
        self.output.flush()
```

- [ ] **步骤 6：保留不变的方法**

`show_segment`、`show_segments`、`get_input` — 这三个方法不涉及可翻译字符串，保持不变。

- [ ] **步骤 7：删除 show_main_menu 中的旧 save_count 标签**

旧代码中的 `"（{} 个存档）"` 硬编码中文字符串。改为英文模板：
```python
if save_count > 0:
    self.output.write(f"      ({save_count} save(s))\n")
```
（save count 不翻译，数字足够直观。）

- [ ] **步骤 8：验证**

```bash
python3 -c "
from src.storyloom.i18n import init_i18n
init_i18n('zh-CN')
from src.storyloom.display import Display
import io, sys
d = Display(output=io.StringIO())
d.show_main_menu(0)
print(d.output.getvalue())
"
```

预期输出包含中文菜单文本。

- [ ] **步骤 9：Commit**

```bash
git add src/storyloom/display.py
git commit -m "refactor: migrate Display to gettext, remove UI dict and t()"
```

---

### 任务 4：迁移 co_create.py 到 gettext

**文件：**
- 修改：`src/storyloom/co_create.py`

**说明：** 将所有 `display.t("key", ...)` 替换为 `_("English text").format(...)`。移除 `language` 参数和 `self._language`，改用 `get_current_lang()` 判断 Q&A 关键词。

- [ ] **步骤 1：添加导入，移除 language 参数**

在文件顶部添加：
```python
from src.storyloom.i18n import _, get_current_lang
```

修改 `__init__` 签名，移除 `language` 参数和 `lang_names` 逻辑：

```python
    def __init__(self, api_client: ApiClient, display: Display):
        self._api = api_client
        self._display = display

        self._messages: list[dict] = [
            {"role": "system", "content": CO_CREATE_SYSTEM_PROMPT}
        ]
```

- [ ] **步骤 2：替换 _step1_get_idea 中的 t() 调用**

```python
    def _step1_get_idea(self) -> None:
        """Collect user's initial story idea."""
        d = self._display
        d.output.write("\n")
        d.output.write("━" * 50 + "\n")
        d.output.write(_("[Co-Creation — Story Setup]") + "\n\n")
        d.output.write(
            _("Describe the story you'd like to play.\n"
              "e.g. 'A cyberpunk love story' or 'A wuxia adventure'\n")
            + "\n"
        )

        for _ in range(20):
            raw_idea = d.get_input("> ")
            if raw_idea and raw_idea.strip():
                break
            d.output.write(_("Please share some thoughts to begin.") + "\n")
        else:
            raise CoCreationAborted()

        self._messages.append({"role": "user", "content": raw_idea.strip()})
```

- [ ] **步骤 3：替换 _step2_questioning 中的 t() 调用**

```python
    def _step2_questioning(self) -> None:
        """Multi-turn Q&A loop with LLM."""
        d = self._display
        d.output.write("\n")
        d.output.write("━" * 50 + "\n")
        d.output.write(_("[Q&A Phase]") + "\n")
        d.output.write(
            _("I'll ask a few questions to understand the story you want.\n"
              "When you're ready, type 'go' to generate the story setup.\n"
              "Type 'quit' to return to the main menu.\n")
            + "\n"
        )

        lang = get_current_lang()
        if lang == "zh-CN":
            START_KEYWORDS = {"开始", "开始吧", "可以", "好的", "行", "ok", "OK", "yes"}
            QUIT_KEYWORDS = {"不玩了", "退出", "quit", "exit", "q"}
        else:
            START_KEYWORDS = {"go", "start", "begin", "yes", "ok", "OK", "ready", "开始"}
            QUIT_KEYWORDS = {"quit", "exit", "q", "stop", "abort", "不玩了", "退出"}
        MAX_QNA_ROUNDS = 15

        for _round in range(MAX_QNA_ROUNDS):
            d.show_wait_message(_("Thinking..."))
            try:
                response = self._api.chat(self._messages)
            except Exception as e:
                d.show_error(_("API call failed: {error}").format(error=e))
                choice = d.get_input(_("[R]etry / [M]enu: "))
                if choice.upper() == 'M':
                    raise CoCreationAborted()
                continue

            self._messages.append({"role": "assistant", "content": response})
            d.output.write(f"\n{response}\n\n")

            user_input = d.get_input(
                _("Your answer (or type 'go'/'quit')> ")
            ).strip()

            if not user_input:
                continue

            if user_input in START_KEYWORDS:
                d.output.write("\n")
                break

            if user_input in QUIT_KEYWORDS:
                confirm = d.get_input(
                    _("Abort co-creation and return to menu? (y/n): ")
                )
                if confirm.lower() in ("y", "yes", "是"):
                    raise CoCreationAborted()
                continue

            self._messages.append({"role": "user", "content": user_input})
        else:
            raise CoCreationAborted()
```

- [ ] **步骤 4：替换 _step3_generate_all 及其辅助方法中的 t() 调用**

```python
    def _step3_generate_all(self) -> CoCreationResult:
        var_names = self._build_var_names_hint()
        gen_prompt = GENERATE_ALL_PROMPT.format(variable_names=var_names)
        self._messages.append({"role": "user", "content": gen_prompt})

        self._display.show_wait_message(_("Weaving your story world..."))
        # ... rest unchanged (parsing logic doesn't use t())
```

`_generate_with_retry` 方法：

```python
    def _generate_with_retry(self) -> str:
        """Call LLM for generation. Handle API errors."""
        d = self._display
        for _ in range(10):
            try:
                return self._api.chat(self._messages)
            except Exception as e:
                d.show_error(_("Generation failed: {error}").format(error=e))
                choice = d.get_input(_("[R]etry / [M]enu: "))
                if choice.upper() == 'M':
                    raise CoCreationAborted()
        raise CoCreationAborted()
```

`_retry_outline_validation` 方法：

```python
    def _retry_outline_validation(
        self, errors: list[str], var_names: list[str]
    ) -> list[dict]:
        for _cycle in range(3):
            for attempt in range(MAX_RETRIES + 1):
                error_msg = "Outline errors: " + "; ".join(errors)
                self._messages.append(
                    {"role": "user",
                     "content": f"Outline has errors. {error_msg}\n"
                               f"Please fix and regenerate the outline block."}
                )
                self._display.show_wait_message(
                    _("Fixing {block}... (attempt {n})").format(
                        block="大纲", n=attempt + 1)
                )
                # ... rest of inner loop unchanged ...

            choice = self._display.get_input(
                _("Outline validation failed ({errors}).").format(
                    errors="; ".join(errors))
                + " " + _("[R]etry / [M]enu: ")
            )
            # ... rest unchanged ...
```

`_retry_block` 方法：

```python
                    self._display.show_wait_message(
                        _("Fixing {block}... (attempt {n})").format(
                            block=block_name, n=attempt + 1)
                    )
                    # ...

            choice = self._display.get_input(
                _("{block} parsing failed ({errors}).").format(
                    block=block_name, errors="; ".join(errors))
                + " " + _("[R]etry / [M]enu: ")
            )
```

- [ ] **步骤 5：检查是否还有其他 t() 调用**

```bash
grep -n "\.t(" src/storyloom/co_create.py
```

应无输出。

- [ ] **步骤 6：Commit**

```bash
git add src/storyloom/co_create.py
git commit -m "refactor: migrate co_create to gettext _() calls"
```

---

### 任务 5：迁移 main.py 到 gettext

**文件：**
- 修改：`src/storyloom/main.py`

- [ ] **步骤 1：添加导入，在 main() 中调用 init_i18n()**

添加导入：
```python
from src.storyloom.i18n import init_i18n, _
```

在 `main()` 函数中，`language` 解析之后立即调用 `init_i18n()`：

```python
def main(output=None) -> None:
    """Main entry point."""
    if output is None:
        args = parse_args()
    else:
        args = parse_args([])
    language = args.lang or os.environ.get("STORYLOOM_LANG") or DEFAULT_LANGUAGE
    if language not in SUPPORTED_LANGUAGES:
        language = DEFAULT_LANGUAGE

    init_i18n(language)

    display = Display(output=output)

    display.output.write("\n")
    display.output.write(_("Storyloom — Interactive Fiction") + "\n")
    display.output.write("=" * 40 + "\n\n")
```

- [ ] **步骤 2：移除 show_main_menu 和 run_game 的 language 参数**

`show_main_menu` 签名改为：
```python
def show_main_menu(display: Display, api_client: ApiClient) -> None:
```

`run_game` 签名改为：
```python
def run_game(
    display: Display,
    api_client: ApiClient,
    story_config: dict | None = None,
    outline_text: str | None = None,
) -> None:
```

- [ ] **步骤 3：替换 show_main_menu 中的 t() 调用**

```python
def show_main_menu(display: Display, api_client: ApiClient) -> None:
    """Show main menu and route user choices."""
    while True:
        display.show_main_menu(save_count=0)
        choice = display.get_input(_("Choose: "))

        if choice == "1":
            try:
                flow = CoCreateFlow(api_client, display)
                result = flow.run()
                run_game(display, api_client,
                         story_config=result.story_config,
                         outline_text=result.outline_text)
            except CoCreationAborted:
                display.output.write(_("Returning to menu.") + "\n")
            except ApiError as e:
                display.show_error(_("API error: {msg}").format(msg=e))
        elif choice == "2":
            display.show_wait_message(
                _("Loading: {feature}").format(feature="继续游戏（加载存档）"))
        elif choice == "3":
            display.show_wait_message(
                _("Loading: {feature}").format(feature="管理存档"))
        elif choice == "4":
            display.output.write(_("Goodbye.") + "\n")
            break
        else:
            display.output.write(_("Invalid choice, try again.") + "\n")
```

- [ ] **步骤 4：替换 run_game 中的 t() 调用**

```python
        display.show_error(_("API error: {msg}").format(msg=e))
```

```python
            display.show_error(_("API error: {msg}").format(msg=e))
```

```python
        choice = display.get_input("\n" + _("Choose an option (type quit to return to menu): ") + " ")

        if choice and choice.strip().lower() in ("quit", "exit", "q"):
            display.output.write(_("Returning to menu.") + "\n")
            return
```

```python
                display.output.write(
                    _("Invalid choice, please enter 1-{n}.").format(n=n_opts) + "\n")
```

```python
            display.output.write(_("Enter a number or quit.") + "\n")
```

- [ ] **步骤 5：替换 main() 中的硬编码中文错误消息**

```python
        display.show_error(
            "请复制 .env.example 为 .env 并填入 API 配置。"
        )
```

→ 保持不变（这是中文环境特有提示，不适合翻译）。

- [ ] **步骤 6：移除 main.py 调用处的 language 参数**

`args.quick` 分支：
```python
    if args.quick:
        run_game(display, api_client)
    else:
        show_main_menu(display, api_client)
```

- [ ] **步骤 7：检查是否还有其他 t() 调用**

```bash
grep -n "\.t(" src/storyloom/main.py
```

应无输出。

- [ ] **步骤 8：Commit**

```bash
git add src/storyloom/main.py
git commit -m "refactor: migrate main.py to gettext _() calls"
```

---

### 任务 6：更新测试

**文件：**
- 修改：`tests/test_co_create.py`
- 修改：`tests/test_main.py`

- [ ] **步骤 1：更新 MockApiClient（检查是否需要支持 chat 方法签名变化）**

`tests/test_co_create.py` 的 `MockApiClient` — 无变化（`chat()` 和 `stream_chat()` 签名不变）。

`tests/test_main.py` 的 `MockApiClient` — 无变化。

- [ ] **步骤 2：重写 MockDisplay（test_co_create.py）**

删除 `t()` 方法，使 MockDisplay 成为纯 IO 模拟：

```python
class MockDisplay:
    """Mock display that captures output and returns predefined inputs."""

    def __init__(self, inputs=None):
        self.inputs = list(inputs or [])
        self._input_idx = 0
        self.written = []

    @property
    def output(self):
        return self

    def write(self, text):
        self.written.append(text)

    def flush(self):
        pass

    def get_input(self, prompt=""):
        if self._input_idx < len(self.inputs):
            val = self.inputs[self._input_idx]
            self._input_idx += 1
            return val
        return ""

    def show_wait_message(self, msg):
        pass

    def show_error(self, msg):
        pass
```

- [ ] **步骤 3：在 test_co_create.py 顶部添加 i18n 初始化**

在 import 之后、任何 test 类之前添加 setUp 逻辑。在文件顶部 `import` 部分添加：

```python
from src.storyloom.i18n import init_i18n

# Initialize i18n for tests — use English for deterministic matching
init_i18n("en")
```

这确保所有 `_()` 调用返回英文 msgid，测试中的字符串匹配不变。

- [ ] **步骤 4：更新 test_main.py**

在文件顶部添加：
```python
from src.storyloom.i18n import init_i18n
init_i18n("en")
```

检查 `test_main.py` 中是否有对 `display.t()` 的调用或在测试中创建 Display 时的 `language` 参数——如有则删除。

- [ ] **步骤 5：运行测试**

```bash
python3 -m pytest tests/test_co_create.py tests/test_main.py tests/test_display.py tests/test_xml_parser.py tests/test_context_manager.py tests/test_prompt_builder.py tests/test_integration.py -q
```

预期：全部通过（~143 tests）。

- [ ] **步骤 6：Commit**

```bash
git add tests/
git commit -m "test: update tests for gettext migration"
```

---

### 任务 7：更新 narrative-flow-refactor 规格

**文件：**
- 修改：`docs/superpowers/specs/2026-07-05-narrative-flow-refactor-design.md`

- [ ] **步骤 1：更新 §6 不变模块表**

找到：
```
| `display.py` | 终端 UI 不修改 |
```

替换为：
```
| `display.py` | 终端 UI 已在 2026-07-06 i18n migration 中修改 |
```

- [ ] **步骤 2：Commit**

```bash
git add docs/superpowers/specs/2026-07-05-narrative-flow-refactor-design.md
git commit -m "docs: update narrative-flow-refactor invariants for i18n migration"
```

---

### 任务 8：端到端验证

- [ ] **步骤 1：运行全部测试**

```bash
python3 -m pytest tests/ -q
```

预期：全部通过。

- [ ] **步骤 2：手动验证中文界面**

```bash
python3 -c "
from src.storyloom.i18n import init_i18n, _
init_i18n('zh-CN')
print(_('Storyloom — Interactive Fiction'))
print(_('[1] New Game'))
print(_('Choose: '))
print(_('Generating story...'))
print(_('[Co-Creation — Story Setup]'))
print(_('Thinking...'))
"
```

预期：全部输出中文。

- [ ] **步骤 3：手动验证英文界面**

```bash
python3 -c "
from src.storyloom.i18n import init_i18n, _
init_i18n('en')
print(_('Storyloom — Interactive Fiction'))
print(_('[1] New Game'))
print(_('Choose: '))
print(_('Generating story...'))
print(_('[Co-Creation — Story Setup]'))
print(_('Thinking...'))
"
```

预期：全部输出英文原文。

- [ ] **步骤 4：验证 .mo 缺失时的 fallback**

```bash
python3 -c "
import os
# Temporarily hide .mo file
os.rename('locale/zh_CN/LC_MESSAGES/storyloom.mo', 'locale/zh_CN/LC_MESSAGES/storyloom.mo.bak')
from src.storyloom.i18n import init_i18n, _
init_i18n('zh-CN')
result = _('Storyloom — Interactive Fiction')
print(result)
# Restore
os.rename('locale/zh_CN/LC_MESSAGES/storyloom.mo.bak', 'locale/zh_CN/LC_MESSAGES/storyloom.mo')
"
```

预期：输出 `Storyloom — Interactive Fiction`（英文原文，无崩溃）。

- [ ] **步骤 5：Commit（如有遗漏）**

```bash
git status
# commit any remaining changes
```
