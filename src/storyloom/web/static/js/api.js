/* ═══════════════════════════════════════════════════════════════════
   api.js — HTTP fetch helpers

   Thin wrappers around fetch() for JSON APIs.
   Exports (window.API):
     API.post(url, body) → parsed JSON response (throws on non-2xx)
     API.get(url)        → parsed JSON response
     API.del(url)        → parsed JSON response (null on 404)

   Authority: CLAUDE.local.md §3.2 (API consumption).
   ═══════════════════════════════════════════════════════════════════ */

const API = {
    /** POST JSON, return parsed response body.
     *  Throws an Error with `status` and `detail` properties on non-2xx,
     *  so callers can distinguish 502 (retriable) from 400 (fatal). */
    async post(url, body = {}) {
        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        const data = await res.json().catch(() => null);
        if (!res.ok) {
            const detail = data?.detail || `HTTP ${res.status}`;
            const err = new Error(detail);
            err.status = res.status;
            throw err;
        }
        return data;
    },

    /** GET JSON, return parsed response body.  Throws on non-2xx. */
    async get(url) {
        const res = await fetch(url);
        const data = await res.json().catch(() => null);
        if (!res.ok) {
            const detail = data?.detail || `HTTP ${res.status}`;
            throw new Error(detail);
        }
        return data;
    },

    /** DELETE, return parsed JSON or null on 404.  Throws on other errors. */
    async del(url) {
        const res = await fetch(url, { method: "DELETE" });
        if (res.status === 404) return null;
        const data = await res.json().catch(() => null);
        if (!res.ok) {
            const detail = data?.detail || `HTTP ${res.status}`;
            throw new Error(detail);
        }
        return data;
    },
};
