/* ═══════════════════════════════════════════════════════════════════
   router.js — Hash-based SPA router + view renderers
   ═══════════════════════════════════════════════════════════════════ */

(function () {
    const app = document.getElementById("app");

    // ── Route table ────────────────────────────────────────────────

    const routes = {
        "": renderMenu,
        "menu": renderMenu,
        "co-create": renderCoCreate,
        "game": renderGame,
    };

    // ── Bootstrap ──────────────────────────────────────────────────

    function init() {
        window.addEventListener("hashchange", dispatch);
        dispatch();
    }

    function dispatch() {
        const hash = location.hash.replace("#", "") || "";
        const [view] = hash.split("/");
        const render = routes[view] || routes[""];
        if (render) render();
    }

    function navigate(hash) {
        location.hash = hash;
    }

    // Expose for other modules
    window.Router = { navigate, dispatch };

    // ── View: Main Menu ────────────────────────────────────────────

    function renderMenu() {
        GameState.reset();
        SSEClient.close();

        app.innerHTML = `
            <div class="menu-view">
                <h1>Storyloom</h1>
                <p class="text-muted">AI 文字冒险</p>

                <div class="menu-buttons">
                    <button class="accent" onclick="Router.navigate('co-create')">
                        [1] ${t("new_game")}
                    </button>
                    <button onclick="Router.navigate('game')" id="btn-continue">
                        [2] ${t("continue")}
                    </button>
                </div>

                <div class="panel" style="margin-top: 2rem; display: inline-block; text-align: left;">
                    <label class="text-muted">${t("display_speed")}:</label>
                    <select id="speed-preset">
                        <option value="fast">${t("speed_fast")} (0.3s)</option>
                        <option value="normal" selected>${t("speed_normal")} (0.8s)</option>
                        <option value="slow">${t("speed_slow")} (2s)</option>
                        <option value="instant">${t("speed_instant")}</option>
                        <option value="manual">${t("speed_manual")}</option>
                    </select>
                </div>

                <div style="margin-top: 2rem;">
                    <button class="danger" id="btn-exit">${t("exit")}</button>
                </div>
            </div>
        `;

        // Speed preset
        const sel = document.getElementById("speed-preset");
        if (sel) {
            sel.value = GameState.speedPreset || "normal";
            sel.addEventListener("change", () => {
                GameState.speedPreset = sel.value;
            });
        }

        // Exit button
        document.getElementById("btn-exit")?.addEventListener("click", () => {
            if (confirm(t("exit") + "?")) window.close();
        });
    }

    // ── View: Co-Create ────────────────────────────────────────────

    async function renderCoCreate() {
        app.innerHTML = `
            <div class="cocreate-view">
                <h2>📝 Co-Create</h2>
                <div id="cocreate-chat" class="panel chat-area"></div>
                <div class="input-row">
                    <input type="text" id="cocreate-input" placeholder="${t("your_answer")}" autofocus>
                    <button id="btn-send">${t("send")}</button>
                    <button id="btn-generate" class="accent">${t("generate")}</button>
                    <button id="btn-quit" class="danger">${t("quit")}</button>
                </div>
            </div>
        `;

        const chat = document.getElementById("cocreate-chat");
        const input = document.getElementById("cocreate-input");
        let sessionId = null;

        // Step 1: Start co-creation
        appendMessage("system", t("loading"));
        try {
            const res = await API.post("/api/co-create/start");
            sessionId = res.session_id;
            chat.innerHTML = "";
            appendMessage("system", res.prompt);
        } catch (err) {
            appendMessage("error", `Failed to start: ${err.message}`);
            return;
        }

        // Send handler
        async function doSend() {
            const msg = input.value.trim();
            if (!msg) return;

            appendMessage("user", msg);
            input.value = "";
            document.getElementById("btn-send").disabled = true;
            document.getElementById("btn-generate").disabled = true;
            appendMessage("system", t("waiting_llm"));

            try {
                const res = await API.post("/api/co-create/send", {
                    session_id: sessionId,
                    message: msg,
                });
                // Remove "waiting" message
                chat.lastChild?.remove();
                appendMessage("assistant", res.reply);
            } catch (err) {
                chat.lastChild?.remove();
                appendMessage("error", err.message);
            } finally {
                document.getElementById("btn-send").disabled = false;
                document.getElementById("btn-generate").disabled = false;
                input.focus();
            }
        }

        // Generate handler
        async function doGenerate() {
            appendMessage("system", t("generating_story"));
            document.getElementById("btn-send").disabled = true;
            document.getElementById("btn-generate").disabled = true;
            document.getElementById("btn-quit").disabled = true;

            try {
                const res = await API.post("/api/co-create/generate", {
                    session_id: sessionId,
                });
                chat.lastChild?.remove();

                // Build a transition panel
                const panel = document.createElement("div");
                panel.className = "panel";
                panel.style.marginTop = "1rem";
                const label = res.story_config.label || "???";
                const genre = res.story_config.genre || "???";
                const tier = res.story_config.tier || "medium";
                const nodeCount = res.outline_nodes.length;
                panel.innerHTML = `
                    <h3>✅ ${t("story_generated")}</h3>
                    <p><strong>${Display._esc(label)}</strong> — ${Display._esc(genre)} (${tier})</p>
                    <p class="text-muted">${t("outline")}: ${nodeCount} ${t("nodes")}</p>
                    <button id="btn-start-game" class="accent" style="font-size:1.1rem;margin-top:0.8rem;">
                        ▶ ${t("start_adventure")}
                    </button>
                `;
                chat.appendChild(panel);
                chat.scrollTop = chat.scrollHeight;

                // Store result
                sessionStorage.setItem("cocreate-result", JSON.stringify(res));

                // Start-game handler
                document.getElementById("btn-start-game").addEventListener("click", async () => {
                    // Show loading state immediately
                    document.getElementById("btn-start-game").disabled = true;
                    document.getElementById("btn-start-game").textContent = t("loading");
                    // Navigate to game view (will show placeholder while API works)
                    await startGame(res);
                });
            } catch (err) {
                chat.lastChild?.remove();
                appendMessage("error", err.message);
            } finally {
                document.getElementById("btn-send").disabled = false;
                document.getElementById("btn-generate").disabled = false;
                document.getElementById("btn-quit").disabled = false;
            }
        }

        // Event bindings
        document.getElementById("btn-send").addEventListener("click", doSend);
        document.getElementById("btn-generate").addEventListener("click", doGenerate);
        document.getElementById("btn-quit").addEventListener("click", async () => {
            if (sessionId) {
                await API.post("/api/co-create/abort", { session_id: sessionId });
            }
            navigate("menu");
        });
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter") doSend();
        });

        function appendMessage(role, text) {
            const div = document.createElement("div");
            div.className = `chat-msg chat-${role}`;
            div.textContent = text;
            chat.appendChild(div);
            chat.scrollTop = chat.scrollHeight;
        }
    }

    // ── Game creation (shared by co-create → start and saves → load) ──

    async function startGame(result) {
        try {
            const res = await API.post("/api/game/new", {
                story_config: result.story_config,
                outline_text: result.outline_text,
                outline_nodes: result.outline_nodes,
            });
            GameState.gameId = res.game_id;
            GameState.roundCount = res.round_count;
            GameState.currentNode = res.current_node;
            navigate(`game/${res.game_id}`);
        } catch (err) {
            alert(`Failed to start game: ${err.message}`);
        }
    }

    window.startGame = startGame; // expose for load-game flow

    // ── View: Game ──────────────────────────────────────────────────

    function renderGame() {
        const gameId = GameState.gameId;
        if (!gameId) {
            // No active game — show save list or prompt
            renderSaveList();
            return;
        }

        app.innerHTML = `
            <div class="game-view">
                <div class="game-toolbar">
                    <span class="text-muted">Round <span id="round-num">0</span></span>
                    <span class="toolbar-spacer">|</span>
                    <span class="text-accent">${t("speed_" + (GameState.speedPreset || "normal"))}</span>
                </div>
                <div class="game-body">
                <div class="game-main">
                    <div id="story-area" class="panel story-area">
                        <p class="text-muted story-placeholder">⏳ ${t("waiting_llm")}</p>
                    </div>
                    <div id="choice-panel" class="choice-panel hidden"></div>
                </div>
                <div class="game-sidebar">
                    <div class="panel">
                        <h3>📊 State</h3>
                        <div id="state-vars"></div>
                    </div>
                    <div class="panel">
                        <h3>🗺️ Outline</h3>
                        <div id="outline-list"></div>
                    </div>
                    <div class="panel">
                        <button id="btn-save">${t("save")}</button>
                        <button id="btn-menu" class="danger" style="margin-top:0.5rem;">${t("back_to_menu")}</button>
                    </div>
                </div>
                </div><!-- .game-body -->
            </div>
        `;

        fetchGameState(gameId);

        // Apply speed preset (set in menu, fixed during game)
        _applySpeedPreset();

        // Save button
        document.getElementById("btn-save")?.addEventListener("click", async () => {
            try {
                const res = await API.post(`/api/game/${gameId}/save`);
                alert(`Saved: ${res.label} (round ${res.round_count})`);
            } catch (err) {
                alert(`Save failed: ${err.message}`);
            }
        });

        // Back to menu
        document.getElementById("btn-menu")?.addEventListener("click", () => {
            SSEClient.close();
            GameState.reset();
            navigate("menu");
        });

        // Start SSE
        runGameLoop(gameId).catch(err => {
            Display.appendSegment(`[Error: ${err.message}]`);
        });
    }

    async function fetchGameState(gameId) {
        try {
            const state = await API.get(`/api/game/${gameId}/state`);
            Display.updateStatePanel(state.state_vars, []);
            Display.updateOutline(state.outline_nodes);
        } catch (err) {
            console.error("fetchGameState:", err);
        }
    }

    // ═══════════════════════════════════════════════════════════════
    // Paced display — simple setTimeout chain, hot-switchable
    // ═══════════════════════════════════════════════════════════════

    let _segQueue = [];       // pending segment texts
    let _segTimer = null;     // setTimeout handle
    // Speed preset — set once from menu, read-only during game
    let _segDelay = 800;       // ms between segments
    let _segManual = false;    // manual mode
    let _manualWaiting = false;
    let _firstSeg = true;

    function _applySpeedPreset() {
        const preset = GameState.speedPreset || "normal";
        switch (preset) {
            case "fast":    _segDelay = 300;  _segManual = false; break;
            case "normal":  _segDelay = 800;  _segManual = false; break;
            case "slow":    _segDelay = 2000; _segManual = false; break;
            case "instant": _segDelay = 0;    _segManual = false; break;
            case "manual":  _segDelay = 800;  _segManual = true;  break;
            default:        _segDelay = 800;  _segManual = false;
        }
    }

    function _enqueue(text) {
        if (_firstSeg) {
            _firstSeg = false;
            const ph = document.querySelector(".story-placeholder");
            if (ph) ph.remove();
            const li = document.querySelector(".loading-indicator");
            if (li) li.remove();
        }
        _segQueue.push(text);
        if (_segTimer === null && !_manualWaiting) {
            // Auto/instant: start the display chain.
            // Manual: only auto-start if not already waiting for a click.
            _processNext();
        }
    }

    function _processNext() {
        if (_segQueue.length === 0) { _segTimer = null; _manualWaiting = false; return; }
        const text = _segQueue.shift();
        Display.appendSegment(text);
        console.log("[pace] shown segment,", _segQueue.length, "left, mode:",
                     _segManual ? "manual" : (_segDelay === 0 ? "instant" : `auto-${_segDelay}ms`));

        if (_segManual) {
            _segTimer = null;
            _manualWaiting = true;
            _showContinueBtn();
        } else if (_segDelay === 0) {
            while (_segQueue.length > 0) {
                Display.appendSegment(_segQueue.shift());
            }
            _segTimer = null;
            _manualWaiting = false;
        } else {
            _segTimer = setTimeout(_processNext, _segDelay);
            _manualWaiting = false;
        }
    }

    function _drainAll() {
        if (_segTimer) { clearTimeout(_segTimer); _segTimer = null; }
        _manualWaiting = false;
        while (_segQueue.length > 0) {
            Display.appendSegment(_segQueue.shift());
        }
        const cb = document.querySelector(".manual-continue");
        if (cb) cb.remove();
    }

    function _showContinueBtn() {
        const area = document.getElementById("story-area");
        if (!area) return;
        const old = area.querySelector(".manual-continue");
        if (old) old.remove();
        const btn = document.createElement("button");
        btn.className = "manual-continue";
        btn.textContent = "▶ 继续";
        btn.addEventListener("click", () => {
            btn.remove();
            _manualWaiting = false;
            _processNext();
        });
        area.appendChild(btn);
    }

    // ═══════════════════════════════════════════════════════════════

    async function runGameLoop(gameId) {
        _firstSeg = true;
        _segQueue = [];
        if (_segTimer) { clearTimeout(_segTimer); _segTimer = null; }
        _manualWaiting = false;
        Display.clearChoices();

        await SSEClient.connect(gameId, {

            token(_data) { /* silent */ },

            segment(data) {
                _enqueue(data.text);
            },

            options(data) {
                console.log("[game] options:", data.choices);
                _drainAll();
                Display.showChoices(data.choices || []).then(async (key) => {
                    if (key === "q") {
                        // Player pressed Q — quit to menu
                        console.log("[game] player quit via Q");
                        SSEClient.close();
                        GameState.reset();
                        Display.clearChoices();
                        Router.navigate("menu");
                        return;
                    }
                    console.log("[game] choice:", key);
                    await SSEClient.sendChoice(GameState.gameId, key);
                    Display.clearChoices();
                });
            },

            state(data) {
                Display.updateStatePanel(data.vars || {}, data.changes || []);
            },

            ending(_data) {
                fetchAdventureLog(GameState.gameId);
            },

            done(data) {
                GameState.roundCount = data.round;
                GameState.currentNode = data.node;
                const rn = document.getElementById("round-num");
                if (rn) rn.textContent = data.round;
                fetchGameState(GameState.gameId);

                SSEClient.close();
                if (!GameState.endingFlag) {
                    runGameLoop(GameState.gameId);
                } else {
                    fetchAdventureLog(GameState.gameId);
                }
            },

            error(data) {
                console.error("[game] error:", data.message);
                Display.showError(
                    data.message || "Unknown error",
                    async () => {
                        await API.post(`/api/game/${GameState.gameId}/retry`);
                        SSEClient.close();
                        runGameLoop(GameState.gameId);
                    },
                    () => { SSEClient.close(); GameState.reset(); Router.navigate("menu"); }
                );
            },

            round_complete() { /* silent */ },
        });
    }

    async function fetchAdventureLog(gameId) {
        try {
            const res = await API.get(`/api/game/${gameId}/adventure-log`);
            if (res.text) {
                Display.showAdventureLog(res.text);
                const area = document.getElementById("story-area");
                if (area) {
                    const btn = document.createElement("button");
                    btn.textContent = t("back_to_menu");
                    btn.addEventListener("click", () => {
                        SSEClient.close();
                        GameState.reset();
                        Router.navigate("menu");
                    });
                    area.appendChild(btn);
                }
            }
            if (res.pending) {
                // Still generating — show placeholder
                Display.appendSegment("[Adventure log still generating...]");
            }
        } catch (err) {
            console.error("fetchAdventureLog:", err);
        }
    }

    // ── View: Save List (Continue / Manage) ────────────────────────

    async function renderSaveList() {
        app.innerHTML = `
            <div class="menu-view">
                <h1>📂 ${t("continue")}</h1>
                <div id="save-list"></div>
                <button id="btn-back" style="margin-top: 1rem;">← ${t("back_to_menu")}</button>
            </div>
        `;

        document.getElementById("btn-back").addEventListener("click", () => navigate("menu"));

        const list = document.getElementById("save-list");
        try {
            const saves = await API.get("/api/saves");
            if (!saves || saves.length === 0) {
                list.innerHTML = `<p class="text-muted">${t("no_saves")}</p>`;
                return;
            }

            let html = "";
            for (const s of saves) {
                html += `
                    <div class="panel save-item">
                        <strong>${Display._esc(s.label)}</strong>
                        <span class="text-muted"> — round ${s.round_count} — ${s.updated_at || ""}</span>
                        <div class="btn-row" style="margin-top:0.5rem;">
                            <button class="load-btn" data-label="${Display._esc(s.label)}">${t("load")}</button>
                            <button class="danger delete-btn" data-label="${Display._esc(s.label)}">${t("delete")}</button>
                        </div>
                    </div>`;
            }
            list.innerHTML = html;

            // Load handlers
            list.querySelectorAll(".load-btn").forEach(btn => {
                btn.addEventListener("click", async () => {
                    const label = btn.dataset.label;
                    try {
                        const res = await API.post(`/api/saves/${encodeURIComponent(label)}/load`);
                        GameState.gameId = res.game_id;
                        GameState.roundCount = res.round_count;
                        GameState.currentNode = res.current_node;
                        navigate(`game/${res.game_id}`);
                    } catch (err) {
                        alert(`Load failed: ${err.message}`);
                    }
                });
            });

            // Delete handlers
            list.querySelectorAll(".delete-btn").forEach(btn => {
                btn.addEventListener("click", async () => {
                    const label = btn.dataset.label;
                    if (!confirm(`${t("delete")} "${label}"?`)) return;
                    try {
                        await API.del(`/api/saves/${encodeURIComponent(label)}`);
                        renderSaveList(); // refresh
                    } catch (err) {
                        alert(`Delete failed: ${err.message}`);
                    }
                });
            });
        } catch (err) {
            list.innerHTML = `<p class="text-error">${Display._esc(err.message)}</p>`;
        }
    }

    // ── Kick off ───────────────────────────────────────────────────

    init();
})();
