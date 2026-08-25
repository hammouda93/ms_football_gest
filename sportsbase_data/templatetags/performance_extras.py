from django import template


register = template.Library()


STAT_LABELS = {
    "Index": "Index",
    "Matches played": "Matchs joués",
    "Minutes played": "Minutes jouées",
    "Goals": "Buts",
    "Assists": "Passes décisives",
    "Mistakes leading to goals": "Erreurs menant à un but",
    "Yellow cards": "Cartons jaunes",
    "Red cards": "Cartons rouges",
    "Key passes": "Passes clés",
    "Shots": "Tirs",
    "Crosses": "Centres",
    "Crosses accurate, %": "Centres réussis",
    "Passes": "Passes",
    "Passes accurate, %": "Passes réussies",
    "Challenges": "Duels",
    "Challenges won, %": "Duels gagnés",
    "Aerial challenges": "Duels aériens",
    "Aerial challenges won, %": "Duels aériens gagnés",
    "Dribbles": "Dribbles",
    "Dribbles successful, %": "Dribbles réussis",
    "Tackles": "Tacles",
    "Tackles successful, %": "Tacles réussis",
    "Interceptions": "Interceptions",
    "Loose ball recoveries": "Récupérations",
    "xG (expected goals)": "xG (buts attendus)",
    "Shots on target, %": "Tirs cadrés",
}


PORTAL_DATA_STATES = {
    "never": "Analyse en préparation",
    "queued": "Mise à jour planifiée",
    "running": "Mise à jour en cours",
    "success": "Données à jour",
    "partial": "Mise à jour en cours",
    "failed": "Actualisation en attente",
}


PORTAL_ACTION_STATES = {
    "not_requested": "À planifier",
    "queued": "Préparation planifiée",
    "generating": "Préparation en cours",
    "downloaded": "Vidéo disponible",
    "emailed": "Envoyée par e-mail",
    "failed": "Vérification en cours",
}


PORTAL_ACTION_MESSAGES = {
    "queued": "La compilation est planifiée par notre équipe.",
    "generating": "La compilation de toutes les actions est en préparation.",
    "downloaded": "La vidéo est prête et sera transmise selon le mode convenu.",
    "emailed": "La vidéo a été envoyée à l’adresse e-mail du compte.",
    "failed": "La livraison est en cours de vérification par notre équipe.",
}


@register.filter
def stat_label(value):
    return STAT_LABELS.get(str(value), str(value))


@register.filter
def stat_value(value):
    if value is None:
        return "—"
    if isinstance(value, str) and value.strip().casefold() in {
        "",
        "-",
        "–",
        "none",
        "null",
        "nan",
    }:
        return "—"
    return value


@register.filter
def portal_data_state(value):
    return PORTAL_DATA_STATES.get(str(value), "Données disponibles")


@register.filter
def portal_action_label(value):
    return PORTAL_ACTION_STATES.get(str(value), "Suivi en cours")


@register.filter
def portal_action_message(value):
    return PORTAL_ACTION_MESSAGES.get(str(value), "")


@register.filter
def dict_get(value, key):
    if not isinstance(value, dict):
        return None
    return value.get(key)
