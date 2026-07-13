/* ═══════════════════════════════════════════════════════════════════
   sse-client.js — SSE consumer + choice injection
   ═══════════════════════════════════════════════════════════════════ */

const SSEClient = {
    _es: null,
    _handlers: {},
    _resolve: null,  // stored so close() can resolve the connect Promise

    /**
     * Open an SSE connection to /api/game/{gameId}/stream.
     *
     * Returns a Promise that resolves ("closed" | "ending") when the
     * stream ends, either via manual close() or server-side completion.
     */
    connect(gameId, handlers) {
        this._handlers = handlers;

        if (this._es) {
            this._es.close();
            this._es = null;
        }

        const url = `/api/game/${gameId}/stream`;
        this._es = new EventSource(url);

        const EVENT_TYPES = [
            "story_begin", "story_end", "token", "segment", "bridge",
            "options", "state", "error", "ending", "done", "round_complete"
        ];

        return new Promise((resolve) => {
            this._resolve = resolve;

            for (const etype of EVENT_TYPES) {
                this._es.addEventListener(etype, (e) => {
                    if (!e.data || !e.data.trim()) return;

                    let data;
                    try {
                        data = JSON.parse(e.data);
                    } catch (err) {
                        console.error(`SSE JSON parse error for "${etype}":`, err, e.data);
                        return;
                    }

                    const h = this._handlers[etype];
                    if (h) {
                        try {
                            h(data, etype);
                        } catch (err) {
                            console.error(`Handler error for "${etype}":`, err);
                        }
                    }
                });
            }

            this._es.onerror = () => {
                // EventSource auto-reconnects on network errors.
                // Manual close() → _es is null, skip.
                // Server closes cleanly → readyState === CLOSED.
                if (this._es && this._es.readyState === EventSource.CLOSED) {
                    this._resolve("closed");
                    this._resolve = null;
                }
            };
        });
    },

    /** Send a choice key (1-indexed string "1", "2", ...). */
    async sendChoice(gameId, key) {
        await API.post(`/api/game/${gameId}/choice`, { key: String(key) });
    },

    /** Close the SSE connection and resolve the connect Promise. */
    close() {
        if (this._es) {
            this._es.close();
            this._es = null;
        }
        // Resolve manually — onerror may not fire after close()
        if (this._resolve) {
            this._resolve("closed");
            this._resolve = null;
        }
    },
};
