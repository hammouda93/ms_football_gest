"""Local, resumable YouTube Studio automation for All Actions videos."""

import hashlib
import json
import os
import re
import time
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


DEFAULT_CHANNEL_ID = "UCB2SMAxFXOcWDDDX5FtI9iA"
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}


class YouTubeUploadError(RuntimeError):
    pass


class YouTubeAuthenticationRequired(YouTubeUploadError):
    pass


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on", "oui"}


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class YouTubeStudioUploader:
    def __init__(self, storage_root):
        self.storage_root = Path(storage_root)
        self.channel_id = os.getenv(
            "YOUTUBE_STUDIO_CHANNEL_ID", DEFAULT_CHANNEL_ID
        ).strip()
        self.profile_dir = Path(
            os.getenv(
                "YOUTUBE_CHROME_PROFILE_DIR",
                r"D:\YouTube_MSPerformance_Profile",
            )
        )
        self.browser_channel = os.getenv("YOUTUBE_BROWSER_CHANNEL", "chrome").strip()
        self.headless = _env_bool("YOUTUBE_HEADLESS", False)
        self.upload_timeout_ms = int(
            os.getenv("YOUTUBE_UPLOAD_TIMEOUT_MINUTES", "180")
        ) * 60 * 1000
        self.navigation_timeout_ms = int(
            os.getenv("YOUTUBE_NAVIGATION_TIMEOUT_SECONDS", "90")
        ) * 1000
        self.upload_url = os.getenv(
            "YOUTUBE_STUDIO_UPLOAD_URL",
            f"https://studio.youtube.com/channel/{self.channel_id}/videos/upload",
        ).strip()
        self.content_url = (
            f"https://studio.youtube.com/channel/{self.channel_id}/videos"
        )
        self.receipt_dir = self.storage_root / "_youtube_receipts"

    def _receipt_path(self, job):
        job_id = re.sub(r"[^0-9A-Za-z_-]", "_", str(job.get("job_id") or "unknown"))
        return self.receipt_dir / f"upload_{job_id}.json"

    def _load_receipt(self, job, *, content_sha256, file_size):
        receipt_path = self._receipt_path(job)
        if not receipt_path.is_file():
            return None
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        youtube_url = str(receipt.get("youtube_url") or "").strip()
        video_id = self._video_id(youtube_url)
        if (
            receipt.get("status") != "uploaded"
            or receipt.get("content_sha256") != content_sha256
            or int(receipt.get("file_size_bytes") or 0) != file_size
            or not video_id
        ):
            return None
        receipt["youtube_video_id"] = video_id
        print(
            "[YOUTUBE] Reçu local retrouvé : la vidéo déjà publiée ne sera pas "
            "envoyée une seconde fois."
        )
        return receipt

    def _save_receipt(self, job, result):
        self.receipt_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = self._receipt_path(job)
        temporary_path = receipt_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(receipt_path)

    def resolve_video_path(self, job):
        match = job.get("match") or {}
        folder_key = str(match.get("local_folder_key") or "").strip()
        filename = str(match.get("filename") or "").strip()
        if not folder_key or not filename:
            raise YouTubeUploadError("Le chemin local de la vidéo est incomplet.")
        if Path(filename).name != filename or "/" in filename or "\\" in filename:
            raise YouTubeUploadError("Le nom du fichier vidéo est invalide.")

        normalized = folder_key.replace("\\", "/")
        relative = PurePosixPath(normalized)
        if relative.is_absolute() or ".." in relative.parts:
            raise YouTubeUploadError("Le dossier local de la vidéo est invalide.")

        root = self.storage_root.resolve()
        candidate = (root.joinpath(*relative.parts) / filename).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise YouTubeUploadError(
                "Le fichier vidéo se trouve hors du stockage autorisé."
            ) from exc
        if not candidate.is_file():
            raise YouTubeUploadError(f"Fichier All Actions introuvable : {candidate}")
        if candidate.suffix.casefold() not in ALLOWED_VIDEO_EXTENSIONS:
            raise YouTubeUploadError("Le format du fichier All Actions n’est pas accepté.")
        if candidate.stat().st_size <= 0:
            raise YouTubeUploadError("Le fichier All Actions est vide.")
        return candidate

    def _launch_context(self, playwright):
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        print(
            "[YOUTUBE] Ouverture Google Chrome avec profil persistant : "
            f"{self.profile_dir}"
        )
        try:
            return playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                channel=self.browser_channel or None,
                headless=self.headless,
                no_viewport=True,
                args=["--start-maximized"],
            )
        except Exception as exc:
            raise YouTubeUploadError(
                "Impossible d’ouvrir le profil YouTube. Fermez les fenêtres Chrome "
                "qui utilisent ce profil, puis réessayez."
            ) from exc

    @staticmethod
    def _authentication_required(page):
        url = page.url.casefold()
        return (
            "accounts.google.com" in url
            or page.locator('input[type="email"]').count() > 0
            or page.get_by_text(
                re.compile(r"^(sign in|se connecter)$", re.IGNORECASE)
            ).count()
            > 0
        )

    def check_access(self):
        with sync_playwright() as playwright:
            context = self._launch_context(playwright)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(
                    self.content_url,
                    wait_until="domcontentloaded",
                    timeout=self.navigation_timeout_ms,
                )
                page.wait_for_timeout(3000)
                if self._authentication_required(page):
                    raise YouTubeAuthenticationRequired(
                        "Connectez-vous à la chaîne MS Performance dans cette fenêtre, "
                        "fermez-la, puis relancez le contrôle."
                    )
                if "studio.youtube.com" not in page.url.casefold():
                    raise YouTubeUploadError(
                        "YouTube Studio n’est pas accessible avec ce profil Chrome."
                    )
                print(f"[YOUTUBE] Chaîne accessible : {self.channel_id}")
                return True
            finally:
                context.close()

    @staticmethod
    def _first_visible(page, selectors, timeout_ms=30000):
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            for selector in selectors:
                locator = page.locator(selector).first
                try:
                    if locator.count() and locator.is_visible():
                        return locator
                except Exception:
                    continue
            page.wait_for_timeout(500)
        raise YouTubeUploadError(
            "YouTube Studio a changé ou l’élément attendu ne s’est pas affiché."
        )

    @staticmethod
    def _replace_text(locator, value):
        locator.click()
        try:
            locator.fill(value)
        except Exception:
            locator.press("Control+A")
            locator.press("Backspace")
            locator.type(value)

    def _open_upload_dialog(self, page):
        inputs = page.locator('input[type="file"]')
        if inputs.count():
            return inputs.first

        create_button = self._first_visible(
            page,
            ("#create-icon", "ytcp-button#create-icon", "button[aria-label*='Create']"),
        )
        create_button.click()
        upload_text = page.get_by_text(
            re.compile(r"(upload videos|mettre en ligne des vidéos)", re.IGNORECASE)
        ).first
        try:
            upload_text.wait_for(state="visible", timeout=15000)
            upload_text.click()
        except PlaywrightTimeoutError as exc:
            raise YouTubeUploadError(
                "Le bouton de mise en ligne YouTube n’a pas été trouvé."
            ) from exc
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            inputs = page.locator('input[type="file"]')
            if inputs.count():
                return inputs.first
            page.wait_for_timeout(500)
        raise YouTubeUploadError("Le sélecteur du fichier vidéo n’a pas été trouvé.")

    @staticmethod
    def _video_id(youtube_url):
        parsed = urlparse(youtube_url)
        host = parsed.netloc.casefold().split(":", 1)[0]
        if host in {"youtu.be", "www.youtu.be"}:
            return parsed.path.strip("/").split("/", 1)[0]
        if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            if parsed.path == "/watch":
                return parse_qs(parsed.query).get("v", [""])[0]
            parts = parsed.path.strip("/").split("/")
            if len(parts) > 1 and parts[0] in {"embed", "shorts", "live"}:
                return parts[1]
        return ""

    def _select_unlisted_visibility(self, page):
        unlisted_selectors = (
            'tp-yt-paper-radio-button[name="UNLISTED"]',
            '#privacy-radios tp-yt-paper-radio-button[name="UNLISTED"]',
        )
        for _step in range(4):
            for selector in unlisted_selectors:
                radio = page.locator(selector).first
                if radio.count() and radio.is_visible():
                    radio.click()
                    return
            next_button = self._first_visible(
                page,
                ("#next-button", "ytcp-button#next-button"),
                timeout_ms=30000,
            )
            next_button.click()
            page.wait_for_timeout(900)
        raise YouTubeUploadError("L’option Non répertoriée n’a pas été trouvée.")

    @staticmethod
    def _wait_button_enabled(page, locator, timeout_ms):
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            try:
                if locator.is_visible() and locator.is_enabled():
                    return
            except Exception:
                pass
            page.wait_for_timeout(1000)
        raise YouTubeUploadError(
            "L’upload YouTube n’est pas terminé dans le délai configuré."
        )

    def upload(self, job):
        video_path = self.resolve_video_path(job)
        title = str((job.get("youtube") or {}).get("title") or video_path.stem)[:100]
        description = str((job.get("youtube") or {}).get("description") or "")[:5000]
        file_size = video_path.stat().st_size
        content_sha256 = _sha256(video_path)
        cached_result = self._load_receipt(
            job,
            content_sha256=content_sha256,
            file_size=file_size,
        )
        if cached_result:
            return cached_result
        print(
            f"[YOUTUBE] Préparation : {video_path.name} "
            f"({file_size / (1024 * 1024):.1f} Mo)"
        )

        with sync_playwright() as playwright:
            context = self._launch_context(playwright)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                try:
                    page.goto(
                        self.upload_url,
                        wait_until="domcontentloaded",
                        timeout=self.navigation_timeout_ms,
                    )
                except PlaywrightTimeoutError:
                    if "studio.youtube.com" not in page.url.casefold():
                        raise
                page.wait_for_timeout(2500)
                if self._authentication_required(page):
                    raise YouTubeAuthenticationRequired(
                        "Le profil Chrome YouTube n’est pas connecté à MS Performance."
                    )

                file_input = self._open_upload_dialog(page)
                file_input.set_input_files(str(video_path))
                print("[YOUTUBE] Fichier transmis à YouTube Studio.")

                title_box = self._first_visible(
                    page,
                    (
                        "#title-textarea #textbox",
                        "ytcp-social-suggestions-textbox#title-textarea #textbox",
                    ),
                    timeout_ms=60000,
                )
                self._replace_text(title_box, title)

                if description:
                    description_box = self._first_visible(
                        page,
                        (
                            "#description-textarea #textbox",
                            "ytcp-social-suggestions-textbox#description-textarea #textbox",
                        ),
                        timeout_ms=30000,
                    )
                    self._replace_text(description_box, description)

                audience = self._first_visible(
                    page,
                    (
                        'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]',
                        '#audience tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]',
                    ),
                    timeout_ms=30000,
                )
                audience.click()
                self._select_unlisted_visibility(page)

                video_link = self._first_visible(
                    page,
                    ("a#video-url", "#video-url"),
                    timeout_ms=60000,
                )
                youtube_url = (video_link.get_attribute("href") or video_link.inner_text()).strip()
                if not youtube_url.startswith("http"):
                    raise YouTubeUploadError(
                        "YouTube Studio n’a pas fourni l’adresse finale de la vidéo."
                    )

                done_button = self._first_visible(
                    page,
                    ("#done-button", "ytcp-button#done-button"),
                    timeout_ms=30000,
                )
                print("[YOUTUBE] Attente de la fin de l’upload…")
                self._wait_button_enabled(page, done_button, self.upload_timeout_ms)
                done_button.click()
                page.wait_for_timeout(2000)
                print(f"[YOUTUBE] Vidéo non répertoriée disponible : {youtube_url}")
                video_id = self._video_id(youtube_url)
                if not video_id:
                    raise YouTubeUploadError(
                        "L’adresse obtenue ne contient pas d’identifiant vidéo valide."
                    )
                result = {
                    "status": "uploaded",
                    "youtube_url": youtube_url,
                    "youtube_video_id": video_id,
                    "content_sha256": content_sha256,
                    "file_size_bytes": file_size,
                }
                self._save_receipt(job, result)
                return result
            finally:
                context.close()
