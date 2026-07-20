/* ═══════════════════════════════════════════════════════════════════
   router.js — Hash-based SPA router + view renderers

   Views:
     #menu       — main menu (new game / continue / load save / settings / credits / exit)
     #co-create  — co-creation Q&A view (placeholder — future task)
     #game/{id}  — game play view with SSE loop + paced display (placeholder)
     #saves      — save browse / load / delete (placeholder)

   Exports (on window):
     Router.navigate(hash)  — switch view
     Router.dispatch()      — re-render current route

   Authority:
     CLAUDE.local.md §3.2 (event flow consumption)
     exec-flow.md §4.1 (event types)
     web-reference hash routing pattern (structural reference only)
   ═══════════════════════════════════════════════════════════════════ */

(function () {
    const app = document.getElementById("app");

    /** Tiny HTML escape — inline until display.js is implemented. */
    function esc(s) {
        const d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }

    /** Trash can icon (Feather-style SVG, 16×16). */
    const TRASH_ICON = `<svg width="16" height="16" viewBox="0 0 24 24" `
        + `fill="none" stroke="currentColor" stroke-width="2" `
        + `stroke-linecap="round" stroke-linejoin="round">`
        + `<polyline points="3 6 5 6 21 6"/>`
        + `<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>`
        + `<line x1="10" y1="11" x2="10" y2="17"/>`
        + `<line x1="14" y1="11" x2="14" y2="17"/>`
        + `</svg>`;

    // ── Route table ────────────────────────────────────────────────

    const routes = {
        "": renderMenu,
        "menu": renderMenu,
        "co-create": renderCoCreate,
        "game": renderGame,
        "game-preview": renderGamePreview,
        "saves": renderSaveList,
        "adventure-log": renderAdventureLog,
    };

    // ── Bootstrap ──────────────────────────────────────────────────

    async function init() {
        await initConfig();
        window.addEventListener("hashchange", dispatch);
        dispatch();
    }

    function dispatch() {
        const hash = location.hash.replace("#", "") || "";
        const parts = hash.split("/");
        const view = parts[0];
        const gameId = parts[1] || null;

        /* #saves/{game_id} → checkpoint list; #saves → game list */
        if (view === "saves" && gameId) {
            renderCheckpointList(decodeURIComponent(gameId));
            return;
        }

        /* #game/{game_id} → narrative view */
        if (view === "game" && gameId) {
            renderGame(decodeURIComponent(gameId));
            return;
        }

        /* #adventure-log/{game_id} → post-ending adventure log */
        if (view === "adventure-log" && gameId) {
            renderAdventureLog(decodeURIComponent(gameId));
            return;
        }

        const render = routes[view] || routes[""];
        if (render) render();
    }

    function navigate(hash) {
        location.hash = hash;
    }

    window.Router = { navigate, dispatch };

    /* ═══════════════════════════════════════════════════════════════
       View: Main Menu (#menu / default)
       ──────────────────────────────────────────────────────────────
       Layout:
         centered "Storyloom" title
         6 buttons: New Game | Continue | Load Save | Settings | Credits | Exit
         hover → scale(1.08) grow (CSS-driven, no JS animation)

       Button behaviors:
         New Game  → navigate to #co-create
         Continue  → fetch /api/saves/games, show recent saves inline
         Load Save → navigate to #saves
         Settings  → open settings overlay (language toggle)
         Credits   → open credits overlay
         Exit      → close window / navigate to goodbye
       ═══════════════════════════════════════════════════════════════ */

    function renderMenu() {
        // Best-effort stop any lingering game stream — catches
        // browser-back and manual hash changes that bypass the
        // per-view quit button.  Capture gameId before reset() clears it.
        const activeGameId = GameState.gameId;
        if (activeGameId && typeof API !== "undefined") {
            API.post(`/api/game/${encodeURIComponent(activeGameId)}/stop`).catch(() => {});
        }

        GameState.reset();
        // SSEClient may not be loaded yet — guard
        if (typeof SSEClient !== "undefined" && SSEClient.close) {
            SSEClient.close();
        }
        // Best-effort abort any lingering co-create session —
        // catches browser-back and manual hash changes that bypass
        // the per-view back buttons.
        API.post("/api/co-create/abort").catch(() => {});

        app.innerHTML = `
            <div class="menu-view">
                <h1 class="menu-title">${esc(_("Storyloom"))}</h1>
                <p class="menu-subtitle">${esc(_("AI Text Adventure"))}</p>

                <div class="menu-buttons">
                    <button class="menu-btn accent" id="btn-new-game">
                        ${esc(_("New Game"))}
                    </button>
                    <button class="menu-btn" id="btn-continue">
                        ${esc(_("Continue"))}
                    </button>
                    <button class="menu-btn" id="btn-load-save">
                        ${esc(_("Load Save"))}
                    </button>
                    <button class="menu-btn" id="btn-settings">
                        ${esc(_("Settings"))}
                    </button>
                    <button class="menu-btn" id="btn-credits">
                        ${esc(_("Credits"))}
                    </button>
                    <button class="menu-btn" id="btn-exit">
                        ${esc(_("Exit"))}
                    </button>
                </div>

                <!-- Continue panel: shown when "Continue" clicked, hidden initially -->
                <div id="continue-panel" class="continue-panel hidden"></div>

                <!-- Settings overlay: shown when "Settings" clicked, hidden initially -->
                <div id="settings-overlay" class="settings-overlay hidden"></div>

                <!-- Credits overlay: shown when "Credits" clicked, hidden initially -->
                <div id="credits-overlay" class="settings-overlay hidden"></div>
            </div>
        `;

        // ── Button 1: New Game ────────────────────────────────────

        document.getElementById("btn-new-game").addEventListener("click", () => {
            navigate("co-create");
        });

        // ── Button 2: Continue (auto-resume last played save) ─────────────
        // Reads .last_played.json (O(1)) — no selection UI.

        document.getElementById("btn-continue").addEventListener("click", async () => {
            const panel = document.getElementById("continue-panel");
            panel.classList.remove("hidden");
            panel.innerHTML = `<p class="text-muted">${esc(_("Loading..."))}</p>`;

            try {
                const lp = await API.get("/api/saves/last-played");
                if (!lp || !lp.game_id || !lp.save_file) {
                    showToast(_("No saves found"));
                    panel.classList.add("hidden");
                    return;
                }
                const res = await API.post(
                    `/api/saves/${encodeURIComponent(lp.game_id)}/start/${encodeURIComponent(lp.save_file)}`
                );
                GameState.gameId = res.game_id;
                GameState.roundCount = res.round_count || 0;
                GameState.currentNode = res.current_node || null;
                GameState.storyConfig = res.story_config || {};
                panel.classList.add("hidden");
                navigate("game-preview");
            } catch (err) {
                console.error("Continue failed:", err);
                showToast(_("Something went wrong"));
                panel.classList.add("hidden");
            }
        });

        // ── Button 3: Load Save ───────────────────────────────────

        document.getElementById("btn-load-save").addEventListener("click", () => {
            navigate("saves");
        });

        // ── Button 4: Settings (data-driven from SETTINGS array) ──

        document.getElementById("btn-settings").addEventListener("click", () => {
            const overlay = document.getElementById("settings-overlay");
            overlay.classList.remove("hidden");
            renderSettingsPanel(overlay);
        });

        // ── Button 5: Credits (data-driven from credits.js) ────

        document.getElementById("btn-credits").addEventListener("click", () => {
            const overlay = document.getElementById("credits-overlay");
            overlay.classList.remove("hidden");

            const sections = CREDITS.sections.map(sec => `
                <div class="credits-section">
                    <h3>${esc(_(sec.title))}</h3>
                    ${sec.people.map(p => `<p class="credits-name">${esc(p)}</p>`).join("")}
                </div>
            `).join("");

            overlay.innerHTML = `
                <div class="settings-panel">
                    <h2>${esc(_("Credits"))}</h2>
                    <p class="credits-app">${esc(_(CREDITS.app))}</p>
                    <p class="text-muted" style="margin-bottom:1.5rem">${esc(_(CREDITS.tagline))}</p>
                    ${sections}
                    <button class="menu-btn settings-close" id="btn-credits-close">
                        ${esc(_("Cancel"))}
                    </button>
                </div>
            `;

            overlay.addEventListener("click", (e) => {
                if (e.target === overlay) overlay.classList.add("hidden");
            });
            document.getElementById("btn-credits-close").addEventListener("click", () => {
                overlay.classList.add("hidden");
            });
        });

        // ── Button 6: Exit ────────────────────────────────────────
        // Show a terminal goodbye screen immediately, then attempt
        // server shutdown.  In a packaged app the server kills the
        // process; in dev mode the user closes the tab manually.

        document.getElementById("btn-exit").addEventListener("click", async () => {
            // 1. Render terminal state — no interactive elements remain
            app.innerHTML = `
                <div class="menu-view">
                    <h1 class="menu-title">${esc(_("Storyloom"))}</h1>
                    <p style="font-size:1.3rem; color:var(--text-accent); margin-top:2rem">
                        ${esc(_("Goodbye"))}
                    </p>
                    <p class="text-muted" style="margin-top:0.5rem">
                        ${esc(_("You may close this tab."))}
                    </p>
                </div>
            `;

            // 2. Attempt graceful server shutdown (works in packaged app)
            try { await API.post("/api/exit"); } catch (_) { /* expected in dev */ }
        });
    }

    /* ── Settings Panel (shared by menu overlay) ──────────────────── */

    /** Mask an API key for display: "sk-9a70****3000". */
    function maskKey(key) {
        if (!key || key.length < 8) return key ? "****" : "";
        return key.slice(0, 4) + "****" + key.slice(-4);
    }

    /** Render the settings overlay content.  Called when the user opens
     *  settings, and re-called after a language change so the panel
     *  reflects the new language immediately.                         */
    function renderSettingsPanel(overlay) {
        const rows = SETTINGS.map(def => {
            const current = getSetting(def.key);
            const label = esc(_(def.label));

            if (def.type === "select") {
                /* Select (Language): always editable, no toggle needed */
                return `
                    <div class="setting-row">
                        <span class="setting-label">${label}</span>
                        <select id="setting-${def.key}">${def.options.map(opt =>
                            `<option value="${esc(opt.value)}" ${current === opt.value ? "selected" : ""}>${esc(opt.label)}</option>`
                        ).join("")}</select>
                    </div>`;
            }

            /* text / password: read-only label + pencil edit button */
            const displayVal = def.key === "api_key"
                ? maskKey(current)
                : (current || esc(def.placeholder || ""));
            const displayCls = (!current && def.key !== "api_key") ? "setting-val muted" : "setting-val";
            return `
                <div class="setting-row" id="row-${def.key}">
                    <span class="setting-label">${label}</span>
                    <span class="${displayCls}" id="display-${def.key}">${esc(displayVal)}</span>
                    <input type="${def.type === "password" ? "password" : "text"}"
                           id="input-${def.key}" value="${esc(current || "")}"
                           placeholder="${esc(def.placeholder || "")}"
                           class="setting-input hidden">
                    <button class="setting-edit-btn" id="edit-${def.key}"
                            title="${esc(_("Edit"))}">&#9998;</button>
                </div>`;
        }).join("");

        overlay.innerHTML = `
            <div class="settings-panel">
                <h2>${esc(_("Settings"))}</h2>
                ${rows}
                <button class="menu-btn settings-close" id="btn-settings-close">
                    ${esc(_("Cancel"))}
                </button>
            </div>
        `;

        /* ── Bind events ────────────────────────────────────────── */

        SETTINGS.forEach(def => {
            if (def.type === "select") {
                const el = document.getElementById(`setting-${def.key}`);
                if (!el) return;
                el.addEventListener("change", () => {
                    const needsRerender = applySetting(def.key, el.value);
                    if (needsRerender) {
                        // renderMenu() rebuilds the whole DOM, so we must
                        // re-acquire the overlay from the fresh tree.
                        renderMenu();
                        const newOverlay = document.getElementById("settings-overlay");
                        if (newOverlay) {
                            renderSettingsPanel(newOverlay);
                            newOverlay.classList.remove("hidden");
                        }
                    }
                });
                return;
            }

            /* text / password: pencil toggles edit mode */
            const displayEl = document.getElementById(`display-${def.key}`);
            const inputEl  = document.getElementById(`input-${def.key}`);
            const editBtn  = document.getElementById(`edit-${def.key}`);
            if (!editBtn) return;

            editBtn.addEventListener("click", () => {
                const editing = !inputEl.classList.contains("hidden");
                if (editing) {
                    /* Save: commit value, exit edit mode */
                    applySetting(def.key, inputEl.value);
                    const newVal = getSetting(def.key);
                    if (def.key === "api_key") {
                        displayEl.textContent = maskKey(newVal);
                    } else {
                        displayEl.textContent = newVal || def.placeholder || "";
                        displayEl.classList.toggle("muted", !newVal);
                    }
                    inputEl.classList.add("hidden");
                    displayEl.classList.remove("hidden");
                    editBtn.innerHTML = "&#9998;";
                } else {
                    /* Enter edit mode */
                    inputEl.value = getSetting(def.key);
                    inputEl.classList.remove("hidden");
                    displayEl.classList.add("hidden");
                    editBtn.innerHTML = "&#10003;";
                    inputEl.focus();
                }
            });
        });

        /* Close handlers — use a named reference to avoid listener
           accumulation across multiple renderSettingsPanel() calls. */
        if (overlay._closeHandler) {
            overlay.removeEventListener("click", overlay._closeHandler);
        }
        overlay._closeHandler = (e) => {
            if (e.target === overlay) overlay.classList.add("hidden");
        };
        overlay.addEventListener("click", overlay._closeHandler);

        document.getElementById("btn-settings-close").addEventListener("click", () => {
            overlay.classList.add("hidden");
        });
    }

    /* ═══════════════════════════════════════════════════════════════
       View: Co-Create (#co-create)
       ──────────────────────────────────────────────────────────────
       Full chat-style Q&A interface for co-creating the story setup.
       Delegates to CoCreateView.render() (co-create.js).

       Layout:
         top bar:  /quit (left)  |  "Co-Create" title (center)
         messages: scrollable chat bubbles (assistant / user / info / error)
         input bar:  textarea + ↑ send button + /go button
       ═══════════════════════════════════════════════════════════════ */

    function renderCoCreate() {
        CoCreateView.render(app);
    }

    /* ═══════════════════════════════════════════════════════════════
       View: Game Preview (#game-preview)
       ──────────────────────────────────────────────────────────────
       Transition page between co-creation generate and game start.
       Reads story_config from the save file (GameState.saveFile or
       ``_init.json``) so the save is the canonical source of truth.

       Layout:
         header:  ← Back button (top-left)
         content: story label (title) + setting text (centered)
                  + Begin Adventure button → Round 1 prompt
       ═══════════════════════════════════════════════════════════════ */

    function renderGamePreview() {
        const gameId = GameState.gameId;
        if (!gameId) {
            navigate("menu");
            return;
        }

        // Show loading state while fetching save data
        app.innerHTML = `
            <div class="gp-view">
                <div class="gp-header">
                    <button class="cc-back-btn" id="gp-back"
                            title="${esc(_("Back to Menu"))}">←</button>
                </div>
                <div class="gp-content">
                    <p class="text-muted">${esc(_("Loading..."))}</p>
                </div>
            </div>
        `;

        document.getElementById("gp-back").addEventListener("click", () => {
            GameState.reset();
            navigate("menu");
        });

        // Fetch story_config from the save file AND store game server-side.
        // Uses /start/ (not /load/) to ensure the GameLoop is in the session
        // before "Begin Adventure" → POST /api/game/{id}/start.
        const filename = GameState.saveFile || "_init.json";
        API.post(`/api/saves/${encodeURIComponent(gameId)}/start/${encodeURIComponent(filename)}`)
            .then(data => {
                const config = data.story_config || {};
                _renderPreviewContent(config);
            })
            .catch(err => {
                // Fall back to in-memory story_config if save fetch fails
                const config = GameState.storyConfig;
                if (config) {
                    console.warn("Save fetch failed, using in-memory config:", err);
                    _renderPreviewContent(config);
                } else {
                    app.innerHTML = `
                        <div class="gp-view">
                            <div class="gp-content">
                                <p class="text-error">${esc(err.message)}</p>
                                <button class="menu-btn" style="margin-top:1.5rem" id="gp-back-err">
                                    ${esc(_("Back to Menu"))}
                                </button>
                            </div>
                        </div>
                    `;
                    document.getElementById("gp-back-err").addEventListener("click", () => {
                        GameState.reset();
                        navigate("menu");
                    });
                }
            });
    }

    /** Render the preview content with story label, setting, and
     *  Begin Adventure button that starts the game. */
    function _renderPreviewContent(config) {
        const gameId = GameState.gameId;
        app.innerHTML = `
            <div class="gp-view">
                <div class="gp-header">
                    <button class="cc-back-btn" id="gp-back"
                            title="${esc(_("Back to Menu"))}">←</button>
                </div>

                <div class="gp-content">
                    <h1 class="gp-label">${esc(config.label)}</h1>
                    <p class="gp-setting">${esc(config.setting || "")}</p>

                    <button class="gp-start-btn" id="gp-start">
                        ${esc(_("Begin Adventure"))}
                    </button>
                </div>
            </div>
        `;

        document.getElementById("gp-back").addEventListener("click", () => {
            GameState.reset();
            navigate("menu");
        });

        document.getElementById("gp-start").addEventListener("click", () => {
            navigate(`game/${encodeURIComponent(gameId)}`);
        });
    }

    /* ═══════════════════════════════════════════════════════════════
       View: Game (#game/{id}) — PLACEHOLDER
       ═══════════════════════════════════════════════════════════════ */

    function renderGame(gameId) {
        if (!gameId) {
            navigate("menu");
            return;
        }

        GameState.gameId = gameId;
        const label = (GameState.storyConfig && GameState.storyConfig.label)
            || gameId;

        /* Close any existing SSE connection before rendering */
        if (typeof SSEClient !== "undefined" && SSEClient.close) {
            SSEClient.close();
        }

        /* Clear the app shell — GameView builds its own DOM */
        app.innerHTML = "";
        GameView.render(app, gameId, label);
    }

    /* ═══════════════════════════════════════════════════════════════
       View: Save List (#saves) — PLACEHOLDER
       ═══════════════════════════════════════════════════════════════ */

    function renderSaveList() {
        GameState.reset();
        if (typeof SSEClient !== "undefined" && SSEClient.close) {
            SSEClient.close();
        }

        app.innerHTML = `
            <div class="sv-view">
                <div class="sv-header">
                    <button class="cc-back-btn" id="sv-back"
                            title="${esc(_("Back to Menu"))}">←</button>
                    <span class="sv-title">${esc(_("Load Save"))}</span>
                </div>
                <div class="sv-list" id="sv-game-list">
                    <p class="sv-card-empty">${esc(_("Loading..."))}</p>
                </div>
            </div>
        `;

        document.getElementById("sv-back").addEventListener("click", () => {
            navigate("menu");
        });

        API.get("/api/saves/games").then(games => {
            const list = document.getElementById("sv-game-list");
            if (!games.length) {
                list.innerHTML = `<p class="sv-card-empty">${esc(_("No saves found"))}</p>`;
                return;
            }
            list.innerHTML = games.map(g => `
                <div class="sv-card" data-game-id="${esc(g.game_id)}">
                    <div class="sv-card-main">
                        <span class="sv-card-label">${esc(g.label)}</span>
                        <div class="sv-card-meta">
                            <span>${esc(g.genre || "?")}</span>
                            <span>${g.save_count} ${esc(_("saves"))}</span>
                        </div>
                    </div>
                    ${g.last_played_at ? `<span class="sv-card-time">${formatDate(g.last_played_at)}</span>` : ""}
                    <button class="sv-card-trash" title="${esc(_("Delete"))}">${TRASH_ICON}</button>
                </div>
            `).join("");

            list.querySelectorAll(".sv-card").forEach(card => {
                card.addEventListener("click", () => {
                    navigate(`saves/${encodeURIComponent(card.dataset.gameId)}`);
                });
                card.querySelector(".sv-card-trash").addEventListener("click", e => {
                    e.stopPropagation();
                    showConfirmPopup(e.clientX, e.clientY,
                        _("Delete this game?"),
                        () => {
                            API.del(`/api/saves/${encodeURIComponent(card.dataset.gameId)}`)
                                .then(() => {
                                    showToast(_("Game deleted."));
                                    card.remove();
                                    if (!list.querySelectorAll(".sv-card").length) {
                                        list.innerHTML = `<p class="sv-card-empty">${esc(_("No saves found"))}</p>`;
                                    }
                                })
                                .catch(err => showToast(err.message));
                        });
                });
            });
        }).catch(err => {
            document.getElementById("sv-game-list").innerHTML =
                `<p class="text-error">${esc(err.message)}</p>`;
        });
    }

    /* ═══════════════════════════════════════════════════════════════════
       View: Checkpoint List (#saves/{game_id}) — save file browser
       ──────────────────────────────────────────────────────────────
       Each card = one .json save file.  Sorted by saved_at descending.
       Left-click loads the save into the game session and navigates to
       #game-preview; right-click shows a delete confirmation popup.
       ═══════════════════════════════════════════════════════════════════ */

    function renderCheckpointList(gameId) {
        if (typeof SSEClient !== "undefined" && SSEClient.close) {
            SSEClient.close();
        }

        app.innerHTML = `
            <div class="sv-view">
                <div class="sv-header">
                    <button class="cc-back-btn" id="sv-back"
                            title="${esc(_("Back to Menu"))}">←</button>
                    <span class="sv-title" id="sv-cp-title">${esc(_("Loading..."))}</span>
                    <button class="sv-restart-btn" id="sv-restart">${esc(_("Restart"))}</button>
                </div>
                <div class="sv-list sv-list--checkpoints" id="sv-cp-list">
                    <p class="sv-card-empty">${esc(_("Loading..."))}</p>
                </div>
            </div>
        `;

        document.getElementById("sv-back").addEventListener("click", () => {
            navigate("saves");
        });

        document.getElementById("sv-restart").addEventListener("click", async () => {
            try {
                const data = await API.post(
                    `/api/saves/${encodeURIComponent(gameId)}/start/_init.json`
                );
                GameState.gameId = data.game_id;
                GameState.roundCount = data.round_count || 0;
                GameState.currentNode = data.current_node || null;
                GameState.storyConfig = data.story_config || {};
                GameState.saveFile = "_init.json";
                navigate("game-preview");
            } catch (err) {
                showToast(err.message);
            }
        });

        /* Fetch saves + game metadata in parallel.
           Saves come back in directory order; re-sort by saved_at
           descending so the newest checkpoint is at the top. */
        Promise.all([
            API.get(`/api/saves/${encodeURIComponent(gameId)}`),
            API.get("/api/saves/games"),
        ]).then(([saves, games]) => {
            const game = games.find(g => g.game_id === gameId);
            document.getElementById("sv-cp-title").textContent =
                game ? game.label : gameId;

            saves.sort((a, b) => (b.saved_at || "").localeCompare(a.saved_at || ""));

            /* Exclude _init.json — it is the initial save, not a checkpoint. */
            const checkpoints = saves.filter(s => s.filename !== "_init.json");

            const list = document.getElementById("sv-cp-list");
            if (!checkpoints.length) {
                list.innerHTML = `<p class="sv-card-empty">${esc(_("No saves in this game."))}</p>`;
                return;
            }

            list.innerHTML = checkpoints.map(s => {
                const label = s.checkpoint_title || s.filename;
                const summary = s.checkpoint_summary || "";
                return `
                    <div class="sv-card" data-filename="${esc(s.filename)}">
                        <div class="sv-card-main">
                            <span class="sv-card-label">${esc(label)}</span>
                            ${summary ? `<div class="sv-card-meta"><span>${esc(summary)}</span></div>` : ""}
                        </div>
                        ${s.saved_at ? `<span class="sv-card-time">${formatDate(s.saved_at)}</span>` : ""}
                        <button class="sv-card-trash" title="${esc(_("Delete"))}">${TRASH_ICON}</button>
                    </div>
                `;
            }).join("");

            list.querySelectorAll(".sv-card").forEach(card => {
                card.addEventListener("click", async () => {
                    const filename = card.dataset.filename;
                    try {
                        const data = await API.post(
                            `/api/saves/${encodeURIComponent(gameId)}/start/${encodeURIComponent(filename)}`
                        );
                        GameState.gameId = data.game_id;
                        GameState.roundCount = data.round_count || 0;
                        GameState.currentNode = data.current_node || null;
                        GameState.storyConfig = data.story_config || {};
                        GameState.saveFile = filename;
                        navigate("game-preview");
                    } catch (err) {
                        showToast(err.message);
                    }
                });
                card.querySelector(".sv-card-trash").addEventListener("click", e => {
                    e.stopPropagation();
                    showConfirmPopup(e.clientX, e.clientY,
                        _("Delete this save?"),
                        () => {
                            API.del(`/api/saves/${encodeURIComponent(gameId)}/${encodeURIComponent(card.dataset.filename)}`)
                                .then(() => {
                                    showToast(_("Save deleted."));
                                    card.remove();
                                    if (!list.querySelectorAll(".sv-card").length) {
                                        list.innerHTML = `<p class="sv-card-empty">${esc(_("No saves in this game."))}</p>`;
                                    }
                                })
                                .catch(err => showToast(err.message));
                        });
                });
            });
        }).catch(err => {
            document.getElementById("sv-cp-list").innerHTML =
                `<p class="text-error">${esc(err.message)}</p>`;
        });
    }

    /* ═══════════════════════════════════════════════════════════════════
       View: Adventure Log (#adventure-log/{game_id})
       ──────────────────────────────────────────────────────────────
       Post-ending scrollable text page showing the generated
       adventure log.  Delegates to AdventureLogView.render().

       Layout:
         header:  ← Back button (top-left) + story label + [Export] (disabled)
         content: scrollable log text (no border, white)
       ═══════════════════════════════════════════════════════════════ */

    function renderAdventureLog(gameId) {
        GameState.gameId = gameId;

        /* Get story label from GameState (set during game session).
           Falls back to gameId only when GameState has been reset —
           the label is present in normal flow (coming from game.js
           end modal, where GameState.storyConfig is still populated). */
        const label = (GameState.storyConfig && GameState.storyConfig.label)
            || gameId;

        app.innerHTML = "";
        AdventureLogView.render(app, gameId, label);
    }

    /* ── Confirm Popup (delete confirmation) ───────────────────────── */

    /** Show a positioned confirmation popup for delete actions.
     *  @param {number} x - clientX of the triggering click
     *  @param {number} y - clientY of the triggering click
     *  @param {string} message - main question text (already translated)
     *  @param {Function} onConfirm - called when user clicks "Yes"    */
    function showConfirmPopup(x, y, message, onConfirm) {
        const existing = document.querySelector(".ctx-menu");
        if (existing) existing.remove();

        const menu = document.createElement("div");
        menu.className = "ctx-menu";
        menu.innerHTML = `
            <p class="ctx-menu-text">${esc(message)}</p>
            <p class="ctx-menu-warn">${esc(_("This cannot be undone."))}</p>
            <div class="ctx-menu-actions">
                <button class="ctx-menu-btn" id="ctx-no">${esc(_("No"))}</button>
                <button class="ctx-menu-btn danger" id="ctx-yes">${esc(_("Yes"))}</button>
            </div>
        `;
        /* Keep within viewport bounds */
        menu.style.left = Math.min(x, window.innerWidth - 240) + "px";
        menu.style.top = Math.min(y, window.innerHeight - 140) + "px";
        document.body.appendChild(menu);

        const close = () => menu.remove();
        menu.querySelector("#ctx-no").addEventListener("click", close);
        menu.querySelector("#ctx-yes").addEventListener("click", () => {
            close();
            onConfirm();
        });
        /* Click outside to dismiss */
        setTimeout(() => {
            document.addEventListener("click", function handler(e) {
                if (!menu.contains(e.target)) {
                    close();
                    document.removeEventListener("click", handler);
                }
            });
        }, 0);
    }

    /** Format an ISO 8601 string for display (e.g. "2026-07-19 14:30"). */
    function formatDate(iso) {
        if (!iso) return "";
        const d = new Date(iso);
        if (isNaN(d.getTime())) return iso;
        const pad = n => String(n).padStart(2, "0");
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }

    // ── Kick off ──────────────────────────────────────────────────

    init();
})();
