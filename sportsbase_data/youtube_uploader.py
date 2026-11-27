"""Local, resumable YouTube Studio automation for All Actions videos."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


DEFAULT_CHANNEL_ID = "UCB2SMAxFXOcWDDDX5FtI9iA"
DEFAULT_PROFILE_DIR = r"D:\YouTube_MSPerformance_Profile"
DEFAULT_HIGHLIGHTS_PROFILE_DIR = r"D:\YouTube_Highlights_Profile"
DEFAULT_HIGHLIGHTS_PROFILE_NAME = "Default"
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
ALLOWED_THUMBNAIL_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MAX_THUMBNAIL_FILE_SIZE_BYTES = 50 * 1024 * 1024


class YouTubeUploadError(RuntimeError):
    pass


class YouTubePostSaveUnconfirmed(YouTubeUploadError):
    """Transfer finished, but publication could not be confirmed."""


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


def _profile_path_key(path):
    return (
        os.path.normcase(os.path.abspath(str(path)))
        .replace("\\", "/")
        .rstrip("/")
        .casefold()
    )


class YouTubeStudioUploader:
    def __init__(self, storage_root, *, config_prefix="YOUTUBE"):
        self.storage_root = Path(storage_root)
        self.config_prefix = str(config_prefix or "YOUTUBE").strip().upper().rstrip("_")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", self.config_prefix):
            raise YouTubeUploadError("Le préfixe de configuration YouTube est invalide.")

        def setting_name(suffix):
            return f"{self.config_prefix}_{suffix}"

        is_performance_config = self.config_prefix == "YOUTUBE"
        default_channel_id = DEFAULT_CHANNEL_ID if is_performance_config else ""
        self.channel_id = os.getenv(
            setting_name("STUDIO_CHANNEL_ID"), default_channel_id
        ).strip()
        if not self.channel_id:
            raise YouTubeUploadError(
                f"{setting_name('STUDIO_CHANNEL_ID')} est obligatoire."
            )

        default_profile_dir = (
            DEFAULT_PROFILE_DIR
            if is_performance_config
            else DEFAULT_HIGHLIGHTS_PROFILE_DIR
        )
        configured_profile_dir = os.getenv(
            setting_name("CHROME_PROFILE_DIR"), ""
        ).strip()
        self.profile_dir = Path(configured_profile_dir or default_profile_dir)
        default_profile_name = (
            DEFAULT_HIGHLIGHTS_PROFILE_NAME
            if self.config_prefix == "HIGHLIGHTS_YOUTUBE"
            else ""
        )
        self.chrome_profile_name = os.getenv(
            setting_name("CHROME_PROFILE_NAME"),
            default_profile_name,
        ).strip()
        if self.chrome_profile_name and not re.fullmatch(
            r"(?:Default|Profile [0-9]+)", self.chrome_profile_name
        ):
            raise YouTubeUploadError(
                f"{setting_name('CHROME_PROFILE_NAME')} est invalide. "
                "Utilisez par exemple Default ou Profile 1."
            )
        if self.config_prefix == "HIGHLIGHTS_YOUTUBE":
            performance_channel_id = (
                os.getenv("YOUTUBE_STUDIO_CHANNEL_ID", DEFAULT_CHANNEL_ID).strip()
                or DEFAULT_CHANNEL_ID
            )
            performance_profile_dir = Path(
                os.getenv("YOUTUBE_CHROME_PROFILE_DIR", "").strip()
                or DEFAULT_PROFILE_DIR
            )
            if self.channel_id == performance_channel_id:
                raise YouTubeUploadError(
                    "La chaîne Highlights doit être différente de la chaîne Performance."
                )
            if _profile_path_key(self.profile_dir) == _profile_path_key(
                performance_profile_dir
            ):
                raise YouTubeUploadError(
                    "HIGHLIGHTS_YOUTUBE_CHROME_PROFILE_DIR doit être différent de "
                    "YOUTUBE_CHROME_PROFILE_DIR."
                )
        self.browser_channel = os.getenv(
            setting_name("BROWSER_CHANNEL"),
            os.getenv("YOUTUBE_BROWSER_CHANNEL", "chrome"),
        ).strip()
        self.chrome_executable = os.getenv(
            setting_name("CHROME_EXE"), ""
        ).strip()
        self.headless = _env_bool(setting_name("HEADLESS"), False)
        self.upload_timeout_ms = int(
            os.getenv(
                setting_name("UPLOAD_TIMEOUT_MINUTES"),
                os.getenv("YOUTUBE_UPLOAD_TIMEOUT_MINUTES", "180"),
            )
        ) * 60 * 1000
        self.navigation_timeout_ms = int(
            os.getenv(
                setting_name("NAVIGATION_TIMEOUT_SECONDS"),
                os.getenv("YOUTUBE_NAVIGATION_TIMEOUT_SECONDS", "90"),
            )
        ) * 1000
        configured_upload_url = os.getenv(
            setting_name("STUDIO_UPLOAD_URL"), ""
        ).strip()
        self.upload_url = configured_upload_url or (
            f"https://studio.youtube.com/channel/{self.channel_id}/videos/upload"
        )
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
        receipt_channel_id = str(receipt.get("youtube_channel_id") or "").strip()
        if (
            receipt.get("status") != "uploaded"
            or receipt.get("content_sha256") != content_sha256
            or int(receipt.get("file_size_bytes") or 0) != file_size
            or (receipt_channel_id and receipt_channel_id != self.channel_id)
            or (not receipt_channel_id and self.config_prefix != "YOUTUBE")
            or not video_id
        ):
            return None
        receipt["youtube_video_id"] = video_id
        print(
            "[YOUTUBE] Reçu local retrouvé : la vidéo déjà publiée ne sera pas "
            "envoyée une seconde fois."
        )
        return receipt

    def _load_pending_receipt(self, job, *, content_sha256, file_size):
        """Recover a known YouTube ID before any new upload is attempted."""
        receipt_path = self._receipt_path(job)
        if not receipt_path.is_file():
            return None
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        youtube_url = str(receipt.get("youtube_url") or "").strip()
        if (
            receipt.get("status") != "link_assigned"
            or receipt.get("content_sha256") != content_sha256
            or int(receipt.get("file_size_bytes") or 0) != file_size
            or receipt.get("youtube_channel_id") != self.channel_id
            or not self._video_id(youtube_url)
        ):
            return None
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

    def resolve_thumbnail_path(self, job):
        raw_path = str(
            (job.get("youtube") or {}).get("thumbnail_path") or ""
        ).strip()
        if not raw_path:
            return None

        normalized = raw_path.replace("\\", "/")
        relative = PurePosixPath(normalized)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or re.match(r"^[A-Za-z]:", normalized)
        ):
            raise YouTubeUploadError(
                "Le chemin de la miniature YouTube est invalide."
            )

        root = self.storage_root.resolve()
        candidate = root.joinpath(*relative.parts).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise YouTubeUploadError(
                "La miniature YouTube se trouve hors du stockage autorisé."
            ) from exc
        if not candidate.is_file():
            raise YouTubeUploadError(
                f"Miniature YouTube introuvable : {candidate}"
            )
        if candidate.suffix.casefold() not in ALLOWED_THUMBNAIL_EXTENSIONS:
            raise YouTubeUploadError(
                "La miniature YouTube doit être au format JPG ou PNG."
            )
        file_size = candidate.stat().st_size
        if file_size <= 0:
            raise YouTubeUploadError("La miniature YouTube est vide.")
        if file_size > MAX_THUMBNAIL_FILE_SIZE_BYTES:
            raise YouTubeUploadError(
                "La miniature YouTube dépasse la limite de 50 Mo."
            )
        return candidate

    def _launch_context(self, playwright):
        launch_args = ["--start-maximized"]
        if self.chrome_profile_name:
            copied_profile_dir = self.profile_dir / self.chrome_profile_name
            local_state_path = self.profile_dir / "Local State"
            if not copied_profile_dir.is_dir():
                raise YouTubeUploadError(
                    "Profil Chrome copié introuvable : "
                    f"{copied_profile_dir}. Copiez le dossier "
                    f"{self.chrome_profile_name} complet à cet emplacement."
                )
            if not local_state_path.is_file():
                raise YouTubeUploadError(
                    "Fichier Chrome 'Local State' introuvable : "
                    f"{local_state_path}. Copiez-le depuis le dossier User Data "
                    "d’origine pour conserver la session Google."
                )
            launch_args.append(
                f"--profile-directory={self.chrome_profile_name}"
            )
        else:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
        print(
            "[YOUTUBE] Ouverture Google Chrome avec profil persistant : "
            f"{self.profile_dir}"
        )
        if self.chrome_profile_name:
            print(f"[YOUTUBE] Sous-profil Chrome : {self.chrome_profile_name}")
        try:
            return playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                channel=self.browser_channel or None,
                headless=self.headless,
                no_viewport=True,
                args=launch_args,
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

    def _find_normal_chrome_executable(self):
        candidates = []
        if self.chrome_executable:
            candidates.append(Path(self.chrome_executable))

        for environment_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base_dir = os.getenv(environment_name, "").strip()
            if base_dir:
                candidates.append(
                    Path(base_dir)
                    / "Google"
                    / "Chrome"
                    / "Application"
                    / "chrome.exe"
                )

        for command_name in ("chrome", "google-chrome", "google-chrome-stable"):
            resolved = shutil.which(command_name)
            if resolved:
                candidates.append(Path(resolved))

        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise YouTubeUploadError(
            "Google Chrome normal est introuvable. Configurez "
            f"{self.config_prefix}_CHROME_EXE avec le chemin de chrome.exe."
        )

    def setup_access_with_normal_chrome(self):
        """Authenticate in regular Chrome before Playwright reuses the session."""
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        chrome_executable = self._find_normal_chrome_executable()
        profile_name = self.chrome_profile_name or "Default"
        command = [
            str(chrome_executable),
            f"--user-data-dir={self.profile_dir}",
            f"--profile-directory={profile_name}",
            "--new-window",
            self.content_url,
        ]
        print(f"[YOUTUBE] Chrome normal : {chrome_executable}")
        print(f"[YOUTUBE] Profil persistant : {self.profile_dir}")
        print(f"[YOUTUBE] Sous-profil : {profile_name}")
        print(
            "[YOUTUBE] Connectez-vous normalement à Google et ouvrez la bonne "
            "chaîne dans YouTube Studio."
        )
        try:
            subprocess.Popen(command)
        except OSError as exc:
            raise YouTubeUploadError(
                f"Impossible d’ouvrir Google Chrome normal : {exc}"
            ) from exc
        input(
            "[YOUTUBE] Fermez complètement cette fenêtre Chrome, puis appuyez "
            "sur Entrée pour vérifier la session : "
        )
        return self.check_access(allow_interactive_login=False)

    def check_access(self, *, allow_interactive_login=True):
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
                    if not allow_interactive_login:
                        raise YouTubeAuthenticationRequired(
                            "La session Google n’est pas encore connectée dans le "
                            f"profil {self.profile_dir}. Relancez la préparation avec "
                            "--setup-youtube dans Chrome normal."
                        )
                    if self.headless:
                        raise YouTubeAuthenticationRequired(
                            "La première connexion YouTube nécessite "
                            f"{self.config_prefix}_HEADLESS=false."
                        )
                    print()
                    print("[YOUTUBE] Première connexion nécessaire.")
                    print(
                        "[YOUTUBE] Connectez-vous au compte Google puis sélectionnez "
                        f"la chaîne {self.channel_id} dans cette fenêtre."
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
    def _attached_thumbnail_input(page):
        selectors = (
            "ytcp-video-custom-still-editor "
            'ytcp-thumbnail-uploader input#file-loader[type="file"]',
            'ytcp-thumbnail-uploader input#file-loader[type="file"]',
            'ytcp-thumbnail-uploader input[type="file"][accept*="image"]',
        )
        for selector in selectors:
            inputs = page.locator(selector)
            try:
                if inputs.count():
                    return inputs.first
            except Exception:
                continue
        return None

    def _upload_thumbnail(self, page, thumbnail_path, timeout_ms=60000):
        deadline = time.monotonic() + timeout_ms / 1000
        file_input = None
        while time.monotonic() < deadline:
            file_input = self._attached_thumbnail_input(page)
            if file_input is not None:
                break
            page.wait_for_timeout(400)
        if file_input is None:
            raise YouTubeUploadError(
                "Le champ Importer un fichier de la miniature YouTube "
                "n’a pas été trouvé."
            )

        # YouTube garde cet input masqué derrière le bouton « Importer un
        # fichier ». set_input_files évite le sélecteur de fichiers Windows et
        # transmet le chemin directement au contrôle officiel de Studio.
        file_input.set_input_files(str(thumbnail_path))
        preview = page.locator(
            "ytcp-video-custom-still-editor "
            "ytcp-thumbnail-uploader button#preview-button"
        ).first
        try:
            preview.wait_for(state="visible", timeout=timeout_ms)
        except PlaywrightTimeoutError as exc:
            raise YouTubeUploadError(
                "YouTube Studio n’a pas confirmé l’import de la miniature."
            ) from exc
        uploading = page.locator(
            "ytcp-video-custom-still-editor "
            "ytcp-thumbnail-uploader .uploading"
        ).first
        try:
            uploading.wait_for(state="hidden", timeout=timeout_ms)
        except PlaywrightTimeoutError as exc:
            raise YouTubeUploadError(
                "L’import de la miniature YouTube n’est pas terminé."
            ) from exc
        print(
            "[YOUTUBE] Miniature personnalisée importée : "
            f"{thumbnail_path.name}"
        )

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

    def _select_visibility(self, page, visibility):
        visibility_key = str(visibility or "unlisted").strip().upper()
        visibility_options = {
            "PUBLIC": (
                "Publique",
                re.compile(r"^(public|publique)$", re.IGNORECASE),
            ),
            "UNLISTED": (
                "Non répertoriée",
                re.compile(r"^(unlisted|non répertoriée?)$", re.IGNORECASE),
            ),
            "PRIVATE": (
                "Privée",
                re.compile(r"^(private|privée?)$", re.IGNORECASE),
            ),
        }
        if visibility_key not in visibility_options:
            raise YouTubeUploadError(
                "La visibilité YouTube doit être public, unlisted ou private."
            )
        visibility_label, visibility_text_pattern = visibility_options[
            visibility_key
        ]
        visibility_selectors = (
            f'tp-yt-paper-radio-button[name="{visibility_key}"]',
            "#privacy-radios "
            f'tp-yt-paper-radio-button[name="{visibility_key}"]',
            f'[role="radio"][name="{visibility_key}"]',
            f'[name="{visibility_key}"]',
        )
        # Details -> Video elements -> Checks -> Visibility. Do not pause
        # for a fixed 1.2 s after every transition: the UI itself decides
        # when Next is enabled, and each step is checked immediately.
        for step in range(4):
            for selector in visibility_selectors:
                radio = page.locator(selector).first
                if radio.count() and radio.is_visible():
                    radio.click(timeout=15000)
                    print(
                        "[YOUTUBE] Visibilité sélectionnée : "
                        f"{visibility_label}."
                    )
                    return visibility_key.casefold()
            visibility_text = page.get_by_text(
                visibility_text_pattern
            ).first
            try:
                if visibility_text.count() and visibility_text.is_visible():
                    visibility_text.click(timeout=5000)
                    print(
                        "[YOUTUBE] Visibilité sélectionnée : "
                        f"{visibility_label}."
                    )
                    return visibility_key.casefold()
            except Exception:
                pass
            if step == 3:
                break
            next_button = self._first_visible(
                page,
                ("#next-button", "ytcp-button#next-button"),
                timeout_ms=30000,
            )
            started = time.monotonic()
            self._wait_button_enabled(page, next_button, timeout_ms=30000)
            waited = time.monotonic() - started
            if waited >= 1.0:
                print(
                    "[YOUTUBE] YouTube a attendu {:.1f}s avant "
                    "d’autoriser l’étape suivante.".format(waited)
                )
            next_button.click(timeout=10000)
            print(
                f"[YOUTUBE] Étape YouTube {step + 1}/3 validée "
                "(passage immédiat)."
            )
        raise YouTubeUploadError(
            f"L’option {visibility_label} n’a pas été trouvée."
        )

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

    def _video_is_published_in_studio(self, context, video_id, visibility, *, page=None):
        """Require a matching video row with finalized visibility, not a stale %.

        A row still marked Uploading/Pending/Draft is never considered a success.
        The check uses a separate tab to preserve the in-progress upload dialog.
        """
        expected = {
            "unlisted": ("unlisted", "non répertoriée", "non repertoriee"),
            "public": ("public", "publique"),
            "private": ("private", "privée", "privee"),
        }.get(visibility, ())
        if not expected or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            return False
        verification_page = page
        owns_page = page is None
        try:
            if owns_page:
                verification_page = context.new_page()
            verification_page.goto(
                self.content_url,
                wait_until="domcontentloaded",
                timeout=self.navigation_timeout_ms if owns_page else 8000,
            )
            rows = verification_page.locator("ytcp-video-row")
            rows.first.wait_for(state="visible", timeout=15000 if owns_page else 5000)
            for index in range(min(rows.count(), 60)):
                row = rows.nth(index)
                link = row.locator(f'a[href*="{video_id}"]').first
                if not link.count():
                    continue
                href = (link.get_attribute("href") or "").strip()
                if not any(
                    marker in href
                    for marker in (
                        f"/video/{video_id}",
                        f"v={video_id}",
                        f"youtu.be/{video_id}",
                    )
                ):
                    continue
                row_text = row.inner_text().casefold()
                if re.search(
                    r"(uploading|mise en ligne|importation|pending|"
                    r"en attente|draft|brouillon)\b",
                    row_text,
                    re.IGNORECASE,
                ):
                    continue
                visibility_node = row.locator(
                    "ytcp-video-visibility, ytcp-video-visibility-select"
                ).first
                if not visibility_node.count():
                    continue
                visibility_text = visibility_node.inner_text().casefold()
                if any(label in visibility_text for label in expected):
                    print(
                        "[YOUTUBE] Publication confirmée dans la liste Studio "
                        f"pour la vidéo {video_id} ({visibility})."
                    )
                    return True
            return False
        except Exception as exc:
            print(
                "[YOUTUBE] Vérification Studio non concluante : "
                f"{type(exc).__name__}"
            )
            return False
        finally:
            if owns_page and verification_page is not None:
                try:
                    verification_page.close()
                except PlaywrightError:
                    pass

    def _wait_for_save_or_studio_confirmation(
        self, page, done_button, video_id, visibility
    ):
        """Wait for Save after the file transfer has been verified complete."""
        deadline = time.monotonic() + self.upload_timeout_ms / 1000
        next_studio_check = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                aria_disabled = (
                    done_button.get_attribute("aria-disabled") or ""
                ).lower()
                if (
                    done_button.is_visible()
                    and done_button.is_enabled()
                    and aria_disabled != "true"
                    and done_button.get_attribute("disabled") is None
                ):
                    return True
            except Exception:
                pass
            if time.monotonic() >= next_studio_check:
                if self._video_is_published_in_studio(
                    page.context, video_id, visibility
                ):
                    return False
                next_studio_check = time.monotonic() + 30
            page.wait_for_timeout(1000)
        raise YouTubeUploadError(
            "Enregistrer est resté désactivé et Studio n’a pas confirmé "
            f"la publication de https://youtu.be/{video_id}. "
            "L’identifiant est conservé pour éviter un upload en double."
        )

    def _wait_upload_transfer_complete(self, page):
        """Wait for proof that the file transfer ended before clicking Save.

        A video ID, an enabled Save button, a missing progress element and
        a stale percentage are NOT proof of completed transfer.
        """
        print(
            "[YOUTUBE] Visibilité définie : attente du transfert complet "
            "avant Enregistrer…"
        )
        deadline = time.monotonic() + self.upload_timeout_ms / 1000
        last_status = ""
        consecutive_complete_checks = 0
        progress_seen = False
        while time.monotonic() < deadline:
            if page.is_closed():
                raise YouTubeUploadError(
                    "La fenêtre Chrome a été fermée pendant le transfert. "
                    "La publication n'est pas confirmée."
                )

            progress = page.locator("ytcp-video-upload-progress").first
            progress_visible = progress.count() > 0 and progress.is_visible()
            status = ""
            percentage = ""
            is_uploading = False
            explicit_complete = False

            if progress_visible:
                progress_seen = True
                uploading_attribute = progress.get_attribute("uploading")
                is_uploading = (
                    uploading_attribute is not None
                    and uploading_attribute.strip().lower() not in ("false", "0")
                )
                status_locator = progress.locator(".progress-label").first
                if status_locator.count():
                    status = status_locator.inner_text().strip()
                if not status:
                    status = progress.inner_text().strip()
                bars = progress.locator(
                    'tp-yt-paper-progress[aria-label*="upload" i], '
                    'tp-yt-paper-progress[aria-label*="mise en ligne" i]'
                )
                if bars.count():
                    percentage = (
                        bars.first.get_attribute("aria-valuenow") or ""
                    ).strip()
                if not percentage:
                    match = re.search(
                        r"(?:upload(?:ing)?|mise en ligne|importation)"
                        r"[^\d]{0,35}(\d{1,3})\s*%",
                        status,
                        re.IGNORECASE,
                    )
                    if match:
                        percentage = match.group(1)

                explicit_complete = bool(
                    re.search(
                        r"(upload complete|upload successful"
                        r"|mise en ligne terminée|importation terminée"
                        r"|transfert terminé|processing will begin shortly"
                        r"|traitement va bientôt commencer)",
                        status,
                        re.IGNORECASE,
                    )
                )

            percent_complete = False
            try:
                percent_complete = bool(
                    percentage and float(percentage) >= 100
                )
            except ValueError:
                pass

            # The completion banner also covers very fast transfers, where
            # the progress widget can disappear before the first poll.
            completion_banner = self._upload_completion_detected(page)
            transfer_finished = (
                (progress_visible and not is_uploading
                 and (completion_banner or explicit_complete or percent_complete))
                or (not progress_visible and completion_banner)
            )
            current_status = status or (
                f"Upload {percentage}%" if percentage else
                ("Progression indisponible" if progress_seen else "Transfert en cours")
            )
            if current_status != last_status:
                print(f"[YOUTUBE] {current_status}")
                last_status = current_status

            if transfer_finished:
                consecutive_complete_checks += 1
            else:
                consecutive_complete_checks = 0
            if consecutive_complete_checks >= 3:
                print(
                    "[YOUTUBE] Transfert confirmé terminé (100 % ou "
                    "confirmation explicite de YouTube). "
                    "Autorisation d'enregistrer."
                )
                return
            page.wait_for_timeout(1000)

        raise YouTubeUploadError(
            "Transfert YouTube non confirmé avant le délai configuré. "
            "Vidéo NON marquée uploaded ; ne pas lancer le fichier suivant."
        )

    @staticmethod
    def _upload_completion_detected(page):
        """Only accept an explicit end-of-transfer notice (not 'Uploaded 94%')."""
        hosts = page.locator(
            "ytcp-video-upload-progress, ytcp-uploads-dialog, "
            "ytcp-video-upload-dialog"
        )
        count = min(hosts.count(), 10)
        for index in range(count):
            text = hosts.nth(index).inner_text() or ""
            if re.search(
                r"(upload complete|upload successful"
                r"|mise en ligne terminée|importation terminée"
                r"|transfert terminé|processing will begin shortly"
                r"|traitement va bientôt commencer"
                r"|100\s*%\s*uploaded)",
                text,
                re.IGNORECASE,
            ):
                return True
        return False

    def _publish_anyway_if_prechecks_pending(self, page):
        """Click an explicit, visible optional confirmation, without waiting for absence."""
        if page.is_closed():
            return False
        pattern = re.compile(r"^(?:Publier quand même|Publish anyway)$", re.I)
        blocked = False
        try:
            for scope in ("ytcp-prechecks-warning-dialog", "tp-yt-paper-dialog"):
                dialog = page.locator(scope)
                candidates = (
                    dialog.get_by_role("button", name=pattern),
                    dialog.locator(
                        'ytcp-button[aria-label="Publier quand même"], '
                        'ytcp-button[aria-label="Publish anyway"]'
                    ),
                )
                for matches in candidates:
                    for index in range(matches.count()):
                        button = matches.nth(index)
                        if not button.is_visible():
                            continue
                        if (
                            not button.is_enabled(timeout=500)
                            or (button.get_attribute("aria-disabled", timeout=500) or "").lower() == "true"
                            or button.get_attribute("disabled", timeout=500) is not None
                        ):
                            blocked = True
                            continue
                        try:
                            button.click(timeout=1500)
                        except PlaywrightError:
                            if page.is_closed():
                                return False
                            if button.is_visible():
                                blocked = True
                            continue
                        print("[YOUTUBE] Bouton Publier quand même cliqué.")
                        return True
        except PlaywrightError:
            if page.is_closed():
                return False
            raise
        if blocked:
            raise YouTubeUploadError(
                "Publier quand même est visible mais non cliquable. "
                "L’identifiant est conservé pour éviter un doublon."
            )
        return False

    def _close_published_confirmation(self, page, video_id):
        """Only close a final success dialog, never the upload wizard/draft."""
        success = re.compile(
            r"\b(?:video (?:published|saved)|vidéo (?:publiée|enregistrée)|"
            r"publication (?:terminée|réussie)|video has been published)\b", re.I
        )
        close_name = re.compile(r"^(?:close|fermer|done|terminé|ok)$", re.I)
        for scope in ("ytcp-video-publish-dialog", "ytcp-video-published-dialog",
                      "ytcp-uploads-still-processing-dialog", "tp-yt-paper-dialog"):
            dialogs = page.locator(scope)
            for index in range(dialogs.count()):
                dialog = dialogs.nth(index)
                if not dialog.is_visible():
                    continue
                message = dialog.inner_text(timeout=1000)
                if not success.search(message) or re.search(
                    r"\b(?:draft|brouillon|uploading|importation en cours)\b",
                    message, re.I,
                ):
                    continue
                # If a video link is displayed, it must belong to this upload.
                links = dialog.locator('a[href*="youtu.be/"], a[href*="youtube.com/watch"]')
                ids = {
                    self._video_id(links.nth(n).get_attribute("href", timeout=500) or "")
                    for n in range(links.count())
                } - {""}
                if ids and video_id not in ids:
                    continue
                button = dialog.get_by_role("button", name=close_name).first
                if not button.count():
                    button = dialog.locator(
                        'ytcp-button#close-button, button[aria-label="Close"], '
                        'button[aria-label="Fermer"]'
                    ).first
                if button.count() and button.is_visible() and button.is_enabled(timeout=500):
                    try:
                        button.click(timeout=1500)
                        print("[YOUTUBE] Confirmation finale : bouton Fermer cliqué.")
                    except PlaywrightError:
                        # The success message was already read. The modal can
                        # disappear itself while the Close action is dispatched.
                        pass
                print("[YOUTUBE] Confirmation finale de YouTube reçue.")
                return True
        return False

    def _complete_after_transfer(self, page, done_button, video_id, visibility):
        """Allow asynchronous Save/Publish/Close, without reopening Chrome."""
        if not self._wait_for_save_or_studio_confirmation(
            page, done_button, video_id, visibility
        ):
            return
        print("[YOUTUBE] Enregistrement de la vidéo…")
        try:
            done_button.click(timeout=15000)
        except PlaywrightError as exc:
            raise YouTubePostSaveUnconfirmed(
                f"Enregistrement non confirmé : https://youtu.be/{video_id}"
            ) from exc
        clicked = False
        deadline = time.monotonic() + 12
        print("[YOUTUBE] Attente courte de la confirmation finale…")
        while time.monotonic() < deadline:
            try:
                if page.is_closed():
                    break
                if self._close_published_confirmation(page, video_id):
                    return
                if not clicked:
                    try:
                        clicked = self._publish_anyway_if_prechecks_pending(page)
                    except YouTubeUploadError:
                        # The button may become enabled during this short window.
                        pass
                if self._close_published_confirmation(page, video_id):
                    return
                page.wait_for_timeout(500)
            except PlaywrightError:
                if page.is_closed():
                    break
                # Rerendering is normal; retry within the same short window.
                time.sleep(0.25)
        # No final popup: a single bounded check in the SAME tab is sufficient.
        # Do not navigate while a save/confirmation wizard is still visible.
        try:
            if not page.is_closed():
                active = page.locator(
                    "ytcp-uploads-dialog, ytcp-video-upload-dialog, "
                    "ytcp-prechecks-warning-dialog, ytcp-uploads-still-processing-dialog"
                )
                if not any(active.nth(n).is_visible() for n in range(active.count())):
                    if self._video_is_published_in_studio(
                        page.context, video_id, visibility, page=page
                    ):
                        return
        except PlaywrightError:
            pass
        raise YouTubePostSaveUnconfirmed(
            "Transfert terminé, publication non confirmée (brouillon possible). "
            f"Lien conservé : https://youtu.be/{video_id}. "
            "Vérifier ou publier la vidéo existante sans réimportation."
        )

    def upload(self, job):
        video_path = self.resolve_video_path(job)
        youtube_options = job.get("youtube") or {}
        title = str(youtube_options.get("title") or video_path.stem)[:100]
        description = str(youtube_options.get("description") or "")[:5000]
        visibility = str(
            youtube_options.get("visibility") or "unlisted"
        ).strip()
        file_size = video_path.stat().st_size
        content_sha256 = _sha256(video_path)
        cached_result = self._load_receipt(
            job,
            content_sha256=content_sha256,
            file_size=file_size,
        )
        if cached_result:
            return cached_result
        pending_receipt = self._load_pending_receipt(
            job, content_sha256=content_sha256, file_size=file_size
        )
        thumbnail_path = self.resolve_thumbnail_path(job)
        thumbnail_sha256 = (
            _sha256(thumbnail_path) if thumbnail_path is not None else ""
        )
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
                        "Le profil Chrome YouTube n’est pas connecté à la chaîne "
                        f"configurée ({self.channel_id})."
                    )

                if pending_receipt:
                    previous_id = self._video_id(pending_receipt["youtube_url"])
                    previous_visibility = pending_receipt.get("visibility", "unlisted")
                    if self._video_is_published_in_studio(
                        context, previous_id, previous_visibility
                    ):
                        recovered = {**pending_receipt, "status": "uploaded"}
                        self._save_receipt(job, recovered)
                        print(
                            "[YOUTUBE] Publication existante récupérée sans "
                            "réimportation : " + pending_receipt["youtube_url"]
                        )
                        return recovered
                    raise YouTubeUploadError(
                        "L’upload précédent possède déjà un identifiant YouTube "
                        f"({pending_receipt['youtube_url']}), mais sa publication "
                        "n’est pas confirmée dans Studio. Vérifiez ce lien avant "
                        "de lancer une nouvelle importation : aucun doublon créé."
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

                if thumbnail_path is not None:
                    self._upload_thumbnail(page, thumbnail_path)

                audience = self._first_visible(
                    page,
                    (
                        'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]',
                        '#audience tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]',
                    ),
                    timeout_ms=30000,
                )
                audience.click()
                selected_visibility = self._select_visibility(page, visibility)

                youtube_url = self._read_video_url(page, timeout_ms=90000)
                video_id = self._video_id(youtube_url)
                if not video_id:
                    raise YouTubeUploadError(
                        "L’adresse obtenue ne contient pas d’identifiant vidéo valide."
                    )
                print(f"[YOUTUBE] Lien attribué : {youtube_url}")

                # Save the assigned ID before waiting or clicking Save. If the
                # agent crashes, the next run can reconcile instead of reupload.
                self._save_receipt(
                    job,
                    {
                        "status": "link_assigned",
                        "youtube_url": youtube_url,
                        "youtube_video_id": video_id,
                        "youtube_channel_id": self.channel_id,
                        "content_sha256": content_sha256,
                        "file_size_bytes": file_size,
                        "visibility": selected_visibility,
                    },
                )
                print(
                    "[YOUTUBE] ID sauvegardé (anti-doublon). "
                    "La publication attend la fin du transfert."
                )
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
                self._complete_after_transfer(
                    page, done_button, video_id, selected_visibility
                )
                visibility_label = {
                    "public": "publique",
                    "unlisted": "non répertoriée",
                    "private": "privée",
                }[selected_visibility]
                print(
                    f"[YOUTUBE] Vidéo {visibility_label} confirmée : "
                    f"{youtube_url}"
                )
                result = {
                    "status": "uploaded",
                    "youtube_url": youtube_url,
                    "youtube_video_id": video_id,
                    "youtube_channel_id": self.channel_id,
                    "content_sha256": content_sha256,
                    "file_size_bytes": file_size,
                    "visibility": selected_visibility,
                    "thumbnail_path": (
                        str(thumbnail_path) if thumbnail_path is not None else ""
                    ),
                    "thumbnail_sha256": thumbnail_sha256,
                }
                self._save_receipt(job, result)
                return result
            finally:
                try:
                    context.close()
                except PlaywrightError as exc:
                    if type(exc).__name__ != "TargetClosedError" and not re.search(
                        r"(target page, context or browser has been closed|browser.*closed|context.*closed)",
                        str(exc), re.I,
                    ):
                        raise
                    print("[YOUTUBE] Chrome est déjà fermé.")
