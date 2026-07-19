/* ═══════════════════════════════════════════════════════════════════
   co-create.js — Co-Creation chat UI module

   Lifecycle:
     1. CoCreateView.render(container) — builds DOM, calls /start,
        shows the LLM's opening question.
     2. User types messages → send → /api/co-create/send → display reply.
     3. User clicks /go → confirm dialog → generate → game/new → #game/{id}.
     4. User clicks /quit → confirm dialog → abort → #menu.

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
    let _phase = "loading";   // loading | chatting | generating | done
    let _sendRetry = false;   // true → call retry-send instead of send
    let _genRetry = false;    // true → call retry-generate instead of generate

    /* ── DOM helpers ─────────────────────────────────────────────── */

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
        _sendRetry = false;
        _genRetry = false;

        _container.innerHTML = `
            <div class="co-create-view">
                <!-- Header: ← back | title | Start -->
                <div class="cc-header">
                    <button class="cc-back-btn" id="cc-back" title="${esc(_("Back to Menu"))}">←</button>
                    <span class="cc-title">${esc(_("Co-Create"))}</span>
                    <button class="cc-start-btn" id="cc-start" disabled>${esc(_("Start"))}</button>
                </div>

                <!-- Messages -->
                <div class="cc-messages" id="cc-messages"></div>

                <!-- Input bar: rounded container wrapping input + circular send button -->
                <div class="cc-input-bar">
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
        try {
            const data = await API.post("/api/co-create/start");
            _clearMessages();
            _addMessage("assistant", data.prompt);
            _phase = "chatting";
            _setInputEnabled(true);
            _updatePlaceholder();
            _focusInput();
        } catch (err) {
            _clearMessages();
            _showFatalError(err.message);
        }
    }

    /* ── Event bindings ──────────────────────────────────────────── */

    function _bindEvents() {
        $("cc-send").addEventListener("click", _handleSend);

        // Enter to send, Shift+Enter / Ctrl+Enter / Cmd+Enter for newline
        $("cc-input").addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                _handleSend();
            }
        });

        // Auto-resize textarea
        $("cc-input").addEventListener("input", () => {
            _autoResize($("cc-input"));
        });

        $("cc-back").addEventListener("click", _handleQuit);
        $("cc-start").addEventListener("click", _handleGo);
    }

    /* ── Send message ────────────────────────────────────────────── */

    async function _handleSend() {
        if (_phase !== "chatting") return;

        const input = $("cc-input");
        const text = input.value.trim();
        if (!text) return;

        /* ── First send (not a retry): show user message + call send ── */
        if (!_sendRetry) {
            _addMessage("user", text);
        }
        input.value = "";
        _autoResize(input);
        _setInputEnabled(false);
        _showTyping();

        try {
            const endpoint = _sendRetry
                ? "/api/co-create/retry-send"
                : "/api/co-create/send";
            const body = _sendRetry ? {} : { text };
            const data = await API.post(endpoint, body);

            _hideTyping();
            _addMessage("assistant", data.reply);
            _sendRetry = false;
            _setInputEnabled(true);
            _updatePlaceholder();
            _focusInput();
        } catch (err) {
            _hideTyping();
            // 502 = CoCreateError → retriable (mirrors dev_cli)
            if (err.status === 502) {
                _addErrorWithRetry(err.message, () => {
                    _sendRetry = true;
                    _handleSend();
                });
            } else {
                _showFatalError(err.message);
            }
            _setInputEnabled(true);
            _focusInput();
        }
    }

    /* ── /go — generate & start game ─────────────────────────────── */

    async function _handleGo() {
        if (_phase !== "chatting") return;

        const confirmed = await _showConfirm(
            _("Start the game?"),
            _("This will generate the story setup based on our conversation and begin the adventure.")
        );
        if (!confirmed) return;

        _phase = "generating";
        _setInputEnabled(false);
        _addMessage("info", _("Generating story setup..."));
        _scrollToBottom();

        // Step 1: Generate (or retry-generate)
        try {
            const endpoint = _genRetry
                ? "/api/co-create/retry-generate"
                : "/api/co-create/generate";
            await API.post(endpoint);
            _genRetry = false;
        } catch (err) {
            // 502 = CoCreateError → retriable (mirrors dev_cli)
            if (err.status === 502) {
                _addErrorWithRetry(err.message, () => {
                    _genRetry = true;
                    _handleGo();
                });
            } else {
                _showFatalError(err.message);
            }
            _phase = "chatting";
            _setInputEnabled(true);
            return;
        }

        // Step 2: Create game
        try {
            const data = await API.post("/api/game/new");
            _phase = "done";
            GameState.gameId = data.game_id;
            GameState.roundCount = data.round_count || 0;
            GameState.currentNode = data.current_node || null;
            Router.navigate(`game/${data.game_id}`);
        } catch (err) {
            _showFatalError(err.message);
        }
    }

    /* ── /quit — abort & return to menu ──────────────────────────── */

    async function _handleQuit() {
        const confirmed = await _showConfirm(
            _("Quit co-creation?"),
            _("Your conversation will be lost. Are you sure?")
        );
        if (!confirmed) return;

        // Best-effort abort — navigate regardless of result
        try { await API.post("/api/co-create/abort"); } catch (_) { /* ok */ }
        _phase = "done";
        Router.navigate("menu");
    }

    /* ── Confirm dialog ──────────────────────────────────────────── */

    function _showConfirm(title, message) {
        return new Promise((resolve) => {
            const overlay = document.createElement("div");
            overlay.className = "cc-confirm-overlay";
            overlay.innerHTML = `
                <div class="cc-confirm-box">
                    <h3>${esc(title)}</h3>
                    <p>${esc(message)}</p>
                    <div class="cc-confirm-buttons">
                        <button class="cc-confirm-yes" id="cc-confirm-yes">
                            ${esc(_("Yes"))}
                        </button>
                        <button class="cc-confirm-no" id="cc-confirm-no">
                            ${esc(_("No"))}
                        </button>
                    </div>
                </div>
            `;

            document.body.appendChild(overlay);

            const cleanup = () => overlay.remove();

            overlay.querySelector("#cc-confirm-yes").addEventListener("click", () => {
                cleanup();
                resolve(true);
            });
            overlay.querySelector("#cc-confirm-no").addEventListener("click", () => {
                cleanup();
                resolve(false);
            });
            overlay.addEventListener("click", (e) => {
                if (e.target === overlay) { cleanup(); resolve(false); }
            });

            const onKey = (e) => {
                if (e.key === "Escape") {
                    cleanup();
                    document.removeEventListener("keydown", onKey);
                    resolve(false);
                }
            };
            document.addEventListener("keydown", onKey);
        });
    }

    /* ── Message rendering ───────────────────────────────────────── */

    function _addMessage(role, text) {
        const msgs = $("cc-messages");
        const div = document.createElement("div");
        div.className = `cc-message ${role}`;
        div.textContent = text;
        msgs.appendChild(div);
        _scrollToBottom();
    }

    function _showTyping() {
        const msgs = $("cc-messages");
        const el = document.createElement("div");
        el.className = "cc-typing";
        el.id = "cc-typing-indicator";
        el.textContent = "...";
        msgs.appendChild(el);
        _scrollToBottom();
    }

    function _hideTyping() {
        const el = $("cc-typing-indicator");
        if (el) el.remove();
    }

    function _clearMessages() {
        const msgs = $("cc-messages");
        if (msgs) msgs.innerHTML = "";
    }

    /** Error message + Retry button in a single bubble. */
    function _addErrorWithRetry(message, retryHandler) {
        const msgs = $("cc-messages");
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
        const msgs = $("cc-messages");
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
        const input = $("cc-input");
        const sendBtn = $("cc-send");
        const startBtn = $("cc-start");
        if (input) input.disabled = !enabled;
        if (sendBtn) sendBtn.disabled = !enabled;
        if (startBtn) startBtn.disabled = !enabled;
    }

    function _focusInput() {
        const input = $("cc-input");
        if (input && !input.disabled) {
            input.focus();
        }
    }

    function _autoResize(textarea) {
        textarea.style.height = "auto";
        textarea.style.height = Math.min(textarea.scrollHeight, 128) + "px";
    }

    function _updatePlaceholder() {
        const input = $("cc-input");
        if (!input) return;
        const msgs = $("cc-messages");
        const userCount = msgs
            ? msgs.querySelectorAll(".cc-message.user").length
            : 0;
        input.placeholder = userCount === 0
            ? _("Type your story idea...")
            : _("Type your answer...");
    }

    function _scrollToBottom() {
        const msgs = $("cc-messages");
        if (msgs) {
            requestAnimationFrame(() => {
                msgs.scrollTop = msgs.scrollHeight;
            });
        }
    }

    /* ── Export ──────────────────────────────────────────────────── */
    return { render };
})();
