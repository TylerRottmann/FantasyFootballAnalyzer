(() => {
    const dialog = document.getElementById('player-card-dialog');
    if (!dialog) return;
    const content = dialog.querySelector('[data-player-card-content]');
    let controller;
    let activeUrl;
    let opener;

    function selectTab(root, name) {
        root.querySelectorAll('[data-player-tab]').forEach(button => {
            const selected = button.dataset.playerTab === name;
            button.classList.toggle('is-active', selected);
            button.setAttribute('aria-pressed', String(selected));
        });
        root.querySelectorAll('[data-player-panel]').forEach(panel => { panel.hidden = panel.dataset.playerPanel !== name; });
    }
    window.playerCardUrl = id => dialog.dataset.urlTemplate.replace('/0/', `/${encodeURIComponent(id)}/`);

    async function openCard(url, tab = 'overview') {
        controller?.abort();
        controller = new AbortController();
        const request = controller;
        activeUrl = new URL(url, window.location.origin);
        if (activeUrl.origin !== window.location.origin) return;
        activeUrl.searchParams.set('fragment', '1');
        if (!activeUrl.searchParams.has('week')) {
            const week = new URL(window.location.href).searchParams.get('week');
            if (week) activeUrl.searchParams.set('week', week);
        }
        content.replaceChildren();
        const status = document.createElement('p');
        status.className = 'player-card-status';
        status.setAttribute('role', 'status');
        status.textContent = 'Loading player…';
        content.append(status);
        dialog.setAttribute('aria-label', 'Player overview');
        dialog.removeAttribute('aria-labelledby');
        if (!dialog.open) dialog.showModal();
        document.body.classList.add('player-card-open');
        try {
            const response = await fetch(activeUrl.href, {signal: request.signal, credentials: 'same-origin'});
            if (request !== controller) return;
            if (response.redirected || !response.ok) throw new Error('This player could not be loaded. Please refresh the page and try again.');
            const html = await response.text();
            if (request !== controller || !dialog.open) return;
            content.innerHTML = html;
            content.querySelector('#player-card-title').id = 'player-card-dialog-title';
            dialog.removeAttribute('aria-label');
            dialog.setAttribute('aria-labelledby', 'player-card-dialog-title');
            selectTab(content, tab);
        } catch (error) {
            if (error.name === 'AbortError' || request !== controller) return;
            status.textContent = error.message || 'Could not load this player. Please try again.';
            const retry = document.createElement('button');
            retry.type = 'button';
            retry.textContent = 'Try again';
            retry.addEventListener('click', () => openCard(activeUrl.href, tab));
            status.append(document.createTextNode(' '), retry);
        }
    }
    document.addEventListener('click', event => {
        const trigger = event.target.closest('.player-card-link');
        if (!trigger || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        const id = trigger.dataset.playerCard;
        let url = trigger.getAttribute('href') || (id && window.playerCardUrl(id));
        if (!url) return;
        if (trigger.dataset.playerWeek) {
            url = new URL(url, window.location.origin);
            url.searchParams.set('week', trigger.dataset.playerWeek);
        }
        event.preventDefault();
        event.stopPropagation();
        opener = trigger;
        openCard(url);
    }, true);
    dialog.querySelector('[data-player-card-close]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    dialog.addEventListener('close', () => { controller?.abort(); document.body.classList.remove('player-card-open'); if (opener?.isConnected) opener.focus(); });
    document.addEventListener('keydown', event => { if (dialog.open && event.key === 'Escape') event.stopPropagation(); }, true);
    document.addEventListener('click', event => {
        const tab = event.target.closest('[data-player-tab]');
        if (tab) selectTab(tab.closest('.pc-profile'), tab.dataset.playerTab);
    });
})();
