import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from sportsbase_playwright import SportsBaseAutomation

load_dotenv()

BASE_URL = os.getenv("DJANGO_BASE_URL", "https://msfootball-1a882b44ed52.herokuapp.com/gestion_joueurs").rstrip("/")
USERNAME = os.getenv("DJANGO_AUTOMATION_USERNAME")
PASSWORD = os.getenv("DJANGO_AUTOMATION_PASSWORD")
POLL_INTERVAL = int(os.getenv("AUTOMATION_POLL_INTERVAL", "30"))
LOCAL_STORAGE_DIR = os.getenv(
    "AUTOMATION_STORAGE_DIR",
    r"D:\Django_Projects\ms_football_gest\gestion_joueurs\automated_players"
)

session = requests.Session()


def login():
    login_url = f"{BASE_URL}/login/"

    response = session.get(login_url, timeout=30)
    response.raise_for_status()

    csrftoken = session.cookies.get("csrftoken")
    if not csrftoken:
        print("[ERROR] CSRF token introuvable sur la page login")
        return False

    payload = {
        "username": USERNAME,
        "password": PASSWORD,
        "csrfmiddlewaretoken": csrftoken,
    }

    headers = {
        "Referer": login_url
    }

    response = session.post(
        login_url,
        data=payload,
        headers=headers,
        allow_redirects=True,
        timeout=30
    )

    if response.status_code not in [200, 302]:
        print(f"[ERROR] Login failed with status {response.status_code}")
        return False

    return True


def get_csrf_headers(referer_url):
    csrftoken = session.cookies.get("csrftoken", "")
    return {
        "X-CSRFToken": csrftoken,
        "Referer": referer_url,
    }


def get_pending_videos():
    url = f"{BASE_URL}/automation/pending-videos/"
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def mark_started(video_id):
    url = f"{BASE_URL}/automation/{video_id}/mark-started/"
    headers = get_csrf_headers(url)
    response = session.post(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def mark_completed(video_id):
    url = f"{BASE_URL}/automation/{video_id}/mark-completed/"
    headers = get_csrf_headers(url)
    response = session.post(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def create_local_folder(video_data):
    player_name = video_data["player"]["name"].replace(" ", "_")
    video_id = video_data["video_id"]

    folder = Path(LOCAL_STORAGE_DIR) / f"{video_id}_{player_name}"
    (folder / "raw_clips").mkdir(parents=True, exist_ok=True)
    (folder / "exports").mkdir(parents=True, exist_ok=True)
    (folder / "logs").mkdir(parents=True, exist_ok=True)

    return str(folder)


def process_video(video_data):
    video_id = video_data["video_id"]
    player_name = video_data["player"]["name"]
    sportsbase_url = video_data["player"].get("sportsbase_url")
    automation_started = video_data.get("automation_started", False)
    seasons_to_process = int(video_data.get("seasons_to_process", 1))

    print(f"[INFO] Nouvelle vidéo à traiter: {video_id} - {player_name}")
    print(f"[INFO] SportsBase URL: {sportsbase_url}")
    print(f"[INFO] Saisons à traiter: {seasons_to_process}")

    if not sportsbase_url:
        print(f"[WARN] Pas de SportsBase URL pour la vidéo {video_id}")
        return

    if not automation_started:
        mark_started(video_id)

    folder = create_local_folder(video_data)
    print(f"[INFO] Dossier créé: {folder}")

    automation = SportsBaseAutomation(base_download_dir=LOCAL_STORAGE_DIR)
    result = automation.run_for_player(
        player_name=player_name,
        player_url=sportsbase_url,
        target_dir=folder,
        seasons_to_process=seasons_to_process
    )

    print(f"[INFO] Matches played: {result['matches_played']}")
    print(f"[INFO] Générations envoyées: {result['generation_requests_sent']}")
    print(f"[INFO] Téléchargés: {len(result['downloaded_files'])}")

    if (
        result["generation_requests_sent"] > 0
        and len(result["downloaded_files"]) == result["generation_requests_sent"]
    ):
        mark_completed(video_id)
        print(f"[INFO] Vidéo {video_id} marquée automation_completed=True")
    else:
        print(f"[WARN] Vidéo {video_id} non complétée, elle sera retentée")


def main():
    if not USERNAME or not PASSWORD:
        print("[ERROR] Variables DJANGO_AUTOMATION_USERNAME / DJANGO_AUTOMATION_PASSWORD manquantes")
        return

    if not login():
        print("[ERROR] Échec connexion Django")
        return

    print("[INFO] Agent connecté")

    while True:
        try:
            data = get_pending_videos()
            videos = data.get("videos", [])

            if videos:
                for video in videos:
                    process_video(video)
            else:
                print("[INFO] Aucune vidéo automation en attente")

        except Exception as e:
            print(f"[ERROR] {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()