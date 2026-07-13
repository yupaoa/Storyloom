/* ═══════════════════════════════════════════════════════════════════
   state.js — Front-end game state + outline + i18n
   ═══════════════════════════════════════════════════════════════════ */

const GameState = {
    gameId: null,
    roundCount: 0,
    currentNode: null,
    endingFlag: false,
    outlineNodes: [],
    stateVars: {},
    displayMode: "auto",
    speedPreset: "normal",  // "fast" | "normal" | "slow" | "instant" | "manual"
    lang: localStorage.getItem("storyloom-lang") || "zh-CN",

    reset() {
        this.gameId = null;
        this.roundCount = 0;
        this.currentNode = null;
        this.endingFlag = false;
        this.outlineNodes = [];
        this.stateVars = {};
    },

    setLang(lang) {
        this.lang = lang;
        localStorage.setItem("storyloom-lang", lang);
    },
};

/* UI text dictionary — mirrors locale .po translations */
const T = {
    "zh-CN": {
        "new_game": "新游戏",
        "continue": "继续",
        "save_management": "存档管理",
        "exit": "退出",
        "send": "发送",
        "generate": "生成设定",
        "quit": "退出",
        "retry": "重试",
        "back_to_menu": "返回主菜单",
        "save": "存档",
        "delete": "删除",
        "load": "加载",
        "confirm": "确定",
        "cancel": "取消",
        "no_saves": "暂无存档",
        "loading": "加载中...",
        "waiting_llm": "等待 LLM 回复...",
        "generating_story": "正在生成故事设定...",
        "enter_to_continue": "按 Enter 继续",
        "auto_mode": "自动",
        "manual_mode": "手动",
        "instant_mode": "即时",
        "game_over": "游戏结束",
        "adventure_log": "冒险日志",
        "language_locked": "游戏结束后可切换语言",
        "describe_story": "请描述你想玩的故事...",
        "your_answer": "输入你的回答...",
        "story_area_placeholder": "故事将在这里展开...",
        "display_mode": "展示模式",
        "speed": "速度",
        "speed_fast": "快",
        "speed_normal": "正常",
        "speed_slow": "慢",
        "speed_instant": "即时",
        "speed_manual": "手动",
        "display_speed": "展示速度",
        "story_generated": "故事设定已生成",
        "outline": "大纲",
        "nodes": "个节点",
        "start_adventure": "开始冒险",
    },
    "en": {
        "new_game": "New Game",
        "continue": "Continue",
        "save_management": "Saves",
        "exit": "Exit",
        "send": "Send",
        "generate": "Generate Story",
        "quit": "Quit",
        "retry": "Retry",
        "back_to_menu": "Back to Menu",
        "save": "Save",
        "delete": "Delete",
        "load": "Load",
        "confirm": "Confirm",
        "cancel": "Cancel",
        "no_saves": "No saves found",
        "loading": "Loading...",
        "waiting_llm": "Waiting for LLM...",
        "generating_story": "Generating story setup...",
        "enter_to_continue": "Press Enter to continue",
        "auto_mode": "Auto",
        "manual_mode": "Manual",
        "instant_mode": "Instant",
        "game_over": "Game Over",
        "adventure_log": "Adventure Log",
        "language_locked": "Language locked during gameplay",
        "describe_story": "Describe the story you'd like to play...",
        "your_answer": "Type your answer...",
        "story_area_placeholder": "Your story will unfold here...",
        "display_mode": "Display Mode",
        "speed": "Speed",
        "speed_fast": "Fast",
        "speed_normal": "Normal",
        "speed_slow": "Slow",
        "speed_instant": "Instant",
        "speed_manual": "Manual",
        "display_speed": "Display Speed",
        "story_generated": "Story setup generated",
        "outline": "Outline",
        "nodes": "nodes",
        "start_adventure": "Start Adventure",
    },
};

function t(key) {
    const dict = T[GameState.lang] || T["zh-CN"];
    return dict[key] || key;
}
