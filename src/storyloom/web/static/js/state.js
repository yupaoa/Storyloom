/* ═══════════════════════════════════════════════════════════════════
   state.js — Front-end game state + i18n

   GameState singleton holds all client-side game state:
     gameId, roundCount, currentNode, endingFlag,
     outlineNodes, stateVars, displayMode, speedPreset, lang.

   _(msgid) — i18n lookup.  Mirrors server-side gettext _() convention.
              Keys are English source strings (msgid); translations come
              from the dictionary matching GameState.lang.

   The ``T`` translation dictionary is auto-generated from .po files
   into i18n-dict.js (loaded before this script).  .po is now the
   single authoritative source — no more dual-write.

   Authority:
     src/storyloom/i18n.py (gettext _() convention)
     locale/zh_CN/LC_MESSAGES/storyloom.po (authoritative translations)
     src/storyloom/i18n_compile.py §generate_js_dict (build-time generation)
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
    lang: localStorage.getItem("storyloom-lang") || "en",

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
