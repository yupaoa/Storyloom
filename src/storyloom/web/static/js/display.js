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
     clearChoices()                — remove choice panel
     showLoading()                 — show "加载中..." indicator
     hideLoading()                 — remove loading indicator
     showErrorModal(msg, onRetry, onQuit) — error modal with Retry/Exit
     showEndModal(msg, onPrimary, onQuit, primaryLabel, quitLabel) — end modal
     closeModal()                  — remove any open modal
     showSettings(getSpeed, onSpeed, getFont, onFont, getLine, onLine) — settings
     closeSettings()               — remove settings overlay
     scrollToBottom()              — scroll story area to latest content

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
        scrollToBottom();
    }

    /** Append selected choice text — green highlight, same font/size. */
    function appendChoiceText(text) {
        const story = $("#game-story");
        if (!story) return;
        const p = document.createElement("p");
        p.className = "game-choice-text";
        p.textContent = text;
        story.appendChild(p);
        scrollToBottom();
    }

    /* ── Loading indicator ─────────────────────────────────────────── */

    /** Show "加载中..." with animated bouncing dots below story text. */
    function showLoading() {
        /* Remove existing indicator if any */
        hideLoading();
        const story = $("#game-story");
        if (!story) return;
        const el = document.createElement("div");
        el.className = "game-loading";
        el.id = "game-loading-indicator";
        el.innerHTML = `<span>加载中</span><span class="cc-dots"><span>.</span><span>.</span><span>.</span></span>`;
        story.appendChild(el);
        scrollToBottom();
    }

    /** Remove the loading indicator. */
    function hideLoading() {
        const el = $("#game-loading-indicator");
        if (el) el.remove();
    }

    /* ── Manual-mode continue hint ──────────────────────────────────── */

    /** Show "点击或按空格继续" hint at the bottom of the story area. */
    function showContinueHint() {
        hideContinueHint();
        const story = $("#game-story");
        if (!story) return;
        const el = document.createElement("div");
        el.className = "game-continue-hint";
        el.id = "game-continue-hint";
        el.innerHTML = `<span>点击或按空格继续</span><span class="cc-dots"><span>.</span><span>.</span><span>.</span></span>`;
        story.appendChild(el);
        scrollToBottom();
    }

    /** Remove the continue hint. */
    function hideContinueHint() {
        const el = document.getElementById("game-continue-hint");
        if (el) el.remove();
    }

    /* ── Choices ───────────────────────────────────────────────────── */

    let _choiceResolve = null;

    /** Render choice buttons below the story area.
     *  @param {Array} choices — engine-evaluated choice objects:
     *    [{ id, branches: ["branch_name"], labels: ["选项文本"],
     *       conditions: ["condition_str"], enabled: [true, false] }]
     *  @returns {Promise<string>} resolves with the selected key (1-indexed string) */
    function showChoices(choices) {
        clearChoices();

        const panel = document.createElement("div");
        panel.className = "game-choices";
        panel.id = "game-choices-panel";

        /* Flatten choices into indexed options (matches game_driver.py _show_choices) */
        let optIndex = 0;
        const flatOpts = [];
        for (const choice of choices) {
            const labels = choice.labels || [];
            const enabled = choice.enabled || labels.map(() => true);
            for (let i = 0; i < labels.length; i++) {
                optIndex++;
                flatOpts.push({
                    key: String(optIndex),
                    label: labels[i],
                    enabled: i < enabled.length ? enabled[i] : true,
                    branch: (choice.branches && choice.branches[i]) || null,
                });
            }
        }

        /* Build buttons */
        for (const opt of flatOpts) {
            const btn = document.createElement("button");
            btn.className = "game-choice-btn";
            btn.textContent = `[${opt.key}] ${opt.label}`;
            if (!opt.enabled) {
                btn.disabled = true;
                btn.textContent += " (不可用)";
            }
            btn.addEventListener("click", () => {
                if (!opt.enabled) return;
                _choiceResolve(opt.key);
            });
            panel.appendChild(btn);
        }

        /* Append below story area */
        const story = $("#game-story");
        if (story) {
            story.parentNode.insertBefore(panel, story.nextSibling);
        }

        scrollToBottom();

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
     *  @param {Function} onRetry — called when user clicks "重试"
     *  @param {Function} onQuit — called when user clicks "退出" */
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
                        重试
                    </button>
                    <button class="game-modal-btn" id="game-modal-secondary">
                        退出
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
     *  @param {string} primaryLabel — label for primary button (e.g. "开始查看")
     *  @param {string} quitLabel — label for quit button (e.g. "退出") */
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
                        ${escHtml(primaryLabel || "确定")}
                    </button>
                    <button class="game-modal-btn" id="game-modal-secondary">
                        ${escHtml(quitLabel || "退出")}
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

    /** Show the in-game settings overlay.
     *  @param {Function} getSpeed — () → current speed preset (1, 2, or 4)
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

        const speedOpts = [
            { val: 1, label: "1x" },
            { val: 2, label: "2x" },
            { val: 4, label: "4x" },
        ];
        const fontOpts = [
            { val: "small", label: "小" },
            { val: "medium", label: "中" },
            { val: "large", label: "大" },
        ];
        const lineOpts = [
            { val: 0.75, label: "0.75" },
            { val: 1.0, label: "1.0" },
            { val: 1.25, label: "1.25" },
        ];

        function renderOpts(opts, current, onChange) {
            return opts.map(o => {
                const active = o.val === current ? " active" : "";
                return `<button class="game-setting-opt${active}" data-val="${o.val}">${o.label}</button>`;
            }).join("");
        }

        overlay.innerHTML = `
            <div class="game-settings-panel">
                <h2>设置</h2>
                <div class="game-setting-row">
                    <span class="game-setting-label">生成速度</span>
                    <div class="game-setting-options" id="setting-speed">
                        ${renderOpts(speedOpts, getSpeed(), onSpeed)}
                    </div>
                </div>
                <div class="game-setting-row">
                    <span class="game-setting-label">字体大小</span>
                    <div class="game-setting-options" id="setting-font">
                        ${renderOpts(fontOpts, getFont(), onFont)}
                    </div>
                </div>
                <div class="game-setting-row">
                    <span class="game-setting-label">行间距</span>
                    <div class="game-setting-options" id="setting-line">
                        ${renderOpts(lineOpts, getLine(), onLine)}
                    </div>
                </div>
                <button class="menu-btn game-settings-close" id="btn-game-settings-close">
                    关闭
                </button>
            </div>
        `;

        document.body.appendChild(overlay);

        /* Bind option clicks */
        overlay.querySelector("#setting-speed").addEventListener("click", (e) => {
            const btn = e.target.closest(".game-setting-opt");
            if (!btn) return;
            const val = Number(btn.dataset.val);
            onSpeed(val);
            /* Refresh options */
            overlay.querySelector("#setting-speed").innerHTML =
                renderOpts(speedOpts, getSpeed(), onSpeed);
        });

        overlay.querySelector("#setting-font").addEventListener("click", (e) => {
            const btn = e.target.closest(".game-setting-opt");
            if (!btn) return;
            const val = btn.dataset.val;
            onFont(val);
            overlay.querySelector("#setting-font").innerHTML =
                renderOpts(fontOpts, getFont(), onFont);
        });

        overlay.querySelector("#setting-line").addEventListener("click", (e) => {
            const btn = e.target.closest(".game-setting-opt");
            if (!btn) return;
            const val = Number(btn.dataset.val);
            onLine(val);
            overlay.querySelector("#setting-line").innerHTML =
                renderOpts(lineOpts, getLine(), onLine);
        });

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

    function scrollToBottom() {
        const story = $("#game-story");
        if (story) {
            requestAnimationFrame(() => {
                story.scrollTop = story.scrollHeight;
            });
        }
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
        clearChoices,
        showLoading,
        hideLoading,
        showContinueHint,
        hideContinueHint,
        showErrorModal,
        showEndModal,
        closeModal,
        showSettings,
        closeSettings,
        scrollToBottom,
    };
})();
