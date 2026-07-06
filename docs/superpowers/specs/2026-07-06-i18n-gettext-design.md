# i18n gettext Migration — Design Spec

> 2026-07-06 | Migrate UI strings from `Display.UI` dict to standard gettext `.po`/`.mo` files.
> Scope: All user-facing UI strings (co-creation + narrative flow + menus). Prompt content stays fixed.

## §1 Motivation

**Current** (`Display.UI` dict):
```python
UI = {
    "zh-CN": {"cc_header": "【共创阶段 — 故事设定】", ...},
    "en":    {"cc_header": "[Co-Creation — Story Setup]", ...},
}
display.t("cc_header")  # → lookup by abstract key
```

**Problems:**
- Translations embedded in Python source — non-developer translators can't work with it
- Abstract keys (`cc_header`) violate gettext convention — `xgettext` can't extract them
- Adding a 3rd language requires editing source code
- `Display` carries `language` state + `UI` dict + `t()` method — mixed concerns

**Target** (gettext standard):
```python
from src.storyloom.i18n import _
_("Co-Creation — Story Setup")  # → zh_CN.po translates; en returns as-is
```

## §2 Architecture

```
locale/
  storyloom.pot                    ← template (auto-generated, git-tracked)
  zh_CN/
    LC_MESSAGES/
      storyloom.po                 ← Chinese translations
      storyloom.mo                 ← compiled binary (gitignored)

src/storyloom/
  i18n.py                          ← [NEW] init_i18n() + _() export
  display.py                       ← [MOD] remove UI/t()/language; _() everywhere
  main.py                          ← [MOD] call init_i18n() at startup
  co_create.py                     ← [MOD] display.t() → _()
```

**Data flow:**
```
main.py: parse --lang / STORYLOOM_LANG / DEFAULT_LANGUAGE
  ↓
i18n.init_i18n(language)
  ↓
gettext.translation("storyloom", "locale/", languages=[lang], fallback=True)
  ↓
Module-level _() available everywhere via `from src.storyloom.i18n import _`
```

**Language resolution** (unchanged priority):
1. `--lang` CLI argument
2. `STORYLOOM_LANG` env var
3. `DEFAULT_LANGUAGE` = `"zh-CN"`

## §3 Module Design

### 3.1 i18n.py (NEW)

```python
import gettext
import os

from src.storyloom.config import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE

_translators = {}
_current_lang = DEFAULT_LANGUAGE


def init_i18n(language: str | None = None) -> None:
    """Initialize gettext for the given language. Call once at startup."""
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


def _(message: str) -> str:
    """Mark string for translation. Drop-in for gettext.gettext."""
    trans = _translators.get(_current_lang)
    if trans is None:
        return message
    return trans.gettext(message)
```

**Design notes:**
- `fallback=True`: missing `.mo` file → return English msgid as-is (no crash)
- `_translators` dict retains possibility of runtime language switch
- Imports use `gettext` after `import gettext` to avoid module name shadowing

### 3.2 display.py (MODIFIED)

**Removed:**
- `Display.UI` dict (~80 lines)
- `Display.t()` method
- `Display.__init__` `language` parameter
- `self.language` attribute
- `show_error(msg)` — callers use `_("Error: {msg}")` directly
- `show_wait_message(msg)` — callers use `_("...")` directly
- `show_section_break()` — callers use `_("...")` directly

**Added:**
- `from src.storyloom.i18n import _` at module level
- All UI strings wrapped in `_("...")`

**Full UI string catalog (~18 msgids):**

| msgid (English original) | Context |
|--------------------------|---------|
| `Storyloom — Interactive Fiction` | Banner |
| `[1] New Game` | Menu |
| `[2] Continue` | Menu |
| `[3] Manage Saves` | Menu |
| `[4] Exit` | Menu |
| `Choose: ` | Menu prompt |
| `Invalid choice, try again.` | Menu error |
| `Goodbye.` | Exit |
| `Returning to menu.` | Navigation |
| `[{min}-{max}] Choose an option (0 for status, Q to quit): ` | Game choice prompt |
| `Invalid choice. Enter {min}-{max}, 0, or Q.` | Game choice error |
| `────────────────────────────────────` | Section divider |
| `···` | Segment separator |
| `Error: {msg}` | Error template |
| `Saving...` | Status |
| `Loading...` | Status |
| `Generating story...` | Status |
| `Under development` | Placeholder |
| `API error: {msg}` | Error template |

### 3.3 co_create.py (MODIFIED)

**Mechanical replacement** of `display.t("key", ...)` → `_("English text", ...)`.

| Current | Replacement |
|---------|-------------|
| `d.t("cc_header")` | `_("[Co-Creation — Story Setup]")` |
| `d.t("cc_idea_prompt")` | `_("Describe the story you'd like to play.\ne.g. 'A cyberpunk love story' or 'A wuxia adventure'\n")` |
| `d.t("cc_idea_empty")` | `_("Please share some thoughts to begin.")` |
| `d.t("cc_qna_header")` | `_("[Q&A Phase]")` |
| `d.t("cc_qna_desc")` | `_("I'll ask a few questions to understand the story you want.\nWhen you're ready, type 'go' to generate the story setup.\nType 'quit' to return to the main menu.\n")` |
| `d.t("cc_think")` | `_("Thinking...")` |
| `d.t("cc_qna_prompt")` | `_("Your answer (or type 'go'/'quit')> ")` |
| `d.t("cc_gen_wait")` | `_("Weaving your story world...")` |
| `d.t("cc_fix_block", ...)` | `_("Fixing {block}... (attempt {n})")` |
| `d.t("cc_block_fail", ...)` | `_("{block} parsing failed ({errors}).")` |
| `d.t("cc_retry_prompt")` | `_("[R]etry / [M]enu: ")` |
| `d.t("cc_api_fail", ...)` | `_("API call failed: {error}")` |
| `d.t("cc_confirm_quit")` | `_("Abort co-creation and return to menu? (y/n): ")` |
| `d.t("cc_gen_fail", ...)` | `_("Generation failed: {error}")` |
| `d.t("cc_outline_fail", ...)` | `_("Outline validation failed ({errors}).")` |

**Also removed from `CoCreateFlow.__init__`:**
- `language` parameter
- `self._language` attribute
- `lang_names` dict + language instruction injection (prompt already in English, LLM infers language from user's messages)

### 3.4 main.py (MODIFIED)

- Call `init_i18n(language)` immediately after language resolution
- Remove `language` parameter from `show_main_menu()`, `run_game()`, `CoCreateFlow()`
- All `display.t("key")` → `_("English text")`

## §4 .po File Management

### Workflow

```bash
# 1. Extract msgids from source → .pot template
xgettext -o locale/storyloom.pot \
  --from-code=UTF-8 \
  --keyword=_ \
  src/storyloom/*.py

# 2. Initialize or update .po from template
msgmerge -U locale/zh_CN/LC_MESSAGES/storyloom.po locale/storyloom.pot

# 3. Compile .po → .mo
msgfmt -o locale/zh_CN/LC_MESSAGES/storyloom.mo \
  locale/zh_CN/LC_MESSAGES/storyloom.po
```

### Directory structure

```
locale/
  storyloom.pot              ← template (git tracked)
  zh_CN/
    LC_MESSAGES/
      storyloom.po           ← translations (git tracked)
      storyloom.mo           ← compiled (gitignored)
```

`.mo` files are gitignored — generated during dev setup or CI.

### Initial zh_CN translation coverage

~33 msgids total (~18 display + ~15 co-creation). All have existing translations in the current `Display.UI` dict — migration extracts them into `.po` format.

## §5 Test Changes

| File | Change |
|------|--------|
| `tests/test_co_create.py` | `MockDisplay` drops `t()` method. `setUp` calls `init_i18n("en")` for deterministic English output |
| `tests/test_main.py` | `MockDisplay` drops `t()` method. Test fixtures call `init_i18n("en")` |
| `tests/test_display.py` | Optional new file — verifies `_()` returns zh-CN strings when `init_i18n("zh-CN")` is called |

## §6 Conflict with narrative-flow-refactor

`docs/superpowers/specs/2026-07-05-narrative-flow-refactor-design.md` §6 lists `display.py` as an invariant module ("终端 UI 不修改"). This i18n migration **must** modify `display.py`. Since the narrative flow refactor has not started implementation, this spec takes priority. The narrative flow spec's §6 should be updated to note `display.py` was modified by the 2026-07-06 i18n migration.

## §7 Implementation Order

| Step | Module | Content |
|------|--------|---------|
| 1 | `locale/` + `.po` | Create directory structure, write `zh_CN/LC_MESSAGES/storyloom.po`, compile `.mo` |
| 2 | `src/storyloom/i18n.py` | New module: `init_i18n()` + `_()` export |
| 3 | `src/storyloom/display.py` | Remove `UI`/`t()`/`language`; wrap all strings in `_()` |
| 4 | `src/storyloom/co_create.py` | `display.t("key")` → `_("English text")`; remove `language` param |
| 5 | `src/storyloom/main.py` | Call `init_i18n()`, remove `language` param passing, `t()` → `_()` |
| 6 | Tests | Update `MockDisplay`, add `init_i18n("en")` to setUp |
| 7 | `docs/superpowers/specs/2026-07-05-narrative-flow-refactor-design.md` | Update §6 invariants table |
| 8 | Verification | Run all tests, manual smoke test |

## §8 Verification Criteria

1. **All 143 existing tests pass** with gettext-based `_()` replacing `display.t()`
2. **`python -m src.storyloom.main`** — zh-CN UI displays correctly (default)
3. **`python -m src.storyloom.main --lang en`** — English UI displays correctly
4. **`STORYLOOM_LANG=en python -m src.storyloom.main`** — env var works
5. **Missing `.mo` file** — falls back to English msgid (no crash)
6. **`xgettext` extracts all msgids** without errors
