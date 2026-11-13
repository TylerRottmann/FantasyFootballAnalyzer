(() => {
    const page = document.querySelector(".page-content");
    const shell = document.querySelector(".page-loading");
    const title = shell.querySelector(".page-loading-title");
    const hero = shell.querySelector(".page-loading-hero");
    const status = shell.querySelector(".page-loading-status");
    const nav = document.querySelector(".main-nav");
    let timer;
    let pendingLink;

    function reset() {
        window.clearTimeout(timer);
        pendingLink?.classList.remove("is-pending");
        pendingLink = undefined;
        shell.hidden = true;
        page.inert = false;
        status.textContent = "";
    }

    function show(label, view = "") {
        const pageTitle = label || document.querySelector(".page-content h1")?.textContent.trim() || "Roster Radar";
        shell.dataset.view = view;
        hero.classList.toggle("radar-hero--waivers", view === "waivers");
        title.textContent = pageTitle;
        window.clearTimeout(timer);
        shell.style.setProperty("--page-loading-top", Math.max(0, nav.getBoundingClientRect().bottom) + "px");
        shell.hidden = false;
        page.inert = true;
        status.textContent = "Loading " + title.textContent;
        timer = window.setTimeout(reset, 30000);
    }

    function isLocal(url, target) {
        return url.origin === window.location.origin &&
            (url.protocol === "http:" || url.protocol === "https:") &&
            (!target || target === "_self");
    }

    function skipsLoader(url, link) {
        return link?.hasAttribute("data-skip-page-loader") ||
            Array.from(nav.querySelectorAll("[data-skip-page-loader]")).some(tab =>
                (tab.classList.contains("active") && url.pathname === window.location.pathname) ||
                (tab.dataset.skipPageLoader !== "fallback" && url.pathname.startsWith(tab.pathname))
            );
    }

    window.addEventListener("click", event => {
        if (event.defaultPrevented || event.button !== 0 ||
            event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;

        const link = event.target.closest("a[href]");
        if (!link || link.hasAttribute("download") || link.closest(".week-picker")) return;
        const url = new URL(link.href, window.location.href);
        if (!isLocal(url, link.target)) return;
        if (url.pathname === window.location.pathname && url.search === window.location.search) return;

        if (link.matches(".main-nav .nav-link")) {
            reset();
            pendingLink = link;
            pendingLink.classList.add("is-pending");
        }
        if (skipsLoader(url, link)) {
            if (pendingLink) timer = window.setTimeout(reset, 30000);
            return;
        }
        show(link.matches(".main-nav a, .brand") ? link.textContent.trim().replace(/\s+/g, " ") : "", link.dataset.loadingView);
    });

    window.addEventListener("submit", event => {
        const form = event.target;
        const target = event.submitter?.getAttribute("formtarget") ?? form.target;
        const action = event.submitter?.getAttribute("formaction") ?? form.action;
        const method = event.submitter?.getAttribute("formmethod") ?? form.method;
        const url = new URL(action, window.location.href);
        if (!event.defaultPrevented && method.toLowerCase() === "get" &&
            isLocal(url, target) && !skipsLoader(url)) show("");
    });

    window.addEventListener("pageshow", reset);
})();
