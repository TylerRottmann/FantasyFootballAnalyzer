(() => {
    const page = document.querySelector(".trades-page");
    if (!page) return;

    const tabs = Array.from(document.querySelectorAll("[data-trade-tab]"));
    const panels = Array.from(document.querySelectorAll("[data-trade-panel]"));
    const form = document.getElementById("trade-filters");
    const status = document.getElementById("trade-suggestion-status");
    const results = document.getElementById("trade-suggestions");
    let requestController = null;

    function activateTab(name) {
        tabs.forEach((tab) => {
            const active = tab.dataset.tradeTab === name;
            tab.classList.toggle("is-active", active);
            tab.setAttribute("aria-selected", String(active));
        });
        panels.forEach((panel) => {
            panel.hidden = panel.dataset.tradePanel !== name;
        });
    }

    tabs.forEach((tab) => tab.addEventListener("click", () => activateTab(tab.dataset.tradeTab)));

    if (!form || !status || !results) return;

    const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[char]);

    const rowTemplate = document.getElementById("trade-package-row-template");
    function renderPackageRows(side) {
        const countValue = form.querySelector(`[data-package-count="${side}"]`).value;
        const count = countValue === "any" ? 1 : Number(countValue);
        const container = form.querySelector(`[data-package-rows="${side}"]`);
        const existing = Array.from(container.querySelectorAll(".trade-filter-row"));
        while (existing.length > count) existing.pop().remove();
        while (container.children.length < count) {
            const row = rowTemplate.content.firstElementChild.cloneNode(true);
            const index = container.children.length + 1;
            row.querySelector("[data-position-field]").name = `${side}_position`;
            row.querySelector("[data-position-field]").setAttribute("aria-label", `${side === "give" ? "Trade away" : "Trade for"} player ${index} position`);
            const input = row.querySelector("[data-player-field]");
            const inputId = `trade-${side}-player-${index}`;
            input.id = inputId;
            row.querySelector("[data-player-label]").htmlFor = inputId;
            input.name = `${side}_player_label`;
            input.setAttribute("aria-label", `${side === "give" ? "Trade away" : "Trade for"} player ${index}`);
            input.placeholder = side === "give" ? "Search your roster" : "Search all other teams";
            row.querySelector("[data-player-id-field]").name = `${side}_player_id`;
            const options = Array.from(form.querySelectorAll(`[data-player-options="${side}"] [data-player-option]`));
            const idInput = row.querySelector("[data-player-id-field]");
            const ownerHint = row.querySelector("[data-player-owner]");
            const searchResults = row.querySelector("[data-player-results]");
            const renderPlayerResults = () => {
                const query = input.value.trim().toLocaleLowerCase();
                idInput.value = "";
                ownerHint.textContent = "";
                if (query.length < 1) {
                    searchResults.hidden = true;
                    searchResults.replaceChildren();
                    input.setAttribute("aria-expanded", "false");
                    return;
                }
                const matches = options.filter((option) => [
                    option.dataset.playerName,
                    option.dataset.position,
                    option.dataset.nflTeam,
                    option.dataset.fantasyTeam,
                ].some((value) => value?.toLocaleLowerCase().includes(query))).slice(0, 12);
                searchResults.innerHTML = matches.length ? matches.map((option) => {
                    const optionIndex = options.indexOf(option);
                    const playerName = option.dataset.playerName || "Unknown player";
                    const position = option.dataset.position === "DEF" ? "D/ST" : option.dataset.position;
                    const nflTeam = option.dataset.nflTeam || "FA";
                    const fantasyTeam = option.dataset.fantasyTeam || "Fantasy team";
                    const headshot = option.dataset.headshot;
                    const avatar = headshot
                        ? `<img src="${escapeHtml(headshot)}" alt="" loading="lazy" onerror="this.remove()"><span>${escapeHtml(position)}</span>`
                        : escapeHtml(position || "—");
                    const logo = nflTeam && nflTeam !== "FA"
                        ? `<img class="trade-team-logo" src="https://a.espncdn.com/i/teamlogos/nfl/500/${encodeURIComponent(nflTeam.toLocaleLowerCase())}.png" alt="" loading="lazy" onerror="this.remove()">`
                        : "";
                    return `<button type="button" class="trade-search-result trade-suggest-player-option" role="option" data-select-player="${optionIndex}">
                        <div class="trade-player-avatar">${avatar}</div>
                        <div class="trade-player-details"><div class="trade-player-name">${escapeHtml(playerName)}</div>
                            <div class="trade-player-meta">${escapeHtml(position)} · ${logo}${escapeHtml(nflTeam)} · ${escapeHtml(fantasyTeam)}</div></div>
                    </button>`;
                }).join("") : '<div class="trade-suggest-no-results">No matching players.</div>';
                searchResults.hidden = false;
                input.setAttribute("aria-expanded", "true");
            };
            input.addEventListener("input", renderPlayerResults);
            input.addEventListener("keydown", (event) => {
                if (event.key === "Escape") {
                    searchResults.hidden = true;
                    input.setAttribute("aria-expanded", "false");
                }
            });
            searchResults.addEventListener("click", (event) => {
                const choice = event.target.closest("[data-select-player]");
                if (!choice) return;
                const option = options[Number(choice.dataset.selectPlayer)];
                if (!option) return;
                input.value = `${option.dataset.playerName} (${option.dataset.position === "DEF" ? "D/ST" : option.dataset.position})`;
                idInput.value = option.dataset.playerId;
                ownerHint.textContent = `Fantasy team: ${option.dataset.fantasyTeam}`;
                searchResults.hidden = true;
                input.setAttribute("aria-expanded", "false");
            });
            input.addEventListener("blur", () => window.setTimeout(() => {
                searchResults.hidden = true;
                input.setAttribute("aria-expanded", "false");
            }, 150));
            container.append(row);
        }
    }
    ["give", "receive"].forEach((side) => {
        const selector = form.querySelector(`[data-package-count="${side}"]`);
        selector.addEventListener("change", () => renderPackageRows(side));
        renderPackageRows(side);
    });
    form.addEventListener("reset", () => window.setTimeout(() => ["give", "receive"].forEach(renderPackageRows), 0));

    const minRange = form.querySelector('[data-age-range="min"]');
    const maxRange = form.querySelector('[data-age-range="max"]');
    const minAgeValue = form.querySelector('[data-age-value="min"]');
    const maxAgeValue = form.querySelector('[data-age-value="max"]');
    const ageLabel = form.querySelector("[data-age-label]");
    function updateAgeRange(changed) {
        if (+minRange.value > +maxRange.value) {
            if (changed === "min") maxRange.value = minRange.value;
            else minRange.value = maxRange.value;
        }
        ageLabel.textContent = `${minRange.value}–${maxRange.value}`;
        const fullRange = minRange.value === "20" && maxRange.value === "45";
        minAgeValue.value = fullRange ? "" : minRange.value;
        maxAgeValue.value = fullRange ? "" : maxRange.value;
        const percent = (value) => `${((+value - 20) / 25) * 100}%`;
        const slider = form.querySelector(".trade-range-pair");
        slider.style.setProperty("--min-percent", percent(minRange.value));
        slider.style.setProperty("--max-percent", percent(maxRange.value));
    }
    minRange.addEventListener("input", () => updateAgeRange("min"));
    maxRange.addEventListener("input", () => updateAgeRange("max"));

    const multiLabels = {
        teams: { input: 'input[name="exclude_nfl_teams"]', empty: "Any team", selected: "teams excluded" },
        byes: { input: 'input[name="bye_week"]', empty: "Any bye week", selected: "bye weeks" },
    };
    Object.entries(multiLabels).forEach(([key, config]) => {
        const summary = form.querySelector(`[data-multi-summary="${key}"]`);
        const checkboxes = Array.from(form.querySelectorAll(config.input));
        const update = () => {
            const count = checkboxes.filter((checkbox) => checkbox.checked).length;
            summary.textContent = count ? `${count} ${config.selected}` : config.empty;
        };
        checkboxes.forEach((checkbox) => checkbox.addEventListener("change", update));
        form.addEventListener("reset", () => window.setTimeout(update, 0));
    });

    function playerCard(player) {
        const position = player.position === "DEF" ? "D/ST" : player.position;
        const avatar = player.headshot_url
            ? `<img src="${escapeHtml(player.headshot_url)}" alt="" loading="lazy" onerror="this.remove()"><span>${escapeHtml(position || "—")}</span>`
            : escapeHtml(position || "—");
        const logo = player.team_logo_url
            ? `<img class="trade-team-logo" src="${escapeHtml(player.team_logo_url)}" alt="${escapeHtml(player.nfl_team)}" loading="lazy" onerror="this.remove()">`
            : "";
        const age = player.age == null ? "Age —" : `Age ${escapeHtml(player.age)}`;
        const bye = player.bye_week == null ? "Bye —" : `Bye ${escapeHtml(player.bye_week)}`;
        const currentStarts = Number(player.projected_starts || 0);
        const newTeamStarts = Number(player.new_team_projected_starts || 0);
        return `<div class="trade-player-card">
            <div class="trade-player-avatar">${avatar}</div>
            <div class="trade-player-details">
                <div class="trade-player-name">${escapeHtml(player.name)}</div>
                <div class="trade-player-meta">${escapeHtml(position)} · ${logo}${escapeHtml(player.nfl_team || "FA")} · ${age} · ${bye}</div>
                <div class="trade-player-meta">Fantasy team: ${escapeHtml(player.fantasy_team)}</div>
            </div>
            <div class="trade-player-points" aria-label="${currentStarts} projected starts on current team, ${newTeamStarts} on new team">
                <strong>${currentStarts} → ${newTeamStarts}</strong><span>starts · current → new team</span>
            </div>
        </div>`;
    }

    function suggestionCard(row, index) {
        const giveCards = row.you_give.map(playerCard).join("");
        const receiveCards = row.you_get.map(playerCard).join("");
        const weeklyRows = (row.weekly_impact || []).map((week) => `
            <tr>
                <th scope="row">Week ${escapeHtml(week.week)}</th>
                <td>${escapeHtml(week.you_before)}</td><td>${escapeHtml(week.you_after)}</td>
                <td class="${week.you_delta >= 0 ? "is-positive" : "is-negative"}">${week.you_delta > 0 ? "+" : ""}${escapeHtml(week.you_delta)}</td>
                <td>${escapeHtml(week.other_before)}</td><td>${escapeHtml(week.other_after)}</td>
                <td class="${week.other_delta >= 0 ? "is-positive" : "is-negative"}">${week.other_delta > 0 ? "+" : ""}${escapeHtml(week.other_delta)}</td>
            </tr>`).join("");
        const positionRows = Object.entries(row.position_impact || {})
            .filter(([, impact]) => impact.you_before || impact.you_after || impact.other_before || impact.other_after)
            .map(([position, impact]) => `
                <tr>
                    <th scope="row">${escapeHtml(position === "DEF" ? "D/ST" : position)}</th>
                    <td>${escapeHtml(impact.you_before)}</td><td>${escapeHtml(impact.you_after)}</td>
                    <td class="${impact.you_delta >= 0 ? "is-positive" : "is-negative"}">${impact.you_delta > 0 ? "+" : ""}${escapeHtml(impact.you_delta)}</td>
                    <td>${escapeHtml(impact.other_before)}</td><td>${escapeHtml(impact.other_after)}</td>
                    <td class="${impact.other_delta >= 0 ? "is-positive" : "is-negative"}">${impact.other_delta > 0 ? "+" : ""}${escapeHtml(impact.other_delta)}</td>
                </tr>`).join("");
        const positionFit = row.position_balance_summary
            ? `<div class="trade-position-fit"><strong>Strength-for-need fit</strong><span>${escapeHtml(row.position_balance_summary)}</span></div>`
            : "";
        return `<article class="trade-suggestion">
            <header class="trade-suggestion-header">
                <h3 class="trade-suggestion-title"><span class="trade-rank">${index + 1}</span>You ↔ ${escapeHtml(row.other_team)}</h3>
                <span class="trade-gain-pill">Both gain · ${escapeHtml(row.mutual_gain)} starter pts</span>
            </header>
            <div class="trade-exchange">
                <div class="trade-side">
                    <div class="trade-side-heading"><span>You give</span><strong>+${escapeHtml(row.you_gain)} for you</strong></div>
                    ${giveCards}
                </div>
                <div class="trade-arrow" aria-hidden="true">⇄</div>
                <div class="trade-side">
                    <div class="trade-side-heading"><span>You receive</span><strong>+${escapeHtml(row.other_gain)} for them</strong></div>
                    ${receiveCards}
                </div>
            </div>
            ${positionFit}
            <footer class="trade-suggestion-footer">
                <span>Optimized starters · ${escapeHtml(row.weeks_counted)} weeks included</span>
                <span>Your total: <strong>${escapeHtml(row.you_before)} → ${escapeHtml(row.you_after)}</strong> · Their total: <strong>${escapeHtml(row.other_before)} → ${escapeHtml(row.other_after)}</strong></span>
            </footer>
            <details class="trade-weekly-impact">
                <summary>View week-by-week lineup impact</summary>
                <div class="trade-weekly-table-wrap"><table>
                    <thead><tr><th scope="col">Week</th><th scope="col">You before</th><th scope="col">You after</th><th scope="col">You change</th><th scope="col">Them before</th><th scope="col">Them after</th><th scope="col">Their change</th></tr></thead>
                    <tbody>${weeklyRows}</tbody>
                </table></div>
            </details>
            <details class="trade-weekly-impact trade-position-impact">
                <summary>View rest-of-season projected starts by position</summary>
                <div class="trade-weekly-table-wrap"><table>
                    <thead><tr><th scope="col">Position</th><th scope="col">You before</th><th scope="col">You after</th><th scope="col">You change</th><th scope="col">Them before</th><th scope="col">Them after</th><th scope="col">Their change</th></tr></thead>
                    <tbody>${positionRows}</tbody>
                </table></div>
            </details>
        </article>`;
    }

    async function loadSuggestions() {
        if (requestController) requestController.abort();
        requestController = new AbortController();
        status.classList.remove("is-error");
        status.textContent = "Finding trades that improve both starting lineups…";
        results.replaceChildren();

        const params = new URLSearchParams(new FormData(form));
        try {
            const response = await fetch(`${page.dataset.suggestionsUrl}?${params.toString()}`, {
                headers: { Accept: "application/json" },
                signal: requestController.signal,
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Unable to load trade suggestions.");
            if (data.error) {
                status.classList.add("is-error");
                status.textContent = data.error;
                return;
            }
            if (!data.suggestions.length) {
                status.textContent = "No trade suggestions matched these filters. Try widening your filters.";
                results.innerHTML = '<div class="trade-empty">No trade suggestions found.</div>';
                return;
            }
            status.textContent = data.suggestions.length < 5
                ? `Found ${data.suggestions.length} trade suggestions with different players to receive · Week ${data.current_week} onward`
                : `Top 5 trade suggestions with different players to receive · Week ${data.current_week} onward`;
            results.innerHTML = data.suggestions.map(suggestionCard).join("");
        } catch (error) {
            if (error.name === "AbortError") return;
            status.classList.add("is-error");
            status.textContent = error.message || "Unable to load trade suggestions.";
        }
    }

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        loadSuggestions();
    });
    form.addEventListener("reset", () => window.setTimeout(loadSuggestions, 0));
    loadSuggestions();
})();
