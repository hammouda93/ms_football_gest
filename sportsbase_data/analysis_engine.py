"""Role-specific, player-facing analysis built from the match Players table.

The engine keeps the player's real match totals. Playing time describes
reliability and selects a coarse activity window; it never turns a substitute
appearance into a fictitious 90-minute performance.
"""

import math
import re
import unicodedata
ANALYSIS_VERSION = "ms-position-score-calibration-v10-20260828"


# The public InStat / Wyscout / SportsBase products do not publish a formula
# that can be reproduced faithfully.  MS Score therefore uses an auditable
# 0-100 model: fixed position-mission weights, a neutral value for missions
# that could not be observed, a small bounded decisive adjustment and a very
# small rank validation.  The limits prevent one event or a provider index
# from erasing the football requirements of the player's position.
MS_NEUTRAL_SCORE = 50
MS_DECISIVE_ADJUSTMENT_LIMIT = 8.0
MS_CONTEXT_ADJUSTMENT_LIMIT = 2.0
MS_SCORE_BANDS = (
    (92, "exceptional"),
    (75, "very_good"),
    (68, "solid"),
    (58, "mixed"),
    (48, "insufficient"),
    (float("-inf"), "difficult"),
)

METHODOLOGY_SOURCES = (
    {
        "name": "FIFA Football Language - performance analysis",
        "url": (
            "https://www.fifatrainingcentre.com/en/game/performance-analysis/"
            "football-language-analysis/the-fifa-football-language.php"
        ),
    },
    {
        "name": "FIFA - Position-specific training",
        "url": (
            "https://www.fifatrainingcentre.com/en/practice/talent-coach-programme/"
            "position-specific-training/developing-players-using-position-specific-training.php"
        ),
    },
    {
        "name": "FIFA - Centre-forwards linking attacks",
        "url": (
            "https://www.fifatrainingcentre.com/en/game/tournaments/2023-u20-fwc/"
            "centre-forwards-linking-attacks.php"
        ),
    },
    {
        "name": "FIFA - Goalkeeper role in build-up",
        "url": (
            "https://www.fifatrainingcentre.com/en/game/tournaments/2021-fifa-arab-cup/"
            "the-goalkeepers-role-in-the-build-up-phase.php"
        ),
    },
    {
        "name": "StatsBomb - Player recruitment: forwards",
        "url": (
            "https://blogarchive.statsbomb.com/articles/soccer/"
            "using-statsbomb-iq-for-player-recruitment-forwards/"
        ),
    },
    {
        "name": "Hudl Wyscout - Position-specific player ranking parameters",
        "url": "https://www.hudl.com/blog/wyscout-teams-of-the-season-2023-24",
    },
    {
        "name": "StatsBomb - Player recruitment: centre-backs",
        "url": (
            "https://blogarchive.statsbomb.com/articles/soccer/"
            "using-statsbomb-iq-for-player-recruitment-centre-backs/"
        ),
    },
    {
        "name": "StatsBomb - Player recruitment: full-backs",
        "url": (
            "https://blogarchive.statsbomb.com/articles/soccer/"
            "using-statsbomb-iq-for-player-recruitment-full-backs/"
        ),
    },
    {
        "name": "StatsBomb - Explaining and training shot quality",
        "url": (
            "https://blogarchive.statsbomb.com/articles/soccer/"
            "explaining-and-training-shot-quality/"
        ),
    },
    {
        "name": "StatsBomb - Expected Goals (xG) explained",
        "url": "https://statsbomb.com/soccer-metrics/expected-goals-xg-explained/",
    },
    {
        "name": "StatsBomb - Unpacking ball progression and On-Ball Value",
        "url": (
            "https://blogarchive.statsbomb.com/articles/soccer/"
            "unpacking-ball-progression/"
        ),
    },
    {
        "name": "StatsBomb - Position-specific full-back radars",
        "url": (
            "https://blogarchive.statsbomb.com/articles/soccer/"
            "introducing-and-explaining-fullback-radars-sagna-debuchy-lahm-alves-and-more/"
        ),
    },
    {
        "name": "FIFA - Emerging positioning of the inverted full-back",
        "url": (
            "https://www.fifatrainingcentre.com/en/game/tournaments/fcwc/2025/"
            "team-analyses/emerging-positioning-of-the-inverted-full-back.php"
        ),
    },
)


TEXT = {
    "fr": {
        "roles": {
            "goalkeeper": "Gardien",
            "centre_back": "Défenseur central",
            "full_back": "Arrière latéral",
            "wing_back": "Piston",
            "holding_midfielder": "Milieu défensif / n° 6",
            "box_to_box_midfielder": "Milieu relayeur / n° 8",
            "attacking_midfielder": "Milieu offensif / n° 10",
            "winger": "Ailier",
            "forward": "Avant-centre",
        },
        "confidence": {
            "very_low": "Très faible",
            "low": "Faible",
            "medium": "Moyenne",
            "good": "Bonne",
            "very_good": "Très bonne",
            "very_high": "Très élevée",
        },
        "confidence_text": {
            "very_low": "1 à 19 minutes : lecture de l’impact immédiat seulement.",
            "low": "20 à 44 minutes : tendances utiles, mais échantillon encore court.",
            "medium": "45 à 59 minutes : base exploitable pour analyser la performance.",
            "good": "60 à 74 minutes : bonne base d’analyse de la rencontre.",
            "very_good": "75 à 89 minutes : lecture très fiable de la performance du match.",
            "very_high": "90 minutes ou plus : match complet, fiabilité maximale pour cette rencontre.",
        },
        "sample": {
            "none": "Aucune occasion",
            "very_low": "Très petit échantillon",
            "low": "Petit échantillon",
            "usable": "Échantillon exploitable",
            "strong": "Échantillon solide",
        },
        "verdicts": {
            "exceptional": "MATCH EXCEPTIONNEL",
            "very_good": "TRÈS BON MATCH",
            "solid": "MATCH SOLIDE",
            "mixed": "MATCH MITIGÉ",
            "insufficient": "PERFORMANCE INSUFFISANTE",
            "difficult": "MATCH TRÈS DIFFICILE",
            "partial": "ÉVALUATION PARTIELLE",
        },
        "entry_verdicts": {
            "exceptional": "ENTRÉE DÉCISIVE",
            "very_good": "TRÈS BONNE ENTRÉE",
            "solid": "BONNE ENTRÉE",
            "mixed": "ENTRÉE MOYENNE",
            "insufficient": "ENTRÉE INSUFFISANTE",
            "difficult": "ENTRÉE CATASTROPHIQUE",
            "partial": "ENTRÉE À CONFIRMER",
        },
        "grades": {
            "dominant": "DOMINANT",
            "strong": "FORT",
            "solid": "SOLIDE",
            "mixed": "MITIGÉ",
            "fragile": "FRAGILE",
            "critical": "À CORRIGER",
            "unseen": "À CONFIRMER",
        },
        "counterpart": "Homologue adverse au même poste",
        "sample_caution": (
            "Les volumes affichés sont les totaux réels du match. Aucun événement n’est "
            "projeté sur 90 minutes. Les pourcentages sont toujours lus avec leur nombre "
            "de tentatives."
        ),
        "video_limit": (
            "Les données proposent des hypothèses de performance. Les intentions, les "
            "consignes, les déplacements sans ballon et les causes doivent être confirmés "
            "avec la vidéo All Actions."
        ),
        "index_first_match": "1er à l’Indice de performance de la rencontre ({rank}/{total}) : signal majeur d’une prestation de très haut niveau statistique.",
        "index_first_team": "1er à l’Indice de performance de son équipe ({rank}/{total}) : signal fort d’un très bon impact statistique.",
        "index_top_three": "Classé {rank}e sur {total} à l’Indice de performance dans son équipe : il figure parmi les performances statistiques les plus fortes de son équipe.",
        "index_available": "Indice de performance : rang {rank}/{total} dans son équipe.",
        "index_unavailable": "Indice de performance non disponible : il n’influence pas le verdict.",
    },
    "en": {
        "roles": {
            "goalkeeper": "Goalkeeper",
            "centre_back": "Centre-back",
            "full_back": "Full-back",
            "wing_back": "Wing-back",
            "holding_midfielder": "Holding midfielder / No. 6",
            "box_to_box_midfielder": "Box-to-box midfielder / No. 8",
            "attacking_midfielder": "Attacking midfielder / No. 10",
            "winger": "Winger",
            "forward": "Centre-forward",
        },
        "confidence": {
            "very_low": "Very low",
            "low": "Low",
            "medium": "Medium",
            "good": "Good",
            "very_good": "Very good",
            "very_high": "Very high",
        },
        "confidence_text": {
            "very_low": "1–19 minutes: immediate-impact reading only.",
            "low": "20–44 minutes: useful trends, but still a short sample.",
            "medium": "45–59 minutes: a usable basis for match analysis.",
            "good": "60–74 minutes: a good basis for analysing the performance.",
            "very_good": "75–89 minutes: a very reliable reading of this match.",
            "very_high": "90+ minutes: full-match evidence and maximum reliability for this game.",
        },
        "sample": {
            "none": "No opportunity",
            "very_low": "Very small sample",
            "low": "Small sample",
            "usable": "Usable sample",
            "strong": "Strong sample",
        },
        "verdicts": {
            "exceptional": "EXCEPTIONAL MATCH",
            "very_good": "VERY GOOD MATCH",
            "solid": "SOLID MATCH",
            "mixed": "MIXED MATCH",
            "insufficient": "INSUFFICIENT PERFORMANCE",
            "difficult": "VERY DIFFICULT MATCH",
            "partial": "PARTIAL ASSESSMENT",
        },
        "entry_verdicts": {
            "exceptional": "DECISIVE IMPACT OFF THE BENCH",
            "very_good": "VERY GOOD IMPACT OFF THE BENCH",
            "solid": "GOOD IMPACT OFF THE BENCH",
            "mixed": "AVERAGE IMPACT OFF THE BENCH",
            "insufficient": "INSUFFICIENT IMPACT OFF THE BENCH",
            "difficult": "VERY POOR IMPACT OFF THE BENCH",
            "partial": "IMPACT TO CONFIRM",
        },
        "grades": {
            "dominant": "DOMINANT",
            "strong": "STRONG",
            "solid": "SOLID",
            "mixed": "MIXED",
            "fragile": "FRAGILE",
            "critical": "TO CORRECT",
            "unseen": "TO CONFIRM",
        },
        "counterpart": "Opposition player in the exact same position",
        "sample_caution": (
            "Displayed volumes are the player's real match totals. No event is projected "
            "to 90 minutes. Every percentage is read with its attempt count."
        ),
        "video_limit": (
            "The data creates performance hypotheses. Intent, tactical instructions, "
            "off-ball movement and causes must be confirmed through All Actions video."
        ),
        "index_first_match": "1st on the Performance Index in the match ({rank}/{total}): a major signal of a very high-level statistical performance.",
        "index_first_team": "1st on the Performance Index in his team ({rank}/{total}): a strong signal of very good statistical impact.",
        "index_top_three": "Ranked {rank}/{total} on the Performance Index in his team: among his team's strongest statistical performances.",
        "index_available": "Performance Index: ranked {rank}/{total} in his team.",
        "index_unavailable": "The Performance Index is unavailable and does not affect the verdict.",
    },
    "ar": {
        "roles": {
            "goalkeeper": "حارس مرمى",
            "centre_back": "قلب دفاع",
            "full_back": "ظهير",
            "wing_back": "جناح دفاعي",
            "holding_midfielder": "وسط دفاعي / رقم 6",
            "box_to_box_midfielder": "وسط متحرك / رقم 8",
            "attacking_midfielder": "وسط هجومي / رقم 10",
            "winger": "جناح هجومي",
            "forward": "قلب هجوم",
        },
        "confidence": {
            "very_low": "ضعيفة جدا",
            "low": "ضعيفة",
            "medium": "متوسطة",
            "good": "جيدة",
            "very_good": "جيدة جدا",
            "very_high": "مرتفعة جدا",
        },
        "confidence_text": {
            "very_low": "من 1 إلى 19 دقيقة: قراءة للتأثير المباشر فقط.",
            "low": "من 20 إلى 44 دقيقة: مؤشرات مفيدة لكن العينة قصيرة.",
            "medium": "من 45 إلى 59 دقيقة: قاعدة قابلة للاستعمال لتحليل الأداء.",
            "good": "من 60 إلى 74 دقيقة: قاعدة جيدة لتحليل المباراة.",
            "very_good": "من 75 إلى 89 دقيقة: قراءة موثوقة جدا للمباراة.",
            "very_high": "90 دقيقة أو أكثر: مباراة كاملة وأعلى موثوقية لهذه المباراة.",
        },
        "sample": {
            "none": "لا توجد فرصة",
            "very_low": "عينة صغيرة جدا",
            "low": "عينة صغيرة",
            "usable": "عينة قابلة للاستعمال",
            "strong": "عينة قوية",
        },
        "verdicts": {
            "exceptional": "مباراة استثنائية",
            "very_good": "مباراة جيدة جدا",
            "solid": "مباراة قوية",
            "mixed": "مباراة متباينة",
            "insufficient": "أداء غير كاف",
            "difficult": "مباراة صعبة جدا",
            "partial": "تقييم جزئي",
        },
        "entry_verdicts": {
            "exceptional": "دخول حاسم",
            "very_good": "دخول ممتاز",
            "solid": "دخول جيد",
            "mixed": "دخول متوسط",
            "insufficient": "دخول غير كاف",
            "difficult": "دخول كارثي",
            "partial": "دخول يحتاج إلى تأكيد",
        },
        "grades": {
            "dominant": "مهيمن",
            "strong": "قوي",
            "solid": "صلب",
            "mixed": "متباين",
            "fragile": "هش",
            "critical": "يحتاج إلى تصحيح",
            "unseen": "يحتاج إلى تأكيد",
        },
        "counterpart": "اللاعب المنافس في نفس المركز تماما",
        "sample_caution": (
            "الأحجام المعروضة هي الأرقام الحقيقية للمباراة ولا يتم تحويلها إلى 90 دقيقة. "
            "كل نسبة تقرأ مع عدد المحاولات."
        ),
        "video_limit": (
            "تقدم البيانات فرضيات للأداء، ويجب تأكيد النوايا والتعليمات والتحركات دون "
            "كرة والأسباب عبر فيديو جميع اللقطات."
        ),
        "index_first_match": "الأول في مؤشر الأداء في المباراة ({rank}/{total})، وهي إشارة قوية إلى أداء إحصائي رفيع المستوى.",
        "index_first_team": "الأول في مؤشر الأداء داخل فريقه ({rank}/{total})، وهي إشارة قوية إلى تأثير إحصائي ممتاز.",
        "index_top_three": "المرتبة {rank}/{total} في مؤشر الأداء داخل فريقه، ضمن أفضل أداءات فريقه إحصائيا.",
        "index_available": "المرتبة {rank}/{total} في مؤشر الأداء داخل فريقه.",
        "index_unavailable": "مؤشر الأداء غير متاح ولا يؤثر في الخلاصة.",
    },
}


METRIC_LABELS = {
    "fr": {
        "№": "N°",
        "Player": "Joueur",
        "Team": "Équipe",
        "Index": "Indice de performance",
        "Minutes played": "Minutes jouées",
        "Position": "Poste",
        "Goals": "Buts",
        "Assists": "Passes décisives",
        "Mistakes leading to goals": "Erreurs menant à un but",
        "Mistakes leading to chances": "Erreurs menant à une occasion",
        "Chances": "Occasions",
        "Chances successful": "Occasions réussies",
        "Chances successful, %": "Occasions converties",
        "Chances created": "Occasions créées",
        "Involvement in scoring attacks": "Implication dans les attaques décisives",
        "Shots": "Tirs",
        "Shots on target": "Tirs cadrés",
        "Shots on target, %": "Tirs cadrés",
        "Shots from the penalty area": "Tirs dans la surface",
        "Shots on target from the penalty area, %": "Tirs cadrés dans la surface",
        "Shots from outside the penalty area": "Tirs hors surface",
        "Shots on target from outside the penalty area, %": "Tirs cadrés hors surface",
        "Shots on post / bar": "Tirs sur le poteau ou la barre",
        "Headers": "Têtes tentées",
        "Headers on target, %": "Têtes cadrées",
        "Goals by head": "Buts de la tête",
        "Free-kick shots": "Tirs sur coup franc",
        "Free-kick goals": "Buts sur coup franc",
        "Shots in box share": "Part des tirs dans la surface",
        "Passes": "Passes",
        "Passes accurate, %": "Passes réussies",
        "Short passes": "Passes courtes",
        "Short passes accurate, %": "Passes courtes réussies",
        "Key passes": "Passes clés",
        "Key passes accurate, %": "Passes clés réussies",
        "Crosses": "Centres",
        "Crosses accurate, %": "Centres réussis",
        "Progressive passes": "Passes progressives",
        "Progressive passes accurate, %": "Passes progressives réussies",
        "Progressive open passes": "Passes progressives dans le jeu",
        "Long passes": "Passes longues",
        "Long passes accurate, %": "Passes longues réussies",
        "Super long passes": "Passes très longues",
        "Super long passes accurate, %": "Passes très longues réussies",
        "Passes forward to the final third": "Passes vers le dernier tiers",
        "Passes forward to the final third accurate, %": "Passes réussies vers le dernier tiers",
        "Passes into the penalty box": "Passes dans la surface",
        "Passes into the penalty box accurate, %": "Passes réussies dans la surface",
        "Passes for a shot": "Passes menant à un tir",
        "Challenges": "Duels",
        "Challenges won, %": "Duels gagnés",
        "Defensive challenges": "Duels défensifs",
        "Defensive challenges won, %": "Duels défensifs gagnés",
        "Attacking challenges": "Duels offensifs",
        "Attacking challenges won, %": "Duels offensifs gagnés",
        "Aerial challenges": "Duels aériens",
        "Aerial challenges won, %": "Duels aériens gagnés",
        "Dribbles": "Dribbles",
        "Dribbles successful, %": "Dribbles réussis",
        "Dribbling in the final third": "Dribbles dans le dernier tiers",
        "Dribbling in the final third successful, %": "Dribbles réussis dans le dernier tiers",
        "Tackles": "Tacles",
        "Tackles successful, %": "Tacles réussis",
        "Interceptions": "Interceptions",
        "Loose ball recoveries": "Deuxièmes ballons récupérés",
        "xG (expected goals)": "Buts attendus (xG)",
        "Final third entries": "Entrées dans le dernier tiers",
        "Final third entries through pass": "Entrées par la passe",
        "Final third entries through carry": "Entrées par la conduite",
        "Lost balls": "Ballons perdus",
        "Lost balls in own half": "Pertes dans son camp",
        "Ball recoveries": "Récupérations",
        "Ball recoveries in opponent's half": "Récupérations hautes",
        "Actions": "Actions",
        "Actions successful, %": "Actions réussies",
        "Involvement in scoring attacks": "Implication dans les attaques menant à un but",
        "Actions in opponent's box": "Actions dans la surface adverse",
        "Actions in opponent's box successful, %": "Actions réussies dans la surface",
        "Fouls": "Fautes commises",
        "Fouls suffered": "Fautes subies",
        "Yellow cards": "Cartons jaunes",
        "Red cards": "Cartons rouges",
        "Final third entries through pass, % of total": "Part des entrées par la passe",
        "Final third entries through carry, % of total": "Part des entrées par la conduite",
    },
    "en": {
        "№": "No.",
        "Player": "Player",
        "Team": "Team",
        "Index": "Performance Index",
        "Minutes played": "Minutes played",
        "Position": "Position",
    },
    "ar": {
        "№": "الرقم",
        "Player": "اللاعب",
        "Team": "الفريق",
        "Index": "مؤشر الأداء",
        "Minutes played": "دقائق اللعب",
        "Position": "المركز",
        "Goals": "الأهداف",
        "Assists": "التمريرات الحاسمة",
        "Shots": "التسديدات",
        "Shots on target": "التسديدات المؤطرة",
        "Shots on target, %": "التسديدات المؤطرة",
        "Shots from the penalty area": "التسديدات من داخل المنطقة",
        "Shots on target from the penalty area, %": "دقة التسديد من داخل المنطقة",
        "Shots from outside the penalty area": "التسديدات من خارج المنطقة",
        "Shots on target from outside the penalty area, %": "دقة التسديد من خارج المنطقة",
        "Shots on post / bar": "التسديدات على القائم أو العارضة",
        "Headers": "الضربات الرأسية",
        "Headers on target, %": "دقة الضربات الرأسية",
        "Goals by head": "الأهداف بالرأس",
        "Free-kick shots": "تسديدات الركلات الحرة",
        "Free-kick goals": "أهداف الركلات الحرة",
        "Shots in box share": "نسبة التسديدات من داخل المنطقة",
        "Passes": "التمريرات",
        "Passes accurate, %": "دقة التمرير",
        "Short passes": "التمريرات القصيرة",
        "Short passes accurate, %": "دقة التمريرات القصيرة",
        "Key passes": "التمريرات المفتاحية",
        "Crosses": "العرضيات",
        "Crosses accurate, %": "العرضيات الناجحة",
        "Progressive passes": "التمريرات التقدمية",
        "Long passes": "التمريرات الطويلة",
        "Passes into the penalty box": "التمريرات داخل منطقة الجزاء",
        "Passes for a shot": "التمريرات المؤدية إلى تسديدة",
        "Challenges": "الثنائيات",
        "Challenges won, %": "الثنائيات الناجحة",
        "Defensive challenges": "الثنائيات الدفاعية",
        "Defensive challenges won, %": "الثنائيات الدفاعية الناجحة",
        "Attacking challenges": "الثنائيات الهجومية",
        "Attacking challenges won, %": "الثنائيات الهجومية الناجحة",
        "Aerial challenges": "الثنائيات الهوائية",
        "Aerial challenges won, %": "الثنائيات الهوائية الناجحة",
        "Dribbles": "المراوغات",
        "Dribbles successful, %": "المراوغات الناجحة",
        "Tackles": "التدخلات",
        "Interceptions": "الاعتراضات",
        "xG (expected goals)": "الأهداف المتوقعة",
        "Final third entries": "دخول الثلث الأخير",
        "Lost balls": "الكرات المفقودة",
        "Lost balls in own half": "فقدان الكرة في نصف الملعب",
        "Ball recoveries": "استرجاع الكرة",
        "Ball recoveries in opponent's half": "استرجاع الكرة عاليا",
        "Actions in opponent's box": "الإجراءات داخل منطقة المنافس",
        "Actions": "الإجراءات بالكرة",
        "Actions successful, %": "الإجراءات الناجحة",
        "Actions in opponent's box successful, %": "الإجراءات الناجحة داخل منطقة المنافس",
        "Final third entries through pass": "الدخول إلى الثلث الأخير بالتمرير",
        "Final third entries through carry": "الدخول إلى الثلث الأخير بحمل الكرة",
        "Involvement in scoring attacks": "المشاركة في الهجمات التي انتهت بهدف",
        "Chances successful": "الفرص الناجحة",
        "Yellow cards": "البطاقات الصفراء",
        "Red cards": "البطاقات الحمراء",
        "Final third entries through pass, % of total": "نسبة الدخول بالتمرير",
        "Final third entries through carry, % of total": "نسبة الدخول بحمل الكرة",
    },
}


METRIC_DEFINITIONS = {
    "fr": {
        "Goals": "But marqué par le joueur : c’est l’impact décisif le plus direct.",
        "Assists": "Dernière passe donnée avant le but d’un partenaire. Exemple : le centre ou la passe qui conduit directement au but.",
        "Passes": "Nombre total de passes tentées pendant les minutes réellement jouées.",
        "Actions": "Nombre total d’actions avec ballon enregistrées pendant les minutes réellement jouées. Ce volume mesure l’implication, pas à lui seul la qualité.",
        "Actions successful, %": "Part des actions avec ballon réussies. Elle est toujours affichée sous la forme réussites/tentatives pour associer volume et efficacité.",
        "Passes accurate, %": "Part des passes arrivées à un partenaire. Exemple : 18/22 signifie 18 passes réussies sur 22.",
        "Progressive passes": "Passes qui font avancer nettement le ballon vers le but adverse et permettent de dépasser une zone ou une ligne.",
        "Progressive passes accurate, %": "Part des passes progressives arrivées à un partenaire ; elle mesure la qualité de la progression, pas seulement son volume.",
        "Key passes": "Dernière passe avant le tir d’un partenaire. Elle crée une possibilité de frappe, même si le tir ne devient pas un but.",
        "Passes for a shot": "Passes après lesquelles un partenaire déclenche un tir ; elles montrent la création concrète d’une occasion de frappe.",
        "Chances created": "Situations créées par le joueur qui donnent à un partenaire une véritable possibilité de conclure.",
        "Final third entries": "Actions qui font entrer le ballon dans le dernier tiers, la zone la plus proche du but adverse.",
        "Final third entries through pass": "Entrées dans le dernier tiers obtenues par une passe : elles montrent la capacité à faire progresser un partenaire ou le ballon vers la zone offensive.",
        "Final third entries through carry": "Entrées dans le dernier tiers obtenues en conduisant le ballon : elles montrent la capacité à gagner du terrain balle au pied.",
        "Passes forward to the final third": "Passes vers l’avant qui atteignent le dernier tiers et rapprochent l’équipe de la zone de création.",
        "Passes into the penalty box": "Passes qui trouvent ou recherchent un partenaire dans la surface de réparation adverse.",
        "Crosses": "Ballons envoyés depuis un côté vers une zone de finition dans ou autour de la surface.",
        "Crosses accurate, %": "Part des centres qui trouvent un partenaire. Exemple : 3/8 signifie 3 centres réussis sur 8.",
        "Challenges": "Tous les duels disputés contre un adversaire, au sol ou dans une lutte directe pour le ballon.",
        "Challenges won, %": "Part de tous les duels remportés. Toujours lire le pourcentage avec le volume : 1/1 n’a pas la même fiabilité que 8/10.",
        "Defensive challenges": "Duels engagés pour stopper, ralentir ou déposséder un adversaire.",
        "Defensive challenges won, %": "Part des duels défensifs remportés. Exemple : 6/8 indique une présence défensive solide sur huit situations.",
        "Attacking challenges": "Duels joués pour conserver le ballon, éliminer un adversaire ou faire avancer l’attaque.",
        "Attacking challenges won, %": "Part des duels offensifs remportés, avec le nombre de tentatives pour juger la fiabilité.",
        "Aerial challenges": "Duels disputés sur un ballon aérien.",
        "Aerial challenges won, %": "Part des duels aériens gagnés. Zéro duel signifie absence d’occasion observée, pas faiblesse.",
        "Dribbles": "Tentatives d’éliminer directement un adversaire avec le ballon.",
        "Dribbles successful, %": "Part des dribbles réussis ; elle mesure l’efficacité du un contre un.",
        "Dribbling in the final third": "Dribbles tentés dans le dernier tiers, là où éliminer un joueur peut créer une occasion.",
        "Interceptions": "Ballons coupés en anticipant une passe ou une trajectoire adverse.",
        "Ball recoveries": "Ballons récupérés par le joueur après une perte ou une action adverse.",
        "Ball recoveries in opponent's half": "Ballons récupérés haut, dans la moitié adverse, permettant souvent d’attaquer rapidement.",
        "Shots": "Nombre de tirs tentés ; il mesure la capacité à se mettre en position de frapper, pas seulement la finition.",
        "Shots on target, %": "Part des tirs cadrés. Un tir cadré oblige le gardien à intervenir ou entre dans le but.",
        "Shots from the penalty area": "Tirs pris dans la surface, généralement depuis des positions plus favorables que les tirs lointains.",
        "Shots on target from the penalty area, %": "Part des tirs pris dans la surface qui sont cadrés. Le volume mesure l’accès aux zones favorables ; le taux juge l’exécution.",
        "Shots from outside the penalty area": "Tirs pris hors de la surface. Ils montrent une menace à distance, mais proviennent en moyenne de positions moins favorables.",
        "Shots on target from outside the penalty area, %": "Part des tirs lointains cadrés, toujours lue avec le nombre de tentatives hors surface.",
        "Shots on post / bar": "Tirs ayant touché un poteau ou la barre : signal d’une finition proche du but, sans être compté comme réalisation.",
        "Headers": "Tentatives de finition de la tête. Pour un avant-centre, elles renseignent sur le placement aérien et l’accès aux centres.",
        "Headers on target, %": "Part des têtes cadrées, présentée avec le nombre de têtes tentées afin de ne pas surinterpréter un petit échantillon.",
        "Goals by head": "Buts inscrits de la tête. Ils précisent le mode de finition sans compter comme un but supplémentaire dans la note décisive.",
        "Free-kick shots": "Tirs tentés directement sur coup franc.",
        "Free-kick goals": "Buts inscrits directement sur coup franc ; ils sont déjà compris dans le total des buts.",
        "Shots in box share": "Part des tirs tentés dans la surface. Six tirs dans la surface sans but restent un signal positif de présence, avec une finition à améliorer.",
        "xG (expected goals)": "Qualité cumulée des tirs selon leur probabilité moyenne de devenir un but ; ce n’est pas une prédiction certaine.",
        "Actions in opponent's box": "Actions avec ballon réalisées dans la surface adverse ; elles mesurent la présence réelle dans la zone décisive.",
        "Actions in opponent's box successful, %": "Part des actions dans la surface adverse conservées ou réussies. Exemple : 4/4 signifie quatre actions utiles réussies dans la zone décisive.",
        "Involvement in scoring attacks": "Nombre d’attaques auxquelles le joueur a participé et qui ont abouti à un but ; ce signal complète buts et passes décisives.",
        "Tackles": "Tentatives d’intervention directe sur le porteur pour récupérer ou dégager le ballon.",
        "Tackles successful, %": "Part des tacles réussis, lue avec le nombre de tentatives.",
        "Long passes": "Passes longues tentées pour dépasser une pression, changer de zone ou accélérer la progression.",
        "Short passes": "Passes de courte distance utilisées pour conserver, fixer ou combiner avec les partenaires proches.",
        "Short passes accurate, %": "Part des passes courtes réussies, lue avec leur volume pour juger la qualité du jeu de liaison.",
        "Long passes accurate, %": "Part des passes longues arrivées à un partenaire.",
        "Super long passes": "Passes de très longue distance utilisées pour renverser le jeu ou attaquer un espace éloigné.",
        "Super long passes accurate, %": "Part des passes très longues arrivées à un partenaire.",
        "Lost balls": "Ballons perdus par le joueur. Le lieu, la pression et le niveau de risque doivent être confirmés en vidéo.",
        "Lost balls in own half": "Ballons perdus dans son propre camp, où une perte peut exposer plus directement l’équipe.",
        "Index": "Indice synthétique du match. Son rang dans l’équipe et la rencontre sert de repère global pour le verdict.",
    },
    "en": {
        "Goals": "A goal scored by the player: the most direct decisive contribution.",
        "Assists": "The final pass before a team-mate scores.",
        "Actions": "All recorded on-ball actions during the minutes actually played; volume measures involvement, not quality by itself.",
        "Actions successful, %": "The share of on-ball actions completed successfully, always shown with successes and attempts.",
        "Passes accurate, %": "The share of passes reaching a team-mate; 18/22 means 18 completed passes from 22 attempts.",
        "Progressive passes": "Passes that move the ball substantially towards goal and bypass a zone or line.",
        "Progressive passes accurate, %": "The completion rate of progressive passes, measuring quality as well as volume.",
        "Key passes": "The final team-mate pass before a shot; it creates a shooting opportunity even when no goal follows.",
        "Passes for a shot": "Passes followed by a team-mate shot, showing concrete chance creation.",
        "Final third entries": "Actions moving the ball into the attacking third, closest to the opposition goal.",
        "Final third entries through pass": "Final-third entries produced by a pass, showing the ability to progress a team-mate or the ball into the attacking zone.",
        "Final third entries through carry": "Final-third entries produced by carrying the ball, showing territorial gain at the player's feet.",
        "Passes into the penalty box": "Passes seeking or finding a team-mate inside the opposition box.",
        "Challenges won, %": "The share of all duels won; always read it with the attempt count because 1/1 is less reliable than 8/10.",
        "Defensive challenges": "Duels used to stop, delay or dispossess an opponent.",
        "Defensive challenges won, %": "The share of defensive duels won, shown with successes and attempts.",
        "Attacking challenges won, %": "The share of attacking duels won while protecting or advancing the ball.",
        "Aerial challenges won, %": "The share of aerial duels won; no duel means no observed opportunity, not weakness.",
        "Dribbles successful, %": "The success rate of attempts to beat an opponent directly on the ball.",
        "Crosses accurate, %": "The share of crosses finding a team-mate; 3/8 means three completed crosses from eight.",
        "Interceptions": "Passes or trajectories cut out through anticipation.",
        "Ball recoveries": "Possessions recovered after a loss or opposition action.",
        "xG (expected goals)": "The combined average scoring probability of the player's shots; it is not a certain prediction.",
        "Shots": "Shot attempts show the ability to reach shooting positions, not only finishing quality.",
        "Shots on target, %": "The share of shots forcing a save or entering the goal.",
        "Shots on target from the penalty area, %": "The share of box shots on target; volume shows access to favourable zones while the rate assesses execution.",
        "Shots from outside the penalty area": "Shots attempted from outside the box, showing long-range threat from generally lower-quality locations.",
        "Shots on target from outside the penalty area, %": "The share of long-range attempts on target, always read with the outside-box attempt count.",
        "Shots on post / bar": "Shots hitting a post or the crossbar: near-goal finishing evidence, but not a scored goal.",
        "Headers": "Headed shot attempts, showing aerial positioning and access to crosses for a centre-forward.",
        "Headers on target, %": "The share of headed attempts on target, always shown with the number of headers.",
        "Goals by head": "Goals scored with a header; this identifies the finishing method without counting an extra goal in decisive impact.",
        "Free-kick shots": "Direct free-kick attempts.",
        "Free-kick goals": "Direct free-kick goals, already included in the player's total goals.",
        "Short passes": "Short-distance passes used to retain possession, fix an opponent or combine with nearby team-mates.",
        "Short passes accurate, %": "The completion rate of short passes, read with their volume to assess link-play quality.",
        "Actions in opponent's box": "Recorded on-ball actions in the opposition box, measuring presence in the decisive area.",
        "Actions in opponent's box successful, %": "The share of opposition-box actions completed successfully, shown with successes and attempts.",
        "Involvement in scoring attacks": "Attacking sequences involving the player that ended in a goal, complementing goals and assists.",
        "Tackles": "Direct attempts to win or clear the ball from an opponent in possession.",
        "Tackles successful, %": "The share of tackles completed successfully, read with the attempt count.",
        "Long passes": "Long deliveries used to bypass pressure, switch zones or accelerate progression.",
        "Long passes accurate, %": "The share of long passes reaching a team-mate.",
        "Super long passes": "Very long deliveries used to switch play or attack distant space.",
        "Super long passes accurate, %": "The share of very long passes reaching a team-mate.",
        "Shots in box share": "The share of shots from inside the box; six box shots without a goal still show strong presence but weaker finishing.",
        "Index": "Composite match index; its team and match rank provides a global reference for the verdict.",
    },
    "ar": {
        "Goals": "هدف سجله اللاعب وهو أوضح مساهمة حاسمة.",
        "Assists": "آخر تمريرة قبل تسجيل الزميل للهدف.",
        "Actions": "كل الإجراءات المسجلة بالكرة خلال الدقائق الفعلية وتوضح حجم المشاركة لا الجودة وحدها.",
        "Actions successful, %": "نسبة الإجراءات الناجحة بالكرة وتعرض دائما مع عدد النجاحات والمحاولات.",
        "Passes accurate, %": "نسبة التمريرات التي وصلت إلى زميل مع عرض عدد المحاولات والتمريرات الناجحة.",
        "Progressive passes": "تمريرات تدفع الكرة بوضوح نحو مرمى المنافس وتتجاوز منطقة أو خطا.",
        "Key passes": "آخر تمريرة قبل تسديدة زميل حتى إن لم تتحول التسديدة إلى هدف.",
        "Passes for a shot": "تمريرات تبعتها تسديدة من زميل وتوضح صناعة فرصة فعلية.",
        "Final third entries": "إجراءات تنقل الكرة إلى الثلث الهجومي الأقرب إلى مرمى المنافس.",
        "Final third entries through pass": "دخول الثلث الأخير بتمريرة تتقدم بالكرة أو بزميل نحو المنطقة الهجومية.",
        "Final third entries through carry": "دخول الثلث الأخير عبر حمل الكرة والتقدم بها.",
        "Passes into the penalty box": "تمريرات تبحث عن زميل أو تصل إليه داخل منطقة جزاء المنافس.",
        "Challenges won, %": "نسبة الثنائيات الناجحة وتقرأ دائما مع عدد المحاولات لأن 1/1 أقل موثوقية من 8/10.",
        "Defensive challenges": "ثنائيات لإيقاف المنافس أو إبطائه أو افتكاك الكرة منه.",
        "Defensive challenges won, %": "نسبة الثنائيات الدفاعية الناجحة مع عدد النجاحات والمحاولات.",
        "Aerial challenges won, %": "نسبة الثنائيات الهوائية الناجحة وغياب المحاولة لا يعني الضعف.",
        "Dribbles successful, %": "نسبة نجاح محاولات تجاوز المنافس بالكرة.",
        "Crosses accurate, %": "نسبة العرضيات التي وصلت إلى زميل.",
        "xG (expected goals)": "مجموع متوسط احتمالات تحول تسديدات اللاعب إلى أهداف وليس توقعا مؤكدا.",
        "Shots": "عدد التسديدات ويقيس الوصول إلى وضعية التسديد وليس الإنهاء فقط.",
        "Shots on target from the penalty area, %": "نسبة التسديدات المؤطرة من داخل المنطقة مع عرض عدد المحاولات.",
        "Shots from outside the penalty area": "التسديدات من خارج منطقة الجزاء وتوضح التهديد من المسافة.",
        "Shots on target from outside the penalty area, %": "نسبة التسديدات البعيدة المؤطرة مع عرض عدد المحاولات.",
        "Shots on post / bar": "التسديدات التي اصطدمت بالقائم أو العارضة وهي اقتراب من التسجيل وليست هدفا.",
        "Headers": "محاولات التسديد بالرأس وتوضح التمركز الهوائي والوصول إلى العرضيات.",
        "Headers on target, %": "نسبة الضربات الرأسية المؤطرة مع عدد المحاولات.",
        "Goals by head": "الأهداف المسجلة بالرأس وهي ضمن العدد الإجمالي للأهداف.",
        "Free-kick shots": "التسديدات المباشرة من الركلات الحرة.",
        "Free-kick goals": "الأهداف المباشرة من الركلات الحرة وهي ضمن إجمالي الأهداف.",
        "Short passes": "التمريرات القصيرة للاحتفاظ بالكرة أو الربط مع الزملاء القريبين.",
        "Short passes accurate, %": "نسبة نجاح التمريرات القصيرة مع عرض حجمها.",
        "Actions in opponent's box": "إجراءات بالكرة داخل منطقة جزاء المنافس وتقيس الحضور في المنطقة الحاسمة.",
        "Actions in opponent's box successful, %": "نسبة الإجراءات الناجحة داخل منطقة المنافس مع عدد النجاحات والمحاولات.",
        "Involvement in scoring attacks": "هجمات شارك فيها اللاعب وانتهت بهدف وتكمل قراءة الأهداف والتمريرات الحاسمة.",
        "Index": "مؤشر أداء مركب ويستخدم ترتيبه داخل الفريق والمباراة مرجعا عاما للخلاصة.",
    },
}


RATE_WEIGHTS = {
    "Chances successful, %": "Chances",
    "Passes accurate, %": "Passes",
    "Short passes accurate, %": "Short passes",
    "Key passes accurate, %": "Key passes",
    "Crosses accurate, %": "Crosses",
    "Progressive passes accurate, %": "Progressive passes",
    "Long passes accurate, %": "Long passes",
    "Super long passes accurate, %": "Super long passes",
    "Passes forward to the final third accurate, %": "Passes forward to the final third",
    "Passes into the penalty box accurate, %": "Passes into the penalty box",
    "Challenges won, %": "Challenges",
    "Defensive challenges won, %": "Defensive challenges",
    "Attacking challenges won, %": "Attacking challenges",
    "Aerial challenges won, %": "Aerial challenges",
    "Dribbles successful, %": "Dribbles",
    "Dribbling in the final third successful, %": "Dribbling in the final third",
    "Tackles successful, %": "Tackles",
    "Shots on target, %": "Shots",
    "Shots on target from the penalty area, %": "Shots from the penalty area",
    "Shots on target from outside the penalty area, %": "Shots from outside the penalty area",
    "Headers on target, %": "Headers",
    "Actions successful, %": "Actions",
    "Actions in opponent's box successful, %": "Actions in opponent's box",
}


# Stable order from the enriched SportsBase "Players" table.  Any future columns
# present in a row are appended automatically, so the report never loses data.
SPORTSBASE_PLAYER_COLUMNS = (
    "№", "Player", "Team", "Index", "Minutes played", "Position",
    "Goals", "Assists", "Mistakes leading to goals", "Mistakes leading to chances",
    "Chances", "Chances successful", "Chances successful, %", "Chances created",
    "Involvement in scoring attacks", "Yellow cards", "Red cards", "Fouls",
    "Fouls suffered", "Shots", "Goals by head", "Free-kick shots",
    "Free-kick goals", "Passes", "Passes accurate, %", "Key passes",
    "Key passes accurate, %", "Crosses", "Crosses accurate, %",
    "Progressive passes", "Progressive passes accurate, %", "Progressive open passes",
    "Short passes", "Short passes accurate, %", "Long passes",
    "Long passes accurate, %", "Passes forward to the final third",
    "Passes forward to the final third accurate, %", "Passes into the penalty box",
    "Passes into the penalty box accurate, %", "Passes for a shot", "Super long passes",
    "Super long passes accurate, %", "xG (expected goals)", "Challenges",
    "Challenges won, %", "Defensive challenges", "Defensive challenges won, %",
    "Attacking challenges", "Attacking challenges won, %", "Aerial challenges",
    "Aerial challenges won, %", "Dribbles", "Dribbles successful, %",
    "Dribbling in the final third", "Dribbling in the final third successful, %",
    "Tackles", "Tackles successful, %", "Interceptions", "Loose ball recoveries",
    "Actions", "Actions successful, %", "Actions in opponent's box",
    "Actions in opponent's box successful, %", "Shots from the penalty area",
    "Shots on target from the penalty area, %", "Shots from outside the penalty area",
    "Shots on target from outside the penalty area, %", "Headers",
    "Headers on target, %", "Shots on target, %", "Shots on post / bar",
    "Final third entries", "Final third entries through pass",
    "Final third entries through pass, % of total", "Final third entries through carry",
    "Final third entries through carry, % of total", "Lost balls", "Lost balls in own half",
    "Ball recoveries", "Ball recoveries in opponent's half",
)

PERCENT_DENOMINATORS = {
    **RATE_WEIGHTS,
    "Final third entries through pass, % of total": "Final third entries",
    "Final third entries through carry, % of total": "Final third entries",
}

APPENDIX_CATEGORY_LABELS = {
    "fr": {
        "identity": "Profil et repères",
        "decisive": "Impact décisif et occasions",
        "finishing": "Tirs et présence dans la surface",
        "creation": "Création, passes et progression",
        "duels": "Duels, défense et un contre un",
        "possession": "Possession, récupérations et discipline",
        "other": "Autres données du match",
    },
    "en": {
        "identity": "Profile and reference points",
        "decisive": "Decisive impact and chances",
        "finishing": "Shooting and box presence",
        "creation": "Creation, passing and progression",
        "duels": "Duels, defending and one-v-one",
        "possession": "Possession, recoveries and discipline",
        "other": "Other match data",
    },
    "ar": {
        "identity": "الملف والمؤشرات العامة",
        "decisive": "التأثير الحاسم والفرص",
        "finishing": "التسديد والحضور داخل المنطقة",
        "creation": "الصناعة والتمرير والتقدم",
        "duels": "الثنائيات والدفاع والمواجهة الفردية",
        "possession": "الاستحواذ والاسترجاع والانضباط",
        "other": "بيانات المباراة الأخرى",
    },
}

APPENDIX_CATEGORIES = {
    "identity": {"№", "Player", "Team", "Index", "Minutes played", "Position"},
    "decisive": {
        "Goals", "Assists", "Mistakes leading to goals", "Mistakes leading to chances",
        "Chances", "Chances successful", "Chances successful, %", "Chances created",
        "Involvement in scoring attacks",
    },
    "finishing": {
        "Shots", "Shots on target", "Shots on target, %", "Goals by head",
        "Free-kick shots", "Free-kick goals", "Shots from the penalty area",
        "Shots on target from the penalty area, %", "Shots from outside the penalty area",
        "Shots on target from outside the penalty area, %", "Headers",
        "Headers on target, %", "Shots on post / bar", "xG (expected goals)",
        "Actions in opponent's box", "Actions in opponent's box successful, %",
    },
    "creation": {
        "Passes", "Passes accurate, %", "Short passes", "Short passes accurate, %",
        "Key passes", "Key passes accurate, %",
        "Crosses", "Crosses accurate, %", "Progressive passes",
        "Progressive passes accurate, %", "Progressive open passes", "Long passes",
        "Long passes accurate, %", "Super long passes", "Super long passes accurate, %",
        "Passes forward to the final third", "Passes forward to the final third accurate, %",
        "Passes into the penalty box", "Passes into the penalty box accurate, %",
        "Passes for a shot", "Final third entries", "Final third entries through pass",
        "Final third entries through pass, % of total", "Final third entries through carry",
        "Final third entries through carry, % of total",
    },
    "duels": {
        "Challenges", "Challenges won, %", "Defensive challenges",
        "Defensive challenges won, %", "Attacking challenges",
        "Attacking challenges won, %", "Aerial challenges", "Aerial challenges won, %",
        "Dribbles", "Dribbles successful, %", "Dribbling in the final third",
        "Dribbling in the final third successful, %", "Tackles", "Tackles successful, %",
        "Interceptions", "Loose ball recoveries",
    },
    "possession": {
        "Lost balls", "Lost balls in own half", "Ball recoveries",
        "Ball recoveries in opponent's half", "Actions", "Actions successful, %",
        "Fouls", "Fouls suffered", "Yellow cards", "Red cards",
    },
}


POSITION_GROUPS = {
    "GK": "goalkeeper",
    "CB": "centre_back",
    "LCB": "centre_back",
    "RCB": "centre_back",
    "LB": "full_back",
    "RB": "full_back",
    "LWB": "wing_back",
    "RWB": "wing_back",
    "CDM": "holding_midfielder",
    "DM": "holding_midfielder",
    "LDM": "holding_midfielder",
    "RDM": "holding_midfielder",
    "CM": "box_to_box_midfielder",
    "LCM": "box_to_box_midfielder",
    "RCM": "box_to_box_midfielder",
    "CAM": "attacking_midfielder",
    "AM": "attacking_midfielder",
    "SS": "attacking_midfielder",
    "LAM": "winger",
    "RAM": "winger",
    "LM": "winger",
    "RM": "winger",
    "LW": "winger",
    "RW": "winger",
    "CF": "forward",
    "LCF": "forward",
    "RCF": "forward",
    "ST": "forward",
}

DIMENSION_LABELS = {
    "fr": {
        "distribution": "Distribution",
        "space_control": "Couverture de l’espace",
        "risk_control": "Gestion du risque",
        "build_up": "Première relance",
        "ground_control": "Contrôle au sol",
        "aerial_control": "Maîtrise aérienne",
        "progression": "Progression",
        "defending": "Défense",
        "delivery": "Qualité des centres",
        "attacking_support": "Soutien offensif",
        "ball_security": "Sécurité avec ballon",
        "protection": "Protection de l’axe",
        "circulation": "Circulation",
        "switching": "Changement de jeu",
        "transition_control": "Contrôle des transitions",
        "final_third_presence": "Présence dans le dernier tiers",
        "creation": "Création",
        "duel_balance": "Équilibre dans les duels",
        "between_lines": "Jeu entre les lignes",
        "one_v_one": "Un contre un",
        "goal_threat": "Menace de but",
        "counterpress": "Contre-pressing",
        "box_presence": "Présence dans la surface",
        "finishing": "Finition",
        "link_play": "Jeu de liaison",
        "direct_play": "Jeu direct et duels",
        "defensive_work": "Travail sans ballon",
        "impact": "Impact décisif et création",
        "involvement": "Implication dans le jeu",
    },
    "en": {
        "distribution": "Distribution",
        "space_control": "Space control",
        "risk_control": "Risk management",
        "build_up": "First build-up",
        "ground_control": "Ground control",
        "aerial_control": "Aerial control",
        "progression": "Progression",
        "defending": "Defending",
        "delivery": "Crossing delivery",
        "attacking_support": "Attacking support",
        "ball_security": "Ball security",
        "protection": "Central protection",
        "circulation": "Circulation",
        "switching": "Switching play",
        "transition_control": "Transition control",
        "final_third_presence": "Final-third presence",
        "creation": "Creation",
        "duel_balance": "Duel balance",
        "between_lines": "Between-the-lines play",
        "one_v_one": "One-v-one",
        "goal_threat": "Goal threat",
        "counterpress": "Counterpress",
        "box_presence": "Box presence",
        "finishing": "Finishing",
        "link_play": "Link play",
        "direct_play": "Direct play and duels",
        "defensive_work": "Out-of-possession work",
        "impact": "Decisive impact and creation",
        "involvement": "Involvement in play",
    },
    "ar": {
        "distribution": "التوزيع",
        "space_control": "تغطية المساحة",
        "risk_control": "إدارة المخاطر",
        "build_up": "بناء اللعب الأول",
        "ground_control": "السيطرة الأرضية",
        "aerial_control": "السيطرة الهوائية",
        "progression": "التقدم بالكرة",
        "defending": "الدفاع",
        "delivery": "جودة العرضيات",
        "attacking_support": "الدعم الهجومي",
        "ball_security": "الأمان بالكرة",
        "protection": "حماية العمق",
        "circulation": "تدوير الكرة",
        "switching": "تغيير جهة اللعب",
        "transition_control": "التحكم في التحولات",
        "final_third_presence": "الحضور في الثلث الأخير",
        "creation": "صناعة اللعب",
        "duel_balance": "التوازن في الثنائيات",
        "between_lines": "اللعب بين الخطوط",
        "one_v_one": "واحد ضد واحد",
        "goal_threat": "الخطورة التهديفية",
        "counterpress": "الضغط العكسي",
        "box_presence": "الحضور داخل المنطقة",
        "finishing": "الإنهاء",
        "link_play": "الربط الهجومي",
        "direct_play": "اللعب المباشر والثنائيات",
        "defensive_work": "العمل دون كرة",
        "impact": "التأثير الحاسم وصناعة اللعب",
        "involvement": "المشاركة في اللعب",
    },
}


def _s(
    metric,
    kind="volume",
    *,
    target=None,
    weight=1.0,
    min_minutes=0,
    zero_is_no_opportunity=False,
):
    return {
        "metric": metric,
        "kind": kind,
        "target": target,
        "weight": weight,
        "min_minutes": min_minutes,
        "zero_is_no_opportunity": zero_is_no_opportunity,
    }


ROLE_CONFIGS = {
    "goalkeeper": {
        "weights": {"risk_control": 25, "distribution": 20, "involvement": 20, "progression": 15, "space_control": 15, "impact": 5},
        "dimensions": (
            ("distribution", _s("Passes", target=30), _s("Passes accurate, %", "pass_cb", weight=1.5), _s("Long passes", target=10), _s("Long passes accurate, %", "long_pass")),
            ("progression", _s("Progressive passes", target=6), _s("Progressive passes accurate, %", "progressive_rate"), _s("Passes forward to the final third", target=6), _s("Passes forward to the final third accurate, %", "progressive_rate"), _s("Super long passes", target=5), _s("Super long passes accurate, %", "long_pass")),
            ("space_control", _s("Interceptions", target=1), _s("Ball recoveries", target=5)),
            ("risk_control", _s("Lost balls in own half", "negative", target=2, weight=1.5), _s("Mistakes leading to chances", "mistake", weight=2), _s("Mistakes leading to goals", "mistake_goal", weight=3)),
        ),
    },
    "centre_back": {
        "weights": {"defending": 25, "progression": 20, "aerial_control": 15, "build_up": 15, "involvement": 10, "risk_control": 10, "impact": 5},
        "dimensions": (
            ("defending", _s("Defensive challenges", target=5), _s("Defensive challenges won, %", "def_duel", weight=2), _s("Tackles", target=4), _s("Tackles successful, %", "def_duel", weight=1.5), _s("Interceptions", target=5)),
            ("aerial_control", _s("Aerial challenges", target=4, zero_is_no_opportunity=True), _s("Aerial challenges won, %", "aerial", weight=2)),
            ("build_up", _s("Passes", target=45), _s("Passes accurate, %", "pass_cb", weight=2)),
            ("progression", _s("Progressive passes", target=8), _s("Progressive passes accurate, %", "progressive_rate", weight=1.5), _s("Long passes", target=7), _s("Long passes accurate, %", "long_pass"), _s("Super long passes", target=3), _s("Super long passes accurate, %", "long_pass")),
            ("risk_control", _s("Lost balls in own half", "negative", target=2), _s("Mistakes leading to chances", "mistake", weight=2), _s("Mistakes leading to goals", "mistake_goal", weight=3)),
        ),
    },
    "full_back": {
        "weights": {"defending": 20, "progression": 15, "attacking_support": 15, "involvement": 15, "impact": 15, "delivery": 10, "ball_security": 10},
        "dimensions": (
            ("defending", _s("Defensive challenges", target=6), _s("Defensive challenges won, %", "def_duel", weight=2), _s("Tackles", target=4), _s("Tackles successful, %", "def_duel"), _s("Interceptions", target=4)),
            ("progression", _s("Progressive passes", target=6), _s("Progressive passes accurate, %", "progressive_rate"), _s("Final third entries", target=5), _s("Final third entries through pass", target=3), _s("Final third entries through carry", target=2)),
            ("delivery", _s("Crosses", target=4), _s("Crosses accurate, %", "cross", weight=2), _s("Passes into the penalty box", target=3), _s("Passes into the penalty box accurate, %", "action_rate")),
            ("ball_security", _s("Passes", target=40), _s("Passes accurate, %", "pass_general", weight=2), _s("Lost balls in own half", "negative", target=2)),
            ("attacking_support", _s("Actions in opponent's box", target=3), _s("Actions in opponent's box successful, %", "action_rate", weight=1.5), _s("Dribbles", target=3), _s("Dribbles successful, %", "dribble"), _s("Passes for a shot", target=1)),
        ),
    },
    "wing_back": {
        "weights": {"attacking_support": 20, "progression": 15, "delivery": 15, "defending": 15, "impact": 15, "involvement": 10, "ball_security": 10},
        "dimensions": (
            ("progression", _s("Progressive passes", target=6), _s("Progressive passes accurate, %", "progressive_rate"), _s("Final third entries", target=6), _s("Final third entries through pass", target=3), _s("Final third entries through carry", target=3)),
            ("delivery", _s("Crosses", target=5), _s("Crosses accurate, %", "cross", weight=2), _s("Passes into the penalty box", target=3), _s("Passes into the penalty box accurate, %", "action_rate"), _s("Passes for a shot", target=2)),
            ("attacking_support", _s("Actions in opponent's box", target=4), _s("Actions in opponent's box successful, %", "action_rate", weight=1.5), _s("Dribbles", target=4), _s("Dribbles successful, %", "dribble"), _s("Dribbling in the final third", target=2), _s("Dribbling in the final third successful, %", "dribble")),
            ("defending", _s("Defensive challenges", target=5), _s("Defensive challenges won, %", "def_duel", weight=2), _s("Tackles", target=3), _s("Tackles successful, %", "def_duel"), _s("Interceptions", target=3)),
            ("ball_security", _s("Passes", target=35), _s("Passes accurate, %", "pass_general", weight=2), _s("Lost balls in own half", "negative", target=2)),
        ),
    },
    "holding_midfielder": {
        "weights": {"protection": 20, "involvement": 20, "circulation": 15, "progression": 15, "switching": 10, "risk_control": 10, "impact": 10},
        "dimensions": (
            ("protection", _s("Defensive challenges", target=7), _s("Defensive challenges won, %", "def_duel", weight=2), _s("Tackles", target=5), _s("Tackles successful, %", "def_duel"), _s("Interceptions", target=5), _s("Ball recoveries", target=8)),
            ("circulation", _s("Passes", target=50), _s("Passes accurate, %", "pass_safe", weight=2)),
            ("progression", _s("Progressive passes", target=8), _s("Progressive passes accurate, %", "progressive_rate"), _s("Passes forward to the final third", target=7), _s("Passes forward to the final third accurate, %", "progressive_rate"), _s("Final third entries", target=4), _s("Final third entries through pass", target=3), _s("Final third entries through carry", target=1)),
            ("switching", _s("Long passes", target=6), _s("Long passes accurate, %", "long_pass", weight=2), _s("Super long passes", target=3), _s("Super long passes accurate, %", "long_pass")),
            ("risk_control", _s("Lost balls in own half", "negative", target=2, weight=2), _s("Mistakes leading to chances", "mistake", weight=2), _s("Mistakes leading to goals", "mistake_goal", weight=3)),
        ),
    },
    "box_to_box_midfielder": {
        "weights": {"impact": 20, "involvement": 20, "final_third_presence": 20, "progression": 15, "circulation": 10, "duel_balance": 10, "creation": 5},
        "dimensions": (
            ("circulation", _s("Passes", target=45), _s("Passes accurate, %", "pass_general", weight=2), _s("Lost balls", "negative", target=8)),
            ("progression", _s("Progressive passes", target=8), _s("Progressive passes accurate, %", "progressive_rate"), _s("Final third entries", target=6), _s("Final third entries through pass", target=3), _s("Final third entries through carry", target=3)),
            ("final_third_presence", _s("Actions in opponent's box", target=3, weight=1.5), _s("Actions in opponent's box successful, %", "action_rate", weight=1.5), _s("Shots", target=2), _s("Dribbles", "positive_volume", target=3), _s("Dribbles successful, %", "dribble")),
            ("creation", _s("Passes for a shot", target=2), _s("Passes into the penalty box", target=3), _s("Passes into the penalty box accurate, %", "action_rate")),
            ("duel_balance", _s("Defensive challenges", target=6), _s("Defensive challenges won, %", "def_duel"), _s("Tackles", target=4), _s("Tackles successful, %", "def_duel"), _s("Interceptions", target=3), _s("Ball recoveries", target=7), _s("Ball recoveries in opponent's half", target=2)),
        ),
    },
    "attacking_midfielder": {
        "weights": {"impact": 30, "creation": 20, "involvement": 15, "between_lines": 10, "goal_threat": 10, "ball_security": 10, "counterpress": 5},
        "dimensions": (
            ("between_lines", _s("Progressive passes", target=7), _s("Progressive passes accurate, %", "progressive_rate"), _s("Final third entries", target=7), _s("Final third entries through pass", target=4), _s("Final third entries through carry", target=3), _s("Dribbles", target=4), _s("Dribbles successful, %", "dribble")),
            ("creation", _s("Passes for a shot", target=3), _s("Passes into the penalty box", target=4), _s("Passes into the penalty box accurate, %", "action_rate")),
            ("goal_threat", _s("Shots", target=3), _s("Shots from the penalty area", target=2), _s("Shots on target from the penalty area, %", "shot_target", weight=1.5), _s("Shots from outside the penalty area", target=1, zero_is_no_opportunity=True), _s("Shots on target from outside the penalty area, %", "shot_target"), _s("Actions in opponent's box", target=5), _s("Actions in opponent's box successful, %", "action_rate", weight=1.5)),
            ("ball_security", _s("Passes", target=40), _s("Passes accurate, %", "pass_general"), _s("Lost balls", "negative", target=9)),
            ("counterpress", _s("Ball recoveries in opponent's half", target=3), _s("Defensive challenges", target=4), _s("Defensive challenges won, %", "def_duel")),
        ),
    },
    "winger": {
        "weights": {"impact": 30, "one_v_one": 20, "creation": 15, "involvement": 15, "goal_threat": 10, "progression": 5, "defensive_work": 5},
        "dimensions": (
            ("one_v_one", _s("Dribbles", target=5), _s("Dribbles successful, %", "dribble", weight=2), _s("Dribbling in the final third", target=3), _s("Dribbling in the final third successful, %", "dribble"), _s("Fouls suffered", target=2)),
            ("creation", _s("Passes for a shot", target=2), _s("Crosses", target=4), _s("Crosses accurate, %", "cross"), _s("Passes into the penalty box", target=3), _s("Passes into the penalty box accurate, %", "action_rate")),
            ("goal_threat", _s("Shots", target=3), _s("Shots from the penalty area", target=2), _s("Shots on target from the penalty area, %", "shot_target", weight=1.5), _s("Shots from outside the penalty area", target=1, zero_is_no_opportunity=True), _s("Shots on target from outside the penalty area, %", "shot_target"), _s("Shots in box share", "shot_location"), _s("Actions in opponent's box", target=6), _s("Actions in opponent's box successful, %", "action_rate", weight=1.5)),
            ("progression", _s("Progressive passes", target=5), _s("Progressive passes accurate, %", "progressive_rate"), _s("Final third entries", target=7), _s("Final third entries through pass", target=3), _s("Final third entries through carry", target=4)),
            ("defensive_work", _s("Ball recoveries in opponent's half", target=2), _s("Defensive challenges", target=3), _s("Lost balls", "negative", target=9)),
        ),
    },
    "forward": {
        "weights": {"impact": 35, "box_presence": 22, "finishing": 18, "involvement": 10, "link_play": 5, "direct_play": 5, "defensive_work": 5},
        "dimensions": (
            ("box_presence", _s("Actions in opponent's box", target=8, weight=2), _s("Actions in opponent's box successful, %", "action_rate", weight=1.5), _s("Shots", target=3), _s("Shots from the penalty area", target=3, weight=2), _s("Shots in box share", "shot_location")),
            ("finishing", _s("Shots on target, %", "shot_target", weight=1.5), _s("Shots on target from the penalty area, %", "shot_target", weight=2.5), _s("Shots on target from outside the penalty area, %", "shot_target", weight=0.5), _s("Headers", target=2, zero_is_no_opportunity=True, weight=1.5), _s("Headers on target, %", "shot_target", weight=2), _s("Shots on post / bar", "positive_volume", target=1, weight=0.5)),
            ("link_play", _s("Passes", target=22), _s("Passes accurate, %", "pass_forward"), _s("Short passes", target=15, weight=0.75), _s("Short passes accurate, %", "pass_safe", weight=0.75), _s("Passes for a shot", target=1)),
            ("direct_play", _s("Attacking challenges", target=6), _s("Attacking challenges won, %", "att_duel", weight=2), _s("Aerial challenges", target=4, zero_is_no_opportunity=True), _s("Aerial challenges won, %", "aerial"), _s("Dribbles", target=3), _s("Dribbles successful, %", "dribble"), _s("Fouls suffered", target=2)),
            ("defensive_work", _s("Defensive challenges", target=4), _s("Defensive challenges won, %", "def_duel", weight=2), _s("Ball recoveries in opponent's half", target=2), _s("Lost balls", "negative", target=8)),
        ),
    },
}


IMPACT_SPECS = {
    # A decisive action is assessed only when it happened.  A zero therefore
    # never creates an artificial weakness, while a goal, assist or creative
    # action contributes visibly to the mission score for every position.
    "goalkeeper": (
        _s("Goals", "positive_decisive", weight=3),
        _s("Assists", "positive_decisive", weight=3),
        _s("Key passes", "positive_volume", target=1, weight=2),
        _s("Chances created", "positive_volume", target=1, weight=2),
        _s("Involvement in scoring attacks", "positive_volume", target=1, weight=2),
    ),
    "centre_back": (
        _s("Goals", "positive_decisive", weight=3),
        _s("Assists", "positive_decisive", weight=3),
        _s("Key passes", "positive_volume", target=1, weight=1.5),
        _s("Chances created", "positive_volume", target=1),
        _s("Dribbles", "positive_volume", target=2),
        _s("Dribbles successful, %", "dribble"),
        _s("Involvement in scoring attacks", "positive_volume", target=1, weight=1.5),
    ),
    "full_back": (
        _s("Goals", "positive_decisive", weight=3),
        _s("Assists", "positive_decisive", weight=3),
        _s("Key passes", "positive_volume", target=2, weight=2),
        _s("Chances created", "positive_volume", target=1, weight=1.5),
        _s("Chances", "positive_volume", target=1),
        _s("Chances successful, %", "finishing_rate"),
        _s("Involvement in scoring attacks", "positive_volume", target=1, weight=2),
        _s("xG (expected goals)", "positive_decimal_volume", target=0.10, weight=1.5),
    ),
    "wing_back": (
        _s("Goals", "positive_decisive", weight=3),
        _s("Assists", "positive_decisive", weight=3),
        _s("Key passes", "positive_volume", target=2, weight=2),
        _s("Chances created", "positive_volume", target=2, weight=2),
        _s("Chances", "positive_volume", target=2),
        _s("Chances successful, %", "finishing_rate"),
        _s("Involvement in scoring attacks", "positive_volume", target=1, weight=2),
        _s("xG (expected goals)", "positive_decimal_volume", target=0.15, weight=1.5),
    ),
    "holding_midfielder": (
        _s("Goals", "positive_decisive", weight=3),
        _s("Assists", "positive_decisive", weight=3),
        _s("Key passes", "positive_volume", target=1, weight=2),
        _s("Chances created", "positive_volume", target=1, weight=1.5),
        _s("Dribbles", "positive_volume", target=2),
        _s("Dribbles successful, %", "dribble"),
        _s("Chances", "positive_volume", target=1),
        _s("Involvement in scoring attacks", "positive_volume", target=1, weight=2),
    ),
    "box_to_box_midfielder": (
        _s("Goals", "positive_decisive", weight=4),
        _s("Assists", "positive_decisive", weight=3.5),
        _s("Key passes", "positive_volume", target=2, weight=2.5),
        _s("Chances created", "positive_volume", target=2, weight=2),
        _s("Chances", "positive_volume", target=2, weight=1.5),
        _s("Chances successful, %", "finishing_rate"),
        _s("Involvement in scoring attacks", "positive_volume", target=1, weight=2),
        _s("xG (expected goals)", "decimal_volume", target=0.15, weight=2),
    ),
    "attacking_midfielder": (
        _s("Goals", "positive_decisive", weight=4),
        _s("Assists", "positive_decisive", weight=4),
        _s("Key passes", "positive_volume", target=3, weight=3),
        _s("Chances created", "positive_volume", target=2, weight=2.5),
        _s("Chances", "positive_volume", target=2, weight=2),
        _s("Chances successful, %", "finishing_rate", weight=1.5),
        _s("Involvement in scoring attacks", "positive_volume", target=2, weight=2),
        _s("xG (expected goals)", "decimal_volume", target=0.25, weight=2.5),
    ),
    "winger": (
        _s("Goals", "positive_decisive", weight=4),
        _s("Assists", "positive_decisive", weight=4),
        _s("Key passes", "positive_volume", target=2, weight=3),
        _s("Chances created", "positive_volume", target=2, weight=2.5),
        _s("Chances", "positive_volume", target=2, weight=2),
        _s("Chances successful, %", "finishing_rate", weight=1.5),
        _s("Involvement in scoring attacks", "positive_volume", target=2, weight=2),
        _s("xG (expected goals)", "decimal_volume", target=0.30, weight=3),
    ),
    "forward": (
        _s("Goals", "positive_decisive", weight=5),
        _s("Assists", "positive_decisive", weight=4),
        _s("Key passes", "positive_volume", target=2, weight=2.5),
        _s("Chances created", "positive_volume", target=1, weight=2),
        _s("Chances", "positive_volume", target=3, weight=2.5),
        _s("Chances successful, %", "finishing_rate", weight=2),
        _s("Involvement in scoring attacks", "positive_volume", target=2, weight=2),
        _s("xG (expected goals)", "decimal_volume", target=0.45, weight=3.5),
    ),
}


INVOLVEMENT_SPECS = {
    "goalkeeper": (_s("Actions", target=40, weight=1.5), _s("Actions successful, %", "action_rate", weight=2)),
    "centre_back": (_s("Actions", target=60, weight=1.5), _s("Actions successful, %", "action_rate", weight=2)),
    "full_back": (_s("Actions", target=50, weight=1.5), _s("Actions successful, %", "action_rate", weight=2)),
    "wing_back": (_s("Actions", target=55, weight=1.5), _s("Actions successful, %", "action_rate", weight=2)),
    "holding_midfielder": (_s("Actions", target=60, weight=1.5), _s("Actions successful, %", "action_rate", weight=2)),
    "box_to_box_midfielder": (_s("Actions", target=55, weight=1.5), _s("Actions successful, %", "action_rate", weight=2)),
    "attacking_midfielder": (_s("Actions", target=50, weight=1.5), _s("Actions successful, %", "action_rate", weight=2)),
    "winger": (_s("Actions", target=45, weight=1.5), _s("Actions successful, %", "action_rate", weight=2)),
    "forward": (_s("Actions", target=35, weight=1.5), _s("Actions successful, %", "action_rate", weight=2)),
}


def _dimension_specs(group):
    yield from ROLE_CONFIGS[group]["dimensions"]
    involvement_specs = INVOLVEMENT_SPECS.get(group) or ()
    if involvement_specs:
        yield ("involvement", *involvement_specs)
    impact_specs = IMPACT_SPECS.get(group) or ()
    if impact_specs:
        yield ("impact", *impact_specs)


KEY_METRICS = {
    "goalkeeper": ("Actions", "Actions successful, %", "Passes", "Passes accurate, %", "Long passes", "Long passes accurate, %", "Progressive passes", "Interceptions", "Lost balls in own half"),
    "centre_back": ("Actions", "Actions successful, %", "Defensive challenges", "Defensive challenges won, %", "Tackles", "Tackles successful, %", "Interceptions", "Aerial challenges won, %", "Passes accurate, %", "Progressive passes", "Progressive passes accurate, %", "Long passes", "Long passes accurate, %", "Super long passes", "Super long passes accurate, %"),
    "full_back": ("Actions", "Actions successful, %", "Defensive challenges won, %", "Tackles successful, %", "Interceptions", "Progressive passes", "Final third entries", "Final third entries through pass", "Final third entries through carry", "Crosses accurate, %", "Actions in opponent's box", "Actions in opponent's box successful, %"),
    "wing_back": ("Actions", "Actions successful, %", "Final third entries", "Final third entries through pass", "Final third entries through carry", "Progressive passes", "Crosses accurate, %", "Actions in opponent's box", "Actions in opponent's box successful, %", "Defensive challenges won, %", "Tackles successful, %", "Interceptions"),
    "holding_midfielder": ("Actions", "Actions successful, %", "Defensive challenges won, %", "Tackles successful, %", "Interceptions", "Ball recoveries", "Passes accurate, %", "Progressive passes", "Progressive passes accurate, %", "Long passes", "Long passes accurate, %", "Super long passes", "Super long passes accurate, %"),
    "box_to_box_midfielder": ("Actions", "Actions successful, %", "Final third entries", "Final third entries through pass", "Final third entries through carry", "Actions in opponent's box", "Actions in opponent's box successful, %", "xG (expected goals)", "Progressive passes", "Passes for a shot", "Defensive challenges won, %", "Tackles successful, %", "Interceptions"),
    "attacking_midfielder": ("Actions", "Actions successful, %", "Goals", "Assists", "xG (expected goals)", "Key passes", "Passes for a shot", "Final third entries", "Final third entries through pass", "Final third entries through carry", "Actions in opponent's box", "Actions in opponent's box successful, %", "Dribbles successful, %"),
    "winger": ("Actions", "Actions successful, %", "Goals", "Assists", "xG (expected goals)", "Dribbles successful, %", "Dribbling in the final third", "Crosses accurate, %", "Key passes", "Shots", "Shots in box share", "Actions in opponent's box", "Actions in opponent's box successful, %"),
    "forward": ("Actions", "Actions successful, %", "Goals", "Goals by head", "Assists", "xG (expected goals)", "Actions in opponent's box", "Actions in opponent's box successful, %", "Shots", "Shots from the penalty area", "Shots on target from the penalty area, %", "Headers", "Headers on target, %", "Shots on target, %", "Shots on post / bar", "Key passes", "Attacking challenges won, %"),
}


PHASE_DIMENSIONS = {
    "goalkeeper": {
        "global": ("involvement", "distribution"),
        "offensive": ("progression", "impact"),
        "defensive": ("space_control", "risk_control"),
    },
    "centre_back": {
        "global": ("involvement", "build_up"),
        "offensive": ("progression", "impact"),
        "defensive": ("defending", "aerial_control", "risk_control"),
    },
    "full_back": {
        "global": ("involvement", "ball_security"),
        "offensive": ("progression", "attacking_support", "delivery", "impact"),
        "defensive": ("defending",),
    },
    "wing_back": {
        "global": ("involvement", "ball_security"),
        "offensive": ("attacking_support", "progression", "delivery", "impact"),
        "defensive": ("defending",),
    },
    "holding_midfielder": {
        "global": ("involvement", "circulation"),
        "offensive": ("progression", "switching", "impact"),
        "defensive": ("protection", "risk_control"),
    },
    "box_to_box_midfielder": {
        "global": ("involvement", "circulation"),
        "offensive": ("impact", "final_third_presence", "progression", "creation"),
        "defensive": ("duel_balance",),
    },
    "attacking_midfielder": {
        "global": ("involvement", "ball_security"),
        "offensive": ("impact", "creation", "between_lines", "goal_threat"),
        "defensive": ("counterpress",),
    },
    "winger": {
        "global": ("involvement",),
        "offensive": ("impact", "one_v_one", "creation", "goal_threat", "progression"),
        "defensive": ("defensive_work",),
    },
    "forward": {
        "global": ("involvement", "link_play"),
        "offensive": ("impact", "box_presence", "finishing", "direct_play"),
        "defensive": ("defensive_work",),
    },
}

GLOBAL_BENCHMARK_METRICS = {
    "goalkeeper": ("Index", "Passes accurate, %", "Long passes accurate, %", "Progressive passes", "Interceptions"),
    "centre_back": ("Index", "__duels_won__", "Challenges won, %", "Defensive challenges won, %", "Aerial challenges won, %", "Interceptions"),
    "full_back": ("Index", "__duels_won__", "Defensive challenges won, %", "Progressive passes", "Crosses accurate, %", "Final third entries"),
    "wing_back": ("Index", "__duels_won__", "Defensive challenges won, %", "Progressive passes", "Crosses accurate, %", "Actions in opponent's box"),
    "holding_midfielder": ("Index", "__duels_won__", "Challenges won, %", "Defensive challenges won, %", "Passes accurate, %", "Progressive passes"),
    "box_to_box_midfielder": ("Index", "__duels_won__", "Challenges won, %", "Final third entries", "Progressive passes", "Passes for a shot"),
    "attacking_midfielder": ("Index", "__duels_won__", "Dribbles successful, %", "Key passes", "Passes for a shot", "Actions in opponent's box"),
    "winger": ("Index", "__duels_won__", "Dribbles successful, %", "Crosses accurate, %", "Shots on target, %", "Actions in opponent's box"),
    "forward": ("Index", "__duels_won__", "Attacking challenges won, %", "Shots on target from the penalty area, %", "Headers on target, %", "Shots from the penalty area", "Actions in opponent's box"),
}

BENCHMARK_LABELS = {
    "fr": {"__duels_won__": "Nombre de duels remportés"},
    "en": {"__duels_won__": "Duels won — total"},
    "ar": {"__duels_won__": "عدد الثنائيات الناجحة"},
}


RATE_BANDS = {
    "pass_cb": ((75, 35), (85, 58), (90, 75), (95, 90), (101, 98)),
    "pass_safe": ((70, 30), (80, 52), (86, 70), (91, 86), (101, 96)),
    "pass_general": ((65, 30), (75, 50), (82, 68), (88, 84), (101, 95)),
    "pass_forward": ((55, 30), (65, 50), (75, 68), (82, 84), (101, 95)),
    "long_pass": ((35, 30), (50, 50), (65, 68), (75, 84), (101, 95)),
    "progressive_rate": ((45, 30), (60, 50), (70, 68), (80, 84), (101, 95)),
    "def_duel": ((50, 25), (60, 50), (70, 68), (80, 84), (90, 94), (101, 99)),
    "duel": ((45, 28), (55, 50), (65, 68), (75, 84), (101, 96)),
    "att_duel": ((35, 30), (45, 50), (55, 68), (65, 84), (101, 96)),
    "aerial": ((50, 30), (60, 52), (70, 70), (80, 86), (90, 95), (101, 99)),
    "cross": ((20, 28), (30, 48), (35, 62), (45, 80), (55, 92), (101, 98)),
    "dribble": ((40, 30), (50, 50), (60, 68), (70, 84), (80, 94), (101, 98)),
    "shot_target": ((25, 28), (35, 48), (45, 65), (55, 80), (65, 92), (101, 98)),
    "finishing_rate": ((20, 30), (35, 50), (50, 70), (65, 86), (101, 98)),
    "action_rate": ((50, 30), (60, 50), (70, 68), (80, 84), (90, 94), (101, 98)),
}


ROLE_COACHING_FR = {
    "goalkeeper": {
        "distribution": "Scanner la première pression et la ligne suivante avant la passe.",
        "progression": "Varier jeu court, passe cassant une ligne et jeu long selon la structure adverse.",
        "space_control": "Revoir en vidéo la hauteur de départ et les sorties derrière la défense.",
        "risk_control": "Sécuriser le premier contrôle et renoncer à la passe axiale si la réception suivante est enfermée.",
    },
    "centre_back": {
        "defending": "Défendre vers l’avant avec appuis courts, sans ouvrir l’axe dans le duel.",
        "aerial_control": "Améliorer prise d’élan, lecture de trajectoire et orientation du premier contact.",
        "build_up": "Créer un angle de relance avant de recevoir et fixer avant de transmettre.",
        "progression": "Chercher la passe qui élimine une ligne lorsque le porteur n’est pas pressé.",
        "risk_control": "Réduire les pertes dans son camp par une meilleure prise d’information avant réception.",
    },
    "full_back": {
        "defending": "Fermer l’intérieur en premier et orienter l’ailier adverse vers la ligne.",
        "progression": "Recevoir ouvert et jouer vers l’avant dès que la pression est dépassée.",
        "delivery": "Lever la tête avant le centre et choisir entre centre précoce, tendu ou en retrait.",
        "ball_security": "Préparer la passe suivante avant le contrôle pour limiter les pertes de couloir.",
        "attacking_support": "Synchroniser dédoublement et sous-lap avec la position de l’ailier.",
    },
    "wing_back": {
        "defending": "Garder une posture permettant de presser vers l’avant tout en protégeant le dos.",
        "progression": "Accélérer après réception et attaquer l’espace libéré dans le dernier tiers.",
        "delivery": "Choisir le centre selon le nombre et la course des partenaires dans la surface.",
        "ball_security": "Alterner prise de risque haute et conservation quand la couverture est insuffisante.",
        "attacking_support": "Occuper plus souvent la dernière ligne ou la zone de centre en retrait.",
    },
    "holding_midfielder": {
        "protection": "Rester connecté aux centraux et intervenir avant que l’adversaire puisse se retourner.",
        "circulation": "Scanner les deux épaules et jouer avec le pied opposé à la pression.",
        "progression": "Identifier plus tôt la passe verticale qui élimine la première ligne.",
        "switching": "Fixer un côté avant de renverser avec une trajectoire exploitable pour le receveur.",
        "risk_control": "Dans l’axe bas, privilégier la solution qui protège l’équipe en cas de perte.",
    },
    "box_to_box_midfielder": {
        "circulation": "Orienter la première touche pour donner du rythme sans perdre la connexion avec le n° 6.",
        "progression": "Recevoir au-delà de la première ligne et porter ou passer vers le dernier tiers.",
        "final_third_presence": "Poursuivre l’action après la passe et arriver dans le demi-espace ou la surface.",
        "creation": "Prendre l’information avant réception pour jouer plus vite la passe qui crée le tir.",
        "duel_balance": "Sécuriser la transition puis se projeter seulement lorsque la couverture est en place.",
    },
    "attacking_midfielder": {
        "between_lines": "Se rendre visible entre les lignes avec un corps déjà orienté vers le but.",
        "creation": "Attirer un défenseur puis libérer la passe vers le dernier mouvement offensif.",
        "goal_threat": "Après avoir créé, continuer la course pour attaquer la surface et la deuxième balle.",
        "ball_security": "Limiter les contrôles fermés sous pression et protéger le ballon avec le corps.",
        "counterpress": "Réagir immédiatement à la perte pour fermer la passe de sortie la plus dangereuse.",
    },
    "winger": {
        "one_v_one": "Varier fixation extérieure, conduite intérieure et appel sans ballon.",
        "creation": "Après avoir éliminé, lever la tête et choisir la zone de centre ou la passe en retrait.",
        "goal_threat": "Attaquer le second poteau et rechercher des tirs plus centraux dans la surface.",
        "progression": "Recevoir en mouvement et accélérer dès que le latéral adverse est déséquilibré.",
        "defensive_work": "Fermer la passe vers le latéral puis déclencher le pressing avec le bloc.",
    },
    "forward": {
        "box_presence": "Varier appels premier poteau, second poteau et retrait pour rester disponible dans la surface.",
        "finishing": "Préparer l’appui et la surface de contact avant la frappe ; privilégier les zones centrales proches.",
        "link_play": "Enchaîner décrochage, remise et attaque immédiate de la surface.",
        "direct_play": "Utiliser le corps entre ballon et défenseur, puis orienter la remise vers l’avant.",
        "defensive_work": "Courber la course de pressing pour fermer l’axe et guider la relance vers le piège collectif.",
    },
}


def _plain(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _number(value, *, missing_zero=False):
    if value is None or isinstance(value, bool):
        return 0.0 if missing_zero else None
    if isinstance(value, (int, float)):
        return float(value)
    normalized = str(value).strip().replace("%", "").replace(",", ".")
    if normalized.casefold() in {"", "-", "–", "—", "none", "null", "nan"}:
        return 0.0 if missing_zero else None
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    return float(match.group()) if match else (0.0 if missing_zero else None)


def _rate(value):
    number = _number(value)
    if number is None:
        return None
    return number * 100 if abs(number) <= 1 else number


def _minutes(row):
    return max(0.0, _number(row.get("Minutes played"), missing_zero=True))


def _position_codes(row):
    """Return every match position while preserving the first as primary."""
    raw = row.get("Position")
    values = raw if isinstance(raw, (list, tuple, set)) else (raw,)
    positions = []
    for value in values:
        text = str(value or "").strip().upper()
        if not text:
            continue
        tokens = re.split(r"\s*[/,;|+]\s*", text)
        if len(tokens) == 1:
            tokens = re.split(r"\s+(?:AND|ET)\s+", text)
        for token in tokens:
            code = re.sub(r"[^A-Z0-9]", "", token)
            if code and code not in positions:
                positions.append(code)
    return tuple(positions)


def _position(row):
    positions = _position_codes(row)
    return positions[0] if positions else ""


def _group(row):
    return POSITION_GROUPS.get(_position(row), "box_to_box_midfielder")


def _label(name, language):
    localized = METRIC_LABELS.get(language, {}).get(name)
    if localized:
        return localized
    return METRIC_LABELS["fr"].get(name, name) if language == "fr" else name


def _definition(name, language):
    localized = METRIC_DEFINITIONS.get(language, {}).get(name)
    if localized:
        return localized
    if name in RATE_WEIGHTS:
        attempts = _label(RATE_WEIGHTS[name], language).lower()
        return {
            "fr": f"Pourcentage de {attempts} réussis, toujours présenté avec le nombre de tentatives.",
            "en": f"Success rate for {attempts}, always shown with the number of attempts.",
            "ar": f"نسبة نجاح {attempts} وتعرض دائما مع عدد المحاولات.",
        }[language]
    return {
        "fr": "Volume réel enregistré pendant les minutes jouées ; il n’est pas extrapolé sur 90 minutes.",
        "en": "The real total recorded during the minutes played; it is not projected to 90 minutes.",
        "ar": "العدد الحقيقي المسجل خلال دقائق اللعب دون تحويله إلى 90 دقيقة.",
    }[language]


def _confidence(minutes, language):
    if minutes < 20:
        code, score = "very_low", 20
    elif minutes < 45:
        code, score = "low", 35
    elif minutes < 60:
        code, score = "medium", 55
    elif minutes < 75:
        code, score = "good", 70
    elif minutes < 90:
        code, score = "very_good", 85
    else:
        code, score = "very_high", 100
    copy = TEXT[language]
    return {
        "code": code,
        "score": score,
        "label": copy["confidence"][code],
        "explanation": copy["confidence_text"][code],
        "minutes": round(minutes),
    }


def _attempt_reliability(attempts, language):
    attempts = int(round(attempts or 0))
    if attempts <= 0:
        code, factor = "none", 0.0
    elif attempts <= 2:
        code, factor = "very_low", 0.25
    elif attempts <= 4:
        code, factor = "low", 0.45
    elif attempts <= 7:
        code, factor = "usable", 0.72
    else:
        code, factor = "strong", 1.0
    return {
        "code": code,
        "factor": factor,
        "attempts": attempts,
        "label": TEXT[language]["sample"][code],
    }


def _duration_factor(minutes):
    if minutes < 20:
        return 0.20
    if minutes < 45:
        return 0.40
    if minutes < 60:
        return 0.60
    if minutes < 75:
        return 0.75
    if minutes < 90:
        return 0.90
    return 1.0


def _window_target(target, minutes, decimal=False):
    target = float(target or 1)
    scaled = target * _duration_factor(minutes)
    if decimal:
        return max(0.05, scaled)
    return max(1.0, math.ceil(scaled))


def _rate_band_score(value, kind):
    for upper, score in RATE_BANDS.get(kind, RATE_BANDS["action_rate"]):
        if value < upper:
            return score
    return 98


def _volume_score(value, target, minutes, *, decimal=False):
    expected = _window_target(target, minutes, decimal=decimal)
    ratio = value / expected if expected else 0
    if ratio <= 0:
        return 25
    if ratio < 0.50:
        return 42
    if ratio < 0.80:
        return 58
    if ratio < 1.20:
        return 74
    if ratio < 1.75:
        return 88
    return 98


def _negative_score(value, target, minutes):
    tolerance = _window_target(target, minutes)
    ratio = value / tolerance if tolerance else value
    if value <= 0:
        return 90
    if ratio <= 0.50:
        return 78
    if ratio <= 1:
        return 62
    if ratio <= 1.50:
        return 45
    if ratio <= 2:
        return 28
    return 12


def _metric_raw(row, metric):
    if metric == "Shots in box share":
        shots = _number(row.get("Shots"), missing_zero=True)
        in_box = _number(row.get("Shots from the penalty area"), missing_zero=True)
        return (in_box / shots * 100) if shots else None
    if metric in RATE_WEIGHTS or "%" in metric:
        return _rate(row.get(metric))
    return _number(row.get(metric), missing_zero=True)


def _successful_actions(row, rate_metric):
    attempts_metric = RATE_WEIGHTS.get(rate_metric)
    attempts = _number(row.get(attempts_metric), missing_zero=True) if attempts_metric else 0
    rate = _rate(row.get(rate_metric))
    if attempts <= 0 or rate is None:
        return None
    return max(0, min(round(attempts), round(attempts * rate / 100)))


def _format_number(value):
    if value is None:
        return "—"
    if abs(value - round(value)) < 1e-8:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _metric_result(row, specification, language):
    metric = specification["metric"]
    kind = specification["kind"]
    minutes = _minutes(row)
    value = _metric_raw(row, metric)
    result = {
        "metric": metric,
        "label": _label(metric, language),
        "definition": _definition(metric, language),
        "value": value,
        "display": "—",
        "score": None,
        "raw_score": None,
        "attempts": None,
        "sample": None,
        "kind": kind,
        "weight": specification.get("weight", 1.0),
        "lower_is_better": kind in {"negative", "mistake", "mistake_goal"},
    }
    if metric == "Shots in box share":
        shots = _number(row.get("Shots"), missing_zero=True)
        in_box = _number(row.get("Shots from the penalty area"), missing_zero=True)
        sample = _attempt_reliability(shots, language)
        result.update(
            attempts=round(shots),
            sample=sample,
            display=(f"{_format_number(in_box)}/{_format_number(shots)} · {_format_number(value)}%" if shots else "—"),
        )
        if value is not None:
            raw_score = _rate_band_score(value, "shot_target")
            result["raw_score"] = raw_score
            result["score"] = round(55 + (raw_score - 55) * sample["factor"])
        return result
    if metric in RATE_WEIGHTS or "%" in metric:
        attempts_metric = RATE_WEIGHTS.get(metric)
        attempts = _number(row.get(attempts_metric), missing_zero=True) if attempts_metric else 0
        sample = _attempt_reliability(attempts, language)
        result.update(attempts=round(attempts), sample=sample)
        if value is None or attempts <= 0:
            return result
        successes = max(0, min(round(attempts), round(attempts * value / 100)))
        result["display"] = f"{successes}/{round(attempts)} · {_format_number(value)}%"
        raw_score = _rate_band_score(value, kind if kind in RATE_BANDS else "action_rate")
        result["raw_score"] = raw_score
        result["score"] = round(55 + (raw_score - 55) * sample["factor"])
        return result
    result["display"] = _format_number(value)
    if value is None:
        return result
    if kind == "positive_decisive":
        if value >= 2:
            score = 100
        elif value >= 1:
            score = 96
        else:
            score = None
    elif kind == "positive_volume":
        score = (
            _volume_score(value, specification.get("target", 1), minutes)
            if value > 0
            else None
        )
    elif kind == "decisive":
        if value >= 2:
            score = 100
        elif value >= 1:
            score = 96
        elif minutes >= 60:
            score = 50
        else:
            score = None
    elif kind == "mistake_goal":
        score = 5 if value >= 1 else None
    elif kind == "mistake":
        score = 15 if value >= 1 else None
    elif kind == "negative":
        # A zero over a short appearance is not evidence that the player would
        # have kept the ball safely over a full match.  It remains unobserved.
        score = None if value <= 0 and minutes < 45 else _negative_score(
            value,
            specification.get("target", 1),
            minutes,
        )
    elif kind == "positive_decimal_volume":
        score = (
            _volume_score(value, specification.get("target", 1), minutes, decimal=True)
            if value > 0
            else None
        )
    elif kind == "decimal_volume":
        if value <= 0 and minutes < max(45, specification.get("min_minutes", 0)):
            score = None
        else:
            score = _volume_score(value, specification.get("target", 1), minutes, decimal=True)
    else:
        if value <= 0 and (
            specification.get("zero_is_no_opportunity")
            or minutes < max(45, specification.get("min_minutes", 0))
        ):
            score = None
        else:
            score = _volume_score(value, specification.get("target", 1), minutes)
    reliability_factor = min(1.0, 0.35 + _confidence(minutes, language)["score"] / 140)
    if score is not None and kind not in {"decisive", "positive_decisive", "mistake", "mistake_goal"}:
        score = round(55 + (score - 55) * reliability_factor)
    result["raw_score"] = score
    result["score"] = score
    return result


def _grade(score, coverage, language):
    copy = TEXT[language]
    if not coverage:
        code, tone = "unseen", "neutral"
    elif score >= 80:
        code, tone = "dominant", "excellent"
    elif score >= 68:
        code, tone = "strong", "positive"
    elif score >= 56:
        code, tone = "solid", "positive"
    elif score >= 45:
        code, tone = "mixed", "warning"
    elif score >= 32:
        code, tone = "fragile", "warning"
    else:
        code, tone = "critical", "danger"
    return code, copy["grades"][code], tone


def _role_dimensions(target, group, language):
    config = ROLE_CONFIGS[group]
    dimensions = []
    for item in _dimension_specs(group):
        key, specifications = item[0], item[1:]
        evidence = [_metric_result(target, spec, language) for spec in specifications]
        observed = [metric for metric in evidence if metric["score"] is not None]
        total_weight = sum(metric["weight"] for metric in observed)
        score = (
            round(sum(metric["score"] * metric["weight"] for metric in observed) / total_weight)
            if total_weight
            else 55
        )
        coverage = round(len(observed) / len(evidence) * 100) if evidence else 0
        grade_code, grade_label, tone = _grade(score, coverage, language)
        ranked_evidence = sorted(
            observed,
            key=lambda metric: (abs(metric["score"] - 55), metric["weight"]),
            reverse=True,
        )
        dimensions.append(
            {
                "key": key,
                "label": DIMENSION_LABELS[language].get(key, key),
                "score": score,
                "coverage": coverage,
                "grade_code": grade_code,
                "grade_label": grade_label,
                "stamp": f"{DIMENSION_LABELS[language].get(key, key).upper()} — {grade_label}",
                "tone": tone,
                "evidence": evidence,
                "headline_evidence": ranked_evidence[:2],
                "positive_evidence": [metric for metric in ranked_evidence if metric["score"] >= 65][:2],
                "negative_evidence": [metric for metric in ranked_evidence if metric["score"] <= 45][:2],
                "weight": config["weights"].get(key, 0),
            }
        )
    # The first mission a player sees must be the mission that matters most for
    # that exact position.  Stable sorting preserves the designed order when
    # two missions have the same coefficient.
    return sorted(dimensions, key=lambda item: item.get("weight", 0), reverse=True)


ACTION_TARGETS = {
    "goalkeeper": 40,
    "centre_back": 60,
    "full_back": 50,
    "wing_back": 55,
    "holding_midfielder": 60,
    "box_to_box_midfielder": 55,
    "attacking_midfielder": 50,
    "winger": 45,
    "forward": 35,
}

BOX_ACTION_TARGETS = {
    "goalkeeper": 1,
    "centre_back": 1,
    "full_back": 3,
    "wing_back": 4,
    "holding_midfielder": 2,
    "box_to_box_midfielder": 3,
    "attacking_midfielder": 5,
    "winger": 6,
    "forward": 8,
}


def _phase_interpretation(target, group, phase, language):
    """Translate the raw Players-table values into role-calibrated football language."""
    minutes = _minutes(target)
    sentences = []
    if phase == "global":
        actions = _number(target.get("Actions"), missing_zero=True)
        action_rate = _rate(target.get("Actions successful, %"))
        successful = _successful_actions(target, "Actions successful, %")
        expected = _window_target(ACTION_TARGETS[group], minutes)
        ratio = actions / expected if expected else 0
        volume_fr = "très forte" if ratio >= 1.2 else "solide" if ratio >= 0.8 else "modérée" if ratio >= 0.5 else "limitée"
        volume_en = "very high" if ratio >= 1.2 else "solid" if ratio >= 0.8 else "moderate" if ratio >= 0.5 else "limited"
        if action_rate is None or successful is None:
            display = f"{round(actions)}"
        else:
            display = f"{round(successful)}/{round(actions)} · {_format_number(action_rate)}%"
        if language == "fr":
            sentences.append(
                f"Implication {volume_fr} pour le poste et le temps joué : {round(actions)} actions ; "
                f"réussite {display}. Le volume décrit la présence dans le jeu ; le taux décrit la qualité d’exécution."
            )
        elif language == "en":
            sentences.append(
                f"{volume_en.capitalize()} involvement for the role and minutes played: {round(actions)} actions; "
                f"success {display}. Volume shows involvement; the rate shows execution quality."
            )
        else:
            sentences.append(f"المشاركة بالكرة: {round(actions)} إجراء، الناجح منها {display}. الحجم يقيس الحضور والنسبة تقيس جودة التنفيذ.")
    elif phase == "offensive":
        goals = round(_number(target.get("Goals"), missing_zero=True))
        assists = round(_number(target.get("Assists"), missing_zero=True))
        key_passes = round(_number(target.get("Key passes"), missing_zero=True))
        chances_created = round(_number(target.get("Chances created"), missing_zero=True))
        xg = _number(target.get("xG (expected goals)"), missing_zero=True)
        if language == "fr":
            sentences.append(
                f"Impact décisif : {goals} but(s), {assists} passe(s) décisive(s), {key_passes} passe(s) clé(s), "
                f"{chances_created} occasion(s) créée(s) et {_format_number(xg)} xG. Le xG mesure la qualité des tirs, pas un but garanti."
            )
        elif language == "en":
            sentences.append(
                f"Decisive output: {goals} goal(s), {assists} assist(s), {key_passes} key pass(es), "
                f"{chances_created} chance(s) created and {_format_number(xg)} xG. xG measures shot quality, not a guaranteed goal."
            )
        else:
            sentences.append(f"التأثير الحاسم: {goals} هدف، {assists} تمريرة حاسمة، {key_passes} تمريرة مفتاحية، {chances_created} فرصة مصنوعة و{_format_number(xg)} أهداف متوقعة.")

        if group == "forward":
            headers = _number(target.get("Headers"), missing_zero=True)
            header_rate = _rate(target.get("Headers on target, %"))
            headed_goals = _number(target.get("Goals by head"), missing_zero=True)
            header_success = _successful_actions(target, "Headers on target, %")
            if headers > 0:
                header_display = (
                    f"{round(header_success)}/{round(headers)} · {_format_number(header_rate)}%"
                    if header_success is not None and header_rate is not None
                    else f"{round(headers)}"
                )
                if language == "fr":
                    sentences.append(
                        f"Menace aérienne : {header_display} tête(s) cadrée(s) et {round(headed_goals)} but(s) de la tête. "
                        "Le volume juge l’accès aux centres ; le taux juge la qualité de la finition aérienne."
                    )
                elif language == "en":
                    sentences.append(
                        f"Aerial threat: {header_display} headed attempts on target and {round(headed_goals)} headed goal(s). "
                        "Volume assesses access to crosses; the rate assesses aerial finishing execution."
                    )
                else:
                    sentences.append(
                        f"التهديد الهوائي: {header_display} و{round(headed_goals)} هدف بالرأس. "
                        "الحجم يقيس الوصول إلى العرضيات والنسبة تقيس جودة الإنهاء بالرأس."
                    )

        box_actions = _number(target.get("Actions in opponent's box"), missing_zero=True)
        box_rate = _rate(target.get("Actions in opponent's box successful, %"))
        box_success = _successful_actions(target, "Actions in opponent's box successful, %")
        box_expected = _window_target(BOX_ACTION_TARGETS[group], minutes)
        if box_actions > 0:
            success_display = (
                f"{round(box_success)}/{round(box_actions)} · {_format_number(box_rate)}%"
                if box_success is not None and box_rate is not None
                else f"{round(box_actions)}"
            )
            above = box_actions >= box_expected
            if language == "fr":
                assessment = "présence forte pour ce poste" if above else "présence réelle, mais volume encore sous le repère du poste"
                sentences.append(
                    f"Surface adverse : réussite {success_display} ; {assessment} "
                    f"(repère interne pour cette durée : {round(box_expected)} actions)."
                )
            elif language == "en":
                assessment = "strong presence for this role" if above else "real presence, but still below the role reference volume"
                sentences.append(
                    f"Opposition box: success {success_display}; {assessment} "
                    f"(internal reference for these minutes: {round(box_expected)} actions)."
                )
            else:
                sentences.append(f"داخل منطقة المنافس: {success_display}؛ مرجع المركز لهذه الدقائق هو {round(box_expected)} إجراءات.")

        entries = round(_number(target.get("Final third entries"), missing_zero=True))
        via_pass = round(_number(target.get("Final third entries through pass"), missing_zero=True))
        via_carry = round(_number(target.get("Final third entries through carry"), missing_zero=True))
        if entries or via_pass or via_carry:
            if language == "fr":
                sentences.append(
                    f"Progression vers le dernier tiers : {entries} entrée(s), dont {via_pass} par la passe et {via_carry} par la conduite. "
                    "La passe fait avancer le bloc ; la conduite gagne directement du terrain balle au pied."
                )
            elif language == "en":
                sentences.append(
                    f"Final-third progression: {entries} entry/entries, {via_pass} by pass and {via_carry} by carry. "
                    "Passing advances the team shape; carrying gains territory directly on the ball."
                )
            else:
                sentences.append(f"التقدم إلى الثلث الأخير: {entries} دخول، منها {via_pass} بالتمرير و{via_carry} بحمل الكرة.")
    else:
        challenges = _number(target.get("Defensive challenges"), missing_zero=True)
        challenge_rate = _rate(target.get("Defensive challenges won, %"))
        challenge_success = _successful_actions(target, "Defensive challenges won, %")
        tackles = _number(target.get("Tackles"), missing_zero=True)
        tackle_rate = _rate(target.get("Tackles successful, %"))
        tackle_success = _successful_actions(target, "Tackles successful, %")
        interceptions = round(_number(target.get("Interceptions"), missing_zero=True))
        challenge_display = (
            f"{round(challenge_success)}/{round(challenges)} · {_format_number(challenge_rate)}%"
            if challenges > 0 and challenge_success is not None and challenge_rate is not None
            else f"{round(challenges)}"
        )
        tackle_display = (
            f"{round(tackle_success)}/{round(tackles)} · {_format_number(tackle_rate)}%"
            if tackles > 0 and tackle_success is not None and tackle_rate is not None
            else f"{round(tackles)}"
        )
        if language == "fr":
            sentences.append(
                f"Activité défensive : duels défensifs {challenge_display}, tacles {tackle_display}, "
                f"interceptions {interceptions}. Les volumes décrivent l’activité ; les taux de réussite jugent l’efficacité."
            )
        elif language == "en":
            sentences.append(
                f"Defensive activity: defensive duels {challenge_display}, tackles {tackle_display}, "
                f"interceptions {interceptions}. Volumes show activity; success rates assess execution."
            )
        else:
            sentences.append(f"النشاط الدفاعي: الثنائيات الدفاعية {challenge_display}، التدخلات {tackle_display}، الاعتراضات {interceptions}.")
    return sentences


def _performance_lenses(target, dimensions, group, language):
    labels = {
        "fr": {"global": "Lecture globale et implication", "offensive": "Contribution offensive", "defensive": "Contribution défensive"},
        "en": {"global": "Overall involvement", "offensive": "Attacking contribution", "defensive": "Defensive contribution"},
        "ar": {"global": "المشاركة العامة", "offensive": "المساهمة الهجومية", "defensive": "المساهمة الدفاعية"},
    }[language]
    dimension_map = {item["key"]: item for item in dimensions}
    lenses = []
    assigned_metrics = set()
    for phase in ("global", "offensive", "defensive"):
        selected = [dimension_map[key] for key in PHASE_DIMENSIONS[group][phase] if key in dimension_map]
        observed = [item for item in selected if item.get("coverage")]
        total_weight = sum(item.get("weight", 0) for item in observed)
        score = (
            round(sum(item["score"] * item.get("weight", 0) for item in observed) / total_weight)
            if total_weight
            else None
        )
        grade_code, grade_label, tone = _grade(score or 55, bool(observed), language)
        metrics = []
        for dimension in selected:
            for metric in dimension.get("evidence") or []:
                name = metric.get("metric")
                if not name or name in assigned_metrics:
                    continue
                assigned_metrics.add(name)
                metrics.append({**metric, "mission": dimension.get("label")})
        lenses.append(
            {
                "key": phase,
                "label": labels[phase],
                "score": score,
                "grade_code": grade_code,
                "grade_label": grade_label,
                "tone": tone,
                "interpretation": _phase_interpretation(target, group, phase, language),
                "metrics": metrics,
            }
        )
    return lenses


def _overall_score(dimensions):
    """Return the fixed-weight position score before bounded adjustments.

    Missing missions stay at the neutral reference instead of donating their
    weight to the few events observed in a short appearance.  This is the key
    distinction between a useful 13-minute entry and a complete high-impact
    match: the entry can be praised without being inflated to full-match level.
    """
    total_weight = sum(item.get("weight", 0) for item in dimensions)
    if not total_weight:
        return None
    raw_score = sum(
        (item.get("score", MS_NEUTRAL_SCORE) if item.get("coverage") else MS_NEUTRAL_SCORE)
        * item.get("weight", 0)
        for item in dimensions
    ) / total_weight
    # Football-facing scores use conventional half-up rounding, which is easier
    # to audit than Python's banker rounding (58.5 must be presented as 59).
    return math.floor(raw_score + 0.5 + 1e-9)


def _round_half_up(value):
    return math.floor(float(value) + 0.5 + 1e-9)


def _bounded_decisive_adjustment(target, language):
    """Return a small, diminishing adjustment for match-changing actions.

    Direct outcomes are deliberately stronger than supporting actions, while
    the complete module is capped.  A goal therefore matters for every role
    without turning the MS Score into a goal-counting table.
    """
    target = target or {}
    goals = _number(target.get("Goals"), missing_zero=True)
    assists = _number(target.get("Assists"), missing_zero=True)
    direct = 0.0
    if goals > 0:
        direct += 4.0 + min(max(goals - 1, 0), 2) * 1.5 + max(goals - 3, 0) * 0.75
    if assists > 0:
        direct += 3.5 + min(max(assists - 1, 0), 2) * 1.25 + max(assists - 3, 0) * 0.5
    direct = min(6.5, direct)

    successful_dribbles = _successful_actions(target, "Dribbles successful, %") or 0
    successful_box_actions = _successful_actions(
        target, "Actions in opponent's box successful, %"
    ) or 0
    supporting = min(
        2.0,
        0.45 * _number(target.get("Key passes"), missing_zero=True)
        + 0.55 * _number(target.get("Chances created"), missing_zero=True)
        + 0.30 * _number(target.get("Chances"), missing_zero=True)
        + 0.50 * _number(target.get("Involvement in scoring attacks"), missing_zero=True)
        + min(0.75, _number(target.get("xG (expected goals)"), missing_zero=True))
        + 0.20 * successful_dribbles
        + 0.15 * successful_box_actions,
    )

    penalty = min(
        MS_DECISIVE_ADJUSTMENT_LIMIT,
        4.0 * _number(target.get("Mistakes leading to goals"), missing_zero=True)
        + 2.0 * _number(target.get("Mistakes leading to chances"), missing_zero=True)
        + 3.0 * _number(target.get("Red cards"), missing_zero=True),
    )
    net = max(
        -MS_DECISIVE_ADJUSTMENT_LIMIT,
        min(MS_DECISIVE_ADJUSTMENT_LIMIT, direct + supporting - penalty),
    )
    labels = {
        "fr": {
            "direct": "Résultat direct (buts et passes décisives)",
            "supporting": "Création, menace et présence dangereuse",
            "penalty": "Erreurs et discipline décisives",
        },
        "en": {
            "direct": "Direct outcome (goals and assists)",
            "supporting": "Creation, threat and dangerous presence",
            "penalty": "Decisive errors and discipline",
        },
        "ar": {
            "direct": "النتيجة المباشرة (الأهداف والتمريرات الحاسمة)",
            "supporting": "الصناعة والخطورة والحضور في المناطق الخطرة",
            "penalty": "الأخطاء الحاسمة والانضباط",
        },
    }[language]
    events = []
    if direct:
        events.append(
            {
                "category": "decisive",
                "metric": "Direct outcome",
                "label": labels["direct"],
                "points": round(direct, 2),
                "calculation": f"{round(goals)} G · {round(assists)} A",
            }
        )
    if supporting:
        events.append(
            {
                "category": "decisive",
                "metric": "High-value attacking actions",
                "label": labels["supporting"],
                "points": round(supporting, 2),
                "calculation": (
                    f"KP {_format_number(_number(target.get('Key passes'), missing_zero=True))} · "
                    f"xG {_format_number(_number(target.get('xG (expected goals)'), missing_zero=True))} · "
                    f"box {round(successful_box_actions)} · dribbles {round(successful_dribbles)}"
                ),
            }
        )
    if penalty:
        events.append(
            {
                "category": "penalty",
                "metric": "Decisive errors",
                "label": labels["penalty"],
                "points": round(-penalty, 2),
                "calculation": (
                    f"G-errors {round(_number(target.get('Mistakes leading to goals'), missing_zero=True))} · "
                    f"chance-errors {round(_number(target.get('Mistakes leading to chances'), missing_zero=True))} · "
                    f"RC {round(_number(target.get('Red cards'), missing_zero=True))}"
                ),
            }
        )
    return round(net, 2), events


def _bounded_context_adjustment(rankings, language):
    """Use at most two points to validate, never replace, the role analysis."""
    rankings = rankings or {}
    match_rank = rankings.get("index_match") or {}
    team_rank = rankings.get("index_team") or {}
    match_total = int(match_rank.get("total") or 0)
    team_total = int(team_rank.get("total") or 0)
    points = 0.0
    scope = None
    ranking = None
    if match_total >= 6 and match_rank.get("rank") in {1, 2, 3}:
        points = {1: 2.0, 2: 1.0, 3: 0.5}[match_rank.get("rank")]
        scope, ranking = "match", match_rank
    elif team_total >= 3 and team_rank.get("rank") in {1, 2}:
        points = {1: 1.0, 2: 0.5}[team_rank.get("rank")]
        scope, ranking = "team", team_rank
    points = min(MS_CONTEXT_ADJUSTMENT_LIMIT, points)
    if not points:
        return 0.0, []
    label = {
        "fr": f"Validation par le rang de performance ({'match' if scope == 'match' else 'équipe'})",
        "en": f"Performance-rank validation ({'match' if scope == 'match' else 'team'})",
        "ar": "تأكيد بترتيب الأداء في المباراة" if scope == "match" else "تأكيد بترتيب الأداء داخل الفريق",
    }[language]
    return points, [
        {
            "category": "context",
            "metric": "Index rank",
            "label": label,
            "points": points,
            "calculation": f"{ranking.get('rank')}/{ranking.get('total')}",
        }
    ]


def _score_breakdown(dimensions, language, *, target=None, rankings=None):
    """Expose every coefficient used by the mission-score formula."""
    total_dimension_weight = sum(item.get("weight", 0) for item in dimensions)
    effect_labels = {
        "fr": {
            "very_positive": "Très positif", "positive": "Positif", "neutral": "Neutre",
            "negative": "À améliorer", "very_negative": "Très pénalisant", "unobserved": "Non évalué",
        },
        "en": {
            "very_positive": "Very positive", "positive": "Positive", "neutral": "Neutral",
            "negative": "To improve", "very_negative": "Strong negative", "unobserved": "Not assessed",
        },
        "ar": {
            "very_positive": "إيجابي جدا", "positive": "إيجابي", "neutral": "محايد",
            "negative": "يحتاج إلى تحسين", "very_negative": "سلبي جدا", "unobserved": "غير مقيم",
        },
    }[language]

    def effect(score):
        if score is None:
            code = "unobserved"
        elif score >= 80:
            code = "very_positive"
        elif score >= 65:
            code = "positive"
        elif score >= 50:
            code = "neutral"
        elif score >= 35:
            code = "negative"
        else:
            code = "very_negative"
        return {"code": code, "label": effect_labels[code]}

    result = []
    for dimension in sorted(dimensions, key=lambda item: item.get("weight", 0), reverse=True):
        used = bool(dimension.get("coverage")) and total_dimension_weight > 0
        effective_weight = (
            dimension.get("weight", 0) / total_dimension_weight * 100
            if total_dimension_weight
            else 0
        )
        scored_value = dimension.get("score", MS_NEUTRAL_SCORE) if used else MS_NEUTRAL_SCORE
        contribution = scored_value * effective_weight / 100
        observed_criteria = [metric for metric in dimension.get("evidence") or [] if metric.get("score") is not None]
        criteria_weight = sum(metric.get("weight", 1) for metric in observed_criteria)
        criteria = []
        for metric in dimension.get("evidence") or []:
            metric_used = metric.get("score") is not None and criteria_weight > 0 and used
            share = metric.get("weight", 1) / criteria_weight * 100 if metric_used else 0
            final_points = (
                metric.get("score", 0) * (share / 100) * (effective_weight / 100)
                if metric_used
                else 0
            )
            criteria.append(
                {
                    "metric": metric.get("metric"),
                    "label": metric.get("label"),
                    "definition": metric.get("definition"),
                    "value": metric.get("value"),
                    "display": metric.get("display"),
                    "score": metric.get("score"),
                    "raw_weight": metric.get("weight", 1),
                    "criterion_weight": round(share, 1),
                    "final_contribution": round(final_points, 2),
                    "ms_points": round(final_points, 2),
                    "used": metric_used,
                    "points_source": "position_mission" if metric_used else "unobserved",
                    "effect": effect(metric.get("score")),
                    "sample": metric.get("sample"),
                }
            )
        result.append(
            {
                "key": dimension.get("key"),
                "label": dimension.get("label"),
                "configured_weight": dimension.get("weight", 0),
                "effective_weight": round(effective_weight, 1),
                "score": dimension.get("score") if used else None,
                "scored_value": scored_value,
                "contribution": round(contribution, 2),
                "ms_budget": round(effective_weight, 1),
                "ms_points": round(contribution, 2),
                "coverage": dimension.get("coverage", 0),
                "used": used,
                "neutral_fill": not used,
                "criteria": criteria,
            }
        )
    formula = {
        "fr": (
            "MS Score /100 = somme des missions pondérées selon le poste + ajustement décisif borné de -8 à +8 "
            "+ validation de classement bornée à +2. Une mission non observable conserve la référence neutre "
            "50/100 : son poids n’est jamais redistribué sur les quelques actions d’une entrée courte. Les buts, "
            "passes décisives, passes clés, occasions, xG, dribbles réussis et actions réussies dans la surface "
            "alimentent l’impact décisif avec rendements décroissants. Le score final reste toujours compris "
            "entre 0 et 100. Les totaux réels ne sont jamais projetés sur 90 minutes."
        ),
        "en": (
            "MS Score /100 = position-weighted missions + a decisive adjustment bounded from -8 to +8 + rank "
            "validation bounded at +2. An unobserved mission keeps the neutral 50/100 reference, so its weight "
            "is never reassigned to the few events in a short appearance. Goals, assists, key passes, chances, "
            "xG, successful dribbles and successful box actions feed the decisive module with diminishing returns. "
            "The final score is always bounded from 0 to 100 and real totals are never projected to 90 minutes."
        ),
        "ar": (
            "مؤشر MS من 100 هو مجموع مهام المركز بأوزانها، مع تعديل حاسم محدود بين -8 و+8 وتأكيد ترتيب "
            "لا يتجاوز نقطتين. المهمة غير القابلة للملاحظة تحتفظ بالمرجع المحايد 50/100 ولا يوزع وزنها على "
            "أحداث مشاركة قصيرة. تدخل الأهداف والتمريرات الحاسمة والمفتاحية والفرص والأهداف المتوقعة والمراوغات "
            "الناجحة والأفعال الناجحة داخل المنطقة في التأثير الحاسم بعائد متناقص، ويبقى المجموع بين 0 و100 "
            "دون تحويل الأرقام الحقيقية إلى 90 دقيقة."
        ),
    }[language]
    raw_total = (
        sum(
            (item.get("score", MS_NEUTRAL_SCORE) if item.get("coverage") else MS_NEUTRAL_SCORE)
            * item.get("weight", 0)
            for item in dimensions
        ) / total_dimension_weight
        if total_dimension_weight
        else MS_NEUTRAL_SCORE
    )
    impact_drivers = []
    driver_metrics = {
        "Goals", "Assists", "Key passes", "Chances created", "Chances",
        "Chances successful, %", "Dribbles", "Dribbles successful, %",
        "Involvement in scoring attacks", "xG (expected goals)",
        "Headers", "Headers on target, %", "Shots on target from the penalty area, %",
    }
    driver_criteria = [
        criterion
        for dimension in result
        for criterion in dimension.get("criteria") or []
        if criterion.get("metric") in driver_metrics
    ]
    if driver_criteria:
        for criterion in driver_criteria:
            if not criterion.get("used"):
                continue
            metric = criterion.get("metric")
            value = _number(criterion.get("value"), missing_zero=True)
            display_value = criterion.get("display") or _format_number(value)
            count = round(value)
            points = criterion.get("final_contribution", 0)
            if language == "fr":
                explanations = {
                    "Goals": f"{count} {'but' if count == 1 else 'buts'} : impact direct sur la rencontre",
                    "Assists": f"{count} {'passe décisive' if count == 1 else 'passes décisives'} : création directement transformée en but",
                    "Key passes": f"{count} {'passe clé' if count == 1 else 'passes clés'} : {'ballon ayant' if count == 1 else 'ballons ayant'} préparé une tentative",
                    "Chances created": f"{count} {'occasion créée' if count == 1 else 'occasions créées'} pour un partenaire",
                    "Dribbles": f"{count} {'dribble tenté' if count == 1 else 'dribbles tentés'} pour éliminer un adversaire",
                    "Dribbles successful, %": f"Réussite des dribbles : {display_value}",
                    "Chances": f"{count} {'occasion de marquer obtenue' if count == 1 else 'occasions de marquer obtenues'}",
                    "Chances successful, %": f"Conversion des occasions : {display_value}",
                    "Involvement in scoring attacks": f"{count} {'attaque menant à un but avec implication du joueur' if count == 1 else 'attaques menant à un but avec implication du joueur'}",
                    "xG (expected goals)": f"{display_value} xG : qualité cumulée des tirs obtenus, sans garantir un but",
                }
            elif language == "en":
                explanations = {
                    "Goals": f"{count} {'goal' if count == 1 else 'goals'}: direct match impact",
                    "Assists": f"{count} {'assist' if count == 1 else 'assists'}: creation converted directly into a goal",
                    "Key passes": f"{count} {'key pass' if count == 1 else 'key passes'}: {'pass that sets' if count == 1 else 'passes that set'} up a shot",
                    "Chances created": f"{count} {'chance' if count == 1 else 'chances'} created for a team-mate",
                    "Dribbles": f"{count} {'dribble' if count == 1 else 'dribbles'} attempted to beat an opponent",
                    "Dribbles successful, %": f"Dribble success: {display_value}",
                    "Chances": f"{count} scoring {'chance' if count == 1 else 'chances'} reached",
                    "Chances successful, %": f"Chance conversion: {display_value}",
                    "Involvement in scoring attacks": f"{count} scoring {'attack involving the player' if count == 1 else 'attacks involving the player'}",
                    "xG (expected goals)": f"{display_value} xG: combined shot quality, not a guaranteed goal",
                }
            else:
                explanations = {
                    "Goals": f"{display_value} هدف: تأثير مباشر في المباراة",
                    "Assists": f"{display_value} تمريرة حاسمة أدت مباشرة إلى هدف",
                    "Key passes": f"{display_value} تمريرة مفتاحية صنعت تسديدة",
                    "Chances created": f"{display_value} فرصة مصنوعة لزميل",
                    "Dribbles": f"{display_value} محاولة مراوغة لتجاوز منافس",
                    "Dribbles successful, %": f"نجاح المراوغات: {display_value}",
                    "Chances": f"{display_value} فرصة تهديفية",
                    "Chances successful, %": f"تحويل الفرص: {display_value}",
                    "Involvement in scoring attacks": f"{display_value} هجمة انتهت بهدف وشارك فيها اللاعب",
                    "xG (expected goals)": f"{display_value} أهداف متوقعة: جودة التسديدات دون ضمان هدف",
                }
            impact_drivers.append(
                {
                    **criterion,
                    "explanation": explanations.get(metric, f"{criterion.get('label')}: {display_value}"),
                    "score_sentence": {
                        "fr": f"Critère {criterion.get('score')}/100 · {points} point(s) dans la note finale.",
                        "en": f"Criterion {criterion.get('score')}/100 · {points} point(s) in the final score.",
                        "ar": f"درجة المعيار {criterion.get('score')}/100 · {points} نقطة في الدرجة النهائية.",
                    }[language],
                }
            )
    decisive_adjustment, decisive_events = _bounded_decisive_adjustment(target or {}, language)
    context_adjustment, context_events = _bounded_context_adjustment(rankings or {}, language)
    score_before_clamp = raw_total + decisive_adjustment + context_adjustment
    total_points = _round_half_up(max(0, min(100, score_before_clamp)))
    band_code = next(code for minimum, code in MS_SCORE_BANDS if total_points >= minimum)
    point_events = decisive_events + context_events
    decisive_positive = sum(
        max(0, item.get("points", 0))
        for item in decisive_events
        if item.get("category") == "decisive"
    )
    penalty_points = sum(
        min(0, item.get("points", 0))
        for item in decisive_events
        if item.get("category") == "penalty"
    )
    criterion_points = {
        criterion.get("metric"): criterion.get("ms_points", 0)
        for dimension in result
        for criterion in dimension.get("criteria") or []
    }
    for driver in impact_drivers:
        points = criterion_points.get(driver.get("metric"), 0)
        driver["ms_points"] = round(points or 0, 2)
        driver["score_sentence"] = {
            "fr": (
                f"Contribution pondérée dans le MS Score : {_format_number(points or 0)} point(s). "
                "L’ajustement décisif global reste plafonné à 8 points."
            ),
            "en": (
                f"Weighted contribution inside MS Score: {_format_number(points or 0)} point(s). "
                "The overall decisive adjustment remains capped at 8 points."
            ),
            "ar": (
                f"المساهمة المرجحة داخل المهمة: {_format_number(points or 0)} نقطة. "
                "ويبقى التعديل الحاسم الإجمالي محدودا بثماني نقاط."
            ),
        }[language]
    return {
        "version": "ms-position-100-v2",
        "scale": "bounded_0_100",
        "formula": formula,
        "mission_quality_formula": formula,
        "dimensions": result,
        "contribution_total": round(raw_total, 2),
        "rounded_score": math.floor(raw_total + 0.5 + 1e-9),
        "position_score": round(raw_total, 2),
        "mission_points": round(raw_total, 2),
        "decisive_adjustment": decisive_adjustment,
        "decisive_points": round(decisive_positive, 2),
        "context_adjustment": context_adjustment,
        "ranking_points": context_adjustment,
        "penalty_points": round(penalty_points, 2),
        "raw_total_points": round(score_before_clamp, 2),
        "total_points": total_points,
        "band_code": band_code,
        "point_events": point_events,
        "decisive_rules": [
            {
                "label": {
                    "fr": "Impact décisif et création",
                    "en": "Decisive impact and creation",
                    "ar": "التأثير الحاسم والصناعة",
                }[language],
                "rule": "-8…+8",
            },
            {
                "label": {
                    "fr": "Validation du classement",
                    "en": "Ranking validation",
                    "ar": "تأكيد الترتيب",
                }[language],
                "rule": "0…+2",
            },
        ],
        "impact_drivers": sorted(
            impact_drivers,
            key=lambda item: item.get("ms_points", 0),
            reverse=True,
        ),
    }


def _entry_impact_floor(target, group):
    """Return a conservative floor for a short, eventful appearance.

    It rewards concrete impact instead of treating low minutes as a bad match.
    Zero events never create a positive floor.
    """
    if _minutes(target) >= 45:
        return None
    goals = _number(target.get("Goals"), missing_zero=True)
    assists = _number(target.get("Assists"), missing_zero=True)
    if goals + assists >= 2:
        return 92
    if goals >= 1:
        return 86
    if assists >= 1:
        return 82

    if group in {"forward", "winger", "attacking_midfielder"}:
        impact = (
            1.5 * _number(target.get("Shots from the penalty area"), missing_zero=True)
            + 0.6 * _number(target.get("Actions in opponent's box"), missing_zero=True)
            + 1.5 * _number(target.get("Key passes"), missing_zero=True)
            + 1.5 * _number(target.get("Passes for a shot"), missing_zero=True)
            + 1.0 * _number(target.get("Passes into the penalty box"), missing_zero=True)
            + 1.0 * (_successful_actions(target, "Dribbles successful, %") or 0)
        )
    elif group in {"box_to_box_midfielder", "holding_midfielder"}:
        impact = (
            0.6 * _number(target.get("Progressive passes"), missing_zero=True)
            + 0.8 * _number(target.get("Final third entries"), missing_zero=True)
            + 1.5 * _number(target.get("Passes for a shot"), missing_zero=True)
            + 1.0 * _number(target.get("Interceptions"), missing_zero=True)
            + 1.0 * (_successful_actions(target, "Challenges won, %") or 0)
        )
    elif group in {"centre_back", "full_back", "wing_back"}:
        impact = (
            1.7 * (_successful_actions(target, "Defensive challenges won, %") or 0)
            + 1.2 * (_successful_actions(target, "Aerial challenges won, %") or 0)
            + 1.3 * _number(target.get("Interceptions"), missing_zero=True)
            + 0.4 * _number(target.get("Progressive passes"), missing_zero=True)
            + 0.8 * _number(target.get("Final third entries"), missing_zero=True)
        )
    else:
        impact = (
            0.3 * _number(target.get("Passes"), missing_zero=True)
            + 1.5 * _number(target.get("Interceptions"), missing_zero=True)
            + 0.5 * _number(target.get("Progressive passes"), missing_zero=True)
        )
    if impact >= 8:
        return 82
    if impact >= 5:
        return 75
    if impact >= 2.5:
        return 65
    return None


def _verdict(score, language, *, target=None, rankings=None, mission_quality_score=None):
    minutes = _minutes(target or {})
    reasons = []
    goals = _number((target or {}).get("Goals"), missing_zero=True)
    assists = _number((target or {}).get("Assists"), missing_zero=True)
    if goals > 0 or assists > 0:
        reasons.append("decisive_goal_or_assist")

    rankings = rankings or {}
    match_rank = rankings.get("index_match") or {}
    team_rank = rankings.get("index_team") or {}
    first_in_match = match_rank.get("rank") == 1 and (match_rank.get("total") or 0) >= 6
    first_in_team = team_rank.get("rank") == 1 and (team_rank.get("total") or 0) >= 3
    if first_in_match or first_in_team:
        reasons.append("index_rank_one")

    copy = TEXT[language]["entry_verdicts" if minutes < 45 else "verdicts"]
    if score is None:
        code, tone = "partial", "neutral"
    else:
        code = next(code for minimum, code in MS_SCORE_BANDS if score >= minimum)
        tone = {
            "exceptional": "excellent",
            "very_good": "excellent",
            "solid": "positive",
            "mixed": "warning",
            "insufficient": "warning",
            "difficult": "danger",
        }[code]
        decisive_errors = (
            _number((target or {}).get("Mistakes leading to goals"), missing_zero=True)
            + _number((target or {}).get("Red cards"), missing_zero=True)
        )
        if minutes >= 45 and (goals > 0 or assists > 0) and not decisive_errors:
            if code in {"mixed", "insufficient", "difficult"}:
                code, tone = "solid", "positive"
                reasons.append("decisive_outcome_validates_verdict")
        if minutes < 45:
            entry_signal = _entry_impact_floor(target or {}, _group(target or {}))
            if goals > 0 or assists > 0:
                code, tone = "exceptional", "excellent"
            elif entry_signal is not None and entry_signal >= 75 and code not in {"exceptional", "very_good"}:
                code, tone = "very_good", "excellent"
                reasons.append("short_appearance_positive_impact")
            elif entry_signal is not None and entry_signal >= 65 and code in {"insufficient", "difficult"}:
                code, tone = "solid", "positive"
                reasons.append("short_appearance_positive_impact")
    return {
        "code": code,
        "label": copy[code],
        "score": score,
        "ms_score": score,
        "mission_score": mission_quality_score,
        "mission_quality_score": mission_quality_score,
        "tone": tone,
        "appearance_type": "entry" if minutes < 45 else "match",
        "reasons": reasons,
    }


def _decisive_highlights(target, language):
    goals = round(_number(target.get("Goals"), missing_zero=True))
    assists = round(_number(target.get("Assists"), missing_zero=True))
    mistakes_goals = round(_number(target.get("Mistakes leading to goals"), missing_zero=True))
    highlights = []
    if goals:
        if language == "fr":
            label = f"PERFORMANCE DE BUTEUR EXCEPTIONNELLE — {goals} BUTS" if goals >= 2 else "BUTTEUR DÉCISIF — 1 BUT"
            explanation = (
                f"{goals} buts sur cette rencontre : contribution directe et prioritaire dans le verdict. "
                "Cette appréciation concerne ce match, pas le niveau de finition sur une saison complète."
            )
        elif language == "en":
            label = f"EXCEPTIONAL GOALSCORING PERFORMANCE — {goals} GOALS" if goals >= 2 else "DECISIVE GOALSCORER — 1 GOAL"
            explanation = (
                f"{goals} goals in this match: a direct, high-priority contribution to the verdict. "
                "This statement assesses this match, not season-long finishing ability."
            )
        else:
            label = f"أداء تهديفي استثنائي — {goals} أهداف" if goals >= 2 else "هداف حاسم — هدف واحد"
            explanation = f"سجل اللاعب {goals} أهداف في هذه المباراة، وهي مساهمة مباشرة وأساسية في الخلاصة دون تعميمها على الموسم."
        highlights.append({"type": "goals", "label": label, "value": goals, "tone": "excellent", "explanation": explanation})
    if assists:
        if language == "fr":
            label = f"CRÉATEUR DÉCISIF — {assists} PASSES DÉCISIVES" if assists >= 2 else "PASSEUR DÉCISIF — 1 PASSE DÉCISIVE"
            explanation = f"{assists} passe(s) directement liée(s) à un but : impact majeur dans le résultat offensif individuel."
        elif language == "en":
            label = f"DECISIVE CREATOR — {assists} ASSISTS" if assists >= 2 else "DECISIVE PROVIDER — 1 ASSIST"
            explanation = f"{assists} pass(es) directly leading to a goal: major individual attacking impact."
        else:
            label = f"صانع حاسم — {assists} تمريرات حاسمة" if assists >= 2 else "صانع هدف — تمريرة حاسمة واحدة"
            explanation = f"قدم اللاعب {assists} تمريرات أدت مباشرة إلى هدف، وهو تأثير هجومي فردي مهم."
        highlights.append({"type": "assists", "label": label, "value": assists, "tone": "excellent", "explanation": explanation})
    if mistakes_goals:
        if language == "fr":
            label = f"ERREUR DÉCISIVE À CORRIGER — {mistakes_goals}"
            explanation = "Une erreur a directement conduit à un but adverse ; la cause doit être vérifiée dans la vidéo avant conclusion technique."
        elif language == "en":
            label = f"DECISIVE ERROR TO CORRECT — {mistakes_goals}"
            explanation = "An error directly led to an opposition goal; its cause must be verified on video before a technical conclusion."
        else:
            label = f"خطأ حاسم يحتاج إلى تصحيح — {mistakes_goals}"
            explanation = "أدى خطأ مباشرة إلى هدف للمنافس ويجب تأكيد سببه بالفيديو قبل الخلاصة الفنية."
        highlights.append({"type": "mistakes_goals", "label": label, "value": mistakes_goals, "tone": "danger", "explanation": explanation})
    return highlights


def _percentile(target, values, direction=1):
    clean = [value for value in values if value is not None and math.isfinite(value)]
    if target is None or not clean:
        return None
    if direction < 0:
        clean = [-value for value in clean]
        target = -target
    lower = sum(value < target for value in clean)
    equal = sum(value == target for value in clean)
    return round((lower + 0.5 * equal) / len(clean) * 100)


def _same_minute_window(target, rows):
    target_minutes = _minutes(target)
    if target_minutes <= 0:
        return []
    selected = []
    for row in rows:
        minutes = _minutes(row)
        if minutes <= 0:
            continue
        ratio = min(minutes, target_minutes) / max(minutes, target_minutes)
        if abs(minutes - target_minutes) <= 15 or ratio >= 0.75:
            selected.append(row)
    return selected


def _spec_for_metric(group, metric):
    for item in _dimension_specs(group):
        for specification in item[1:]:
            if specification["metric"] == metric:
                return specification
    if metric in RATE_WEIGHTS or "%" in metric:
        return _s(metric, "action_rate")
    return _s(metric, target=1)


def _canonical_radar_metric(name):
    """Expand the two labels truncated by the SportsBase SVG tooltip."""
    normalized = _plain(str(name or "").replace("…", "..."))
    if normalized.startswith("passes into the penalty box accurate"):
        return "Passes into the penalty box accurate, %"
    if normalized.startswith("dribbling in the final third successf"):
        return "Dribbling in the final third successful, %"
    aliases = {
        _plain(metric): metric
        for metric in (
            "Chances",
            "Chances created",
            "Involvement in scoring attacks",
            "Shots",
            "Passes into the penalty box",
            "Passes for a shot",
            "Defensive challenges",
            "Defensive challenges won, %",
            "Dribbling in the final third",
            "Interceptions",
        )
    }
    return aliases.get(normalized, str(name or "").strip())


def _position_benchmark(target, context, group, language):
    """Expose the real SportsBase season values behind the radar geometry.

    Every SportsBase radar axis has its own real-world scale.  The stored
    normalised values are used only to draw comparable polygons; the report
    displays the real player and same-position tournament values per 90.
    """
    context = context if isinstance(context, dict) else {}
    source = context.get("position_benchmark")
    if not isinstance(source, dict):
        source = {}
    positions = [item for item in source.get("positions") or [] if isinstance(item, dict)]
    primary = max(
        positions,
        key=lambda item: _number(item.get("percent"), missing_zero=True),
        default={},
    )
    metrics = []
    for source_metric in source.get("radar_metrics") or []:
        if not isinstance(source_metric, dict):
            continue
        metric = _canonical_radar_metric(source_metric.get("name") or source_metric.get("label"))
        average = _number(source_metric.get("average"))
        season_player = _number(source_metric.get("player"))
        if season_player is None:
            season_player = _number(source_metric.get("value"))
        scale_max = _number(source_metric.get("scale_max"))
        player_normalized = _number(source_metric.get("player_normalized"))
        average_normalized = _number(source_metric.get("average_normalized"))
        if scale_max and scale_max > 0:
            if player_normalized is None and season_player is not None:
                player_normalized = season_player / scale_max * 100
            if average_normalized is None and average is not None:
                average_normalized = average / scale_max * 100
        has_real_scale = scale_max is not None and scale_max > 0
        comparable = (
            has_real_scale
            and season_player is not None
            and average is not None
            and player_normalized is not None
            and average_normalized is not None
        )
        unit = str(source_metric.get("unit") or ("%" if "%" in metric else "per_90"))
        precision = max(0, min(2, int(_number(source_metric.get("precision"), missing_zero=True))))
        metrics.append(
            {
                "metric": metric,
                "label": _label(metric, language),
                "definition": _definition(metric, language),
                "season_player": round(season_player, precision) if season_player is not None else None,
                "position_average": round(average, precision) if average is not None else None,
                "player_normalized": round(max(0, min(100, player_normalized)), 1)
                if player_normalized is not None
                else None,
                "average_normalized": round(max(0, min(100, average_normalized)), 1)
                if average_normalized is not None
                else None,
                "scale_min": 0,
                "scale_max": round(scale_max, precision) if scale_max is not None else None,
                "precision": precision,
                "unit": unit,
                "scope": str(source_metric.get("scope") or "season_per_90"),
                "value_source": str(source_metric.get("value_source") or ""),
                "difference": round(season_player - average, precision) if comparable else None,
                "comparable": comparable,
            }
        )
    comparable_metrics = [item for item in metrics if item.get("comparable")]
    note = {
        "fr": (
            "Ce radar décrit le profil saisonnier du joueur face à la moyenne réelle des joueurs du même poste "
            "dans le championnat. Les nombres sont les valeurs saisonnières par 90 minutes ; les pourcentages "
            "restent en %. Chaque axe possède sa propre échelle : la normalisation sert uniquement à dessiner "
            "la forme et ne constitue ni une note sur 100 ni une projection de ce match."
        ),
        "en": (
            "This radar describes the player's season profile against the real tournament average for players "
            "in the same position. Numbers are season values per 90 minutes and percentages remain in %. "
            "Each axis has its own scale: normalisation is used only to draw the shape and is neither a score "
            "out of 100 nor a projection of this match."
        ),
        "ar": (
            "يعرض هذا الرادار ملف اللاعب الموسمي مقارنة بالمتوسط الحقيقي للاعبي المركز نفسه في البطولة. "
            "الأرقام هي القيم الموسمية لكل 90 دقيقة وتبقى النسب المئوية بوحدة %. لكل محور مقياسه الخاص، "
            "ويستخدم التطبيع للرسم فقط ولا يمثل درجة من 100 أو إسقاطا لأرقام هذه المباراة."
        ),
    }[language]
    return {
        "available": len(comparable_metrics) >= 3,
        "season": str(source.get("season") or ""),
        "position_code": str(primary.get("code") or ""),
        "position_name": str(primary.get("name") or primary.get("code") or ""),
        "position_percent": round(_number(primary.get("percent"), missing_zero=True)),
        "selection_rule": "highest_position_percentage",
        "scale": "real_per_90_values_axis_normalized_for_shape_only",
        "metrics": metrics,
        "comparable_metrics": comparable_metrics,
        "note": note,
    }


def _key_metrics(target, population, group, language):
    comparable = _same_minute_window(target, population)
    results = []
    for metric in KEY_METRICS[group]:
        specification = _spec_for_metric(group, metric)
        result = _metric_result(target, specification, language)
        comparison_rows = population if metric in RATE_WEIGHTS or "%" in metric else comparable
        values = []
        for row in comparison_rows:
            if metric in RATE_WEIGHTS:
                attempts = _number(row.get(RATE_WEIGHTS[metric]), missing_zero=True)
                if attempts < 3:
                    continue
            values.append(_metric_raw(row, metric))
        clean = [value for value in values if value is not None]
        result["percentile"] = (
            _percentile(result["value"], clean, -1 if result["lower_is_better"] else 1)
            if len(clean) >= 3
            else None
        )
        result["comparison_population"] = len(clean)
        results.append(result)
    return results


def _format_comparison_value(row, metric, group, language):
    result = _metric_result(row, _spec_for_metric(group, metric), language)
    return result["value"], result["display"], result["lower_is_better"]


def _homologous_position_codes(position):
    """Narrow position equivalence, never a whole line or playing unit."""
    groups = {
        "RB": ("RB", "RWB"), "RWB": ("RWB", "RB"),
        "LB": ("LB", "LWB"), "LWB": ("LWB", "LB"),
        "RCB": ("RCB", "CB"), "LCB": ("LCB", "CB"), "CB": ("CB", "RCB", "LCB"),
        "RCM": ("RCM", "CM"), "LCM": ("LCM", "CM"), "CM": ("CM", "RCM", "LCM"),
        "RDM": ("RDM", "DM", "CDM"), "LDM": ("LDM", "DM", "CDM"),
        "DM": ("DM", "CDM", "RDM", "LDM"), "CDM": ("CDM", "DM", "RDM", "LDM"),
        "RW": ("RW", "RM", "RAM"), "RM": ("RM", "RW", "RAM"), "RAM": ("RAM", "RW", "RM"),
        "LW": ("LW", "LM", "LAM"), "LM": ("LM", "LW", "LAM"), "LAM": ("LAM", "LW", "LM"),
        "RCF": ("RCF", "CF", "ST"), "LCF": ("LCF", "CF", "ST"),
        "CF": ("CF", "ST", "RCF", "LCF"), "ST": ("ST", "CF", "RCF", "LCF"),
    }
    return groups.get(position, (position,))


def _same_position_comparison(target, opponents, title, language, key_metrics, group):
    """Compare only with the opposition player's exact or narrow equivalent position."""
    position = _position(target)
    selected = [row for row in opponents if _position(row) == position and _minutes(row) > 0]
    match_type = "exact"
    if not selected:
        equivalents = set(_homologous_position_codes(position)) - {position}
        selected = [row for row in opponents if _position(row) in equivalents and _minutes(row) > 0]
        match_type = "equivalent"
    if not selected:
        return None
    counterpart = max(selected, key=_minutes)
    target_minutes, opponent_minutes = _minutes(target), _minutes(counterpart)
    maximum = max(target_minutes, opponent_minutes)
    ratio = min(target_minutes, opponent_minutes) / maximum if maximum else 0
    comparable = abs(target_minutes - opponent_minutes) <= 15 or ratio >= 0.75
    metrics = []
    for metric in key_metrics[:6]:
        target_value, target_display, lower = _format_comparison_value(target, metric, group, language)
        opponent_value, opponent_display, _lower = _format_comparison_value(counterpart, metric, group, language)
        metrics.append(
            {
                "metric": metric,
                "label": _label(metric, language),
                "target": target_value,
                "target_display": target_display,
                "opponent": opponent_value,
                "opponent_display": opponent_display,
                "lower_is_better": lower,
                "volume_comparable": comparable or metric in RATE_WEIGHTS or "%" in metric,
            }
        )
    return {
        "title": title,
        "player": str(counterpart.get("Player") or ""),
        "team": str(counterpart.get("Team") or ""),
        "position": _position(counterpart),
        "position_match": match_type,
        "minutes": round(opponent_minutes),
        "comparable_minutes": comparable,
        "metrics": metrics,
    }


def _benchmark_value(row, metric):
    if metric == "__duels_won__":
        successful = _successful_actions(row, "Challenges won, %")
        return float(successful) if successful is not None else None
    if metric == "Index":
        return _number(row.get("Index"))
    return _metric_raw(row, metric)


def _benchmark_display(row, metric, group, language):
    if metric == "__duels_won__":
        attempts = _number(row.get("Challenges"), missing_zero=True)
        rate = _rate(row.get("Challenges won, %"))
        successful = _successful_actions(row, "Challenges won, %")
        if successful is None:
            return "—"
        return f"{successful}/{round(attempts)} · {_format_number(rate)}%"
    if metric == "Index":
        return _format_number(_number(row.get("Index")))
    return _metric_result(row, _spec_for_metric(group, metric), language)["display"]


def _global_benchmarks(target, rows, group, language):
    """Individual leaders across both teams; never aggregate lines or units."""
    results = []
    match_rows = [row for row in rows if _minutes(row) > 0]
    for metric in GLOBAL_BENCHMARK_METRICS[group]:
        min_attempts = 3 if metric in RATE_WEIGHTS else 1
        candidates = []
        for row in match_rows:
            value = _benchmark_value(row, metric)
            if value is None:
                continue
            if metric in RATE_WEIGHTS:
                attempts = _number(row.get(RATE_WEIGHTS[metric]), missing_zero=True)
                if attempts < min_attempts:
                    continue
            candidates.append((row, value))
        if not candidates:
            continue
        best_value = max(value for _row, value in candidates)
        leaders = [row for row, value in candidates if abs(value - best_value) < 1e-9]
        target_value = _benchmark_value(target, metric)
        target_eligible = any(_plain(row.get("Player")) == _plain(target.get("Player")) for row, _value in candidates)
        rank, total = _rank(target_value, [value for _row, value in candidates]) if target_eligible else (None, len(candidates))
        label = BENCHMARK_LABELS.get(language, {}).get(metric) or _label(metric, language)
        definition = (
            {
                "fr": "Nombre de duels gagnés calculé à partir du volume de duels et du pourcentage de réussite.",
                "en": "Number of duels won, derived from duel volume and success rate.",
                "ar": "عدد الثنائيات الناجحة محسوب من حجم الثنائيات ونسبة النجاح.",
            }[language]
            if metric == "__duels_won__"
            else _definition(metric, language)
        )
        results.append(
            {
                "metric": metric,
                "label": label,
                "definition": definition,
                "target_display": _benchmark_display(target, metric, group, language),
                "target_rank": {"rank": rank, "total": total, "available": rank is not None},
                "minimum_attempts": min_attempts,
                "leaders": [
                    {
                        "name": str(row.get("Player") or ""),
                        "team": str(row.get("Team") or ""),
                        "position": _position(row),
                        "minutes": round(_minutes(row)),
                        "display": _benchmark_display(row, metric, _group(row), language),
                    }
                    for row in leaders[:2]
                ],
            }
        )
    return results


def _rank(value, values, higher=True):
    clean = [number for number in values if number is not None]
    if value is None or not clean:
        return None, len(clean)
    clean.sort(reverse=higher)
    return clean.index(value) + 1, len(clean)


def _rankings(target, rows, dimensions, language):
    team = str(target.get("Team") or "")
    team_rows = [row for row in rows if str(row.get("Team") or "") == team and _minutes(row) > 0]
    match_rows = [row for row in rows if _minutes(row) > 0]
    homologous_codes = set(_homologous_position_codes(_position(target)))
    position_rows = [row for row in match_rows if _position(row) in homologous_codes]
    index = _number(target.get("Index"))
    team_rank, team_total = _rank(index, [_number(row.get("Index")) for row in team_rows])
    match_rank, match_total = _rank(index, [_number(row.get("Index")) for row in match_rows])
    position_rank, position_total = _rank(index, [_number(row.get("Index")) for row in position_rows])
    result = {
        "index_team": {"rank": team_rank, "total": team_total, "available": team_rank is not None},
        "index_match": {"rank": match_rank, "total": match_total, "available": match_rank is not None},
        "index_same_position": {"rank": position_rank, "total": position_total, "available": position_rank is not None},
        "index_used_as_verdict_signal": True,
    }
    copy = TEXT[language]
    if match_rank == 1 and match_total >= 6:
        summary = copy["index_first_match"].format(rank=match_rank, total=match_total)
    elif team_rank == 1 and team_total >= 3:
        summary = copy["index_first_team"].format(rank=team_rank, total=team_total)
    elif team_rank is not None and team_rank <= 3 and team_total >= 6:
        summary = copy["index_top_three"].format(rank=team_rank, total=team_total)
    elif team_rank is not None:
        summary = copy["index_available"].format(rank=team_rank, total=team_total)
    else:
        summary = copy["index_unavailable"]
    result["summary"] = summary
    return result


def _territorial_profile(points, language):
    valid = []
    for point in points or []:
        x = _number(point.get("left_pct")) if isinstance(point, dict) else None
        y = _number(point.get("top_pct")) if isinstance(point, dict) else None
        if x is not None and y is not None and 0 <= x <= 100 and 0 <= y <= 100:
            valid.append((x, y))
    if not valid:
        return {"available": False, "total_touches": 0}
    thirds = {
        "displayed_left": sum(x < 33.34 for x, _y in valid),
        "displayed_middle": sum(33.34 <= x < 66.67 for x, _y in valid),
        "displayed_right": sum(x >= 66.67 for x, _y in valid),
    }
    lanes = {
        "wide": sum(y <= 25 or y >= 75 for _x, y in valid),
        "half_space": sum(25 < y < 42 or 58 < y < 75 for _x, y in valid),
        "central": sum(42 <= y <= 58 for _x, y in valid),
    }
    total = len(valid)
    thirds_pct = {key: round(value / total * 100) for key, value in thirds.items()}
    lanes_pct = {key: round(value / total * 100) for key, value in lanes.items()}
    note = {
        "fr": "Les tiers gauche/droit suivent l’affichage de la carte source : le sens d’attaque n’est pas déduit sans donnée explicite.",
        "en": "Left/right thirds follow the source-map display; attacking direction is not inferred without explicit data.",
        "ar": "الثلثان الأيسر والأيمن يتبعان عرض خريطة المصدر ولا يتم افتراض اتجاه الهجوم دون بيانات صريحة.",
    }[language]
    return {
        "available": True,
        "total_touches": total,
        "displayed_thirds": thirds_pct,
        "lanes": lanes_pct,
        "average_location": {
            "x": round(sum(x for x, _y in valid) / total, 1),
            "y": round(sum(y for _x, y in valid) / total, 1),
        },
        "attack_direction_normalized": False,
        "note": note,
    }


def _context_payload(target, context, language):
    context = dict(context or {})
    home_team = str(context.get("home_team") or "")
    away_team = str(context.get("away_team") or "")
    source_metadata = context.get("source_metadata") if isinstance(context.get("source_metadata"), dict) else {}
    points = source_metadata.get("ball_touches_points") or context.get("ball_touches_points") or []
    return {
        "home_team": home_team,
        "away_team": away_team,
        # Kept only to identify the fixture on the cover.  No match-result or
        # score-state conclusion is produced until the scraper supplies the
        # required event timeline.
        "score": str(context.get("score") or ""),
        "match_date": str(context.get("match_date") or ""),
        "performance_context_analysis": False,
        "territory": _territorial_profile(points, language),
    }


def _evidence_sentence(metric):
    sentence = f"{metric.get('label')}: {metric.get('display')}"
    definition = str(metric.get("definition") or "").strip()
    return f"{sentence} — {definition}" if definition else sentence


def _role_specific_observations(target, group, language):
    strengths, risks = [], []
    minutes = _minutes(target)
    if language == "fr":
        if group == "goalkeeper":
            risks.append(
                "L’export Players ne contient ni arrêts, ni buts évités, ni données post-tir : "
                "le jugement du gardien sur sa mission première reste partiel."
            )
        elif group == "forward":
            shots = _number(target.get("Shots"), missing_zero=True)
            box_shots = _number(target.get("Shots from the penalty area"), missing_zero=True)
            goals = _number(target.get("Goals"), missing_zero=True)
            box_actions = _number(target.get("Actions in opponent's box"), missing_zero=True)
            headers = _number(target.get("Headers"), missing_zero=True)
            header_rate = _rate(target.get("Headers on target, %"))
            if shots >= 3 and box_shots >= max(2, shots * 0.60):
                strengths.append(f"Présence de finition : {box_shots:.0f}/{shots:.0f} tirs ont été pris dans la surface.")
            if box_actions >= _window_target(6, minutes):
                strengths.append(f"Occupation régulière de la zone décisive avec {box_actions:.0f} actions dans la surface.")
            if box_actions >= 3 and shots == 0:
                risks.append(
                    f"La présence dans la surface ({box_actions:.0f} actions) ne s’est pas transformée en tir : "
                    "revoir le placement avant la dernière passe et la préparation du premier contact."
                )
            if shots >= 3 and goals == 0:
                risks.append(
                    f"La présence est positive, mais les {shots:.0f} tirs n’ont pas encore produit de but : "
                    "travailler la sélection et l’exécution, sans dévaloriser l’accès aux occasions."
                )
            if headers >= 2 and header_rate is not None and header_rate >= 50:
                strengths.append(
                    f"Menace aérienne crédible : {round(headers * header_rate / 100)}/{round(headers)} "
                    f"têtes cadrées ({header_rate:.0f} %)."
                )
            elif headers >= 3 and header_rate is not None and header_rate < 35:
                risks.append(
                    f"Accès aérien réel ({headers:.0f} têtes), mais cadrage limité ({header_rate:.0f} %) : "
                    "travailler le timing d’appel, l’orientation du corps et la zone de contact."
                )
        elif group == "box_to_box_midfielder":
            entries = _number(target.get("Final third entries"), missing_zero=True)
            box_actions = _number(target.get("Actions in opponent's box"), missing_zero=True)
            if entries or box_actions:
                strengths.append(
                    f"Projection offensive mesurable : {entries:.0f} entrée(s) dans le dernier tiers "
                    f"et {box_actions:.0f} action(s) dans la surface."
                )
            elif minutes >= 60:
                risks.append("Peu de présence mesurable au-delà du milieu : vérifier les consignes puis travailler la projection après passe.")
        elif group in {"full_back", "wing_back"}:
            attempts = _number(target.get("Defensive challenges"), missing_zero=True)
            rate = _rate(target.get("Defensive challenges won, %"))
            crosses = _number(target.get("Crosses"), missing_zero=True)
            cross_rate = _rate(target.get("Crosses accurate, %"))
            if attempts and rate is not None and rate >= 70:
                strengths.append(
                    f"Solidité dans le couloir : {round(attempts * rate / 100)}/{round(attempts)} "
                    f"duels défensifs gagnés ({rate:.0f} %)."
                )
            if crosses >= 2 and cross_rate is not None:
                strengths.append(
                    f"Activité de centre : {crosses:.0f} tentatives, dont environ "
                    f"{round(crosses * cross_rate / 100)} réussie(s) ({cross_rate:.0f} %)."
                )
        elif group == "centre_back":
            aerial = _number(target.get("Aerial challenges"), missing_zero=True)
            aerial_rate = _rate(target.get("Aerial challenges won, %"))
            if aerial and aerial_rate is not None and aerial_rate >= 70:
                strengths.append(f"Maîtrise aérienne : {round(aerial * aerial_rate / 100)}/{round(aerial)} duels gagnés ({aerial_rate:.0f} %).")
        elif group == "winger":
            dribbles = _number(target.get("Dribbles"), missing_zero=True)
            box_actions = _number(target.get("Actions in opponent's box"), missing_zero=True)
            if dribbles or box_actions:
                strengths.append(f"Menace de couloir : {dribbles:.0f} dribble(s) et {box_actions:.0f} action(s) dans la surface.")
        elif group == "attacking_midfielder":
            key = _number(target.get("Key passes"), missing_zero=True)
            box = _number(target.get("Passes into the penalty box"), missing_zero=True)
            if key or box:
                strengths.append(f"Création entre les lignes : {key:.0f} passe(s) clé(s) et {box:.0f} passe(s) dans la surface.")
        elif group == "holding_midfielder":
            recoveries = _number(target.get("Ball recoveries"), missing_zero=True)
            own_losses = _number(target.get("Lost balls in own half"), missing_zero=True)
            if recoveries and own_losses == 0:
                strengths.append(f"Protection propre de l’axe : {recoveries:.0f} récupération(s) sans perte enregistrée dans son camp.")
    elif language == "en":
        if group == "goalkeeper":
            risks.append(
                "The Players export contains no saves, goals prevented or post-shot data; "
                "assessment of the goalkeeper's primary mission remains partial."
            )
        elif group == "forward":
            shots = _number(target.get("Shots"), missing_zero=True)
            box_shots = _number(target.get("Shots from the penalty area"), missing_zero=True)
            goals = _number(target.get("Goals"), missing_zero=True)
            box_actions = _number(target.get("Actions in opponent's box"), missing_zero=True)
            headers = _number(target.get("Headers"), missing_zero=True)
            header_rate = _rate(target.get("Headers on target, %"))
            if shots >= 3 and box_shots >= max(2, shots * 0.60):
                strengths.append(f"Finishing presence: {box_shots:.0f}/{shots:.0f} shots came from inside the box.")
            if box_actions >= _window_target(6, minutes):
                strengths.append(f"Regular occupation of the decisive zone with {box_actions:.0f} box actions.")
            if box_actions >= 3 and shots == 0:
                risks.append(
                    f"Box presence ({box_actions:.0f} actions) did not become a shot; review positioning "
                    "before the final pass and first-contact preparation."
                )
            if shots >= 3 and goals == 0:
                risks.append(
                    f"The presence was positive, but {shots:.0f} shots did not produce a goal: improve "
                    "selection and execution without discounting access to chances."
                )
            if headers >= 2 and header_rate is not None and header_rate >= 50:
                strengths.append(
                    f"Credible aerial threat: {round(headers * header_rate / 100)}/{round(headers)} "
                    f"headers on target ({header_rate:.0f}%)."
                )
            elif headers >= 3 and header_rate is not None and header_rate < 35:
                risks.append(
                    f"Real aerial access ({headers:.0f} headers), but limited accuracy ({header_rate:.0f}%): "
                    "work on run timing, body orientation and contact zone."
                )
    else:
        if group == "goalkeeper":
            risks.append("لا يتضمن ملف اللاعبين بيانات التصديات أو ما بعد التسديدة، لذلك يبقى تقييم المهمة الأساسية للحارس جزئيا.")
        elif group == "forward":
            shots = _number(target.get("Shots"), missing_zero=True)
            box_shots = _number(target.get("Shots from the penalty area"), missing_zero=True)
            goals = _number(target.get("Goals"), missing_zero=True)
            if shots >= 3 and box_shots >= max(2, shots * 0.60):
                strengths.append(f"حضور تهديفي واضح: {box_shots:.0f}/{shots:.0f} تسديدات من داخل المنطقة.")
            if shots >= 3 and goals == 0:
                risks.append(f"الحضور إيجابي لكن {shots:.0f} تسديدات لم تنتج هدفا؛ يجب تطوير اختيار التسديدة والتنفيذ.")
    return strengths, risks


def _coaching(group, key, language):
    if key == "impact":
        return {
            "fr": "Revoir les actions décisives et les situations de création pour reproduire les bons choix et améliorer la dernière exécution.",
            "en": "Review decisive actions and creation situations to repeat the right choices and improve the final execution.",
            "ar": "مراجعة اللقطات الحاسمة وحالات صناعة اللعب لتكرار القرار الجيد وتحسين التنفيذ الأخير.",
        }[language]
    if language == "fr":
        return ROLE_COACHING_FR.get(group, {}).get(
            key,
            "Confirmer la cause en vidéo puis répéter la situation à l’entraînement.",
        )
    if language == "en":
        return "Confirm the cause on video, then rehearse the role-specific situation at match speed."
    return "تأكيد السبب بالفيديو ثم تكرار الحالة الخاصة بالمركز بسرعة المباراة."


def _narrative(target, dimensions, confidence, verdict, rankings, language):
    name = str(target.get("Player") or "")
    position = _position(target)
    group = _group(target)
    role = TEXT[language]["roles"][group]
    observed = [dimension for dimension in dimensions if dimension.get("coverage")]
    best = max(observed, key=lambda item: item["score"]) if observed else None
    weak = min(observed, key=lambda item: item["score"]) if observed else None
    is_entry = verdict.get("appearance_type") == "entry"
    if language == "fr":
        evaluation = "Lecture de son entrée" if is_entry else "Verdict sur son match"
        summary = (
            f"{name} a joué {round(_minutes(target))} minutes au poste de {position} ({role}). "
            f"{evaluation} : {verdict['label'].lower()}. "
            f"La fiabilité pour juger cette apparition est {confidence['label'].lower()}."
        )
        if rankings.get("summary"):
            summary += f" {rankings['summary']}"
        if best and best.get("headline_evidence"):
            summary += f" Sa mission la plus convaincante est {best['label'].lower()} ({_evidence_sentence(best['headline_evidence'][0])})."
        if weak and weak is not best and weak.get("headline_evidence"):
            summary += f" La priorité concerne {weak['label'].lower()} ({_evidence_sentence(weak['headline_evidence'][0])})."
    elif language == "en":
        evaluation = "Impact off the bench" if is_entry else "Match verdict"
        summary = (
            f"{name} played {round(_minutes(target))} minutes as {position} ({role}). "
            f"{evaluation}: {verdict['label'].lower()}. "
            f"Reliability for this appearance is {confidence['label'].lower()}."
        )
        if rankings.get("summary"):
            summary += f" {rankings['summary']}"
        if best and best.get("headline_evidence"):
            summary += f" The strongest mission was {best['label'].lower()} ({_evidence_sentence(best['headline_evidence'][0])})."
        if weak and weak is not best and weak.get("headline_evidence"):
            summary += f" The priority is {weak['label'].lower()} ({_evidence_sentence(weak['headline_evidence'][0])})."
    else:
        summary = (
            f"شارك {name} لمدة {round(_minutes(target))} دقيقة في مركز {position} ({role}). "
            f"التقييم: {verdict['label']} وموثوقية العينة {confidence['label']}."
        )
        if rankings.get("summary"):
            summary += f" {rankings['summary']}"
    strengths, risks = [], []
    for dimension in sorted(observed, key=lambda item: item["score"], reverse=True):
        evidence = dimension.get("positive_evidence") or []
        if dimension["score"] >= 65 and evidence:
            strengths.append(f"{dimension['stamp']} — " + " ; ".join(_evidence_sentence(item) for item in evidence))
        negative_evidence = dimension.get("negative_evidence") or []
        if dimension["score"] < 48 and negative_evidence:
            risks.append(f"{dimension['stamp']} — " + " ; ".join(_evidence_sentence(item) for item in negative_evidence))
    extra_strengths, extra_risks = _role_specific_observations(target, group, language)
    strengths.extend(extra_strengths)
    risks.extend(extra_risks)
    if not strengths:
        strengths.append({
            "fr": "Aucun point fort n’est suffisamment robuste pour être affirmé ; conserver les actions positives comme hypothèses à confirmer en vidéo.",
            "en": "No strength is robust enough to assert; retain positive events as video-review hypotheses.",
            "ar": "لا توجد نقطة قوة ثابتة بما يكفي ويجب تأكيد المؤشرات الإيجابية بالفيديو.",
        }[language])
    if not risks:
        risks.append({
            "fr": "Aucune faiblesse statistique robuste n’est isolée ; la taille de l’échantillon et le contexte tactique restent les principales limites.",
            "en": "No robust statistical weakness is isolated; sample size and tactical context remain the main limitations.",
            "ar": "لا توجد نقطة ضعف إحصائية ثابتة وتبقى العينة والسياق التكتيكي أهم الحدود.",
        }[language])
    development = []
    for dimension in sorted(observed, key=lambda item: item["score"]):
        if dimension["score"] < 60 or len(development) < 2:
            development.append(_coaching(group, dimension["key"], language))
        if len(development) >= 3:
            break
    return {
        "executive_summary": summary,
        "strengths": list(dict.fromkeys(strengths))[:5],
        "risks": list(dict.fromkeys(risks))[:5],
        "development": list(dict.fromkeys(development))[:3],
        "sample_caution": TEXT[language]["sample_caution"],
        "video_limit": TEXT[language]["video_limit"],
    }


def _appendix_metrics(target, language):
    group = _group(target)
    role_metrics = set(KEY_METRICS[group])
    for dimension in _dimension_specs(group):
        role_metrics.update(specification["metric"] for specification in dimension[1:])
    decisive_metrics = {
        "Goals", "Assists", "Mistakes leading to goals", "Mistakes leading to chances",
        "Chances", "Chances successful", "Chances successful, %", "Chances created",
        "Involvement in scoring attacks", "Index",
    }
    columns = list(SPORTSBASE_PLAYER_COLUMNS)
    columns.extend(metric for metric in target if metric not in columns)
    not_assessed = {
        "fr": "0 tentative · non évalué",
        "en": "0 attempts · not assessed",
        "ar": "0 محاولة · غير مقيم",
    }[language]

    def category_for(metric):
        for category, metrics in APPENDIX_CATEGORIES.items():
            if metric in metrics:
                return category
        return "other"

    def display_value(metric):
        raw = target.get(metric)
        if metric in {"Player", "Team", "Position"}:
            return str(raw or "—")
        if metric == "Index":
            return _format_number(_number(raw))
        if metric in {"№", "Minutes played"}:
            return _format_number(_number(raw, missing_zero=True))
        denominator = PERCENT_DENOMINATORS.get(metric)
        if denominator:
            attempts = _number(target.get(denominator), missing_zero=True)
            rate = _rate(raw)
            if attempts <= 0 or rate is None:
                return not_assessed
            successes = max(0, min(round(attempts), round(attempts * rate / 100)))
            return f"{successes}/{round(attempts)} · {_format_number(rate)}%"
        if "%" in metric:
            rate = _rate(raw)
            return not_assessed if rate is None else f"{_format_number(rate)}%"
        number = _number(raw)
        if number is not None:
            return _format_number(number)
        # A blank or dash in a statistical count means no registered event.
        return "0"

    items = []
    for source_order, metric in enumerate(columns):
        category = category_for(metric)
        role_specific = metric in role_metrics
        decisive = metric in decisive_metrics
        items.append(
            {
                "metric": metric,
                "label": _label(metric, language),
                "display": display_value(metric),
                "category": category,
                "category_label": APPENDIX_CATEGORY_LABELS[language][category],
                "role_specific": role_specific,
                "decisive": decisive,
                "priority": 0 if decisive else 1 if role_specific else 2,
                "source_order": source_order,
            }
        )
    items.sort(
        key=lambda item: (
            tuple(APPENDIX_CATEGORY_LABELS[language]).index(item["category"]),
            item["priority"],
            item["source_order"],
        )
    )
    groups = []
    for category in APPENDIX_CATEGORY_LABELS[language]:
        category_items = [item for item in items if item["category"] == category]
        if category_items:
            groups.append(
                {
                    "key": category,
                    "label": APPENDIX_CATEGORY_LABELS[language][category],
                    "items": category_items,
                }
            )
    return {"items": items, "groups": groups, "total_columns": len(columns)}


def analyse_match_dataset(rows, player_name, language="fr", context=None):
    """Build a complete JSON-safe player analysis for one match."""
    language = language if language in TEXT else "fr"
    rows = [dict(row) for row in rows if isinstance(row, dict)]
    target = next((row for row in rows if _plain(row.get("Player")) == _plain(player_name)), None)
    if target is None:
        return {
            "version": ANALYSIS_VERSION,
            "available": False,
            "reason": "player_not_found",
            "player_name": player_name,
            "methodology_sources": list(METHODOLOGY_SOURCES),
        }
    target_team = str(target.get("Team") or "")
    other_teams = [
        team for team in dict.fromkeys(str(row.get("Team") or "") for row in rows)
        if team and team != target_team
    ]
    opponent_team = other_teams[0] if other_teams else ""
    group = _group(target)
    homologous_codes = set(_homologous_position_codes(_position(target)))
    population = [row for row in rows if _position(row) in homologous_codes and _minutes(row) > 0]
    dimensions = _role_dimensions(target, group, language)
    performance_lenses = _performance_lenses(target, dimensions, group, language)
    profile_score = _overall_score(dimensions)
    rankings = _rankings(target, rows, dimensions, language)
    score_breakdown = _score_breakdown(
        dimensions,
        language,
        target=target,
        rankings=rankings,
    )
    ms_score = score_breakdown.get("total_points")
    confidence = _confidence(_minutes(target), language)
    context_payload = _context_payload(target, context, language)
    position_benchmark = _position_benchmark(target, context, group, language)
    key_metrics = _key_metrics(target, population, group, language)
    verdict = _verdict(
        ms_score,
        language,
        target=target,
        rankings=rankings,
        mission_quality_score=profile_score,
    )
    opponents = [row for row in rows if str(row.get("Team") or "") == opponent_team]
    copy = TEXT[language]
    counterpart = _same_position_comparison(
        target,
        opponents,
        copy["counterpart"],
        language,
        KEY_METRICS[group],
        group,
    )
    global_benchmarks = _global_benchmarks(target, rows, group, language)
    narrative = _narrative(target, dimensions, confidence, verdict, rankings, language)
    appendix = _appendix_metrics(target, language)
    return {
        "version": ANALYSIS_VERSION,
        "available": True,
        "language": language,
        "player": {
            "name": str(target.get("Player") or player_name),
            "team": target_team,
            "opponent": opponent_team,
            "position": _position(target),
            "positions": list(_position_codes(target)),
            "role_group": group,
            "role_label": copy["roles"][group],
            "minutes": round(_minutes(target)),
            "index": _number(target.get("Index")),
            "profile_score": profile_score,
            "ms_score": ms_score,
        },
        "verdict": verdict,
        "decisive_highlights": _decisive_highlights(target, language),
        "confidence": confidence,
        "context": context_payload,
        "rankings": rankings,
        "dimensions": dimensions,
        "performance_lenses": performance_lenses,
        "score_breakdown": score_breakdown,
        "position_benchmark": position_benchmark,
        "key_metrics": key_metrics,
        "same_position_comparison": counterpart,
        "global_benchmarks": global_benchmarks,
        "narrative": narrative,
        "glossary": [
            {"metric": metric, "label": _label(metric, language), "definition": definition}
            for metric, definition in METRIC_DEFINITIONS.get(language, {}).items()
            if metric in KEY_METRICS[group]
            or metric in {"Progressive passes", "Key passes", "Final third entries", "xG (expected goals)"}
        ],
        "appendix_metrics": appendix["items"],
        "appendix_groups": appendix["groups"],
        "appendix_total_columns": appendix["total_columns"],
        "population": {
            "position": _position(target),
            "players": len(population),
            "comparable_minutes": len(_same_minute_window(target, population)),
            "description": (
                "Only players listed in the same position or its strict formation equivalent are used for the direct comparison. "
                "Global match leaders remain individual and rates require at least three attempts."
            ),
        },
        "methodology": {
            "volume_normalisation": "none_raw_match_totals",
            "duration_calibration": "six_coarse_playing_time_windows",
            "rate_aggregation": "weighted_by_attempts",
            "comparison_scope": "same_or_strictly_equivalent_position_and_individual_match_leaders_only",
            "collective_unit_analysis": False,
            "match_result_context_analysis": False,
            "index_usage": "explicit_verdict_validation_signal",
            "position_benchmark_selection": "highest_stored_position_percentage",
            "position_benchmark_scale": "real_per_90_player_vs_position_average_axis_normalized_for_shape_only",
            "performance_reading": "three_non_overlapping_lenses_global_attacking_defensive",
            "xlsx_integrity": "all_players_sheet_columns_preserved_with_zero_events_explicit",
            "raw_volume_vs_season_index_comparison": False,
            "no_opportunity_rule": "zero_attempts_is_not_a_weakness",
            "video_confirmation_required": True,
        },
        "methodology_sources": list(METHODOLOGY_SOURCES),
    }


def build_match_analysis(match, language=None):
    try:
        stats = match.player_stats
    except Exception:
        return {
            "version": ANALYSIS_VERSION,
            "available": False,
            "reason": "match_stats_missing",
            "methodology_sources": list(METHODOLOGY_SOURCES),
        }
    rows = getattr(stats, "players_statistics_rows", None) or []
    language = language or getattr(match.subscription, "report_language", "fr")
    match_date = getattr(match, "match_date", "")
    context = {
        "home_team": getattr(match, "home_team", ""),
        "away_team": getattr(match, "away_team", ""),
        "score": getattr(match, "score", ""),
        "match_date": match_date.isoformat() if hasattr(match_date, "isoformat") else str(match_date or ""),
        "source_metadata": getattr(stats, "source_metadata", None) or {},
    }
    subscription = getattr(match, "subscription", None)
    snapshots = getattr(subscription, "season_snapshots", None)
    if snapshots is not None and hasattr(snapshots, "filter"):
        snapshot = (
            snapshots.filter(season=getattr(match, "season", ""))
            .order_by("-synced_at")
            .first()
        )
        if snapshot is not None:
            context["position_benchmark"] = {
                "season": getattr(snapshot, "season", ""),
                "positions": getattr(snapshot, "positions", None) or [],
                "radar_metrics": getattr(snapshot, "radar_metrics", None) or [],
            }
    return analyse_match_dataset(
        rows,
        getattr(subscription.player, "name", ""),
        language=language,
        context=context,
    )
