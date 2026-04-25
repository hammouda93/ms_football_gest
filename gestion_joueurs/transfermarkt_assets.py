import json
import re
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def safe_filename(value: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", clean_text(value))


def download_image(url: str, output_path: Path) -> bool:
    if not url:
        return False
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        output_path.write_bytes(r.content)
        return True
    except Exception:
        return False


def extract_img_url(img) -> str:
    if not img:
        return ""

    srcset = img.get("srcset", "")
    if srcset:
        parts = [p.strip() for p in srcset.split(",") if p.strip()]
        if parts:
            return parts[-1].split(" ")[0].strip()

    data_src = img.get("data-src", "").strip()
    if data_src:
        return data_src

    return img.get("src", "").strip()


def extract_transfermarkt_data(html_text: str) -> dict:
    soup = BeautifulSoup(html_text, "html.parser")

    data = {
        "player_name": "",
        "shirt_number": "",
        "player_image_url": "",
        "club_name": "",
        "club_logo_url": "",
        "league_name": "",
        "league_logo_url": "",
        "country": "",
        "birth_date_age": "",
        "birth_place": "",
        "nationality": "",
        "height": "",

        # Position header
        "position": "",

        # Position détaillée
        "primary_position": "",
        "secondary_positions": [],
        "detailed_positions": [],
        "position_marker_classes": [],

        # Valeur marchande
        "market_value": "",
        "market_value_last_update": "",
        "market_value_current": "",
        "market_value_highest": "",
        "market_value_highest_date": "",
        "market_value_last_change": "",

        # SVG / graph source
        "market_value_svg": "",

        "badges": [],
    }

    header = soup.select_one("header.data-header")

    if header:
        name_wrap = header.select_one("h1.data-header__headline-wrapper")
        if name_wrap:
            shirt = name_wrap.select_one(".data-header__shirt-number")
            if shirt:
                data["shirt_number"] = clean_text(shirt.get_text(" ", strip=True))

            data["player_name"] = clean_text(name_wrap.get_text(" ", strip=True))
            if data["shirt_number"]:
                data["player_name"] = data["player_name"].replace(data["shirt_number"], "").strip()

        club_link_img = header.select_one("a.data-header__box__club-link img")
        if club_link_img:
            data["club_logo_url"] = extract_img_url(club_link_img)

        club_name_link = header.select_one(".data-header__club a")
        if club_name_link:
            data["club_name"] = clean_text(club_name_link.get_text(" ", strip=True))

        league_link = header.select_one(".data-header__league-link")
        if league_link:
            data["league_name"] = clean_text(league_link.get_text(" ", strip=True))
            league_img = league_link.select_one("img")
            if league_img:
                data["league_logo_url"] = extract_img_url(league_img)

        player_img = header.select_one(".data-header__profile-image")
        if player_img:
            data["player_image_url"] = extract_img_url(player_img)

        badges = []
        badge_links = header.select(".data-header__badge-container a.data-header__success-data")
        for badge in badge_links:
            badge_title = clean_text(badge.get("title", ""))
            badge_count_el = badge.select_one(".data-header__success-number")
            badge_count = clean_text(badge_count_el.get_text(" ", strip=True)) if badge_count_el else "1"

            badge_img = badge.select_one("img")
            badge_img_url = extract_img_url(badge_img) if badge_img else ""

            badges.append({
                "title": badge_title,
                "count": badge_count,
                "image_url": badge_img_url,
            })

        data["badges"] = badges

        mv_wrap = header.select_one(".data-header__market-value-wrapper")
        if mv_wrap:
            full_mv_text = clean_text(mv_wrap.get_text(" ", strip=True))
            last_update = header.select_one(".data-header__last-update")
            if last_update:
                data["market_value_last_update"] = clean_text(last_update.get_text(" ", strip=True))
                mv_text = full_mv_text.replace(data["market_value_last_update"], "").strip()
                data["market_value"] = mv_text
            else:
                data["market_value"] = full_mv_text

        labels = header.select(".data-header__label")
        for label in labels:
            txt = clean_text(label.get_text(" ", strip=True))

            if txt.startswith("Naissance"):
                content = label.select_one(".data-header__content")
                if content:
                    data["birth_date_age"] = clean_text(content.get_text(" ", strip=True))

            elif txt.startswith("Lieu de naissance"):
                content = label.select_one(".data-header__content")
                if content:
                    data["birth_place"] = clean_text(content.get_text(" ", strip=True))

            elif txt.startswith("Nationalité"):
                content = label.select_one(".data-header__content")
                if content:
                    data["nationality"] = clean_text(content.get_text(" ", strip=True))

            elif txt.startswith("Taille"):
                content = label.select_one(".data-header__content")
                if content:
                    data["height"] = clean_text(content.get_text(" ", strip=True))

            elif txt.startswith("Position"):
                content = label.select_one(".data-header__content")
                if content:
                    data["position"] = clean_text(content.get_text(" ", strip=True))

            elif "Pays/Ligue" in txt:
                content = label.select_one(".data-header__content")
                if content:
                    data["country"] = clean_text(content.get_text(" ", strip=True))

    # ------------------------------------------------------------
    # Position détaillée + classes terrain
    # ------------------------------------------------------------
    detail_position_box = soup.select_one(".detail-position")
    if detail_position_box:
        detailed_positions = []

        for dl in detail_position_box.select("dl"):
            title_el = dl.select_one("dt.detail-position__title")
            position_el = dl.select_one("dd.detail-position__position")

            title = clean_text(title_el.get_text(" ", strip=True)) if title_el else ""
            position_value = clean_text(position_el.get_text(" ", strip=True)) if position_el else ""

            if not position_value:
                continue

            detailed_positions.append({
                "label": title,
                "position": position_value,
            })

            normalized_title = title.lower()

            if "principale" in normalized_title:
                data["primary_position"] = position_value
            elif "secondaire" in normalized_title:
                data["secondary_positions"].append(position_value)

        data["detailed_positions"] = detailed_positions

        markers = []
        for marker in detail_position_box.select(".matchfield__campo .position"):
            classes = marker.get("class", [])
            marker_type = "unknown"
            marker_number = ""

            for cls in classes:
                if cls == "position--primary":
                    marker_type = "primary"
                elif cls == "position--secondary":
                    marker_type = "secondary"
                elif cls.startswith("position--") and cls not in ["position--primary", "position--secondary"]:
                    marker_number = cls.replace("position--", "")

            markers.append({
                "type": marker_type,
                "number": marker_number,
                "classes": classes,
            })

        data["position_marker_classes"] = markers

    # ------------------------------------------------------------
    # Valeur marchande détaillée
    # ------------------------------------------------------------
    market_box = soup.select_one(".tm-player-market-value-development-container")
    if market_box:
        current_value_el = market_box.select_one(".current-value a")
        if current_value_el:
            data["market_value_current"] = clean_text(current_value_el.get_text(" ", strip=True))

        max_value_el = market_box.select_one(".max-value")
        if max_value_el:
            data["market_value_highest"] = clean_text(max_value_el.get_text(" ", strip=True))

            max_parent = max_value_el.parent
            if max_parent:
                max_parent_text = clean_text(max_parent.get_text(" ", strip=True))
                possible_date = max_parent_text.replace("Valeur la plus élevée:", "")
                possible_date = possible_date.replace(data["market_value_highest"], "").strip()
                data["market_value_highest_date"] = possible_date

        update_el = market_box.select_one(".update")
        if update_el:
            update_text = clean_text(update_el.get_text(" ", strip=True))
            data["market_value_last_change"] = update_text.replace("Dernier changement:", "").strip()

        svg_el = market_box.select_one("svg")
        if svg_el:
            data["market_value_svg"] = str(svg_el)

    if not data["market_value_current"] and data["market_value"]:
        data["market_value_current"] = data["market_value"]

    return data


def load_font(size: int):
    candidates = [
        "arial.ttf",
        "DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            pass
    return ImageFont.load_default()


def open_image_from_url(url: str, max_size=(220, 220)):
    if not url:
        return None
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGBA")
        img.thumbnail(max_size)
        return img
    except Exception:
        return None


def draw_wrapped_text(draw, text, xy, font, fill, max_width, line_spacing=8):
    x, y = xy
    words = text.split()
    line = ""

    for word in words:
        test_line = f"{line} {word}".strip()
        bbox = draw.textbbox((x, y), test_line, font=font)
        line_width = bbox[2] - bbox[0]

        if line_width <= max_width:
            line = test_line
        else:
            if line:
                draw.text((x, y), line, font=font, fill=fill)
                y += font.size + line_spacing
            line = word

    if line:
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + line_spacing

    return y


def build_position_lines(data: dict) -> list:
    lines = []

    primary_position = data.get("primary_position", "")
    secondary_positions = data.get("secondary_positions", [])
    header_position = data.get("position", "")

    if primary_position:
        lines.append(f"Position principale: {primary_position}")
    elif header_position:
        lines.append(f"Position: {header_position}")

    if secondary_positions:
        lines.append(f"Position secondaire: {', '.join(secondary_positions)}")

    return lines


def build_market_value_lines(data: dict) -> list:
    lines = []

    current_value = data.get("market_value_current") or data.get("market_value", "")
    highest_value = data.get("market_value_highest", "")
    highest_date = data.get("market_value_highest_date", "")
    last_change = data.get("market_value_last_change", "")
    last_update = data.get("market_value_last_update", "")

    if current_value:
        lines.append(f"Valeur marchande actuelle: {current_value}")

    if highest_value:
        if highest_date:
            lines.append(f"Valeur la plus élevée: {highest_value} ({highest_date})")
        else:
            lines.append(f"Valeur la plus élevée: {highest_value}")

    if last_change:
        lines.append(f"Dernier changement: {last_change}")
    elif last_update:
        lines.append(f"Dernière mise à jour: {last_update}")

    return lines


def position_number_to_xy(position_number: str, field_x: int, field_y: int, field_w: int, field_h: int):
    """
    Mapping simple pour reproduire le terrain Transfermarkt.
    Les numéros Transfermarkt peuvent varier, donc on garde un fallback.
    14 = Avant-centre dans ton exemple.
    11 = Ailier gauche dans ton exemple.
    """
    mapping = {
        "1": (0.50, 0.91),   # Gardien
        "2": (0.20, 0.74),
        "3": (0.38, 0.76),
        "4": (0.62, 0.76),
        "5": (0.80, 0.74),
        "6": (0.35, 0.58),
        "7": (0.65, 0.58),
        "8": (0.50, 0.50),
        "9": (0.50, 0.34),
        "10": (0.50, 0.42),
        "11": (0.22, 0.28),  # Ailier gauche
        "12": (0.78, 0.28),
        "13": (0.35, 0.23),
        "14": (0.50, 0.18),  # Avant-centre
        "15": (0.65, 0.23),
    }

    rx, ry = mapping.get(str(position_number), (0.50, 0.50))
    return int(field_x + rx * field_w), int(field_y + ry * field_h)


def build_position_graph(data: dict, output_path: Path):
    width, height = 1200, 900
    bg = Image.new("RGB", (width, height), (12, 18, 30))
    draw = ImageDraw.Draw(bg)

    title_font = load_font(54)
    big_font = load_font(40)
    text_font = load_font(30)
    small_font = load_font(22)

    player_name = data.get("player_name", "Unknown Player")
    primary_position = data.get("primary_position") or data.get("position") or "-"
    secondary_positions = data.get("secondary_positions", [])
    markers = data.get("position_marker_classes", [])

    draw.text((50, 35), "Position détaillée", font=title_font, fill=(255, 255, 255))
    draw.text((50, 105), player_name, font=big_font, fill=(255, 210, 80))

    field_x, field_y = 190, 180
    field_w, field_h = 820, 620

    # Terrain
    draw.rounded_rectangle((field_x, field_y, field_x + field_w, field_y + field_h), radius=28, fill=(23, 95, 58))
    draw.rectangle((field_x + 20, field_y + 20, field_x + field_w - 20, field_y + field_h - 20), outline=(210, 230, 220), width=4)
    draw.line((field_x + 20, field_y + field_h // 2, field_x + field_w - 20, field_y + field_h // 2), fill=(210, 230, 220), width=3)
    draw.ellipse(
        (
            field_x + field_w // 2 - 95,
            field_y + field_h // 2 - 95,
            field_x + field_w // 2 + 95,
            field_y + field_h // 2 + 95,
        ),
        outline=(210, 230, 220),
        width=3,
    )

    # Surfaces
    draw.rectangle((field_x + field_w // 2 - 150, field_y + 20, field_x + field_w // 2 + 150, field_y + 130), outline=(210, 230, 220), width=3)
    draw.rectangle((field_x + field_w // 2 - 150, field_y + field_h - 130, field_x + field_w // 2 + 150, field_y + field_h - 20), outline=(210, 230, 220), width=3)

    # Marqueurs
    if not markers:
        markers = [{"type": "primary", "number": "14", "classes": []}]

    for marker in markers:
        marker_type = marker.get("type", "unknown")
        number = marker.get("number", "")
        x, y = position_number_to_xy(number, field_x, field_y, field_w, field_h)

        if marker_type == "primary":
            radius = 24
            fill = (255, 210, 80)
            outline = (255, 255, 255)
            label = "P"
        else:
            radius = 18
            fill = (70, 160, 255)
            outline = (255, 255, 255)
            label = "S"

        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill, outline=outline, width=4)
        draw.text((x - 8, y - 15), label, font=small_font, fill=(10, 15, 25))

    # Infos
    info_y = 815
    draw.text((50, info_y), f"Principale: {primary_position}", font=text_font, fill=(245, 247, 252))

    if secondary_positions:
        draw.text((50, info_y + 42), f"Secondaire: {', '.join(secondary_positions)}", font=text_font, fill=(210, 225, 245))

    bg.save(output_path)


def extract_svg_paths(svg_text: str):
    """
    Extraction simple des path d'un SVG Transfermarkt.
    On ne rend pas tout le SVG exactement, mais on reconstruit le graphe principal
    à partir des paths d'origine si disponibles.
    """
    if not svg_text:
        return []

    try:
        cleaned_svg = svg_text.replace("xlink:href", "href")
        root = ET.fromstring(cleaned_svg)
    except Exception:
        return []

    paths = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag == "path":
            d = elem.attrib.get("d", "")
            if d and ("L" in d or "M" in d):
                paths.append(d)

    return paths


def parse_simple_svg_polyline_path(d: str):
    """
    Parse simple pour les paths du genre:
    M10,119.455L24.531,117.236L45.577,69.545...
    """
    points = []
    if not d:
        return points

    main = d.split("Z")[0]
    tokens = re.split(r"[ML]", main)
    for token in tokens:
        token = token.strip()
        if not token or "," not in token:
            continue

        parts = token.split(",")
        if len(parts) < 2:
            continue

        try:
            x = float(parts[0])
            y = float(parts[1])
            points.append((x, y))
        except Exception:
            pass

    return points


def build_market_value_graph(data: dict, output_path: Path):
    width, height = 1200, 900
    bg = Image.new("RGB", (width, height), (12, 18, 30))
    draw = ImageDraw.Draw(bg)

    title_font = load_font(54)
    big_font = load_font(46)
    text_font = load_font(30)
    small_font = load_font(22)

    player_name = data.get("player_name", "Unknown Player")
    current_value = data.get("market_value_current") or data.get("market_value") or "-"
    highest_value = data.get("market_value_highest") or "-"
    highest_date = data.get("market_value_highest_date") or ""
    last_change = data.get("market_value_last_change") or data.get("market_value_last_update") or ""

    draw.text((50, 35), "Valeur marchande", font=title_font, fill=(255, 255, 255))
    draw.text((50, 105), player_name, font=big_font, fill=(255, 210, 80))

    # Cards infos
    card_y = 180
    draw.rounded_rectangle((50, card_y, 555, card_y + 150), radius=24, fill=(26, 32, 48))
    draw.text((80, card_y + 28), "Valeur actuelle", font=text_font, fill=(210, 225, 245))
    draw.text((80, card_y + 78), current_value, font=big_font, fill=(255, 255, 255))

    draw.rounded_rectangle((645, card_y, 1150, card_y + 150), radius=24, fill=(26, 32, 48))
    draw.text((675, card_y + 28), "Valeur la plus élevée", font=text_font, fill=(210, 225, 245))
    high_text = highest_value
    if highest_date:
        high_text = f"{highest_value} | {highest_date}"
    draw.text((675, card_y + 78), high_text, font=text_font, fill=(255, 255, 255))

    # Zone graphe
    graph_x, graph_y = 90, 390
    graph_w, graph_h = 1020, 330
    draw.rounded_rectangle((graph_x, graph_y, graph_x + graph_w, graph_y + graph_h), radius=28, fill=(245, 247, 252))

    # Axes
    axis_color = (80, 90, 110)
    draw.line((graph_x + 45, graph_y + graph_h - 45, graph_x + graph_w - 35, graph_y + graph_h - 45), fill=axis_color, width=3)
    draw.line((graph_x + 45, graph_y + 35, graph_x + 45, graph_y + graph_h - 45), fill=axis_color, width=3)

    # Essayer d'utiliser le SVG source Transfermarkt
    svg_text = data.get("market_value_svg", "")
    paths = extract_svg_paths(svg_text)

    selected_points = []
    for d in paths:
        points = parse_simple_svg_polyline_path(d)
        if len(points) >= 4:
            # On prend le premier path linéaire assez long
            selected_points = points
            break

    if selected_points:
        src_w, src_h = 328, 135
        target_x = graph_x + 70
        target_y = graph_y + 45
        target_w = graph_w - 120
        target_h = graph_h - 105

        scaled = []
        for px, py in selected_points:
            sx = target_x + (px / src_w) * target_w
            sy = target_y + (py / src_h) * target_h
            scaled.append((sx, sy))

        # Area
        area = [(scaled[0][0], graph_y + graph_h - 45)] + scaled + [(scaled[-1][0], graph_y + graph_h - 45)]
        draw.polygon(area, fill=(205, 218, 238))

        # Line
        draw.line(scaled, fill=(28, 70, 120), width=6, joint="curve")

        # Dots
        for x, y in scaled:
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(28, 70, 120), outline=(255, 255, 255), width=2)
    else:
        # Fallback visuel si SVG absent
        fallback = [
            (graph_x + 80, graph_y + 250),
            (graph_x + 220, graph_y + 210),
            (graph_x + 360, graph_y + 130),
            (graph_x + 520, graph_y + 90),
            (graph_x + 700, graph_y + 180),
            (graph_x + 880, graph_y + 215),
            (graph_x + 1030, graph_y + 120),
        ]
        area = [(fallback[0][0], graph_y + graph_h - 45)] + fallback + [(fallback[-1][0], graph_y + graph_h - 45)]
        draw.polygon(area, fill=(205, 218, 238))
        draw.line(fallback, fill=(28, 70, 120), width=6)
        for x, y in fallback:
            draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(28, 70, 120), outline=(255, 255, 255), width=2)

    if last_change:
        draw.text((50, 785), f"Dernier changement: {last_change}", font=text_font, fill=(220, 225, 235))

    bg.save(output_path)


def build_position_market_value_card(data: dict, output_path: Path):
    width, height = 1600, 900
    bg = Image.new("RGB", (width, height), (12, 16, 26))
    draw = ImageDraw.Draw(bg)

    title_font = load_font(62)
    big_font = load_font(46)
    medium_font = load_font(34)
    text_font = load_font(28)
    small_font = load_font(22)

    player_name = data.get("player_name", "Unknown Player")
    shirt_number = data.get("shirt_number", "")
    club_name = data.get("club_name", "-")
    league_name = data.get("league_name", "-")
    nationality = data.get("nationality", "-")

    player_img = open_image_from_url(data.get("player_image_url", ""), (360, 460))
    club_logo = open_image_from_url(data.get("club_logo_url", ""), (150, 150))

    draw.text((60, 45), player_name, font=title_font, fill=(255, 255, 255))
    subtitle = f"{club_name} | {league_name} | {nationality}"
    draw.text((60, 125), subtitle, font=text_font, fill=(210, 218, 232))

    if shirt_number:
        draw.text((60, 170), shirt_number, font=big_font, fill=(255, 210, 80))

    if club_logo:
        bg.paste(club_logo, (1390, 45), club_logo)

    if player_img:
        bg.paste(player_img, (80, 340), player_img)

    panel_x, panel_y = 500, 240
    panel_w, panel_h = 980, 560
    draw.rounded_rectangle(
        (panel_x, panel_y, panel_x + panel_w, panel_y + panel_h),
        radius=32,
        fill=(26, 32, 48)
    )

    position_x = panel_x + 45
    position_y = panel_y + 45
    draw.text((position_x, position_y), "POSITION PROFILE", font=big_font, fill=(255, 210, 80))

    y = position_y + 75
    position_lines = build_position_lines(data) or ["Position: -"]

    for line in position_lines:
        y = draw_wrapped_text(
            draw=draw,
            text=line,
            xy=(position_x, y),
            font=text_font,
            fill=(245, 247, 252),
            max_width=850,
            line_spacing=10
        )
        y += 8

    sep_y = y + 25
    draw.line((position_x, sep_y, panel_x + panel_w - 45, sep_y), fill=(70, 80, 105), width=2)

    market_y = sep_y + 35
    draw.text((position_x, market_y), "MARKET VALUE", font=big_font, fill=(255, 210, 80))

    y = market_y + 75
    market_lines = build_market_value_lines(data) or ["Valeur marchande: -"]

    for line in market_lines:
        y = draw_wrapped_text(
            draw=draw,
            text=line,
            xy=(position_x, y),
            font=medium_font,
            fill=(245, 247, 252),
            max_width=850,
            line_spacing=12
        )
        y += 10

    draw.text((60, 860), "Transfermarkt position + market value card", font=small_font, fill=(160, 170, 190))
    bg.save(output_path)


def build_prompt_text(data: dict) -> str:
    player_name = data.get("player_name", "Unknown Player")
    shirt_number = data.get("shirt_number", "")
    club_name = data.get("club_name", "")
    league_name = data.get("league_name", "")
    nationality = data.get("nationality", "")
    position = data.get("position", "")
    primary_position = data.get("primary_position", "")
    secondary_positions = data.get("secondary_positions", [])
    secondary_positions_text = ", ".join(secondary_positions) if secondary_positions else ""

    height = data.get("height", "")
    market_value = data.get("market_value_current") or data.get("market_value", "")
    market_value_last_update = data.get("market_value_last_update", "")
    country = data.get("country", "")
    birth_date_age = data.get("birth_date_age", "")
    birth_place = data.get("birth_place", "")
    badges = data.get("badges", [])

    trophies_block = ""
    if badges:
        trophy_lines = []
        for badge in badges:
            title = badge.get("title", "").strip()
            count = badge.get("count", "1")
            if title:
                trophy_lines.append(f"- {title} x{count}")
        if trophy_lines:
            trophies_block = (
                "\nAchievements to include elegantly:\n" +
                "\n".join(trophy_lines) +
                "\n"
            )

    prompt = f"""Create a premium cinematic football player profile poster in 1920x1080.

Use the uploaded real player photo as the main focal point. The player must remain realistic, recognizable, sharp, and highly detailed. Build the design in the style of elite football highlight graphics, with dramatic lighting, strong contrast, clean structure, luxury sports branding, and professional marketing quality.

Also use the uploaded Transfermarkt assets and JSON data as reference for the factual information and visual identity:
- Name: {player_name}
- Shirt number: {shirt_number or "-"}
- Nationality: {nationality or "-"}
- Club: {club_name or "-"}
- League: {league_name or "-"}
- Position: {position or "-"}
- Primary position: {primary_position or position or "-"}
- Secondary position(s): {secondary_positions_text or "-"}
- Height: {height or "-"}
- Market value: {market_value or "-"}
- Market value last update: {market_value_last_update or "-"}
- Birth date / age: {birth_date_age or "-"}
- Birth place: {birth_place or "-"}
- Country / League context: {country or "-"}

{trophies_block}
Design requirements:
- modern football poster aesthetic
- bold typography
- dynamic composition
- subtle but premium background effects inspired by the club colors and the football culture of the club’s city / country
- elegant glow, depth, lighting, and atmosphere
- high-end sports broadcast / scouting presentation style
- clean hierarchy of information
- polished professional finish
- no clutter

Visual priorities:
1. player photo must dominate the composition
2. club logo must be integrated in a stylish way
3. trophies / badges must be integrated in a premium way
4. use nationality and club location/cultural atmosphere subtly in the background design language
5. make the composition feel like elite football promo art

Text to include in an elegant way:
- player full name
- Season Highlights
- club name
- position
- nationality
- market value
- selected profile details from the uploaded data

Important:
- do not invent false statistics
- use only the uploaded factual data
- keep the layout aesthetic and balanced
- make it feel like an elite football promo graphic
- output must be exactly 1920x1080
"""
    return prompt


def build_position_market_value_prompt_text(data: dict) -> str:
    player_name = data.get("player_name", "Unknown Player")
    shirt_number = data.get("shirt_number", "")
    club_name = data.get("club_name", "")
    league_name = data.get("league_name", "")
    nationality = data.get("nationality", "")

    position_lines = build_position_lines(data)
    market_lines = build_market_value_lines(data)

    position_block = "\n".join(f"- {line}" for line in position_lines) if position_lines else "- Position: -"
    market_block = "\n".join(f"- {line}" for line in market_lines) if market_lines else "- Valeur marchande: -"

    prompt = f"""Create a second premium football presentation poster in 1920x1080 focused ONLY on the player's position profile and market value.

Use these uploaded assets:
- player_photo image
- transfermarkt_data.json
- transfermarkt_Team_Logo image if available
- position_graph.png
- market_value_graph.png
- position_market_value_card.png

Use the uploaded real player photo. The player must remain realistic, recognizable, sharp, and highly detailed.

This is NOT the normal season highlights presentation. This is a separate visual presentation dedicated to:
1. player identity
2. position information
3. market value information

Factual data to display:
- Player name: {player_name}
- Shirt number: {shirt_number or "-"}
- Club: {club_name or "-"}
- League: {league_name or "-"}
- Nationality: {nationality or "-"}

Position information:
{position_block}

Market value information:
{market_block}

Design direction:
- premium football scouting / transfer market visual
- cinematic dark sports background
- luxury football data-card style
- player photo large and clean
- player name clearly visible
- include the position graph as a visual tactical field element
- include the market value graph as a financial progression element
- position area as one strong section
- market value area as another strong section
- use visual separation between Position and Market Value
- use elegant typography
- use club colors subtly if possible
- use the club logo if available
- clean, high-end, modern design
- no fake statistics
- no invented numbers
- use only the provided Transfermarkt JSON data and uploaded assets

Text to include:
- player full name
- Position Profile
- Market Value
- main position
- secondary position if available
- current market value
- highest market value if available
- last change/update if available
- club name

Important:
- do not include Season Highlights in this second poster
- do not invent false statistics
- keep the design clean and readable
- output must be exactly 1920x1080
"""
    return prompt


def download_badges(data: dict, badges_dir: Path):
    badges = data.get("badges", [])
    if not badges:
        return []

    badges_dir.mkdir(parents=True, exist_ok=True)
    downloaded_badges = []

    for idx, badge in enumerate(badges, start=1):
        badge_url = badge.get("image_url", "").strip()
        badge_title = badge.get("title", "").strip() or f"badge_{idx:02d}"
        badge_count = badge.get("count", "1")

        safe_title = safe_filename(badge_title)
        output_path = badges_dir / f"badge_{idx:02d}_{safe_title}_x{badge_count}.png"

        ok = download_image(badge_url, output_path)
        if ok:
            downloaded_badges.append({
                "path": str(output_path),
                "title": badge_title,
                "count": badge_count,
            })

    return downloaded_badges


def build_badges_card(data: dict, downloaded_badges: list, output_path: Path):
    width, height = 1600, 900
    bg = Image.new("RGB", (width, height), (15, 18, 28))
    draw = ImageDraw.Draw(bg)

    title_font = load_font(56)
    big_font = load_font(38)
    text_font = load_font(28)
    small_font = load_font(20)

    player_name = data.get("player_name", "Unknown Player")
    club_name = data.get("club_name", "-")
    league_name = data.get("league_name", "-")
    shirt_number = data.get("shirt_number", "")
    market_value = data.get("market_value_current") or data.get("market_value", "-")
    position = data.get("primary_position") or data.get("position", "-")
    nationality = data.get("nationality", "-")

    club_logo = open_image_from_url(data.get("club_logo_url", ""), (130, 130))
    player_img = open_image_from_url(data.get("player_image_url", ""), (260, 340))

    if club_logo:
        bg.paste(club_logo, (1380, 40), club_logo)

    draw.text((60, 45), player_name, font=title_font, fill=(255, 255, 255))
    if shirt_number:
        draw.text((60, 120), shirt_number, font=big_font, fill=(255, 210, 80))

    draw.text((60, 175), f"{club_name} | {league_name}", font=text_font, fill=(220, 225, 235))
    draw.text((60, 220), f"{position} | {nationality} | {market_value}", font=text_font, fill=(220, 225, 235))

    if player_img:
        bg.paste(player_img, (60, 300), player_img)

    panel_x, panel_y = 380, 300
    panel_w, panel_h = 1160, 520
    draw.rounded_rectangle(
        (panel_x, panel_y, panel_x + panel_w, panel_y + panel_h),
        radius=28,
        fill=(27, 33, 48)
    )

    draw.text((panel_x + 30, panel_y + 25), "Achievements / Badges", font=big_font, fill=(255, 210, 80))

    cols = 3
    cell_w = 350
    cell_h = 180
    start_x = panel_x + 25
    start_y = panel_y + 90

    for idx, badge in enumerate(downloaded_badges):
        row = idx // cols
        col = idx % cols

        x = start_x + col * cell_w
        y = start_y + row * cell_h

        draw.rounded_rectangle((x, y, x + 320, y + 150), radius=22, fill=(36, 43, 61))

        badge_img = None
        try:
            badge_img = Image.open(badge["path"]).convert("RGBA")
            badge_img.thumbnail((90, 90))
        except Exception:
            badge_img = None

        if badge_img:
            bg.paste(badge_img, (x + 20, y + 30), badge_img)

        draw.text((x + 125, y + 25), badge["title"], font=text_font, fill=(255, 255, 255))
        draw.text((x + 125, y + 80), f"x{badge['count']}", font=big_font, fill=(255, 210, 80))

    draw.text((60, 860), "Transfermarkt badges card", font=small_font, fill=(160, 170, 190))
    bg.save(output_path)


def build_assets_from_transfermarkt_html_text(html_text: str, output_dir: str):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    data = extract_transfermarkt_data(html_text)

    json_path = output_dir / "transfermarkt_data.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    logo_path = output_dir / "transfermarkt_Team_Logo.jpg"
    logo_ok = download_image(data.get("club_logo_url", ""), logo_path)

    prompt_path = output_dir / "prompt.txt"
    prompt_path.write_text(build_prompt_text(data), encoding="utf-8")

    position_market_value_prompt_path = output_dir / "prompt_position_market_value.txt"
    position_market_value_prompt_path.write_text(
        build_position_market_value_prompt_text(data),
        encoding="utf-8"
    )

    position_graph_path = output_dir / "position_graph.png"
    build_position_graph(data, position_graph_path)

    market_value_graph_path = output_dir / "market_value_graph.png"
    build_market_value_graph(data, market_value_graph_path)

    position_market_value_card_path = output_dir / "position_market_value_card.png"
    build_position_market_value_card(data, position_market_value_card_path)

    badge_paths = []
    badges_card_path = None

    if data.get("badges"):
        badges_dir = output_dir / "badges"
        downloaded_badges = download_badges(data, badges_dir)

        if downloaded_badges:
            badge_paths = [b["path"] for b in downloaded_badges]
            badges_card_path_obj = output_dir / "badges_card.png"
            build_badges_card(data, downloaded_badges, badges_card_path_obj)
            badges_card_path = str(badges_card_path_obj)

    return {
        "json_path": str(json_path),
        "logo_path": str(logo_path) if logo_ok else None,
        "badge_paths": badge_paths,
        "badges_card_path": badges_card_path,
        "prompt_path": str(prompt_path),

        # Deuxième génération
        "position_market_value_prompt_path": str(position_market_value_prompt_path),
        "position_graph_path": str(position_graph_path),
        "market_value_graph_path": str(market_value_graph_path),
        "position_market_value_card_path": str(position_market_value_card_path),

        "data": data,
    }