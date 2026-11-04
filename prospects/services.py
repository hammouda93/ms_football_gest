from urllib.parse import urlparse

from django.core.exceptions import ValidationError

from gestion_joueurs.models import Player

from .models import Prospect


TRANSFERMARKT_DOMAINS = {
    "transfermarkt.at",
    "transfermarkt.be",
    "transfermarkt.ch",
    "transfermarkt.co.id",
    "transfermarkt.co.in",
    "transfermarkt.co.uk",
    "transfermarkt.co.za",
    "transfermarkt.com",
    "transfermarkt.com.ar",
    "transfermarkt.com.br",
    "transfermarkt.com.mx",
    "transfermarkt.com.tr",
    "transfermarkt.cz",
    "transfermarkt.de",
    "transfermarkt.es",
    "transfermarkt.fr",
    "transfermarkt.gr",
    "transfermarkt.hr",
    "transfermarkt.it",
    "transfermarkt.nl",
    "transfermarkt.pl",
    "transfermarkt.pt",
    "transfermarkt.ro",
    "transfermarkt.ru",
    "transfermarkt.us",
}

PLAYER_TO_PROSPECT_POSITION = {
    "GK": Prospect.Position.GOALKEEPER,
    "DF": Prospect.Position.DEFENDER,
    "MF": Prospect.Position.MIDFIELDER,
    "FW": Prospect.Position.FORWARD,
}

PROSPECT_TO_PLAYER_POSITION = {
    Prospect.Position.GOALKEEPER: "GK",
    Prospect.Position.DEFENDER: "DF",
    Prospect.Position.MIDFIELDER: "MF",
    Prospect.Position.FORWARD: "FW",
    Prospect.Position.OTHER: "DF",
}


def validate_transfermarkt_profile_url(value):
    """Accept only HTTP(S) URLs hosted on an actual Transfermarkt domain."""
    if not value:
        return ""

    candidate = value.strip()
    parsed = urlparse(candidate)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValidationError(
            "Collez un lien de profil Transfermarkt valide."
        ) from exc

    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or port not in {None, 80, 443}
        or not any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in TRANSFERMARKT_DOMAINS
        )
    ):
        raise ValidationError("Collez un lien de profil Transfermarkt valide.")

    return candidate


def map_player_position_to_prospect(position):
    return PLAYER_TO_PROSPECT_POSITION.get(
        position,
        Prospect.Position.OTHER,
    )


def map_player_league_to_prospect(league):
    valid_leagues = {value for value, _label in Prospect.League.choices}
    if league in valid_leagues:
        return league
    return Prospect.League.OTHER_COUNTRY


def find_matching_player(prospect):
    if prospect.transfermarkt_url:
        player = Player.objects.filter(
            transfermarkt_url__iexact=prospect.transfermarkt_url
        ).first()
        if player:
            return player

    if prospect.date_of_birth:
        player = Player.objects.filter(
            name__iexact=prospect.full_name,
            date_of_birth=prospect.date_of_birth,
        ).first()
        if player:
            return player

    if prospect.club:
        return Player.objects.filter(
            name__iexact=prospect.full_name,
            club__iexact=prospect.club,
        ).first()

    return None


def convert_prospect_to_player(prospect):
    """Create or safely enrich a Player, without creating a Video or invoice."""
    player = prospect.player or find_matching_player(prospect)
    created = player is None

    if created:
        player = Player(
            name=prospect.full_name,
            club=prospect.club,
            email=prospect.email,
            date_of_birth=prospect.date_of_birth,
            whatsapp_number=prospect.whatsapp_number,
            league=prospect.league,
            position=PROSPECT_TO_PLAYER_POSITION.get(prospect.position, "DF"),
            transfermarkt_url=prospect.transfermarkt_url or None,
        )
        player.save()
    else:
        update_fields = []
        safe_values = {
            "email": prospect.email,
            "date_of_birth": prospect.date_of_birth,
            "whatsapp_number": prospect.whatsapp_number,
            "transfermarkt_url": prospect.transfermarkt_url,
        }
        for field_name, value in safe_values.items():
            if value and not getattr(player, field_name):
                setattr(player, field_name, value)
                update_fields.append(field_name)

        if update_fields:
            if "date_of_birth" in update_fields:
                update_fields.append("age")
            player.save(update_fields=tuple(update_fields))

    prospect.player = player
    prospect.status = Prospect.Status.CONVERTED
    prospect.save(update_fields=("player", "status", "updated_at"))
    return player, created
