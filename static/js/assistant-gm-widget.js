(() => {
    const widget = document.querySelector(".assistant-gm-widget");
    if (!widget) return;

    const panel = widget.querySelector(".assistant-gm-panel");
    const launcher = widget.querySelector(".assistant-gm-launcher");
    const closeButton = widget.querySelector("[data-gm-close]");
    const resetButton = widget.querySelector("[data-gm-reset]");
    const form = widget.querySelector("[data-gm-form]");
    const input = form.querySelector("textarea[name='message']");
    const send = widget.querySelector("[data-gm-send]");
    const messages = widget.querySelector("[data-gm-messages]");
    const endpoint = widget.dataset.chatUrl;
    const csrfToken = form.querySelector("[name='csrfmiddlewaretoken']").value;
    const storageKey = `roster-radar-assistant-gm-${widget.dataset.userId}`;
    let transcript = [];

    function persist() {
        try {
            sessionStorage.setItem(storageKey, JSON.stringify(transcript.slice(-40)));
        } catch (_) {
            // The chat remains usable if browser storage is disabled or full.
        }
    }

    function appendMessage(text, role, players = [], week = null, save = true) {
        const entry = {text: String(text || ""), role, players: Array.isArray(players) ? players : [], week};
        const bubble = document.createElement("div");
        bubble.className = `assistant-gm-widget-message ${role}`;
        const playerMap = new Map(entry.players.map(player => [String(player.name || "").toLowerCase(), player]));
        const names = entry.players.map(player => String(player.name || ""))
            .filter(Boolean)
            .sort((a, b) => b.length - a.length)
            .map(name => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));

        if (!names.length) {
            bubble.textContent = entry.text;
        } else {
            const pattern = new RegExp(`(?<![a-z])(${names.join("|")})(?![a-z])`, "gi");
            let cursor = 0;
            for (const match of entry.text.matchAll(pattern)) {
                bubble.append(document.createTextNode(entry.text.slice(cursor, match.index)));
                const player = playerMap.get(match[0].toLowerCase());
                const link = document.createElement("button");
                link.type = "button";
                link.className = "player-card-link";
                link.dataset.playerCard = player.id;
                if (entry.week != null) link.dataset.playerWeek = entry.week;
                link.textContent = match[0];
                bubble.append(link);
                cursor = match.index + match[0].length;
            }
            bubble.append(document.createTextNode(entry.text.slice(cursor)));
        }

        messages.append(bubble);
        messages.scrollTop = messages.scrollHeight;
        if (save) {
            transcript.push(entry);
            persist();
        }
        return bubble;
    }

    function restoreTranscript() {
        try {
            const saved = JSON.parse(sessionStorage.getItem(storageKey) || "[]");
            if (Array.isArray(saved)) transcript = saved.slice(-40);
        } catch (_) {
            transcript = [];
        }
        if (!transcript.length) {
            appendMessage(widget.dataset.welcome, "bot");
            return;
        }
        transcript.forEach(entry => appendMessage(entry.text, entry.role, entry.players, entry.week, false));
    }

    function setOpen(open) {
        panel.hidden = !open;
        launcher.setAttribute("aria-expanded", String(open));
        launcher.setAttribute("aria-label", open ? "Close Assistant GM" : "Open Assistant GM");
        launcher.innerHTML = open
            ? '<i class="bi bi-x-lg" aria-hidden="true"></i><span class="assistant-gm-launcher-label">Close Assistant GM</span>'
            : '<i class="bi bi-chat-dots-fill" aria-hidden="true"></i><span class="assistant-gm-launcher-label">Assistant GM</span>';
        if (open) input.focus();
    }

    async function post(values) {
        const body = new URLSearchParams(values);
        body.set("csrfmiddlewaretoken", csrfToken);
        const response = await fetch(endpoint, {
            method: "POST",
            headers: {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Accept": "application/json"},
            body: body.toString(),
            credentials: "same-origin",
        });
        const data = await response.json();
        if (!response.ok || response.redirected) throw new Error(data.error || "Assistant GM could not respond. Please try again.");
        return data;
    }

    async function ask(question) {
        const value = String(question || "").trim();
        if (!value || send.disabled) return;
        appendMessage(value, "user");
        input.value = "";
        send.disabled = true;
        send.innerHTML = '<i class="bi bi-hourglass-split" aria-hidden="true"></i>';
        try {
            const data = await post({message: value});
            appendMessage(data.answer || data.error || "Sorry, something went wrong.", "bot", data.players || [], data.week);
        } catch (error) {
            appendMessage(error.message || "I couldn’t reach the server. Please try again.", "bot");
        } finally {
            send.disabled = false;
            send.innerHTML = '<i class="bi bi-arrow-up" aria-hidden="true"></i>';
            input.focus();
        }
    }

    launcher.addEventListener("click", () => setOpen(panel.hidden));
    closeButton.addEventListener("click", () => { setOpen(false); launcher.focus(); });
    panel.querySelectorAll("[data-question]").forEach(button => {
        button.addEventListener("click", () => ask(button.dataset.question));
    });
    form.addEventListener("submit", event => {
        event.preventDefault();
        ask(input.value);
    });
    input.addEventListener("keydown", event => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            form.requestSubmit();
        }
    });
    resetButton.addEventListener("click", async () => {
        resetButton.disabled = true;
        try {
            await post({reset: "1"});
            transcript = [];
            messages.replaceChildren();
            try { sessionStorage.removeItem(storageKey); } catch (_) {}
            appendMessage(widget.dataset.welcome, "bot");
        } catch (_) {
            appendMessage("I couldn't start a new chat. Please try again.", "bot");
        } finally {
            resetButton.disabled = false;
        }
    });
    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && !panel.hidden) {
            setOpen(false);
            launcher.focus();
        }
    });

    restoreTranscript();
})();
