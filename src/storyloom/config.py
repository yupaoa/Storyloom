"""Configurable constants for Storyloom."""

# ── Sliding window ─────────────────────────────────────────────
WINDOW_SIZE = 3          # full rounds to keep in window
FIRST_COMPRESSION_AT = 5  # round number to trigger first compression

# ── Segment ranges ────────────────────────────────────────────
SEGMENTS_PER_ROUND_MIN = 120
SEGMENTS_PER_ROUND_MAX = 200
SEGMENTS_HARD_CAP = 200

# ── Bridge ─────────────────────────────────────────────────────
BRIDGE_POSITION_RATIO = 0.75  # target bridge position (fraction of total, pre-bridge)
MIN_TAIL_SEGMENTS = 15       # minimum segments per branch after bridge

# ── Context budget ────────────────────────────────────────────
MAX_CONTEXT_TOKENS = 50_000   # target ceiling

# ── API defaults ──────────────────────────────────────────────
DEFAULT_MODEL = "deepseek-chat"
STREAM_STALL_TIMEOUT_SEC = 180
