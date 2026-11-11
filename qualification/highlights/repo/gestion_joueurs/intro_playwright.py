import json
import re
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO


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
    }

    header = soup.select_one("header.data-header")
    if not header:
        return data

    # player name + shirt number
    name_wrap = header.select_one("h1.data-header__headline-wrapper")
    if name_wrap:
        shirt = name_wrap.select_one(".data-header__shirt-number")
        if shirt:
            data["shirt_number"] = clean_text(shirt.get_text(" ", strip=True))

        strong = name_wrap.select_one("strong")
        if strong:
            surname = clean_text(strong.get_text(" ", strip=True))
            full_text = clean_text(name_wrap.get_text(" ", strip=True))
            full_text = full_text.replace(data["shirt_number"], "").strip()
            data["player_name"] = full_text
        else:
            data["player_name"] = clean_text(name_wrap.get_text(" ", strip=True))

    # club name + logos
    club_link = header.select_one("a.data-header__box__club-link img")
    if club_link:
        srcset = club_link.get("srcset", "")
        club_logo_url = ""
        if srcset:
            parts = [p.strip() for p in srcset.split(",") if p.strip()]
            if parts:
                club_logo_url = parts[-1].split(" ")[0].strip()
        if not club_logo_url:
            club_logo_url = club_link.get("src", "").strip()
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

    # player image
    player_img = header.select_one(".data-header__profile-image")
    if player_img:
        data["player_image_url"] = player_img.get("src", "").strip()

    # market value
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

    # details
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


def open_image_local_or_download(url: str, max_size=(220, 220)):
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


def draw_wrapped_text(draw, text, font, x, y, max_width, fill=(255, 255, 255), line_spacing=6):
    words = text.split()
    if not words:
        return y

    line = ""
    lines = []
    for word in words:
        test = word if not line else f"{line} {word}"
        bbox = draw.textbbox((0, 0), test, font=font)
        width = bbox[2] - bbox[0]
        if width <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)

    for ln in lines:
        draw.text((x, y), ln, font=font, fill=fill)
        bbox = draw.textbbox((x, y), ln, font=font)
        y += (bbox[3] - bbox[1]) + line_spacing

    return y


def build_transfermarkt_card(data: dict, output_path: Path):
    width, height = 1400, 800
    bg = Image.new("RGB", (width, height), (15, 18, 28))
    draw = ImageDraw.Draw(bg)

    title_font = load_font(54)
    big_font = load_font(38)
    label_font = load_font(24)
    text_font = load_font(28)
    small_font = load_font(20)

    # layout
    left_x = 70
    top_y = 60

    # load assets
    player_img = open_image_local_or_download(data.get("player_image_url", ""), (300, 390))
    club_logo = open_image_local_or_download(data.get("club_logo_url", ""), (120, 120))
    league_logo = open_image_local_or_download(data.get("league_logo_url", ""), (80, 80))

    # player image block
    if player_img:
        bg.paste(player_img, (left_x, 140), player_img)

    # logos
    if club_logo:
        bg.paste(club_logo, (1180, 60), club_logo)
    if league_logo:
        bg.paste(league_logo, (1080, 80), league_logo)

    # name + number
    draw.text((420, top_y), data.get("player_name", "Unknown Player"), font=title_font, fill=(255, 255, 255))
    if data.get("shirt_number"):
        draw.text((420, top_y + 70), data["shirt_number"], font=big_font, fill=(255, 210, 80))

    # club / league
    draw.text((420, 170), f"Club: {data.get('club_name', '-')}", font=text_font, fill=(220, 225, 235))
    draw.text((420, 215), f"Ligue: {data.get('league_name', '-')}", font=text_font, fill=(220, 225, 235))

    # details box
    box_x, box_y = 420, 290
    box_w, box_h = 900, 390
    draw.rounded_rectangle((box_x, box_y, box_x + box_w, box_y + box_h), radius=26, fill=(27, 33, 48))

    details = [
        ("Nationalité", data.get("nationality", "-")),
        ("Pays/Ligue", data.get("country", "-")),
        ("Naissance", data.get("birth_date_age", "-")),
        ("Lieu de naissance", data.get("birth_place", "-")),
        ("Taille", data.get("height", "-")),
        ("Position", data.get("position", "-")),
        ("Valeur", data.get("market_value", "-")),
        ("Dernière maj", data.get("market_value_last_update", "-")),
    ]

    current_y = box_y + 30
    for label, value in details:
        draw.text((box_x + 30, current_y), f"{label} :", font=label_font, fill=(255, 210, 80))
        current_y = draw_wrapped_text(
            draw,
            value or "-",
            text_font,
            box_x + 220,
            current_y - 2,
            650,
            fill=(240, 243, 248),
            line_spacing=4,
        )
        current_y += 10

    # footer
    draw.text((70, 740), "Transfermarkt data card", font=small_font, fill=(160, 170, 190))

    bg.save(output_path)


def build_assets_from_transfermarkt_html(html_path: str, output_dir: str):
    html_path = Path(html_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    html_text = html_path.read_text(encoding="utf-8")
    data = extract_transfermarkt_data(html_text)

    # save json
    json_path = output_dir / "transfermarkt_data.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # save club logo
    logo_path = output_dir / "transfermarkt_Team_Logo.jpg"
    logo_ok = download_image(data.get("club_logo_url", ""), logo_path)

    # save card
    card_path = output_dir / "transfermarkt_card.png"
    build_transfermarkt_card(data, card_path)

    return {
        "json_path": str(json_path),
        "logo_path": str(logo_path) if logo_ok else None,
        "card_path": str(card_path),
        "data": data,
    }


if __name__ == "__main__":
    result = build_assets_from_transfermarkt_html(
        html_path="Texte collé(13).txt",
        output_dir="transfermarkt_output"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))