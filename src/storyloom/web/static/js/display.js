/* ═══════════════════════════════════════════════════════════════════
   display.js — DOM rendering functions for the game narrative view

   All functions operate within a game container element passed as the
   first argument (or use the shared `_container` reference set via
   `Display.init(container)`).

   Exports (Display namespace):
     init(container)               — set the game view container
     appendSegment(text)           — add <p> to story area
     appendChoiceText(text)        — add selected choice (green) to story
     showChoices(choices) → Promise<key> — render choice buttons, resolve on click
     flattenChoices(choices) → Array — flatten engine choice objects
     clearChoices()                — remove choice panel
     showLoading()                 — show loading indicator with bouncing dots
     hideLoading()                 — remove loading indicator
     showErrorModal(msg, onRetry, onQuit) — error modal with Retry/Exit
     showEndModal(msg, onPrimary, onQuit, primaryLabel, quitLabel) — end modal
     closeModal()                  — remove any open modal
     showSettings(getSpeed, onSpeed, getFont, onFont, getLine, onLine) — settings
     closeSettings()               — remove settings overlay

   Internal: _scrollToCenter(el) — scroll so new element is vertically centred.

   Authority:
     exec-flow.md §4.1 (event types), §4.5 (display pacing)
     User spec: green choice text, gray loading dots, semi-transparent modal
   ═══════════════════════════════════════════════════════════════════ */

const Display = (function () {
    let _container = null;

    /** Set the game view container element.  Call once on render. */
    function init(container) {
        _container = container;
    }

    function $(sel) { return _container ? _container.querySelector(sel) : null; }

    /* ── Story text ────────────────────────────────────────────────── */

    /** Append a narrative segment paragraph to the story area. */
    function appendSegment(text) {
        const story = $("#game-story");
        if (!story) return;
        const p = document.createElement("p");
        p.className = "game-segment";
        p.textContent = text;
        story.appendChild(p);
        _scrollToCenter(p);
    }

    /** Append selected choice text — green highlight, same font/size. */
    function appendChoiceText(text) {
        const story = $("#game-story");
        if (!story) return;
        const p = document.createElement("p");
        p.className = "game-choice-text";
        p.textContent = text;
        story.appendChild(p);
        _scrollToCenter(p);
    }

    /* ── Loading indicator ─────────────────────────────────────────── */

    /** Show loading indicator with animated bouncing dots below story text. */
    function showLoading() {
        /* Remove existing indicator if any */
        hideLoading();
        const story = $("#game-story");
        if (!story) return;
        const el = document.createElement("div");
        el.className = "game-loading";
        el.id = "game-loading-indicator";
        el.innerHTML = `<span>${_("Loading")}</span><span class="cc-dots"><span>.</span><span>.</span><span>.</span></span>`;
        story.appendChild(el);
        _scrollToCenter(el);
    }

    /** Remove the loading indicator. */
    function hideLoading() {
        const el = $("#game-loading-indicator");
        if (el) el.remove();
    }

    /* ── Choices ───────────────────────────────────────────────────── */

    let _choiceResolve = null;

    /** Build human-readable reason text for a disabled option.
     *
     *  Per exec-flow.md §4.6: disabled options must show the condition
     *  that failed and the current variable value, e.g.
     *  "需理智值 >= 30，当前：20".
     *
     *  Uses the condition string the engine already includes in the
     *  ``conditions`` dict of choice data, plus the current variable
     *  values tracked in ``GameState.stateVars``.
     *
     *  @param {string} condition — raw condition from engine (e.g. "理智值 >= 30")
     *  @returns {string} display-ready reason, or "" if no condition */
    function _buildDisabledReason(condition) {
        if (!condition || !condition.trim()) return "";
        /* Parse "var_name op value" to extract variable name */
        /* \p{L} matches Unicode letters (including CJK) — JS \w does
           not.  Python 3 \w handles this natively; we must use the u
           flag here to match Chinese variable names like 理智值.  */
        const match = condition.match(
            /^\s*([\p{L}\p{N}_]+)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*$/u
        );
        if (match) {
            const varName = match[1];
            const current = GameState.stateVars[varName];
            if (current !== undefined) {
                /* Single-pass replacement: avoids the (low-probability)
                   edge case where `condition` itself contains "{val}". */
                const tmpl = _("Requires {cond}, current: {val}");
                return tmpl.replaceAll(
                    /{cond}|{val}/g,
                    (m) => m === "{cond}" ? condition : String(current)
                );
            }
        }
        return _("Requires {cond}").replace("{cond}", condition);
    }

    /** Flatten engine-evaluated choices into 1-indexed options.
     *  Shared by showChoices() (rendering) and game.js (label lookup).
     *  Matches dev_cli game_driver.py _show_choices() flat-indexing.
     *
     *  @param {Array} choices — engine-evaluated choice objects:
     *    [{ id, branches: ["branch_name"], labels: ["option text"],
     *       conditions: {"branch": "condition_str"}, enabled: [true, false] }]
     *  @returns {Array} flat options with
     *    { key, label, enabled, disabledReason, branch } */
    function flattenChoices(choices) {
        const result = [];
        let idx = 0;
        for (const c of choices) {
            const labels = c.labels || [];
            const enabled = c.enabled || labels.map(() => true);
            const branches = c.branches || [];
            const conditions = c.conditions || {};
            for (let i = 0; i < labels.length; i++) {
                idx++;
                const isEnabled = i < enabled.length ? enabled[i] : true;
                /* Build disabled reason from engine-provided condition
                   string + current state var value (exec-flow.md §4.6). */
                let disabledReason = "";
                if (!isEnabled) {
                    const branch = branches[i] || "";
                    const cond = conditions[branch] || "";
                    disabledReason = _buildDisabledReason(cond);
                }
                result.push({
                    key: String(idx),
                    label: labels[i],
                    enabled: isEnabled,
                    disabledReason: disabledReason,
                    branch: (branches[i]) || null,
                });
            }
        }
        return result;
    }

    /** Render choice buttons below the story area.
     *  @param {Array} choices — engine-evaluated choice objects
     *  @returns {Promise<string>} resolves with the selected key (1-indexed string) */
    function showChoices(choices) {
        clearChoices();

        const panel = document.createElement("div");
        panel.className = "game-choices";
        panel.id = "game-choices-panel";

        const flatOpts = flattenChoices(choices);

        /* Build buttons */
        for (const opt of flatOpts) {
            const btn = document.createElement("button");
            btn.className = "game-choice-btn";
            btn.textContent = opt.label;
            if (!opt.enabled) {
                btn.disabled = true;
                /* Per exec-flow.md §4.6: show specific condition reason
                   (e.g. "需理智值 >= 30，当前：20"), fall back to generic
                   label only when no condition info is available. */
                if (opt.disabledReason) {
                    btn.textContent += "（" + opt.disabledReason + "）";
                } else {
                    btn.textContent += "（" + _("unavailable") + "）";
                }
            }
            btn.addEventListener("click", () => {
                if (!opt.enabled) return;
                _choiceResolve(opt.key);
            });
            panel.appendChild(btn);
        }

        /* Append below story area — at page bottom */
        const story = $("#game-story");
        if (story) {
            story.parentNode.insertBefore(panel, story.nextSibling);
        }

        _scrollToCenter(panel);

        return new Promise((resolve) => {
            _choiceResolve = resolve;
        });
    }

    /** Remove the choices panel. */
    function clearChoices() {
        const panel = document.getElementById("game-choices-panel");
        if (panel) panel.remove();
        _choiceResolve = null;
    }

    /* ── Modal dialogs ─────────────────────────────────────────────── */

    /** Show an error modal with Retry and Exit buttons.
     *  @param {string} message — error message text
     *  @param {Function} onRetry — called when user clicks Retry
     *  @param {Function} onQuit — called when user clicks Quit */
    function showErrorModal(message, onRetry, onQuit) {
        closeModal();

        const overlay = document.createElement("div");
        overlay.className = "game-modal-overlay";
        overlay.id = "game-modal-overlay";

        overlay.innerHTML = `
            <div class="game-modal">
                <p class="game-modal-text">${escHtml(message)}</p>
                <div class="game-modal-actions">
                    <button class="game-modal-btn accent" id="game-modal-primary">
                        ${_("Retry")}
                    </button>
                    <button class="game-modal-btn" id="game-modal-secondary">
                        ${_("Quit")}
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);

        overlay.querySelector("#game-modal-primary").addEventListener("click", () => {
            closeModal();
            if (onRetry) onRetry();
        });
        overlay.querySelector("#game-modal-secondary").addEventListener("click", () => {
            closeModal();
            if (onQuit) onQuit();
        });

        /* Click outside modal to dismiss (only overlay background) */
        overlay.addEventListener("click", (e) => {
            if (e.target === overlay) {
                closeModal();
            }
        });
    }

    /** Show a general end/transition modal.
     *  @param {string} message
     *  @param {Function} onPrimary — primary action callback
     *  @param {Function} onQuit — secondary (quit) action callback
     *  @param {string} primaryLabel — label for primary button
     *  @param {string} quitLabel — label for quit button */
    function showEndModal(message, onPrimary, onQuit, primaryLabel, quitLabel) {
        closeModal();

        const overlay = document.createElement("div");
        overlay.className = "game-modal-overlay";
        overlay.id = "game-modal-overlay";

        overlay.innerHTML = `
            <div class="game-modal">
                <p class="game-modal-text">${escHtml(message)}</p>
                <div class="game-modal-actions">
                    <button class="game-modal-btn accent" id="game-modal-primary">
                        ${escHtml(primaryLabel || _("OK"))}
                    </button>
                    <button class="game-modal-btn" id="game-modal-secondary">
                        ${escHtml(quitLabel || _("Quit"))}
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);

        overlay.querySelector("#game-modal-primary").addEventListener("click", () => {
            closeModal();
            if (onPrimary) onPrimary();
        });
        overlay.querySelector("#game-modal-secondary").addEventListener("click", () => {
            closeModal();
            if (onQuit) onQuit();
        });

        overlay.addEventListener("click", (e) => {
            if (e.target === overlay) closeModal();
        });
    }

    /** Remove any open modal overlay. */
    function closeModal() {
        const existing = document.getElementById("game-modal-overlay");
        if (existing) existing.remove();
    }

    /* ── In-game Settings ──────────────────────────────────────────── */

    /** Settings section definitions — add entries here to extend the
     *  settings panel without touching DOM construction or event binding.
     *  Each section: { id, label, options: [{ val, label }], getVal, onChange } */
    function _buildSettingsSections(getSpeed, onSpeed, getFont, onFont, getLine, onLine) {
        return [
            {
                id: "setting-speed",
                label: _("Speed"),
                options: [
                    { val: 0.75, label: "0.75x" },
                    { val: 1,    label: "1x" },
                    { val: 2,    label: "2x" },
                    { val: 3,    label: "3x" },
                ],
                getVal: getSpeed,
                onChange: onSpeed,
                parseVal: Number,
            },
            {
                id: "setting-font",
                label: _("Font Size"),
                options: [
                    { val: "small",  label: _("Small") },
                    { val: "medium", label: _("Medium") },
                    { val: "large",  label: _("Large") },
                ],
                getVal: getFont,
                onChange: onFont,
                parseVal: (v) => v,
            },
            {
                id: "setting-line",
                label: _("Line Spacing"),
                options: [
                    { val: 0.75, label: "0.75" },
                    { val: 1.0,  label: "1.0" },
                    { val: 1.25, label: "1.25" },
                ],
                getVal: getLine,
                onChange: onLine,
                parseVal: Number,
            },
        ];
    }

    function _renderOpts(opts, current) {
        return opts.map(o => {
            const active = o.val === current ? " active" : "";
            return `<button class="game-setting-opt${active}" data-val="${o.val}">${o.label}</button>`;
        }).join("");
    }

    /** Show the in-game settings overlay.
     *  @param {Function} getSpeed — () → current speed preset
     *  @param {Function} onSpeed — (speed) → void
     *  @param {Function} getFont — () → current font size ("small"|"medium"|"large")
     *  @param {Function} onFont — (size) → void
     *  @param {Function} getLine — () → current line spacing (0.75, 1.0, or 1.25)
     *  @param {Function} onLine — (spacing) → void */
    function showSettings(getSpeed, onSpeed, getFont, onFont, getLine, onLine) {
        closeSettings();

        const overlay = document.createElement("div");
        overlay.className = "game-settings-overlay";
        overlay.id = "game-settings-overlay";

        const sections = _buildSettingsSections(
            getSpeed, onSpeed, getFont, onFont, getLine, onLine
        );

        /* Build rows HTML from section definitions */
        const rowsHTML = sections.map(s => `
            <div class="game-setting-row">
                <span class="game-setting-label">${s.label}</span>
                <div class="game-setting-options" id="${s.id}">
                    ${_renderOpts(s.options, s.getVal())}
                </div>
            </div>
        `).join("");

        overlay.innerHTML = `
            <div class="game-settings-panel">
                <h2>${_("Settings")}</h2>
                ${rowsHTML}
                <button class="menu-btn game-settings-close" id="btn-game-settings-close">
                    ${_("Close")}
                </button>
            </div>
        `;

        document.body.appendChild(overlay);

        /* Bind option clicks — one delegated listener per section */
        for (const s of sections) {
            const container = overlay.querySelector(`#${s.id}`);
            if (!container) continue;
            container.addEventListener("click", (e) => {
                const btn = e.target.closest(".game-setting-opt");
                if (!btn) return;
                const val = s.parseVal(btn.dataset.val);
                s.onChange(val);
                /* Refresh the option buttons to reflect new active state */
                container.innerHTML = _renderOpts(s.options, s.getVal());
            });
        }

        overlay.querySelector("#btn-game-settings-close").addEventListener("click", closeSettings);
        overlay.addEventListener("click", (e) => {
            if (e.target === overlay) closeSettings();
        });
    }

    /** Remove the settings overlay. */
    function closeSettings() {
        const existing = document.getElementById("game-settings-overlay");
        if (existing) existing.remove();
    }

    /* ── Helpers ───────────────────────────────────────────────────── */

    /** Scroll so the newest content sits at the viewport centre.
     *  Relies on .game-story { padding-bottom: 50vh } which provides
     *  scroll room below the last element.  Simply scrolling to max
     *  puts the last segment roughly at the vertical midpoint. */
    function _scrollToCenter(_el) {
        const story = $("#game-story");
        if (!story) return;
        story.scrollTop = story.scrollHeight;
    }

    /** HTML entity escape. */
    function escHtml(s) {
        const d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }

    /* ── Export ────────────────────────────────────────────────────── */
    return {
        init,
        appendSegment,
        appendChoiceText,
        showChoices,
        flattenChoices,
        clearChoices,
        showLoading,
        hideLoading,
        showErrorModal,
        showEndModal,
        closeModal,
        showSettings,
        closeSettings,
    };
})();
