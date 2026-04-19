from pathlib import Path
import requests

from transfermarkt_assets import build_assets_from_transfermarkt_html_text


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


def fetch_transfermarkt_html(url: str, timeout: int = 30) -> str:
    response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.text


def build_transfermarkt_assets_from_url_file(intro_folder: str):
    intro_path = Path(intro_folder)
    intro_path.mkdir(parents=True, exist_ok=True)

    url_file = intro_path / "transfermarkt_url.txt"
    if not url_file.exists():
        raise FileNotFoundError(f"transfermarkt_url.txt introuvable: {url_file}")

    transfermarkt_url = url_file.read_text(encoding="utf-8").strip()
    if not transfermarkt_url:
        raise ValueError("transfermarkt_url.txt est vide")

    html_text = fetch_transfermarkt_html(transfermarkt_url)

    raw_html_path = intro_path / "transfermarkt_raw.html"
    raw_html_path.write_text(html_text, encoding="utf-8")

    assets = build_assets_from_transfermarkt_html_text(
        html_text=html_text,
        output_dir=str(intro_path),
    )

    return {
        "transfermarkt_url": transfermarkt_url,
        "raw_html_path": str(raw_html_path),
        "json_path": assets["json_path"],
        "logo_path": assets["logo_path"],
        "badge_paths": assets["badge_paths"],
        "badges_card_path": assets["badges_card_path"],
        "prompt_path": assets["prompt_path"],
        "data": assets["data"],
    }


if __name__ == "__main__":
    result = build_transfermarkt_assets_from_url_file(
        r"D:\Django_Projects\ms_football_gest\gestion_joueurs\automated_players\1749_Amine_Haboubi\intro"
    )
    print(result)