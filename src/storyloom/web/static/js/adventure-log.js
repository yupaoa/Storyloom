/* ═══════════════════════════════════════════════════════════════════
   adventure-log.js — Adventure Log View Controller

   Renders the post-ending adventure log in a scrollable text page.
   Route: #adventure-log/{gameId}

   Flow:
     1. render(container, gameId, label) — build DOM, start polling
     2. _fetchLog() → GET /api/game/{id}/adventure-log
        → "ok"      → display text
        → "pending" → retry after 1s
        → "error"   → show error message
     3. Back button → Router.navigate("menu")

   Authority:
     exec-flow.md §5.2 (natural ending → display adventure log)
     exec-flow.md §5.3 (active exit → UI confirmation → display)
     dev_cli/game_driver.py:309-340 (reference: get_adventure_log → print → return)
     server.py:524-540 (GET /api/game/{id}/adventure-log)
     CLAUDE.local.md §3.1 (UI territory)
   ═══════════════════════════════════════════════════════════════════ */

const AdventureLogView = (function () {
    let _container = null;
    let _gameId = null;
    let _pollTimer = null;
    let _pollCount = 0;
    const MAX_POLL_RETRIES = 30;    // 30 s timeout — matches dev_cli 30 s

    /** HTML entity escape (same pattern as display.js, router.js). */
    function escHtml(s) {
        const d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }

    function $(sel) { return _container ? _container.querySelector(sel) : null; }

    /* ═══════════════════════════════════════════════════════════════
       Public API
       ═══════════════════════════════════════════════════════════════ */

    /** Render the adventure log view.
     *  @param {Element} container — DOM element to render into
     *  @param {string} gameId
     *  @param {string} label — story name for the top bar */
    function render(container, gameId, label) {
        _container = container;
        _gameId = gameId;

        _buildDOM(label);
        _fetchLog();
    }

    /* ═══════════════════════════════════════════════════════════════
       DOM Construction
       ═══════════════════════════════════════════════════════════════ */

    function _buildDOM(label) {
        _container.innerHTML = `
            <div class="al-view">
                <!-- Top bar -->
                <div class="al-header">
                    <button class="cc-back-btn" id="al-back"
                            title="${_("Back to Menu")}">${Icons.arrowLeft()}</button>
                    <span class="al-label">${escHtml(label)}</span>
                    <button class="al-export-btn" id="al-export" disabled>
                        ${_("Export")}
                    </button>
                </div>

                <!-- Scrollable log content area -->
                <div class="al-content" id="al-content">
                    <p class="al-loading">${_("Loading...")}</p>
                </div>
            </div>
        `;

        /* ── Back button → return to main menu ──────────────────── */
        $("#al-back").addEventListener("click", () => {
            _cleanup();
            GameState.reset();
            if (typeof SSEClient !== "undefined" && SSEClient.close) {
                SSEClient.close();
            }
            Router.navigate("menu");
        });
    }

    /* ═══════════════════════════════════════════════════════════════
       API Fetch & Polling
       ═══════════════════════════════════════════════════════════════ */

    /** Fetch adventure log from server.  Polls on "pending" status
     *  with 1 s interval — mirrors dev_cli's get_adventure_log(timeout)
     *  pattern, adapted for async web UI.
     *
     *  Rendering: if marked.js loaded (CDN), parse Markdown → HTML;
     *  otherwise fall back to raw text with white-space: pre-wrap. */
    async function _fetchLog() {
        const content = document.getElementById("al-content");
        if (!content) return;

        try {
            const data = await API.get(
                `/api/game/${encodeURIComponent(_gameId)}/adventure-log`
            );

            if (data.status === "ok" && data.text) {
                /* Engine generates Markdown (game_loop.py:1548).
                   Progressive enhancement: render as HTML when marked.js
                   is available, plain pre-wrap text otherwise. */
                if (typeof marked !== "undefined") {
                    const html = marked.parse(data.text);
                    content.innerHTML = `<div class="al-text">${html}</div>`;
                } else {
                    content.innerHTML = `<div class="al-text al-text--raw">${escHtml(data.text)}</div>`;
                }
                return;
            }

            if (data.status === "pending") {
                /* Still generating — retry with backstop.
                   Matches dev_cli "[Adventure log still generating...]"
                   followed by another get_adventure_log() call.
                   MAX_POLL_RETRIES prevents infinite polling if the
                   LLM API hangs. */
                if (_pollCount >= MAX_POLL_RETRIES) {
                    content.innerHTML = `<p class="al-error">${_("Adventure log timed out.")}</p>`;
                    return;
                }
                _pollCount++;
                content.innerHTML = `<p class="al-loading">${_("Generating adventure log...")}</p>`;
                _pollTimer = setTimeout(_fetchLog, 1000);
                return;
            }

            /* data.status === "error" */
            content.innerHTML = `<p class="al-error">${escHtml(data.message || _("Something went wrong"))}</p>`;
        } catch (err) {
            content.innerHTML = `<p class="al-error">${escHtml(err?.message || String(err))}</p>`;
        }
    }

    /* ═══════════════════════════════════════════════════════════════
       Cleanup
       ═══════════════════════════════════════════════════════════════ */

    /** Cancel any pending poll timer.  Called on back navigation. */
    function _cleanup() {
        if (_pollTimer) {
            clearTimeout(_pollTimer);
            _pollTimer = null;
        }
        _pollCount = 0;
    }

    /* ── Export ──────────────────────────────────────────────────── */
    return { render };
})();
