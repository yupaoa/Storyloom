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

    // ── Route table ────────────────────────────────────────────────

    const routes = {
        "": renderMenu,
        "menu": renderMenu,
        "co-create": renderCoCreate,
        "game": renderGame,
        "saves": renderSaveList,
    };

    // ── Bootstrap ──────────────────────────────────────────────────

    async function init() {
        await initConfig();
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

    window.Router = { navigate, dispatch };

    /* ═══════════════════════════════════════════════════════════════
       View: Main Menu (#menu / default)
       ──────────────────────────────────────────────────────────────
       Layout:
         centered "storyloom" title
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
        GameState.reset();
        // SSEClient may not be loaded yet — guard
        if (typeof SSEClient !== "undefined" && SSEClient.close) {
            SSEClient.close();
        }

        app.innerHTML = `
            <div class="menu-view">
                <h1 class="menu-title">${esc(_("storyloom"))}</h1>
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

        // ── Button 2: Continue ──────────────────────────────────────

        document.getElementById("btn-continue").addEventListener("click", async () => {
            const panel = document.getElementById("continue-panel");

            // Toggle off if already visible
            if (!panel.classList.contains("hidden")) {
                panel.classList.add("hidden");
                return;
            }

            panel.classList.remove("hidden");
            panel.innerHTML = `<p class="text-muted">${esc(_("Loading..."))}</p>`;

            try {
                const games = await API.get("/api/saves/games");

                if (!games || games.length === 0) {
                    panel.innerHTML = `<p class="no-saves-msg">${esc(_("No saves found"))}</p>`;
                    return;
                }

                // Sort by created_at descending, show top 3
                const recent = games
                    .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""))
                    .slice(0, 3);

                panel.innerHTML = recent.map(g => `
                    <div class="continue-item" data-game-id="${esc(g.game_id)}">
                        <span class="ci-label">${esc(g.label)}</span>
                        <span class="ci-meta">
                            ${esc(g.genre || "?")} · ${esc(g.tier || "?")} · ${esc(_("Save"))}: ${g.save_count}
                        </span>
                    </div>
                `).join("");

                // Click handler: load latest save for the selected game
                panel.querySelectorAll(".continue-item").forEach(item => {
                    item.addEventListener("click", async () => {
                        const gameId = item.dataset.gameId;
                        try {
                            const saves = await API.get(
                                `/api/saves/${encodeURIComponent(gameId)}`
                            );
                            if (!saves || saves.length === 0) {
                                panel.innerHTML = `<p class="no-saves-msg">${esc(_("No saves found"))}</p>`;
                                return;
                            }
                            const latestSave = saves[saves.length - 1];
                            const filename = latestSave.filename;
                            const res = await API.post(
                                `/api/saves/${encodeURIComponent(gameId)}/load/${encodeURIComponent(filename)}`
                            );
                            GameState.gameId = res.game_id;
                            GameState.roundCount = res.round_count || 0;
                            GameState.currentNode = res.current_node || null;
                            navigate(`game/${res.game_id}`);
                        } catch (err) {
                            panel.innerHTML = `<p class="text-error">${esc(err.message)}</p>`;
                        }
                    });
                });
            } catch (err) {
                panel.innerHTML = `<p class="text-error">${esc(err.message)}</p>`;
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
                    <p class="credits-app">${esc(CREDITS.app)}</p>
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
                    <h1 class="menu-title">storyloom</h1>
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
                        // Re-render panel in-place so labels update
                        renderSettingsPanel(overlay);
                        renderMenu();
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

        /* Close handlers */
        overlay.addEventListener("click", (e) => {
            if (e.target === overlay) overlay.classList.add("hidden");
        });
        document.getElementById("btn-settings-close").addEventListener("click", () => {
            overlay.classList.add("hidden");
        });
    }

    /* ═══════════════════════════════════════════════════════════════
       View: Co-Create (#co-create) — PLACEHOLDER
       ═══════════════════════════════════════════════════════════════ */

    function renderCoCreate() {
        app.innerHTML = `
            <div class="placeholder-view">
                <h2>Co-Create</h2>
                <p class="text-muted">Co-creation Q&A view — coming soon.</p>
                <button class="menu-btn" style="margin-top:1.5rem" id="btn-back-menu">
                    ${esc(_("Back to Menu"))}
                </button>
            </div>
        `;
        document.getElementById("btn-back-menu").addEventListener("click", () => {
            navigate("menu");
        });
    }

    /* ═══════════════════════════════════════════════════════════════
       View: Game (#game/{id}) — PLACEHOLDER
       ═══════════════════════════════════════════════════════════════ */

    function renderGame() {
        app.innerHTML = `
            <div class="placeholder-view">
                <h2>Game</h2>
                <p class="text-muted">Gameplay view — coming soon.</p>
                <button class="menu-btn" style="margin-top:1.5rem" id="btn-back-menu">
                    ${esc(_("Back to Menu"))}
                </button>
            </div>
        `;
        document.getElementById("btn-back-menu").addEventListener("click", () => {
            navigate("menu");
        });
    }

    /* ═══════════════════════════════════════════════════════════════
       View: Save List (#saves) — PLACEHOLDER
       ═══════════════════════════════════════════════════════════════ */

    function renderSaveList() {
        app.innerHTML = `
            <div class="placeholder-view">
                <h2>${esc(_("Load Save"))}</h2>
                <p class="text-muted">Save management view — coming soon.</p>
                <button class="menu-btn" style="margin-top:1.5rem" id="btn-back-menu">
                    ${esc(_("Back to Menu"))}
                </button>
            </div>
        `;
        document.getElementById("btn-back-menu").addEventListener("click", () => {
            navigate("menu");
        });
    }

    // ── Kick off ──────────────────────────────────────────────────

    init();
})();
