/* ═══════════════════════════════════════════════════════════════════
   co-create.js — Co-Creation chat UI module

   Lifecycle:
     1. CoCreateView.render(container) — builds DOM, calls /start,
        shows the LLM's opening question.
     2. User chats with LLM — multi-turn Q&A.
     3. User clicks ← → abort → #menu.

   Phase gating:
     - Back button (←) and Start button only active during "chatting".
     - All other phases (loading, done) → buttons are silent.

   Error handling (mirrors dev_cli/game_driver.py run_co_create):
     - CoCreateError → show error + Retry button → call retry endpoint
     - RuntimeError / ValueError → fatal, show error with Back to Menu

   Authority:
     dev_cli/game_driver.py (co-creation driver — authoritative reference)
     src/storyloom/core/co_create.py (CoCreateFlow API)
     CLAUDE.local.md §3.2 (API consumption)
   ═══════════════════════════════════════════════════════════════════ */

const CoCreateView = (function () {
    /* ── Internal state ──────────────────────────────────────────── */
    let _container = null;
    let _phase = "loading";   // loading | chatting | done

    /* ── DOM helpers ─────────────────────────────────────────────── */

    /** Shortcut for _container.querySelector(sel).
     *  sel MUST be a valid CSS selector: "#id" for IDs, ".class" for classes. */
    function $(sel) { return _container.querySelector(sel); }

    function esc(s) {
        const d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }

    /* ── Public API ──────────────────────────────────────────────── */

    /** Render the co-creation chat view into *container*.
     *  Kicks off POST /api/co-create/start and shows the opening prompt. */
    async function render(container) {
        _container = container;
        _phase = "loading";

        _container.innerHTML = `
            <div class="co-create-view">
                <!-- Header: ← back | title | Start -->
                <div class="cc-header">
                    <button class="cc-back-btn" id="cc-back"
                            title="${esc(_("Back to Menu"))}" disabled>←</button>
                    <span class="cc-title">${esc(_("Co-Create"))}</span>
                    <button class="cc-start-btn" id="cc-start" disabled>${esc(_("Start"))}</button>
                </div>

                <!-- Messages -->
                <div class="cc-messages" id="cc-messages"></div>

                <!-- Input bar: rounded container wrapping input + circular send button -->
                <div class="cc-input-bar" id="cc-input-bar">
                    <div class="cc-input-wrap">
                        <textarea class="cc-input" id="cc-input"
                                  placeholder="${esc(_("Type your story idea..."))}"
                                  rows="1"></textarea>
                        <button class="cc-send-btn" id="cc-send"
                                title="${esc(_("Send"))}" disabled>↑</button>
                    </div>
                </div>
            </div>
        `;

        _bindEvents();

        // Call /start — get opening prompt
        _showTyping();
        try {
            const data = await API.post("/api/co-create/start");
            _hideTyping();
            _clearMessages();
            _addMessage("assistant", data.prompt);
            _phase = "chatting";
            _setInputEnabled(true);
            _updatePlaceholder();
            _focusInput();
        } catch (err) {
            _hideTyping();
            _clearMessages();
            _showFatalError(err.message);
        }
    }

    /* ── Event bindings ──────────────────────────────────────────── */

    function _bindEvents() {
        $("#cc-send").addEventListener("click", _handleSend);

        // Enter to send, Shift+Enter / Ctrl+Enter / Cmd+Enter for newline
        $("#cc-input").addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                _handleSend();
            }
        });

        // Auto-resize textarea
        $("#cc-input").addEventListener("input", () => {
            _autoResize($("#cc-input"));
        });

        $("#cc-back").addEventListener("click", _handleBack);
        $("#cc-start").addEventListener("click", _handleStart);
    }

    /* ── Back button — follows same gating as Start (via _setInputEnabled) ── */

    async function _handleBack() {
        if (_phase !== "chatting") return;

        // Immediate abort, no confirmation (matches dev_cli /quit)
        try { await API.post("/api/co-create/abort"); } catch (_) { /* ok */ }
        _phase = "done";
        Router.navigate("menu");
    }

    /* ── Start button — Phase 1: generate story setup ────────────── */

    async function _handleStart() {
        if (_phase !== "chatting") return;

        _phase = "generating";
        _setInputEnabled(false);
        _renderTransition();

        try {
            // Step 1: Generate story setup (co_create.py generate)
            const genData = await API.post("/api/co-create/generate");

            // Step 2: Store story config for the preview page
            GameState.storyConfig = genData.story_config;

            // Step 3: Navigate to the game preview (transition) page
            _phase = "done";
            Router.navigate("game-preview");
        } catch (err) {
            if (err.status === 502) {
                // CoCreateError — retriable (generate or generate_parse failure)
                _renderTransitionError(err.message, _retryGenerate);
            } else {
                _renderTransitionFatal(err.message);
            }
        }
    }

    /** Retry generation after a CoCreateError. */
    async function _retryGenerate() {
        _phase = "generating";
        _renderTransition();

        try {
            // Step 1: Retry generate
            const genData = await API.post("/api/co-create/retry-generate");

            // Step 2: Store story config for the preview page
            GameState.storyConfig = genData.story_config;

            // Step 3: Navigate to the game preview (transition) page
            _phase = "done";
            Router.navigate("game-preview");
        } catch (err) {
            if (err.status === 502) {
                _renderTransitionError(err.message, _retryGenerate);
            } else {
                _renderTransitionFatal(err.message);
            }
        }
    }

    /* ── Transition phase rendering ────────────────────────────────── */

    /** Render the centered transition screen with animated dots.
     *  Reuses the existing cc-dots / cc-bounce animation design. */
    function _renderTransition() {
        _container.innerHTML = `
            <div class="cc-transition">
                <div class="cc-transition-text">
                    <span>${esc(_("Generating settings"))}</span>
                    <span class="cc-dots">
                        <span>.</span><span>.</span><span>.</span>
                    </span>
                </div>
            </div>
        `;
    }

    /** Transition screen with error + Retry button. */
    function _renderTransitionError(message, retryHandler) {
        _container.innerHTML = `
            <div class="cc-transition">
                <div class="cc-transition-text" style="font-size:1.4rem; color:var(--text-error); margin-bottom:1.5rem;">
                    ${esc(message)}
                </div>
                <button class="menu-btn" id="cc-transition-retry">${esc(_("Retry"))}</button>
            </div>
        `;
        document.getElementById("cc-transition-retry").addEventListener("click", () => {
            retryHandler();
        });
    }

    /** Transition screen with fatal error + Back to Menu button. */
    function _renderTransitionFatal(message) {
        _phase = "done";
        _container.innerHTML = `
            <div class="cc-transition">
                <div class="cc-transition-text" style="font-size:1.4rem; color:var(--text-error); margin-bottom:1.5rem;">
                    ${esc(message)}
                </div>
                <button class="menu-btn" id="cc-transition-back">${esc(_("Back to Menu"))}</button>
            </div>
        `;
        document.getElementById("cc-transition-back").addEventListener("click", () => {
            Router.navigate("menu");
        });
    }

    /* ── Send message ─────────────────────────────────────────────── */

    async function _handleSend() {
        if (_phase !== "chatting") return;

        const input = $("#cc-input");
        const text = input.value.trim();
        if (!text) return;

        // ── Normal message → send to LLM ──────────────────────────
        _addMessage("user", text);
        input.value = "";
        _autoResize(input);
        _setInputEnabled(false);
        _showTyping();

        try {
            const data = await API.post("/api/co-create/send", { text });
            _hideTyping();
            _addMessage("assistant", data.reply);
            _setInputEnabled(true);
            _updatePlaceholder();
            _focusInput();
        } catch (err) {
            _hideTyping();
            // 502 = CoCreateError → retriable (mirrors dev_cli)
            if (err.status === 502) {
                _addErrorWithRetry(err.message, _retrySend);
            } else {
                _showFatalError(err.message);
            }
            _setInputEnabled(true);
            _focusInput();
        }
    }

    /** Self-contained retry — calls retry-send directly, no input dependency. */
    async function _retrySend() {
        _setInputEnabled(false);
        _showTyping();
        try {
            const data = await API.post("/api/co-create/retry-send");
            _hideTyping();
            _addMessage("assistant", data.reply);
            _setInputEnabled(true);
            _focusInput();
        } catch (err) {
            _hideTyping();
            if (err.status === 502) {
                _addErrorWithRetry(err.message, _retrySend);
            } else {
                _showFatalError(err.message);
            }
            _setInputEnabled(true);
            _focusInput();
        }
    }

    /* ── Message rendering ───────────────────────────────────────── */

    function _addMessage(role, text) {
        const msgs = $("#cc-messages");
        if (!msgs) return;
        const div = document.createElement("div");
        div.className = `cc-message ${role}`;
        div.textContent = text;
        msgs.appendChild(div);
        _scrollToBottom();
    }

    /** Show typing indicator with animated bouncing dots. */
    function _showTyping() {
        const msgs = $("#cc-messages");
        if (!msgs) return;
        const el = document.createElement("div");
        el.className = "cc-typing";
        el.id = "cc-typing-indicator";
        el.innerHTML = `<span>${esc(_("Thinking"))}</span><span class="cc-dots"><span>.</span><span>.</span><span>.</span></span>`;
        msgs.appendChild(el);
        _scrollToBottom();
    }

    function _hideTyping() {
        const el = $("#cc-typing-indicator");
        if (el) el.remove();
    }

    function _clearMessages() {
        const msgs = $("#cc-messages");
        if (msgs) msgs.innerHTML = "";
    }

    /** Error message + Retry button in a single bubble. */
    function _addErrorWithRetry(message, retryHandler) {
        const msgs = $("#cc-messages");
        if (!msgs) return;
        const div = document.createElement("div");
        div.className = "cc-message error";
        div.textContent = message;

        const btn = document.createElement("button");
        btn.className = "menu-btn";
        btn.style.marginTop = "0.5rem";
        btn.textContent = _("Retry");
        btn.addEventListener("click", () => {
            div.remove();
            retryHandler();
        });
        div.appendChild(btn);
        msgs.appendChild(div);
        _scrollToBottom();
    }

    /** Fatal error — show message with Back to Menu button. */
    function _showFatalError(message) {
        _phase = "done";
        _setInputEnabled(false);
        const msgs = $("#cc-messages");
        if (!msgs) return;
        const div = document.createElement("div");
        div.className = "cc-message error";
        div.textContent = message;

        const btn = document.createElement("button");
        btn.className = "menu-btn";
        btn.style.marginTop = "0.5rem";
        btn.textContent = _("Back to Menu");
        btn.addEventListener("click", () => {
            Router.navigate("menu");
        });
        div.appendChild(btn);
        msgs.appendChild(div);
        _scrollToBottom();
    }

    /* ── Input helpers ────────────────────────────────────────────── */

    function _setInputEnabled(enabled) {
        const input = $("#cc-input");
        const sendBtn = $("#cc-send");
        const backBtn = $("#cc-back");
        const startBtn = $("#cc-start");
        if (input) input.disabled = !enabled;
        if (sendBtn) sendBtn.disabled = !enabled;
        if (backBtn) backBtn.disabled = !enabled;
        if (startBtn) startBtn.disabled = !enabled;
    }

    function _focusInput() {
        const input = $("#cc-input");
        if (input && !input.disabled) {
            input.focus();
        }
    }

    function _autoResize(textarea) {
        if (!textarea) return;
        textarea.style.height = "auto";
        textarea.style.height = Math.min(textarea.scrollHeight, 128) + "px";
    }

    function _updatePlaceholder() {
        const input = $("#cc-input");
        if (!input) return;
        const msgs = $("#cc-messages");
        const userCount = msgs
            ? msgs.querySelectorAll(".cc-message.user").length
            : 0;
        input.placeholder = userCount === 0
            ? _("Type your story idea...")
            : _("Type your answer...");
    }

    function _scrollToBottom() {
        const msgs = $("#cc-messages");
        if (msgs) {
            requestAnimationFrame(() => {
                msgs.scrollTop = msgs.scrollHeight;
            });
        }
    }

    /* ── Export ──────────────────────────────────────────────────── */
    return { render };
})();
