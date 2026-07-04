"""Configurable constants for Storyloom."""

# ── Sliding window ─────────────────────────────────────────────
WINDOW_SIZE = 3          # full rounds to keep in window
FIRST_COMPRESSION_AT = 5  # round number to trigger first compression

# ── Segment ranges ────────────────────────────────────────────
SEGMENTS_PER_ROUND_MIN = 60
SEGMENTS_PER_ROUND_MAX = 120
SEGMENTS_HARD_CAP = 120

# ── Bridge ─────────────────────────────────────────────────────
BRIDGE_POSITION_RATIO = 0.5  # target bridge position (fraction of total)
MIN_TAIL_SEGMENTS = 15       # minimum segments per branch after bridge

# ── Context budget ────────────────────────────────────────────
MAX_CONTEXT_TOKENS = 50_000   # target ceiling

# ── API defaults ──────────────────────────────────────────────
DEFAULT_MODEL = "deepseek-chat"
STREAM_STALL_TIMEOUT_SEC = 60
