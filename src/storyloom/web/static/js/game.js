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
    let _speed = 1;             // 1 | 2 | 4  (1x = 2.0s per segment)
    let _fontSize = "medium";   // "small" | "medium" | "large"
    let _lineSpacing = 1.0;     // 0.75 | 1.0 | 1.25

    /* Speed → delay mapping (1x = 2.0s base) */
    const SPEED_DELAY = { 1: 2000, 2: 1000, 4: 500 };

    /* Queue buffer for paced display (exec-flow.md §4.5) */
    let _eventQueue = [];
    let _drainTimer = null;
    let _advanceResolve = null;  // resolve when user clicks/keypresses in manual mode
    let _pendingPoll = false;    // true when display loop is waiting for queue data
                                 // (empty queue → 150ms poll).  SSE receiver
                                 // calls _wakeDisplay() to break the poll early.

    /* SSE event handlers — bound once per render */
    let _handlers = null;

    /* Ending flag — set when ending event received */
    let _ending = false;
    /* Track whether we've shown the end modal to avoid double-show */
    let _endModalShown = false;

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
        _endModalShown = false;

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
                            title="${_("Quit")}">←</button>
                    <span class="game-label" id="game-label"></span>
                    <div class="game-topright">
                        <button class="game-mode-btn" id="game-mode-btn"
                                title="${_("Toggle Mode")}">
                            ${_modeSVG("manual")}
                        </button>
                        <button class="game-settings-btn" id="game-settings-btn"
                                title="${_("Settings")}">
                            ${_gearSVG()}
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
                /* Only advance if user clicked the story area itself
                   (not a child element like the continue hint) */
                _advanceManual();
            });
        }
        document.addEventListener("keydown", (e) => {
            if (e.key === " " || e.key === "Enter") {
                /* Don't trigger if user is typing in an input */
                if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
                e.preventDefault();
                _advanceManual();
            }
        });
    }

    /* ═══════════════════════════════════════════════════════════════
       SSE Connection & Event Loop
       ═══════════════════════════════════════════════════════════════ */

    function _connectSSE() {
        _handlers = {
            story_begin: () => { /* silent */ },
            story_end: () => { /* silent */ },
            token: () => { /* silent — reserved for typewriter effect */ },
            segment: (data) => {
                /* ── Receiver: push then wake display if polling ── */
                _eventQueue.push({ type: "segment", text: data.text });
                _wakeDisplay();
            },
            bridge: () => {
                _eventQueue.push({ type: "bridge" });
                _wakeDisplay();
            },
            options: (data) => {
                /* ── Inline: flush queue then handle options ── */
                _flushQueue();
                _handleOptions(data);
            },
            state: (data) => {
                if (data.vars) GameState.stateVars = data.vars;
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

        SSEClient.connect(_gameId, _handlers).then(() => {
            _stopDisplayLoop();
            if (_ending && !_endModalShown) {
                _showEndModal();
            }
        }).catch(() => {
            _stopDisplayLoop();
        });
    }

    /* ═══════════════════════════════════════════════════════════════
       Queue Buffer & Paced Display (exec-flow.md §4.5)
       ═══════════════════════════════════════════════════════════════ */

    /* ── Independent display loop ──────────────────────────────────
       Receiver (SSE) pushes to _eventQueue only — never triggers display.
       Display loop runs on setTimeout, polls queue, paces output.
       Queue empty → show loading indicator; queue has data → pop one, display, wait. */

    let _displayRunning = false;

    function _startDisplayLoop() {
        if (_displayRunning) return;
        _displayRunning = true;
        _displayTick();
    }

    function _stopDisplayLoop() {
        _displayRunning = false;
        _pendingPoll = false;
        Display.hideLoading();
        Display.hideContinueHint();
        if (_advanceResolve) { _advanceResolve(); _advanceResolve = null; }
        if (_drainTimer) { clearTimeout(_drainTimer); _drainTimer = null; }
    }

    function _displayTick() {
        if (!_displayRunning) return;

        if (_eventQueue.length === 0) {
            Display.showLoading();
            _pendingPoll = true;
            _drainTimer = setTimeout(_displayTick, 150);
            return;
        }

        _pendingPoll = false;
        Display.hideLoading();
        const event = _eventQueue.shift();

        if (event.type === "segment") {
            Display.appendSegment(event.text);
        }

        if (_mode === "auto") {
            _drainTimer = setTimeout(_displayTick, SPEED_DELAY[_speed] || 2000);
        } else {
            /* Manual: wait for user click / Space / Enter */
            Display.showContinueHint();
            _drainTimer = setTimeout(() => {
                _waitForUserAdvance().then(() => {
                    if (!_displayRunning) return;
                    Display.hideContinueHint();
                    _displayTick();
                });
            }, 0);
        }
    }

    function _waitForUserAdvance() {
        return new Promise((resolve) => { _advanceResolve = resolve; });
    }

    function _advanceManual() {
        if (_advanceResolve) { _advanceResolve(); _advanceResolve = null; }
    }

    /** Wake the display loop when new data arrives while polling.
     *  Called by SSE receiver handlers after pushing to _eventQueue.
     *  Only interrupts a pending poll — does not disturb auto-mode
     *  pacing or manual-mode waits. */
    function _wakeDisplay() {
        if (_pendingPoll && _displayRunning) {
            _pendingPoll = false;
            if (_drainTimer) { clearTimeout(_drainTimer); _drainTimer = null; }
            _displayTick();
        }
    }

    function _flushQueue() {
        Display.hideLoading();
        Display.hideContinueHint();
        if (_advanceResolve) { _advanceResolve(); _advanceResolve = null; }
        while (_eventQueue.length > 0) {
            const event = _eventQueue.shift();
            if (event.type === "segment") Display.appendSegment(event.text);
        }
    }

    /* ═══════════════════════════════════════════════════════════════
       Options Handling (exec-flow.md §4.6)
       ═══════════════════════════════════════════════════════════════ */

    async function _handleOptions(data) {
        const choices = data.choices || [];

        /* Show choice buttons and wait for selection */
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

            /* More SSE events will arrive via the same connection.
               Show loading indicator for post-choice content. */
            Display.showLoading();
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

    /** User clicked exit button — show confirmation modal. */
    function _handleExit() {
        Display.showEndModal(
            _("Generate adventure log?"),
            /* Primary: view adventure log (stub — disabled below) */
            () => {
                /* TODO: navigate to adventure log view when implemented */
            },
            /* Secondary: quit */
            () => {
                SSEClient.close();
                Router.navigate("menu");
            },
            _("View Log"),
            _("Quit")
        );

        /* Disable the primary button (adventure log view not yet implemented) */
        const primaryBtn = document.getElementById("game-modal-primary");
        if (primaryBtn) {
            primaryBtn.disabled = true;
            primaryBtn.style.opacity = "0.4";
            primaryBtn.style.cursor = "not-allowed";
        }
    }

    /** Natural ending or stream end — show end modal. */
    function _showEndModal() {
        if (_endModalShown) return;
        _endModalShown = true;

        Display.showEndModal(
            _("Story has ended. Generate adventure log?"),
            /* Primary: view adventure log (stub — disabled below) */
            () => {
                /* TODO: navigate to adventure log view when implemented */
            },
            /* Secondary: quit */
            () => {
                SSEClient.close();
                Router.navigate("menu");
            },
            _("View Log"),
            _("Quit")
        );

        /* Disable the primary button (adventure log view not yet implemented) */
        const primaryBtn = document.getElementById("game-modal-primary");
        if (primaryBtn) {
            primaryBtn.disabled = true;
            primaryBtn.style.opacity = "0.4";
            primaryBtn.style.cursor = "not-allowed";
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
                Router.navigate("menu");
            }
        );
    }

    /* ═══════════════════════════════════════════════════════════════
       Mode Toggle (manual ↔ auto)
       ═══════════════════════════════════════════════════════════════ */

    function _toggleMode() {
        _mode = (_mode === "manual") ? "auto" : "manual";
        _updateModeButton();

        /* Release any pending manual-mode wait and re-tick immediately */
        if (_advanceResolve) {
            _advanceResolve();
            _advanceResolve = null;
        }
        if (_drainTimer) {
            clearTimeout(_drainTimer);
            _drainTimer = null;
        }
        Display.hideContinueHint();
        if (_displayRunning) _displayTick();
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

    /** Gear icon for settings button. */
    function _gearSVG() {
        return `<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M12 15.5A3.5 3.5 0 0 1 8.5 12 3.5 3.5 0 0 1 12 8.5a3.5 3.5 0 0 1 3.5 3.5 3.5 3.5 0 0 1-3.5 3.5m7.43-2.53c.04-.32.07-.64.07-.97 0-.33-.03-.66-.07-1l2.11-1.63c.19-.15.24-.42.12-.64l-2-3.46c-.12-.22-.39-.31-.61-.22l-2.49 1c-.52-.39-1.06-.73-1.69-.98l-.37-2.65A.506.506 0 0 0 14 2h-4c-.25 0-.46.18-.5.42l-.37 2.65c-.63.25-1.17.59-1.69.98l-2.49-1c-.22-.09-.49 0-.61.22l-2 3.46c-.13.22-.07.49.12.64L4.57 11c-.04.34-.07.67-.07 1 0 .33.03.65.07.97l-2.11 1.66c-.19.15-.25.42-.12.64l2 3.46c.12.22.39.3.61.22l2.49-1.01c.52.4 1.06.74 1.69.99l.37 2.65c.04.24.25.42.5.42h4c.25 0 .46-.18.5-.42l.37-2.65c.63-.26 1.17-.59 1.69-.99l2.49 1.01c.22.08.49 0 .61-.22l2-3.46c.12-.22.07-.49-.12-.64l-2.11-1.66Z"/></svg>`;
    }

    /* ── Export ──────────────────────────────────────────────────── */
    return { render };
})();
