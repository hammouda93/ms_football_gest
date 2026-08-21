(function () {
    'use strict';

    const root = document.getElementById('deadline-planning-assistant');
    const deadlineInput = document.getElementById('id_deadline');
    if (!root || !deadlineInput) return;

    const editorInput = document.getElementById('id_editor');
    const endpoint = root.dataset.endpoint;
    const mode = root.dataset.mode || 'create';
    const excludeVideoId = root.dataset.excludeVideoId || '';
    let currentRequest = null;

    const deadlineGroup = document.getElementById('div_id_deadline') || deadlineInput.closest('.form-group');
    if (deadlineGroup && deadlineGroup.nextElementSibling !== root) {
        deadlineGroup.insertAdjacentElement('afterend', root);
    }

    function role(name) {
        return root.querySelector(`[data-role="${name}"]`);
    }

    function setText(name, value) {
        const element = role(name);
        if (element) element.textContent = value;
    }

    function setLoading(isLoading) {
        role('loading').hidden = !isLoading;
        role('content').hidden = isLoading;
        if (isLoading) role('error').hidden = true;
    }

    function loadText(count) {
        return `${count} vidéo${count > 1 ? 's' : ''}`;
    }

    function makeEmpty(message) {
        const empty = document.createElement('div');
        empty.className = 'deadline-empty';
        empty.textContent = message;
        return empty;
    }

    function chooseDate(value) {
        deadlineInput.value = value;
        deadlineInput.dispatchEvent(new Event('change', { bubbles: true }));
        deadlineInput.focus({ preventScroll: true });
    }

    function renderSuggestions(items) {
        const container = role('suggestions');
        container.replaceChildren();
        if (!items.length) {
            container.appendChild(makeEmpty('Aucune autre date disponible dans cette période.'));
            return;
        }
        items.forEach(function (item) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'deadline-suggestion';
            button.title = `Choisir le ${item.date_label}`;

            const copy = document.createElement('span');
            const title = document.createElement('strong');
            const detail = document.createElement('small');
            title.textContent = item.date_label;
            detail.textContent = `${item.load_label} · ${item.reason}`;
            copy.append(title, detail);

            const icon = document.createElement('i');
            icon.className = 'fas fa-arrow-right';
            icon.setAttribute('aria-hidden', 'true');
            button.append(copy, icon);
            button.addEventListener('click', function () { chooseDate(item.date); });
            container.appendChild(button);
        });
    }

    function renderCalendar(days, hasEditor) {
        const container = role('calendar');
        container.replaceChildren();
        days.forEach(function (day) {
            const button = document.createElement('button');
            const count = hasEditor ? day.editor_count : day.global_count;
            button.type = 'button';
            button.className = `deadline-calendar-day load-${day.tone}`;
            if (day.is_selected) button.classList.add('is-selected');
            if (day.is_today) button.classList.add('is-today');
            button.title = `${day.date_label} — ${day.load_label}, ${loadText(count)}`;
            button.setAttribute('aria-label', button.title);

            const weekday = document.createElement('span');
            const number = document.createElement('strong');
            const month = document.createElement('span');
            const load = document.createElement('span');
            weekday.className = 'deadline-day-week';
            number.className = 'deadline-day-number';
            month.className = 'deadline-day-month';
            load.className = 'deadline-day-load';
            weekday.textContent = day.weekday;
            number.textContent = day.day;
            month.textContent = day.month;
            load.textContent = count ? loadText(count) : 'Libre';
            button.append(weekday, number, month, load);
            button.addEventListener('click', function () { chooseDate(day.date); });
            container.appendChild(button);
        });
    }

    function renderVideoList(containerName, videos, emptyMessage) {
        const container = role(containerName);
        container.replaceChildren();
        if (!videos.length) {
            container.appendChild(makeEmpty(emptyMessage));
            return;
        }
        videos.forEach(function (video) {
            const row = document.createElement('a');
            row.className = 'deadline-video-row';
            row.href = video.edit_url;

            const copy = document.createElement('span');
            copy.className = 'deadline-video-copy';
            const player = document.createElement('strong');
            const detail = document.createElement('small');
            player.textContent = video.player;
            detail.textContent = `${video.deadline_label} · ${video.editor} · ${video.seasons} saison${video.seasons > 1 ? 's' : ''}`;
            copy.append(player, detail);

            const status = document.createElement('span');
            status.className = `deadline-status-chip ${video.status_tone}`;
            status.textContent = video.status_label;
            row.append(copy, status);
            container.appendChild(row);
        });
    }

    function updatePastWarning(payload) {
        const warning = role('past-warning');
        if (mode === 'edit' && payload.selection.is_past) {
            const lateDays = Math.abs(payload.selection.days_from_today);
            setText(
                'past-warning-copy',
                `Elle est dépassée de ${lateDays} jour${lateDays > 1 ? 's' : ''}. Vous pouvez quand même mettre la vidéo à jour.`
            );
            warning.hidden = false;
        } else {
            warning.hidden = true;
        }
    }

    function render(payload) {
        const hasChosenDate = Boolean(deadlineInput.value);
        const hasEditor = Boolean(payload.selected_editor.id);
        const selection = payload.selection;
        const score = hasEditor ? selection.editor_score : selection.global_score;
        const dayCount = hasEditor ? selection.editor_count : selection.global_count;
        const windowCount = hasEditor ? selection.window_editor_count : selection.window_count;

        setText('active-count', payload.summary.active_count);
        setText('week-count', payload.summary.next_7_days_count);
        setText('overdue-count', payload.summary.overdue_count);
        setText('finishing-count', payload.summary.finishing_count);
        setText('selection-eyebrow', hasChosenDate ? 'Analyse de votre choix' : 'Aperçu à 7 jours');
        setText('selection-date', selection.date_label);
        setText(
            'selection-copy',
            `${loadText(dayCount)} ce jour · ${loadText(windowCount)} sur la période de ± 2 jours · ${payload.selected_editor.name}`
        );
        setText('load-score', Number(score).toLocaleString('fr-FR', { maximumFractionDigits: 1 }));
        setText('editor-scope', payload.selected_editor.name);
        setText('period-count', payload.period_videos.length);
        setText('attention-count', payload.attention_videos.length);
        setText('method-note', payload.method_note);

        const pill = role('load-pill');
        pill.textContent = selection.load_label;
        pill.className = `deadline-load-pill load-${selection.tone}`;

        updatePastWarning(payload);
        renderSuggestions(payload.suggestions);
        renderCalendar(payload.calendar, hasEditor);
        renderVideoList('period-videos', payload.period_videos, 'Aucune deadline active dans cette fenêtre.');
        renderVideoList('attention-videos', payload.attention_videos, 'Aucune deadline active dépassée.');
    }

    function refresh() {
        if (currentRequest) currentRequest.abort();
        currentRequest = new AbortController();
        setLoading(true);

        const url = new URL(endpoint, window.location.origin);
        if (deadlineInput.value) url.searchParams.set('date', deadlineInput.value);
        if (editorInput && editorInput.value) url.searchParams.set('editor_id', editorInput.value);
        if (excludeVideoId) url.searchParams.set('exclude_video_id', excludeVideoId);

        fetch(url.toString(), {
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            signal: currentRequest.signal
        })
        .then(function (response) {
            if (!response.ok) throw new Error('deadline-planning-unavailable');
            return response.json();
        })
        .then(function (payload) {
            render(payload);
            role('content').hidden = false;
            role('loading').hidden = true;
            role('error').hidden = true;
        })
        .catch(function (error) {
            if (error.name === 'AbortError') return;
            role('loading').hidden = true;
            role('content').hidden = true;
            role('error').hidden = false;
        });
    }

    deadlineInput.addEventListener('change', refresh);
    if (editorInput) editorInput.addEventListener('change', refresh);
    refresh();
})();
