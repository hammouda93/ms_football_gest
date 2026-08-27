import base64
import json
import os
import re
import shutil
import time
import traceback
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

from gestion_joueurs.sportsbase_playwright import SportsBaseAutomation
from sportsbase_data.xlsx_statistics import read_players_statistics_xlsx

SPORTSBASE_ROOT = "https://football.sportsbase.world"
MATCH_ID_RE = re.compile(r"/matches/(\d+)")
PLAYER_ID_RE = re.compile(r"/players/(\d+)")
DATE_RE = re.compile(
    r"(?<!\d)(\d{2})[./-](\d{2})[./-](\d{4}|\d{2})(?!\d)"
)
SCORE_RE = re.compile(r"\b(\d+)\s*[:–-]\s*(\d+)\b")
SCRAPER_BUILD = "season-kpis-radar-v11-analysis-data-20260827"


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
    if len(year) == 2:
        year = f"20{year}"
    return f"{year}-{month}-{day}"


def _clean_label(value):
    return re.sub(r"\s+", " ", str(value or "")).strip(" :\n\t")


class SportsBaseSubscriptionScraper:
    """Read subscription data while reusing the project's proven SportsBase workflow."""

    def __init__(self, storage_root):
        self.storage_root = Path(storage_root)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.automation = SportsBaseAutomation(base_download_dir=str(self.storage_root))
        self.profile_dir = Path(
            os.getenv(
                "SPORTSBASE_SUBSCRIPTION_PROFILE_DIR",
                os.getenv(
                    "SPORTSBASE_PROFILE_DIR",
                    r"D:\SportsBase_Playwright_Profile",
                ),
            )
        )
        self.browser_channel = (
            os.getenv("SPORTSBASE_BROWSER_CHANNEL", "chrome").strip() or "chrome"
        )

    def _launch_persistent_context(self, playwright, downloads_dir):
        """Open the same persistent Chrome profile used by the legacy agent."""
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        downloads_dir.mkdir(parents=True, exist_ok=True)
        print(
            "[SPORTSBASE] Ouverture Google Chrome avec profil persistant : "
            f"{self.profile_dir}"
        )
        print(f"[SPORTSBASE] Canal navigateur : {self.browser_channel}")
        try:
            return playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                channel=self.browser_channel,
                headless=self.automation.headless,
                accept_downloads=True,
                downloads_path=str(downloads_dir),
                no_viewport=True,
                args=["--start-maximized"],
            )
        except Exception as exc:
            message = str(exc)
            if "ProcessSingleton" in message or "profile" in message.lower():
                raise RuntimeError(
                    "Le profil Chrome SportsBase est déjà utilisé. Fermez Chrome et "
                    "arrêtez automation_agent.py avant de lancer local_agent.py."
                ) from exc
            raise

    def run(self, job):
        print(f"[SPORTSBASE] Version scraper : {SCRAPER_BUILD}")
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
            context = None
            try:
                context = self._launch_persistent_context(playwright, downloads_dir)
                page = context.new_page()
                self.automation.ensure_logged_in_and_open_player(
                    page, player["sportsbase_url"]
                )
                if job["job_type"] in {"full", "profile"}:
                    result["profile"] = self._read_profile(page, job)

                if job["job_type"] in {"full", "profile", "matches"}:
                    self.automation.open_player_statistics(page)
                    season_data = self._read_season_statistics(page)
                    self._season_table_headers = season_data.get(
                        "season_table_headers", []
                    )
                    self._season_match_rows = {
                        str(item.get("sportsbase_match_id") or ""): item.get(
                            "values", []
                        )
                        for item in season_data.get("season_match_rows", [])
                        if item.get("sportsbase_match_id")
                    }
                    if result["profile"]:
                        result["profile"].update(season_data)
                        self._write_season_artifacts(
                            player_root=player_root,
                            profile=result["profile"],
                        )

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
                result["status"] = (
                    "partial" if result["profile"] or result["matches"] else "failed"
                )
                result["error"] = str(exc)
                print(f"[SPORTSBASE][ERREUR SCRAPER] {exc}")
                traceback.print_exc()
            finally:
                if context is not None:
                    try:
                        context.close()
                    except Exception:
                        pass

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
              const cleanText = (node) => {
                if (!node) return '';
                const clone = node.cloneNode(true);
                clone.querySelectorAll('[class*="Tooltip"], [role="tooltip"]').forEach(
                  (item) => item.remove()
                );
                return text(clone);
              };
              const headerText = (node) => {
                if (!node) return '';
                const tooltip = node.querySelector('[class*="Tooltip"] [class*="LexicWrapper"]');
                if (tooltip) return text(tooltip);
                const labels = [...node.querySelectorAll('[class*="LexicWrapper"]')].map(text).filter(Boolean);
                return labels.length ? labels[labels.length - 1] : text(node);
              };
              const passport = {};
              document.querySelectorAll('[class*="PassportItem"]').forEach((row) => {
                const key = cleanText(row.querySelector('[class*="ParamName"]'));
                const values = [...row.querySelectorAll('[class*="ParamValueContainer"]')].map((node) => ({
                  main: cleanText(node.querySelector('[class*="ParamValueMain"]')),
                  second: cleanText(node.querySelector('[class*="ParamValueSecond"]')),
                  full: cleanText(node),
                  tooltip: text(node.querySelector('[class*="Tooltip"]')),
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
            normalized_label = _clean_label(label).casefold()
            rows = next(
                (
                    values
                    for key, values in passport.items()
                    if _clean_label(key).casefold() == normalized_label
                    or _clean_label(key).casefold().startswith(normalized_label)
                ),
                [],
            )
            return rows[0].get("main", "") if rows else ""

        positions = []
        for item in passport.get("Position", []):
            percent = _safe_int(item.get("second"))
            positions.append(
                {
                    "code": item.get("main", ""),
                    "name": item.get("tooltip") or item.get("main", ""),
                    "percent": percent,
                }
            )

        player_id = PLAYER_ID_RE.search(page.url)
        club_id = re.search(r"/teams/(\d+)", raw.get("clubHref", ""))
        heatmap = self._capture_named_map(page, "Heatmap")
        touches = self._capture_named_map(page, "Ball touches map")
        ball_touches_points = list(
            getattr(self, "_last_ball_touches_points", [])
        )
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
            "time_on_field_percent": _safe_int(
                first("Time on the field, %") or first("Time on the field")
            ),
            "positions": positions,
            "radar_metrics": radar.get("metrics", []),
            "radar_png_base64": _b64(radar.get("png", b"")),
            "heatmap_png_base64": _b64(heatmap),
            "ball_touches_png_base64": _b64(touches),
            "source_metadata": {
                "profile_url": page.url,
                "captured_at": _now_iso(),
                "ball_touches_scope": "last_5_matches",
                "ball_touches_count": len(ball_touches_points),
                "ball_touches_points": ball_touches_points,
            },
        }

    def _capture_named_map(self, page, label):
        return self._capture_map_field(page, page, label)

    def _capture_radar(self, page):
        """Capture the real performance radar SVG and retain normalized series data."""
        try:
            radar_tab = page.get_by_text("Radar", exact=True).first
            radar_tab.scroll_into_view_if_needed(timeout=10_000)
            radar_tab.click(timeout=10_000)
            page.wait_for_timeout(900)
            candidates = page.locator('svg[width][height]')
            best = None
            best_score = 0
            for index in range(candidates.count()):
                candidate = candidates.nth(index)
                box = candidate.bounding_box()
                if not box or box["width"] < 300 or box["height"] < 300:
                    continue
                signature = candidate.evaluate(
                    r"""
                    (svg) => ({
                      labels: [...svg.querySelectorAll('text')].filter((node) =>
                        Number(node.getAttribute('font-size') || 0) >= 10
                      ).length,
                      points: svg.querySelectorAll('circle[cx][cy]').length,
                      paths: svg.querySelectorAll('path[d]').length,
                      text: (svg.textContent || '').replace(/\s+/g, ' ').trim(),
                    })
                    """
                )
                radar_words = (
                    "chances",
                    "shots",
                    "dribbling",
                    "defensive",
                    "interceptions",
                )
                semantic_hits = sum(
                    word in signature.get("text", "").casefold()
                    for word in radar_words
                )
                score = (
                    box["width"] * box["height"]
                    + signature.get("labels", 0) * 12_000
                    + signature.get("points", 0) * 2_000
                    + semantic_hits * 100_000
                )
                if semantic_hits >= 2 and signature.get("paths", 0) >= 2 and score > best_score:
                    best, best_score = candidate, score
            if best is None:
                print("[SPORTSBASE][WARN] SVG du radar de performance non détecté.")
                return {"png": b"", "metrics": []}

            best.scroll_into_view_if_needed(timeout=10_000)
            page.wait_for_timeout(300)
            metrics = best.evaluate(
                r"""
                (svg) => {
                  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
                  const labels = [...svg.querySelectorAll('text')]
                    .filter((node) => Number(node.getAttribute('font-size') || 0) >= 10)
                    .map((node) => clean([...node.querySelectorAll('tspan')]
                      .map((item) => item.textContent).join(' ') || node.textContent))
                    .filter(Boolean);
                  const circles = [...svg.querySelectorAll('circle[cx][cy]')];
                  const byColour = (rgb) => circles.filter((node) => {
                    const stroke = clean(
                      node.getAttribute('stroke') || getComputedStyle(node).stroke
                    ).replace(/\s+/g, '');
                    return stroke.includes(rgb);
                  });
                  const player = byColour('11,69,110');
                  const average = byColour('178,0,0');
                  const viewBox = svg.viewBox && svg.viewBox.baseVal;
                  const width = viewBox?.width || Number(svg.getAttribute('width')) || 540;
                  const height = viewBox?.height || Number(svg.getAttribute('height')) || 540;
                  const centreX = (viewBox?.x || 0) + width / 2;
                  const centreY = (viewBox?.y || 0) + height / 2;
                  const chartRadius = Math.min(width, height) * 0.444444;
                  const normalizedRadius = (node) => {
                    if (!node) return 0;
                    const point = svg.createSVGPoint();
                    point.x = Number(node.getAttribute('cx'));
                    point.y = Number(node.getAttribute('cy'));
                    const absolute = point.matrixTransform(node.getCTM());
                    const dx = absolute.x - centreX;
                    const dy = absolute.y - centreY;
                    return Math.round(Math.max(0, Math.min(100,
                      Math.hypot(dx, dy) / chartRadius * 100
                    )) * 10) / 10;
                  };
                  const count = Math.min(labels.length, player.length, average.length);
                  return labels.slice(0, count).map((label, index) => ({
                    name: label,
                    label,
                    value: normalizedRadius(player[index]),
                    player: normalizedRadius(player[index]),
                    average: normalizedRadius(average[index]),
                  }));
                }
                """
            )
            print(
                "[SPORTSBASE] Radar exact détecté — "
                f"{len(metrics)} axe(s) — capture SVG complète."
            )
            return {"png": best.screenshot(type="png"), "metrics": metrics}
        except Exception as exc:
            print(f"[SPORTSBASE][WARN] Capture radar impossible : {exc}")
            return {"png": b"", "metrics": []}

    def _read_season_statistics(self, page):
        data = page.evaluate(
            r"""
            () => {
              const text = (node) => node ? node.textContent.replace(/\s+/g, ' ').trim() : '';
              const cleanValue = (node) => {
                if (!node) return '';
                const clone = node.cloneNode(true);
                clone.querySelectorAll('[class*="Tooltip"], [role="tooltip"]').forEach((item) => item.remove());
                return text(clone);
              };
              const tooltipLabel = (node) => text(
                node?.querySelector('[class*="Tooltip"] [class*="LexicWrapper"], [class*="Tooltip"], [role="tooltip"]')
              );
              const headerText = (node) => {
                if (!node) return '';
                const tooltip = tooltipLabel(node);
                if (tooltip) return tooltip;
                const labels = [...node.querySelectorAll('[class*="LexicWrapper"]')].map(text).filter(Boolean);
                return labels.length ? labels[labels.length - 1] : text(node);
              };
              const addRows = (block, result) => {
                if (!block) return;
                block.querySelectorAll('li').forEach((row) => {
                  const label = text(row.querySelector(
                    '[class*="StatsName"], [class*="StatName"], [class*="ParamName"]'
                  ));
                  const values = [...row.querySelectorAll('[class*="StatValue"]')];
                  if (!label || !values.length) return;
                  const primary = cleanValue(values[0]);
                  if (primary) result[label] = primary;
                  values.slice(1).forEach((valueNode) => {
                    const secondaryLabel = tooltipLabel(valueNode);
                    const secondaryValue = cleanValue(valueNode);
                    if (secondaryLabel && secondaryValue) {
                      result[secondaryLabel] = secondaryValue;
                    }
                  });
                });
              };

              const season = {};
              const seasonBlocks = [
                ...document.querySelectorAll(
                  '[class*="PlayerStatsBody"], ul[class*="PlayerStats"], ul[class*="LeftStatBlock"], [class*="SeasonStats"]'
                )
              ];
              seasonBlocks.forEach((block) => addRows(block, season));

              const averages = {};
              document.querySelectorAll('[class*="AverageStats"], [class*="Averages"]').forEach(
                (block) => addRows(block, averages)
              );
              let bestTable = {headers: [], rows: []};
              document.querySelectorAll('[role="table"]').forEach((table) => {
                const headers = [...table.querySelectorAll('[role="headercell"], [role="columnheader"]')].map(headerText);
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
            previous_xlsx = str(
                previous.get("players_statistics_xlsx") or ""
            ).strip()
            previous_folder_key = str(
                previous.get("local_folder_key") or ""
            ).strip()
            if previous_folder_key:
                previous_xlsx_path = (
                    self.storage_root / previous_folder_key / previous_xlsx
                )
            else:
                previous_xlsx_path = self._match_folder(
                    player_root=player_root,
                    season=job.get("season", ""),
                    match_data=match_data,
                ) / previous_xlsx
            xlsx_is_local = bool(
                previous_xlsx and self._valid_xlsx(previous_xlsx_path)
            )
            if previous.get("complete") and (
                job["job_type"] == "all_actions" or xlsx_is_local
            ):
                continue
            match_item = self._match_item(page, match_data["sportsbase_match_id"])
            if job["job_type"] != "all_actions":
                try:
                    match_data["stats"] = self._read_match_details(
                        page,
                        context,
                        match_item,
                        match_data,
                        job,
                        player_root=player_root,
                    )
                    match_data["sync_state"] = "synced"
                except Exception as exc:
                    match_data["sync_state"] = "partial"
                    match_data.setdefault("source_metadata", {})["stats_error"] = str(exc)
            else:
                match_data["sync_state"] = previous.get("sync_state", "discovered")

            self._write_match_artifacts(
                player_root=player_root,
                season=job.get("season", ""),
                match_data=match_data,
            )

            if not job.get("all_actions_enabled"):
                match_data["actions_state"] = "not_requested"
            elif previous.get("actions_state") in {"downloaded", "emailed"}:
                # L’e-mail final est envoyé une seule fois par Django, lorsque le
                # rapport (et, si activé, YouTube) est prêt. L’agent local conserve
                # uniquement le fichier vidéo et ne l’envoie plus en pièce jointe.
                match_data["actions_state"] = previous["actions_state"]
                for field in (
                    "local_folder_key",
                    "all_actions_filename",
                    "all_actions_downloaded_at",
                    "all_actions_emailed_at",
                    "delivery_error",
                ):
                    if previous.get(field) not in (None, ""):
                        match_data[field] = previous[field]
            elif previous.get("actions_state") == "generating":
                # Une génération a déjà été demandée lors d'un passage précédent.
                # On reprend uniquement My Videos, sans créer de doublon SportsBase.
                match_data["actions_state"] = "generating"
                generation_queue.append((match_data, match_item, False))
            else:
                match_data["actions_state"] = "queued"
                generation_queue.append((match_data, match_item, True))
            output.append(match_data)

        try:
            self._generate_and_deliver_actions(
                page=page,
                job=job,
                player_root=player_root,
                downloads_dir=downloads_dir,
                queue=generation_queue,
            )
        except Exception as exc:
            # Les statistiques déjà collectées doivent toujours être envoyées à Django.
            print(f"[SPORTSBASE][ERREUR ALL ACTIONS] {exc}")
            traceback.print_exc()
            for match_data, _match_item, _should_generate in generation_queue:
                if match_data.get("actions_state") in {"queued", "generating"}:
                    match_data["actions_state"] = "generating"
                    match_data["delivery_error"] = (
                        "Statistiques enregistrées. Téléchargement All Actions à reprendre : "
                        f"{exc}"
                    )
        for match_data in output:
            self._write_match_artifacts(
                player_root=player_root,
                season=job.get("season", ""),
                match_data=match_data,
            )
        return output

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
                    score: text(row.querySelector('[class*="Score-sc-jnav9l-8"], [class*="Score-sc-ql8gpc-3"]')),
                    referee: text(row.querySelector('[class*="RefereeName"]')),
                  };
                }
                """
            )
            text = raw.get("text", "")
            teams = raw.get("teams", [])
            score = SCORE_RE.search(raw.get("score", "")) or SCORE_RE.search(text)
            row = {
                "sportsbase_match_id": id_match.group(1),
                "match_date": _iso_date(text),
                "competition": raw.get("competition", ""),
                "week": raw.get("week", ""),
                "referee": raw.get("referee", ""),
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

    def _read_match_details(
        self, page, context, match_item, match_data, job, *, player_root
    ):
        details_scope = self._open_match_details_scope(
            page,
            match_item,
            match_data["sportsbase_match_id"],
        )
        pairs = self._season_match_statistics(
            match_data["sportsbase_match_id"]
        )
        pairs.update(self._extract_label_values(details_scope))
        pairs.update(
            self._extract_match_table_stats(
                page, match_data["sportsbase_match_id"]
            )
        )
        success = {key: value for key, value in pairs.items() if "%" in value or "%" in key}
        summary = {key: value for key, value in pairs.items() if key not in success}
        heatmap = self._capture_map_in_container(page, details_scope, "Heatmap")
        touches = self._capture_map_in_container(
            page, details_scope, "Ball touches map"
        )
        ball_touches_points = list(
            getattr(self, "_last_ball_touches_points", [])
        )
        profile = self._read_match_profile(
            context,
            match_data["match_url"],
            job["player"],
            match_data,
            statistics_dir=self._match_folder(
                player_root=player_root,
                season=job.get("season", ""),
                match_data=match_data,
            ),
        )
        for field in ("match_date", "home_score", "away_score", "referee"):
            value = profile.get(field)
            if value not in (None, ""):
                match_data[field] = value
        if profile.get("stadium"):
            match_data.setdefault("source_metadata", {})["stadium"] = profile[
                "stadium"
            ]
        position_percentages = self._extract_position_percentages(details_scope)
        return {
            "team_name": profile.get("team_name") or job["player"].get("club", ""),
            "position": profile.get("position") or match_data.get("lineup", ""),
            "position_percentages": position_percentages,
            "minutes_played": profile.get("minutes_played"),
            "index": profile.get("index"),
            "team_rank": profile.get("team_rank"),
            "match_rank": profile.get("match_rank"),
            "summary_statistics": summary,
            "success_rates": success,
            "detailed_statistics": pairs,
            "team_table": profile.get("team_table", []),
            "players_statistics_headers": profile.get(
                "players_statistics_headers", []
            ),
            "players_statistics_rows": profile.get("players_statistics_rows", []),
            "heatmap_png_base64": _b64(heatmap),
            "ball_touches_png_base64": _b64(touches),
            "source_metadata": {
                "match_profile_url": match_data["match_url"],
                "stadium": profile.get("stadium", ""),
                "referee": profile.get("referee", ""),
                "players_statistics_url": profile.get(
                    "players_statistics_url", ""
                ),
                "players_statistics_xlsx": profile.get(
                    "players_statistics_xlsx", ""
                ),
                "players_statistics_downloaded_at": profile.get(
                    "players_statistics_downloaded_at", ""
                ),
                "players_statistics_error": profile.get(
                    "players_statistics_error", ""
                ),
                "ball_touches_scope": "match",
                "ball_touches_count": len(ball_touches_points),
                "ball_touches_points": ball_touches_points,
            },
        }

    @staticmethod
    def _open_match_details_scope(page, match_item, match_id):
        def visible_scope(locator):
            for index in range(locator.count()):
                candidate = locator.nth(index)
                try:
                    if (
                        candidate.is_visible()
                        and candidate.locator('[class*="MapFieldWrapper"]').count()
                        and candidate.locator('[class*="PlayerStatsContainer"]').count()
                    ):
                        return candidate
                except Exception:
                    continue
            return None

        descendant = visible_scope(
            match_item.locator('[class*="StatsWrapper"]')
        )
        if descendant is not None:
            print(
                f"[SPORTSBASE] Détails match {match_id} déjà ouverts dans la ligne"
            )
            return descendant

        existing_following = visible_scope(
            match_item.locator(
                'xpath=following::*[contains(@class,"StatsWrapper")][1]'
            )
        )
        if existing_following is not None:
            print(
                f"[SPORTSBASE] Détails match {match_id} déjà ouverts hors de la ligne"
            )
            return existing_following

        existing_wrappers = page.locator('[class*="StatsWrapper"]')
        existing_count = existing_wrappers.count()
        more = match_item.get_by_text("More details", exact=False).first
        if not more.count():
            raise RuntimeError(
                f"Bouton More details introuvable pour le match {match_id}"
            )
        more.scroll_into_view_if_needed(timeout=10000)
        more.click(timeout=10000)

        for _attempt in range(40):
            descendant = visible_scope(
                match_item.locator('[class*="StatsWrapper"]')
            )
            if descendant is not None:
                print(
                    f"[SPORTSBASE] Détails match {match_id} ouverts dans la ligne"
                )
                return descendant

            wrappers = page.locator('[class*="StatsWrapper"]')
            if wrappers.count() > existing_count:
                for index in range(existing_count, wrappers.count()):
                    candidate = visible_scope(wrappers.nth(index))
                    if candidate is not None:
                        print(
                            f"[SPORTSBASE] Détails match {match_id} ouverts hors de la ligne"
                        )
                        return candidate

            following = visible_scope(
                match_item.locator(
                    'xpath=following::*[contains(@class,"StatsWrapper")][1]'
                )
            )
            if following is not None:
                print(
                    f"[SPORTSBASE] Détails match {match_id} associés par position DOM"
                )
                return following
            page.wait_for_timeout(250)

        raise RuntimeError(
            f"Le bloc Player match stats du match {match_id} ne s’est pas ouvert"
        )

    def _season_match_statistics(self, match_id):
        headers = getattr(self, "_season_table_headers", [])
        values = getattr(self, "_season_match_rows", {}).get(str(match_id), [])
        return {
            _clean_label(header): _clean_label(value)
            for header, value in zip(headers, values)
            if _clean_label(header)
            and _clean_label(value)
            and _clean_label(value) not in {"–", "-"}
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
            labels = []
            for header_index in range(headers.count()):
                label = headers.nth(header_index).evaluate(
                    r"""
                    (node) => {
                      const text = (item) => item ? item.textContent.replace(/\s+/g, ' ').trim() : '';
                      const tooltip = node.querySelector('[class*="Tooltip"] [class*="LexicWrapper"]');
                      if (tooltip) return text(tooltip);
                      const labels = [...node.querySelectorAll('[class*="LexicWrapper"]')].map(text).filter(Boolean);
                      return labels.length ? labels[labels.length - 1] : text(node);
                    }
                    """
                )
                labels.append(_clean_label(label))
            values = [_clean_label(cells.nth(i).inner_text()) for i in range(cells.count())]
            return {
                label: value
                for label, value in zip(labels, values)
                if label and value and value != "–"
            }
        return {}

    @staticmethod
    def _extract_label_values(container):
        rows = container.locator(
            'li[class*="PlayerStatsItem"], li[class*="PlayerStatsItem-sc-98ruxp-0"]'
        )
        result = {}
        for index in range(rows.count()):
            row = rows.nth(index)
            try:
                parsed = row.evaluate(
                    r"""
                    (node) => {
                      const text = (item) => item ? item.textContent.replace(/\s+/g, ' ').trim() : '';
                      const directText = (item) => {
                        if (!item) return '';
                        const clone = item.cloneNode(true);
                        clone.querySelectorAll('[class*="Tooltip"]').forEach((tooltip) => tooltip.remove());
                        return text(clone);
                      };
                      const label = directText(node.querySelector('[class*="PlayerStatsName"]'));
                      const values = [...node.querySelectorAll('[class*="PlayerStatsValue-sc-"]')].map((item) => ({
                        value: directText(item),
                        semanticLabel: text(item.querySelector('[class*="Tooltip"] [class*="LexicWrapper"], [class*="Tooltip"]')),
                      }));
                      return {label, values};
                    }
                    """
                )
                label = _clean_label(parsed.get("label"))
                values = parsed.get("values") or []
                if label and values:
                    primary = _clean_label(values[0].get("value"))
                    if primary:
                        result[label] = primary
                for value in values[1:]:
                    semantic_label = _clean_label(value.get("semanticLabel"))
                    semantic_value = _clean_label(value.get("value"))
                    if semantic_label and semantic_value:
                        result[semantic_label] = semantic_value
            except Exception:
                continue
        return result

    @staticmethod
    def _extract_position_percentages(container):
        try:
            rows = container.locator('[class*="MapTitleValueContainer"]')
            values = []
            for index in range(rows.count()):
                parsed = rows.nth(index).evaluate(
                    r"""
                    (node) => {
                      const text = (item) => item ? item.textContent.replace(/\s+/g, ' ').trim() : '';
                      const main = node.querySelector('[class*="MapTitleValueMain"]');
                      const clone = main ? main.cloneNode(true) : null;
                      if (clone) clone.querySelectorAll('[class*="Tooltip"]').forEach((item) => item.remove());
                      return {
                        code: text(clone),
                        name: text(main?.querySelector('[class*="Tooltip"]')),
                        percent: text(node.querySelector('[class*="MapTitleValueSecond"]')),
                      };
                    }
                    """
                )
                code = _clean_label(parsed.get("code"))
                if code:
                    values.append(
                        {
                            "code": code,
                            "name": _clean_label(parsed.get("name")) or code,
                            "percent": _safe_int(parsed.get("percent")),
                        }
                    )
            return values
        except Exception:
            return []

    def _capture_map_field(self, page, scope, label):
        try:
            if label == "Ball touches map":
                self._last_ball_touches_points = []
            button = scope.get_by_role("button", name=label, exact=True).first
            if not button.count():
                button = scope.get_by_text(label, exact=True).first
            if not button.count():
                raise RuntimeError(f"Bouton {label} absent du bloc de statistiques")
            button.scroll_into_view_if_needed()
            button.click()
            wrapper = button.locator(
                'xpath=ancestor::*[contains(@class,"MapFieldWrapper")][1]'
            )
            if not wrapper.count():
                wrapper = scope.locator('[class*="MapFieldWrapper"]').first
            wrapper.wait_for(state="visible", timeout=5000)
            field = wrapper.locator('div[class*="Field-sc-12b02qw-2"]').first
            if not field.count():
                field = wrapper.locator('[class*="Field-"]').first
            field.wait_for(state="visible", timeout=5000)
            if not self._wait_for_map_mode(page, button, field, label):
                raise RuntimeError(
                    f"L’onglet {label} n’a pas produit le DOM attendu"
                )
            page.wait_for_timeout(1500)
            box = field.bounding_box()
            if not box or box["width"] < 200 or box["height"] < 100:
                raise RuntimeError(f"Terrain {label} trop petit ou invisible")
            state = field.evaluate(
                r"""
                (node) => ({
                  width: Math.round(node.getBoundingClientRect().width),
                  height: Math.round(node.getBoundingClientRect().height),
                  canvases: node.querySelectorAll('canvas').length,
                  points: node.querySelectorAll('[class*="Point-sc-"]').length,
                  mapContainers: node.querySelectorAll('[class*="MapContainer"]').length,
                  background: getComputedStyle(node).backgroundImage,
                })
                """
            )
            print(
                f"[SPORTSBASE] Carte {label} — "
                f"{state.get('width')}x{state.get('height')} — "
                f"canvas={state.get('canvases')} — points={state.get('points')}"
            )

            if label == "Heatmap" and field.locator("canvas").count():
                content = self._read_canvas_png(
                    page, field.locator("canvas").first
                )
                if content:
                    return content

            if label == "Ball touches map":
                touch_data = self._read_ball_touch_data(field)
                self._last_ball_touches_points = touch_data.get("points", [])
                content = self._render_ball_touches_overlay(touch_data)
                if content:
                    print(
                        "[SPORTSBASE] Ball touches reconstruite depuis "
                        f"{len(self._last_ball_touches_points)} coordonnée(s)"
                    )
                    return content
            else:
                content = self._capture_viewport_crop(page, field)
                if content:
                    return content
            raise RuntimeError(
                "SportsBase affiche encore un terrain vide après le rendu"
            )
        except Exception as exc:
            print(f"[SPORTSBASE][WARN] Capture {label} impossible : {exc}")
            return b""

    @staticmethod
    def _wait_for_map_mode(page, button, field, label):
        for click_attempt in range(3):
            for _attempt in range(20):
                canvas_count = field.locator("canvas").count()
                map_count = field.locator('[class*="MapContainer"]').count()
                point_count = field.locator('[class*="Point-sc-"]').count()
                if label == "Heatmap" and canvas_count:
                    return True
                if label == "Ball touches map" and map_count and point_count:
                    return True
                page.wait_for_timeout(250)
            if click_attempt < 2:
                button.evaluate("node => node.click()")
                page.wait_for_timeout(750)
        return False

    @staticmethod
    def _read_ball_touch_data(field):
        return field.evaluate(
            r"""
            (node) => {
              const container = node.querySelector('[class*="MapContainer"]');
              if (!container) return {width: 0, height: 0, points: []};
              const rect = container.getBoundingClientRect();
              const percent = (value) => {
                const parsed = Number.parseFloat(value || '');
                return Number.isFinite(parsed) ? parsed : null;
              };
              const points = [...container.querySelectorAll('[class*="Point-sc-"]')].map((point) => {
                const style = getComputedStyle(point);
                const pointRect = point.getBoundingClientRect();
                let left = percent(point.style.left);
                let top = percent(point.style.top);
                if (left === null && rect.width) left = ((pointRect.left - rect.left) / rect.width) * 100;
                if (top === null && rect.height) top = ((pointRect.top - rect.top) / rect.height) * 100;
                return {
                  left_pct: left,
                  top_pct: top,
                  width_px: pointRect.width || Number.parseFloat(style.width) || 6,
                  height_px: pointRect.height || Number.parseFloat(style.height) || 6,
                  color: style.backgroundColor || style.color || 'rgb(220, 35, 55)',
                };
              }).filter((point) => point.left_pct !== null && point.top_pct !== null);
              return {
                width: Math.round(rect.width) || 389,
                height: Math.round(rect.height) || 252,
                points,
              };
            }
            """
        )

    @staticmethod
    def _render_ball_touches_overlay(touch_data):
        points = touch_data.get("points") or []
        if not points:
            return b""
        width = max(200, min(_safe_int(touch_data.get("width")) or 389, 2000))
        height = max(120, min(_safe_int(touch_data.get("height")) or 252, 1400))
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image, "RGBA")
        for point in points:
            left = max(0.0, min(float(point.get("left_pct") or 0), 100.0))
            top = max(0.0, min(float(point.get("top_pct") or 0), 100.0))
            x = left * (width - 1) / 100
            y = top * (height - 1) / 100
            diameter = max(
                5.0,
                min(
                    float(point.get("width_px") or 6),
                    float(point.get("height_px") or 6),
                    16.0,
                ),
            )
            radius = diameter / 2
            color = SportsBaseSubscriptionScraper._parse_css_color(
                point.get("color")
            )
            draw.ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                fill=color,
            )
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    @staticmethod
    def _parse_css_color(value):
        numbers = [
            float(item)
            for item in re.findall(r"[\d.]+", str(value or ""))[:4]
        ]
        if len(numbers) >= 3:
            alpha = numbers[3] if len(numbers) > 3 else 1.0
            if alpha <= 1:
                alpha *= 255
            return tuple(
                max(0, min(round(channel), 255))
                for channel in (*numbers[:3], alpha)
            )
        return (220, 35, 55, 255)

    @staticmethod
    def _read_canvas_png(page, canvas):
        for _attempt in range(20):
            try:
                data_url = canvas.evaluate(
                    "node => node.toDataURL('image/png')"
                )
                if data_url and "," in data_url:
                    content = base64.b64decode(data_url.split(",", 1)[1])
                    if not SportsBaseSubscriptionScraper._png_is_blank(content):
                        print(
                            "[SPORTSBASE] Heatmap lue directement depuis le canvas"
                        )
                        return content
            except Exception:
                # Canvas protégé ou remplacé pendant le rendu React : le recadrage
                # du viewport prend ensuite le relais.
                break
            page.wait_for_timeout(500)
        return b""

    @staticmethod
    def _capture_viewport_crop(page, field):
        for _attempt in range(6):
            field.evaluate(
                "node => node.scrollIntoView({block: 'center', inline: 'center'})"
            )
            page.wait_for_timeout(800)
            box = field.bounding_box()
            if not box:
                continue
            viewport = page.evaluate(
                "() => ({width: window.innerWidth, height: window.innerHeight})"
            )
            screenshot = page.screenshot(
                type="png",
                full_page=False,
                animations="disabled",
            )
            with Image.open(BytesIO(screenshot)) as source:
                scale_x = source.width / max(viewport.get("width") or 1, 1)
                scale_y = source.height / max(viewport.get("height") or 1, 1)
                left = max(0, round(box["x"] * scale_x))
                top = max(0, round(box["y"] * scale_y))
                right = min(
                    source.width,
                    round((box["x"] + box["width"]) * scale_x),
                )
                bottom = min(
                    source.height,
                    round((box["y"] + box["height"]) * scale_y),
                )
                if right <= left or bottom <= top:
                    continue
                cropped = source.crop((left, top, right, bottom)).convert("RGB")
                output = BytesIO()
                cropped.save(output, format="PNG")
                content = output.getvalue()
            if not SportsBaseSubscriptionScraper._png_is_blank(content):
                print("[SPORTSBASE] Carte recadrée depuis le viewport Chrome")
                return content
            page.wait_for_timeout(1000)
        return b""

    @staticmethod
    def _png_is_blank(content):
        if not content:
            return True
        try:
            with Image.open(BytesIO(content)) as image:
                rgb = image.convert("RGB")
                extrema = rgb.getextrema()
                return all((maximum - minimum) <= 3 for minimum, maximum in extrema)
        except Exception:
            return True

    def _capture_map_in_container(self, page, container, label):
        return self._capture_map_field(page, container, label)

    def _read_match_profile(
        self,
        context,
        match_url,
        player,
        match_data=None,
        *,
        statistics_dir=None,
    ):
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
                  const headerText = (node) => {
                    if (!node) return '';
                    const tooltip = node.querySelector('[class*="Tooltip"] [class*="LexicWrapper"]');
                    if (tooltip) return text(tooltip);
                    const labels = [...node.querySelectorAll('[class*="LexicWrapper"]')].map(text).filter(Boolean);
                    return labels.length ? labels[labels.length - 1] : text(node);
                  };
                  const rows = [...root.querySelectorAll('[role="row"]')];
                  return rows.map((row) => ({
                    headers: [...row.querySelectorAll('[role="headercell"], [role="columnheader"]')].map(headerText),
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
            metadata = self._read_match_header_metadata(page, match_data or {})
            result = self._normalize_team_table(
                parsed,
                sportsbase_id.group(1) if sportsbase_id else "",
                team_name,
                all_rows=all_rows,
            )
            result.update(metadata)
            if statistics_dir is not None:
                result.update(
                    self._download_match_players_statistics(
                        page=page,
                        match_data=match_data or {},
                        destination_dir=statistics_dir,
                    )
                )
            return result
        finally:
            page.close()

    def _download_match_players_statistics(
        self, *, page, match_data, destination_dir
    ):
        """Download the full Players XLSX once the team ranking has been read."""
        match_id = str(match_data.get("sportsbase_match_id") or "").strip()
        if not match_id:
            match = MATCH_ID_RE.search(page.url)
            match_id = match.group(1) if match else ""
        if not match_id:
            return {
                "players_statistics_error": (
                    "Identifiant du match introuvable pour le téléchargement XLSX."
                )
            }

        destination_dir = Path(destination_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / (
            f"match_{self._file_component(match_id)}__players_statistics.xlsx"
        )
        if self._valid_xlsx(destination):
            print(
                "[SPORTSBASE] Statistiques Players XLSX déjà présentes : "
                f"{destination}"
            )
            return {
                "players_statistics_url": urljoin(
                    SPORTSBASE_ROOT, f"/matches/{match_id}/players"
                ),
                "players_statistics_xlsx": destination.name,
                **self._parse_players_statistics(destination),
            }

        players_path = f"/matches/{match_id}/players"
        players_url = urljoin(SPORTSBASE_ROOT, players_path)
        try:
            players_tab = page.locator(f'a[href="{players_path}"]').first
            if players_tab.count():
                players_tab.scroll_into_view_if_needed(timeout=10_000)
                players_tab.click(timeout=10_000)
                page.wait_for_url(f"**{players_path}*", timeout=30_000)
            else:
                page.goto(
                    players_url,
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
            page.locator('[role="table"]').first.wait_for(
                state="visible", timeout=30_000
            )

            tooltip = page.get_by_text(
                "Download statistics (XLSX)", exact=True
            ).first
            tooltip.wait_for(state="attached", timeout=15_000)
            download_button = tooltip.locator(
                'xpath=ancestor::*[contains(@class,"ActionIconWrapper")][1]'
            )
            if not download_button.count():
                download_button = page.locator(
                    '[class*="DownloadButtonContainer"] '
                    '[class*="ActionIconWrapper"]'
                ).first
            download_button.wait_for(state="visible", timeout=15_000)
            download_button.scroll_into_view_if_needed(timeout=10_000)

            print(
                "[SPORTSBASE] Téléchargement des statistiques Players XLSX — "
                f"match {match_id}"
            )
            with page.expect_download(timeout=30_000) as download_info:
                download_button.click(timeout=10_000)
            download = download_info.value
            if destination.exists():
                destination = self._unique_path(destination)
            download.save_as(str(destination))
            failure = download.failure()
            if failure:
                raise RuntimeError(failure)
            if not self._valid_xlsx(destination):
                raise RuntimeError(
                    "Le fichier reçu n’est pas un classeur XLSX valide."
                )

            print(f"[SPORTSBASE] Statistiques Players XLSX enregistrées : {destination}")
            return {
                "players_statistics_url": players_url,
                "players_statistics_xlsx": destination.name,
                "players_statistics_downloaded_at": _now_iso(),
                "players_statistics_error": "",
                **self._parse_players_statistics(destination),
            }
        except Exception as exc:
            print(
                "[SPORTSBASE][WARN] Téléchargement Players XLSX impossible — "
                f"match {match_id} : {exc}"
            )
            return {
                "players_statistics_url": players_url,
                "players_statistics_xlsx": "",
                "players_statistics_error": str(exc),
            }

    @staticmethod
    def _parse_players_statistics(path):
        try:
            workbook = read_players_statistics_xlsx(path)
            rows = workbook.get("rows") or []
            print(
                "[SPORTSBASE] Statistiques Players lues — "
                f"{len(rows)} joueur(s), "
                f"{len(workbook.get('headers') or [])} indicateur(s)"
            )
            return {
                "players_statistics_headers": workbook.get("headers") or [],
                "players_statistics_rows": rows,
            }
        except Exception as exc:
            print(
                "[SPORTSBASE][WARN] Lecture du fichier Players XLSX impossible : "
                f"{exc}"
            )
            return {
                "players_statistics_headers": [],
                "players_statistics_rows": [],
                "players_statistics_error": str(exc),
            }

    @staticmethod
    def _valid_xlsx(path):
        path = Path(path)
        try:
            if not path.is_file() or path.stat().st_size <= 0:
                return False
            with path.open("rb") as workbook:
                return workbook.read(2) == b"PK"
        except OSError:
            return False

    @staticmethod
    def _read_match_header_metadata(page, match_data):
        raw = page.evaluate(
            r"""
            () => {
              const text = (node) => node ? (node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim() : '';
              const directText = (node) => {
                if (!node) return '';
                const clone = node.cloneNode(true);
                clone.querySelectorAll('[class*="Tooltip"]').forEach((item) => item.remove());
                return text(clone);
              };
              const labelled = [];
              document.querySelectorAll('[class*="ParamName"], [class*="InfoName"], [class*="Label"], dt').forEach((labelNode) => {
                const label = directText(labelNode);
                if (!/(referee|arbitre|stadium|stade|venue|terrain)/i.test(label)) return;
                const row = labelNode.closest('li, [class*="Row"], [class*="Item"], [class*="Info"]') || labelNode.parentElement;
                if (!row) return;
                const clone = row.cloneNode(true);
                const clonedLabel = clone.querySelector('[class*="ParamName"], [class*="InfoName"], [class*="Label"], dt');
                if (clonedLabel) clonedLabel.remove();
                labelled.push({label, value: text(clone)});
              });
              const selectorTexts = (selector) => [...document.querySelectorAll(selector)].map(text).filter(Boolean);
              return {
                labelled,
                scoreTexts: selectorTexts('[class*="Score"], [class*="MatchTeams"], [class*="Result"]'),
                dateTexts: selectorTexts('time, [class*="MatchDate"], [class*="Date"]'),
                bodyLines: (document.body?.innerText || '').split(/\n+/).map((item) => item.trim()).filter(Boolean).slice(0, 250),
              };
            }
            """
        )
        result = {"stadium": "", "referee": ""}
        for item in raw.get("labelled", []):
            label = _clean_label(item.get("label")).lower()
            value = _clean_label(item.get("value"))
            if not value:
                continue
            if any(token in label for token in ("referee", "arbitre")):
                result["referee"] = value
            elif any(
                token in label
                for token in ("stadium", "stade", "venue", "terrain")
            ):
                result["stadium"] = value

        home = _clean_label(match_data.get("home_team")).lower()
        away = _clean_label(match_data.get("away_team")).lower()
        score_candidates = raw.get("scoreTexts", [])
        preferred = [
            value
            for value in score_candidates
            if (not home or home in value.lower())
            and (not away or away in value.lower())
        ]
        for value in preferred or score_candidates:
            score = SCORE_RE.search(value or "")
            if score:
                result["home_score"] = int(score.group(1))
                result["away_score"] = int(score.group(2))
                break

        for value in raw.get("dateTexts", []):
            parsed_date = _iso_date(value)
            if parsed_date:
                result["match_date"] = parsed_date
                break

        lines = raw.get("bodyLines", [])
        if not result["referee"]:
            result["referee"] = SportsBaseSubscriptionScraper._value_after_label(
                lines, ("referee", "arbitre")
            )
        if not result["stadium"]:
            result["stadium"] = SportsBaseSubscriptionScraper._value_after_label(
                lines, ("stadium", "stade", "venue", "terrain")
            )
        return result

    @staticmethod
    def _value_after_label(lines, labels):
        for index, line in enumerate(lines):
            normalized = _clean_label(line)
            lowered = normalized.lower()
            for label in labels:
                if lowered == label and index + 1 < len(lines):
                    return _clean_label(lines[index + 1])
                match = re.match(
                    rf"^{re.escape(label)}\s*[:\-]\s*(.+)$",
                    normalized,
                    flags=re.IGNORECASE,
                )
                if match:
                    return _clean_label(match.group(1))
        return ""

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
        team_rank = None
        if current:
            team_rank = next(
                (
                    index + 1
                    for index, item in enumerate(ranked)
                    if item["is_current_player"]
                ),
                None,
            )
            if team_rank is None:
                # SportsBase peut laisser l'index vide pour une courte participation.
                # La position affichée dans la table reste alors l'information fiable.
                team_rank = current["rank"]
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
        """Generate All Actions last, then click each ready row exactly once."""
        if not queue:
            return

        generated_matches = []
        for match_data, match_item, should_generate in queue:
            popup = None
            if not should_generate:
                generated_matches.append(
                    (match_data, self._generated_match_label(match_data))
                )
                continue
            try:
                popup = self.automation.click_all_players_actions_for_match(
                    page,
                    match_item,
                    match_data["source_metadata"]["list_position"] - 1,
                )
                title, _confirmed, _cancelled = (
                    self.automation.generate_download_in_popup(popup)
                )
                score = SCORE_RE.search(title or "")
                if score:
                    match_data["home_score"] = int(score.group(1))
                    match_data["away_score"] = int(score.group(2))
                generated_matches.append((match_data, title))
                match_data["actions_state"] = "generating"
                match_data["delivery_error"] = ""
            except Exception as exc:
                match_data["actions_state"] = "failed"
                match_data["delivery_error"] = str(exc)
            finally:
                if popup is not None:
                    try:
                        popup.close()
                    except Exception:
                        pass

        if not generated_matches:
            return

        # Le clic natif de Chrome possède exactement le contexte d'authentification
        # attendu par SportsBase. Playwright ne reçoit pas toujours son événement
        # download : on détecte donc le fichier terminé directement sur le disque.
        downloaded = self._download_generated_actions_once(
            page=page,
            player_name=job["player"]["name"],
            downloads_dir=downloads_dir,
            generated_matches=generated_matches,
        )
        downloaded_ids = set()
        for match_data, _generated_title in generated_matches:
            source = downloaded.get(match_data["sportsbase_match_id"])
            if not source:
                match_data["actions_state"] = "generating"
                match_data["delivery_error"] = (
                    "La vidéo a été générée, mais le fichier téléchargé n’a pas encore "
                    "été confirmé. Le prochain passage de l’agent pourra reprendre ce match."
                )
                continue

            destination = self._store_actions_file(
                source=source,
                player_root=player_root,
                player_name=job["player"]["name"],
                season=job.get("season", ""),
                match_data=match_data,
            )
            match_folder = destination.parent
            match_data.update(
                {
                    "actions_state": "downloaded",
                    "local_folder_key": str(match_folder.relative_to(self.storage_root)),
                    "all_actions_filename": destination.name,
                    "all_actions_downloaded_at": _now_iso(),
                    "delivery_error": "",
                }
            )
            downloaded_ids.add(match_data["sportsbase_match_id"])

        if downloaded_ids:
            print(
                "[SPORTSBASE] All Actions classées : "
                f"{len(downloaded_ids)} fichier(s)"
            )

    def _download_generated_actions_once(
        self, *, page, player_name, downloads_dir, generated_matches
    ):
        """Download ready My Videos rows without ever repeating a click in this run."""
        self._open_my_videos(page)
        targets = {
            f"{player_name}, player actions".lower(),
            f"{player_name}, all player actions".lower(),
            f"{player_name}, player's actions".lower(),
            f"{player_name}, all player's actions".lower(),
            f"{player_name}, actions du joueur".lower(),
            f"{player_name}, toutes les actions du joueur".lower(),
        }
        candidate_indexes = self._wait_for_candidate_rows(
            page,
            targets=targets,
            expected=len(generated_matches),
        )
        if not candidate_indexes:
            print("[SPORTSBASE][WARN] Aucune ligne My Videos trouvée pour le joueur.")
            return {}

        # SportsBase affiche les vidéos les plus récentes en premier. Les générations,
        # elles, ont été lancées du match le plus ancien au plus récent.
        selected_indexes = candidate_indexes[: len(generated_matches)]
        assignments = zip(generated_matches, reversed(selected_indexes))
        downloaded = {}
        clicked_rows = set()

        for ((match_data, generated_title), row_index) in assignments:
            row = self._wait_until_video_row_done(page, row_index, targets)
            if row is None:
                continue

            row_key = self._video_row_key(row)
            if row_key in clicked_rows:
                continue
            clicked_rows.add(row_key)

            buttons_cell = row.locator(
                "div.ButtonsCellContainer-sc-1t45i5t-0"
            ).first
            icons = buttons_cell.locator("div.IconWrapper-sc-1t45i5t-3")
            if not buttons_cell.count() or not icons.count():
                print(f"[SPORTSBASE][WARN] Bouton download absent : {row_key}")
                continue

            download_icon = icons.first
            download_icon.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            watch_dirs = self._download_watch_directories(downloads_dir)
            self._configure_native_downloads(page, downloads_dir)
            before = self._snapshot_download_files(watch_dirs)

            print(f"[SPORTSBASE] Clic download unique : {row_key}")
            try:
                download_icon.click(timeout=5000, no_wait_after=True)
            except Exception as exc:
                print(f"[SPORTSBASE][WARN] Clic My Videos : {exc}")
                continue

            print(
                "[SPORTSBASE] Téléchargement Chrome lancé; attente de la fin du fichier…"
            )
            source = self._wait_for_new_download(
                watch_dirs,
                before,
                timeout_seconds=300,
            )

            if source:
                downloaded[match_data["sportsbase_match_id"]] = Path(source)
                print(f"[SPORTSBASE] Fichier détecté après clic unique : {source}")
            else:
                print(
                    "[SPORTSBASE][WARN] Aucun fichier confirmé après le clic; "
                    "aucun second clic ne sera effectué."
                )
        return downloaded

    @staticmethod
    def _configure_native_downloads(page, downloads_dir):
        try:
            session = page.context.new_cdp_session(page)
            session.send(
                "Browser.setDownloadBehavior",
                {
                    "behavior": "allow",
                    "downloadPath": str(Path(downloads_dir).resolve()),
                    "eventsEnabled": True,
                },
            )
            return
        except Exception as exc:
            print(
                "[SPORTSBASE][INFO] Dossier Chrome contrôlé par le profil "
                f"persistant : {exc}"
            )

    @staticmethod
    def _generated_match_label(match_data):
        home = match_data.get("home_team") or "Equipe 1"
        away = match_data.get("away_team") or "Equipe 2"
        if match_data.get("home_score") is not None and match_data.get("away_score") is not None:
            return (
                f"{home} {match_data['home_score']}:"
                f"{match_data['away_score']} {away}"
            )
        return f"{home} - {away}"

    def _open_my_videos(self, page):
        opener = getattr(
            self.automation,
            "ensure_logged_in_and_open_my_videos",
            None,
        ) or getattr(self.automation, "open_my_videos")
        opener(page)
        page.locator('div[role="table"]').first.wait_for(
            state="visible", timeout=30000
        )

    @staticmethod
    def _video_rows(page):
        groups = page.locator('div[role="rowgroup"]')
        return groups.nth(1).locator('div[role="row"]') if groups.count() > 1 else page.locator('div[role="row"]')

    def _candidate_video_indexes(self, page, targets):
        rows = self._video_rows(page)
        indexes = []
        for index in range(rows.count()):
            try:
                title = rows.nth(index).locator("span.Name-sc-jbc8ns-2").first
                if not title.count():
                    continue
                value = _clean_label(title.inner_text()).lower()
                if any(target in value for target in targets):
                    indexes.append(index)
            except Exception:
                continue
        return indexes

    def _wait_for_candidate_rows(self, page, *, targets, expected):
        for attempt in range(20):
            indexes = self._candidate_video_indexes(page, targets)
            print(f"[SPORTSBASE] Lignes My Videos candidates : {indexes}")
            if len(indexes) >= expected:
                return indexes
            show_more = page.get_by_role("button", name="Show more").first
            if show_more.count() and show_more.is_visible():
                show_more.click()
                page.wait_for_timeout(1500)
            else:
                page.wait_for_timeout(5000)
                if attempt < 19:
                    page.reload(wait_until="domcontentloaded", timeout=30000)
                    page.locator('div[role="table"]').first.wait_for(
                        state="visible", timeout=30000
                    )
        indexes = self._candidate_video_indexes(page, targets)
        return indexes if len(indexes) >= expected else []

    def _wait_until_video_row_done(self, page, row_index, targets):
        try:
            timeout_seconds = int(
                os.getenv("SPORTSBASE_VIDEO_READY_TIMEOUT_SECONDS", "1200")
            )
        except (TypeError, ValueError):
            timeout_seconds = 1200
        timeout_seconds = max(60, min(timeout_seconds, 3600))
        attempts = max(1, timeout_seconds // 5)
        previous_state = None

        for attempt in range(attempts):
            indexes = self._candidate_video_indexes(page, targets)
            if row_index not in indexes:
                if attempt < attempts - 1:
                    page.wait_for_timeout(5000)
                    page.reload(wait_until="domcontentloaded", timeout=45000)
                    page.locator('div[role="table"]').first.wait_for(
                        state="visible", timeout=30000
                    )
                    continue
                return None

            row = self._video_rows(page).nth(row_index)
            status = row.locator("div.StatusContainer-sc-1qv6hin-1 span").first
            status_text = _clean_label(status.inner_text()).lower() if status.count() else ""
            buttons_cell = row.locator(
                "div.ButtonsCellContainer-sc-1t45i5t-0"
            ).first
            download_icon = buttons_cell.locator(
                "div.IconWrapper-sc-1t45i5t-3"
            ).first
            download_ready = bool(
                buttons_cell.count()
                and download_icon.count()
                and download_icon.is_visible()
            )
            state = status_text or "inconnu"
            if status_text == "done" and not download_ready:
                state = "done — attente de la flèche Download"
            if state != previous_state or attempt % 6 == 0:
                print(f"[SPORTSBASE] Ligne {row_index} — statut : {state}")
                previous_state = state

            if status_text == "done" and download_ready:
                return row

            page.wait_for_timeout(5000)
            if attempt % 3 == 2:
                page.reload(wait_until="domcontentloaded", timeout=45000)
                page.locator('div[role="table"]').first.wait_for(
                    state="visible", timeout=30000
                )

        print(
            "[SPORTSBASE][WARN] La vidéo n’est pas devenue Done avec la flèche "
            f"Download dans les {timeout_seconds} secondes."
        )
        return None

    @staticmethod
    def _video_row_key(row):
        def value(selector):
            locator = row.locator(selector).first
            return _clean_label(locator.inner_text()) if locator.count() else ""

        return "|".join(
            (
                value("span.Name-sc-jbc8ns-2"),
                value("div.DateCellContainer-sc-88jqaj-0"),
                value("div.DurationCellContainer-sc-kz1ea2-0"),
            )
        )

    @staticmethod
    def _download_watch_directories(downloads_dir):
        directories = [Path(downloads_dir)]
        configured = os.getenv("SPORTSBASE_BROWSER_DOWNLOAD_DIR", "").strip()
        if configured:
            directories.append(Path(configured))
        else:
            directories.append(Path.home() / "Downloads")
        unique = []
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            if directory not in unique:
                unique.append(directory)
        return unique

    @staticmethod
    def _snapshot_download_files(directories):
        snapshot = {}
        for directory in directories:
            try:
                for path in directory.iterdir():
                    if path.is_file():
                        stat = path.stat()
                        snapshot[str(path.resolve())] = (
                            stat.st_size,
                            stat.st_mtime_ns,
                        )
            except OSError:
                continue
        return snapshot

    def _wait_for_new_download(self, directories, before, timeout_seconds):
        deadline = time.monotonic() + timeout_seconds
        stable_sizes = {}
        temporary_suffixes = {".crdownload", ".part", ".tmp", ".download"}
        while time.monotonic() < deadline:
            candidates = []
            for directory in directories:
                try:
                    paths = list(directory.iterdir())
                except OSError:
                    continue
                for path in paths:
                    if not path.is_file() or path.suffix.lower() in temporary_suffixes:
                        continue
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    original = before.get(str(path.resolve()))
                    if original is None or original != (stat.st_size, stat.st_mtime_ns):
                        candidates.append((stat.st_mtime_ns, stat.st_size, path))

            for _modified, size, path in sorted(candidates, reverse=True):
                if size <= 0:
                    continue
                key = str(path.resolve())
                if stable_sizes.get(key) == size:
                    return path
                stable_sizes[key] = size
            time.sleep(1)
        return None

    def _write_season_artifacts(self, *, player_root, profile):
        season_key = self._folder_component(
            profile.get("season") or "saison_inconnue"
        )
        season_folder = Path(player_root) / f"season_{season_key}"
        season_folder.mkdir(parents=True, exist_ok=True)
        payload = {
            key: value
            for key, value in profile.items()
            if not key.endswith("_png_base64")
        }
        self._write_json(season_folder / "season_profile.json", payload)
        self._write_base64_png(
            season_folder / "season_radar.png",
            profile.get("radar_png_base64"),
        )
        self._write_base64_png(
            season_folder / "season_heatmap.png",
            profile.get("heatmap_png_base64"),
        )
        self._write_base64_png(
            season_folder / "season_ball_touches.png",
            profile.get("ball_touches_png_base64"),
        )

    def _write_match_artifacts(self, *, player_root, season, match_data):
        match_folder = self._match_folder(
            player_root=player_root,
            season=season,
            match_data=match_data,
        )
        stats = match_data.get("stats") or {}
        payload = {
            key: value
            for key, value in match_data.items()
            if key != "stats"
        }
        payload["stats"] = {
            key: value
            for key, value in stats.items()
            if not key.endswith("_png_base64")
        }
        self._write_json(match_folder / "match_data.json", payload)
        self._write_base64_png(
            match_folder / "heatmap.png",
            stats.get("heatmap_png_base64"),
        )
        self._write_base64_png(
            match_folder / "ball_touches.png",
            stats.get("ball_touches_png_base64"),
        )
        match_data["local_folder_key"] = str(
            match_folder.relative_to(self.storage_root)
        )

    @staticmethod
    def _write_json(path, payload):
        with Path(path).open("w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)

    @staticmethod
    def _write_base64_png(path, encoded):
        if not encoded:
            return
        try:
            content = base64.b64decode(encoded, validate=True)
        except Exception:
            return
        if content:
            Path(path).write_bytes(content)

    def _match_folder(self, *, player_root, season, match_data):
        season_key = self._folder_component(season or "saison_inconnue")
        date_key = self._folder_component(
            match_data.get("match_date") or "date_inconnue"
        )
        home_key = self._folder_component(
            match_data.get("home_team") or "equipe_1"
        )
        away_key = self._folder_component(
            match_data.get("away_team") or "equipe_2"
        )
        match_id = self._folder_component(match_data["sportsbase_match_id"])
        match_folder = (
            Path(player_root)
            / f"season_{season_key}"
            / f"{date_key}__{home_key}_vs_{away_key}__match_{match_id}"
        )
        match_folder.mkdir(parents=True, exist_ok=True)
        return match_folder

    def _store_actions_file(
        self, *, source, player_root, player_name, season, match_data
    ):
        match_folder = self._match_folder(
            player_root=player_root,
            season=season,
            match_data=match_data,
        )
        match_id = self._folder_component(match_data["sportsbase_match_id"])

        extension = Path(source).suffix or ".mp4"
        filename = self._file_component(
            f"{player_name}__All_Actions__match_{match_id}"
        )
        destination = self._unique_path(match_folder / f"{filename}{extension}")
        if Path(source).resolve() != destination.resolve():
            shutil.move(str(source), str(destination))
        return destination

    @staticmethod
    def _folder_component(value):
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", str(value or ""))
        cleaned = re.sub(r"\s+", "_", cleaned).strip(" ._-")
        return cleaned[:100] or "inconnu"

    @classmethod
    def _file_component(cls, value):
        return cls._folder_component(value)[:140]

    @staticmethod
    def _unique_path(path):
        if not path.exists():
            return path
        counter = 2
        while True:
            candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1
