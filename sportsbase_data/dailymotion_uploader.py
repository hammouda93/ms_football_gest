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
DAILYMOTION_RPA_BUILD = "dailymotion-studio-unlimited-preview-wait-v7-20260908"
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
UPLOAD_LABEL = re.compile(
    r"^(upload(?: a)? vid[eé]o(?:s)?|upload|mettre en ligne(?: une vid[eé]o)?|"
    r"importer(?: des vid[eé]os)?|envoyer une vid[eé]o)$", re.I
)
CREATE_CONTENT_LABEL = re.compile(
    r"^(create (?:your )?content|cr[eé]er (?:votre )?contenu|nouveau contenu)$",
    re.I,
)
NEXT_LABEL = re.compile(r"^(next|suivant)$", re.I)
AUDIENCE_HEADING = re.compile(r"^(audience|public(?: cible)?)$", re.I)
VISIBILITY_HEADING = re.compile(
    r"^(visibility|privacy|visibilit[eé]|confidentialit[eé])$",
    re.I,
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
CLOSE_LABEL = re.compile(r"^(close|fermer)$", re.I)
PREVIEW_LABEL = re.compile(r"^(preview|aper[çc]u)$", re.I)


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
        self.link_wait_seconds = max(
            0,
            int(os.getenv("DAILYMOTION_LINK_WAIT_SECONDS", "0")),
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
        if receipt.get("status") == "link_pending":
            receipt["dailymotion_url"] = ""
            receipt["dailymotion_video_id"] = ""
            print(
                "[DAILYMOTION] Transfert déjà terminé : ajoutez le lien "
                "Aperçu dans la gestion interne."
            )
            return receipt
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
                    lambda: self._create_content_button(page)
                    or self._upload_button(page),
                    "bouton Créer votre contenu",
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

    def _create_content_button(self, page):
        return self._visible(
            page.get_by_role("button", name=CREATE_CONTENT_LABEL)
        ) or self._visible(
            page.locator(
                'button[class*="createContentMenuButton"], '
                'button:has(svg[aria-label="Créer votre contenu"]), '
                'button:has(svg[aria-label="Create your content"])'
            )
        )

    @staticmethod
    def _video_file_input(page):
        inputs = page.locator('input[type="file"]')
        try:
            count = inputs.count()
        except Exception:
            return None
        for index in range(count):
            field = inputs.nth(index)
            try:
                accept = (field.get_attribute("accept") or "").casefold()
            except Exception:
                continue
            if "video" in accept or any(
                extension in accept for extension in ALLOWED_VIDEO_EXTENSIONS
            ):
                return field
        return None

    def _open_upload_dialog(self, page):
        field = self._video_file_input(page)
        if field is None:
            create_content = self._create_content_button(page)
            if create_content is not None:
                create_content.click()
                upload_action = self._wait_control(
                    page,
                    lambda: self._upload_button(page),
                    "Upload vidéo",
                    10000,
                )
                upload_action.click()
                print(
                    "[DAILYMOTION] Créer votre contenu → Upload vidéo."
                )
            else:
                # Compatibility with the previous Studio layout where Upload
                # was directly available in the page header.
                upload_action = self._wait_control(
                    page,
                    lambda: self._upload_button(page),
                    "Upload vidéo",
                )
                upload_action.click()
            field = self._wait_control(
                page,
                lambda: self._video_file_input(page),
                "sélecteur de fichier vidéo",
                30000,
            )
        return field

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

    @staticmethod
    def _selected_option_texts(field):
        texts = []

        def remember(value):
            if isinstance(value, str) and value.strip():
                texts.append(value.strip())

        try:
            remember(field.inner_text())
        except Exception:
            pass
        try:
            remember(field.input_value(timeout=500))
        except Exception:
            pass
        try:
            container = field.locator(
                "xpath=ancestor-or-self::*[contains(concat(' ', "
                "normalize-space(@class), ' '), ' ant-select ')][1]"
            )
            if container.count():
                remember(container.inner_text())
                selections = container.locator(
                    ".ant-select-selection-item, [class*='selection-item']"
                )
                for item in selections.all():
                    remember(item.inner_text())
                    remember(item.get_attribute("title"))
        except Exception:
            pass
        return texts

    @classmethod
    def _selection_confirmed(cls, field, values, option_pattern):
        normalized_values = {str(value).casefold() for value in values}
        return any(
            option_pattern.fullmatch(text)
            or text.casefold() in normalized_values
            for text in cls._selected_option_texts(field)
        )

    def _select_click_target(self, field):
        # Ant Design makes the combobox input transparent/read-only. Clicking
        # that input is intercepted by .ant-select-selection-item; the visible
        # selector container is the actual control that opens the option list.
        selector = self._visible(
            field.locator(
                "xpath=ancestor-or-self::*[contains(concat(' ', "
                "normalize-space(@class), ' '), ' ant-select-selector ')][1]"
            )
        )
        if selector is not None:
            return selector

        ant_select = self._visible(
            field.locator(
                "xpath=ancestor-or-self::*[contains(concat(' ', "
                "normalize-space(@class), ' '), ' ant-select ')][1]"
            )
        )
        if ant_select is not None:
            selector = self._visible(ant_select.locator(".ant-select-selector"))
            if selector is not None:
                return selector
        return field

    def _visible_select_option(self, page, option_pattern):
        dropdown = self._visible(page.locator(".ant-select-dropdown"))
        scopes = [dropdown] if dropdown is not None else []
        scopes.append(page)
        for scope in scopes:
            option = self._visible(
                scope.get_by_role("option", name=option_pattern)
            ) or self._visible(
                scope.locator(".ant-select-item-option").filter(
                    has_text=option_pattern
                )
            )
            if option is not None:
                return option
        return None

    @staticmethod
    def _active_option_matches(page, field, option_pattern):
        try:
            active_id = field.get_attribute("aria-activedescendant") or ""
        except Exception:
            return False
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,127}", active_id):
            return False
        active = page.locator(f'[id="{active_id}"]')
        try:
            if not active.count():
                return False
            active = active.first
        except Exception:
            return False
        values = []
        for getter in (
            active.inner_text,
            active.text_content,
            lambda: active.get_attribute("aria-label"),
            lambda: active.get_attribute("title"),
        ):
            try:
                value = getter()
            except Exception:
                continue
            if isinstance(value, str) and value.strip():
                values.append(" ".join(value.split()))
        return any(option_pattern.fullmatch(value) for value in values)

    def _select_ant_option(self, page, field, option_pattern):
        # Dailymotion virtualizes the category list. The requested item may
        # therefore be absent from the visible DOM until keyboard navigation
        # moves aria-activedescendant to it.
        for _index in range(80):
            option = self._visible_select_option(page, option_pattern)
            if option is not None:
                option.click()
                return
            if self._active_option_matches(page, field, option_pattern):
                field.press("Enter")
                return
            field.press("ArrowDown")
            page.wait_for_timeout(100)
        raise DailymotionUploadError(
            f"L’option « {option_pattern.pattern} » est introuvable dans la liste."
        )

    def _select_option(self, page, label, selectors, values, option_pattern):
        field = self._wait_control(
            page, lambda: self._field(page, label, selectors), label.pattern
        )
        if self._selection_confirmed(field, values, option_pattern):
            return
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
            self._select_click_target(field).click()
            self._select_ant_option(page, field, option_pattern)
            page.wait_for_timeout(300)
            if self._selection_confirmed(field, values, option_pattern):
                return
        raise DailymotionUploadError(
            f"La sélection « {label.pattern} » n’a pas été confirmée."
        )

    def _select_private(self, page):
        radio = self._visible(
            page.get_by_role("radio", name=PRIVATE_LABEL)
        ) or self._visible(
            page.locator('input[type="radio"][name="visibility"][value="private"]')
        )
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
            ) or self._visible(
                page.locator(
                    'input[type="radio"][name="is_created_for_kids"][value="false"]'
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
            'select[name="category"], [role="combobox"][name="category"], '
            '[name="channel"] [role="combobox"], [role="combobox"][id="channel"]',
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
            'select[name="language"], [role="combobox"][name="language"], '
            '[name="language"] [role="combobox"], '
            '[role="combobox"][id="language"]',
            {self.language},
            re.compile(f"^(?:{language_pattern})$", re.I),
        )
        print("[DAILYMOTION] Informations remplies — catégorie Sport, langue validée.")

    def _next_button(self, page):
        button = self._visible(page.get_by_role("button", name=NEXT_LABEL))
        if (
            button is not None
            and button.is_enabled()
            and button.get_attribute("aria-disabled") != "true"
        ):
            return button
        return None

    def _wizard_stage(self, page):
        if self._visible(
            page.get_by_role("heading", name=AUDIENCE_HEADING)
        ) is not None:
            return "audience"
        if self._visible(
            page.get_by_role("heading", name=VISIBILITY_HEADING)
        ) is not None:
            return "visibility"
        return None

    def _advance_upload_wizard(self, page):
        first_next = self._wait_control(
            page,
            lambda: self._next_button(page),
            "Suivant",
            60000,
        )
        first_next.click()
        stage = self._wait_control(
            page,
            lambda: self._wizard_stage(page),
            "étape Audience ou Visibilité",
            60000,
        )
        if stage == "audience":
            self._select_not_for_kids(page)
            print("[DAILYMOTION] Audience — Non créé pour les enfants.")
            second_next = self._wait_control(
                page,
                lambda: self._next_button(page),
                "Suivant après Audience",
                60000,
            )
            second_next.click()
            self._wait_control(
                page,
                lambda: (
                    "visibility"
                    if self._wizard_stage(page) == "visibility"
                    else None
                ),
                "étape Visibilité",
                60000,
            )
        self._select_private(page)
        print("[DAILYMOTION] Visibilité — Privée.")

    @staticmethod
    def _transfer_complete(text, percentages=()):
        active_upload_percentages = []
        for raw in re.findall(
            r"(?:upload|transfert|importation)\s+"
            r"(?:en cours|in progress)\s*[:\-]?\s*"
            r"(\d{1,3}(?:[.,]\d+)?)\s*%",
            text or "",
            re.I,
        ):
            try:
                active_upload_percentages.append(float(raw.replace(",", ".")))
            except ValueError:
                continue
        # An enabled "Fermer" button and other 100% indicators can already be
        # present while the actual video transfer is still running. The exact
        # upload status therefore has priority over every completion signal.
        if any(value < 100 for value in active_upload_percentages):
            return False
        return bool(
            re.search(
                r"^(upload complete|uploaded|upload finished|upload termin[eé]e?|"
                r"upload r[eé]ussi|optimizing(?:\s+\d+(?:[.,]\d+)?\s*%)?|"
                r"optimisation(?: en cours)?(?:\s+\d+(?:[.,]\d+)?\s*%)?|"
                r"processing(?:\s+\d+(?:[.,]\d+)?\s*%)?|"
                r"traitement en cours(?:\s+\d+(?:[.,]\d+)?\s*%)?|"
                r"encodage en cours(?:\s+\d+(?:[.,]\d+)?\s*%)?|"
                r"mise en ligne termin[eé]e|"
                r"transfert termin[eé]|importation termin[eé]e)[.!]?$",
                text,
                re.I | re.M,
            )
            or any(value >= 100 for value in percentages)
        )

    @staticmethod
    def _text_percentages(text):
        percentages = []
        for raw in re.findall(r"(?<!\d)(\d{1,3}(?:[.,]\d+)?)\s*%", text or ""):
            try:
                value = float(raw.replace(",", "."))
            except ValueError:
                continue
            if 0 <= value <= 100:
                percentages.append(value)
        return percentages

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

    def _upload_summary_scope(self, page, title=""):
        summaries = page.locator('[class*="itemSummaryContainer"]')
        if title:
            summaries = summaries.filter(has_text=title)
        return self._visible(summaries)

    def _upload_scope(self, page, title=""):
        summary = self._upload_summary_scope(page, title)
        if summary is not None:
            return summary
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
        body = self._visible(page.locator("body"))
        if body is not None:
            return body
        raise DailymotionUploadError(
            "Le panneau de progression Dailymotion n’est pas identifiable."
        )

    def _close_button(self, page):
        button = self._visible(page.get_by_role("button", name=CLOSE_LABEL))
        if (
            button is not None
            and button.is_enabled()
            and button.get_attribute("aria-disabled") != "true"
        ):
            return button
        return None

    def _wait_upload_transfer_complete(self, page, title=""):
        deadline = time.monotonic() + self.upload_timeout_ms / 1000
        stable_complete = 0
        last_progress = None
        while time.monotonic() < deadline:
            self._raise_if_blocked(page)
            scope = self._upload_scope(page, title)
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
            percentages.extend(self._text_percentages(text))
            if percentages:
                progress = max(percentages)
                if progress != last_progress and progress < 100:
                    print(f"[DAILYMOTION] Upload en cours : {progress:g} %")
                    last_progress = progress
            # Studio exposes an enabled "Fermer" button before the file has
            # finished uploading. Only progress/status evidence may complete
            # this wait; the button is used afterwards, never as confirmation.
            complete = self._transfer_complete(text, percentages)
            stable_complete = stable_complete + 1 if complete else 0
            if stable_complete >= 2:
                print("[DAILYMOTION] Transfert terminé.")
                return
            page.wait_for_timeout(1000)
        raise DailymotionUploadError(
            "Dailymotion n’a pas confirmé la fin du transfert dans le délai prévu."
        )

    def _close_upload_dialog(self, page, title):
        button = self._wait_control(
            page,
            lambda: self._close_button(page),
            "Fermer après le transfert",
            60000,
        )
        button.click()
        self._wait_control(
            page,
            lambda: self._uploaded_title_control(page, title),
            f"vidéo publiée « {title} »",
            60000,
        )
        print("[DAILYMOTION] Fenêtre d’upload fermée — vidéo retrouvée dans Médias.")

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

    def _wait_saved(self, page, title=""):
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
            summary = self._upload_summary_scope(page, title)
            if summary is not None and re.search(
                r"upload\s+(?:en cours|in progress|termin[eé]|complete|finished)|"
                r"traitement en cours|processing",
                summary.inner_text(),
                re.I,
            ):
                print(
                    "[DAILYMOTION] Sauvegarde confirmée — suivi de l’upload."
                )
                return
            # Some Studio variants close the editor after Save. Only accept
            # this once it has returned to this profile's video library.
            if (
                page.url.split("?", 1)[0].rstrip("/") == self.content_url
                and self._title_field(page) is None
            ):
                if (
                    self._create_content_button(page) is not None
                    or self._upload_button(page) is not None
                ):
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

    def _row_actions_button(self, row):
        return self._visible(
            row.locator(
                "button.ant-dropdown-trigger, "
                "[class*='dropdownActions'] button, "
                "button[class*='toolbar']"
            )
        )

    def _preview_url(self, page):
        candidates = (
            page.get_by_role("link", name=PREVIEW_LABEL),
            page.locator(
                'a[title="Aperçu"], a[title="Apercu"], a[title="Preview"]'
            ),
        )
        for candidate in candidates:
            link = self._only_visible(candidate)
            if link is None:
                continue
            url = canonical_dailymotion_url(link.get_attribute("href"))
            if url:
                return url
        return ""

    def _row_processing_progress(self, row):
        try:
            text = row.inner_text()
        except Exception:
            return None
        if not re.search(r"optimis|process|traitement|encodage", text, re.I):
            return None
        percentages = self._text_percentages(text)
        return max(percentages) if percentages else 0.0

    def _row_ready_for_preview(self, row):
        return self._visible(
            row.locator(
                'svg[aria-label="Monétisée"], svg[aria-label="Monetized"], '
                'svg[aria-label="Monétisé"], svg[aria-label="Monetised"]'
            )
        ) is not None

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

    def _read_video_url(self, page, *, previous_urls=None, title):
        # The private k... identifier is exposed by the visible "Aperçu" link
        # in the exact uploaded row's ellipsis menu. Never derive it from the
        # public x... Studio details identifier.
        deadline = (
            time.monotonic() + self.link_wait_seconds
            if self.link_wait_seconds
            else None
        )
        last_progress = None
        next_menu_attempt = 0.0
        ready_logged = False
        first_pass = True
        if deadline is None:
            print(
                "[DAILYMOTION] Recherche du lien Aperçu "
                "(appuyer sur une touche pour quitter)."
            )
        else:
            print(
                "[DAILYMOTION] Recherche du lien Aperçu "
                f"({self.link_wait_seconds} s maximum; appuyer sur une touche "
                "pour quitter)."
            )
        while first_pass or deadline is None or time.monotonic() < deadline:
            first_pass = False
            if self._keyboard_exit_requested():
                raise DailymotionUploadError(
                    "Attente interrompue par l’utilisateur; le transfert est "
                    "conservé et le lien peut être ajouté manuellement."
                )
            self._raise_if_blocked(page)
            row = self._uploaded_row(page, title)
            if row is not None:
                progress = self._row_processing_progress(row)
                if progress is not None and progress != last_progress:
                    print(f"[DAILYMOTION] Optimisation en cours : {progress:g} %")
                    last_progress = progress

                url = self._preview_url(page)
                if url:
                    return url

                ready = self._row_ready_for_preview(row)
                if ready and not ready_logged:
                    print("[DAILYMOTION] Vidéo optimisée — lien Aperçu disponible.")
                    ready_logged = True

                now = time.monotonic()
                if ready or now >= next_menu_attempt:
                    # Refresh the exact row's menu periodically: Studio may add
                    # the Preview action only after optimization finishes.
                    open_menu = self._visible(
                        page.locator("ul.ant-dropdown-menu[role='menu']")
                    )
                    if open_menu is not None:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(100)
                    actions = self._row_actions_button(row)
                    if actions is not None:
                        actions.click()
                        page.wait_for_timeout(300)
                        url = self._preview_url(page)
                        if url:
                            return url
                    next_menu_attempt = now + 10
            page.wait_for_timeout(1000)
        raise DailymotionUploadError(
            "L’optimisation continue et le lien Aperçu n’est pas encore disponible."
        )

    @staticmethod
    def _keyboard_exit_requested():
        """Consume one console key on Windows without blocking Playwright."""
        if os.name != "nt":
            return False
        try:
            import msvcrt

            if not msvcrt.kbhit():
                return False
            key = msvcrt.getwch()
            # Extended keys emit a two-character sequence. Consume the second
            # character so it cannot stop a later Dailymotion job unexpectedly.
            if key in {"\x00", "\xe0"} and msvcrt.kbhit():
                msvcrt.getwch()
            return True
        except (ImportError, OSError):
            return False

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
        print(f"[DAILYMOTION] Version RPA : {DAILYMOTION_RPA_BUILD}")
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
                self._advance_upload_wizard(page)
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
                self._wait_saved(page, title)
                self._wait_upload_transfer_complete(page, title)
                link_pending_result = {
                    "status": "link_pending",
                    "dailymotion_url": "",
                    "dailymotion_video_id": "",
                    "studio_url": page.url,
                    "content_sha256": digest,
                    "file_size_bytes": file_size,
                }
                # From this point the file is safely on Dailymotion. Persist
                # that fact before waiting for the slower optimization/link.
                self._save_receipt(job, link_pending_result)
                try:
                    self._close_upload_dialog(page, title)
                    url = self._read_video_url(
                        page,
                        previous_urls=previous_urls,
                        title=title,
                    )
                except Exception as link_error:
                    print(
                        "[DAILYMOTION] Upload réussi — lien Aperçu à ajouter "
                        "dans la gestion interne."
                    )
                    print(f"[DAILYMOTION] Détail : {link_error}")
                    return link_pending_result
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
                try:
                    context.close()
                except Exception:
                    pass
