import argparse
import os
import json
import socket
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv


def configure_utf8_console():
    """Keep Windows logs readable even when an exception contains Unicode art."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="backslashreplace")


configure_utf8_console()

try:
    from .intro_generation import (
        generate_chatgpt_presentation,
        generate_kling_intro,
        kling_video_configured,
        openai_image_configured,
    )
    from .media_validation import validate_video_file
    from .premiere_automation import PremiereAutomation
    from .sportsbase_playwright import SportsBaseAutomation
    from .presentation_styles import DEFAULT_PRESENTATION_STYLE
    from .transfermarkt_fetcher import (
        build_transfermarkt_assets_from_url_file,
        refresh_presentation_style_assets,
    )
except ImportError:
    from intro_generation import (
        generate_chatgpt_presentation,
        generate_kling_intro,
        kling_video_configured,
        openai_image_configured,
    )
    from media_validation import validate_video_file
    from premiere_automation import PremiereAutomation
    from sportsbase_playwright import SportsBaseAutomation
    from presentation_styles import DEFAULT_PRESENTATION_STYLE
    from transfermarkt_fetcher import (
        build_transfermarkt_assets_from_url_file,
        refresh_presentation_style_assets,
    )

try:
    from sportsbase_data.youtube_uploader import YouTubeStudioUploader
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sportsbase_data.youtube_uploader import YouTubeStudioUploader
load_dotenv()

BASE_URL = os.getenv("DJANGO_BASE_URL", "https://msfootball-1a882b44ed52.herokuapp.com/gestion_joueurs").rstrip("/")
USERNAME = os.getenv("DJANGO_AUTOMATION_USERNAME")
PASSWORD = os.getenv("DJANGO_AUTOMATION_PASSWORD")
POLL_INTERVAL = int(os.getenv("AUTOMATION_POLL_INTERVAL", "5"))
LOCAL_STORAGE_DIR = (
    os.getenv("AUTOMATION_STORAGE_DIR", "").strip()
    or os.getenv("SPORTSBASE_DOWNLOAD_DIR", "").strip()
    or r"D:\Django_Projects\ms_football_gest\gestion_joueurs\automated_players"
)

session = requests.Session()
AGENT_VERSION = "highlights-v33-youtube-split"
WORKER_ID = os.getenv(
    "AUTOMATION_WORKER_ID",
    f"{socket.gethostname()}-highlights",
).strip()
USE_ATOMIC_CLAIM = os.getenv(
    "AUTOMATION_USE_ATOMIC_CLAIM",
    "true",
).strip().casefold() in {"1", "true", "yes", "on", "oui"}


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
    if "/login/" in response.url.rstrip("/") + "/":
        print("[ERROR] Identifiants Django refusés")
        return False

    return True


def get_csrf_headers(referer_url):
    csrftoken = session.cookies.get("csrftoken", "")
    return {
        "X-CSRFToken": csrftoken,
        "Referer": referer_url,
    }


def post_json(path, payload):
    url = f"{BASE_URL}/{path.lstrip('/')}"
    for attempt in range(2):
        headers = get_csrf_headers(url)
        response = session.post(url, json=payload, headers=headers, timeout=30)
        authentication_expired = (
            response.status_code in {401, 403}
            or "/login/" in response.url.rstrip("/") + "/"
        )
        if authentication_expired and attempt == 0 and login():
            continue
        response.raise_for_status()
        try:
            return response.json()
        except requests.JSONDecodeError as exc:
            raise ValueError(
                "L’application n’a pas retourné une réponse JSON valide."
            ) from exc
    raise RuntimeError("Connexion à l’application impossible.")


def send_heartbeat(
    *,
    state="idle",
    video_id=None,
    pipeline="",
    stage="",
    last_error="",
):
    try:
        return post_json("automation/worker/heartbeat/", {
            "worker_id": WORKER_ID,
            "display_name": f"Agent vidéo {socket.gethostname()}",
            "host_name": socket.gethostname(),
            "version": AGENT_VERSION,
            "state": state,
            "current_video_id": video_id,
            "current_pipeline": pipeline,
            "current_stage": stage,
            "last_error": last_error,
            "capabilities": {
                "sportsbase": True,
                "transfermarkt": True,
                "premiere": True,
                "youtube": True,
                "openai_image": openai_image_configured(),
                "kling_connector": kling_video_configured(),
            },
        })
    except Exception as exc:
        print(f"[WARN] Heartbeat application impossible: {exc}")
        return None


def claim_next(pipeline):
    payload = post_json("automation/jobs/claim/", {
        "pipeline": pipeline,
        "worker_id": WORKER_ID,
    })
    return payload.get("job")


def report_progress(video_id, pipeline, stage, **fields):
    payload = {
        "pipeline": pipeline,
        "stage": stage,
        "worker_id": WORKER_ID,
        **fields,
    }
    return post_json(f"automation/{video_id}/progress/report/", payload)


def report_video_progress(video_data, pipeline, stage, **fields):
    claim_token = video_data.get("claim_token") or ""
    if claim_token:
        fields["claim_token"] = claim_token
    return report_progress(video_data["video_id"], pipeline, stage, **fields)


def get_pending_videos():
    url = f"{BASE_URL}/automation/pending-videos/"
    for attempt in range(2):
        response = session.get(url, timeout=30)
        if "/login/" in response.url.rstrip("/") + "/" and attempt == 0 and login():
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError("Connexion à l’application impossible.")


def mark_started(video_id):
    return post_json(f"automation/{video_id}/mark-started/", {})


def mark_completed(video_id, export_path, validation):
    return post_json(f"automation/{video_id}/mark-completed/", {
        "export_path": export_path,
        "validation": validation,
    })


def mark_intro_started(video_id):
    return post_json(f"automation/{video_id}/mark-intro-started/", {})


def mark_intro_completed(video_id, intro_path, validation):
    return post_json(f"automation/{video_id}/mark-intro-completed/", {
        "intro_path": intro_path,
        "validation": validation,
    })


def complete_delivery(video_id, youtube_result):
    return post_json(f"automation/{video_id}/delivery/complete/", {
        "youtube_url": youtube_result.get("youtube_url", ""),
        "validation": {
            "youtube_video_id": youtube_result.get("youtube_video_id", ""),
            "content_sha256": youtube_result.get("content_sha256", ""),
            "file_size_bytes": youtube_result.get("file_size_bytes"),
        },
    })


def create_local_folder(video_data):
    player_name = video_data["player"]["name"].replace(" ", "_")
    video_id = video_data["video_id"]

    folder = Path(LOCAL_STORAGE_DIR) / f"{video_id}_{player_name}"
    (folder / "raw_clips").mkdir(parents=True, exist_ok=True)
    (folder / "exports").mkdir(parents=True, exist_ok=True)
    (folder / "logs").mkdir(parents=True, exist_ok=True)
    (folder / "intro").mkdir(parents=True, exist_ok=True)

    return str(folder)


def prepare_intro_generation_folder(intro_folder: Path, intro_photo_path: Path, tm_assets: dict):
    uploads_dir = intro_folder / "Uploads_ChatGPT_Kling"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # player photo
    if intro_photo_path and intro_photo_path.exists():
        ext = intro_photo_path.suffix or ".jpg"
        target_photo = uploads_dir / f"player_photo{ext}"
        target_photo.write_bytes(intro_photo_path.read_bytes())

    # transfermarkt files
    for key in [
        # Présentation normale
        "json_path",
        "logo_path",
        "prompt_path",
        "chatgpt_image_prompt_path",
        "kling_prompt_path",
        "visual_identity_brief_path",
        "presentation_style_path",
        "badges_card_path",

        # Deuxième présentation : position + valeur marchande
        "position_market_value_prompt_path",
        "position_graph_path",
        "market_value_graph_path",
        "position_market_value_card_path",
    ]:
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


def download_intro_photo(video_data, intro_folder: Path):
    existing = find_local_intro_photo(video_data, intro_folder)
    if existing:
        return existing
    photo_url = video_data.get("intro_photo_url")
    if not photo_url:
        return None
    response = session.get(photo_url, timeout=60)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").casefold()
    extension = ".png" if "png" in content_type else ".jpg"
    player_name = sanitize_filename(video_data["player"]["name"])
    output_path = intro_folder / f"{player_name}_intro_photo{extension}"
    output_path.write_bytes(response.content)
    return output_path


def existing_transfermarkt_assets(intro_folder: Path):
    required = {
        "json_path": intro_folder / "transfermarkt_data.json",
        "prompt_path": intro_folder / "prompt.txt",
        "chatgpt_image_prompt_path": intro_folder / "prompt_chatgpt_image.txt",
        "kling_prompt_path": intro_folder / "prompt_kling_image_to_video.txt",
        "visual_identity_brief_path": intro_folder / "visual_identity_brief.txt",
    }
    if not all(path.is_file() for path in required.values()):
        return None
    optional = {
        "logo_path": intro_folder / "transfermarkt_Team_Logo.jpg",
        "badges_card_path": intro_folder / "badges_card.png",
        "position_market_value_prompt_path": intro_folder / "prompt_position_market_value.txt",
        "position_graph_path": intro_folder / "position_graph.png",
        "market_value_graph_path": intro_folder / "market_value_graph.png",
        "position_market_value_card_path": intro_folder / "position_market_value_card.png",
        "presentation_style_path": intro_folder / "presentation_style.json",
    }
    badges_dir = intro_folder / "badges"
    payload = {key: str(path) for key, path in required.items()}
    payload.update({
        key: str(path) if path.is_file() else None
        for key, path in optional.items()
    })
    payload["badge_paths"] = (
        [str(path) for path in badges_dir.iterdir() if path.is_file()]
        if badges_dir.is_dir()
        else []
    )
    return payload


def newest_file(folder: Path, *, extensions, prefixes, not_before=None):
    if not folder.is_dir():
        return None
    candidates = [
        path
        for path in folder.iterdir()
        if path.is_file()
        and path.suffix.casefold() in extensions
        and path.stem.casefold().startswith(prefixes)
        and (not_before is None or path.stat().st_mtime >= not_before)
    ]
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def find_generated_presentation_image(folder: Path, not_before=None):
    return newest_file(
        folder,
        extensions={".png", ".jpg", ".jpeg", ".webp"},
        prefixes=("chatgpt", "generated", "presentation", "player_presentation"),
        not_before=not_before,
    )


def find_kling_intro(folder: Path, not_before=None):
    return newest_file(
        folder,
        extensions={".mp4"},
        prefixes=("kling", "intro"),
        not_before=not_before,
    )


def read_key_value_file(path: Path):
    if not path.is_file():
        return None
    result = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            result[key.strip()] = value.strip()
    return result or None


def process_intro_video(video_data):
    video_id = video_data["video_id"]
    player_name = video_data["player"]["name"]
    presentation_style = (
        video_data.get("intro_presentation_style")
        or DEFAULT_PRESENTATION_STYLE
    )
    transfermarkt_url = video_data["player"].get("transfermarkt_url")
    intro_started = video_data.get("intro_automation_started", False)

    print(f"[INFO] Intro à traiter: {video_id} - {player_name}")
    print(f"[INFO] Transfermarkt URL: {transfermarkt_url}")

    folder = Path(create_local_folder(video_data))
    intro_folder = folder / "intro"
    if not intro_started:
        mark_intro_started(video_id)

    if not transfermarkt_url:
        raise ValueError("Le lien Transfermarkt du joueur est absent.")

    intro_photo_path = download_intro_photo(video_data, intro_folder)
    transfermarkt_file = save_transfermarkt_url(video_data, intro_folder)

    if not intro_photo_path or not intro_photo_path.exists():
        report_video_progress(
            video_data,
            "intro",
            "chatgpt_image",
            state="waiting_external",
            message="Photo du joueur attendue avant la génération ChatGPT",
            artifacts={
                "local_folder": str(folder),
                "intro_folder": str(intro_folder),
            },
        )
        print(f"[INFO] Photo intro attendue dans {intro_folder}")
        return

    report_video_progress(
        video_data,
        "intro",
        "transfermarkt",
        state="running",
        message="Vérification des données et visuels Transfermarkt",
        artifacts={
            "local_folder": str(folder),
            "presentation_style": presentation_style,
        },
    )

    tm_assets = existing_transfermarkt_assets(intro_folder)
    if not tm_assets:
        tm_assets = build_transfermarkt_assets_from_url_file(
            str(intro_folder),
            presentation_style=presentation_style,
        )
    else:
        tm_assets.update(
            refresh_presentation_style_assets(
                str(intro_folder),
                presentation_style=presentation_style,
            )
        )
    generation_dir = prepare_intro_generation_folder(
        intro_folder=intro_folder,
        intro_photo_path=intro_photo_path,
        tm_assets=tm_assets,
    )
    style_manifest_path = Path(tm_assets.get("presentation_style_path") or "")
    style_selected_at = (
        style_manifest_path.stat().st_mtime
        if style_manifest_path.is_file()
        else None
    )

    generated_image = find_generated_presentation_image(
        generation_dir,
        not_before=style_selected_at,
    )
    if not generated_image and openai_image_configured():
        report_video_progress(
            video_data,
            "intro",
            "chatgpt_image",
            state="running",
            message="Génération de l’image de présentation par OpenAI",
        )
        output_image = generation_dir / "chatgpt_presentation.png"
        try:
            image_result = generate_chatgpt_presentation(
                player_photo=intro_photo_path,
                club_logo=Path(tm_assets["logo_path"]) if tm_assets.get("logo_path") else None,
                prompt_path=Path(tm_assets["chatgpt_image_prompt_path"]),
                output_path=output_image,
            )
        except Exception as exc:
            report_video_progress(
                video_data,
                "intro",
                "chatgpt_image",
                state="failed",
                message="La génération de l’image OpenAI a échoué",
                error_code="OPENAI_IMAGE_FAILED",
                error_detail=str(exc),
            )
            return
        generated_image = output_image if image_result.get("generated") else None
        if generated_image:
            report_video_progress(
                video_data,
                "intro",
                "chatgpt_image",
                state="running",
                progress_percent=55,
                message="Image de présentation OpenAI générée",
                artifacts={
                    "generated_image": str(generated_image),
                    "openai_generation": image_result,
                },
            )
    if not generated_image:
        report_video_progress(
            video_data,
            "intro",
            "chatgpt_image",
            state="waiting_external",
            message="Dossier prêt : génération de l’image ChatGPT attendue",
            artifacts={
                "local_folder": str(folder),
                "generation_folder": str(generation_dir),
                "chatgpt_prompt": str(generation_dir / "prompt_chatgpt_image.txt"),
                "visual_identity_brief": str(generation_dir / "visual_identity_brief.txt"),
            },
        )
        print(f"[INFO] Image ChatGPT attendue dans {generation_dir}")
        return

    kling_video = find_kling_intro(
        generation_dir,
        not_before=style_selected_at,
    )
    if not kling_video and kling_video_configured():
        report_video_progress(
            video_data,
            "intro",
            "kling_video",
            state="running",
            message="Animation image-to-video Kling en cours",
        )

        def kling_progress(status, task_id):
            send_heartbeat(
                state="busy",
                video_id=video_id,
                pipeline="intro",
                stage="kling_video",
            )
            report_video_progress(
                video_data,
                "intro",
                "kling_video",
                state="running",
                message=f"Kling : {status}",
                artifacts={"kling_task_id": task_id},
            )

        kling_output = generation_dir / "kling_intro.mp4"
        try:
            kling_result = generate_kling_intro(
                source_image=generated_image,
                prompt_path=Path(tm_assets["kling_prompt_path"]),
                output_path=kling_output,
                progress_callback=kling_progress,
            )
        except Exception as exc:
            report_video_progress(
                video_data,
                "intro",
                "kling_video",
                state="failed",
                message="La génération Kling a échoué",
                error_code="KLING_GENERATION_FAILED",
                error_detail=str(exc),
            )
            return
        kling_video = kling_output if kling_result.get("generated") else None
        if kling_video:
            report_video_progress(
                video_data,
                "intro",
                "kling_video",
                state="running",
                progress_percent=90,
                message="Animation Kling téléchargée, vérification en cours",
                artifacts={
                    "kling_video": str(kling_video),
                    "kling_generation": kling_result,
                },
            )
    if not kling_video:
        report_video_progress(
            video_data,
            "intro",
            "kling_video",
            state="waiting_external",
            message="Image ChatGPT prête : génération Kling attendue",
            artifacts={
                "generated_image": str(generated_image),
                "kling_prompt": str(generation_dir / "prompt_kling_image_to_video.txt"),
                "generation_folder": str(generation_dir),
            },
        )
        print(f"[INFO] Vidéo Kling attendue dans {generation_dir}")
        return

    validation = validate_video_file(
        kling_video,
        min_size_bytes=100_000,
        require_probe=False,
    )
    if not validation["valid"]:
        report_video_progress(
            video_data,
            "intro",
            "kling_video",
            state="failed",
            message="Le MP4 Kling est invalide",
            error_code="INVALID_KLING_MP4",
            error_detail=" ".join(validation["errors"]),
            artifacts={"intro_validation": validation},
        )
        return

    player_intro_output = intro_folder / f"{sanitize_filename(player_name)}Intro.mp4"
    if kling_video.resolve() != player_intro_output.resolve():
        player_intro_output.write_bytes(kling_video.read_bytes())
    mark_intro_completed(video_id, str(player_intro_output), validation)
    print(f"[INFO] Intro vidéo {video_id} vérifiée et terminée")

    print(f"[INFO] Dossier intro: {intro_folder}")
    print(f"[INFO] Photo intro téléchargée: {intro_photo_path}")
    print(f"[INFO] Transfermarkt URL sauvegardée: {transfermarkt_file}")
    print(f"[INFO] Fichier intro vidéo: {player_intro_output}")

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

    folder = Path(create_local_folder(video_data))
    print(f"[INFO] Dossier créé: {folder}")

    premiere = PremiereAutomation()
    export_result = read_key_value_file(
        folder / "premiere" / "premiere_export_result.txt"
    )
    export_status = str(
        (export_result or {}).get("status") or ""
    ).strip().casefold()

    # L'export direct est exécuté par Premiere Pro. Libérer la tâche permet
    # à l'agent de revérifier son résultat toutes les 30 secondes sans
    # considérer un MP4 encore en cours d'écriture comme terminé.
    if export_status in {"preparing", "queued", "rendering", "exporting"}:
        progress = (export_result or {}).get("progress")
        try:
            export_percent = 92 + round(float(progress or 0) * 5)
        except (TypeError, ValueError):
            export_percent = 92
        report_video_progress(
            video_data,
            "highlights",
            "export",
            state="waiting_external",
            progress_percent=export_percent,
            message="Export direct Premiere Pro en cours",
            artifacts={"premiere_export_result": export_result or {}},
        )
        return

    if export_status in {"failed", "cancelled"}:
        cancelled = export_status == "cancelled"
        report_video_progress(
            video_data,
            "highlights",
            "export",
            state="failed",
            message=(
                "Export annulé dans Premiere Pro"
                if cancelled
                else "Échec de l’export direct Premiere Pro"
            ),
            error_code=(
                "PREMIERE_EXPORT_CANCELLED"
                if cancelled
                else "PREMIERE_EXPORT_FAILED"
            ),
            error_detail=(
                (export_result or {}).get("error")
                or (
                    "L’export a été annulé."
                    if cancelled
                    else "Erreur d’export inconnue"
                )
            ),
            artifacts={"premiere_export_result": export_result or {}},
        )
        return

    final_export = premiere.find_final_export(folder)
    if final_export:
        report_video_progress(
            video_data,
            "highlights",
            "export_validation",
            state="running",
            message="Vérification technique du MP4 final",
            artifacts={"export_path": final_export},
        )
        validation = validate_video_file(
            final_export,
            min_size_bytes=1_000_000,
            require_audio=True,
            require_full_hd=True,
        )
        if validation["valid"]:
            mark_completed(video_id, final_export, validation)
            print(f"[INFO] Vidéo {video_id} terminée après validation du MP4")
        else:
            report_video_progress(
                video_data,
                "highlights",
                "export_validation",
                state="failed",
                message="Le MP4 final n’a pas passé les contrôles",
                error_code="INVALID_FINAL_EXPORT",
                error_detail=" ".join(validation["errors"]),
                artifacts={"export_path": final_export, "export_validation": validation},
            )
        return

    if export_status == "completed":
        expected_export = (export_result or {}).get("output_path") or str(
            folder / "exports"
        )
        report_video_progress(
            video_data,
            "highlights",
            "export_validation",
            state="failed",
            message="Premiere Pro indique un export terminé, mais le MP4 est introuvable",
            error_code="FINAL_EXPORT_MISSING",
            error_detail=f"Fichier attendu : {expected_export}",
            artifacts={"premiere_export_result": export_result or {}},
        )
        return

    project_result = premiere.read_project_result(folder)
    if project_result:
        if not project_result.get("success"):
            report_video_progress(
                video_data,
                "highlights",
                "premiere_project",
                state="failed",
                message="Premiere Pro n’a pas créé le projet",
                error_code="PREMIERE_PROJECT_FAILED",
                error_detail=project_result.get("error") or project_result.get("reason") or "Erreur Premiere inconnue",
                artifacts={"premiere_result": project_result},
            )
            return
        report_video_progress(
            video_data,
            "highlights",
            "human_review",
            state="waiting_external",
            message="Projet prêt : sélection, styles, intro/audio puis bouton 4 — Exporter",
            artifacts={
                "project_path": project_result.get("project_path", ""),
                "local_folder": str(folder),
            },
        )
        return

    if not sportsbase_url:
        raise ValueError(f"Pas de lien SportsBase pour la vidéo {video_id}")

    if not automation_started:
        mark_started(video_id)

    existing_clips = sorted((folder / "raw_clips").glob("*.mp4"))
    if existing_clips:
        previous_result_path = folder / "logs" / "sportsbase_result.json"
        previous_result = {}
        if previous_result_path.is_file():
            try:
                previous_result = json.loads(
                    previous_result_path.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                previous_result = {}
        expected_count = int(
            previous_result.get("generation_requests_sent") or len(existing_clips)
        )
        result = {
            "sportsbase_player_name": player_name,
            "matches_played": previous_result.get("matches_played") or expected_count,
            "generation_requests_sent": expected_count,
            "downloaded_files": [str(path) for path in existing_clips],
            "reused_existing_files": True,
        }
        report_video_progress(
            video_data,
            "highlights",
            "sportsbase_download",
            state="running",
            progress_current=len(existing_clips),
            progress_total=expected_count,
            message=f"{len(existing_clips)}/{expected_count} fichiers locaux retrouvés",
            artifacts={"local_folder": str(folder)},
        )
    else:
        report_video_progress(
            video_data,
            "highlights",
            "sportsbase_discovery",
            state="running",
            message="Connexion SportsBase et recherche des matchs",
            artifacts={"local_folder": str(folder)},
        )
        def sportsbase_progress(stage, current=0, total=0, message=""):
            send_heartbeat(
                state="busy",
                video_id=video_id,
                pipeline="highlights",
                stage=stage,
            )
            report_video_progress(
                video_data,
                "highlights",
                stage,
                state="running",
                progress_current=current,
                progress_total=total,
                message=message,
            )

        automation = SportsBaseAutomation(
            base_download_dir=LOCAL_STORAGE_DIR,
            progress_callback=sportsbase_progress,
        )
        result = automation.run_for_player(
            player_name=player_name,
            player_url=sportsbase_url,
            target_dir=str(folder),
            seasons_to_process=seasons_to_process
        )
        (folder / "logs" / "sportsbase_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"[INFO] Matches played: {result['matches_played']}")
    print(f"[INFO] Générations envoyées: {result['generation_requests_sent']}")
    print(f"[INFO] Téléchargés: {len(result['downloaded_files'])}")
    report_video_progress(
        video_data,
        "highlights",
        "sportsbase_download",
        state="running",
        progress_current=len(result["downloaded_files"]),
        progress_total=result["generation_requests_sent"],
        message=(
            f"{len(result['downloaded_files'])}/{result['generation_requests_sent']} "
            "matchs téléchargés"
        ),
        artifacts={
            "local_folder": str(folder),
            "downloaded_files": result["downloaded_files"],
        },
    )

    if (
        result["generation_requests_sent"] > 0
        and len(result["downloaded_files"]) == result["generation_requests_sent"]
    ):
        if video_data.get("intro_automation_enabled") and not video_data.get("intro_automation_completed"):
            report_video_progress(
                video_data,
                "highlights",
                "premiere_project",
                state="waiting_external",
                message="Clips prêts : attente de l’intro Kling avant Premiere Pro",
                artifacts={"local_folder": str(folder)},
            )
            return

        report_video_progress(
            video_data,
            "highlights",
            "premiere_project",
            state="running",
            message="Création du projet Premiere Pro",
        )
        premiere_result = premiere.run_for_player(
            player_name=result.get("sportsbase_player_name") or player_name,
            target_dir=folder,
            downloaded_files=result["downloaded_files"]
        )
        print(f"[INFO] Premiere success: {premiere_result['success']}")
        if premiere_result.get("success"):
            report_video_progress(
                video_data,
                "highlights",
                "human_review",
                state="waiting_external",
                message="Projet Premiere prêt : sélection humaine et export attendus",
                artifacts={
                    "project_path": premiere_result.get("project_path", ""),
                    "expected_export_path": premiere_result.get("final_export_path", ""),
                },
            )
        elif premiere_result.get("awaiting_result"):
            report_video_progress(
                video_data,
                "highlights",
                "premiere_project",
                state="running",
                message=premiere_result.get("reason", "Confirmation Premiere attendue"),
            )
        else:
            report_video_progress(
                video_data,
                "highlights",
                "premiere_project",
                state="failed",
                message="Création du projet Premiere impossible",
                error_code="PREMIERE_PROJECT_FAILED",
                error_detail=premiere_result.get("reason", "Erreur Premiere inconnue"),
                artifacts={"premiere_result": premiere_result},
            )
    else:
        report_video_progress(
            video_data,
            "highlights",
            "sportsbase_download",
            state="failed",
            message="Téléchargement SportsBase incomplet",
            error_code="SPORTSBASE_DOWNLOAD_INCOMPLETE",
            error_detail=(
                f"{len(result['downloaded_files'])} fichier(s) pour "
                f"{result['generation_requests_sent']} génération(s) confirmée(s)."
            ),
        )
        print(f"[WARN] Vidéo {video_id} incomplète ; reprise manuelle disponible")


def build_highlights_youtube_uploader(storage_root):
    """Keep Highlights delivery isolated from Performance YouTube settings."""
    return YouTubeStudioUploader(
        storage_root,
        config_prefix="HIGHLIGHTS_YOUTUBE",
    )


def check_highlights_youtube_access():
    storage_root = Path(LOCAL_STORAGE_DIR).resolve()
    uploader = build_highlights_youtube_uploader(storage_root)
    print(f"[YOUTUBE HIGHLIGHTS] Chaîne : {uploader.channel_id}")
    print(f"[YOUTUBE HIGHLIGHTS] Profil : {uploader.profile_dir}")
    uploader.check_access()


def process_delivery_video(video_data):
    video_id = video_data["video_id"]
    folder = Path(create_local_folder(video_data))
    run_artifacts = (video_data.get("run") or {}).get("artifacts") or {}
    export_path = run_artifacts.get("export_path")
    if not export_path:
        export_path = PremiereAutomation.find_final_export(folder)
    if not export_path:
        raise ValueError("Aucun MP4 final n’est disponible pour la livraison.")

    validation = validate_video_file(
        export_path,
        min_size_bytes=1_000_000,
        require_audio=True,
        require_full_hd=True,
    )
    if not validation["valid"]:
        raise ValueError(" ".join(validation["errors"]))

    storage_root = Path(LOCAL_STORAGE_DIR).resolve()
    resolved_export = Path(export_path).resolve()
    try:
        relative_export = resolved_export.relative_to(storage_root)
    except ValueError as exc:
        raise ValueError(
            "Le MP4 final doit rester dans le dossier sécurisé de l’automatisation."
        ) from exc

    report_video_progress(
        video_data,
        "delivery",
        "youtube_upload",
        state="running",
        progress_percent=35,
        message="Mise en ligne YouTube non répertoriée en cours",
        artifacts={"export_path": str(resolved_export)},
    )
    player_name = video_data["player"]["name"].strip()
    job = {
        "job_id": f"highlight-{video_id}",
        "player": video_data["player"],
        "match": {
            "local_folder_key": str(relative_export.parent).replace("\\", "/"),
            "filename": relative_export.name,
        },
        "youtube": {
            "title": f"{player_name} — Season Highlights {video_data.get('season', '')}"[:100],
            "description": (
                "MS Football — Player Highlights\n"
                f"Joueur : {player_name}\n"
                f"Club : {video_data.get('club') or video_data['player'].get('club') or '-'}\n"
                f"Saison : {video_data.get('season') or '-'}"
            ),
            "visibility": "unlisted",
        },
    }
    result = build_highlights_youtube_uploader(storage_root).upload(job)
    if result.get("status") != "uploaded":
        raise ValueError(result.get("error") or "YouTube n’a pas confirmé la mise en ligne.")

    report_video_progress(
        video_data,
        "delivery",
        "youtube_validation",
        state="running",
        progress_percent=75,
        message="Lien YouTube reçu, validation dans l’application",
        artifacts={"youtube_url": result.get("youtube_url", "")},
    )
    delivery = complete_delivery(video_id, result)
    whatsapp_url = delivery.get("whatsapp_url")
    if whatsapp_url and os.getenv("WHATSAPP_OPEN_ON_DELIVERY", "false").casefold() in {
        "1", "true", "yes", "on", "oui"
    }:
        os.startfile(whatsapp_url)
    print(f"[INFO] Vidéo {video_id} livrée: {result.get('youtube_url')}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Agent Windows Vidéos Highlights")
    parser.add_argument(
        "--check-youtube",
        action="store_true",
        help=(
            "ouvrir le profil Chrome de la chaîne Highlights et vérifier "
            "l’accès à YouTube Studio"
        ),
    )
    return parser.parse_args(argv)


def main():
    if not USERNAME or not PASSWORD:
        print("[ERROR] Variables DJANGO_AUTOMATION_USERNAME / DJANGO_AUTOMATION_PASSWORD manquantes")
        return

    if not login():
        print("[ERROR] Échec connexion Django")
        return

    print("[INFO] Agent connecté")
    send_heartbeat(state="idle")

    while True:
        try:
            handled = False
            if USE_ATOMIC_CLAIM:
                pipelines = (
                    ("intro", "transfermarkt", process_intro_video),
                    ("highlights", "sportsbase_discovery", process_video),
                    ("delivery", "youtube_upload", process_delivery_video),
                )
                for pipeline, fallback_stage, handler in pipelines:
                    video = claim_next(pipeline)
                    if not video:
                        continue
                    handled = True
                    send_heartbeat(
                        state="busy",
                        video_id=video["video_id"],
                        pipeline=pipeline,
                        stage=fallback_stage,
                    )
                    try:
                        handler(video)
                    except Exception as exc:
                        print(f"[ERROR] {pipeline} video={video['video_id']}: {exc}")
                        traceback.print_exc()
                        try:
                            report_video_progress(
                                video,
                                pipeline,
                                fallback_stage,
                                state="failed",
                                message="L’automatisation s’est arrêtée sur cette étape",
                                error_code="UNEXPECTED_AGENT_ERROR",
                                error_detail=str(exc),
                                force_event=True,
                            )
                        except Exception as report_exc:
                            print(f"[WARN] Impossible d’enregistrer l’erreur: {report_exc}")
                        send_heartbeat(
                            state="error",
                            video_id=video["video_id"],
                            pipeline=pipeline,
                            stage=fallback_stage,
                            last_error=str(exc),
                        )
                    else:
                        send_heartbeat(state="idle")
            else:
                data = get_pending_videos()
                intro_videos = data.get("intro_videos", [])
                videos = data.get("videos", [])
                for video in intro_videos:
                    handled = True
                    process_intro_video(video)
                for video in videos:
                    handled = True
                    process_video(video)

            if not handled:
                send_heartbeat(state="idle")
                print("[INFO] Aucune tâche automation en attente")

        except Exception as e:
            print(f"[ERROR] {e}")
            traceback.print_exc()
            send_heartbeat(state="error", last_error=str(e))

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    arguments = parse_args()
    if arguments.check_youtube:
        check_highlights_youtube_access()
    else:
        main()
