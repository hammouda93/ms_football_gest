(function () {
  "use strict";
  const root = document.getElementById("performance-control-center");
  if (!root) return;
  const url = root.dataset.historyUrl;
  const base = url.replace(/history\/$/, "");
  const $ = (id) => document.getElementById(id);
  const history = { kind: "sessions", page: 1, pages: 1, q: "", status: "", from: "", to: "", pending: 0 };

  function el(tag, text, cls) {
    const n = document.createElement(tag);
    if (text !== undefined && text !== null) n.textContent = String(text);
    if (cls) n.className = cls;
    return n;
  }
  function dateTime(x) {
    if (!x) return "—";
    const d = new Date(x);
    return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("fr-FR", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit"
    });
  }
  function statusLabel(raw) {
    return ({
      active: "Connecté", offline: "Hors ligne", stopped: "Arrêté",
      pending: "En attente", running: "En cours", success: "Terminé",
      partial: "Partiel", failed: "Échec", open: "À corriger",
      info: "Information", warning: "Avertissement", error: "Erreur",
      uploaded: "Publié", link_pending: "Lien en attente",
      downloaded: "Téléchargé", emailed: "Envoyé", not_requested: "Non demandé",
      generating: "En génération", discovered: "Détecté",
      synced: "Synchronisé", complete: "Complet"
    })[raw] || raw || "—";
  }
  function pill(raw) {
    return el("span", statusLabel(raw), "monitor-pill monitor-" + (raw || "unknown"));
  }
  function row(lines, status, action) {
    const button = el("button", null, "monitor-history-row");
    button.type = "button";
    const stack = el("span", null, "monitor-history-row-copy");
    lines.forEach(function (line, i) {
      stack.appendChild(el(i === 0 ? "strong" : "small", line));
    });
    button.appendChild(stack);
    if (status) button.appendChild(pill(status));
    if (action) button.addEventListener("click", action);
    return button;
  }
  function message(node, text) { node.replaceChildren(el("p", text, "monitor-empty")); }
  function paragraph(node, text) { node.appendChild(el("p", text, "monitor-detail-meta")); }

  async function fetchJson(input) {
    const response = await fetch(input, { credentials: "same-origin", headers: {
      "Accept": "application/json"
    }, cache: "no-store" });
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  }
  function queryUrl(query) {
    const u = new URL(url, window.location.href);
    for (const key in query) {
      if (query[key] !== undefined && query[key] !== null && query[key] !== "") {
        u.searchParams.set(key, String(query[key]));
      }
    }
    return u.toString();
  }
  function statusOptions() {
    const options = {
      sessions: [["", "Tous les états"], ["active", "Connecté"], ["offline", "Hors ligne"], ["stopped", "Arrêté"]],
      jobs: [["", "Tous les états"], ["pending", "En attente"], ["running", "En cours"], ["success", "Terminé"], ["partial", "Partiel"], ["failed", "Échec"]],
      events: [["", "Tous les niveaux"], ["info", "Information"], ["warning", "Avertissement"], ["error", "Erreur"]],
      issues: [["", "Tous les dossiers incomplets"], ["open", "À corriger"], ["pending", "À synchroniser"]]
    };
    const select = $("monitor-status");
    select.replaceChildren();
    (options[history.kind] || []).forEach(function (option) {
      const item = el("option", option[1]);
      item.value = option[0];
      select.appendChild(item);
    });
    history.status = "";
  }

  function makeIssueLabel(item) {
    return item.player + " · " + item.fixture + " · match " + item.match_id;
  }
  function renderListing(data) {
    history.pages = data.pages || 1;
    const container = $("monitor-history-results");
    container.replaceChildren();
    $("monitor-history-page").textContent = "Page " + data.page + " / " + history.pages +
      " · " + (data.total || 0) + " résultat(s)";
    $("monitor-history-previous").disabled = data.page <= 1;
    $("monitor-history-next").disabled = data.page >= history.pages;
    if (!data.items || !data.items.length) {
      message(container, "Aucun résultat pour les critères sélectionnés.");
      return;
    }
    data.items.forEach(function (item) {
      if (history.kind === "sessions") {
        container.appendChild(row(
          [item.worker + " · " + dateTime(item.started_at),
            "Plan initial : " + item.planned_jobs + " tâches · Dernier signal : " + dateTime(item.last_seen_at)],
          item.status, function () { showSession(item.id); }
        ));
      } else if (history.kind === "jobs") {
        container.appendChild(row(
          [item.player + " · tâche #" + item.id + " · " + item.type,
            dateTime(item.created_at) + " → " + dateTime(item.finished_at) +
            (item.error ? " · " + item.error : "")],
          item.status, function () { showJob(item.id); }
        ));
      } else if (history.kind === "events") {
        container.appendChild(row(
          [dateTime(item.at) + " · " + item.message,
            [item.worker, item.player, item.match_id ? "Match " + item.match_id : "",
              item.stage].filter(Boolean).join(" · ")],
          item.level, function () {
            if (item.job_id) showJob(item.job_id);
            else showSession(item.run_id);
          }
        ));
      } else {
        container.appendChild(row(
          [makeIssueLabel(item), item.reasons.join(" · ")],
          item.issue_state, function () { showIssue(item); }
        ));
      }
    });
  }
  async function loadHistory() {
    const ticket = ++history.pending;
    const results = $("monitor-history-results");
    message(results, "Chargement des résultats…");
    try {
      const result = await fetchJson(queryUrl({
        kind: history.kind, page: history.page, q: history.q,
        status: history.status, from: history.from, to: history.to
      }));
      if (ticket !== history.pending) return;
      renderListing(result);
    } catch (error) {
      if (ticket === history.pending) message(results, "Impossible de lire l'historique (" + error.message + ").");
    }
  }
  function heading(node, text) { node.appendChild(el("h4", text)); }
  function chronological(node, events) {
    if (!events.length) {
      paragraph(node, "Aucune étape détaillée observée pour cette sélection.");
      return;
    }
    events.forEach(function (event) {
      const item = el("div", null, "monitor-detail-event monitor-event-" + event.level);
      item.appendChild(el("time", dateTime(event.at)));
      const inner = el("div");
      inner.appendChild(el("strong", event.message));
      inner.appendChild(el("small", [event.player, event.match_id ? "Match " + event.match_id : "", event.stage]
        .filter(Boolean).join(" · ")));
      item.appendChild(inner);
      node.appendChild(item);
    });
  }
  function detailsContainer(title) {
    const box = $("monitor-history-detail");
    box.hidden = false;
    box.replaceChildren();
    const top = el("div", null, "monitor-detail-header");
    top.appendChild(el("h3", title));
    const close = el("button", "Fermer ×", "btn btn-sm btn-outline-secondary");
    close.type = "button";
    close.addEventListener("click", function () { box.hidden = true; });
    top.appendChild(close);
    box.appendChild(top);
    box.scrollIntoView({ block: "nearest", behavior: "smooth" });
    return box;
  }
  async function showSession(id) {
    const box = detailsContainer("Session Windows");
    paragraph(box, "Chargement du détail de session…");
    try {
      const [detail, log] = await Promise.all([
        fetchJson(base + "session/" + encodeURIComponent(id) + "/"),
        fetchJson(queryUrl({ kind: "events", run_id: id, page: 1 }))
      ]);
      box.replaceChildren(box.firstChild);
      const run = detail.session;
      paragraph(box, run.worker + " · " + dateTime(run.started_at) +
        " → " + dateTime(run.ended_at) + " · " + statusLabel(run.status));
      paragraph(box, "Dernier signal : " + dateTime(run.last_seen_at) +
        " · " + detail.events_total + " événements horodatés.");
      heading(box, "Joueurs prévus au démarrage (" + detail.planned_players.length + ")");
      if (!detail.planned_players.length) paragraph(box, "Plan initial non observé pour cette session.");
      detail.planned_players.forEach(function (player) {
        box.appendChild(row(["#" + player.job_id + " · " + player.player], null,
          function () { showJob(player.job_id); }));
      });
      heading(box, "Joueurs pris en charge (" + detail.processed_players.length + ")");
      if (!detail.processed_players.length) paragraph(box, "Aucun début de tâche observé.");
      detail.processed_players.forEach(function (player) {
        box.appendChild(row(["#" + player.job_id + " · " + player.player], null,
          function () { showJob(player.job_id); }));
      });
      heading(box, "Événements de la session — " + log.total + " au total");
      chronological(box, log.items);
      if (log.pages > 1) {
        paragraph(box, "Les 20 derniers événements sont affichés ici. L'onglet Journal complet permet de parcourir l'ensemble.");
      }
    } catch (error) {
      paragraph(box, "Détail indisponible : " + error.message);
    }
  }
  function stage(node, title, message, ok) {
    const line = el("div", null, "monitor-stage");
    line.appendChild(el("strong", title));
    line.appendChild(el("span", message, ok === true ? "monitor-stage-good" :
      ok === false ? "monitor-stage-warning" : "monitor-subtle"));
    node.appendChild(line);
  }
  async function showJob(id) {
    const box = detailsContainer("Tâche Performance #" + id);
    paragraph(box, "Chargement des détails par joueur et par match…");
    try {
      const [detail, log] = await Promise.all([
        fetchJson(base + "job/" + encodeURIComponent(id) + "/"),
        fetchJson(queryUrl({ kind: "events", job_id: id, page: 1 }))
      ]);
      box.replaceChildren(box.firstChild);
      const job = detail.job;
      paragraph(box, job.player + " · " + job.type + " · " + statusLabel(job.status));
      paragraph(box, "Créée " + dateTime(job.created_at) + " · démarrée " +
        dateTime(job.started_at) + " · terminée " + dateTime(job.finished_at) +
        " · tentatives : " + job.attempts);
      if (job.error) paragraph(box, "Erreur enregistrée : " + job.error);
      heading(box, "Étapes observées");
      const observed = log.items.map(function (event) { return (event.stage || "").toLowerCase(); });
      [
        ["Connexion navigateur", "connexion"],
        ["Profil / saison", "profil"],
        ["Collecte des statistiques Players", "xlsx"],
        ["All Actions", "vidéo"],
        ["Rapport PDF", "pdf"],
        ["Publication", "publication"]
      ].forEach(function (part) {
        const seen = observed.some(function (name) { return name.indexOf(part[1]) >= 0; });
        stage(box, part[0], seen ? "Événement observé" :
          "Non observé (cela ne signifie pas un échec)", seen ? true : null);
      });
      heading(box, "Matchs associés à cette exécution (" + detail.matches.length + ")");
      if (!detail.matches.length) paragraph(box, "Aucun match dans le résultat enregistré de cette tâche.");
      detail.matches.forEach(function (match) {
        const section = el("details", null, "monitor-match-details");
        section.appendChild(el("summary", match.fixture + " · " + match.match_id));
        stage(section, "Données Players", match.kpis_found + "/" + match.kpis_required + " KPI contractuels", match.statistics_complete);
        stage(section, "Analyse", match.analysis_available ? "Disponible dans Heroku" : "Incomplète ou absente", match.analysis_available);
        stage(section, "Rapport PDF", match.analysis_available ?
          "Rapport analysé; présence du fichier Windows non vérifiable ici" :
          "Analyse non disponible (PDF potentiellement vide)", match.analysis_available);
        stage(section, "All Actions", statusLabel(match.video_state) +
          " — présence physique du fichier Windows non vérifiable", match.video_state === "downloaded" || match.video_state === "emailed");
        stage(section, "YouTube / Dailymotion", statusLabel(match.youtube) + " / " +
          statusLabel(match.dailymotion), null);
        const related = log.items.filter(function (ev) { return ev.match_id === match.match_id; });
        if (related.length) { heading(section, "Événements observés sur ce match"); chronological(section, related); }
        box.appendChild(section);
      });
      heading(box, "Journal de la tâche (" + log.total + " événements)");
      chronological(box, log.items);
      paragraph(box, detail.note);
      if (log.pages > 1) paragraph(box, "Afficher les autres pages dans l'onglet Journal complet.");
    } catch (error) {
      paragraph(box, "Détail indisponible : " + error.message);
    }
  }
  function showIssue(item) {
    const box = detailsContainer("Dossier à compléter · " + item.player);
    paragraph(box, item.fixture + " · match " + item.match_id + " · " + statusLabel(item.issue_state));
    item.reasons.forEach(function (reason) { stage(box, "À résoudre", reason, false); });
    stage(box, "Statistiques Players", item.kpis_found + "/" + item.kpis_required, item.statistics_complete);
    stage(box, "Analyse", item.analysis_available ? "Disponible" : "Indisponible", item.analysis_available);
    stage(box, "All Actions", statusLabel(item.video_state), null);
    paragraph(box, "Dernière mise à jour : " + dateTime(item.updated_at));
    paragraph(box, "La présence du MP4 ou du PDF sur Windows ne peut pas être attestée depuis Heroku.");
  }
  function selectKind(kind) {
    history.kind = kind; history.page = 1;
    $("monitor-history-detail").hidden = true;
    root.querySelectorAll("[data-monitor-kind]").forEach(function (tab) {
      tab.classList.toggle("is-selected", tab.dataset.monitorKind === kind);
      tab.setAttribute("aria-pressed", String(tab.dataset.monitorKind === kind));
    });
    statusOptions();
    loadHistory();
  }
  root.querySelectorAll("[data-monitor-kind]").forEach(function (tab) {
    tab.addEventListener("click", function () { selectKind(tab.dataset.monitorKind); });
  });
  $("monitor-history-form").addEventListener("submit", function (event) {
    event.preventDefault();
    history.q = $("monitor-search").value.trim().slice(0, 100);
    history.from = $("monitor-date-from").value;
    history.to = $("monitor-date-to").value;
    history.status = $("monitor-status").value;
    history.page = 1;
    $("monitor-history-detail").hidden = true;
    loadHistory();
  });
  $("monitor-clear").addEventListener("click", function () {
    $("monitor-search").value = "";
    $("monitor-date-from").value = "";
    $("monitor-date-to").value = "";
    history.q = history.from = history.to = history.status = "";
    history.page = 1;
    statusOptions();
    loadHistory();
  });
  $("monitor-history-previous").addEventListener("click", function () {
    if (history.page > 1) { history.page--; loadHistory(); }
  });
  $("monitor-history-next").addEventListener("click", function () {
    if (history.page < history.pages) { history.page++; loadHistory(); }
  });
  statusOptions();
  loadHistory();
})();
