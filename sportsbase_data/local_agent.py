"""Local SportsBase subscription agent.

Run from the project root with:
    python -m sportsbase_data.local_agent
"""

import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from .scraper import SportsBaseSubscriptionScraper


load_dotenv()


def _site_url():
    explicit = os.getenv("DJANGO_SITE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    legacy = os.getenv(
        "DJANGO_BASE_URL",
        "https://msfootball-1a882b44ed52.herokuapp.com/gestion_joueurs",
    ).rstrip("/")
    return legacy[: -len("/gestion_joueurs")] if legacy.endswith("/gestion_joueurs") else legacy


class SportsBaseAgentClient:
    def __init__(self):
        self.site_url = _site_url()
        self.username = os.getenv("DJANGO_AUTOMATION_USERNAME", "").strip()
        self.password = os.getenv("DJANGO_AUTOMATION_PASSWORD", "").strip()
        self.poll_interval = int(os.getenv("SPORTSBASE_AGENT_POLL_INTERVAL", "60"))
        self.storage_root = Path(
            os.getenv(
                "SPORTSBASE_SUBSCRIPTION_STORAGE_DIR",
                r"D:\Django_Projects\ms_football_gest\gestion_joueurs\sportsbase_subscriptions",
            )
        )
        self.session = requests.Session()
        self.scraper = SportsBaseSubscriptionScraper(self.storage_root)
        if not self.username or not self.password:
            raise ValueError(
                "DJANGO_AUTOMATION_USERNAME et DJANGO_AUTOMATION_PASSWORD sont obligatoires."
            )

    def login(self):
        login_url = f"{self.site_url}/gestion_joueurs/login/"
        response = self.session.get(login_url, timeout=30)
        response.raise_for_status()
        csrf = self.session.cookies.get("csrftoken")
        if not csrf:
            raise RuntimeError("Jeton CSRF introuvable sur la page de connexion.")
        response = self.session.post(
            login_url,
            data={
                "username": self.username,
                "password": self.password,
                "csrfmiddlewaretoken": csrf,
                "next": "/sportsbase/automation/jobs/next/",
            },
            headers={"Referer": login_url},
            allow_redirects=True,
            timeout=30,
        )
        response.raise_for_status()
        if "/login/" in response.url:
            raise RuntimeError("Connexion Django refusée pour l’agent SportsBase.")

    def _get(self, path):
        response = self.session.get(f"{self.site_url}{path}", timeout=45)
        if response.status_code in {401, 403}:
            self.login()
            response = self.session.get(f"{self.site_url}{path}", timeout=45)
        response.raise_for_status()
        return response

    def _post_json(self, path, payload):
        url = f"{self.site_url}{path}"
        headers = {
            "X-CSRFToken": self.session.cookies.get("csrftoken", ""),
            "Referer": url,
        }
        response = self.session.post(url, json=payload, headers=headers, timeout=120)
        if response.status_code in {401, 403}:
            self.login()
            headers["X-CSRFToken"] = self.session.cookies.get("csrftoken", "")
            response = self.session.post(url, json=payload, headers=headers, timeout=120)
        response.raise_for_status()
        return response

    def next_job(self):
        return self._get("/sportsbase/automation/jobs/next/").json().get("job")

    def submit_result(self, job_id, result):
        return self._post_json(
            f"/sportsbase/automation/jobs/{job_id}/result/",
            result,
        ).json()

    def process_once(self):
        job = self.next_job()
        if not job:
            return False
        print(
            f"[SPORTSBASE] Tâche {job['job_id']} — "
            f"{job['player']['name']} — {job['job_type']}"
        )
        try:
            result = self.scraper.run(job)
        except Exception as exc:
            result = {
                "status": "failed",
                "profile": {},
                "matches": [],
                "summary": {},
                "error": str(exc),
            }
        self.submit_result(job["job_id"], result)
        print(
            f"[SPORTSBASE] Tâche {job['job_id']} terminée — "
            f"{result['status']} — {len(result.get('matches', []))} match(s)"
        )
        return True

    def run_forever(self):
        self.login()
        print(f"[SPORTSBASE] Agent actif — stockage : {self.storage_root}")
        while True:
            try:
                if not self.process_once():
                    time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                print("[SPORTSBASE] Arrêt demandé.")
                return
            except Exception as exc:
                print(f"[SPORTSBASE][ERROR] {exc}")
                time.sleep(self.poll_interval)


if __name__ == "__main__":
    SportsBaseAgentClient().run_forever()
