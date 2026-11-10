(() => {
    const lineup = document.querySelector(".lineup-layout");
    const status = document.querySelector(".lineup-loading-status");
    if (!lineup || !status) return;

    const warmUrl = document.querySelector("[data-waiver-warm-url]")?.dataset.waiverWarmUrl;
    if (warmUrl && !navigator.connection?.saveData) {
        const warm = () => { fetch(warmUrl, { cache: "no-store", priority: "low" }).catch(() => {}); };
        if (document.readyState === "complete") window.setTimeout(warm, 400);
        else window.addEventListener("load", () => window.setTimeout(warm, 400), { once: true });
    }

    let resetTimer;

    function resetLoading() {
        window.clearTimeout(resetTimer);
        lineup.classList.remove("is-loading");
        lineup.removeAttribute("aria-busy");
        lineup.inert = false;
        status.textContent = "";
    }

    document.addEventListener("click", event => {
        const link = event.target.closest(".week-picker a");
        if (!link || event.defaultPrevented || event.button !== 0 ||
            event.altKey || event.ctrlKey || event.metaKey || event.shiftKey ||
            (link.target && link.target !== "_self") || link.hasAttribute("download") ||
            link.href === window.location.href) {
            return;
        }

        window.clearTimeout(resetTimer);
        lineup.setAttribute("aria-busy", "true");
        lineup.classList.add("is-loading");
        lineup.inert = true;
        status.textContent = "Loading lineup";
        resetTimer = window.setTimeout(resetLoading, 30000);
    });

    window.addEventListener("pageshow", resetLoading);
})();
