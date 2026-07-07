"""GameSession — lightweight lifecycle coordinator for the Storyloom engine.

Owns ApiClient and SaveManager. Wires CoCreateFlow → GameLoop transitions
so the UI doesn't need to know internal dependency order.

UI retains full control over rendering and interaction flow.
"""

from storyloom.io.api_client import ApiClient
from storyloom.core.save_manager import SaveManager
from storyloom.core.co_create import CoCreateFlow, CoCreationResult
from storyloom.core.game_loop import GameLoop, GameState


class GameSession:
    """Lightweight lifecycle coordinator.

    Does NOT control UI flow. UI calls methods at its own pace.

    Usage:
        session = GameSession()
        flow = session.new_co_create()
        # ... drive flow.start() / flow.send() ...
        gl = session.start_game(flow.result)
        # ... drive gl.start_round1_stream() / continue_round_stream() ...
        # Or load:
        gl = session.load_game("save_label")
    """

    def __init__(self, saves_dir: str = "saves"):
        self._api_client = ApiClient()
        self._save_manager = SaveManager(saves_dir)
        self._game_loop: GameLoop | None = None

    # ── Save management ──

    def list_saves(self) -> list[dict]:
        return self._save_manager.list_saves()

    def delete_save(self, label: str) -> bool:
        return self._save_manager.delete(label)

    # ── Lifecycle ──

    def new_co_create(self) -> CoCreateFlow:
        return CoCreateFlow(self._api_client)

    def start_game(self, result: CoCreationResult) -> GameLoop:
        story_config = result.story_config
        game_state = GameState(story_config)

        outline_nodes = result.outline_nodes
        first_node = ""
        first_goal = ""
        if outline_nodes:
            first_node = outline_nodes[0].get("id", "")
            first_goal = outline_nodes[0].get("goal", "")

        gl = GameLoop(
            story_config=story_config,
            outline_text=result.outline_text,
            api_client=self._api_client,
            game_state=game_state,
            current_node=first_node or None,
            goal=first_goal or None,
            outline_nodes=outline_nodes,
        )
        gl.set_save_manager(self._save_manager)
        self._game_loop = gl
        return gl

    def load_game(self, label: str) -> GameLoop:
        data = self._save_manager.load(label)
        gl = GameLoop.from_save_dict(data, self._api_client)
        gl.set_save_manager(self._save_manager)
        self._game_loop = gl
        return gl

    # ── State ──

    @property
    def game_loop(self) -> GameLoop | None:
        return self._game_loop
