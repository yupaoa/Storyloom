"""Configurable constants for Storyloom."""

# ── Sliding window ─────────────────────────────────────────────
WINDOW_SIZE = 3          # full rounds to keep in window
FIRST_COMPRESSION_AT = 5  # round number to trigger first compression

# ── Line count ranges ─────────────────────────────────────────
LINES_PER_ROUND_MIN = 150
LINES_PER_ROUND_MAX = 300

# ── Language-specific segment limits ───────────────────────────
LANGUAGE_SEG_LIMITS = {
    "zh-CN": {"narration": 40, "dialogue": 50},
}

# ── Bridge ─────────────────────────────────────────────────────
BRIDGE_POSITION_RATIO = 0.75  # target bridge position (fraction of total, pre-bridge)
MIN_TAIL_LINES = 25           # minimum lines per branch after bridge

# ── Context budget ────────────────────────────────────────────
MAX_CONTEXT_TOKENS = 50_000   # target ceiling

# ── API defaults ──────────────────────────────────────────────
DEFAULT_MODEL = "deepseek-chat"
STREAM_STALL_TIMEOUT_SEC = 180
