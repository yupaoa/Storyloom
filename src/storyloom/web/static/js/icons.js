/* ═══════════════════════════════════════════════════════════════════
   Storyloom Web — Shared SVG Icons

   Global Icons namespace providing inline SVG icons for UI buttons.
   Replaces hardcoded Unicode characters (←, ↑, ✎, ✓) with scalable
   fill-based icons styled via currentColor (matches _modeSVG convention).

   Usage: Icons.arrowLeft() → inline SVG string for the left-arrow icon.
   ═══════════════════════════════════════════════════════════════════ */

const Icons = (function () {
    "use strict";

    /** Left arrow — back / return to menu. */
    function arrowLeft() {
        return '<svg viewBox="0 0 24 24" width="20" height="20" ' +
            'fill="currentColor">' +
            '<path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41' +
            'L7.83 13H20v-2z"/>' +
            '</svg>';
    }

    /** Pencil — edit / modify. */
    function pencil() {
        return '<svg viewBox="0 0 24 24" width="16" height="16" ' +
            'fill="currentColor">' +
            '<path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25z' +
            'M20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39' +
            '-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>' +
            '</svg>';
    }

    /** Checkmark — confirm / save (shown in edit mode). */
    function checkmark() {
        return '<svg viewBox="0 0 24 24" width="16" height="16" ' +
            'fill="currentColor">' +
            '<path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41' +
            'L9 16.17z"/>' +
            '</svg>';
    }

    /** Up arrow — send / submit. */
    function arrowUp() {
        return '<svg viewBox="0 0 24 24" width="18" height="18" ' +
            'fill="currentColor">' +
            '<path d="M4 12l1.41 1.41L11 7.83V20h2V7.83l5.58 5.59L20 12' +
            'l-8-8-8 8z"/>' +
            '</svg>';
    }

    /** Gear — settings / preferences (migrated from game.js). */
    function gear() {
        return '<svg viewBox="0 0 24 24" width="20" height="20" ' +
            'fill="currentColor">' +
            '<path d="M12 15.5A3.5 3.5 0 0 1 8.5 12 3.5 3.5 0 0 1 ' +
            '12 8.5a3.5 3.5 0 0 1 3.5 3.5 3.5 3.5 0 0 1-3.5 3.5m7.43-2.53' +
            'c.04-.32.07-.64.07-.97 0-.33-.03-.66-.07-1l2.11-1.63c.19-.15' +
            '.24-.42.12-.64l-2-3.46c-.12-.22-.39-.31-.61-.22l-2.49 1c-.52' +
            '-.39-1.06-.73-1.69-.98l-.37-2.65A.506.506 0 0 0 14 2h-4c-.25 ' +
            '0-.46.18-.5.42l-.37 2.65c-.63.25-1.17.59-1.69.98l-2.49-1c-.22' +
            '-.09-.49 0-.61.22l-2 3.46c-.13.22-.07.49.12.64L4.57 11c-.04.34' +
            '-.07.67-.07 1 0 .33.03.65.07.97l-2.11 1.66c-.19.15-.25.42-.12' +
            '.64l2 3.46c.12.22.39.3.61.22l2.49-1.01c.52.4 1.06.74 1.69.99' +
            'l.37 2.65c.04.24.25.42.5.42h4c.25 0 .46-.18.5-.42l.37-2.65c.63' +
            '-.26 1.17-.59 1.69-.99l2.49 1.01c.22.08.49 0 .61-.22l2-3.46c.12' +
            '-.22.07-.49-.12-.64l-2.11-1.66Z"/>' +
            '</svg>';
    }

    /* ── Exports ─────────────────────────────────────────────────── */
    return {
        arrowLeft: arrowLeft,
        pencil: pencil,
        checkmark: checkmark,
        arrowUp: arrowUp,
        gear: gear,
    };
})();
