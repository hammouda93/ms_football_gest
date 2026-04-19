import json
import re
from io import BytesIO
from pathlib import Path

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
        "position": "",
        "market_value": "",
        "market_value_last_update": "",
        "badges": [],
    }

    header = soup.select_one("header.data-header")
    if not header:
        return data

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
        srcset = club_link_img.get("srcset", "")
        club_logo_url = ""
        if srcset:
            parts = [p.strip() for p in srcset.split(",") if p.strip()]
            if parts:
                club_logo_url = parts[-1].split(" ")[0].strip()
        if not club_logo_url:
            club_logo_url = club_link_img.get("src", "").strip()
        data["club_logo_url"] = club_logo_url

    club_name_link = header.select_one(".data-header__club a")
    if club_name_link:
        data["club_name"] = clean_text(club_name_link.get_text(" ", strip=True))

    league_link = header.select_one(".data-header__league-link")
    if league_link:
        data["league_name"] = clean_text(league_link.get_text(" ", strip=True))
        league_img = league_link.select_one("img")
        if league_img:
            data["league_logo_url"] = league_img.get("src", "").strip()

    player_img = header.select_one(".data-header__profile-image")
    if player_img:
        data["player_image_url"] = player_img.get("src", "").strip()

    badges = []
    badge_links = header.select(".data-header__badge-container a.data-header__success-data")
    for badge in badge_links:
        badge_title = clean_text(badge.get("title", ""))
        badge_count_el = badge.select_one(".data-header__success-number")
        badge_count = clean_text(badge_count_el.get_text(" ", strip=True)) if badge_count_el else "1"

        badge_img = badge.select_one("img")
        badge_img_url = badge_img.get("src", "").strip() if badge_img else ""

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


def build_prompt_text(data: dict) -> str:
    player_name = data.get("player_name", "Unknown Player")
    shirt_number = data.get("shirt_number", "")
    club_name = data.get("club_name", "")
    league_name = data.get("league_name", "")
    nationality = data.get("nationality", "")
    position = data.get("position", "")
    height = data.get("height", "")
    market_value = data.get("market_value", "")
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
    market_value = data.get("market_value", "-")
    position = data.get("position", "-")
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
        "data": data,
    }