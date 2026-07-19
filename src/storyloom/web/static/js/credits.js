/* ═══════════════════════════════════════════════════════════════════
   credits.js — Credits data (i18n-aware)

   Section titles are English msgid strings resolved via _().
   Add or reorder sections here; the credits overlay renders
   from this data automatically.

   Authority: storyloom.po (translations)
   ═══════════════════════════════════════════════════════════════════ */

const CREDITS = {
    app: "Storyloom",                 // msgid
    tagline: "AI Text Adventure",   // msgid
    sections: [
        {
            title: "Engine & System Architecture",   // msgid
            people: ["Slev"],
        },
        {
            title: "Web Interface",   // msgid
            people: ["yupaoa"],
        },
    ],
};
