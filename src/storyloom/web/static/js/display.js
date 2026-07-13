/* ═══════════════════════════════════════════════════════════════════
   display.js — DOM rendering functions (segments, options, state)
   ═══════════════════════════════════════════════════════════════════ */

const Display = {
    /**
     * Append a narrative segment to the story area.
     */
    appendSegment(text) {
        const area = document.getElementById("story-area");
        if (!area) return;

        // Remove placeholder on first segment
        const placeholder = area.querySelector(".story-placeholder");
        if (placeholder) placeholder.remove();

        const seg = document.createElement("p");
        seg.className = "story-segment";
        seg.textContent = text;
        area.appendChild(seg);
        area.scrollTop = area.scrollHeight;
    },

    /**
     * Render choice buttons.  Returns a Promise that resolves with
     * the selected key string ("1", "2", ...) when the user clicks.
     */
    showChoices(choicesData) {
        return new Promise((resolve) => {
            const panel = document.getElementById("choice-panel");
            if (!panel) {
                console.error("showChoices: #choice-panel not found");
                return;
            }

            panel.innerHTML = "";
            console.log("showChoices: rendering", choicesData);

            let totalIndex = 0;
            const optionCounts = [];  // per-choice-group option count

            // Deadlock fallback: if ALL options have non-null conditions,
            // enable them all anyway.
            let allDisabled = true;
            for (const choice of choicesData) {
                const conds = choice.conditions || {};
                const branches = choice.branches || [];
                for (const b of branches) {
                    if (!conds[b]) { allDisabled = false; break; }
                }
                if (!allDisabled) break;
            }

            for (const choice of choicesData) {
                const labels = choice.labels || [];
                const branches = choice.branches || [];
                const conds = choice.conditions || {};

                for (let i = 0; i < labels.length; i++) {
                    const idx = totalIndex + 1;
                    const branch = branches[i] || "";
                    const condition = conds[branch] || null;
                    const disabled = !allDisabled && condition !== null;

                    const btn = document.createElement("button");
                    btn.className = "choice-btn";
                    btn.innerHTML = `<span class="choice-key">[${idx}]</span> ${Display._esc(labels[i])}`;
                    if (disabled) {
                        btn.disabled = true;
                        btn.innerHTML += ` <span class="choice-cond">(需: ${Display._esc(condition)})</span>`;
                        btn.title = condition;
                    }
                    btn.addEventListener("click", () => {
                        if (!disabled) _select(panel, resolve, String(idx));
                    });
                    panel.appendChild(btn);
                    totalIndex++;
                }
                optionCounts.push(labels.length);
            }

            // ── Keyboard shortcuts ──────────────────────────────────
            const onKey = (e) => {
                // Number keys 1-9 → select corresponding option
                const n = parseInt(e.key);
                if (n >= 1 && n <= totalIndex) {
                    const btn = panel.querySelectorAll(".choice-btn")[n - 1];
                    if (btn && !btn.disabled) {
                        _select(panel, resolve, String(n));
                    }
                }
                // Q → treat as "back to menu" (resolve with special marker)
                if (e.key === "q" || e.key === "Q") {
                    _select(panel, resolve, "q");
                }
            };
            document.addEventListener("keydown", onKey, { once: false });
            // Store cleanup reference
            panel._cleanupKey = () => document.removeEventListener("keydown", onKey);

            panel.classList.remove("hidden");
        });
    },

    /**
     * Clear the choice panel and keyboard listeners.
     */
    clearChoices() {
        const panel = document.getElementById("choice-panel");
        if (panel) {
            if (panel._cleanupKey) { panel._cleanupKey(); panel._cleanupKey = null; }
            panel.innerHTML = "";
            panel.classList.add("hidden");
        }
    },

    /**
     * Show an error message in a modal.
     */
    showError(message, onRetry, onQuit) {
        const area = document.getElementById("story-area");
        if (!area) return;

        const err = document.createElement("div");
        err.className = "panel error-panel";
        err.innerHTML = `
            <p class="text-error">⚠ ${Display._esc(message)}</p>
            <div class="btn-row" style="margin-top: 0.8rem;">
                ${onRetry ? '<button class="retry-btn">' + t("retry") + '</button>' : ""}
                ${onQuit ? '<button class="danger quit-btn">' + t("back_to_menu") + '</button>' : ""}
            </div>
        `;
        area.appendChild(err);

        if (onRetry) {
            err.querySelector(".retry-btn")?.addEventListener("click", () => {
                err.remove();
                onRetry();
            });
        }
        if (onQuit) {
            err.querySelector(".quit-btn")?.addEventListener("click", () => {
                err.remove();
                onQuit();
            });
        }
    },

    /**
     * Update the state panel sidebar.
     */
    updateStatePanel(vars, changes) {
        const varsEl = document.getElementById("state-vars");
        if (!varsEl) return;

        let html = "";
        for (const [k, v] of Object.entries(vars)) {
            const valStr = Array.isArray(v) ? v.join(", ") : String(v);
            html += `<div class="var-item"><span class="var-name">${Display._esc(k)}</span> <span class="var-value">${Display._esc(valStr)}</span></div>`;
        }
        varsEl.innerHTML = html || '<span class="text-muted">—</span>';
    },

    /**
     * Update the outline sidebar.
     */
    updateOutline(nodes) {
        const el = document.getElementById("outline-list");
        if (!el) return;

        // Only show reached nodes — hide future chapters (spoiler prevention)
        const visible = nodes.filter(n => n.status === "completed" || n.status === "active");
        let html = "";
        for (const node of visible) {
            const icon = node.status === "completed" ? "●" : "▶";
            const cls = "outline-" + node.status;
            html += `<div class="outline-node ${cls}"><span class="outline-icon">${icon}</span> ${Display._esc(node.title || node.id)}</div>`;
        }
        el.innerHTML = html || '<span class="text-muted">—</span>';
    },

    /**
     * Render adventure log (Markdown → HTML).
     */
    showAdventureLog(text) {
        const area = document.getElementById("story-area");
        if (!area) return;

        const div = document.createElement("div");
        div.className = "panel adventure-log";
        // Simple markdown: headings, bold, paragraphs
        const html = text
            .replace(/^### (.+)$/gm, "<h3>$1</h3>")
            .replace(/^## (.+)$/gm, "<h2>$1</h2>")
            .replace(/^# (.+)$/gm, "<h1>$1</h1>")
            .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
            .replace(/\*(.+?)\*/g, "<em>$1</em>")
            .replace(/\n\n/g, "</p><p>")
            .replace(/\n/g, "<br>");
        div.innerHTML = `<h2>📜 ${t("adventure_log")}</h2><p>${html}</p>`;
        area.appendChild(div);
    },

    /** Escape HTML entities. */
    _esc(s) {
        const d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    },
};

/** Shared helper — resolve choice, disable buttons, clean keyboard listener. */
function _select(panel, resolve, key) {
    panel.querySelectorAll("button").forEach(b => b.disabled = true);
    const input = panel.querySelector("input");
    if (input) input.disabled = true;
    if (panel._cleanupKey) { panel._cleanupKey(); panel._cleanupKey = null; }
    resolve(key);
}
