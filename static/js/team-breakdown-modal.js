(() => {
    const colors = ["#ffcc00", "#5ca8ff", "#57d69a", "#c084fc", "#ff8b6a"];
    let activeRequest = null;

    function renderPie(backdrop) {
        const dataElement = backdrop.querySelector("#team-breakdown-chart-data");
        const select = backdrop.querySelector("#team-breakdown-chart-mode");
        const pie = backdrop.querySelector("#team-breakdown-pie");
        const legend = backdrop.querySelector("#team-breakdown-pie-legend");
        if (!dataElement || !select || !pie || !legend) return;

        const chartData = JSON.parse(dataElement.textContent);
        const rows = chartData[select.value] || [];
        const total = rows.reduce((sum, row) => sum + (Number(row.points) || 0), 0);
        const positiveTotal = rows.reduce((sum, row) => sum + Math.max(0, Number(row.points) || 0), 0);
        let cursor = 0;
        const stops = [];
        legend.replaceChildren();

        rows.forEach((row, index) => {
            const points = Number(row.points) || 0;
            const slice = positiveTotal > 0 ? Math.max(0, points) / positiveTotal * 360 : 0;
            if (slice > 0) {
                stops.push(`${colors[index % colors.length]} ${cursor}deg ${cursor + slice}deg`);
                cursor += slice;
            }

            const item = document.createElement("li");
            const swatch = document.createElement("span");
            swatch.className = "team-breakdown-pie-swatch";
            swatch.style.backgroundColor = colors[index % colors.length];
            const label = document.createElement("span");
            label.textContent = row.position;
            const value = document.createElement("strong");
            value.textContent = `${points.toFixed(1)} pts`;
            item.append(swatch, label, value);
            legend.appendChild(item);
        });

        pie.style.background = stops.length
            ? `conic-gradient(${stops.join(", ")})`
            : "conic-gradient(#303744 0deg 360deg)";
        pie.setAttribute(
            "aria-label",
            `${select.options[select.selectedIndex].text}: ${total.toFixed(1)} projected points`
        );
        select.onchange = () => renderPie(backdrop);
    }

    function initializeRosterControls(backdrop) {
        const table = backdrop.querySelector("#team-breakdown-roster");
        const filters = [...backdrop.querySelectorAll(".team-position-filters input[type='checkbox']")];
        const count = backdrop.querySelector(".team-position-filter-count");
        if (!table) return;

        const body = table.querySelector("tbody");
        const rows = [...body.querySelectorAll("tr[data-position-groups]")];
        const sortButtons = [...table.querySelectorAll(".roster-sort-button")];
        let activeSortKey = null;
        let sortDirection = "desc";

        function applyFilters() {
            const selected = new Set(filters.filter(input => input.checked).map(input => input.value));
            let visibleCount = 0;
            rows.forEach(row => {
                const groups = row.dataset.positionGroups.split(",").filter(Boolean);
                const visible = groups.some(group => selected.has(group));
                row.hidden = !visible;
                if (visible) visibleCount += 1;
            });
            if (count) count.textContent = `Showing ${visibleCount} of ${rows.length} players`;
        }

        filters.forEach(input => input.addEventListener("change", applyFilters));
        applyFilters();

        sortButtons.forEach(button => button.addEventListener("click", () => {
            const key = button.dataset.sortKey;
            if (key === activeSortKey) {
                sortDirection = sortDirection === "desc" ? "asc" : "desc";
            } else {
                activeSortKey = key;
                sortDirection = "desc";
            }
            const dataKey = {
                "rest-points": "restPoints",
                "starter-points": "starterPoints",
                "bench-points": "benchPoints",
                "starts": "starts",
            }[key];
            rows.sort((a, b) => {
                const difference = (Number(a.dataset[dataKey]) || 0) - (Number(b.dataset[dataKey]) || 0);
                return (sortDirection === "desc" ? -difference : difference)
                    || a.querySelector(".team-breakdown-player-cell").textContent.trim()
                        .localeCompare(b.querySelector(".team-breakdown-player-cell").textContent.trim());
            });
            rows.forEach(row => body.appendChild(row));
            sortButtons.forEach(candidate => {
                const heading = candidate.closest("th");
                heading.setAttribute("aria-sort", candidate === button
                    ? (sortDirection === "desc" ? "descending" : "ascending")
                    : "none");
            });
        }));
    }

    function initializeTabs(backdrop) {
        const tabs = [...backdrop.querySelectorAll("[data-team-tab]")];
        const panels = [...backdrop.querySelectorAll("[data-team-panel]")];
        if (!tabs.length || !panels.length) return;

        function activate(tab, moveFocus = false) {
            const selected = tab.dataset.teamTab;
            tabs.forEach(candidate => {
                const active = candidate === tab;
                candidate.classList.toggle("is-active", active);
                candidate.setAttribute("aria-selected", String(active));
                candidate.tabIndex = active ? 0 : -1;
            });
            panels.forEach(panel => {
                panel.hidden = panel.dataset.teamPanel !== selected;
            });
            if (moveFocus) tab.focus();
        }

        tabs.forEach((tab, index) => {
            tab.addEventListener("click", () => activate(tab));
            tab.addEventListener("keydown", event => {
                let nextIndex = null;
                if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
                if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
                if (event.key === "Home") nextIndex = 0;
                if (event.key === "End") nextIndex = tabs.length - 1;
                if (nextIndex === null) return;
                event.preventDefault();
                activate(tabs[nextIndex], true);
            });
        });
    }

    function initializeModal(backdrop) {
        initializeTabs(backdrop);
        renderPie(backdrop);
        initializeRosterControls(backdrop);
    }

    function closeModal(backdrop, restoreFocus = true) {
        if (!backdrop) return;
        if (activeRequest) {
            activeRequest.abort();
            activeRequest = null;
        }
        backdrop.remove();
        document.body.classList.remove("team-breakdown-modal-open");
        if (restoreFocus && window.teamBreakdownTrigger) {
            window.teamBreakdownTrigger.focus();
        }
    }

    document.addEventListener("click", async event => {
        const closeButton = event.target.closest("[data-team-modal-close]");
        if (closeButton) {
            closeModal(closeButton.closest("[data-team-modal-backdrop]"));
            return;
        }

        const backdrop = event.target.closest("[data-team-modal-backdrop]");
        if (backdrop && event.target === backdrop) {
            closeModal(backdrop);
            return;
        }

        const trigger = event.target.closest(".js-team-breakdown");
        if (!trigger) return;
        event.preventDefault();
        window.teamBreakdownTrigger = trigger;

        const oldBackdrop = document.querySelector("[data-team-modal-backdrop]");
        if (oldBackdrop) closeModal(oldBackdrop, false);
        document.body.classList.add("team-breakdown-modal-open");
        const loading = document.createElement("div");
        loading.className = "team-breakdown-backdrop";
        loading.dataset.teamModalBackdrop = "";
        const loadingCard = document.createElement("div");
        loadingCard.className = "team-breakdown-modal team-breakdown-loading";
        loadingCard.setAttribute("role", "status");
        loadingCard.textContent = "Loading team breakdown…";
        loading.appendChild(loadingCard);
        document.body.appendChild(loading);

        try {
            const url = new URL(trigger.href, window.location.href);
            url.searchParams.set("modal", "1");
            activeRequest = new AbortController();
            const response = await fetch(url, {
                headers: {"X-Requested-With": "XMLHttpRequest"},
                signal: activeRequest.signal,
            });
            if (!response.ok) throw new Error("Unable to load team details.");
            const template = document.createElement("template");
            template.innerHTML = (await response.text()).trim();
            const modal = template.content.firstElementChild;
            if (!modal || !modal.matches("[data-team-modal-backdrop]")) {
                throw new Error("The team details response was incomplete.");
            }
            activeRequest = null;
            loading.remove();
            document.body.appendChild(modal);
            modal.querySelector(".team-breakdown-modal")?.focus();
            initializeModal(modal);
        } catch (error) {
            loading.remove();
            if (error.name === "AbortError") return;
            activeRequest = null;
            document.body.classList.remove("team-breakdown-modal-open");
            window.location.assign(trigger.href);
        }
    });

    document.addEventListener("keydown", event => {
        if (event.key !== "Escape") return;
        closeModal(document.querySelector("[data-team-modal-backdrop]"));
    });

    document.querySelectorAll("[data-team-modal-backdrop]").forEach(initializeModal);
})();
