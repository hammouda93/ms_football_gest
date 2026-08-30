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
                    if self.headless:
                        raise YouTubeAuthenticationRequired(
                            "La première connexion YouTube nécessite "
                            "YOUTUBE_HEADLESS=false."
                        )
                    print()
                    print("[YOUTUBE] Première connexion nécessaire.")
                    print(
                        "[YOUTUBE] Connectez-vous au compte Google de la chaîne "
                        "MS Performance dans cette fenêtre."
                    )
                    print(
                        "[YOUTUBE] Quand YouTube Studio est visible, revenez dans "
                        "PowerShell sans fermer Chrome."
                    )
                    input(
                        "[YOUTUBE] Appuyez sur Entrée après avoir terminé "
                        "la connexion : "
                    )
                    page.goto(
                        self.content_url,
                        wait_until="domcontentloaded",
                        timeout=self.navigation_timeout_ms,
                    )
                    page.wait_for_timeout(5000)
                if self._authentication_required(page):
                    raise YouTubeAuthenticationRequired(
                        "La connexion Google n’est pas terminée. Relancez le "
                        "contrôle après avoir connecté le profil avec Chrome normal."
                    )
                if "studio.youtube.com" not in page.url.casefold():
                    raise YouTubeUploadError(
                        "YouTube Studio n’est pas accessible avec ce profil Chrome."
                    )
                print(f"[YOUTUBE] Chaîne accessible : {self.channel_id}")
                print("[YOUTUBE] Profil Chrome YouTube prêt.")
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

    @staticmethod
    def _attached_file_input(page):
        inputs = page.locator(
            'input[type="file"][accept*="video"], input[type="file"]'
        )
        try:
            return inputs.first if inputs.count() else None
        except Exception:
            return None

    def _wait_for_file_input(self, page, timeout_ms=15000):
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            file_input = self._attached_file_input(page)
            if file_input is not None:
                return file_input
            page.wait_for_timeout(400)
        return None

    def _open_upload_dialog(self, page):
        # L’URL /videos/upload ouvre souvent directement le dialogue. On lui
        # laisse quelques secondes avant d’utiliser le menu Créer.
        file_input = self._wait_for_file_input(page, timeout_ms=8000)
        if file_input is not None:
            print("[YOUTUBE] Dialogue d’upload ouvert directement.")
            return file_input

        create_selectors = (
            "ytcp-button#create-icon",
            "#create-icon",
            'button[aria-label*="Create" i]',
            'button[aria-label*="Créer" i]',
            '[role="button"][aria-label*="Create" i]',
            '[role="button"][aria-label*="Créer" i]',
        )
        upload_item_selectors = (
            'tp-yt-paper-item[test-id="upload"]',
            '[role="menuitem"][test-id="upload"]',
            "tp-yt-paper-item#text-item-0",
            '#paper-list tp-yt-paper-item[test-id="upload"]',
        )

        for attempt in range(1, 4):
            print(
                f"[YOUTUBE] Ouverture du menu Créer "
                f"(tentative {attempt}/3)…"
            )
            create_button = self._first_visible(
                page,
                create_selectors,
                timeout_ms=30000,
            )
            create_button.click()

            upload_item = None
            try:
                upload_item = self._first_visible(
                    page,
                    upload_item_selectors,
                    timeout_ms=12000,
                )
            except YouTubeUploadError:
                # Repli multilingue si YouTube change l’attribut test-id.
                text_item = page.get_by_text(
                    re.compile(
                        r"^(upload videos|mettre en ligne des vidéos|"
                        r"importer des vidéos)$",
                        re.IGNORECASE,
                    )
                ).first
                try:
                    text_item.wait_for(state="visible", timeout=5000)
                    upload_item = text_item
                except PlaywrightTimeoutError:
                    upload_item = None

            if upload_item is None:
                page.keyboard.press("Escape")
                page.wait_for_timeout(800)
                continue

            print("[YOUTUBE] Option Mettre en ligne des vidéos détectée.")
            try:
                upload_item.click(timeout=10000)
            except Exception:
                upload_item.click(force=True, timeout=10000)

            file_input = self._wait_for_file_input(page, timeout_ms=20000)
            if file_input is not None:
                print("[YOUTUBE] Dialogue de sélection du fichier prêt.")
                return file_input

            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)

        raise YouTubeUploadError(
            "Le dialogue de mise en ligne ne s’est pas ouvert après trois "
            "tentatives. Fermez les autres fenêtres YouTube Studio et réessayez."
        )

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
            '[role="radio"][name="UNLISTED"]',
            '[name="UNLISTED"]',
        )
        for _step in range(4):
            for selector in unlisted_selectors:
                radio = page.locator(selector).first
                if radio.count() and radio.is_visible():
                    radio.click()
                    page.wait_for_timeout(500)
                    print("[YOUTUBE] Visibilité sélectionnée : Non répertoriée.")
                    return
            unlisted_text = page.get_by_text(
                re.compile(r"^(unlisted|non répertoriée?)$", re.IGNORECASE)
            ).first
            try:
                if unlisted_text.count() and unlisted_text.is_visible():
                    unlisted_text.click()
                    page.wait_for_timeout(500)
                    print("[YOUTUBE] Visibilité sélectionnée : Non répertoriée.")
                    return
            except Exception:
                pass
            next_button = self._first_visible(
                page,
                ("#next-button", "ytcp-button#next-button"),
                timeout_ms=30000,
            )
            next_button.click()
            page.wait_for_timeout(1200)
        raise YouTubeUploadError("L’option Non répertoriée n’a pas été trouvée.")

    @staticmethod
    def _wait_button_enabled(page, locator, timeout_ms):
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            try:
                aria_disabled = (locator.get_attribute("aria-disabled") or "").lower()
                disabled = locator.get_attribute("disabled")
                if (
                    locator.is_visible()
                    and locator.is_enabled()
                    and aria_disabled != "true"
                    and disabled is None
                ):
                    return
            except Exception:
                pass
            page.wait_for_timeout(1000)
        raise YouTubeUploadError(
            "L’upload YouTube n’est pas terminé dans le délai configuré."
        )

    def _read_video_url(self, page, timeout_ms=90000):
        selectors = (
            'a#video-link[href*="youtu.be/"]',
            "a#video-link",
            "#video-link",
            'a[href*="youtu.be/"]',
            'a[href*="youtube.com/watch"]',
        )
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            for selector in selectors:
                links = page.locator(selector)
                try:
                    count = min(links.count(), 10)
                except Exception:
                    count = 0
                for index in range(count):
                    link = links.nth(index)
                    try:
                        href = (link.get_attribute("href") or "").strip()
                        text = (link.inner_text() or "").strip()
                    except Exception:
                        continue
                    for candidate in (href, text):
                        if candidate.startswith("youtu.be/"):
                            candidate = f"https://{candidate}"
                        video_id = self._video_id(candidate)
                        if video_id:
                            return f"https://youtu.be/{video_id}"
            page.wait_for_timeout(500)
        raise YouTubeUploadError(
            "YouTube Studio n’a pas fourni l’adresse de la vidéo dans le délai prévu."
        )

    def _wait_upload_transfer_complete(self, page):
        progress = page.locator("ytcp-video-upload-progress").first
        appearance_deadline = time.monotonic() + 60
        while time.monotonic() < appearance_deadline:
            try:
                if progress.count() and progress.is_visible():
                    break
            except Exception:
                pass
            if self._upload_completion_detected(page):
                print(
                    "[YOUTUBE] Transfert terminé avant la première "
                    "lecture du pourcentage."
                )
                return
            page.wait_for_timeout(250)
        else:
            raise YouTubeUploadError(
                "YouTube n’a affiché ni progression ni confirmation de fin "
                "de transfert."
            )
        deadline = time.monotonic() + self.upload_timeout_ms / 1000
        last_status = ""
        consecutive_complete_checks = 0

        while time.monotonic() < deadline:
            try:
                is_uploading = progress.get_attribute("uploading") is not None
                status_locator = progress.locator(".progress-label").first
                status = (
                    status_locator.inner_text().strip()
                    if status_locator.count()
                    else ""
                )
                bars = progress.locator(
                    'tp-yt-paper-progress[aria-label*="upload" i], '
                    'tp-yt-paper-progress[aria-label*="mise en ligne" i]'
                )
                percentage = ""
                if bars.count():
                    percentage = (
                        bars.first.get_attribute("aria-valuenow") or ""
                    ).strip()

                display_status = status or (
                    f"Upload {percentage}%" if percentage else "Upload en cours"
                )
                if display_status and display_status != last_status:
                    print(f"[YOUTUBE] {display_status}")
                    last_status = display_status

                percentage_complete = False
                try:
                    percentage_complete = bool(
                        percentage and float(percentage) >= 100
                    )
                except ValueError:
                    percentage_complete = False

                status_complete = bool(
                    re.search(
                        r"(upload complete|uploaded|mise en ligne terminée|"
                        r"importation terminée)",
                        status,
                        re.IGNORECASE,
                    )
                )

                if not is_uploading or percentage_complete or status_complete:
                    consecutive_complete_checks += 1
                else:
                    consecutive_complete_checks = 0

                # Deux lectures successives évitent de considérer comme terminé
                # un composant transitoire recréé au passage de 99 à 100 %.
                if consecutive_complete_checks >= 2:
                    print(
                        "[YOUTUBE] Transfert du fichier terminé. "
                        "Les vérifications YouTube peuvent commencer."
                    )
                    return
            except Exception:
                # YouTube recrée parfois le composant au moment où le transfert
                # se termine. On recherche alors sa nouvelle instance visible.
                try:
                    progress = self._first_visible(
                        page,
                        ("ytcp-video-upload-progress",),
                        timeout_ms=10000,
                    )
                except YouTubeUploadError:
                    print(
                        "[YOUTUBE] Le composant de transfert a disparu : "
                        "upload terminé."
                    )
                    return
            page.wait_for_timeout(500)

        raise YouTubeUploadError(
            "Le transfert YouTube n’a pas atteint 100 % dans le délai configuré."
        )

    @staticmethod
    def _upload_completion_detected(page):
        hosts = page.locator(
            "ytcp-video-upload-progress, ytcp-uploads-dialog, "
            "ytcp-video-upload-dialog"
        )
        try:
            count = min(hosts.count(), 10)
        except Exception:
            return False
        for index in range(count):
            try:
                text = hosts.nth(index).inner_text()
            except Exception:
                continue
            if re.search(
                r"(upload complete|uploaded|mise en ligne terminée|"
                r"importation terminée|transfert terminé|"
                r"processing will begin shortly|traitement va bientôt commencer)",
                text or "",
                re.IGNORECASE,
            ):
                return True
        return False

    @staticmethod
    def _wait_upload_dialog_closed(page, timeout_ms=45000):
        dialogs = page.locator(
            "ytcp-uploads-dialog, ytcp-video-upload-dialog, "
            "ytcp-uploads-still-processing-dialog, "
            "ytcp-prechecks-warning-dialog, "
            "tp-yt-paper-dialog:has(button[aria-label=\"Publier quand même\"]), "
            "tp-yt-paper-dialog:has(button[aria-label=\"Publish anyway\"])"
        )
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            try:
                visible = any(
                    dialogs.nth(index).is_visible()
                    for index in range(dialogs.count())
                )
            except Exception:
                visible = False
            if not visible:
                return True
            page.wait_for_timeout(500)
        return False

    def _publish_anyway_if_prechecks_pending(self, page):
        """Confirm publication when YouTube checks are still running."""
        selectors = (
            "ytcp-prechecks-warning-dialog ytcp-button#secondary-action-button",
            "ytcp-prechecks-warning-dialog button[aria-label=\"Publier quand même\"]",
            "ytcp-prechecks-warning-dialog button[aria-label=\"Publish anyway\"]",
            "tp-yt-paper-dialog button[aria-label=\"Publier quand même\"]",
            "tp-yt-paper-dialog button[aria-label=\"Publish anyway\"]",
        )
        try:
            publish_anyway = self._first_visible(
                page,
                selectors,
                timeout_ms=10000,
            )
        except YouTubeUploadError:
            return False

        print(
            "[YOUTUBE] Vérifications encore en cours : clic sur "
            "Publier quand même…"
        )
        self._wait_button_enabled(page, publish_anyway, timeout_ms=30000)
        try:
            publish_anyway.click(timeout=15000)
        except Exception:
            publish_anyway.click(force=True, timeout=15000)

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if not publish_anyway.is_visible():
                    return True
            except Exception:
                return True
            page.wait_for_timeout(250)
        raise YouTubeUploadError(
            "YouTube n’a pas fermé la confirmation Publier quand même."
        )

    def _finish_still_processing_dialog(self, page):
        dialog = page.locator("ytcp-uploads-still-processing-dialog").first
        try:
            dialog.wait_for(state="visible", timeout=10000)
        except PlaywrightTimeoutError:
            return False

        print(
            "[YOUTUBE] YouTube confirme l’enregistrement, mais le fichier est "
            "encore en cours d’envoi."
        )
        print("[YOUTUBE] Attente de la fin réelle du transfert…")

        progress = dialog.locator("ytcp-video-upload-progress").first
        deadline = time.monotonic() + self.upload_timeout_ms / 1000
        last_status = ""
        upload_finished = False

        while time.monotonic() < deadline:
            try:
                progress_exists = progress.count() > 0
                is_uploading = (
                    progress_exists
                    and progress.get_attribute("uploading") is not None
                )
                status_locator = progress.locator(".progress-label").first
                status = (
                    status_locator.inner_text().strip()
                    if status_locator.count()
                    else ""
                )
                bars = progress.locator(
                    'tp-yt-paper-progress[aria-label*="upload" i], '
                    'tp-yt-paper-progress[aria-label*="mise en ligne" i]'
                )
                percentage = ""
                if bars.count():
                    percentage = (
                        bars.first.get_attribute("aria-valuenow") or ""
                    ).strip()
                display_status = status or (
                    f"Upload {percentage}%" if percentage else "Upload en cours"
                )
                if display_status and display_status != last_status:
                    print(f"[YOUTUBE] {display_status}")
                    last_status = display_status

                if not progress_exists or not is_uploading:
                    upload_finished = True
                    break
                try:
                    if percentage and float(percentage) >= 100:
                        # L’attribut uploading disparaît généralement juste après
                        # que la barre atteint 100 %.
                        page.wait_for_timeout(1500)
                except ValueError:
                    pass
            except Exception:
                # Le composant peut être recréé par YouTube au passage de 99 à
                # 100 %. S’il disparaît, le transfert est terminé.
                try:
                    if not dialog.is_visible():
                        return True
                except Exception:
                    return True
            page.wait_for_timeout(1500)

        if not upload_finished:
            raise YouTubeUploadError(
                "Le transfert YouTube n’a pas atteint 100 % dans le délai configuré."
            )

        print("[YOUTUBE] Transfert terminé. Fermeture de la confirmation…")
        close_button = self._first_visible(
            page,
            (
                "ytcp-uploads-still-processing-dialog ytcp-button#close-button",
                "ytcp-uploads-still-processing-dialog #close-button",
                'ytcp-uploads-still-processing-dialog button[aria-label="Close"]',
                'ytcp-uploads-still-processing-dialog button[aria-label="Fermer"]',
            ),
            timeout_ms=30000,
        )
        self._wait_button_enabled(page, close_button, timeout_ms=30000)
        try:
            close_button.click(timeout=15000)
        except Exception:
            close_button.click(force=True, timeout=15000)
        return True

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

                youtube_url = self._read_video_url(page, timeout_ms=90000)
                video_id = self._video_id(youtube_url)
                if not video_id:
                    raise YouTubeUploadError(
                        "L’adresse obtenue ne contient pas d’identifiant vidéo valide."
                    )
                print(f"[YOUTUBE] Lien attribué : {youtube_url}")

                print("[YOUTUBE] Suivi immédiat du transfert avant Enregistrer…")
                self._wait_upload_transfer_complete(page)
                done_button = self._first_visible(
                    page,
                    (
                        "ytcp-button#done-button",
                        "#done-button",
                        'ytcp-button[aria-label*="Save" i]',
                        'ytcp-button[aria-label*="Enregistrer" i]',
                    ),
                    timeout_ms=30000,
                )
                self._wait_button_enabled(page, done_button, self.upload_timeout_ms)
                print("[YOUTUBE] Enregistrement de la vidéo…")
                try:
                    done_button.click(timeout=15000)
                except Exception:
                    done_button.click(force=True, timeout=15000)

                prechecks_confirmed = self._publish_anyway_if_prechecks_pending(page)
                if not prechecks_confirmed:
                    self._finish_still_processing_dialog(page)
                dialog_closed = self._wait_upload_dialog_closed(
                    page,
                    timeout_ms=60000,
                )
                if not dialog_closed:
                    raise YouTubeUploadError(
                        "YouTube Studio n’a pas confirmé la fermeture du dialogue "
                        "après Enregistrer. Vérifiez la vidéo avant toute reprise."
                    )

                print(f"[YOUTUBE] Vidéo non répertoriée disponible : {youtube_url}")
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
