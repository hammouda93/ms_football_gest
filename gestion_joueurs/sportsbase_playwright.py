import json
import os
import re
import socket
import subprocess
import time
from http.client import HTTPConnection
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

PLAYER_ACTIONS_BUTTON_RE = re.compile(
    r"^(?:Player\s+actions?|All\s+(?:players?\s+)?actions?)$",
    re.IGNORECASE,
)


class SportsBaseAutomation:
    def __init__(self, base_download_dir: Optional[str] = None, progress_callback=None):
        self.login_url = os.getenv("SPORTSBASE_LOGIN_URL", "").strip()
        self.email = os.getenv("SPORTSBASE_EMAIL", "").strip()
        self.password = os.getenv("SPORTSBASE_PASSWORD", "").strip()
        self.headless = os.getenv("SPORTSBASE_HEADLESS", "false").lower() == "true"
        self.base_download_dir = base_download_dir or os.getenv(
            "SPORTSBASE_DOWNLOAD_DIR",
            "D:/Django_Projects/ms_football_gest/gestion_joueurs/automated_players"
        )
        self.profile_dir = Path(
            os.getenv(
                "SPORTSBASE_PROFILE_DIR",
                r"D:\SportsBase_Playwright_Profile",
            )
        )
        self.progress_callback = progress_callback
        self._cdp_browser = None
        self._cdp_process = None

        if not self.login_url:
            raise ValueError("SPORTSBASE_LOGIN_URL manquant dans .env")
        if not self.email or not self.password:
            raise ValueError("SPORTSBASE_EMAIL ou SPORTSBASE_PASSWORD manquant dans .env")

    def notify_progress(self, stage, current=0, total=0, message=""):
        if not self.progress_callback:
            return
        try:
            self.progress_callback(
                stage=stage,
                current=current,
                total=total,
                message=message,
            )
        except Exception as exc:
            print(f"[WARN] Mise à jour progression impossible: {exc}")

    @staticmethod
    def sanitize_filename(value: str) -> str:
        value = re.sub(r'[<>:"/\\|?*]+', "_", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value

    @staticmethod
    def resolve_browser_executable(playwright) -> str:
        """Reuse an installed browser when Playwright's bundled Chromium is absent."""
        program_files = os.getenv("ProgramFiles", "")
        program_files_x86 = os.getenv("ProgramFiles(x86)", "")
        local_app_data = os.getenv("LOCALAPPDATA", "")
        candidates = [
            os.getenv("SPORTSBASE_BROWSER_EXECUTABLE", "").strip(),
            getattr(playwright.chromium, "executable_path", ""),
            os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe")
            if program_files else "",
            os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe")
            if program_files_x86 else "",
            os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe")
            if local_app_data else "",
            os.path.join(program_files_x86, "Microsoft", "Edge", "Application", "msedge.exe")
            if program_files_x86 else "",
            os.path.join(program_files, "Microsoft", "Edge", "Application", "msedge.exe")
            if program_files else "",
        ]
        for candidate in dict.fromkeys(candidates):
            if candidate and Path(candidate).is_file():
                return str(Path(candidate))
        return ""

    @staticmethod
    def reserve_cdp_port() -> int:
        configured = os.getenv("SPORTSBASE_CDP_PORT", "").strip()
        if configured:
            return int(configured)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    @staticmethod
    def wait_for_cdp_endpoint(process, port: int, timeout_seconds: int = 30) -> str:
        deadline = time.monotonic() + timeout_seconds
        last_error = ""
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    "Chrome s'est arrêté avant la connexion. Fermez toute autre "
                    "fenêtre utilisant le profil SportsBase puis réessayez."
                )
            connection = None
            try:
                connection = HTTPConnection("127.0.0.1", port, timeout=1)
                connection.request("GET", "/json/version")
                response = connection.getresponse()
                payload = response.read()
                if response.status == 200:
                    metadata = json.loads(payload.decode("utf-8"))
                    if metadata.get("webSocketDebuggerUrl"):
                        return f"http://127.0.0.1:{port}"
            except Exception as exc:
                last_error = str(exc)
            finally:
                if connection is not None:
                    connection.close()
            time.sleep(0.2)
        raise RuntimeError(
            f"Chrome n'a pas ouvert son port local dans les délais. {last_error}".strip()
        )

    def launch_profile_context(self, playwright, browser_executable: str):
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        port = self.reserve_cdp_port()
        command = [
            browser_executable,
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={self.profile_dir.resolve()}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-mode",
            "--start-maximized",
            "about:blank",
        ]
        if self.headless:
            command.insert(-1, "--headless=new")
        print(f"[DEBUG] Profil Chrome SportsBase: {self.profile_dir}")
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._cdp_process = process
        try:
            endpoint = self.wait_for_cdp_endpoint(process, port)
            browser = playwright.chromium.connect_over_cdp(
                endpoint,
                timeout=30_000,
                is_local=True,
                no_defaults=False,
            )
            if not browser.contexts:
                raise RuntimeError("Chrome n'a exposé aucun profil navigateur.")
            self._cdp_browser = browser
            return browser.contexts[0]
        except Exception:
            self.close_profile_browser()
            raise

    def close_profile_browser(self):
        browser = self._cdp_browser
        process = self._cdp_process
        self._cdp_browser = None
        self._cdp_process = None
        if browser is not None:
            try:
                session = browser.new_browser_cdp_session()
                session.send("Browser.close")
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
        if process is None:
            return
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    def run_for_player(self, player_name: str, player_url: str, target_dir: str, seasons_to_process: int = 1) -> dict:
        target_path = Path(target_dir)
        raw_clips_dir = target_path / "raw_clips"
        raw_clips_dir.mkdir(parents=True, exist_ok=True)

        result = {
            "player_name": player_name,
            "sportsbase_player_name": None,
            "player_url": player_url,
            "matches_played": 0,
            "generation_requests_sent": 0,
            "downloaded_files": [],
            "generated_match_titles": [],
        }

        with sync_playwright() as p:
            browser_executable = self.resolve_browser_executable(p)
            if not browser_executable:
                raise RuntimeError(
                    "Aucun navigateur compatible trouvé. Installez Chrome/Edge ou "
                    "définissez SPORTSBASE_BROWSER_EXECUTABLE."
                )
            print(f"[DEBUG] Navigateur SportsBase: {browser_executable}")
            context = self.launch_profile_context(p, browser_executable)

            page = context.new_page()

            try:
                self.notify_progress(
                    "sportsbase_discovery",
                    message="Connexion au profil SportsBase",
                )
                self.ensure_logged_in_and_open_player(page, player_url)

                sportsbase_player_name = self.get_sportsbase_player_name(page)
                result["sportsbase_player_name"] = sportsbase_player_name or player_name

                existing_video_keys = self.snapshot_existing_video_keys(
                    page,
                    sportsbase_player_name or player_name,
                )
                result["excluded_existing_video_count"] = sum(existing_video_keys.values())

                self.open_player_statistics(page)

                matches_played = self.get_matches_played(page, seasons_to_process=seasons_to_process) 
                result["matches_played"] = matches_played
                print(f"[DEBUG] Matches played lus: {matches_played}")
                self.notify_progress(
                    "sportsbase_generation",
                    current=0,
                    total=matches_played,
                    message=f"{matches_played} matchs trouvés",
                )

                generation_requests_sent, generated_match_titles = self.generate_all_players_actions(page, matches_played)
                result["generation_requests_sent"] = generation_requests_sent
                result["generated_match_titles"] = generated_match_titles
                self.notify_progress(
                    "sportsbase_download",
                    current=0,
                    total=generation_requests_sent,
                    message=f"{generation_requests_sent} générations confirmées",
                )

                downloaded = self.download_ready_videos(
                    page,
                    sportsbase_player_name or player_name,
                    raw_clips_dir,
                    generated_match_titles=generated_match_titles,
                    max_downloads=generation_requests_sent,
                    excluded_row_keys=existing_video_keys,
                )
                result["downloaded_files"] = downloaded

            finally:
                self.close_profile_browser()

        return result

    def ensure_logged_in_and_open_player(self, page, player_url: str):
        print(f"[DEBUG] Ouverture directe page joueur: {player_url}")
        page.goto(player_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        # laisser le temps à la redirection auth éventuelle
        page.wait_for_timeout(2000)

        print(f"[DEBUG] URL après premier accès joueur: {page.url}")
        print(f"[DEBUG] Titre après premier accès joueur: {page.title()}")

        def is_login_page():
            try:
                email_count = page.locator('input[placeholder="E-mail"], input[type="email"]').count()
                password_count = page.locator('input[placeholder="Password"], input[type="password"]').count()
                return email_count > 0 and password_count > 0
            except Exception:
                return False

        # si redirect login -> login
        if is_login_page() or "auth.sportsbase.world" in page.url:
            print("[DEBUG] Page login détectée, connexion en cours...")

            email_input = page.locator('input[placeholder="E-mail"], input[type="email"]').first
            password_input = page.locator('input[placeholder="Password"], input[type="password"]').first

            email_input.wait_for(timeout=15000)
            password_input.wait_for(timeout=15000)

            email_input.fill(self.email)
            password_input.fill(self.password)

            sign_in_button = page.get_by_role("button", name="Sign in").first
            sign_in_button.wait_for(timeout=10000)
            sign_in_button.click()

            page.wait_for_load_state("domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            page.wait_for_timeout(4000)

        print(f"[DEBUG] URL après éventuel login: {page.url}")
        print(f"[DEBUG] Titre après éventuel login: {page.title()}")

        # si on n'est pas revenu sur la page joueur, on y retourne
        if player_url not in page.url:
            print(f"[DEBUG] Retour manuel vers la page joueur: {player_url}")
            page.goto(player_url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

        print(f"[DEBUG] URL finale joueur: {page.url}")
        print(f"[DEBUG] Titre final joueur: {page.title()}")

        # sécurité finale
        if "auth.sportsbase.world" in page.url:
            raise RuntimeError("Toujours bloqué sur la page login SportsBase après tentative de connexion.")

    def get_sportsbase_player_name(self, page):
        try:
            title_locator = page.locator("span.ProfileTitle-sc-kzljqc-4").first
            title_locator.wait_for(timeout=10000)
            sportsbase_name = title_locator.inner_text().strip()
            print(f"[DEBUG] Nom joueur SportsBase: {sportsbase_name}")
            return sportsbase_name
        except Exception as e:
            print(f"[WARN] Impossible de lire le nom joueur SportsBase: {e}")
            return None

    def open_player_statistics(self, page):
        print(f"[DEBUG] URL actuelle avant Statistics: {page.url}")

        statistics_tab = page.locator("span").filter(has_text="Statistics").first
        statistics_tab.scroll_into_view_if_needed()
        statistics_tab.wait_for(timeout=20000)
        statistics_tab.click()

        page.wait_for_load_state("domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

        page.wait_for_timeout(2000)

    def get_matches_played(self, page, seasons_to_process: int = 1) -> int:
        # Saison 1 : bloc gauche, ligne "Matches played" = 2e li
        left_block = page.locator("ul.LeftStatBlock-sc-16aevzl-7").first
        left_block.wait_for(timeout=15000)

        first_row = left_block.locator("li.Row-sc-16aevzl-9").nth(1)
        first_value_locator = first_row.locator(
            "div.Values-sc-16aevzl-10 div.StatValue-sc-16aevzl-11"
        ).first

        first_text = first_value_locator.inner_text().strip()

        try:
            first_season_matches = int(first_text)
        except ValueError:
            raise RuntimeError(f"Impossible de lire Matches played saison 1: {first_text}")

        if seasons_to_process == 1:
            return first_season_matches

        try:
            # activer Compare with previous season
            compare_switch = page.locator('div[role="switch"]').filter(
                has=page.get_by_text("Compare with previous season", exact=False)
            ).first
            compare_switch.wait_for(timeout=10000)

            aria_checked = compare_switch.get_attribute("aria-checked")
            if aria_checked != "true":
                slider = compare_switch.locator("div.Slider-sc-e7kel1-1").first
                slider.scroll_into_view_if_needed()
                slider.click()
                page.wait_for_timeout(1500)

            # attendre que le switch soit bien activé
            compare_switch = page.locator('div[role="switch"][aria-checked="true"]').filter(
                has=page.get_by_text("Compare with previous season", exact=False)
            ).first
            compare_switch.wait_for(timeout=10000)

            # Saison 2 : bloc droit, ligne "Matches played" = 2e li
            right_block = page.locator("ul.RightStatBlock-sc-16aevzl-8").first
            right_block.wait_for(timeout=10000)

            second_row = right_block.locator("li.Row-sc-16aevzl-9").nth(1)
            second_value_locator = second_row.locator(
                "div.Values-sc-16aevzl-10 div.StatValue-sc-16aevzl-11"
            ).first

            second_text = second_value_locator.inner_text().strip()
            second_season_matches = int(second_text)

            total_matches = first_season_matches + second_season_matches
            print(
                f"[DEBUG] Matches played saison 1: {first_season_matches} | "
                f"saison 2: {second_season_matches} | total: {total_matches}"
            )
            return total_matches

        except Exception as e:
            raise RuntimeError(f"Impossible de lire Matches played saison 2: {e}")
        

    def expand_matches_list(self, page, target_count: int):
        safety = 0
        max_rounds = 20

        while safety < max_rounds:
            match_items = self.get_match_items(page)
            current_count = match_items.count()
            print(f"[DEBUG] Matchs visibles actuellement: {current_count} / cible: {target_count}")

            if current_count >= target_count:
                return current_count

            show_more_button = page.get_by_role("button", name="Show more").first

            if show_more_button.count() == 0 or not show_more_button.is_visible():
                print("[DEBUG] Bouton Show more non visible, arrêt expansion")
                return current_count

            show_more_button.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            show_more_button.click()
            page.wait_for_timeout(2000)

            safety += 1

        return self.get_match_items(page).count()
    
    def get_match_items(self, page):
        return page.locator("ul.MatchesList-sc-1gt3fpl-2 > li.MatchItem-sc-wzxkix-1")

    def get_match_profile_href(self, match_item):
        link = match_item.locator('a[href*="/matches/"]').first
        if link.count() == 0:
            return None
        return link.get_attribute("href")

    def click_all_players_actions_for_match(self, page, match_item, index: int):
        profile_href = self.get_match_profile_href(match_item)
        print(f"[DEBUG] Match {index + 1} href: {profile_href}")

        match_item.wait_for(state="visible", timeout=10000)

        # SportsBase currently uses both "Player actions" and the older
        # "All player actions" label. Keep the selector used by the proven
        # subscription scraper so a UI wording change does not hide the button.
        action_button = match_item.get_by_role(
            "button",
            name=PLAYER_ACTIONS_BUTTON_RE,
        ).first
        action_button.wait_for(state="visible", timeout=10000)
        action_button.scroll_into_view_if_needed()

        with page.expect_popup(timeout=20000) as popup_info:
            action_button.click()

        popup = popup_info.value
        popup.wait_for_load_state("domcontentloaded", timeout=30000)
        popup.wait_for_timeout(4000)

        print(f"[DEBUG] Popup URL match {index + 1}: {popup.url}")
        print(f"[DEBUG] Popup title match {index + 1}: {popup.title()}")

        return popup

    def get_match_title_from_popup(self, popup):
        try:
            title_locator = popup.locator("div.MatchTeams-sc-91pnol-5").first
            title_locator.wait_for(timeout=10000)
            match_title = title_locator.inner_text().strip()
            print(f"[DEBUG] Titre du match popup: {match_title}")
            return match_title
        except Exception as e:
            print(f"[WARN] Impossible de récupérer le titre du match: {e}")
            return "match_unknown"

    def open_download_menu(self, popup):
        right_panel = popup.locator("#rightPanel").first
        right_panel.wait_for(timeout=20000)

        download_button = right_panel.get_by_role("button", name="Download").first
        download_button.scroll_into_view_if_needed()
        download_button.wait_for(timeout=20000)
        download_button.click()

        popup.wait_for_timeout(1200)

    def select_track(self, popup):
        track_dropdown = popup.locator("div.DropdownFrame-sc-1228j4m-0").filter(
            has=popup.get_by_text("Select a track", exact=False)
        ).first

        track_dropdown.wait_for(timeout=10000)

        track_option = track_dropdown.locator("div.DropdownItem-sc-tuwi5p-2").filter(
            has_text=re.compile(r"Track\s*1\s*for all episodes", re.I)
        ).last

        track_option.wait_for(timeout=10000)
        track_option.click()
        popup.wait_for_timeout(1000)

    def select_best_quality(self, popup):
        format_dropdown = popup.locator("div.DropdownFrame-sc-1228j4m-0").filter(
            has=popup.get_by_text("Select the format", exact=False)
        ).first

        format_dropdown.wait_for(timeout=10000)

        for quality in ["1080", "720", "480"]:
            option = format_dropdown.get_by_text(quality, exact=True)
            if option.count() > 0:
                try:
                    option.first.click()
                    print(f"[DEBUG] Qualité sélectionnée: {quality}")
                    popup.wait_for_timeout(1000)
                    return quality
                except Exception as e:
                    print(f"[WARN] Clic {quality} impossible: {e}")

        raise RuntimeError("Aucune qualité disponible (1080/720/480)")

    def select_download_type(self, popup):
        type_dropdown = popup.locator("div.DropdownFrame-sc-1228j4m-0").filter(
            has=popup.get_by_text("Type of download", exact=False)
        ).first

        type_dropdown.wait_for(timeout=10000)

        one_file_option = type_dropdown.locator("div.DropdownItem-sc-tuwi5p-2").filter(
            has_text=re.compile(r"One file", re.I)
        ).last

        one_file_option.wait_for(timeout=10000)
        one_file_option.click()
        popup.wait_for_timeout(1200)

    def generate_download_in_popup(self, popup):
        popup.wait_for_timeout(3000)

        match_title = self.get_match_title_from_popup(popup)

        self.open_download_menu(popup)
        self.select_track(popup)
        selected_quality = self.select_best_quality(popup)

        generation_confirmed = False
        direct_download_cancelled = False

        def abort_video_download(route):
            nonlocal direct_download_cancelled
            url = route.request.url.lower()
            if ".mp4" in url or "videocuts" in url:
                print(f"[DEBUG] Téléchargement bloqué: {route.request.url}")
                direct_download_cancelled = True
                route.abort()
            else:
                route.continue_()

        try:
            type_dropdown = popup.locator("div.DropdownFrame-sc-1228j4m-0").filter(
                has=popup.get_by_text("Type of download", exact=False)
            ).first
            type_dropdown.wait_for(timeout=10000)

            popup.wait_for_timeout(500)

            one_file_option = popup.locator("div.DropdownItem-sc-tuwi5p-2").filter(
                has_text=re.compile(r"^\s*One file\s*$", re.I)
            ).first

            one_file_option.wait_for(state="visible", timeout=10000)
            one_file_option.scroll_into_view_if_needed()
            popup.wait_for_timeout(300)

            try:
                print(f"[DEBUG] one_file_option count = {one_file_option.count()}")
                print(f"[DEBUG] one_file_option text = {one_file_option.inner_text().strip()}")
            except Exception:
                pass

            # Limiter le blocage à cette popup ; les autres pages restent intactes.
            popup.route("**/*", abort_video_download)

            try:
                one_file_option.click(timeout=5000, no_wait_after=True)
                print("[DEBUG] Clic One file effectué")
                try:
                    popup.get_by_text(
                        "Video file generation has started",
                        exact=False,
                    ).wait_for(timeout=7000)
                    print(
                        f"[DEBUG] Message génération vidéo détecté "
                        f"avec qualité {selected_quality}"
                    )
                    generation_confirmed = True
                except Exception:
                    print("[INFO] Notification de génération non détectée")
            finally:
                try:
                    popup.unroute("**/*", abort_video_download)
                except Exception:
                    pass

        except Exception as e:
            print(f"[WARN] Erreur durant generate_download_in_popup: {e}")

        popup.wait_for_timeout(1000)
        return match_title, generation_confirmed, direct_download_cancelled

    def generate_all_players_actions(self, page, matches_played: int):
        processed = 0
        max_matches = matches_played
        generated_match_titles = []

        # IMPORTANT : charger plus de matchs si nécessaire
        current_count = self.expand_matches_list(page, max_matches)
        print(f"[DEBUG] Nombre de vrais matchs visibles après expansion: {current_count}")

        match_items = self.get_match_items(page)

        for i in range(min(current_count, max_matches)):
            match_item = match_items.nth(i)

            try:
                profile_href = self.get_match_profile_href(match_item)
                print(f"[DEBUG] Traitement match visible #{i + 1} | href={profile_href}")

                popup = self.click_all_players_actions_for_match(page, match_item, i)
                match_title, generation_confirmed, direct_download_cancelled = self.generate_download_in_popup(popup)

                try:
                    if not popup.is_closed():
                        popup.close()
                except Exception as e:
                    print(f"[WARN] popup.close error: {e}")

                if generation_confirmed:
                    processed += 1
                    generated_match_titles.append(match_title)
                    self.notify_progress(
                        "sportsbase_generation",
                        current=processed,
                        total=max_matches,
                        message=f"Génération confirmée pour le match {processed}/{max_matches}",
                    )
                else:
                    print(
                        f"[WARN] Match #{i + 1} non compté : SportsBase "
                        "n’a pas confirmé la génération"
                    )

                print(
                    f"[DEBUG] Match #{i + 1} traité | "
                    f"title={match_title} | "
                    f"confirmed={generation_confirmed} | "
                    f"direct_download_cancelled={direct_download_cancelled}"
                )

                page.wait_for_timeout(800)

            except Exception as e:
                print(f"[WARN] Match {i + 1} non traité: {e}")

        return processed, generated_match_titles

    def open_my_videos(self, page):
        target_url = "https://football.sportsbase.world/profile/myvideo"
        print(f"[DEBUG] Ouverture directe My videos: {target_url}")

        page.goto(target_url, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception as e:
            print(f"[WARN] networkidle non atteint sur My videos: {e}")

        print(f"[DEBUG] URL après goto my-videos: {page.url}")
        print(f"[DEBUG] Title après goto my-videos: {page.title()}")

        try:
            my_videos_text = page.get_by_text("My videos", exact=True)
            print(f"[DEBUG] 'My videos' count: {my_videos_text.count()}")
        except Exception as e:
            print(f"[WARN] Impossible de compter 'My videos': {e}")

        try:
            table_count = page.locator('div[role="table"]').count()
            print(f"[DEBUG] div[role='table'] count: {table_count}")
        except Exception as e:
            print(f"[WARN] Impossible de compter div[role='table']: {e}")

        try:
            rowgroup_count = page.locator('div[role="rowgroup"]').count()
            print(f"[DEBUG] div[role='rowgroup'] count: {rowgroup_count}")
        except Exception as e:
            print(f"[WARN] Impossible de compter div[role='rowgroup']: {e}")

        try:
            row_count = page.locator('div[role="row"]').count()
            print(f"[DEBUG] div[role='row'] count: {row_count}")
        except Exception as e:
            print(f"[WARN] Impossible de compter div[role='row']: {e}")

        table = page.locator('div[role="table"]').first
        table.wait_for(timeout=20000)

        print("[DEBUG] Table My videos détectée")
        return page

    def snapshot_existing_video_keys(self, player_page, player_name: str):
        """Remember old rows so a new job cannot download a previous player's clip."""
        snapshot_page = player_page.context.new_page()
        normalized_target = f"{player_name}, All player actions".lower().strip()
        existing = {}
        try:
            self.open_my_videos(snapshot_page)
            body_group = snapshot_page.locator('div[role="rowgroup"]').nth(1)
            rows = body_group.locator('div[role="row"]')
            for index in range(rows.count()):
                row = rows.nth(index)
                title_locator = row.locator("span.Name-sc-jbc8ns-2").first
                if title_locator.count() == 0:
                    continue
                title_text = title_locator.inner_text().strip()
                if normalized_target not in title_text.casefold():
                    continue
                date_text = row.locator("div.DateCellContainer-sc-88jqaj-0").first.inner_text().strip() if row.locator("div.DateCellContainer-sc-88jqaj-0").count() else ""
                duration_text = row.locator("div.DurationCellContainer-sc-kz1ea2-0").first.inner_text().strip() if row.locator("div.DurationCellContainer-sc-kz1ea2-0").count() else ""
                fingerprint = f"{title_text}|{date_text}|{duration_text}"
                existing[fingerprint] = existing.get(fingerprint, 0) + 1
        except Exception as exc:
            print(f"[WARN] Snapshot My Videos incomplet: {exc}")
        finally:
            snapshot_page.close()
        print(f"[DEBUG] Anciennes vidéos exclues: {sum(existing.values())}")
        return existing

    def download_ready_videos(
        self,
        page,
        player_name: str,
        raw_clips_dir: Path,
        generated_match_titles: list,
        max_downloads: int,
        excluded_row_keys=None,
    ):
        my_videos_page = self.open_my_videos(page)
        downloaded_files = []
        normalized_target = f"{player_name}, All player actions".lower().strip()

        excluded_counts = (
            dict(excluded_row_keys)
            if isinstance(excluded_row_keys, dict)
            else {key: 1 for key in (excluded_row_keys or ())}
        )
        seen_rows = set()
        global_rounds = 0
        max_global_rounds = 20

        def load_rows():
            my_videos_page.bring_to_front()
            my_videos_page.wait_for_load_state("domcontentloaded")
            try:
                my_videos_page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            my_videos_page.wait_for_timeout(1500)

            table = my_videos_page.locator('div[role="table"]').first
            table.wait_for(timeout=20000)

            body_group = my_videos_page.locator('div[role="rowgroup"]').nth(1)
            body_group.wait_for(timeout=15000)

            return body_group.locator('div[role="row"]')

        def refresh_page():
            print("[DEBUG] Refresh My videos")
            my_videos_page.reload(wait_until="domcontentloaded", timeout=30000)
            my_videos_page.wait_for_timeout(3000)
            try:
                my_videos_page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

        def get_candidate_indexes(rows):
            row_count = rows.count()
            indexes = []
            occurrences = {}

            for i in range(row_count):
                try:
                    row = rows.nth(i)
                    title_locator = row.locator("span.Name-sc-jbc8ns-2").first
                    if title_locator.count() == 0:
                        continue

                    title_text = title_locator.inner_text().strip().lower()
                    if normalized_target in title_text:
                        original_title = title_locator.inner_text().strip()
                        date_text = row.locator("div.DateCellContainer-sc-88jqaj-0").first.inner_text().strip() if row.locator("div.DateCellContainer-sc-88jqaj-0").count() else ""
                        duration_text = row.locator("div.DurationCellContainer-sc-kz1ea2-0").first.inner_text().strip() if row.locator("div.DurationCellContainer-sc-kz1ea2-0").count() else ""
                        fingerprint = f"{original_title}|{date_text}|{duration_text}"
                        occurrence = occurrences.get(fingerprint, 0) + 1
                        occurrences[fingerprint] = occurrence
                        unique_key = f"{fingerprint}|occurrence={occurrence}"
                        if (
                            occurrence > excluded_counts.get(fingerprint, 0)
                            and unique_key not in seen_rows
                        ):
                            indexes.append(i)
                except Exception:
                    continue

            return indexes

        def get_row_identity(rows, row_index):
            """Identify duplicate-looking rows without collapsing a newly generated one."""
            fingerprints = {}
            selected = None
            for scan_index in range(row_index + 1):
                scan_row = rows.nth(scan_index)
                title_locator = scan_row.locator("span.Name-sc-jbc8ns-2").first
                if title_locator.count() == 0:
                    continue
                title_text = title_locator.inner_text().strip()
                date_locator = scan_row.locator("div.DateCellContainer-sc-88jqaj-0").first
                duration_locator = scan_row.locator("div.DurationCellContainer-sc-kz1ea2-0").first
                date_text = date_locator.inner_text().strip() if date_locator.count() else ""
                duration_text = duration_locator.inner_text().strip() if duration_locator.count() else ""
                fingerprint = f"{title_text}|{date_text}|{duration_text}"
                occurrence = fingerprints.get(fingerprint, 0) + 1
                fingerprints[fingerprint] = occurrence
                if scan_index == row_index:
                    selected = (
                        f"{fingerprint}|occurrence={occurrence}",
                        date_text,
                        duration_text,
                    )
            return selected

        def expand_if_needed():
            safety = 0
            max_expand_rounds = 20

            while safety < max_expand_rounds:
                rows = load_rows()
                candidate_indexes = get_candidate_indexes(rows)

                print(f"[DEBUG] Rows candidates pour le joueur (avant limite): {candidate_indexes}")

                if len(candidate_indexes) >= max_downloads:
                    return rows, candidate_indexes

                show_more = my_videos_page.get_by_role("button", name="Show more")
                if show_more.count() > 0 and show_more.first.is_visible():
                    print("[DEBUG] Click Show more")
                    show_more.first.scroll_into_view_if_needed()
                    my_videos_page.wait_for_timeout(300)
                    show_more.first.click()
                    my_videos_page.wait_for_timeout(2000)
                else:
                    return rows, candidate_indexes

                safety += 1

            rows = load_rows()
            return rows, get_candidate_indexes(rows)

        while len(downloaded_files) < max_downloads and global_rounds < max_global_rounds:
            try:
                rows, candidate_indexes = expand_if_needed()
            except Exception as e:
                print(f"[WARN] Impossible de charger My videos: {e}")
                global_rounds += 1
                try:
                    refresh_page()
                except Exception:
                    my_videos_page.wait_for_timeout(4000)
                continue

            if not candidate_indexes:
                global_rounds += 1
                print(f"[DEBUG] Aucune row candidate. refresh + retry. global_rounds={global_rounds}")
                try:
                    refresh_page()
                except Exception:
                    my_videos_page.wait_for_timeout(5000)
                continue

            if len(candidate_indexes) < max_downloads:
                global_rounds += 1
                print(
                    f"[DEBUG] Rows candidates insuffisantes: {len(candidate_indexes)} / {max_downloads}. "
                    f"refresh + retry. global_rounds={global_rounds}"
                )
                try:
                    refresh_page()
                except Exception:
                    my_videos_page.wait_for_timeout(5000)
                continue

            candidate_indexes = candidate_indexes[:max_downloads]
            print(f"[DEBUG] Rows candidates retenues: {candidate_indexes}")

            downloaded_this_round = 0

            for reverse_pos, row_index in enumerate(reversed(candidate_indexes)):
                if len(downloaded_files) >= max_downloads:
                    break

                try:
                    rows = load_rows()
                    row = rows.nth(row_index)

                    identity = get_row_identity(rows, row_index)
                    if not identity:
                        continue
                    unique_key, date_text, duration_text = identity
                    if unique_key in seen_rows:
                        continue

                    wait_done_round = 0
                    max_wait_done_rounds = 12

                    while wait_done_round < max_wait_done_rounds:
                        rows = load_rows()
                        row = rows.nth(row_index)

                        status_locator = row.locator("div.StatusContainer-sc-1qv6hin-1 span").first
                        if status_locator.count() == 0:
                            break

                        status_text = status_locator.inner_text().strip().lower()
                        print(f"[DEBUG] Row {row_index} status = {status_text}")

                        if status_text == "done":
                            break

                        print(f"[DEBUG] Row {row_index} encore processing, attente...")
                        wait_done_round += 1
                        my_videos_page.wait_for_timeout(5000)

                    rows = load_rows()
                    row = rows.nth(row_index)

                    status_locator = row.locator("div.StatusContainer-sc-1qv6hin-1 span").first
                    if status_locator.count() == 0:
                        continue

                    status_text = status_locator.inner_text().strip().lower()
                    if status_text != "done":
                        print(f"[DEBUG] Row {row_index} pas prête après attente: {status_text}")
                        continue

                    identity = get_row_identity(rows, row_index)
                    if not identity:
                        continue
                    unique_key, date_text, duration_text = identity
                    if unique_key in seen_rows:
                        continue

                    print(f"[DEBUG] Ligne candidate: {unique_key}")

                    buttons_cell = row.locator("div.ButtonsCellContainer-sc-1t45i5t-0").first
                    if buttons_cell.count() == 0:
                        continue

                    icon_wrappers = buttons_cell.locator("div.IconWrapper-sc-1t45i5t-3")
                    if icon_wrappers.count() == 0:
                        continue

                    download_icon = icon_wrappers.first
                    download_icon.scroll_into_view_if_needed()
                    my_videos_page.wait_for_timeout(300)

                    try:
                        with my_videos_page.expect_download(timeout=15000) as download_info:
                            download_icon.click()
                        download = download_info.value
                    except Exception:
                        try:
                            with my_videos_page.expect_download(timeout=15000) as download_info:
                                download_icon.evaluate("(el) => el.click()")
                            download = download_info.value
                        except Exception as e:
                            print(f"[WARN] Download row {row_index} impossible: {e}")
                            continue

                    match_title = "match_unknown"
                    if reverse_pos < len(generated_match_titles):
                        match_title = generated_match_titles[reverse_pos]

                    safe_match_title = self.sanitize_filename(match_title)
                    safe_player_name = self.sanitize_filename(player_name)
                    safe_duration = self.sanitize_filename(duration_text.replace(":", "-")) if duration_text else "duration_unknown"
                    safe_date = self.sanitize_filename(date_text.replace(":", "-").replace(" ", "_")) if date_text else "date_unknown"

                    ext = Path(download.suggested_filename).suffix if download.suggested_filename else ".mp4"
                    filename = f"{safe_player_name} - {safe_match_title} - {safe_date} - {safe_duration}{ext}"

                    save_path = raw_clips_dir / filename
                    download.save_as(str(save_path))

                    downloaded_files.append(str(save_path))
                    seen_rows.add(unique_key)
                    downloaded_this_round += 1
                    self.notify_progress(
                        "sportsbase_download",
                        current=len(downloaded_files),
                        total=max_downloads,
                        message=f"{len(downloaded_files)}/{max_downloads} matchs téléchargés",
                    )

                    print(f"[DEBUG] Fichier téléchargé: {save_path}")
                    my_videos_page.wait_for_timeout(800)

                except Exception as e:
                    print(f"[WARN] row {row_index} error: {e}")

            if downloaded_this_round == 0:
                global_rounds += 1
                print(f"[DEBUG] Aucun téléchargement ce round. global_rounds={global_rounds}")
                try:
                    refresh_page()
                except Exception:
                    my_videos_page.wait_for_timeout(5000)
            else:
                global_rounds = 0

        return downloaded_files
