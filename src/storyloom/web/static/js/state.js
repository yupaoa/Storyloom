/* ═══════════════════════════════════════════════════════════════════
   state.js — Front-end game state + i18n

   GameState singleton holds all client-side game state:
     gameId, roundCount, currentNode, endingFlag,
     outlineNodes, stateVars, displayMode, speedPreset, lang.

   _(msgid) — i18n lookup.  Mirrors server-side gettext _() convention.
              Keys are English source strings (msgid); translations come
              from the dictionary matching GameState.lang.

   Authority:
     src/storyloom/i18n.py (gettext _() convention)
     locale/zh_CN/LC_MESSAGES/storyloom.po (authoritative translations)
     CLAUDE.local.md §3.2 (event-driven state updates)
   ═══════════════════════════════════════════════════════════════════ */

const GameState = {
    gameId: null,
    roundCount: 0,
    currentNode: null,
    endingFlag: false,
    outlineNodes: [],
    stateVars: {},
    displayMode: "auto",
    speedPreset: "normal",
    lang: localStorage.getItem("storyloom-lang") || "zh-CN",

    /** Story config from co-creation, set before game/new.
     *  Populated by _handleStart() in co-create.js after generate(). */
    storyConfig: null,

    /** Save file selected from checkpoint list.  When set, game-preview
     *  loads this file instead of ``_init.json``. */
    saveFile: null,

    /** Reset all per-game state.  Called on menu entry. */
    reset() {
        this.gameId = null;
        this.roundCount = 0;
        this.currentNode = null;
        this.endingFlag = false;
        this.outlineNodes = [];
        this.stateVars = {};
        this.storyConfig = null;
        this.saveFile = null;
    },

    /** Set language and persist to localStorage. */
    setLang(lang) {
        this.lang = lang;
        localStorage.setItem("storyloom-lang", lang);
    },
};

/* ── UI text dictionary ─────────────────────────────────────────── */
/* Keys are English source strings (msgid), matching gettext convention
   and locale/zh_CN/LC_MESSAGES/storyloom.po msgid entries.
   The en dict is an identity map — _() returns the key itself.

   ⚠️  DUAL-WRITE CONVENTION: Every new msgid must be added to BOTH
   this T dictionary AND locale/zh_CN/LC_MESSAGES/storyloom.po.
   The .po file is the authoritative source; this dictionary is the
   SPA's client-side mirror (browsers cannot consume gettext .mo).   */

const T = {
    "zh-CN": {
        /* Menu */
        "Storyloom": "Storyloom",
        "AI Text Adventure": "AI 文字冒险",
        "New Game": "新游戏",
        "Continue": "继续",
        "Load Save": "读取存档",
        "Settings": "设置",
        "Credits": "制作人员",
        "Exit": "退出",
        "Recent Saves": "最近存档",
        "No saves found": "暂无存档",
        "Language": "语言",
        "API Base URL": "API 地址",
        "API Key": "API 密钥",
        "Model": "模型",
        /* Credits */
        "Engine & System Architecture": "引擎 & 系统架构",
        "Web Interface": "Web 界面",
        /* Co-Create */
        "Co-Create": "共创设定",
        "Start": "开始",
        "Send": "发送",
        "Type your story idea...": "输入你的故事想法...",
        "Type your answer...": "输入你的回答...",
        "Retry": "重试",
        "Thinking": "正在思考",
        "Generating settings": "正在生成设定",
        /* Game Preview */
        "Begin Adventure": "开始冒险",
        /* Shared */
        "Loading...": "加载中...",
        "Save": "存档",
        "Delete": "删除",
        "Load": "加载",
        "Edit": "编辑",
        "Cancel": "取消",
        "Back to Menu": "返回主菜单",
        "Goodbye": "再见",
        "You may close this tab.": "你可以关闭此标签页。",
        "Something went wrong": "出了点问题",
        /* Save Browser */
        "Delete this game?": "确定删除此游戏？",
        "Delete this save?": "确定删除此存档？",
        "This cannot be undone.": "此操作无法撤销。",
        "Yes": "是",
        "No": "否",
        "No saves in this game.": "此游戏暂无存档。",
        "Game deleted.": "游戏已删除。",
        "Save deleted.": "存档已删除。",
        "saves": "个存档",
        "Restart": "重新开始",
        /* Game Narrative */
        "Generating adventure log...": "正在生成冒险日志...",
        "Story has ended. Generate adventure log?": "故事已结束。是否生成冒险日志？",
        "Generate adventure log?": "是否生成冒险日志？",
        "View Log": "开始查看",
        "Quit": "退出",
        "Retry": "重试",
        "Loading": "加载中",
        "Speed": "生成速度",
        "Font Size": "字体大小",
        "Line Spacing": "行间距",
        "Close": "关闭",
        "Toggle Mode": "切换模式",
        "Switch to Auto": "切换至自动模式",
        "Switch to Manual": "切换至手动模式",
        "Settings": "设置",
        "(unavailable)": "(不可用)",
        "Choice send failed: ": "选项发送失败: ",
        "Game start failed: ": "游戏启动失败: ",
        "Retry failed: ": "重试失败: ",
        "Unknown error": "未知错误",
        "OK": "确定",
        "Small": "小",
        "Medium": "中",
        "Large": "大",
    },
    "en": {
        /* English is the source language — identity map */
    },
};

/* ── Settings ────────────────────────────────────────────────────── */
/* Data-driven settings panel.  Add a new object to the SETTINGS array
   to add a row to the settings overlay — no HTML changes needed.

   Supported types: "select", "text", "password".

   All setting values are persisted in localStorage under the key
   "storyloom-setting-<key>".  The "lang" setting is mirrored to
   GameState.lang for convenience.

   Authority: keys, defaults, and structure mirror
              src/storyloom/user_config.py UserConfig._DEFAULTS.

   ⚠️  SYNC: api_base_url and api_model placeholder values must
   stay in sync with UserConfig._DEFAULTS.  When the backend
   defaults change, update the placeholders here too.             */

const SETTINGS_STORE = "storyloom-setting-";

const SETTINGS = [
    /* ── Language ── */
    {
        key: "lang",
        type: "select",
        label: "Language",
        options: [
            { value: "zh-CN", label: "中文" },
            { value: "en", label: "English" },
        ],
    },
    /* ── API Configuration (mirrors UserConfig properties) ── */
    {
        key: "api_base_url",
        type: "text",
        label: "API Base URL",
        placeholder: "https://api.deepseek.com",
    },
    {
        key: "api_key",
        type: "password",
        label: "API Key",
        placeholder: "sk-...",
    },
    {
        key: "api_model",
        type: "text",
        label: "Model",
        placeholder: "deepseek-v4-pro",
    },
];

/** Get the current value of a setting by key.
 *  Reads from localStorage first (instant); server is the
 *  authoritative source loaded via initConfig() at startup.
 *  For api_key: returns the real key if set, otherwise falls
 *  back to the server-provided masked display hint.            */
function getSetting(key) {
    if (key === "lang") return GameState.lang;
    const val = localStorage.getItem(SETTINGS_STORE + key);
    if (val) return val;
    if (key === "api_key") {
        return localStorage.getItem(SETTINGS_STORE + "api_key_display") || "";
    }
    return "";
}

/** Apply a setting change — localStorage immediately, then
 *  persist to config.json via UserConfig.save() in background.
 *  Returns true if the change requires a UI re-render.         */
function applySetting(key, value) {
    localStorage.setItem(SETTINGS_STORE + key, value);
    /* Once the user has typed a real key, the masked display hint
       is no longer needed. */
    if (key === "api_key" && value && !value.includes("****")) {
        localStorage.removeItem(SETTINGS_STORE + "api_key_display");
    }
    if (key === "lang") GameState.setLang(value);
    saveConfig();
    return key === "lang";
}

/** Push current settings to server → UserConfig.save(). */
async function saveConfig() {
    const key = getSetting("api_key");
    const body = {
        language: getSetting("lang"),
        api_base_url: getSetting("api_base_url"),
        api_model: getSetting("api_model"),
    };
    /* Only send api_key if the user typed a real one — an empty or
       masked value means "keep the existing key on disk". */
    if (key && !key.includes("****")) body.api_key = key;

    try { await API.post("/api/config", body); } catch (err) {
        console.warn("saveConfig: server unreachable, values in localStorage only", err);
    }
}

/** Pull config from server (UserConfig properties) at startup.
 *  Populates localStorage + GameState.lang.  Call once on load. */
async function initConfig() {
    try {
        const data = await API.get("/api/config");
        if (data.language) {
            GameState.setLang(data.language);
            localStorage.setItem(SETTINGS_STORE + "lang", data.language);
        }
        /* Server returns masked key for display hint only.
           Store it separately so the masked value never pollutes
           the editable api_key slot — saveConfig's guard relies on
           this separation. */
        if (data.api_key) {
            localStorage.setItem(SETTINGS_STORE + "api_key_display", data.api_key);
        }
        if (data.api_base_url) {
            localStorage.setItem(SETTINGS_STORE + "api_base_url", data.api_base_url);
        }
        if (data.api_model) {
            localStorage.setItem(SETTINGS_STORE + "api_model", data.api_model);
        }
    } catch (err) {
        console.warn("initConfig: server unreachable, using localStorage", err);
    }
}

/**
 * Look up a translated string.
 * Mirrors server-side gettext _() convention.
 *
 * @param {string} msgid — English source string
 * @returns {string} translated string in the current language,
 *                   or msgid itself if no translation exists
 */
function _(msgid) {
    const dict = T[GameState.lang];
    if (dict && dict[msgid] !== undefined) return dict[msgid];
    return msgid;
}

/**
 * Show a temporary toast notification that auto-dismisses.
 *
 * @param {string} message — already-translated string to display
 * @param {number} duration — ms before auto-dismiss (default 3000)
 */
function showToast(message, duration = 3000) {
    let container = document.getElementById("toast-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "toast-container";
        document.body.appendChild(container);
    }
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = message;
    container.appendChild(toast);
    /* trigger reflow for enter animation */
    void toast.offsetWidth;
    toast.classList.add("toast--visible");
    setTimeout(() => {
        toast.classList.remove("toast--visible");
        const cleanup = () => {
            toast.remove();
            toast.removeEventListener("transitionend", cleanup);
        };
        toast.addEventListener("transitionend", cleanup);
        /* Fallback: force-remove after transition duration in case
           transitionend never fires (e.g. element removed from DOM). */
        setTimeout(cleanup, 500);
    }, duration);
}
