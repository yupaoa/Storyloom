/* ═══════════════════════════════════════════════════════════════════
   router.js — Hash-based SPA router + view renderers

   Views:
     #menu       — main menu (new game / continue / speed preset)
     #co-create  — co-creation Q&A view
     #game/{id}  — game play view with SSE loop + paced display
     #saves      — save browse / load / delete

   Display pacing (matches dev_cli DisplayController):
     Modes: fast (300ms) / normal (800ms) / slow (2s) / instant / manual
     Deque-buffered: receiver pushes segments, display drains at pace.
     All segments drained before showing choices.

   Exports (on window):
     Router.navigate(hash)  — switch view
     Router.dispatch()      — re-render current route
     startGame(result)      — create game from co-create result
                               (exposed via window.startGame for co-create view)
   ═══════════════════════════════════════════════════════════════════ */

(function () {
    const app = document.getElementById("app");

    // ── Route table ──
    // ── Bootstrap ──
    // ── View: Main Menu ──
    // ── View: Co-Create ──
    // ── View: Game ──
    //   - SSR loop via runGameLoop()
    //   - Paced display: _enqueue / _processNext / _drainAll
    //   - Choice handling: showChoices → sendChoice → resume
    //   - Error handling: showError with retry/quit callbacks
    //   - Adventure log fetch on ending
    // ── View: Save List ──
    // ── Shared: startGame(result) — exposed as window.startGame ──
    // ── Kick off ──
})();
