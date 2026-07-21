/* ═══════════════════════════════════════════════════════════════════
   game.js — Game Narrative View Controller

   Manages the full game lifecycle:
     1. render(container, gameId, label) — build DOM, start game, connect SSE
     2. SSE event → deque buffer → paced display (manual / auto)
     3. Options → show buttons → sendChoice → resume
     4. Mode toggle (manual ↔ auto), speed, font size, line spacing
     5. Error modal (retry / exit), End modal (view log / exit)

   Default: manual mode, 1x speed (2.0s/segment), medium font, 1.0 line spacing.

   Authority:
     exec-flow.md §4.1 (event types), §4.5 (display pacing, queue buffer)
     exec-flow.md §4.6 (options gen.send pattern), §4.1.1 (error severity)
     exec-flow.md §5.3 (active exit flow)
     dev_cli/game_driver.py (event consumption reference)
     CLAUDE.local.md §3.2 (event flow consumption)
   ═══════════════════════════════════════════════════════════════════ */

const GameView = (function () {
    /* ── Internal state ──────────────────────────────────────────── */
    let _container = null;
    let _gameId = null;
    let _label = "";

    /* Display settings (defaults per user spec) */
    let _mode = "manual";       // "manual" | "auto"
    let _speed = 1;             // 0.75 | 1 | 2 | 3  (1x = 2.0s per segment)
    let _fontSize = "medium";   // "small" | "medium" | "large"
    let _lineSpacing = 1.0;     // 0.75 | 1.0 | 1.25

    /* Speed → delay mapping (1x = 2.0s base) */
    const SPEED_DELAY = { 0.75: 2667, 1: 2000, 2: 1000, 3: 667 };
    const ADVANCE_DEBOUNCE_MS = 200;  // minimum ms between manual advances

    /* Queue buffer for paced display (exec-flow.md §4.5).
       Receiver (SSE handlers) pushes; display loop (_displayTick)
       drains one event per tick at the user's chosen pace.  When
       options arrive (_optionsPending set), the display loop shows
       choices naturally when the queue empties — no acceleration,
       no synchronous flush. */
    let _eventQueue = [];
    let _drainTimer = null;
    let _advanceResolve = null;  // resolve when user clicks / Space / Enter
    let _lastAdvanceTime = 0;    // debounce OS key repeat (ms timestamp)
    let _keydownHandler = null;  // named ref for cleanup
    let _loadingTimer = null;    // delayed loading indicator (500 ms debounce)
    let _optionsPending = null;  // options event data awaiting display

    /* Ending flag — set when ending event received */
    let _ending = false;
    /* Track whether we've shown the end choice to avoid double-show */
    let _endChoiceShown = false;
    /* Track whether any story content has arrived (vs. loading state).
       Controls exit behavior — during loading there is no content to
       generate an adventure log from, so we skip the confirmation modal
       and exit immediately (analogous to co-create phase restrictions). */
    let _contentStarted = false;

    /* ── DOM helpers ─────────────────────────────────────────────── */
    function $(sel) { return _container ? _container.querySelector(sel) : null; }

    /* ═══════════════════════════════════════════════════════════════
       Public API
       ═══════════════════════════════════════════════════════════════ */

    /** Render the game narrative view and start the game.
     *  @param {Element} container — DOM element to render into
     *  @param {string} gameId
     *  @param {string} label — story name for the top bar */
    async function render(container, gameId, label) {
        _container = container;
        _gameId = gameId;
        _label = label;
        _ending = false;
        _endChoiceShown = false;
        _contentStarted = false;
        _eventQueue = [];
        _optionsPending = null;
        /* Ensure display loop starts fresh — previous session may have
           left _displayRunning = true if the EventSource was still
           CONNECTING when close() was called (browsers don't fire
           onerror in that state). */
        _stopDisplayLoop();

        _buildDOM();

        /* Apply saved font/line settings from localStorage or defaults */
        _loadDisplayPrefs();
        _applyDisplayClasses();

        Display.init(_container);

        /* Start Round 1 → then connect SSE */
        try {
            await API.post(`/api/game/${encodeURIComponent(gameId)}/start`);
        } catch (err) {
            _showFatalError(err.message);
            return;
        }

        _connectSSE();
    }

    /* ═══════════════════════════════════════════════════════════════
       DOM Construction
       ═══════════════════════════════════════════════════════════════ */

    function _buildDOM() {
        _container.innerHTML = `
            <div class="game-view">
                <!-- Top bar -->
                <div class="game-topbar">
                    <button class="game-exit-btn" id="game-exit"
                            title="${_("Quit")}">${Icons.arrowLeft()}</button>
                    <span class="game-label" id="game-label"></span>
                    <div class="game-topright">
                        <button class="game-mode-btn" id="game-mode-btn"
                                title="${_("Toggle Mode")}">
                            ${_modeSVG("manual")}
                        </button>
                        <button class="game-settings-btn" id="game-settings-btn"
                                title="${_("Settings")}">
                            ${Icons.gear()}
                        </button>
                    </div>
                </div>

                <!-- Story area -->
                <div class="game-story" id="game-story"></div>

                <!-- Choices panel (inserted dynamically by Display) -->
            </div>
        `;

        /* Set label */
        $("#game-label").textContent = _label;

        /* ── Event bindings ─────────────────────────────────────── */
        $("#game-exit").addEventListener("click", _handleExit);
        $("#game-mode-btn").addEventListener("click", _toggleMode);
        $("#game-settings-btn").addEventListener("click", _openSettings);

        /* Manual mode advance: click story area, Space, or Enter */
        const storyEl = $("#game-story");
        if (storyEl) {
            storyEl.addEventListener("click", (e) => {
                _advanceManual();
            });
        }
        _keydownHandler = (e) => {
            if (e.key === " " || e.key === "Enter") {
                /* Don't trigger if user is typing in an input */
                if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
                e.preventDefault();
                _advanceManual();
            }
        };
        document.addEventListener("keydown", _keydownHandler);
    }

    /* ═══════════════════════════════════════════════════════════════
       SSE Connection & Event Loop
       ═══════════════════════════════════════════════════════════════ */

    function _connectSSE() {
        const handlers = {
            story_begin: () => { /* silent */ },
            story_end: () => { /* silent */ },
            token: () => { /* silent — reserved for typewriter effect */ },
            segment: (data) => {
                _contentStarted = true;
                _eventQueue.push({ type: "segment", text: data.text });
                _wakeDisplay();
            },
            bridge: () => {
                _eventQueue.push({ type: "bridge" });
                _wakeDisplay();
            },
            options: (data) => {
                /* Defer to display loop — when the queue is naturally
                   empty (all pre-choice segments displayed at normal
                   pace), _displayTick will show the choices. */
                _optionsPending = data;
                _wakeDisplay();
            },
            state: (data) => {
                if (data.vars) GameState.stateVars = data.vars;
            },
            save: () => {
                showToast(_("Saved"));
            },
            error: (data) => {
                _stopDisplayLoop();
                _handleError(data);
            },
            ending: () => {
                _ending = true;
            },
            done: (data) => {
                if (data.node) GameState.currentNode = data.node;
                if (data.state) GameState.stateVars = data.state;
                GameState.roundCount = (GameState.roundCount || 0) + 1;
            },
        };

        /* ── Start the independent display loop ── */
        _startDisplayLoop();

        SSEClient.connect(_gameId, handlers).then(() => {
            /* Stream ended — wake the display loop so it drains any
               remaining bridge_text segments.  When the queue is
               empty and _ending is true, _displayTick will show the
               end modal naturally (exec-flow.md §5.2 step 4-5). */
            _wakeDisplay();
        }).catch(() => {
            _stopDisplayLoop();
        });
    }

    /* ═══════════════════════════════════════════════════════════════
       Queue Buffer & Paced Display (exec-flow.md §4.5)

       Architecture (mirrors dev_cli game_driver.py run_game):
         Receiver (SSE handlers) pushes to _eventQueue.
         Display loop (_displayTick) is the SOLE consumer — it drains
         one event per tick, paces by mode, and handles options
         when the queue is naturally empty (no synchronous flush).

       Loading indicator is debounced 500 ms — prevents flicker
       during normal pacing gaps while still showing for TTFT /
       inter-round waits (the only genuinely empty-queue states).
       ═══════════════════════════════════════════════════════════════ */

    let _displayRunning = false;
    let _isPolling = false;   // true only during empty-queue 150 ms poll
                               // (not during pacing delays or manual waits)

    function _startDisplayLoop() {
        if (_displayRunning) return;
        _displayRunning = true;
        _displayTick();
    }

    function _stopDisplayLoop() {
        _displayRunning = false;
        _isPolling = false;
        _lastAdvanceTime = 0;
        _cancelLoading();
        if (_advanceResolve) { _advanceResolve(); _advanceResolve = null; }
        if (_drainTimer) { clearTimeout(_drainTimer); _drainTimer = null; }
        if (_keydownHandler) {
            document.removeEventListener("keydown", _keydownHandler);
            _keydownHandler = null;
        }
    }

    function _displayTick() {
        if (!_displayRunning) return;

        /* ── Queue empty ────────────────────────────────────────── */
        if (_eventQueue.length === 0) {
            /* Options pending + queue drained → show choices now. */
            if (_optionsPending) {
                const data = _optionsPending;
                _optionsPending = null;
                _cancelLoading();
                Display.hideLoading();
                _handleOptions(data);
                return;
            }
            /* Ending: all bridge_text displayed, show end choice
               (exec-flow.md §5.2 step 4-5: bridge_text must finish
               before adventure log prompt). */
            if (_ending && !_endChoiceShown) {
                _showEndChoice();
                return;
            }
            /* Debounced loading — only show after 500 ms of genuine
               wait (TTFT / inter-round), not pacing gaps. */
            if (!_loadingTimer) {
                _loadingTimer = setTimeout(() => {
                    if (_displayRunning && _eventQueue.length === 0) {
                        Display.showLoading();
                    }
                }, 500);
            }
            _isPolling = true;
            _drainTimer = setTimeout(_displayTick, 150);
            return;
        }

        /* ── Queue has data ─────────────────────────────────────── */
        _isPolling = false;
        _cancelLoading();
        Display.hideLoading();
        const event = _eventQueue.shift();

        if (event.type === "segment") {
            Display.appendSegment(event.text);
        }

        /* ── Pacing (after segment display, per dev_cli pattern) ─── */
        if (_mode === "auto") {
            _drainTimer = setTimeout(_displayTick, SPEED_DELAY[_speed] || 2000);
        } else {
            /* Manual mode — wait for click / Space / Enter.
               _optionsPending does NOT override this: the user chose
               manual pacing and each segment must be confirmed. */
            _waitForUserAdvance().then(() => {
                if (!_displayRunning) return;
                _displayTick();
            });
        }
    }

    function _waitForUserAdvance() {
        return new Promise((resolve) => { _advanceResolve = resolve; });
    }

    function _advanceManual() {
        if (_mode !== "manual") return;
        if (!_advanceResolve) return;
        const now = Date.now();
        if (now - _lastAdvanceTime < ADVANCE_DEBOUNCE_MS) return;
        _lastAdvanceTime = now;
        _advanceResolve();
        _advanceResolve = null;
    }

    /** Wake the display loop when SSE delivers new data.
     *  Only interrupts the empty-queue poll — never disturbs
     *  auto-mode pacing delays or manual-mode waits. */
    function _wakeDisplay() {
        if (!_displayRunning) return;
        if (_isPolling) {
            _isPolling = false;
            if (_drainTimer) { clearTimeout(_drainTimer); _drainTimer = null; }
            _displayTick();
        }
    }

    /** Cancel the debounced loading timer without showing loading. */
    function _cancelLoading() {
        if (_loadingTimer) { clearTimeout(_loadingTimer); _loadingTimer = null; }
    }

    /* ═══════════════════════════════════════════════════════════════
       Options Handling (exec-flow.md §4.6)
       ═══════════════════════════════════════════════════════════════ */

    async function _handleOptions(data) {
        const choices = data.choices || [];

        /* Show choice buttons and wait for selection.
           The display loop has stopped (returned from _displayTick's
           _optionsPending branch).  We restart it after the choice
           is sent so post-choice content is displayed. */
        Display.showChoices(choices).then(async (key) => {
            /* Find the selected option label for green display */
            const flat = Display.flattenChoices(choices);
            const selected = flat.find(o => o.key === key);
            if (selected) {
                Display.appendChoiceText(selected.label);
            }

            /* Clear choice buttons */
            Display.clearChoices();

            /* Send choice to server (this unblocks the background thread) */
            try {
                await SSEClient.sendChoice(_gameId, key);
            } catch (err) {
                Display.showErrorModal(
                    _("Choice send failed: ") + err.message,
                    () => _handleOptions(data),  /* retry same options */
                    () => Router.navigate("menu")
                );
                return;
            }

            /* Restart the display loop with pacing — the green choice
               text already provides a visual beat, so the first
               post-choice segment must also respect the current mode
               (auto: speed-based delay, manual: wait for advance).
               Otherwise it appears instantly and looks like a duplicate
               of the choice text. */
            if (_mode === "auto") {
                _drainTimer = setTimeout(
                    _displayTick, SPEED_DELAY[_speed] || 2000
                );
            } else {
                _waitForUserAdvance().then(() => {
                    if (!_displayRunning) return;
                    _displayTick();
                });
            }
        });
    }

    /* ═══════════════════════════════════════════════════════════════
       Error Handling (exec-flow.md §4.1.1 — severe errors only)
       ═══════════════════════════════════════════════════════════════ */

    function _handleError(data) {
        const message = data.message || _("Unknown error");

        Display.showErrorModal(
            message,
            /* Retry */
            async () => {
                Display.showLoading();
                try {
                    await SSEClient.retry(_gameId);
                } catch (err) {
                    Display.showErrorModal(
                        _("Retry failed: ") + err.message,
                        () => _handleError(data),
                        () => Router.navigate("menu")
                    );
                    return;
                }
                /* Reconnect SSE */
                _connectSSE();
            },
            /* Exit */
            () => {
                Router.navigate("menu");
            }
        );
    }

    /* ═══════════════════════════════════════════════════════════════
       Exit & End Modals (exec-flow.md §5.3)
       ═══════════════════════════════════════════════════════════════ */

    /** User clicked exit button — show confirmation modal if content
     *  has started, or exit immediately if still loading.
     *
     *  During loading (before the first segment arrives) there is no
     *  story content yet, so exit immediately without confirmation.
     *
     *  Per exec-flow.md §5.3 (2026-07-20): active exit → confirm →
     *  return to menu.  No adventure log — that only applies to
     *  natural endings (§5.2).  The save is retained; the player can
     *  "Continue" to resume from the last checkpoint. */
    function _handleExit() {
        if (!_contentStarted) {
            // Loading state — no content yet.  Stop and exit immediately.
            _stopDisplayLoop();
            if (_gameId) {
                API.post(`/api/game/${encodeURIComponent(_gameId)}/stop`).catch(() => {});
            }
            SSEClient.close();
            Router.navigate("menu");
            return;
        }

        Display.showEndModal(
            _("Quit the game?"),
            /* Primary: quit */
            () => {
                _stopDisplayLoop();
                if (_gameId) {
                    API.post(`/api/game/${encodeURIComponent(_gameId)}/stop`).catch(() => {});
                }
                SSEClient.close();
                Router.navigate("menu");
            },
            /* Secondary: cancel — modal auto-closes, resume game */
            () => {},
            _("Quit"),
            _("Cancel")
        );
    }

    /** Natural ending — show green inline choice option instead of modal.
     *  Per exec-flow.md §5.2: ending_flag detected → adventure log
     *  generated by engine daemon thread → UI displays log.
     *  Renders a single green-text option (same color as story label)
     *  in the same form as narrative choices.  Click navigates to
     *  #adventure-log/{gameId} which fetches from GET /api/game/{id}/adventure-log. */
    function _showEndChoice() {
        if (_endChoiceShown) return;
        _endChoiceShown = true;
        _cancelLoading();
        Display.hideLoading();

        const logHash = `adventure-log/${encodeURIComponent(_gameId)}`;

        /* Remove any existing choices panel first */
        Display.clearChoices();

        const panel = document.createElement("div");
        panel.className = "game-choices";
        panel.id = "game-choices-panel";

        const btn = document.createElement("button");
        btn.className = "game-choice-btn game-ending-choice";
        btn.textContent = _("The story has ended. View adventure log.");
        btn.addEventListener("click", () => {
            _stopDisplayLoop();
            SSEClient.close();
            Router.navigate(logHash);
        });
        panel.appendChild(btn);

        const story = document.getElementById("game-story");
        if (story) {
            story.parentNode.insertBefore(panel, story.nextSibling);
        }
    }

    function _showFatalError(message) {
        Display.showErrorModal(
            _("Game start failed: ") + message,
            /* Retry: re-render */
            () => {
                render(_container, _gameId, _label);
            },
            /* Exit */
            () => {
                // Game start failed — no running stream, but stop is
                // idempotent and safe to call for belt-and-suspenders.
                if (_gameId) {
                    API.post(`/api/game/${encodeURIComponent(_gameId)}/stop`).catch(() => {});
                }
                Router.navigate("menu");
            }
        );
    }

    /* ═══════════════════════════════════════════════════════════════
       Mode Toggle (manual ↔ auto)
       ═══════════════════════════════════════════════════════════════ */

    function _toggleMode() {
        const wasManual = _mode === "manual";
        _mode = wasManual ? "auto" : "manual";
        _updateModeButton();

        _isPolling = false;
        if (_drainTimer) { clearTimeout(_drainTimer); _drainTimer = null; }

        /* Release any pending manual-mode wait.  The .then() microtask
           will call _displayTick() — do NOT call it here, or the
           segment after the released wait AND the next segment would
           both fire in the same tick (burst). */
        const hadPending = !!_advanceResolve;
        if (_advanceResolve) {
            _advanceResolve();
            _advanceResolve = null;
        }

        if (_displayRunning && !hadPending) {
            if (wasManual) {
                /* manual→auto: start auto-paced drain */
                _displayTick();
            } else {
                /* auto→manual: enter wait without popping a segment */
                _waitForUserAdvance().then(() => {
                    if (!_displayRunning) return;
                    _displayTick();
                });
            }
        }
    }

    function _updateModeButton() {
        const btn = $("#game-mode-btn");
        if (!btn) return;

        if (_mode === "auto") {
            btn.classList.add("auto");
            btn.title = _("Switch to Manual");
        } else {
            btn.classList.remove("auto");
            btn.title = _("Switch to Auto");
        }
        btn.innerHTML = _modeSVG(_mode);
    }

    /* ═══════════════════════════════════════════════════════════════
       Settings
       ═══════════════════════════════════════════════════════════════ */

    function _openSettings() {
        Display.showSettings(
            () => _speed,
            (val) => {
                _speed = val;
                localStorage.setItem("storyloom-game-speed", val);
            },
            () => _fontSize,
            (val) => {
                _fontSize = val;
                localStorage.setItem("storyloom-game-font", val);
                _applyDisplayClasses();
            },
            () => _lineSpacing,
            (val) => {
                _lineSpacing = val;
                localStorage.setItem("storyloom-game-line", val);
                _applyDisplayClasses();
            }
        );
    }

    function _loadDisplayPrefs() {
        const savedSpeed = localStorage.getItem("storyloom-game-speed");
        if (savedSpeed) _speed = Number(savedSpeed);

        const savedFont = localStorage.getItem("storyloom-game-font");
        if (savedFont) _fontSize = savedFont;

        const savedLine = localStorage.getItem("storyloom-game-line");
        if (savedLine) _lineSpacing = Number(savedLine);
    }

    function _applyDisplayClasses() {
        const story = $("#game-story");
        if (!story) return;

        /* Font size */
        story.classList.remove("font-small", "font-medium", "font-large");
        story.classList.add(`font-${_fontSize}`);

        /* Line spacing */
        story.classList.remove("line-075", "line-100", "line-125");
        if (_lineSpacing === 0.75) story.classList.add("line-075");
        else if (_lineSpacing === 1.25) story.classList.add("line-125");
        else story.classList.add("line-100");
    }

    /* ═══════════════════════════════════════════════════════════════
       SVG Icons
       ═══════════════════════════════════════════════════════════════ */

    /** Mode toggle icon: play triangle (manual) or pause bars (auto)
     *  inside a circle.  Auto mode adds a rotating arc. */
    function _modeSVG(mode) {
        if (mode === "auto") {
            return `<svg viewBox="0 0 24 24" width="24" height="24"><circle cx="12" cy="12" r="10" class="mode-circle"/><circle cx="12" cy="12" r="10" class="mode-arc" stroke-dasharray="63" stroke-dashoffset="47" transform="rotate(-90 12 12)"/><rect x="8.5" y="8" width="2.5" height="8" rx="0.5" fill="currentColor"/><rect x="13" y="8" width="2.5" height="8" rx="0.5" fill="currentColor"/></svg>`;
        }
        return `<svg viewBox="0 0 24 24" width="24" height="24"><circle cx="12" cy="12" r="10" class="mode-circle"/><polygon points="9.5,7 9.5,17 17,12" fill="currentColor"/></svg>`;
    }

    /* ── Export ──────────────────────────────────────────────────── */
    return { render };
})();
