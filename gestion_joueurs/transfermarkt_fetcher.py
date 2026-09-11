from pathlib import Path
import json
import requests

try:
    from .presentation_styles import DEFAULT_PRESENTATION_STYLE
    from .transfermarkt_assets import (
        build_assets_from_transfermarkt_html_text,
        write_presentation_prompt_assets,
    )
except ImportError:
    from presentation_styles import DEFAULT_PRESENTATION_STYLE
    from transfermarkt_assets import (
        build_assets_from_transfermarkt_html_text,
        write_presentation_prompt_assets,
    )


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


def build_transfermarkt_assets_from_url_file(
    intro_folder: str,
    presentation_style=DEFAULT_PRESENTATION_STYLE,
):
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
        presentation_style=presentation_style,
    )

    return {
        "transfermarkt_url": transfermarkt_url,
        "raw_html_path": str(raw_html_path),

        # Présentation normale
        "json_path": assets["json_path"],
        "logo_path": assets["logo_path"],
        "badge_paths": assets["badge_paths"],
        "badges_card_path": assets["badges_card_path"],
        "prompt_path": assets["prompt_path"],
        "chatgpt_image_prompt_path": assets["chatgpt_image_prompt_path"],
        "kling_prompt_path": assets["kling_prompt_path"],
        "visual_identity_brief_path": assets["visual_identity_brief_path"],
        "presentation_style_path": assets["presentation_style_path"],

        # Deuxième présentation : position + valeur marchande
        "position_market_value_prompt_path": assets["position_market_value_prompt_path"],
        "position_graph_path": assets["position_graph_path"],
        "market_value_graph_path": assets["market_value_graph_path"],
        "position_market_value_card_path": assets["position_market_value_card_path"],

        "data": assets["data"],
    }


def refresh_presentation_style_assets(
    intro_folder: str,
    presentation_style=DEFAULT_PRESENTATION_STYLE,
):
    """Refresh prompts for a new preset from cached factual data."""
    intro_path = Path(intro_folder)
    json_path = intro_path / "transfermarkt_data.json"
    if not json_path.is_file():
        raise FileNotFoundError(f"transfermarkt_data.json introuvable: {json_path}")
    style_path = intro_path / "presentation_style.json"
    if style_path.is_file():
        try:
            current_style = json.loads(style_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current_style = {}
        if current_style.get("value") == presentation_style:
            return {
                "prompt_path": str(intro_path / "prompt.txt"),
                "chatgpt_image_prompt_path": str(intro_path / "prompt_chatgpt_image.txt"),
                "kling_prompt_path": str(intro_path / "prompt_kling_image_to_video.txt"),
                "visual_identity_brief_path": str(intro_path / "visual_identity_brief.txt"),
                "presentation_style_path": str(style_path),
                "presentation_style": current_style,
                "style_changed": False,
            }
    data = json.loads(json_path.read_text(encoding="utf-8"))
    result = write_presentation_prompt_assets(
        data,
        intro_path,
        presentation_style,
    )
    result["style_changed"] = True
    return result


if __name__ == "__main__":
    result = build_transfermarkt_assets_from_url_file(
        r"D:\Django_Projects\ms_football_gest\gestion_joueurs\automated_players\1749_Amine_Haboubi\intro"
    )
    print(result)
