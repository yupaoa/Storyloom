/* ═══════════════════════════════════════════════════════════════════
   sse-client.js — SSE consumer + choice injection

   Connects to GET /api/game/{id}/stream and dispatches events to
   registered handlers.  Exports:
     SSEClient.connect(gameId, handlers) → Promise
       handlers: { token, segment, bridge, options, state, error,
                   ending, done, story_begin, story_end, round_complete }
     SSEClient.sendChoice(gameId, key)   → POST /choice
     SSEClient.close()                   → close EventSource
   ═══════════════════════════════════════════════════════════════════ */

const SSEClient = {
    // EventSource instance
    // connect(gameId, handlers) → Promise<"closed" | "ending">
    // sendChoice(gameId, key)
    // close()
};
