import os
import shutil
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv

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


def mark_intro_started(video_id):
    url = f"{BASE_URL}/automation/{video_id}/mark-intro-started/"
    headers = get_csrf_headers(url)
    response = session.post(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def mark_intro_completed(video_id):
    url = f"{BASE_URL}/automation/{video_id}/mark-intro-completed/"
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
    (folder / "intro").mkdir(parents=True, exist_ok=True)

    return folder


def sanitize_filename(name: str) -> str:
    return name.replace(" ", "_").replace("/", "_").replace("\\", "_")


def download_intro_photo(video_data, target_folder: Path) -> Path | None:
    intro_photo_url = video_data.get("intro_photo_url")
    if not intro_photo_url:
        return None

    absolute_url = urljoin(f"{BASE_URL}/", intro_photo_url.lstrip("/"))

    ext = Path(intro_photo_url).suffix or ".jpg"
    player_name = sanitize_filename(video_data["player"]["name"])
    output_path = target_folder / f"{player_name}_intro_photo{ext}"

    response = session.get(absolute_url, timeout=60, stream=True)
    response.raise_for_status()

    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

    return output_path


def save_transfermarkt_url(video_data, target_folder: Path) -> Path | None:
    transfermarkt_url = video_data["player"].get("transfermarkt_url")
    if not transfermarkt_url:
        return None

    output_path = target_folder / "transfermarkt_url.txt"
    output_path.write_text(transfermarkt_url, encoding="utf-8")
    return output_path


def process_intro_video(video_data):
    video_id = video_data["video_id"]
    player_name = video_data["player"]["name"]
    transfermarkt_url = video_data["player"].get("transfermarkt_url")
    intro_started = video_data.get("intro_automation_started", False)

    print(f"[INFO] Intro à traiter: {video_id} - {player_name}")
    print(f"[INFO] Transfermarkt URL: {transfermarkt_url}")

    if not intro_started:
        mark_intro_started(video_id)

    folder = create_local_folder(video_data)
    intro_folder = folder / "intro"

    intro_photo_path = download_intro_photo(video_data, intro_folder)
    transfermarkt_file = save_transfermarkt_url(video_data, intro_folder)

    player_intro_output = intro_folder / f"{sanitize_filename(player_name)}Intro.mp4"

    print(f"[INFO] Dossier intro: {intro_folder}")
    print(f"[INFO] Photo intro téléchargée: {intro_photo_path}")
    print(f"[INFO] Transfermarkt URL sauvegardée: {transfermarkt_file}")
    print(f"[INFO] Fichier cible intro vidéo: {player_intro_output}")

    # Placeholder: ici tu brancheras plus tard
    # - capture Transfermarkt
    # - Gemini web automation
    # - Kling web automation
    #
    # Pour l’instant on marque completed seulement si la photo existe bien.
    if intro_photo_path and intro_photo_path.exists():
        mark_intro_completed(video_id)
        print(f"[INFO] Intro vidéo {video_id} marquée intro_automation_completed=True")
    else:
        print(f"[WARN] Pas de photo intro pour {video_id}, automation intro non complétée")


def main():
    if not USERNAME or not PASSWORD:
        print("[ERROR] Variables DJANGO_AUTOMATION_USERNAME / DJANGO_AUTOMATION_PASSWORD manquantes")
        return

    if not login():
        print("[ERROR] Échec connexion Django")
        return

    print("[INFO] Agent intro connecté")

    while True:
        try:
            data = get_pending_videos()
            intro_videos = data.get("intro_videos", [])

            if intro_videos:
                for video in intro_videos:
                    process_intro_video(video)
            else:
                print("[INFO] Aucune intro automation en attente")

        except Exception as e:
            print(f"[ERROR] {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()