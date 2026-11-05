(() => {
    document.addEventListener("click", async event => {
        const button = event.target.closest("[data-boom-bust-v2-url]");
        if (!button || button.disabled) return;

        const output = button.parentElement.querySelector(".boom-bust-v2-result");
        if (!output) return;

        button.disabled = true;
        output.textContent = "Loading prediction…";

        try {
            const url = new URL(button.dataset.boomBustV2Url, window.location.origin);
            url.searchParams.set("week", button.dataset.boomBustV2Week);

            const response = await fetch(url, {
                method: "GET",
                credentials: "same-origin",
                headers: {"Accept": "application/json"},
            });

            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || "Prediction unavailable.");
            }

            const probabilities = data.probabilities;
            if (!probabilities || !["boom", "normal", "bust"].every(
                key => Number.isFinite(probabilities[key])
                    && probabilities[key] >= 0
                    && probabilities[key] <= 1
            )) {
                throw new Error("Invalid prediction response.");
            }

            const format = key => `${key[0].toUpperCase()}${key.slice(1)}: ${(probabilities[key] * 100).toFixed(1)}%`;
            const lines = [
                `Week ${data.week}`,
                format("boom"),
                format("normal"),
                format("bust"),
            ];

            const availability = data.availability;

            if (availability && typeof availability === "object") {
                const context = [];

                const injury = typeof availability.injury_status === "string"
                    ? availability.injury_status.trim()
                    : "";

                if (injury) {
                    context.push(`Injury: ${injury}`);
                }

                const rosterStatus = typeof availability.roster_status === "string"
                    ? availability.roster_status.trim()
                    : "";

                if (rosterStatus) {
                    context.push(`Roster: ${rosterStatus}`);
                }

                if (
                    Number.isInteger(availability.depth_order)
                    && availability.depth_order > 0
                ) {
                    context.push(`Depth-chart rank: ${availability.depth_order}`);
                }

                const snapPercent = value =>
                    Number.isFinite(value) && value >= 0 && value <= 1
                        ? `${(value * 100).toFixed(1)}%`
                        : null;

                const recentSnaps = snapPercent(availability.snap_share_l3);
                const longerSnaps = snapPercent(availability.snap_share_l8);

                if (recentSnaps) {
                    context.push(`Recent snap share: ${recentSnaps}`);
                }

                if (longerSnaps) {
                    context.push(`Historical snap share: ${longerSnaps}`);
                }

                const trend = availability.snap_share_trend_l3_l8;

                if (Number.isFinite(trend)) {
                    const percentagePoints = trend * 100;
                    context.push(
                        `Snap-share trend: ${percentagePoints >= 0 ? "+" : ""}${percentagePoints.toFixed(1)} pp`
                    );
                }

                if (availability.limited_snap_history === 1) {
                    context.push("Limited snap history");
                }

                lines.push(
                    context.length
                        ? `Player context: ${context.join(" | ")}`
                        : "Player context: No verified information available"
                );

                if (data.availability_affects_probabilities === false) {
                    lines.push("Player context does not adjust model probabilities");
                }
            }

            output.textContent = lines.join(" | ");

            const csrfToken = document.cookie
                .split("; ")
                .find(cookie => cookie.startsWith("csrftoken="))
                ?.substring("csrftoken=".length);

            if (!csrfToken) {
                output.textContent += " | Not saved (CSRF token unavailable)";
                return;
            }

            try {
                const saveUrl = new URL(
                    button.dataset.boomBustV2SaveUrl,
                    window.location.origin
                );
                saveUrl.searchParams.set("week", button.dataset.boomBustV2Week);

                const saveResponse = await fetch(saveUrl, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "Accept": "application/json",
                        "X-CSRFToken": decodeURIComponent(csrfToken),
                    },
                });

                const saved = await saveResponse.json();

                if (!saveResponse.ok || !saved.saved) {
                    throw new Error(saved.error || "Save failed");
                }

                output.textContent += " | Saved";
            } catch (saveError) {
                output.textContent += " | Not saved";
                console.error("Boom/Bust v2 save failed:", saveError);
            }
        } catch (error) {
            output.textContent = error.message || "Prediction unavailable.";
        } finally {
            button.disabled = false;
        }
    });
})();
