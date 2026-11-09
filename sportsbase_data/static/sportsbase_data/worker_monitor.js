(function () {
  "use strict";
  const root = document.getElementById("performance-control-center");
  if (!root) return;

  const sourceUrl = root.dataset.monitorUrl;
  const $ = (id) => document.getElementById(id);

  function setText(id, value) {
    const node = $(id);
    if (node) node.textContent = String(value == null ? "—" : value);
  }

  function time(value) {
    if (!value) return "—";
    const date = new Date(value);
    return isNaN(date.getTime()) ? "—" : date.toLocaleString("fr-FR", {
      day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit"
    });
  }

  function span(text, className) {
    const node = document.createElement("span");
    node.textContent = String(text == null ? "" : text);
    if (className) node.className = className;
    return node;
  }

  function empty(node, message) {
    node.replaceChildren(span(message, "monitor-empty"));
  }

  function drawJobs(jobs) {
    const container = $("monitor-task-list");
    container.replaceChildren();
    const pending = jobs.filter((job) => job.status === "running" || job.status === "pending");
    if (!pending.length) {
      empty(container, "Aucune tâche Performance en attente ou en cours.");
      return;
    }
    for (const job of pending.slice(0, 300)) {
      const card = document.createElement("article");
      card.className = "monitor-task-row";
      card.append(
        span(job.player + " · " + job.type, "monitor-task-name"),
        span(job.status === "running" ? "En cours" : "En attente",
          "monitor-pill monitor-" + job.status)
      );
      container.appendChild(card);
    }
  }

  function reportLine(label, value) {
    const paragraph = document.createElement("p");
    paragraph.className = "monitor-report-line";
    const strong = document.createElement("strong");
    strong.textContent = label + " : ";
    paragraph.append(strong, document.createTextNode(value || "Non renseigné"));
    return paragraph;
  }

  function verifiedProviderLink(item) {
    if (!item.url || (item.kind !== "YouTube" && item.kind !== "Dailymotion")) return null;
    try {
      const url = new URL(item.url);
      const allowedHosts = item.kind === "YouTube"
        ? ["youtu.be", "www.youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com"]
        : ["dailymotion.com", "www.dailymotion.com", "dai.ly", "www.dai.ly"];
      if (url.protocol !== "https:" || !allowedHosts.includes(url.hostname)) return null;
      const link = document.createElement("a");
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Voir la vidéo";
      link.className = "monitor-report-link";
      return link;
    } catch (_) {
      return null;
    }
  }

  function drawReports(reports) {
    const container = $("monitor-report-list");
    container.replaceChildren();
    if (!reports.length) {
      empty(container, "Aucune tâche enregistrée pour le moment. La file des joueurs reste disponible.");
      return;
    }

    for (const item of reports) {
      const card = document.createElement("article");
      card.className = "monitor-report-card";
      const header = document.createElement("div");
      header.className = "monitor-report-header";
      const heading = document.createElement("div");
      heading.append(
        span(item.player, "monitor-task-name"),
        span(item.kind + " · tâche " + item.id + " · " + time(item.date), "monitor-subtle")
      );
      header.append(
        heading,
        span(item.status_label, "monitor-pill monitor-" + item.status)
      );
      card.append(
        header,
        reportLine("À faire", item.planned),
        reportLine("Fait", item.observed),
        reportLine("Reste", item.remaining)
      );
      if (item.error) card.append(reportLine("Erreur", item.error));
      const link = verifiedProviderLink(item);
      if (link) card.append(link);
      container.appendChild(card);
    }
  }

  let refreshing = false;
  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    $("monitor-refresh").disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(sourceUrl, {
        credentials: "same-origin", cache: "no-store",
        headers: { "Accept": "application/json" }, signal: controller.signal
      });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const data = await response.json();
      setText("monitor-count-subs", data.metrics.subscriptions);
      setText("monitor-count-waiting", data.metrics.waiting);
      setText("monitor-count-running", data.metrics.running);
      setText("monitor-count-finished", data.metrics.finished);
      drawJobs(data.jobs || []);
      drawReports(data.reports || []);
      setText("monitor-last-refresh", "Rapport consulté le " + time(data.now));
      setText("monitor-connection", "Rapport chargé");
    } catch (_error) {
      setText("monitor-connection", "Rapport indisponible — aucun impact sur l’agent");
      empty($("monitor-report-list"), "Impossible de charger les résultats. Réessayez avec Actualiser.");
    } finally {
      clearTimeout(timeout);
      refreshing = false;
      $("monitor-refresh").disabled = false;
    }
  }

  $("monitor-refresh").addEventListener("click", refresh);
  refresh(); // No live polling: report is read on demand.
})();
