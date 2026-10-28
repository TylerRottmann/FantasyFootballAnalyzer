(() => {
    const page = document.querySelector(".trades-page");
    const calculateButton = document.getElementById("calculate-trade");
    if (!page || !calculateButton) return;

    const teamElements = Array.from(document.querySelectorAll("[data-calculator-team]"));
    const status = document.getElementById("trade-calculator-status");
    const result = document.getElementById("trade-calculator-result");
    const csrfToken = document.querySelector("#trade-csrf-form input[name=csrfmiddlewaretoken]")?.value || "";
    const selected = new Map(teamElements.map((team) => [team.dataset.calculatorTeam, new Map()]));
    const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[char]);

    function rosterId(team) {
        if (team.dataset.calculatorTeam === "one") return team.dataset.rosterId;
        return team.querySelector(".calculator-roster-select")?.value || "";
    }

    function playerMarkup(player, removable = false) {
        const position = player.position === "DEF" ? "D/ST" : player.position;
        const avatar = player.headshot_url
            ? `<img src="${escapeHtml(player.headshot_url)}" alt="" loading="lazy" onerror="this.remove()"><span>${escapeHtml(position || "—")}</span>`
            : escapeHtml(position || "—");
        const logo = player.team_logo_url
            ? `<img class="trade-team-logo" src="${escapeHtml(player.team_logo_url)}" alt="" loading="lazy" onerror="this.remove()">`
            : "";
        const age = player.age == null ? "Age —" : `Age ${escapeHtml(player.age)}`;
        const removeButton = removable
            ? `<button type="button" class="remove-trade-player" aria-label="Remove ${escapeHtml(player.name)}" data-remove-player="${escapeHtml(player.roster_player_id)}">×</button>`
            : "";
        const playerData = removable ? "" : `data-player="${encodeURIComponent(JSON.stringify(player))}"`;
        return `<${removable ? "div" : "div"} class="${removable ? "selected-trade-player" : "trade-search-result"}" ${removable ? "" : `role="button" tabindex="0" ${playerData} data-add-player="${escapeHtml(player.roster_player_id)}"`}>
            <div class="trade-player-avatar">${avatar}</div>
            <div class="trade-player-details">
                <div class="trade-player-name">${escapeHtml(player.name)}</div>
                <div class="trade-player-meta">${escapeHtml(position)} · ${logo}${escapeHtml(player.nfl_team || "FA")} · ${age}${removable ? "" : ` · ${escapeHtml(player.fantasy_team)}`}</div>
            </div>
            <div class="trade-player-points">
                <span class="trade-points-value">${escapeHtml(player.rest_of_season_points)} pts <button type="button" class="trade-points-info" data-points-info aria-label="Explain projected points" aria-expanded="false"><i class="bi bi-info-circle" aria-hidden="true"></i></button></span>
                <span class="trade-points-explanation" hidden>Sum of this player’s saved projections for the remaining regular-season weeks. This is the player’s total, not points contributed to the team lineup.</span>
            </div>
            ${removeButton}
        </div>`;
    }

    function renderSelected(team) {
        const name = team.dataset.calculatorTeam;
        const container = team.querySelector(".trade-selected-players");
        container.innerHTML = Array.from(selected.get(name).values())
            .map((player) => playerMarkup(player, true)).join("");
    }

    function setStatus(message, isError = false) {
        status.classList.toggle("is-error", isError);
        status.textContent = message;
    }

    function attachSearch(team) {
        const input = team.querySelector(".trade-player-search");
        const results = team.querySelector(".trade-search-results");
        const name = team.dataset.calculatorTeam;
        let timer = null;
        let controller = null;

        const runSearch = async () => {
            const selectedRosterId = rosterId(team);
            const query = input.value.trim();
            // The opposing side can search the whole league before a fantasy team
            // is chosen. Selecting a result below will assign its roster automatically.
            if ((!selectedRosterId && name !== "two") || query.length < 2) {
                results.hidden = true;
                results.replaceChildren();
                return;
            }
            if (controller) controller.abort();
            controller = new AbortController();
            results.hidden = false;
            results.innerHTML = '<div class="trade-search-result">Searching…</div>';
            const url = new URL(page.dataset.playerSearchUrl, window.location.origin);
            url.searchParams.set("q", query);
            if (selectedRosterId) url.searchParams.set("roster_id", selectedRosterId);
            try {
                const response = await fetch(url, { headers: { Accept: "application/json" }, signal: controller.signal });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || "Player search failed.");
                const available = data.results.filter((player) => !selected.get(name).has(String(player.roster_player_id)));
                results.innerHTML = available.length
                    ? available.map((player) => playerMarkup(player)).join("")
                    : '<div class="trade-search-result">No available players matched.</div>';
            } catch (error) {
                if (error.name === "AbortError") return;
                results.innerHTML = `<div class="trade-search-result">${escapeHtml(error.message || "Search failed.")}</div>`;
            }
        };

        input.addEventListener("input", () => {
            window.clearTimeout(timer);
            timer = window.setTimeout(runSearch, 250);
        });
        input.addEventListener("keydown", (event) => {
            if (event.key === "Escape") results.hidden = true;
        });
        results.addEventListener("click", (event) => {
            const infoButton = event.target.closest("[data-points-info]");
            if (infoButton) {
                event.preventDefault();
                event.stopPropagation();
                const explanation = infoButton.closest(".trade-player-points").querySelector(".trade-points-explanation");
                explanation.hidden = !explanation.hidden;
                infoButton.setAttribute("aria-expanded", String(!explanation.hidden));
                return;
            }
            const button = event.target.closest("[data-add-player]");
            if (!button) return;
            let player;
            try {
                player = JSON.parse(decodeURIComponent(button.dataset.player));
            } catch (_error) {
                return;
            }
            if (name === "two") {
                const rosterSelect = team.querySelector(".calculator-roster-select");
                const currentRosterId = rosterSelect.value;
                const hasPlayers = selected.get(name).size > 0;
                if (hasPlayers && currentRosterId !== String(player.roster_id)) {
                    setStatus("Choose players from the same fantasy team for one trade.", true);
                    return;
                }
                if (!hasPlayers && currentRosterId !== String(player.roster_id)) {
                    rosterSelect.value = String(player.roster_id);
                    rosterSelect.dispatchEvent(new Event("change", { bubbles: true }));
                }
            }
            selected.get(name).set(String(player.roster_player_id), player);
            setStatus("");
            renderSelected(team);
            input.value = "";
            results.hidden = true;
            results.replaceChildren();
        });
        results.addEventListener("keydown", (event) => {
            if (event.target.closest("[data-points-info]")) return;
            const resultCard = event.target.closest("[data-add-player]");
            if (resultCard && (event.key === "Enter" || event.key === " ")) {
                event.preventDefault();
                resultCard.click();
            }
        });
    }

    teamElements.forEach((team) => attachSearch(team));

    teamElements.forEach((team) => {
        team.querySelector(".trade-selected-players").addEventListener("click", (event) => {
            const infoButton = event.target.closest("[data-points-info]");
            if (infoButton) {
                event.preventDefault();
                const explanation = infoButton.closest(".trade-player-points").querySelector(".trade-points-explanation");
                explanation.hidden = !explanation.hidden;
                infoButton.setAttribute("aria-expanded", String(!explanation.hidden));
                return;
            }
            const remove = event.target.closest("[data-remove-player]");
            if (!remove) return;
            selected.get(team.dataset.calculatorTeam).delete(String(remove.dataset.removePlayer));
            renderSelected(team);
        });
    });

    const opposingTeam = document.querySelector('[data-calculator-team="two"]');
    const opposingRosterSelect = opposingTeam?.querySelector(".calculator-roster-select");
    const opposingSearch = opposingTeam?.querySelector(".trade-player-search");
    opposingRosterSelect?.addEventListener("change", () => {
        selected.get("two").clear();
        renderSelected(opposingTeam);
        opposingSearch.disabled = false;
        opposingSearch.placeholder = opposingRosterSelect.value
            ? "Search this team or any other team"
            : "Search all other teams' players";
        opposingSearch.value = "";
        opposingTeam.querySelector(".trade-search-results").hidden = true;
    });

    calculateButton.addEventListener("click", async () => {
        const one = document.querySelector('[data-calculator-team="one"]');
        const two = opposingTeam;
        const team1Players = Array.from(selected.get("one").keys());
        const team2Players = Array.from(selected.get("two").keys());
        if (!team1Players.length || !team2Players.length) {
            setStatus("Add at least one player to both teams.", true);
            return;
        }
        if (!rosterId(two)) {
            setStatus("Select the other fantasy team first.", true);
            return;
        }
        calculateButton.disabled = true;
        result.replaceChildren();
        setStatus("Calculating optimized rest-of-season lineups…");
        try {
            const response = await fetch(page.dataset.calculatorUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken,
                    Accept: "application/json",
                },
                body: JSON.stringify({
                    team1_roster_id: rosterId(one),
                    team2_roster_id: rosterId(two),
                    team1_player_ids: team1Players,
                    team2_player_ids: team2Players,
                }),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Trade calculation failed.");
            renderResult(data);
            setStatus("");
        } catch (error) {
            setStatus(error.message || "Trade calculation failed.", true);
        } finally {
            calculateButton.disabled = false;
        }
    });

    function renderResult(data) {
        const team = (row) => {
            const changeClass = row.gain > 0 ? "positive" : row.gain < 0 ? "negative" : "";
            const sign = row.gain > 0 ? "+" : "";
            return `<div class="trade-result-team">
                <strong>${escapeHtml(row.name)}</strong>
                <div class="trade-result-numbers">
                    <span>Before <b>${escapeHtml(row.before)}</b></span>
                    <span>After <b>${escapeHtml(row.after)}</b></span>
                    <span>Change <b class="${changeClass}">${sign}${escapeHtml(row.gain)}</b></span>
                </div>
            </div>`;
        };
        result.innerHTML = `<section class="trade-result-card" data-verdict="${escapeHtml(data.verdict)}">
            <h3>${escapeHtml(data.label)}</h3>
            <p>Rest-of-season optimized starter points · ${escapeHtml(data.weeks_counted)} weeks</p>
            <div class="trade-result-teams">${team(data.team1)}${team(data.team2)}</div>
        </section>`;
    }

    document.getElementById("clear-calculator")?.addEventListener("click", () => {
        selected.forEach((players) => players.clear());
        teamElements.forEach(renderSelected);
        result.replaceChildren();
        setStatus("");
        teamElements.forEach((team) => {
            team.querySelector(".trade-player-search").value = "";
            team.querySelector(".trade-search-results").hidden = true;
        });
    });
})();
