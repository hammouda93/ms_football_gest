(function () {
  "use strict";
  const root = document.getElementById("performance-control-center");
  if (!root) return;

  const sourceUrl = root.dataset.monitorUrl;
  const $ = (id) => document.getElementById(id);
  const state = { data: null, filter: "all", refreshTimer: null };

  function setText(id, value) {
    const node = $(id);
    if (node) node.textContent = String(value == null ? "—" : value);
  }
  function time(value) {
    if (!value) return "—";
    const d = new Date(value);
    return isNaN(d.getTime()) ? "—" : d.toLocaleString("fr-FR", {
      day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
      second: "2-digit"
    });
  }
  function span(value, className) {
    const e = document.createElement("span");
    e.textContent = String(value == null ? "" : value);
    if (className) e.className = className;
    return e;
  }
  function empty(container, message) {
    container.replaceChildren(span(message, "monitor-empty"));
  }
  function card(container, children, className) {
    const article = document.createElement("article");
    article.className = className;
    children.forEach((item) => article.appendChild(item));
    container.appendChild(article);
  }

  function drawWorkers(data) {
    const container = $("monitor-worker-list");
    container.replaceChildren();
    if (!data.workers.length) {
      empty(container, "Aucune session de supervision reçue. Le bouton Agent Performance reste utilisable normalement.");
      return;
    }
    for (const worker of data.workers) {
      const title = document.createElement("strong");
      title.textContent = worker.name;
      const status = span(
        worker.state === "active" ? "Connecté" :
          worker.state === "offline" ? "Signal perdu" : "Arrêté",
        "monitor-pill monitor-" + worker.state
      );
      const main = document.createElement("div");
      main.className = "monitor-worker-header";
      main.append(title, status);
      const details = span("Démarrage : " + time(worker.started_at) +
        " · Dernier signal : " + time(worker.last_seen_at), "monitor-subtle");
      const progress = span(
        worker.state === "active" ?
          ((worker.current_player || "Agent disponible") +
            " · " + (worker.stage || "En attente de progression") +
            (worker.current_match_id ? " · Match " + worker.current_match_id : "")) :
          (worker.state === "offline" ? "Activité non confirmée : aucun signal récent" : "Session terminée"),
        "monitor-worker-current"
      );
      const counters = span("Tâches prévues : " + worker.planned_jobs +
        " · Terminées pendant la session : " + worker.finished_jobs, "monitor-subtle");
      card(container, [main, details, progress, counters], "monitor-worker-card");
    }
  }

  function drawEvents(data) {
    const container = $("monitor-event-list");
    container.replaceChildren();
    const filtered = data.events.filter((event) =>
      state.filter === "all" || event.level === state.filter
    );
    if (!filtered.length) {
      empty(container, "Aucun événement enregistré pour cette session et ce filtre.");
      return;
    }
    for (const event of filtered) {
      const left = span(time(event.at), "monitor-event-time");
      const body = document.createElement("div");
      const line = span(event.message, "monitor-event-message");
      const metadata = span(
        [event.player, event.match_id ? "match " + event.match_id : "",
          event.stage].filter(Boolean).join(" · "),
        "monitor-subtle"
      );
      body.append(line, metadata);
      card(container, [left, body], "monitor-event-row monitor-event-" + event.level);
    }
  }

  function drawJobs(data) {
    const container = $("monitor-task-list");
    container.replaceChildren();
    const pending = data.jobs.filter((job) => job.status === "running" || job.status === "pending");
    if (!pending.length) {
      empty(container, "Aucune tâche Performance en attente ou en cours.");
      return;
    }
    pending.reverse();
    for (const job of pending.slice(0, 50)) {
      const text = span(job.player + " · " + job.type, "monitor-task-name");
      const pill = span(
        job.status === "running" ? "En cours" : "En attente",
        "monitor-pill monitor-" + job.status
      );
      card(container, [text, pill], "monitor-task-row");
    }
  }

  function drawMissing(data) {
    const container = $("monitor-missing-list");
    container.replaceChildren();
    if (!data.missing_matches.length) {
      empty(container, "Aucune anomalie détectée parmi les matchs récemment mis à jour.");
      return;
    }
    for (const match of data.missing_matches) {
      const body = document.createElement("div");
      body.append(
        span(match.player + " — " + match.match, "monitor-task-name"),
        span("Match " + match.match_id, "monitor-subtle")
      );
      const details = span(
        (match.statistics ? "XLSX présent" : "Statistiques manquantes") + " · " +
        (match.analysis ? "Analyse présente" : "Analyse PDF indisponible") + " · " +
        "Vidéo : " + match.all_actions, "monitor-subtle"
      );
      card(container, [body, details], "monitor-missing-row");
    }
  }

  function render(data) {
    state.data = data;
    setText("monitor-count-subs", data.metrics.subscriptions);
    setText("monitor-count-waiting", data.metrics.waiting);
    setText("monitor-count-running", data.metrics.running);
    setText("monitor-count-problems", data.metrics.partial + data.metrics.failed);
    setText("monitor-last-refresh", "Dernière actualisation : " + time(data.now));
    drawWorkers(data);
    drawEvents(data);
    drawJobs(data);
    drawMissing(data);
  }

  async function refresh() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(sourceUrl, {
        credentials: "same-origin", cache: "no-store",
        headers: { "Accept": "application/json" }, signal: controller.signal
      });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const data = await response.json();
      render(data);
      setText("monitor-connection", "Supervision connectée");
    } catch (_error) {
      setText("monitor-connection", "Supervision indisponible — agent non affecté");
    } finally {
      clearTimeout(timeout);
    }
  }
  $("monitor-refresh").addEventListener("click", refresh);
  $("monitor-event-filter").addEventListener("change", function (event) {
    state.filter = event.target.value;
    if (state.data) drawEvents(state.data);
  });
  refresh();
  state.refreshTimer = setInterval(function () {
    if (document.visibilityState !== "hidden") refresh();
  }, 10000);
})();
