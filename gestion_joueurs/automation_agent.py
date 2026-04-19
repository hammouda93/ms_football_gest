import os
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv

from sportsbase_playwright import SportsBaseAutomation
from premiere_automation import PremiereAutomation
from transfermarkt_assets import build_assets_from_transfermarkt_html_text
from transfermarkt_fetcher import build_transfermarkt_assets_from_url_file
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

    return str(folder)


def prepare_uploads_gemini_folder(intro_folder: Path, intro_photo_path: Path, tm_assets: dict):
    uploads_dir = intro_folder / "Uploads_Gemini"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # player photo
    if intro_photo_path and intro_photo_path.exists():
        ext = intro_photo_path.suffix or ".jpg"
        target_photo = uploads_dir / f"player_photo{ext}"
        target_photo.write_bytes(intro_photo_path.read_bytes())

    # transfermarkt files
    for key in ["json_path", "logo_path", "prompt_path", "badges_card_path"]:
        path_value = tm_assets.get(key)
        if path_value:
            src = Path(path_value)
            if src.exists():
                dst = uploads_dir / src.name
                dst.write_bytes(src.read_bytes())

    # badges folder
    badge_paths = tm_assets.get("badge_paths", [])
    if badge_paths:
        badges_dir = uploads_dir / "badges"
        badges_dir.mkdir(parents=True, exist_ok=True)
        for badge_path in badge_paths:
            src = Path(badge_path)
            if src.exists():
                dst = badges_dir / src.name
                dst.write_bytes(src.read_bytes())

    return uploads_dir

def sanitize_filename(name: str) -> str:
    return name.replace(" ", "_").replace("/", "_").replace("\\", "_")


def find_local_intro_photo(video_data, target_folder: Path):
    player_name = sanitize_filename(video_data["player"]["name"])

    candidates = [
        target_folder / f"{player_name}_intro_photo.jpg",
        target_folder / f"{player_name}_intro_photo.jpeg",
        target_folder / f"{player_name}_intro_photo.png",
        target_folder / "player_photo.jpg",
        target_folder / "player_photo.jpeg",
        target_folder / "player_photo.png",
        target_folder / "intro_photo.jpg",
        target_folder / "intro_photo.jpeg",
        target_folder / "intro_photo.png",
        target_folder / "photo.jpg",
        target_folder / "photo.jpeg",
        target_folder / "photo.png",
        target_folder / "intro.jpg",
        target_folder / "intro.jpeg",
        target_folder / "intro.png",
    ]

    for path in candidates:
        if path.exists():
            return path

    return None


def save_transfermarkt_url(video_data, target_folder: Path):
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

    folder = Path(create_local_folder(video_data))
    intro_folder = folder / "intro"

    intro_photo_path = find_local_intro_photo(video_data, intro_folder)
    transfermarkt_file = save_transfermarkt_url(video_data, intro_folder)

    tm_assets = None
    try:
        tm_assets = build_transfermarkt_assets_from_url_file(str(intro_folder))
        print(f"[INFO] Transfermarkt HTML: {tm_assets['raw_html_path']}")
        print(f"[INFO] Transfermarkt JSON: {tm_assets['json_path']}")
        print(f"[INFO] Transfermarkt Team Logo: {tm_assets['logo_path']}")
        print(f"[INFO] Badges Card: {tm_assets['badges_card_path']}")
        print(f"[INFO] Prompt TXT: {tm_assets['prompt_path']}")
        print(f"[INFO] Badges PNG: {tm_assets['badge_paths']}")
    except Exception as e:
        print(f"[WARN] Impossible de générer les assets Transfermarkt: {e}")

    uploads_gemini_dir = None
    if intro_photo_path and intro_photo_path.exists() and tm_assets:
        uploads_gemini_dir = prepare_uploads_gemini_folder(
            intro_folder=intro_folder,
            intro_photo_path=intro_photo_path,
            tm_assets=tm_assets,
        )
        print(f"[INFO] Uploads_Gemini: {uploads_gemini_dir}")

        if uploads_gemini_dir and Path(uploads_gemini_dir).exists():
            mark_intro_completed(video_id)
            print(f"[INFO] Intro vidéo {video_id} marquée intro_automation_completed=True")
            try:
                os.startfile(str(uploads_gemini_dir))
            except Exception as e:
                print(f"[WARN] Impossible d'ouvrir Uploads_Gemini: {e}")
        player_intro_output = intro_folder / f"{sanitize_filename(player_name)}Intro.mp4"

    print(f"[INFO] Dossier intro: {intro_folder}")
    print(f"[INFO] Photo intro téléchargée: {intro_photo_path}")
    print(f"[INFO] Transfermarkt URL sauvegardée: {transfermarkt_file}")
    print(f"[INFO] Fichier cible intro vidéo: {player_intro_output}")

    if intro_photo_path and intro_photo_path.exists():
        print("[INFO] Photo Trouvé pour Intro Video")
    else:
        print(f"[WARN] Pas de photo intro pour {video_id}, automation intro non complétée")


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
        premiere = PremiereAutomation()
        premiere_result = premiere.run_for_player(
            player_name=result.get("sportsbase_player_name") or player_name,
            target_dir=folder,
            downloaded_files=result["downloaded_files"]
        )
        print(f"[INFO] Premiere success: {premiere_result['success']}")

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
            intro_videos = data.get("intro_videos", [])

            if videos:
                for video in videos:
                    process_video(video)
            else:
                print("[INFO] Aucune vidéo automation en attente")

            if intro_videos:
                for video in intro_videos:
                    process_intro_video(video)
            else:
                print("[INFO] Aucune vidéo automation intro en attente")

        except Exception as e:
            print(f"[ERROR] {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()