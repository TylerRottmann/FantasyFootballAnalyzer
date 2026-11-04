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
            output.textContent = [
                `Week ${data.week}`,
                format("boom"),
                format("normal"),
                format("bust"),
            ].join(" | ");
        } catch (error) {
            output.textContent = error.message || "Prediction unavailable.";
        } finally {
            button.disabled = false;
        }
    });
})();
