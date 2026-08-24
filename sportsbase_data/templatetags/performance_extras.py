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
    "Passes": "Passes",
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
}


@register.filter
def stat_label(value):
    return STAT_LABELS.get(str(value), str(value))


@register.filter
def dict_get(value, key):
    if not isinstance(value, dict):
        return None
    return value.get(key)
