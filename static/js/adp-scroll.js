(() => {
    const page = document.querySelector(".adp-page");
    const rows = page.querySelector("tbody");
    const more = page.querySelector(".adp-load-more");
    const status = page.querySelector(".adp-loading-status");
    const team = page.querySelector('select[name="team"]');
    const placeholders = Array.from(rows.children);
    let initial = true;
    let loading = false;

    const observer = typeof IntersectionObserver === "function"
        ? new IntersectionObserver(entries => {
            if (entries.some(entry => entry.isIntersecting)) load();
        })
        : null;

    async function load() {
        if (loading || more.hidden) return;
        loading = true;
        observer?.unobserve(more);
        more.hidden = true;
        rows.setAttribute("aria-busy", "true");
        status.textContent = initial ? "Loading rankings" : "Loading more players";
        if (!initial || !rows.children.length) {
            rows.append(...placeholders.map(row => row.cloneNode(true)));
        }

        try {
            const response = await fetch(more.href);
            if (!response.ok) throw new Error("Rankings request failed");
            const batch = new DOMParser().parseFromString(await response.text(), "text/html");
            const incoming = batch.querySelector(".adp-table tbody");
            if (!incoming?.children.length) throw new Error("Rankings missing");
            const next = batch.querySelector(".adp-next-page");

            rows.querySelectorAll(".adp-skeleton").forEach(row => row.remove());
            rows.append(...incoming.children);
            if (initial) {
                team.replaceChildren(...batch.querySelector('select[name="team"]').children);
                initial = false;
            }
            status.textContent = "";
            if (next) {
                more.href = new URL(next.getAttribute("href"), response.url).href;
                more.textContent = "Load more players";
                more.hidden = false;
                observer?.observe(more);
            }
        } catch {
            rows.querySelectorAll(".adp-skeleton").forEach(row => row.remove());
            status.textContent = "Couldn’t load rankings. Try again.";
            more.textContent = "Try again";
            more.hidden = false;
        } finally {
            rows.removeAttribute("aria-busy");
            loading = false;
        }
    }

    more.addEventListener("click", event => {
        if (event.button !== 0 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
        event.preventDefault();
        load();
    });

    load();
})();
