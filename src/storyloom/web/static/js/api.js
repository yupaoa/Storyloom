/* ═══════════════════════════════════════════════════════════════════
   api.js — HTTP / fetch helpers
   ═══════════════════════════════════════════════════════════════════ */

const API = {
    /**
     * POST JSON to an endpoint.  Returns the parsed response body.
     * Throws on non-2xx status with the server error message.
     */
    async post(url, body = {}) {
        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || `HTTP ${res.status}`);
        }
        return data;
    },

    /**
     * GET JSON from an endpoint.
     */
    async get(url) {
        const res = await fetch(url);
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || `HTTP ${res.status}`);
        }
        return data;
    },

    /**
     * DELETE request.  Returns parsed JSON or null on 404.
     */
    async del(url) {
        const res = await fetch(url, { method: "DELETE" });
        if (res.status === 404) return null;
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || `HTTP ${res.status}`);
        }
        return data;
    },
};
