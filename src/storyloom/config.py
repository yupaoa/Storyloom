"""Configurable constants for Storyloom engine.

All constants defined here; no hardcoded values in business logic.
Reference values from docs/spec/data-model.md §A.
"""

# Path constants
SAVE_DIR: str = "saves/"

# Co-creation stage
MAX_RETRIES: int = 2
STORY_LABEL_MIN_CHARS: int = 5
STORY_LABEL_MAX_CHARS: int = 15

# Story tier identifiers
STORY_TIER_SHORT: str = "short"
STORY_TIER_MEDIUM: str = "medium"
STORY_TIER_LONG: str = "long"

# Narrative segment control
SEGMENTS_PER_ROUND_MIN: int = 60
SEGMENTS_PER_ROUND_MAX: int = 120
BRIDGE_SEGMENT_RATIO: float = 0.4

# Runtime
STREAM_STALL_TIMEOUT_SEC: int = 3
MIN_NARRATION_CHARS: int = 200
AUTO_ADVANCE_DELAY_MS: int = 500
SAVE_VERSION: int = 1
