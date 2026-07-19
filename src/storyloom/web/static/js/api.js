/* ═══════════════════════════════════════════════════════════════════
   api.js — HTTP fetch helpers

   Thin wrappers around fetch() for JSON APIs.
   Exports:
     API.post(url, body) → parsed JSON response (throws on non-2xx)
     API.get(url)        → parsed JSON response
     API.del(url)        → parsed JSON response (null on 404)
   ═══════════════════════════════════════════════════════════════════ */

const API = {
    // POST JSON, return parsed response body
    // GET JSON, return parsed response body
    // DELETE, return parsed JSON or null on 404
};
