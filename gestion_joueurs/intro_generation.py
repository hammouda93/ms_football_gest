from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from contextlib import ExitStack
from pathlib import Path

import requests
from PIL import Image


def _enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().casefold() in {
        "1", "true", "yes", "on", "oui",
    }


def openai_image_configured() -> bool:
    return _enabled("OPENAI_IMAGE_AUTO_GENERATE") and bool(
        os.getenv("OPENAI_API_KEY", "").strip()
    )


def kling_video_configured() -> bool:
    has_credentials = bool(os.getenv("KLING_API_TOKEN", "").strip()) or bool(
        os.getenv("KLING_ACCESS_KEY", "").strip()
        and os.getenv("KLING_SECRET_KEY", "").strip()
    )
    return _enabled("KLING_AUTO_GENERATE") and has_credentials


def _save_openai_image(payload: dict, output_path: Path) -> None:
    images = payload.get("data") or []
    if not images or not isinstance(images[0], dict):
        raise ValueError("OpenAI n’a retourné aucune image.")
    image_payload = images[0]
    encoded = image_payload.get("b64_json")
    if encoded:
        raw_image = base64.b64decode(encoded, validate=True)
    elif image_payload.get("url"):
        download = requests.get(image_payload["url"], timeout=180)
        download.raise_for_status()
        raw_image = download.content
    else:
        raise ValueError("La réponse OpenAI ne contient ni image ni URL.")

    source_path = output_path.with_suffix(".source.png")
    source_path.write_bytes(raw_image)
    try:
        with Image.open(source_path) as generated:
            generated.load()
            resized = generated.convert("RGB").resize(
                (1920, 1080),
                Image.Resampling.LANCZOS,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            resized.save(output_path, format="PNG", optimize=True)
    finally:
        source_path.unlink(missing_ok=True)


def generate_chatgpt_presentation(
    *,
    player_photo: Path,
    prompt_path: Path,
    output_path: Path,
    club_logo: Path | None = None,
) -> dict:
    """Generate the stable 16:9 source image when the API option is enabled."""
    if not openai_image_configured():
        return {"configured": False, "generated": False}

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    endpoint = os.getenv(
        "OPENAI_IMAGE_EDIT_URL",
        "https://api.openai.com/v1/images/edits",
    ).strip()
    model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2.5-sunburst").strip()
    prompt = prompt_path.read_text(encoding="utf-8")
    references = [player_photo]
    if club_logo and club_logo.is_file():
        references.append(club_logo)

    headers = {"Authorization": f"Bearer {api_key}"}
    organization = os.getenv("OPENAI_ORGANIZATION", "").strip()
    project = os.getenv("OPENAI_PROJECT", "").strip()
    if organization:
        headers["OpenAI-Organization"] = organization
    if project:
        headers["OpenAI-Project"] = project

    data = {
        "model": model,
        "prompt": prompt,
        "size": os.getenv("OPENAI_IMAGE_SIZE", "2048x1152").strip(),
        "quality": os.getenv("OPENAI_IMAGE_QUALITY", "high").strip(),
        "output_format": "png",
    }
    input_fidelity = os.getenv("OPENAI_IMAGE_INPUT_FIDELITY", "").strip()
    if input_fidelity:
        data["input_fidelity"] = input_fidelity

    with ExitStack() as stack:
        files = []
        for reference in references:
            handle = stack.enter_context(reference.open("rb"))
            content_type = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
            }.get(reference.suffix.casefold(), "image/png")
            files.append(("image[]", (reference.name, handle, content_type)))
        response = requests.post(
            endpoint,
            headers=headers,
            data=data,
            files=files,
            timeout=int(os.getenv("OPENAI_IMAGE_TIMEOUT_SECONDS", "600")),
        )
    try:
        payload = response.json()
    except requests.JSONDecodeError as exc:
        raise ValueError(
            f"Réponse OpenAI illisible (HTTP {response.status_code})."
        ) from exc
    if not response.ok:
        api_error = payload.get("error") or {}
        raise ValueError(
            str(api_error.get("message") or f"Erreur OpenAI HTTP {response.status_code}")
        )

    _save_openai_image(payload, output_path)
    return {
        "configured": True,
        "generated": True,
        "provider": "openai",
        "model": model,
        "request_id": response.headers.get("x-request-id", ""),
        "output_path": str(output_path),
    }


def _base64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _kling_token() -> str:
    explicit_token = os.getenv("KLING_API_TOKEN", "").strip()
    if explicit_token:
        return explicit_token

    access_key = os.getenv("KLING_ACCESS_KEY", "").strip()
    secret_key = os.getenv("KLING_SECRET_KEY", "").strip()
    if not access_key or not secret_key:
        raise ValueError("Identifiants API Kling absents.")
    now = int(time.time())
    header = _base64url(json.dumps(
        {"alg": "HS256", "typ": "JWT"},
        separators=(",", ":"),
    ).encode("utf-8"))
    claims = _base64url(json.dumps(
        {"iss": access_key, "exp": now + 1800, "nbf": now - 5},
        separators=(",", ":"),
    ).encode("utf-8"))
    signing_input = f"{header}.{claims}".encode("ascii")
    signature = _base64url(hmac.new(
        secret_key.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest())
    return f"{header}.{claims}.{signature}"


def _kling_data(payload: dict) -> dict:
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _kling_task_id(payload: dict) -> str:
    data = _kling_data(payload)
    return str(data.get("task_id") or payload.get("task_id") or "").strip()


def _kling_status(payload: dict) -> str:
    data = _kling_data(payload)
    return str(
        data.get("task_status")
        or data.get("status")
        or payload.get("task_status")
        or payload.get("status")
        or ""
    ).strip().casefold()


def _kling_video_url(payload: dict) -> str:
    data = _kling_data(payload)
    task_result = data.get("task_result") or data.get("result") or {}
    videos = task_result.get("videos") if isinstance(task_result, dict) else []
    if videos and isinstance(videos[0], dict):
        return str(videos[0].get("url") or videos[0].get("video_url") or "")
    return str(data.get("video_url") or payload.get("video_url") or "")


def generate_kling_intro(
    *,
    source_image: Path,
    prompt_path: Path,
    output_path: Path,
    progress_callback=None,
) -> dict:
    """Create and poll one official Kling image-to-video task when configured."""
    if not kling_video_configured():
        return {"configured": False, "generated": False}

    create_url = os.getenv(
        "KLING_IMAGE_TO_VIDEO_URL",
        "https://api.klingai.com/v1/videos/image2video",
    ).strip()
    status_template = os.getenv(
        "KLING_IMAGE_TO_VIDEO_STATUS_URL",
        create_url.rstrip("/") + "/{task_id}",
    ).strip()
    prompt = prompt_path.read_text(encoding="utf-8")
    headers = {
        "Authorization": f"Bearer {_kling_token()}",
        "Content-Type": "application/json",
    }
    request_payload = {
        "model_name": os.getenv("KLING_MODEL_NAME", "kling-v2-6").strip(),
        "image": base64.b64encode(source_image.read_bytes()).decode("ascii"),
        "prompt": prompt,
        "negative_prompt": os.getenv(
            "KLING_NEGATIVE_PROMPT",
            "face morphing, identity drift, extra limbs, lip movement, camera shake, "
            "jerky motion, distorted jersey, warped logo, unreadable text, flicker",
        ).strip(),
        "mode": os.getenv("KLING_MODE", "pro").strip(),
        "duration": os.getenv("KLING_DURATION_SECONDS", "5").strip(),
        "cfg_scale": float(os.getenv("KLING_CFG_SCALE", "0.5")),
    }
    create_response = requests.post(
        create_url,
        headers=headers,
        json=request_payload,
        timeout=int(os.getenv("KLING_REQUEST_TIMEOUT_SECONDS", "120")),
    )
    try:
        create_payload = create_response.json()
    except requests.JSONDecodeError as exc:
        raise ValueError(
            f"Réponse Kling illisible (HTTP {create_response.status_code})."
        ) from exc
    if not create_response.ok or create_payload.get("code") not in (None, 0):
        raise ValueError(str(
            create_payload.get("message")
            or f"Erreur Kling HTTP {create_response.status_code}"
        ))
    task_id = _kling_task_id(create_payload)
    if not task_id:
        raise ValueError("Kling n’a pas retourné d’identifiant de tâche.")

    poll_seconds = max(5, int(os.getenv("KLING_POLL_SECONDS", "15")))
    deadline = time.monotonic() + int(os.getenv("KLING_MAX_WAIT_SECONDS", "1200"))
    last_payload = create_payload
    while time.monotonic() < deadline:
        status = _kling_status(last_payload)
        if progress_callback:
            progress_callback(status or "submitted", task_id)
        if status in {"succeed", "succeeded", "success", "completed"}:
            break
        if status in {"failed", "error", "cancelled", "canceled"}:
            data = _kling_data(last_payload)
            raise ValueError(str(
                data.get("task_status_msg")
                or data.get("message")
                or last_payload.get("message")
                or "La génération Kling a échoué."
            ))
        time.sleep(poll_seconds)
        status_response = requests.get(
            status_template.format(task_id=task_id),
            headers=headers,
            timeout=int(os.getenv("KLING_REQUEST_TIMEOUT_SECONDS", "120")),
        )
        status_response.raise_for_status()
        last_payload = status_response.json()
    else:
        raise TimeoutError("Kling n’a pas terminé dans le délai configuré.")

    video_url = _kling_video_url(last_payload)
    if not video_url:
        raise ValueError("Kling a terminé sans retourner de vidéo.")
    download = requests.get(video_url, timeout=300)
    download.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(download.content)
    return {
        "configured": True,
        "generated": True,
        "provider": "kling",
        "model": request_payload["model_name"],
        "task_id": task_id,
        "output_path": str(output_path),
    }
