"""Storyloom — AI-powered interactive text fiction game engine."""

from storyloom.io.api_client import ApiClient, ApiError, ApiResult
from storyloom.config import WINDOW_SIZE, DEFAULT_MODEL
from storyloom.core.context_manager import ContextManager
from storyloom.io.display import Display
from storyloom.core.game_loop import GameLoop, GameState, RoundResult, RoundRecord
from storyloom.core.prompt_builder import PromptBuilder
from storyloom.parser.xml_parser import XmlParser, ParsedOutput, ParseError, Segment

__all__ = [
    "ApiClient",
    "ApiError",
    "ApiResult",
    "ContextManager",
    "DEFAULT_MODEL",
    "Display",
    "GameLoop",
    "GameState",
    "ParsedOutput",
    "ParseError",
    "PromptBuilder",
    "RoundRecord",
    "RoundResult",
    "Segment",
    "WINDOW_SIZE",
    "XmlParser",
]
