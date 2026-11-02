"""Structured, best-effort telemetry from the unchanged local Performance agent.

The wrapper is used ONLY by the Windows sidebar launcher. It forwards every byte
of stdout from the existing agent to its terminal while parsing a small allowlist
of progress lines for a separate authenticated Django telemetry endpoint.
Failures to reach Heroku never interrupt or retry SportsBase/All Actions work.
"""
import argparse
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections import deque

import requests
from dotenv import load_dotenv


TASK_START = re.compile(r"^\[SPORTSBASE\] Tâche (\d+) — (.*?) — (full|profile|matches|all_actions)\s*$")
TASK_DONE = re.compile(r"^\[SPORTSBASE\] Tâche (\d+) terminée — (\w+) — (\d+) match")
PLAN = re.compile(r"^\[SPORTSBASE\] Plan initial — (\d+) joueur\(s\), (\d+) tâche\(s\)")
PLAN_ITEM = re.compile(r"^\[SPORTSBASE\]\s+\d+\. (.+?) — tâche (\d+) — (\w+)")
MATCH = re.compile(r"(?:match[_\s-]+|/matches/)(\d+)", re.I)
MATCH_XLSX = re.compile(r"match_(\d+)__players_statistics\.xlsx")
AGENT_LINE = re.compile(r"^\[(SPORTSBASE|YOUTUBE|DAILYMOTION)\]")


def _site_url():
    explicit = os.getenv("DJANGO_SITE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    legacy = os.getenv(
        "DJANGO_BASE_URL",
        "https://msfootball-1a882b44ed52.herokuapp.com/gestion_joueurs",
    ).rstrip("/")
    if legacy.endswith("/gestion_joueurs"):
        return legacy[: -len("/gestion_joueurs")]
    return legacy


def _safe_message(message):
    # Never forward credentials, signed URLs, query strings or local directory paths.
    clean = re.sub(r"https?://\S+", "[URL]", message)
    clean = re.sub(r"[A-Za-z]:\\[^\s]+", "[chemin local]", clean)
    return re.sub(r"\s+", " ", clean).strip()[:320]


class PassiveMonitor:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.run_id = str(uuid.uuid4())
        self.worker_name = socket.gethostname()[:100] or "Windows"
        self.site_url = _site_url()
        self.username = os.getenv("DJANGO_AUTOMATION_USERNAME", "").strip()
        self.password = os.getenv("DJANGO_AUTOMATION_PASSWORD", "").strip()
        self.events = queue.Queue(maxsize=500)
        self.next_sequence = 0
        self.last_seen_stage = ""
        self.current_player = ""
        self.current_job_id = None
        self._stop = threading.Event()
        self._thread = None
        self.session = requests.Session()

    def emit(self, kind, message, *, job_id=None, match_id="", player="", level="info", stage=""):
        if not self.enabled:
            return
        self.next_sequence += 1
        item = {
            "sequence": self.next_sequence,
            "kind": kind,
            "message": _safe_message(message),
            "job_id": job_id if job_id and str(job_id).isdigit() else None,
            "match_id": str(match_id)[:32],
            "player": _safe_message(player)[:160],
            "level": level,
            "stage": stage[:80],
        }
        try:
            self.events.put_nowait(item)
        except queue.Full:
            # Telemetry must never slow down the production agent.
            try:
                self.events.get_nowait()
                self.events.put_nowait(item)
            except queue.Empty:
                pass

    def track(self, line):
        if not self.enabled or not AGENT_LINE.match(line):
            return
        match = TASK_START.match(line)
        if match:
            self.current_job_id, self.current_player = int(match.group(1)), match.group(2)
            self.emit("job_started", "Traitement de " + self.current_player,
                      job_id=self.current_job_id, player=self.current_player, stage="Joueur en cours")
            return
        match = TASK_DONE.match(line)
        if match:
            self.emit("job_finished", "Tâche " + match.group(1) + " : " + match.group(2)
                      + ", " + match.group(3) + " match(s)",
                      job_id=int(match.group(1)), player=self.current_player,
                      level="error" if match.group(2) == "failed" else "info",
                      stage="Tâche terminée")
            self.current_player, self.current_job_id = "", None
            return
        match = PLAN.match(line)
        if match:
            self.emit("plan", match.group(1) + " joueurs, " + match.group(2)
                      + " tâches programmées", stage="Plan initial")
            return
        match = PLAN_ITEM.match(line)
        if match:
            self.emit("queued", match.group(1) + " — " + match.group(3),
                      job_id=int(match.group(2)), player=match.group(1), stage="En attente")
            return
        stage = None
        kind = "progress"
        if "Agent actif — stockage" in line:
            stage, kind = "Agent démarré", "started"
            message = "Agent Performance démarré"
        elif "Chrome connecté par CDP" in line:
            stage, message = "Connexion SportsBase", "Connexion au navigateur SportsBase établie"
        elif "Ouverture Google Chrome avec profil persistant" in line:
            stage, message = "Ouverture navigateur", "Ouverture du profil Chrome SportsBase"
        elif "Nom exact du profil" in line:
            stage, message = "Profil joueur", "Profil SportsBase du joueur vérifié"
        elif "Heatmap lue directement" in line or "Carte recadrée depuis le viewport" in line:
            stage, message = "Cartes du match", "Collecte des cartes du match"
        elif "Statistiques Players XLSX enregistrées" in line:
            stage, message = "XLSX enregistré", "Statistiques Players téléchargées"
        elif "Statistiques Players XLSX déjà présentes" in line:
            stage, message = "XLSX réutilisé", "Statistiques Players déjà disponibles"
        elif "Statistiques Players lues" in line:
            stage, message = "XLSX analysé", _safe_message(line.split("] ", 1)[-1])
        elif "Téléchargement des statistiques Players XLSX" in line:
            stage, message = "Téléchargement XLSX", "Téléchargement des statistiques Players"
        elif "Table Players incomplète" in line:
            stage, message = "Colonnes SportsBase", "Colonnes Players incomplètes — configuration automatique"
        elif "Configuration enrichie enregistrée" in line:
            stage, message = "Colonnes configurées", "Configuration des colonnes Players enregistrée"
        elif "Détails match " in line:
            stage, message = "Lecture match", "Lecture des détails du match"
        elif "All Actions classées" in line:
            stage, message = "Vidéo classée", "All Actions récupérée et classée"
        elif "MP4 original détecté" in line:
            stage, message = "Vidéo téléchargée", "Fichier vidéo MP4 téléchargé"
        elif "All Actions locale déjà valide" in line:
            stage, message = "Vidéo conservée", "All Actions locale réutilisée"
        elif "All Actions ajoutée à la file" in line:
            stage, message = "Génération vidéo", "All Actions ajoutée à la file"
        elif "Rapport PDF enregistré localement" in line:
            stage, message = "PDF enregistré", "Rapport PDF enregistré sur le PC"
        elif "Aucun nouveau match" in line:
            stage, message = "Aucun nouveau match", "Pas de nouveau match à traiter"
        elif "Téléchargement Players XLSX impossible" in line:
            stage, kind, message = "Erreur XLSX", "warning", _safe_message(line).replace("[SPORTSBASE][WARN] ", "")
        elif "[SPORTSBASE][WARN] Copie locale du rapport PDF impossible" in line:
            stage, kind, message = "Erreur PDF", "warning", "Échec de l'enregistrement local du PDF"
        elif "[SPORTSBASE][WARN]" in line:
            stage, kind, message = "Avertissement", "warning", _safe_message(line)
        elif "[SPORTSBASE][ERREUR" in line or "[SPORTSBASE][ERROR" in line:
            stage, kind, message = "Erreur agent", "error", _safe_message(line)
        elif "[YOUTUBE] Tâche " in line:
            stage, message = "Publication YouTube", "Tâche YouTube en cours"
        elif "[DAILYMOTION] Tâche " in line:
            stage, message = "Publication Dailymotion", "Tâche Dailymotion en cours"
        if stage is None:
            return
        game = MATCH_XLSX.search(line) or MATCH.search(line)
        level = "error" if kind == "error" else "warning" if kind == "warning" else "info"
        self.emit(kind, message, job_id=self.current_job_id, match_id=game.group(1) if game else "",
                  player=self.current_player, level=level, stage=stage)

    def _login(self):
        if not self.username or not self.password:
            return False
        url = self.site_url + "/gestion_joueurs/login/"
        try:
            response = self.session.get(url, timeout=5)
            response.raise_for_status()
            csrf = self.session.cookies.get("csrftoken")
            if not csrf:
                return False
            response = self.session.post(
                url,
                data={"username": self.username, "password": self.password,
                      "csrfmiddlewaretoken": csrf, "next": "/gestion/performances/"},
                headers={"Referer": url},
                allow_redirects=True, timeout=8,
            )
            return response.ok and "/login/" not in response.url
        except requests.RequestException:
            return False

    def _send(self, events, state):
        url = self.site_url + "/sportsbase/automation/monitoring/ingest/"
        payload = {
            "run_id": self.run_id, "worker_name": self.worker_name,
            "state": state, "events": events,
        }
        try:
            csrf = self.session.cookies.get("csrftoken", "")
            response = self.session.post(
                url, json=payload,
                headers={"Referer": url, "X-CSRFToken": csrf},
                timeout=6,
            )
            if response.status_code in (401, 403) or "/login/" in response.url:
                if self._login():
                    response = self.session.post(
                        url, json=payload,
                        headers={"Referer": url,
                                 "X-CSRFToken": self.session.cookies.get("csrftoken", "")},
                        timeout=6,
                    )
            return response.ok and response.headers.get("Content-Type", "").startswith("application/json")
        except requests.RequestException:
            return False

    def _worker(self):
        backlog = deque(maxlen=500)
        last_heartbeat = 0.0
        while not self._stop.is_set() or not self.events.empty() or backlog:
            try:
                item = self.events.get(timeout=1)
                backlog.append(item)
            except queue.Empty:
                pass
            now = time.monotonic()
            if now - last_heartbeat < 10 and len(backlog) < 15 and not self._stop.is_set():
                continue
            last_heartbeat = now
            chunk = list(backlog)[:25]
            state = "finished" if self._stop.is_set() else "running"
            if self._send(chunk, state):
                for _ in chunk:
                    backlog.popleft()
                if state == "finished":
                    return
            if self._stop.is_set():
                # Bounded shutdown: a monitoring outage must not keep Windows terminal open.
                return

    def start(self):
        if not self.enabled:
            return
        self.emit("started", "Supervision de l'agent démarrée", stage="Démarrage")
        self._thread = threading.Thread(target=self._worker, name="ms-performance-monitor", daemon=True)
        self._thread.start()

    def close(self, returncode):
        if not self.enabled:
            return
        self.emit("stopped" if returncode == 0 else "error",
                  "Agent arrêté" if returncode == 0 else "Agent interrompu (code " + str(returncode) + ")",
                  stage="Arrêt", level="info" if returncode == 0 else "error")
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)


def main():
    parser = argparse.ArgumentParser(description="Passive Performance Agent monitoring")
    parser.add_argument("--agent-module", default="sportsbase_data.local_agent")
    args, child_args = parser.parse_known_args()
    if args.agent_module != "sportsbase_data.local_agent":
        parser.error("Seul l'agent Performance est autorisé.")
    load_dotenv()
    enabled = os.getenv("MS_PERFORMANCE_MONITOR_ENABLED", "1").strip().casefold() not in {
        "0", "false", "no", "off",
    }
    # Run the unchanged production module with the same interpreter and arguments.
    command = [sys.executable, "-X", "utf8", "-u", "-m", args.agent_module, *child_args]
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             bufsize=0)
    monitor = None
    if enabled:
        try:
            monitor = PassiveMonitor(enabled=True)
            monitor.start()
        except Exception:
            # Even observer startup must never prevent the agent from running.
            monitor = None
    code = 1
    try:
        for raw in iter(child.stdout.readline, b""):
            try:
                sys.stdout.buffer.write(raw)
                sys.stdout.buffer.flush()
            except (OSError, AttributeError):
                pass
            if monitor is not None:
                try:
                    monitor.track(raw.decode("utf-8", errors="replace").strip())
                except Exception:
                    # No telemetry parsing error may stop an active scraping run.
                    pass
        code = child.wait()
    except KeyboardInterrupt:
        child.terminate()
        try:
            code = child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            code = child.wait()
    finally:
        if monitor is not None:
            try:
                monitor.close(code)
            except Exception:
                pass
    return code


if __name__ == "__main__":
    sys.exit(main())
