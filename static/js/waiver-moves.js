(() => {
    const moves = document.querySelector("[data-waiver-moves-url]");
    if (!moves) return;

    fetch(moves.dataset.waiverMovesUrl)
        .then(response => {
            if (!response.ok || response.redirected) throw new Error("Suggestions unavailable");
            return response.text();
        })
        .then(html => { moves.innerHTML = html; })
        .catch(() => { moves.textContent = "Suggested moves couldn’t load. Refresh the page to retry."; })
        .finally(() => { moves.removeAttribute("aria-busy"); });
})();
