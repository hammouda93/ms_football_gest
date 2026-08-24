import base64
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

from gestion_joueurs.sportsbase_playwright import SportsBaseAutomation

from .delivery import send_all_actions_email


SPORTSBASE_ROOT = "https://football.sportsbase.world"
MATCH_ID_RE = re.compile(r"/matches/(\d+)")
PLAYER_ID_RE = re.compile(r"/players/(\d+)")
DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
SCORE_RE = re.compile(r"\b(\d+)\s*[:–-]\s*(\d+)\b")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _b64(png):
    return base64.b64encode(png).decode("ascii") if png else ""


def _safe_int(value):
    if value is None:
        return None
    match = re.search(r"-?\d+", str(value).replace(" ", ""))
    return int(match.group()) if match else None


def _iso_date(text):
    match = DATE_RE.search(text or "")
    if not match:
        return None
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def _clean_label(value):
    return re.sub(r"\s+", " ", str(value or "")).strip(" :\n\t")


class SportsBaseSubscriptionScraper:
    """Read subscription data while reusing the project's proven SportsBase workflow."""

    def __init__(self, storage_root):
        self.storage_root = Path(storage_root)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.automation = SportsBaseAutomation(base_download_dir=str(self.storage_root))

    def run(self, job):
        player = job["player"]
        player_root = self.storage_root / player["storage_key"]
        downloads_dir = player_root / "_downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        known = {
            str(item["sportsbase_match_id"]): item
            for item in job.get("known_matches", [])
        }
        result = {
            "status": "success",
            "profile": {},
            "matches": [],
            "summary": {},
            "error": "",
        }

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=self.automation.headless,
                args=["--start-maximized"],
            )
            context = browser.new_context(accept_downloads=True, no_viewport=True)
            page = context.new_page()
            try:
                self.automation.ensure_logged_in_and_open_player(
                    page, player["sportsbase_url"]
                )
                if job["job_type"] in {"full", "profile"}:
                    result["profile"] = self._read_profile(page, job)

                if job["job_type"] in {"full", "profile", "matches"}:
                    self.automation.open_player_statistics(page)
                    if result["profile"]:
                        result["profile"].update(self._read_season_statistics(page))

                if job["job_type"] in {"full", "matches", "all_actions"}:
                    result["matches"] = self._read_matches(
                        page=page,
                        context=context,
                        job=job,
                        known=known,
                        player_root=player_root,
                        downloads_dir=downloads_dir,
                    )
            except Exception as exc:
                result["status"] = "partial" if result["profile"] or result["matches"] else "failed"
                result["error"] = str(exc)
            finally:
                context.close()
                browser.close()

        result["summary"] = {
            "matches_imported": len(result["matches"]),
            "all_actions_downloaded": sum(
                item.get("actions_state") in {"downloaded", "emailed"}
                for item in result["matches"]
            ),
        }
        return result

    def _read_profile(self, page, job):
        raw = page.evaluate(
            r"""
            () => {
              const text = (node) => node ? node.textContent.replace(/\s+/g, ' ').trim() : '';
              const passport = {};
              document.querySelectorAll('[class*="PassportItem"]').forEach((row) => {
                const key = text(row.querySelector('[class*="ParamName"]'));
                const values = [...row.querySelectorAll('[class*="ParamValueContainer"]')].map((node) => ({
                  main: text(node.querySelector('[class*="ParamValueMain"]')),
                  second: text(node.querySelector('[class*="ParamValueSecond"]')),
                  full: text(node),
                }));
                if (key) passport[key] = values;
              });
              const clubLink = document.querySelector('a[href*="/teams/"]');
              const image = document.querySelector('[class*="ProfileLogo"]');
              return {
                name: text(document.querySelector('[class*="ProfileTitle"]')),
                nativeName: text(document.querySelector('[class*="NativeName"]')),
                club: text(clubLink),
                clubHref: clubLink?.getAttribute('href') || '',
                imageUrl: image?.getAttribute('src') || '',
                passport,
              };
            }
            """
        )
        passport = raw.get("passport", {})

        def first(label):
            rows = passport.get(label, [])
            return rows[0].get("main", "") if rows else ""

        positions = []
        for item in passport.get("Position", []):
            percent = _safe_int(item.get("second"))
            positions.append(
                {"code": item.get("main", ""), "name": item.get("main", ""), "percent": percent}
            )

        player_id = PLAYER_ID_RE.search(page.url)
        club_id = re.search(r"/teams/(\d+)", raw.get("clubHref", ""))
        heatmap = self._capture_named_map(page, "Heatmap")
        touches = self._capture_named_map(page, "Ball touches map")
        radar = self._capture_radar(page)
        return {
            "season": job["season"],
            "sportsbase_player_id": player_id.group(1) if player_id else "",
            "sportsbase_player_name": raw.get("name") or job["player"]["name"],
            "native_name": raw.get("nativeName", ""),
            "club_name": raw.get("club", ""),
            "club_sportsbase_id": club_id.group(1) if club_id else "",
            "profile_image_url": raw.get("imageUrl", ""),
            "date_of_birth": _iso_date(first("Date of birth")),
            "nationality": first("Nationality"),
            "contract_expires": _iso_date(first("Contract expires")),
            "height_weight": first("Height, Weight"),
            "national_team": first("National team"),
            "strong_foot": first("Strong foot"),
            "time_on_field_percent": _safe_int(first("Time on the field, %")),
            "positions": positions,
            "radar_png_base64": _b64(radar),
            "heatmap_png_base64": _b64(heatmap),
            "ball_touches_png_base64": _b64(touches),
            "source_metadata": {"profile_url": page.url, "captured_at": _now_iso()},
        }

    def _capture_named_map(self, page, label):
        try:
            button = page.get_by_text(label, exact=True).first
            button.scroll_into_view_if_needed()
            button.click()
            page.wait_for_timeout(700)
            wrapper = page.locator('[class*="MapFieldWrapper"]').first
            return wrapper.screenshot(type="png")
        except Exception:
            return b""

    def _capture_radar(self, page):
        try:
            page.get_by_text("Radar", exact=True).first.click()
            page.wait_for_timeout(500)
            candidates = page.locator('svg[width][height]')
            best = None
            area = 0
            for index in range(candidates.count()):
                candidate = candidates.nth(index)
                box = candidate.bounding_box()
                if box and box["width"] * box["height"] > area:
                    best, area = candidate, box["width"] * box["height"]
            return best.screenshot(type="png") if best and area > 50000 else b""
        except Exception:
            return b""

    def _read_season_statistics(self, page):
        data = page.evaluate(
            r"""
            () => {
              const text = (node) => node ? node.textContent.replace(/\s+/g, ' ').trim() : '';
              const read = (selector) => {
                const result = {};
                const block = document.querySelector(selector);
                if (!block) return result;
                block.querySelectorAll('li').forEach((row) => {
                  const labelNode = row.querySelector('[class*="StatName"], [class*="ParamName"], span');
                  const values = [...row.querySelectorAll('[class*="StatValue"]')].map(text);
                  const label = text(labelNode);
                  if (label && values.length) result[label] = values[0];
                });
                return result;
              };
              const season = read('ul[class*="LeftStatBlock"]');
              let averages = {};
              document.querySelectorAll('[class*="Average"], [class*="StatBlock"]').forEach((block) => {
                block.querySelectorAll('li').forEach((row) => {
                  const label = text(row.querySelector('[class*="StatName"], [class*="ParamName"], span'));
                  const value = text(row.querySelector('[class*="StatValue"]'));
                  if (label && value && !(label in season)) averages[label] = value;
                });
              });
              let bestTable = {headers: [], rows: []};
              document.querySelectorAll('[role="table"]').forEach((table) => {
                const headers = [...table.querySelectorAll('[role="headercell"], [role="columnheader"]')].map(text);
                const rows = [...table.querySelectorAll('[role="row"]')].map((row) => {
                  const cells = [...row.querySelectorAll('[role="bodycell"], [role="cell"]')].map(text);
                  const href = row.querySelector('a[href*="/matches/"]')?.getAttribute('href') || '';
                  return cells.length ? {cells, href} : null;
                }).filter(Boolean);
                if (headers.length > bestTable.headers.length && rows.length) bestTable = {headers, rows};
              });
              return {season, averages, table: bestTable};
            }
            """
        )
        headers = [_clean_label(value) for value in data.get("table", {}).get("headers", [])]
        rows = []
        numeric_columns = {header: [] for header in headers}
        for raw_row in data.get("table", {}).get("rows", []):
            values = [_clean_label(value) for value in raw_row.get("cells", [])]
            href_match = MATCH_ID_RE.search(raw_row.get("href", ""))
            rows.append(
                {
                    "sportsbase_match_id": href_match.group(1) if href_match else "",
                    "values": values,
                }
            )
            for header, value in zip(headers, values):
                normalized = value.replace("%", "").replace(",", ".").strip()
                if re.fullmatch(r"-?\d+(?:\.\d+)?", normalized):
                    numeric_columns[header].append(float(normalized))

        season = data.get("season", {})
        averages = data.get("averages", {})
        for header, values in numeric_columns.items():
            if not values or header in season:
                continue
            average = sum(values) / len(values)
            total = average if "%" in header else sum(values)
            season[header] = self._format_number(total, percent="%" in header)
            averages.setdefault(header, self._format_number(average, percent="%" in header))
        return {
            "season_statistics": season,
            "average_statistics": averages,
            "season_table_headers": headers,
            "season_match_rows": rows,
        }

    @staticmethod
    def _format_number(value, percent=False):
        formatted = f"{value:.2f}".rstrip("0").rstrip(".")
        return f"{formatted}%" if percent else formatted

    def _read_matches(self, *, page, context, job, known, player_root, downloads_dir):
        try:
            matches_played = self.automation.get_matches_played(page, seasons_to_process=1)
        except Exception:
            matches_played = 100
        self.automation.expand_matches_list(page, matches_played)
        discovered = self._discover_matches(page)
        discovered = self._apply_season_boundary(discovered, job)
        output = []
        generation_queue = []

        for match_data in discovered:
            previous = known.get(match_data["sportsbase_match_id"], {})
            if previous.get("complete"):
                continue
            match_item = self._match_item(page, match_data["sportsbase_match_id"])
            if job["job_type"] != "all_actions":
                try:
                    match_data["stats"] = self._read_match_details(
                        page, context, match_item, match_data, job
                    )
                    match_data["sync_state"] = "synced"
                except Exception as exc:
                    match_data["sync_state"] = "partial"
                    match_data.setdefault("source_metadata", {})["stats_error"] = str(exc)
            else:
                match_data["sync_state"] = previous.get("sync_state", "discovered")

            if not job.get("all_actions_enabled"):
                match_data["actions_state"] = "not_requested"
            elif previous.get("actions_state") == "emailed":
                match_data["actions_state"] = previous["actions_state"]
            elif previous.get("actions_state") == "downloaded" and job.get(
                "email_delivery_enabled"
            ):
                if self._retry_existing_delivery(match_data, previous, job):
                    generation_queue.append((match_data, match_item))
            elif previous.get("actions_state") == "downloaded":
                match_data["actions_state"] = "downloaded"
            else:
                match_data["actions_state"] = "queued"
                generation_queue.append((match_data, match_item))
            output.append(match_data)

        self._generate_and_deliver_actions(
            page=page,
            job=job,
            player_root=player_root,
            downloads_dir=downloads_dir,
            queue=generation_queue,
        )
        return output

    def _retry_existing_delivery(self, match_data, previous, job):
        folder_key = previous.get("local_folder_key", "")
        filename = previous.get("all_actions_filename", "")
        path = self.storage_root / folder_key / filename if folder_key and filename else None
        if not path or not path.is_file():
            match_data["actions_state"] = "queued"
            match_data["delivery_error"] = "Fichier local introuvable ; une nouvelle génération est nécessaire."
            return True
        sent, error = send_all_actions_email(
            recipient=job["player"].get("email"),
            player_name=job["player"]["name"],
            match_label=f"{match_data['home_team']} - {match_data['away_team']}",
            video_path=path,
        )
        match_data.update(
            {
                "actions_state": "emailed" if sent else "downloaded",
                "local_folder_key": folder_key,
                "all_actions_filename": filename,
                "all_actions_emailed_at": _now_iso() if sent else None,
                "delivery_error": "" if sent else error,
            }
        )
        return False

    def _discover_matches(self, page):
        rows = []
        items = self.automation.get_match_items(page)
        for index in range(items.count()):
            item = items.nth(index)
            href = self.automation.get_match_profile_href(item) or ""
            id_match = MATCH_ID_RE.search(href)
            if not id_match:
                continue
            raw = item.evaluate(
                r"""
                (row) => {
                  const text = (node) => node ? node.textContent.replace(/\s+/g, ' ').trim() : '';
                  const teamLinks = [...row.querySelectorAll('a[href*="/teams/"]')];
                  return {
                    text: text(row),
                    teams: teamLinks.slice(0, 2).map((node) => ({
                      name: text(node), href: node.getAttribute('href') || ''
                    })),
                    competition: text(row.querySelector('[class*="Tournament"], [class*="Competition"]')),
                    week: text(row.querySelector('[class*="Week"], [class*="Round"]')),
                    lineup: text(row.querySelector('[class*="Lineup"], [class*="Position"]')),
                  };
                }
                """
            )
            text = raw.get("text", "")
            teams = raw.get("teams", [])
            score = SCORE_RE.search(text)
            row = {
                "sportsbase_match_id": id_match.group(1),
                "match_date": _iso_date(text),
                "competition": raw.get("competition", ""),
                "week": raw.get("week", ""),
                "home_team": teams[0]["name"] if teams else "",
                "home_team_id": self._id_from_href(teams[0]["href"]) if teams else "",
                "away_team": teams[1]["name"] if len(teams) > 1 else "",
                "away_team_id": self._id_from_href(teams[1]["href"]) if len(teams) > 1 else "",
                "home_score": int(score.group(1)) if score else None,
                "away_score": int(score.group(2)) if score else None,
                "lineup": raw.get("lineup", ""),
                "match_url": urljoin(SPORTSBASE_ROOT, href),
                "source_metadata": {"list_position": index + 1, "captured_at": _now_iso()},
            }
            rows.append(row)
        return rows

    @staticmethod
    def _id_from_href(href):
        match = re.search(r"/(?:teams|players)/(\d+)", href or "")
        return match.group(1) if match else ""

    @staticmethod
    def _apply_season_boundary(matches, job):
        first_id = str(job.get("first_match_id") or "")
        if first_id:
            index = next(
                (i for i, item in enumerate(matches) if item["sportsbase_match_id"] == first_id),
                None,
            )
            if index is not None:
                matches = matches[: index + 1]
        start = job.get("sync_from_date")
        if start:
            matches = [item for item in matches if not item["match_date"] or item["match_date"] >= start]
        return matches

    def _match_item(self, page, match_id):
        item = self.automation.get_match_items(page).filter(
            has=page.locator(f'a[href*="/matches/{match_id}"]')
        ).first
        item.wait_for(state="visible", timeout=10000)
        return item

    def _read_match_details(self, page, context, match_item, match_data, job):
        more = match_item.get_by_text("More details", exact=False).first
        if more.count() and more.is_visible():
            more.click()
            page.wait_for_timeout(800)
        pairs = self._extract_label_values(match_item)
        pairs.update(
            self._extract_match_table_stats(
                page, match_data["sportsbase_match_id"]
            )
        )
        success = {key: value for key, value in pairs.items() if "%" in value or "%" in key}
        summary = {key: value for key, value in pairs.items() if key not in success}
        heatmap = self._capture_map_in_container(match_item, "Heatmap")
        touches = self._capture_map_in_container(match_item, "Ball touches map")
        profile = self._read_match_profile(
            context,
            match_data["match_url"],
            job["player"],
        )
        return {
            "team_name": profile.get("team_name") or job["player"].get("club", ""),
            "position": profile.get("position") or match_data.get("lineup", ""),
            "minutes_played": profile.get("minutes_played"),
            "index": profile.get("index"),
            "team_rank": profile.get("team_rank"),
            "match_rank": profile.get("match_rank"),
            "summary_statistics": summary,
            "success_rates": success,
            "detailed_statistics": pairs,
            "team_table": profile.get("team_table", []),
            "heatmap_png_base64": _b64(heatmap),
            "ball_touches_png_base64": _b64(touches),
            "source_metadata": {"match_profile_url": match_data["match_url"]},
        }

    @staticmethod
    def _extract_match_table_stats(page, match_id):
        links = page.locator(f'a[href*="/matches/{match_id}"]')
        for index in range(links.count()):
            row = links.nth(index).locator('xpath=ancestor::*[@role="row"][1]')
            if not row.count():
                continue
            cells = row.locator('[role="bodycell"], [role="cell"]')
            if cells.count() < 5:
                continue
            table = row.locator('xpath=ancestor::*[@role="table"][1]')
            headers = table.locator('[role="headercell"], [role="columnheader"]')
            labels = [_clean_label(headers.nth(i).inner_text()) for i in range(headers.count())]
            values = [_clean_label(cells.nth(i).inner_text()) for i in range(cells.count())]
            return {
                label: value
                for label, value in zip(labels, values)
                if label and value and value != "–"
            }
        return {}

    @staticmethod
    def _extract_label_values(container):
        rows = container.locator('li, [role="row"]')
        result = {}
        for index in range(rows.count()):
            row = rows.nth(index)
            try:
                parsed = row.evaluate(
                    r"""
                    (node) => {
                      const text = (item) => item ? item.textContent.replace(/\s+/g, ' ').trim() : '';
                      const label = text(node.querySelector('[class*="ParamName"], [class*="StatName"], [role="rowheader"]'));
                      const value = text(node.querySelector('[class*="ParamValueMain"], [class*="StatValue"], [role="bodycell"], [role="cell"]'));
                      return {label, value};
                    }
                    """
                )
                if parsed["label"] and parsed["value"]:
                    result[_clean_label(parsed["label"])] = _clean_label(parsed["value"])
            except Exception:
                continue
        return result

    @staticmethod
    def _capture_map_in_container(container, label):
        try:
            button = container.get_by_text(label, exact=True).first
            button.click()
            canvas = container.locator('[class*="MapFieldWrapper"] canvas').first
            canvas.wait_for(state="visible", timeout=5000)
            return container.locator('[class*="MapFieldWrapper"]').first.screenshot(type="png")
        except Exception:
            return b""

    def _read_match_profile(self, context, match_url, player):
        page = context.new_page()
        try:
            page.goto(match_url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            sportsbase_id = PLAYER_ID_RE.search(player["sportsbase_url"])
            selector = (
                f'a[href*="/players/{sportsbase_id.group(1)}"]'
                if sportsbase_id
                else f'a:has-text("{player["name"]}")'
            )
            player_link = page.locator(selector).first
            player_link.wait_for(timeout=15000)
            team_block = player_link.locator(
                'xpath=ancestor::*[contains(@class,"BlockWrapper")][1]'
            )
            if not team_block.count():
                team_block = page.locator("body")
            team_name = _clean_label(
                team_block.locator('[class*="BlockTitle"]').first.inner_text()
            ) if team_block.locator('[class*="BlockTitle"]').count() else ""
            table = team_block.locator('[role="table"]').first
            if not table.count():
                table = team_block
            parsed = table.evaluate(
                r"""
                (root) => {
                  const text = (node) => node ? node.textContent.replace(/\s+/g, ' ').trim() : '';
                  const rows = [...root.querySelectorAll('[role="row"]')];
                  return rows.map((row) => ({
                    headers: [...row.querySelectorAll('[role="headercell"], [role="columnheader"]')].map(text),
                    cells: [...row.querySelectorAll('[role="bodycell"], [role="cell"]')].map(text),
                    playerName: text(row.querySelector('a[href*="/players/"]')),
                    playerHref: row.querySelector('a[href*="/players/"]')?.getAttribute('href') || '',
                  }));
                }
                """
            )
            all_rows = page.evaluate(
                r"""
                () => [...document.querySelectorAll('a[href*="/players/"]')].map((link) => {
                  const row = link.closest('[role="row"]');
                  const cells = row ? [...row.querySelectorAll('[role="bodycell"], [role="cell"]')].map(
                    (node) => node.textContent.replace(/\s+/g, ' ').trim()
                  ) : [];
                  return {playerHref: link.getAttribute('href') || '', cells};
                })
                """
            )
            return self._normalize_team_table(
                parsed,
                sportsbase_id.group(1) if sportsbase_id else "",
                team_name,
                all_rows=all_rows,
            )
        finally:
            page.close()

    @staticmethod
    def _normalize_team_table(rows, player_id, team_name, all_rows=None):
        headers = next((row["headers"] for row in rows if row.get("headers")), [])
        table = []
        current = None
        for row in rows:
            if not row.get("playerName"):
                continue
            cells = row.get("cells", [])
            mapped = dict(zip(headers, cells)) if headers else {}
            index_value = _safe_int(mapped.get("Index") or (cells[1] if len(cells) > 1 else None))
            item = {
                "rank": len(table) + 1,
                "player_name": row["playerName"],
                "index": index_value,
                "position": mapped.get("Pos") or mapped.get("Position") or (cells[2] if len(cells) > 2 else ""),
                "minutes": _safe_int(mapped.get("Min") or mapped.get("Minutes") or (cells[3] if len(cells) > 3 else None)),
                "is_current_player": f"/players/{player_id}" in row.get("playerHref", ""),
            }
            table.append(item)
            if item["is_current_player"]:
                current = item
        ranked = sorted(
            [item for item in table if item["index"] is not None],
            key=lambda item: item["index"],
            reverse=True,
        )
        team_rank = (
            next((index + 1 for index, item in enumerate(ranked) if item["is_current_player"]), None)
            if current
            else None
        )
        match_indexes = []
        for row in all_rows or []:
            cells = row.get("cells", [])
            index_value = _safe_int(cells[1] if len(cells) > 1 else None)
            if index_value is not None:
                match_indexes.append(
                    {
                        "index": index_value,
                        "is_current_player": f"/players/{player_id}" in row.get("playerHref", ""),
                    }
                )
        if not match_indexes:
            match_indexes = ranked
        match_indexes.sort(key=lambda item: item["index"], reverse=True)
        match_rank = next(
            (index + 1 for index, item in enumerate(match_indexes) if item["is_current_player"]),
            None,
        )
        return {
            "team_name": team_name,
            "team_table": table,
            "index": current.get("index") if current else None,
            "position": current.get("position") if current else "",
            "minutes_played": current.get("minutes") if current else None,
            "team_rank": team_rank,
            "match_rank": match_rank,
        }

    def _generate_and_deliver_actions(self, *, page, job, player_root, downloads_dir, queue):
        if not queue:
            return
        generated = []
        generated_matches = []
        for match_data, match_item in queue:
            try:
                popup = self.automation.click_all_players_actions_for_match(
                    page,
                    match_item,
                    match_data["source_metadata"]["list_position"] - 1,
                )
                title, _confirmed, _cancelled = self.automation.generate_download_in_popup(popup)
                generated.append(title)
                generated_matches.append((match_data, title))
                match_data["actions_state"] = "generating"
                popup.close()
            except Exception as exc:
                match_data["actions_state"] = "failed"
                match_data["delivery_error"] = str(exc)

        if not generated:
            return
        files = self.automation.download_ready_videos(
            page,
            job["player"]["name"],
            downloads_dir,
            generated_match_titles=generated,
            max_downloads=len(generated),
        )
        remaining_files = [Path(value) for value in files]
        downloaded_ids = set()
        for match_data, generated_title in generated_matches:
            safe_title = self.automation.sanitize_filename(generated_title).lower()
            source = next(
                (value for value in remaining_files if safe_title and safe_title in value.name.lower()),
                remaining_files[0] if remaining_files else None,
            )
            if not source:
                continue
            remaining_files.remove(source)
            source = Path(source)
            match_folder = player_root / f"match_{match_data['sportsbase_match_id']}"
            match_folder.mkdir(parents=True, exist_ok=True)
            destination = match_folder / source.name
            shutil.move(str(source), destination)
            match_data.update(
                {
                    "actions_state": "downloaded",
                    "local_folder_key": str(match_folder.relative_to(self.storage_root)),
                    "all_actions_filename": destination.name,
                    "all_actions_downloaded_at": _now_iso(),
                }
            )
            if job.get("email_delivery_enabled"):
                sent, error = send_all_actions_email(
                    recipient=job["player"].get("email"),
                    player_name=job["player"]["name"],
                    match_label=f"{match_data['home_team']} - {match_data['away_team']}",
                    video_path=destination,
                )
                if sent:
                    match_data["actions_state"] = "emailed"
                    match_data["all_actions_emailed_at"] = _now_iso()
                else:
                    match_data["delivery_error"] = error
            downloaded_ids.add(match_data["sportsbase_match_id"])

        for match_data, _generated_title in generated_matches:
            if match_data["sportsbase_match_id"] not in downloaded_ids:
                match_data["actions_state"] = "generating"
                match_data["delivery_error"] = "La génération SportsBase est encore en cours ; l’agent reprendra ce match."
