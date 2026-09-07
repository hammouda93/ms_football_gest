"""Dailymotion Studio RPA: persistent Chrome profile, no Dailymotion API keys."""

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from .dailymotion_links import canonical_dailymotion_url, extract_dailymotion_video_id


DEFAULT_PROFILE_ID = "x6445ea"
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
UPLOAD_LABEL = re.compile(
    r"^(upload(?: a)? video(?:s)?|upload|mettre en ligne(?: une vid[eé]o)?|"
    r"importer(?: des vid[eé]os)?|envoyer une vid[eé]o)$", re.I
)
SAVE_LABEL = re.compile(
    r"^(save(?: all| changes| video)?|enregistrer(?: tout| les modifications| "
    r"la vid[eé]o)?|sauvegarder|publish|publier)$",
    re.I,
)
PRIVATE_LABEL = re.compile(r"^(private|priv[eé]e?)(?:\s*\(.*\))?$", re.I)
TITLE_LABEL = re.compile(r"^(title|titre)(?:\s*\*|\s*\(.*\))?$", re.I)
SHARE_LABEL = re.compile(
    r"^(share(?: video)?|partager(?: la vid[eé]o)?)$",
    re.I,
)
EMBED_LABEL = re.compile(
    r"^(embed(?: video)?|int[eé]grer(?: la vid[eé]o)?)$",
    re.I,
)
MORE_LABEL = re.compile(
    r"^(more actions|actions|more|plus d[’']actions|plus|open menu|"
    r"ouvrir le menu)$",
    re.I,
)


class DailymotionUploadError(RuntimeError):
    pass


class DailymotionAuthenticationRequired(DailymotionUploadError):
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


class DailymotionStudioUploader:
    def __init__(self, storage_root, profile_dir=None):
        self.storage_root = Path(storage_root)
        self.profile_id = (
            os.getenv("DAILYMOTION_STUDIO_PROFILE_ID") or DEFAULT_PROFILE_ID
        ).strip()
        if not re.fullmatch(r"[A-Za-z0-9]{4,64}", self.profile_id):
            raise DailymotionUploadError("DAILYMOTION_STUDIO_PROFILE_ID est invalide.")
        self.profile_dir = Path(
            profile_dir
            or os.getenv("DAILYMOTION_CHROME_PROFILE_DIR", "").strip()
            or os.getenv("SPORTSBASE_SUBSCRIPTION_PROFILE_DIR", "").strip()
            or os.getenv("SPORTSBASE_PROFILE_DIR", "").strip()
            or r"D:\SportsBase_Playwright_Profile"
        )
        self.browser_channel = os.getenv("DAILYMOTION_BROWSER_CHANNEL", "chrome").strip()
        self.headless = _env_bool("DAILYMOTION_HEADLESS", False)
        self.upload_timeout_ms = (
            int(os.getenv("DAILYMOTION_UPLOAD_TIMEOUT_MINUTES", "180"))
            * 60
            * 1000
        )
        self.navigation_timeout_ms = (
            int(os.getenv("DAILYMOTION_NAVIGATION_TIMEOUT_SECONDS", "90"))
            * 1000
        )
        self.language = os.getenv("DAILYMOTION_VIDEO_LANGUAGE", "fr").strip()
        self.content_url = (
            f"https://www.dailymotion.com/partner/{self.profile_id}/media/video"
        )
        self.receipt_dir = self.storage_root / "_dailymotion_receipts"

    def _receipt_path(self, job):
        job_id = re.sub(r"[^0-9A-Za-z_-]", "_", str(job.get("job_id") or "unknown"))
        return self.receipt_dir / f"upload_{job_id}.json"

    def _load_receipt(self, job, *, content_sha256, file_size):
        try:
            receipt = json.loads(self._receipt_path(job).read_text(encoding="utf-8"))
            if not isinstance(receipt, dict):
                return None
            size_matches = int(receipt.get("file_size_bytes") or 0) == file_size
        except (OSError, ValueError, TypeError):
            return None
        if receipt.get("content_sha256") != content_sha256 or not size_matches:
            return None
        if receipt.get("status") == "needs_review":
            raise DailymotionUploadError(
                "Un enregistrement Dailymotion a déjà été tenté pour ce fichier. "
                "Vérifiez la vidéo dans Studio avant de réessayer pour éviter un doublon. "
                f"Reçu local à vérifier : {self._receipt_path(job)}"
            )
        url = canonical_dailymotion_url(receipt.get("dailymotion_url"))
        if receipt.get("status") != "uploaded" or not url:
            return None
        receipt["dailymotion_url"] = url
        receipt["dailymotion_video_id"] = extract_dailymotion_video_id(url)
        print("[DAILYMOTION] Reçu local retrouvé : aucun nouvel upload nécessaire.")
        return receipt

    def _save_receipt(self, job, result):
        self.receipt_dir.mkdir(parents=True, exist_ok=True)
        destination = self._receipt_path(job)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(destination)

    def resolve_video_path(self, job):
        match = job.get("match") or {}
        folder = str(match.get("local_folder_key") or "").strip()
        filename = str(match.get("filename") or "").strip()
        if not folder or not filename:
            raise DailymotionUploadError("Le chemin local de la vidéo est incomplet.")
        if Path(filename).name != filename or "/" in filename or "\\" in filename:
            raise DailymotionUploadError("Le nom du fichier vidéo est invalide.")
        relative = PurePosixPath(folder.replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise DailymotionUploadError("Le dossier local de la vidéo est invalide.")
        root = self.storage_root.resolve()
        candidate = (root.joinpath(*relative.parts) / filename).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise DailymotionUploadError("Le fichier sort du stockage autorisé.") from exc
        if not candidate.is_file():
            raise DailymotionUploadError(f"Fichier All Actions introuvable : {candidate}")
        if (
            candidate.suffix.casefold() not in ALLOWED_VIDEO_EXTENSIONS
            or candidate.stat().st_size <= 0
        ):
            raise DailymotionUploadError(
                "Le fichier All Actions est vide ou son format est invalide."
            )
        return candidate

    @staticmethod
    def _chrome_executable():
        configured = os.getenv("DAILYMOTION_CHROME_EXECUTABLE", "").strip()
        candidates = [Path(configured)] if configured else []
        for environment_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = os.getenv(environment_name, "").strip()
            if root:
                candidates.append(
                    Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"
                )
        for command in ("chrome.exe", "chrome", "google-chrome", "google-chrome-stable"):
            discovered = shutil.which(command)
            if discovered:
                candidates.append(Path(discovered))
        return next((candidate for candidate in candidates if candidate.is_file()), None)

    def _open_manual_login(self):
        """Open regular Chrome so Google sign-in is not performed by Playwright."""
        executable = self._chrome_executable()
        if executable is None:
            raise DailymotionUploadError(
                "Google Chrome est introuvable. Définissez "
                "DAILYMOTION_CHROME_EXECUTABLE dans le .env."
            )
        print(
            "[DAILYMOTION] Connexion initiale dans Chrome normal — profil partagé : "
            f"{self.profile_dir}"
        )
        try:
            subprocess.Popen(
                [
                    str(executable),
                    f"--user-data-dir={self.profile_dir}",
                    "--new-window",
                    self.content_url,
                ]
            )
        except OSError as exc:
            raise DailymotionUploadError(
                f"Impossible d’ouvrir Google Chrome : {exc}"
            ) from exc
        input(
            "[DAILYMOTION] Connectez-vous, ouvrez Studio, fermez complètement "
            "Chrome puis appuyez sur Entrée : "
        )

    def _launch_context(self, playwright):
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        print(f"[DAILYMOTION] Ouverture Chrome — profil : {self.profile_dir}")
        try:
            return playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                channel=self.browser_channel or None,
                headless=self.headless,
                no_viewport=True,
                args=["--start-maximized"],
            )
        except Exception as exc:
            raise DailymotionUploadError(
                "Impossible d’ouvrir le profil Dailymotion. Fermez les autres "
                "fenêtres Chrome qui utilisent ce profil, puis réessayez."
            ) from exc

    @staticmethod
    def _visible(locator):
        try:
            count = min(locator.count(), 20)
        except Exception:
            return None
        for index in range(count):
            try:
                item = locator.nth(index)
                if item.is_visible():
                    return item
            except Exception:
                continue
        return None

    @staticmethod
    def _only_visible(locator):
        visible = []
        try:
            count = min(locator.count(), 20)
        except Exception:
            return None
        for index in range(count):
            try:
                item = locator.nth(index)
                if item.is_visible():
                    visible.append(item)
            except Exception:
                continue
        return visible[0] if len(visible) == 1 else None

    def _authentication_required(self, page):
        path = urlparse(page.url).path.casefold()
        return bool(
            re.search(r"/(signin|sign-in|login|sign_in)(?:/|$)", path)
            or self._visible(
                page.locator('input[type="password"], input[type="email"]')
            )
            or self._visible(
                page.get_by_role(
                    "button",
                    name=re.compile(r"^(log in|sign in|se connecter)$", re.I),
                )
            )
        )

    def _assert_studio(self, page):
        if self._authentication_required(page):
            raise DailymotionAuthenticationRequired(
                "Le profil Chrome Dailymotion n’est pas connecté. Lancez "
                "python -m sportsbase_data.local_agent --check-dailymotion."
            )
        parsed = urlparse(page.url)
        if (
            parsed.hostname not in {"dailymotion.com", "www.dailymotion.com"}
            or not parsed.path.startswith(f"/partner/{self.profile_id}/")
        ):
            raise DailymotionUploadError(
                "Le profil Dailymotion Studio attendu n’est pas accessible."
            )

    def _goto_studio(self, page):
        page.set_default_timeout(15000)
        page.goto(
            self.content_url,
            wait_until="domcontentloaded",
            timeout=self.navigation_timeout_ms,
        )
        page.wait_for_timeout(2500)

    def check_access(self):
        with sync_playwright() as playwright:
            context = None
            try:
                context = self._launch_context(playwright)
                page = context.pages[0] if context.pages else context.new_page()
                self._goto_studio(page)
                if self._authentication_required(page):
                    if self.headless:
                        raise DailymotionAuthenticationRequired(
                            "La première connexion nécessite DAILYMOTION_HEADLESS=false."
                        )
                    context.close()
                    context = None
                    self._open_manual_login()
                    context = self._launch_context(playwright)
                    page = context.pages[0] if context.pages else context.new_page()
                    self._goto_studio(page)
                self._assert_studio(page)
                self._wait_control(
                    page,
                    lambda: self._upload_button(page),
                    "bouton Upload video",
                    30000,
                )
                print(
                    f"[DAILYMOTION] Profil Chrome prêt : {self.profile_id}. "
                    "Aucune vidéo envoyée."
                )
                return True
            finally:
                if context is not None:
                    context.close()

    def _wait_control(self, page, find, label, timeout_ms=30000):
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            control = find()
            if control is not None:
                return control
            page.wait_for_timeout(500)
        raise DailymotionUploadError(
            f"Studio : élément « {label} » introuvable. Vérifiez l’interface."
        )

    def _upload_button(self, page):
        return self._visible(
            page.get_by_role("button", name=UPLOAD_LABEL)
        ) or self._visible(
            page.get_by_role("link", name=UPLOAD_LABEL)
        )

    def _open_upload_dialog(self, page):
        inputs = page.locator('input[type="file"]')
        if not inputs.count():
            button = self._wait_control(
                page,
                lambda: self._upload_button(page),
                "Upload video",
            )
            button.click()
        inputs.first.wait_for(state="attached", timeout=30000)
        for index in range(inputs.count()):
            field = inputs.nth(index)
            accept = (field.get_attribute("accept") or "").lower()
            if (
                not accept
                or "video" in accept
                or any(ext in accept for ext in ALLOWED_VIDEO_EXTENSIONS)
            ):
                return field
        raise DailymotionUploadError(
            "Le sélecteur de fichier vidéo Dailymotion est introuvable."
        )

    def _field(self, page, label, selectors):
        return self._visible(page.get_by_label(label)) or self._visible(
            page.locator(selectors)
        )

    def _title_field(self, page):
        return self._field(
            page,
            TITLE_LABEL,
            'input[name="title"], textarea[name="title"], input[id="title"]',
        )

    def _select_option(self, page, label, selectors, values, option_pattern):
        field = self._wait_control(
            page, lambda: self._field(page, label, selectors), label.pattern
        )
        if field.evaluate("node => node.tagName.toLowerCase()") == "select":
            for option in field.locator("option").all():
                value = option.get_attribute("value") or ""
                if value in values or option_pattern.fullmatch(
                    option.inner_text().strip()
                ):
                    field.select_option(value=value)
                    if field.input_value() == value:
                        return
        else:
            field.click()
            option = self._wait_control(
                page,
                lambda: self._visible(page.get_by_role("option", name=option_pattern))
                or self._visible(page.get_by_text(option_pattern)),
                option_pattern.pattern,
                10000,
            )
            option.click()
            page.wait_for_timeout(300)
            selected_text = field.inner_text().strip()
            try:
                input_text = field.input_value(timeout=500)
            except Exception:
                input_text = ""
            if any(
                option_pattern.fullmatch(text) or text in values
                for text in (selected_text, input_text)
            ):
                return
        raise DailymotionUploadError(
            f"La sélection « {label.pattern} » n’a pas été confirmée."
        )

    def _select_private(self, page):
        radio = self._visible(page.get_by_role("radio", name=PRIVATE_LABEL))
        if radio is not None:
            radio.check()
            if radio.is_checked():
                return
        self._select_option(
            page,
            re.compile(
                r"^(visibility|privacy|visibilit[eé]|confidentialit[eé])"
                r"(?:\s*\*)?$",
                re.I,
            ),
            'select[name="privacy"], select[name="visibility"], '
            '[role="combobox"][name="privacy"], '
            '[role="combobox"][name="visibility"]',
            {"private", "PRIVATE"},
            PRIVATE_LABEL,
        )

    def _select_not_for_kids(self, page):
        question = re.compile(
            r"(created|made|cr[eé][eé]|con[çc]u).*(kids|children|enfants)",
            re.I,
        )
        group = self._visible(
            page.get_by_role("radiogroup", name=question)
        ) or self._visible(
            page.locator("fieldset").filter(has_text=question)
        )
        radio = None
        if group is not None:
            radio = self._visible(
                group.get_by_role(
                    "radio",
                    name=re.compile(r"^(no|non)(?:\b.*)?$", re.I),
                )
            )
        if radio is None:
            radio = self._visible(
                page.get_by_role(
                    "radio",
                    name=re.compile(
                        r"^(no|non).*(kids|children|enfants)",
                        re.I,
                    ),
                )
            )
        if radio is not None:
            radio.check()
            if radio.is_checked():
                return
        self._select_option(
            page,
            question,
            'select[name="is_created_for_kids"], select[name="is_for_kids"]',
            {"false", "0"},
            re.compile(r"^(no|non)(?:\b.*)?$", re.I),
        )

    def _fill_details(self, page, title, description):
        title_field = self._wait_control(
            page,
            lambda: self._title_field(page),
            "Titre",
            60000,
        )
        title_field.fill(title)
        if description:
            box = self._wait_control(
                page,
                lambda: self._field(
                    page,
                    re.compile(r"^description", re.I),
                    'textarea[name="description"]',
                ),
                "Description",
            )
            box.fill(description)
        self._select_option(
            page,
            re.compile(r"^(category|cat[eé]gorie)(?:\s*\*)?$", re.I),
            'select[name="category"], [role="combobox"][name="category"]',
            {"sport", "sports"},
            re.compile(r"^sports?$", re.I),
        )
        languages = {
            "fr": r"fran[çc]ais|french",
            "en": r"english|anglais",
            "ar": r"arabic|arabe|العربية",
        }
        language_pattern = languages.get(self.language, re.escape(self.language))
        self._select_option(
            page,
            re.compile(r"^(language|langue)(?:\s*\*)?$", re.I),
            'select[name="language"], [role="combobox"][name="language"]',
            {self.language},
            re.compile(f"^(?:{language_pattern})$", re.I),
        )
        self._select_not_for_kids(page)
        self._select_private(page)
        print("[DAILYMOTION] Informations remplies — Sport, visibilité Privée.")

    @staticmethod
    def _transfer_complete(text, percentages=()):
        return bool(
            re.search(
                r"^(upload complete|uploaded|upload finished|optimizing|optimisation|"
                r"mise en ligne termin[eé]e|transfert termin[eé]|importation termin[eé]e)[.!]?$",
                text,
                re.I | re.M,
            )
            or any(value >= 100 for value in percentages)
        )

    def _raise_if_blocked(self, page):
        if self._authentication_required(page):
            raise DailymotionAuthenticationRequired(
                "La session Dailymotion a expiré. Relancez --check-dailymotion."
            )
        challenge = self._visible(
            page.locator(
                'iframe[src*="captcha"], iframe[title*="challenge" i]'
            )
        )
        if challenge is not None:
            raise DailymotionAuthenticationRequired(
                "Une validation manuelle est demandée dans Chrome. "
                "Relancez --check-dailymotion."
            )
        error_pattern = re.compile(
            r"(upload failed|unsupported format|reached your upload|upload limit|"
            r"blacklisted|content duration is too long|file size is too big|"
            r"échec de l[’'](?:upload|envoi|importation)|"
            r"format non (?:pris en charge|supporté)|limite d[’'](?:envoi|upload)|"
            r"liste noire|dur[eé]e du contenu est trop longue|fichier est trop volumineux|"
            r"blocked.*copyright|bloqu[eé].*droit d[’']auteur)",
            re.I,
        )
        error = self._visible(page.get_by_text(error_pattern))
        if error is not None:
            raise DailymotionUploadError(error.inner_text()[:500])

    def _upload_scope(self, page):
        title = self._title_field(page)
        if title is not None:
            dialog = self._visible(page.get_by_role("dialog").filter(has=title))
            if dialog is not None:
                return dialog
            form = self._visible(page.locator("form").filter(has=title))
            if form is not None:
                return form
        main = self._visible(page.get_by_role("main"))
        if main is not None:
            return main
        raise DailymotionUploadError(
            "Le panneau de progression Dailymotion n’est pas identifiable."
        )

    def _wait_upload_transfer_complete(self, page):
        deadline = time.monotonic() + self.upload_timeout_ms / 1000
        stable_complete = 0
        while time.monotonic() < deadline:
            self._raise_if_blocked(page)
            scope = self._upload_scope(page)
            percentages = []
            for bar in scope.get_by_role("progressbar").all():
                if bar.is_visible():
                    try:
                        percentages.append(
                            float(bar.get_attribute("aria-valuenow") or "0")
                        )
                    except ValueError:
                        pass
            text = scope.inner_text()
            stable_complete = (
                stable_complete + 1
                if self._transfer_complete(text, percentages)
                else 0
            )
            if stable_complete >= 2:
                print("[DAILYMOTION] Transfert terminé.")
                return
            page.wait_for_timeout(1000)
        raise DailymotionUploadError(
            "Dailymotion n’a pas confirmé la fin du transfert dans le délai prévu."
        )

    def _wait_save_button(self, page):
        def find():
            button = self._visible(page.get_by_role("button", name=SAVE_LABEL))
            if (
                button is not None
                and button.is_enabled()
                and button.get_attribute("aria-disabled") != "true"
            ):
                return button
            return None

        return self._wait_control(page, find, "Enregistrer activé", 60000)

    @staticmethod
    def _video_urls(page):
        # Read only visible UI links / share fields; never inspect private
        # application state or replay the site's internal HTTP requests.
        values = page.locator('a[href], input, textarea').evaluate_all("""nodes => nodes
            .filter(node => node.getClientRects().length)
            .map(node => node.tagName === 'A' ? node.href : node.value)
        """)
        urls = set()
        for value in values:
            candidates = re.findall(
                r'https?://[^\s<>"\']+',
                html.unescape(value or ""),
            )
            for candidate in candidates:
                url = canonical_dailymotion_url(candidate)
                if url:
                    urls.add(url)
        return urls

    def _wait_saved(self, page):
        confirmation = re.compile(
            r"^(?:video |vid[eé]o |changes |modifications )?(?:successfully |bien )?"
            r"(?:saved|published|enregistr[eé]e?s?|publi[eé]e?s?)"
            r"(?: successfully| avec succ[eè]s)?[.!]?$",
            re.I,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self._raise_if_blocked(page)
            if self._visible(page.get_by_text(confirmation)) is not None:
                return
            # Some Studio variants close the editor after Save. Only accept
            # this once it has returned to this profile's video library.
            if (
                page.url.split("?", 1)[0].rstrip("/") == self.content_url
                and self._title_field(page) is None
            ):
                if self._upload_button(page) is not None:
                    return
            page.wait_for_timeout(500)
        raise DailymotionUploadError(
            "Studio n’a pas confirmé l’enregistrement. Vérifiez la vidéo "
            "avant de réessayer."
        )

    def _uploaded_title_control(self, page, title):
        candidates = (
            page.get_by_role("link", name=title, exact=True),
            page.get_by_role("button", name=title, exact=True),
            page.get_by_text(title, exact=True),
        )
        for candidate in candidates:
            control = self._only_visible(candidate)
            if control is not None:
                return control
        return None

    def _uploaded_row(self, page, title):
        control = self._uploaded_title_control(page, title)
        if control is None:
            return None
        row = control.locator(
            "xpath=ancestor::*[self::tr or self::li or @role='row' "
            "or @role='listitem'][1]"
        )
        return self._only_visible(row)

    def _open_uploaded_title(self, page, title):
        """Open only the uniquely matching title created by this upload."""
        control = self._uploaded_title_control(page, title)
        if control is None:
            return False
        control.click()
        return True

    def _link_action(self, scope, roles):
        # Prefer the current Studio action documented for obtaining a usable
        # embed URL, then fall back to a visible sharing action.
        for pattern in (EMBED_LABEL, SHARE_LABEL):
            for role in roles:
                control = self._only_visible(
                    scope.get_by_role(role, name=pattern)
                )
                if control is not None:
                    return control
        return None

    def _reveal_share_panel(self, page, scope=None):
        """Expose a visible share/embed URL without reading internal app state."""
        action_scope = scope or page
        action = self._link_action(action_scope, ("button", "link"))
        if action is not None:
            action.click()
            return True

        more = self._only_visible(
            action_scope.get_by_role("button", name=MORE_LABEL)
        )
        if more is None:
            return False
        more.click()
        try:
            action = self._wait_control(
                page,
                lambda: self._link_action(page, ("menuitem", "button")),
                "Intégrer ou partager",
                5000,
            )
        except DailymotionUploadError:
            return False
        action.click()
        return True

    def _read_video_url(self, page, *, previous_urls, title):
        # Studio documents link/embed retrieval from Media > Videos. Return to
        # that library after Save so the exact uploaded row can be targeted.
        self._goto_studio(page)
        deadline = time.monotonic() + 60
        opened_title = False
        share_attempted = False
        while time.monotonic() < deadline:
            self._raise_if_blocked(page)
            urls = self._video_urls(page) - previous_urls
            # Keep the private share identifier provided by Studio. Never
            # synthesize a link from /partner/.../media/video/<id>.
            private_urls = {
                url
                for url in urls
                if extract_dailymotion_video_id(url).casefold().startswith("k")
            }
            if len(private_urls) == 1:
                return private_urls.pop()
            if len(urls) == 1:
                return urls.pop()
            if len(urls) > 1:
                raise DailymotionUploadError(
                    "Plusieurs liens vidéo détectés : impossible d’identifier "
                    "le match avec certitude."
                )

            # The editor can expose Share immediately after Save. If Studio
            # returned to the library, open only the exact uploaded title,
            # then reveal that video's Share panel.
            in_editor = self._title_field(page) is not None
            if not share_attempted and (in_editor or opened_title):
                share_attempted = self._reveal_share_panel(page)
                if share_attempted:
                    page.wait_for_timeout(500)
                    continue
            if not share_attempted and not in_editor and not opened_title:
                uploaded_row = self._uploaded_row(page, title)
                if uploaded_row is not None:
                    share_attempted = self._reveal_share_panel(
                        page,
                        scope=uploaded_row,
                    )
                    if share_attempted:
                        page.wait_for_timeout(500)
                        continue
            # On return to the library, open only the exact freshly uploaded
            # title. Do not select the first existing video in the account.
            if not opened_title and self._open_uploaded_title(page, title):
                opened_title = True
                share_attempted = False
                page.wait_for_timeout(1000)
            else:
                page.wait_for_timeout(500)
        raise DailymotionUploadError(
            "Le lien de partage Dailymotion n’a pas été trouvé dans Studio."
        )

    def upload(self, job):
        video_path = self.resolve_video_path(job)
        file_size = video_path.stat().st_size
        digest = _sha256(video_path)
        cached = self._load_receipt(job, content_sha256=digest, file_size=file_size)
        if cached:
            return cached
        options = job.get("dailymotion") or {}
        title = str(options.get("title") or video_path.stem).strip()[:255]
        description = str(options.get("description") or "").strip()[:3000]
        print(
            f"[DAILYMOTION] Préparation : {video_path.name} "
            f"({file_size / (1024 * 1024):.1f} Mo)"
        )
        with sync_playwright() as playwright:
            context = self._launch_context(playwright)
            page = None
            try:
                page = context.pages[0] if context.pages else context.new_page()
                self._goto_studio(page)
                self._assert_studio(page)
                previous_urls = self._video_urls(page)
                file_input = self._open_upload_dialog(page)
                file_input.set_input_files(str(video_path))
                print("[DAILYMOTION] Fichier transmis à Studio.")
                self._fill_details(page, title, description)
                self._wait_upload_transfer_complete(page)
                button = self._wait_save_button(page)
                # If the browser dies after Save, block an uncertain duplicate
                # on the next retry. A confirmed receipt replaces this marker.
                self._save_receipt(
                    job,
                    {
                        "status": "needs_review",
                        "studio_url": page.url,
                        "content_sha256": digest,
                        "file_size_bytes": file_size,
                    },
                )
                button.click()
                self._wait_saved(page)
                url = self._read_video_url(page, previous_urls=previous_urls, title=title)
                result = {
                    "status": "uploaded",
                    "dailymotion_url": url,
                    "dailymotion_video_id": extract_dailymotion_video_id(url),
                    "content_sha256": digest,
                    "file_size_bytes": file_size,
                }
                self._save_receipt(job, result)
                print(f"[DAILYMOTION] Vidéo privée enregistrée : {url}")
                return result
            except DailymotionAuthenticationRequired:
                raise
            except Exception as exc:
                try:
                    diagnostic_dir = self.storage_root / "_dailymotion_diagnostics"
                    diagnostic_dir.mkdir(parents=True, exist_ok=True)
                    screenshot = diagnostic_dir / f"{self._receipt_path(job).stem}.png"
                    page.screenshot(path=str(screenshot), full_page=True, timeout=10000)
                    print(f"[DAILYMOTION] Capture de diagnostic locale : {screenshot}")
                except Exception:
                    pass
                if isinstance(exc, DailymotionUploadError):
                    raise
                raise DailymotionUploadError(
                    f"RPA Dailymotion interrompu : {exc}"
                ) from exc
            finally:
                context.close()
