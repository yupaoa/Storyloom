/* ═══════════════════════════════════════════════════════════════════
   Storyloom Web — Shared SVG Icons

   Global Icons namespace providing inline SVG icons for UI buttons.
   Replaces hardcoded Unicode characters (←, ↑, ✎, ✓) with scalable
   stroke-based icons styled via currentColor.

   Usage: Icons.arrowLeft() → inline SVG string for the left-arrow icon.
   ═══════════════════════════════════════════════════════════════════ */

var Icons = (function () {
    "use strict";

    /** Left arrow — back / return to menu. */
    function arrowLeft() {
        return '<svg viewBox="0 0 24 24" width="20" height="20" ' +
            'fill="none" stroke="currentColor" stroke-width="2" ' +
            'stroke-linecap="round" stroke-linejoin="round">' +
            '<line x1="19" y1="12" x2="5" y2="12"/>' +
            '<polyline points="12 19 5 12 12 5"/>' +
            '</svg>';
    }

    /** Pencil — edit / modify. */
    function pencil() {
        return '<svg viewBox="0 0 24 24" width="16" height="16" ' +
            'fill="none" stroke="currentColor" stroke-width="2" ' +
            'stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>' +
            '</svg>';
    }

    /** Checkmark — confirm / save (shown in edit mode). */
    function checkmark() {
        return '<svg viewBox="0 0 24 24" width="16" height="16" ' +
            'fill="none" stroke="currentColor" stroke-width="2" ' +
            'stroke-linecap="round" stroke-linejoin="round">' +
            '<polyline points="20 6 9 17 4 12"/>' +
            '</svg>';
    }

    /** Up arrow — send / submit. */
    function arrowUp() {
        return '<svg viewBox="0 0 24 24" width="18" height="18" ' +
            'fill="none" stroke="currentColor" stroke-width="2" ' +
            'stroke-linecap="round" stroke-linejoin="round">' +
            '<line x1="12" y1="19" x2="12" y2="5"/>' +
            '<polyline points="5 12 12 5 19 12"/>' +
            '</svg>';
    }

    /* ── Exports ─────────────────────────────────────────────────── */
    return {
        arrowLeft: arrowLeft,
        pencil: pencil,
        checkmark: checkmark,
        arrowUp: arrowUp,
    };
})();
