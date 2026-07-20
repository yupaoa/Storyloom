/* ═══════════════════════════════════════════════════════════════════
   sse-client.js — SSE consumer + choice injection

   Connects to GET /api/game/{id}/stream and dispatches events to
   registered handlers.  Exports:
     SSEClient.connect(gameId, handlers) → Promise
       handlers: { segment, bridge, options, state, error,
                   ending, done, story_begin, story_end, token }
     SSEClient.sendChoice(gameId, key)   → POST /choice
     SSEClient.retry(gameId)             → POST /retry
     SSEClient.close()                   → close EventSource
     SSEClient.resume(gameId, handlers)  → re-connect after choice

   Authority:
     exec-flow.md §4.1 (event types), §4.5 (queue buffer)
     dev_cli/game_driver.py (event consumption reference)
     server.py /api/game/{id}/stream (SSE endpoint)
   ═══════════════════════════════════════════════════════════════════ */

const SSEClient = {
    _es: null,
    _gameId: null,
    _handlers: null,

    /** Connect to the game SSE stream.
     *  @param {string} gameId
     *  @param {object} handlers — { segment, bridge, options, state,
     *      error, ending, done, story_begin, story_end, token }
     *  @returns {Promise} resolves when stream closes normally or on error */
    connect(gameId, handlers) {
        /* Close any existing connection before opening a new one.
           Prevents duplicate EventSource instances when retrying
           after an error — the old EventSource may still be
           auto-reconnecting (readyState === CONNECTING). */
        this.close();

        this._gameId = gameId;
        this._handlers = handlers;

        const url = `/api/game/${encodeURIComponent(gameId)}/stream`;
        this._es = new EventSource(url);

        return new Promise((resolve, reject) => {
            this._es.onerror = () => {
                /* EventSource auto-reconnects on connection loss.
                   We let the handlers deal with the stream state. */
                if (this._es.readyState === EventSource.CLOSED) {
                    resolve("closed");
                }
                /* CLOSED (2) = permanent close; CONNECTING (0) = auto-retry */
            };

            /* ── Event dispatchers ──────────────────────────────── */

            this._es.addEventListener("token", (e) => {
                const data = JSON.parse(e.data);
                if (this._handlers.token) this._handlers.token(data);
            });

            this._es.addEventListener("segment", (e) => {
                const data = JSON.parse(e.data);
                if (this._handlers.segment) this._handlers.segment(data);
            });

            this._es.addEventListener("bridge", (e) => {
                if (this._handlers.bridge) this._handlers.bridge({});
            });

            this._es.addEventListener("options", (e) => {
                const data = JSON.parse(e.data);
                if (this._handlers.options) this._handlers.options(data);
            });

            this._es.addEventListener("state", (e) => {
                const data = JSON.parse(e.data);
                if (this._handlers.state) this._handlers.state(data);
            });

            this._es.addEventListener("error", (e) => {
                const data = JSON.parse(e.data);
                if (this._handlers.error) this._handlers.error(data);
            });

            this._es.addEventListener("ending", (e) => {
                const data = JSON.parse(e.data);
                if (this._handlers.ending) this._handlers.ending(data);
            });

            this._es.addEventListener("done", (e) => {
                const data = JSON.parse(e.data);
                if (this._handlers.done) this._handlers.done(data);
            });

            this._es.addEventListener("story_begin", () => {
                if (this._handlers.story_begin) this._handlers.story_begin({});
            });

            this._es.addEventListener("story_end", () => {
                if (this._handlers.story_end) this._handlers.story_end({});
            });

            /* ── Stream complete — sent by server when round ends ── */
            this._es.addEventListener("stream_end", () => {
                this._es.close();
                resolve("stream_end");
            });
        });
    },

    /** Resume the SSE stream after a choice was sent.
     *  The server continues the generator after gen.send(key). */
    async resume(gameId, handlers) {
        /* Close any existing connection, then re-connect.
           The server-side generator resumes from where gen.send() left off. */
        this.close();
        return this.connect(gameId, handlers);
    },

    /** Inject a player choice into the running game loop.
     *  POST /api/game/{id}/choice — the server calls gen.send(key). */
    async sendChoice(gameId, key) {
        return API.post(`/api/game/${encodeURIComponent(gameId)}/choice`, { key });
    },

    /** Retry after an API error.
     *  POST /api/game/{id}/retry — the server retries the failed API call. */
    async retry(gameId) {
        return API.post(`/api/game/${encodeURIComponent(gameId)}/retry`);
    },

    /** Close the EventSource connection. */
    close() {
        if (this._es) {
            this._es.close();
            this._es = null;
        }
        this._gameId = null;
        this._handlers = null;
    },
};
