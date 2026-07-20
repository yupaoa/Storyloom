"""Storyloom — AI-powered interactive text fiction game engine."""

__version__ = "1.0.0"

from storyloom.io.api_client import ApiClient, ApiError, ApiResult
from storyloom.config import WINDOW_SIZE, DEFAULT_MODEL
from storyloom.core.context_manager import ContextManager
from storyloom.core.game_loop import GameLoop, GameState, RoundResult, RoundRecord
from storyloom.core.prompt_builder import PromptBuilder
from storyloom.core.save_manager import SaveManager
from storyloom.core.session import GameSession
from storyloom.user_config import UserConfig

from storyloom.parser import ParsedOutput, ParseError, Segment

__all__ = [
    "ApiClient",
    "ApiError",
    "ApiResult",
    "ContextManager",
    "DEFAULT_MODEL",
    "GameLoop",
    "GameSession",
    "GameState",
    "ParsedOutput",
    "ParseError",
    "PromptBuilder",
    "RoundRecord",
    "RoundResult",
    "SaveManager",
    "Segment",
    "UserConfig",

    "WINDOW_SIZE",
]
