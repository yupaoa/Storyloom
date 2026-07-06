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
    "en":    {"narration": 120, "dialogue": 160},
}
SUPPORTED_LANGUAGES = {"zh-CN", "en"}
DEFAULT_LANGUAGE = "zh-CN"

# ── Bridge ─────────────────────────────────────────────────────
BRIDGE_POSITION_RATIO = 0.75  # target bridge position (fraction of total, pre-bridge)
MIN_TAIL_LINES = 25           # minimum lines per branch after bridge

# ── Context budget ────────────────────────────────────────────
MAX_CONTEXT_TOKENS = 50_000   # target ceiling

# ── Co-creation ──────────────────────────────────────────────────
MAX_RETRIES = 2

# Variable caps (per 2026-07-05 variable-cap spec)
VARIABLE_CAP = 3            # max total variables
VARIABLE_NUMERIC_CAP = 2    # max numeric (number) variables
VARIABLE_LABEL_CAP = 1      # max label (string/list) variables

# Story config label constraints
STORY_LABEL_MIN_CHARS = 5
STORY_LABEL_MAX_CHARS = 15

# Outline node ranges by tier
OUTLINE_NODE_RANGES = {
    "short":  (3, 5),
    "medium": (5, 8),
    "long":   (8, 15),
}

# ── API defaults ──────────────────────────────────────────────
DEFAULT_MODEL = "deepseek-v4-pro"
STREAM_STALL_TIMEOUT_SEC = 180
