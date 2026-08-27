"""Position-aware match analysis built from SportsBase Players XLSX data."""

import math
import re
import unicodedata
from collections import defaultdict


ANALYSIS_VERSION = "position-context-v1-20260827"

METHODOLOGY_SOURCES = (
    {
        "name": "FIFA Football Language",
        "url": (
            "https://www.fifatrainingcentre.com/en/game/performance-analysis/"
            "football-language-analysis/the-fifa-football-language.php"
        ),
    },
    {
        "name": "FIFA Talent Identification Guide - Player profiles",
        "url": (
            "https://www.fifatrainingcentre.com/en/environment/guide/"
            "high-performance/find/talent-identification-guide-module-2.php"
        ),
    },
    {
        "name": "FIFA Scales of the game",
        "url": (
            "https://www.fifatrainingcentre.com/en/practice/"
            "talent-coach-programme/training-framework/scales-of-the-game.php"
        ),
    },
    {
        "name": "StatsBomb - Understanding radars and per-90 metrics",
        "url": (
            "https://blogarchive.statsbomb.com/articles/soccer/"
            "understanding-statsbomb-radars/"
        ),
    },
)


TEXT = {
    "fr": {
        "roles": {
            "goalkeeper": "Gardien",
            "centre_back": "Défenseur central",
            "wide_defender": "Latéral / piston",
            "holding_midfielder": "Milieu défensif",
            "central_midfielder": "Milieu central",
            "attacking_midfielder": "Milieu offensif / ailier",
            "forward": "Attaquant",
        },
        "units": {
            "defence": "Défense centrale",
            "midfield": "Milieu",
            "corridors": "Couloirs",
            "attack": "Attaque",
        },
        "confidence": {
            "very_low": "Très limitée",
            "limited": "Limitée",
            "moderate": "Modérée",
            "high": "Élevée",
        },
        "confidence_text": {
            "very_low": (
                "Entrée très courte : lecture descriptive uniquement, sans conclusion "
                "sur le niveau durable du joueur."
            ),
            "limited": (
                "Échantillon partiel : les tendances sont indicatives et doivent être "
                "confirmées par la vidéo et plusieurs matchs."
            ),
            "moderate": (
                "Temps de jeu significatif mais incomplet : la lecture du match est "
                "exploitable, sans constituer encore une référence stable."
            ),
            "high": (
                "Temps de jeu suffisant pour une lecture solide de cette rencontre, "
                "à replacer malgré tout dans le contexte collectif."
            ),
        },
        "sample_summary": (
            "{player} a disputé {minutes} minutes au poste de {position} ({role}). "
            "La fiabilité de l’échantillon est {confidence}."
        ),
        "relative_profile": (
            "Le profil relatif de ce match est le plus favorable sur {best} et le plus "
            "fragile sur {weak}. Ces scores situent la production dans ce match, pas "
            "la valeur absolue du joueur."
        ),
        "no_relative_profile": (
            "Le volume disponible ne permet pas de construire un profil relatif fiable."
        ),
        "sample_caution": (
            "Ne pas extrapoler les ratios à 90 minutes comme une prévision : ils servent "
            "uniquement à rendre les volumes comparables."
        ),
        "unit_edge": "Avantage {team} sur {won}/{total} indicateurs observés.",
        "unit_even": "Lecture équilibrée : aucun avantage net sur les indicateurs retenus.",
        "homologue": "Homologue adverse",
        "direct_channel": "Opposition directe dans le couloir / la zone",
        "strength_fallback": (
            "Aucun point fort statistique suffisamment robuste n’est isolé sur cet "
            "échantillon ; la vidéo doit compléter la lecture."
        ),
        "risk_fallback": (
            "La principale réserve concerne la taille de l’échantillon et le contexte "
            "tactique non entièrement observable dans les événements."
        ),
    },
    "en": {
        "roles": {
            "goalkeeper": "Goalkeeper",
            "centre_back": "Centre-back",
            "wide_defender": "Full-back / wing-back",
            "holding_midfielder": "Holding midfielder",
            "central_midfielder": "Central midfielder",
            "attacking_midfielder": "Attacking midfielder / winger",
            "forward": "Forward",
        },
        "units": {
            "defence": "Central defence",
            "midfield": "Midfield",
            "corridors": "Wide channels",
            "attack": "Attack",
        },
        "confidence": {
            "very_low": "very limited",
            "limited": "limited",
            "moderate": "moderate",
            "high": "high",
        },
        "confidence_text": {
            "very_low": (
                "Very short appearance: descriptive reading only, with no conclusion "
                "about the player's sustainable level."
            ),
            "limited": (
                "Partial sample: trends are indicative and must be confirmed through "
                "video review and several matches."
            ),
            "moderate": (
                "Meaningful but incomplete playing time: useful match evidence, not yet "
                "a stable performance benchmark."
            ),
            "high": (
                "Enough playing time for a strong reading of this match, while still "
                "requiring collective and tactical context."
            ),
        },
        "sample_summary": (
            "{player} played {minutes} minutes as {position} ({role}). Sample "
            "reliability is {confidence}."
        ),
        "relative_profile": (
            "The match-relative profile is strongest in {best} and most fragile in "
            "{weak}. These scores describe production in this match, not the player's "
            "absolute ability."
        ),
        "no_relative_profile": (
            "The available volume is insufficient for a reliable relative profile."
        ),
        "sample_caution": (
            "Do not treat per-90 ratios as a forecast: they are used only to make "
            "playing-time volumes comparable."
        ),
        "unit_edge": "{team} leads on {won}/{total} observed indicators.",
        "unit_even": "Balanced reading: no clear edge across the selected indicators.",
        "homologue": "Opposition role counterpart",
        "direct_channel": "Direct opponent in the channel / zone",
        "strength_fallback": (
            "No statistical strength is robust enough to isolate in this sample; video "
            "review must complete the assessment."
        ),
        "risk_fallback": (
            "The main reservation is sample size and the tactical context that event "
            "data cannot fully capture."
        ),
    },
    "ar": {
        "roles": {
            "goalkeeper": "حارس مرمى",
            "centre_back": "قلب دفاع",
            "wide_defender": "ظهير / جناح دفاعي",
            "holding_midfielder": "وسط دفاعي",
            "central_midfielder": "وسط مركزي",
            "attacking_midfielder": "وسط هجومي / جناح",
            "forward": "مهاجم",
        },
        "units": {
            "defence": "قلب الدفاع",
            "midfield": "خط الوسط",
            "corridors": "الأطراف",
            "attack": "الهجوم",
        },
        "confidence": {
            "very_low": "محدودة جدا",
            "limited": "محدودة",
            "moderate": "متوسطة",
            "high": "مرتفعة",
        },
        "confidence_text": {
            "very_low": "مشاركة قصيرة جدا: قراءة وصفية دون حكم على المستوى المستدام للاعب.",
            "limited": "عينة جزئية يجب تأكيدها بالفيديو وبعدة مباريات.",
            "moderate": "وقت لعب مهم لكنه غير كامل ويعطي مؤشرات خاصة بهذه المباراة.",
            "high": "وقت لعب يسمح بقراءة قوية للمباراة مع ضرورة مراعاة السياق الجماعي.",
        },
        "sample_summary": (
            "شارك {player} لمدة {minutes} دقيقة في مركز {position} ({role}). "
            "درجة موثوقية العينة {confidence}."
        ),
        "relative_profile": (
            "أفضل محور نسبي في هذه المباراة هو {best}، بينما يحتاج محور {weak} إلى "
            "أكبر تطوير. هذه الدرجات تصف المباراة فقط ولا تحكم على القيمة المطلقة للاعب."
        ),
        "no_relative_profile": "حجم البيانات لا يسمح ببناء ملف نسبي موثوق.",
        "sample_caution": (
            "لا يجب اعتبار المعدلات لكل 90 دقيقة توقعا للمستقبل؛ هي فقط أداة لمقارنة "
            "الأحجام بين أوقات لعب مختلفة."
        ),
        "unit_edge": "أفضلية {team} في {won} من أصل {total} مؤشرات.",
        "unit_even": "قراءة متوازنة دون أفضلية واضحة في المؤشرات المختارة.",
        "homologue": "اللاعب المقابل في نفس الدور",
        "direct_channel": "المنافس المباشر في الرواق / المنطقة",
        "strength_fallback": "لا توجد نقطة قوة إحصائية ثابتة في هذه العينة ويجب إكمالها بالفيديو.",
        "risk_fallback": "التحفظ الرئيسي هو قصر العينة وغياب جزء من السياق التكتيكي.",
    },
}


METRIC_LABELS = {
    "fr": {
        "Passes": "Passes",
        "Passes accurate, %": "Précision des passes",
        "Progressive passes": "Passes progressives",
        "Progressive passes accurate, %": "Précision progressive",
        "Long passes": "Passes longues",
        "Long passes accurate, %": "Précision des passes longues",
        "Passes into the penalty box": "Passes dans la surface",
        "Passes into the penalty box accurate, %": "Précision vers la surface",
        "Key passes": "Passes clés",
        "Crosses": "Centres",
        "Crosses accurate, %": "Précision des centres",
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
        "Tackles": "Tacles",
        "Tackles successful, %": "Tacles réussis",
        "Interceptions": "Interceptions",
        "Shots": "Tirs",
        "Shots on target, %": "Tirs cadrés",
        "xG (expected goals)": "xG",
        "Final third entries": "Entrées dans le dernier tiers",
        "Lost balls": "Ballons perdus",
        "Lost balls in own half": "Pertes dans son camp",
        "Ball recoveries": "Récupérations",
        "Ball recoveries in opponent's half": "Récupérations hautes",
        "Actions": "Actions",
        "Actions successful, %": "Actions réussies",
        "Actions in opponent's box": "Actions dans la surface adverse",
        "Actions in opponent's box successful, %": "Réussite dans la surface",
    },
    "en": {
        "Passes": "Passes",
        "Passes accurate, %": "Pass accuracy",
        "Progressive passes": "Progressive passes",
        "Progressive passes accurate, %": "Progressive-pass accuracy",
        "Long passes": "Long passes",
        "Long passes accurate, %": "Long-pass accuracy",
        "Passes into the penalty box": "Passes into the penalty area",
        "Passes into the penalty box accurate, %": "Penalty-area pass accuracy",
        "Key passes": "Key passes",
        "Crosses": "Crosses",
        "Crosses accurate, %": "Cross accuracy",
        "Challenges": "Duels",
        "Challenges won, %": "Duels won",
        "Defensive challenges": "Defensive duels",
        "Defensive challenges won, %": "Defensive duels won",
        "Attacking challenges": "Attacking duels",
        "Attacking challenges won, %": "Attacking duels won",
        "Aerial challenges": "Aerial duels",
        "Aerial challenges won, %": "Aerial duels won",
        "Dribbles": "Dribbles",
        "Dribbles successful, %": "Successful dribbles",
        "Tackles": "Tackles",
        "Tackles successful, %": "Successful tackles",
        "Interceptions": "Interceptions",
        "Shots": "Shots",
        "Shots on target, %": "Shots on target",
        "xG (expected goals)": "Expected goals (xG)",
        "Final third entries": "Final-third entries",
        "Lost balls": "Ball losses",
        "Lost balls in own half": "Ball losses in own half",
        "Ball recoveries": "Ball recoveries",
        "Ball recoveries in opponent's half": "High recoveries",
        "Actions": "Actions",
        "Actions successful, %": "Successful actions",
        "Actions in opponent's box": "Actions in the opposition box",
        "Actions in opponent's box successful, %": "Successful box actions",
    },
    "ar": {
        "Passes": "التمريرات",
        "Passes accurate, %": "دقة التمرير",
        "Progressive passes": "التمريرات التقدمية",
        "Progressive passes accurate, %": "دقة التمرير التقدمي",
        "Long passes": "التمريرات الطويلة",
        "Long passes accurate, %": "دقة التمرير الطويل",
        "Passes into the penalty box": "تمريرات داخل منطقة الجزاء",
        "Key passes": "التمريرات المفتاحية",
        "Crosses": "العرضيات",
        "Crosses accurate, %": "دقة العرضيات",
        "Challenges": "الثنائيات",
        "Challenges won, %": "الثنائيات الناجحة",
        "Defensive challenges": "الثنائيات الدفاعية",
        "Defensive challenges won, %": "نجاح الثنائيات الدفاعية",
        "Attacking challenges": "الثنائيات الهجومية",
        "Attacking challenges won, %": "نجاح الثنائيات الهجومية",
        "Aerial challenges": "الثنائيات الهوائية",
        "Aerial challenges won, %": "نجاح الثنائيات الهوائية",
        "Dribbles": "المراوغات",
        "Dribbles successful, %": "المراوغات الناجحة",
        "Tackles": "التدخلات",
        "Interceptions": "الاعتراضات",
        "Shots": "التسديدات",
        "Shots on target, %": "التسديدات المؤطرة",
        "xG (expected goals)": "الأهداف المتوقعة",
        "Final third entries": "دخول الثلث الأخير",
        "Lost balls": "الكرات المفقودة",
        "Lost balls in own half": "فقدان الكرة في نصف الملعب",
        "Ball recoveries": "استرجاع الكرة",
        "Ball recoveries in opponent's half": "استرجاع الكرة عاليا",
        "Actions": "الإجراءات",
        "Actions successful, %": "الإجراءات الناجحة",
        "Actions in opponent's box": "الإجراءات داخل منطقة المنافس",
    },
}


RATE_WEIGHTS = {
    "Passes accurate, %": "Passes",
    "Key passes accurate, %": "Key passes",
    "Crosses accurate, %": "Crosses",
    "Progressive passes accurate, %": "Progressive passes",
    "Long passes accurate, %": "Long passes",
    "Super long passes accurate, %": "Super long passes",
    "Passes forward to the final third accurate, %": (
        "Passes forward to the final third"
    ),
    "Passes into the penalty box accurate, %": "Passes into the penalty box",
    "Challenges won, %": "Challenges",
    "Defensive challenges won, %": "Defensive challenges",
    "Attacking challenges won, %": "Attacking challenges",
    "Aerial challenges won, %": "Aerial challenges",
    "Dribbles successful, %": "Dribbles",
    "Dribbling in the final third successful, %": "Dribbling in the final third",
    "Tackles successful, %": "Tackles",
    "Shots on target, %": "Shots",
    "Actions successful, %": "Actions",
    "Actions in opponent's box successful, %": "Actions in opponent's box",
}


POSITION_GROUPS = {
    "GK": "goalkeeper",
    "CB": "centre_back",
    "LCB": "centre_back",
    "RCB": "centre_back",
    "LB": "wide_defender",
    "RB": "wide_defender",
    "LWB": "wide_defender",
    "RWB": "wide_defender",
    "CDM": "holding_midfielder",
    "DM": "holding_midfielder",
    "CM": "central_midfielder",
    "LCM": "central_midfielder",
    "RCM": "central_midfielder",
    "CAM": "attacking_midfielder",
    "LAM": "attacking_midfielder",
    "RAM": "attacking_midfielder",
    "LM": "attacking_midfielder",
    "RM": "attacking_midfielder",
    "LW": "attacking_midfielder",
    "RW": "attacking_midfielder",
    "CF": "forward",
    "LCF": "forward",
    "RCF": "forward",
    "ST": "forward",
}


UNIT_POSITIONS = {
    "defence": {"CB", "LCB", "RCB"},
    "midfield": {"CDM", "DM", "CM", "LCM", "RCM", "CAM"},
    "corridors": {"LB", "RB", "LWB", "RWB"},
    "attack": {"LAM", "RAM", "LM", "RM", "LW", "RW", "CF", "LCF", "RCF", "ST"},
}


ROLE_DIMENSIONS = {
    "goalkeeper": (
        ("distribution", ("Passes", "p90", 1), ("Passes accurate, %", "rate", 1)),
        ("long_distribution", ("Long passes", "p90", 1), ("Long passes accurate, %", "rate", 1), ("Super long passes", "p90", 1)),
        ("progression", ("Progressive passes", "p90", 1), ("Passes forward to the final third", "p90", 1)),
        ("sweeping", ("Interceptions", "p90", 1), ("Ball recoveries", "p90", 1)),
        ("risk_control", ("Lost balls in own half", "p90", -1), ("Mistakes leading to chances", "p90", -1), ("Mistakes leading to goals", "p90", -1)),
    ),
    "centre_back": (
        ("build_up", ("Passes", "p90", 1), ("Passes accurate, %", "rate", 1)),
        ("progression", ("Progressive passes", "p90", 1), ("Progressive passes accurate, %", "rate", 1)),
        ("ground_control", ("Defensive challenges", "p90", 1), ("Defensive challenges won, %", "rate", 1), ("Interceptions", "p90", 1)),
        ("aerial_control", ("Aerial challenges", "p90", 1), ("Aerial challenges won, %", "rate", 1)),
        ("risk_control", ("Lost balls in own half", "p90", -1), ("Mistakes leading to chances", "p90", -1), ("Mistakes leading to goals", "p90", -1)),
    ),
    "wide_defender": (
        ("progression", ("Progressive passes", "p90", 1), ("Final third entries", "p90", 1), ("Passes into the penalty box", "p90", 1)),
        ("delivery", ("Crosses", "p90", 1), ("Crosses accurate, %", "rate", 1), ("Key passes", "p90", 1)),
        ("ball_security", ("Passes accurate, %", "rate", 1), ("Actions successful, %", "rate", 1), ("Lost balls in own half", "p90", -1)),
        ("defending", ("Defensive challenges", "p90", 1), ("Defensive challenges won, %", "rate", 1), ("Interceptions", "p90", 1), ("Tackles", "p90", 1)),
        ("attacking_support", ("Dribbles", "p90", 1), ("Dribbles successful, %", "rate", 1), ("Actions in opponent's box", "p90", 1)),
    ),
    "holding_midfielder": (
        ("circulation", ("Passes", "p90", 1), ("Passes accurate, %", "rate", 1)),
        ("progression", ("Progressive passes", "p90", 1), ("Passes forward to the final third", "p90", 1), ("Final third entries", "p90", 1)),
        ("ball_winning", ("Defensive challenges", "p90", 1), ("Defensive challenges won, %", "rate", 1), ("Interceptions", "p90", 1)),
        ("transition_control", ("Ball recoveries", "p90", 1), ("Tackles", "p90", 1), ("Lost balls in own half", "p90", -1)),
        ("duel_presence", ("Challenges", "p90", 1), ("Challenges won, %", "rate", 1), ("Aerial challenges won, %", "rate", 1)),
    ),
    "central_midfielder": (
        ("circulation", ("Passes", "p90", 1), ("Passes accurate, %", "rate", 1)),
        ("progression", ("Progressive passes", "p90", 1), ("Final third entries", "p90", 1)),
        ("creation", ("Key passes", "p90", 1), ("Passes into the penalty box", "p90", 1), ("Passes for a shot", "p90", 1)),
        ("duel_presence", ("Challenges", "p90", 1), ("Challenges won, %", "rate", 1), ("Ball recoveries", "p90", 1)),
        ("territorial_impact", ("Actions in opponent's box", "p90", 1), ("Ball recoveries in opponent's half", "p90", 1), ("Lost balls", "p90", -1)),
    ),
    "attacking_midfielder": (
        ("creation", ("Key passes", "p90", 1), ("Chances created", "p90", 1), ("Passes for a shot", "p90", 1)),
        ("progression", ("Progressive passes", "p90", 1), ("Final third entries", "p90", 1)),
        ("one_v_one", ("Dribbles", "p90", 1), ("Dribbles successful, %", "rate", 1), ("Fouls suffered", "p90", 1)),
        ("goal_threat", ("Shots", "p90", 1), ("xG (expected goals)", "p90", 1), ("Actions in opponent's box", "p90", 1)),
        ("counterpress", ("Ball recoveries in opponent's half", "p90", 1), ("Defensive challenges", "p90", 1), ("Lost balls", "p90", -1)),
    ),
    "forward": (
        ("finishing", ("Shots", "p90", 1), ("Shots on target, %", "rate", 1), ("xG (expected goals)", "p90", 1)),
        ("box_threat", ("Actions in opponent's box", "p90", 1), ("Actions in opponent's box successful, %", "rate", 1), ("Chances", "p90", 1)),
        ("link_play", ("Passes", "p90", 1), ("Passes accurate, %", "rate", 1), ("Key passes", "p90", 1)),
        ("duel_presence", ("Attacking challenges", "p90", 1), ("Attacking challenges won, %", "rate", 1), ("Aerial challenges won, %", "rate", 1)),
        ("defensive_work", ("Defensive challenges", "p90", 1), ("Ball recoveries in opponent's half", "p90", 1), ("Lost balls", "p90", -1)),
    ),
}


DIMENSION_LABELS = {
    "fr": {
        "distribution": "Distribution courte",
        "long_distribution": "Distribution longue",
        "sweeping": "Couverture derrière la ligne",
        "build_up": "Première relance",
        "progression": "Progression",
        "ground_control": "Contrôle au sol",
        "aerial_control": "Maîtrise aérienne",
        "risk_control": "Gestion du risque",
        "delivery": "Qualité de livraison",
        "ball_security": "Sécurité avec ballon",
        "defending": "Défense du couloir",
        "attacking_support": "Soutien offensif",
        "circulation": "Circulation",
        "ball_winning": "Récupération",
        "transition_control": "Contrôle des transitions",
        "duel_presence": "Présence dans les duels",
        "creation": "Création",
        "territorial_impact": "Impact territorial",
        "one_v_one": "Un contre un",
        "goal_threat": "Menace offensive",
        "counterpress": "Contre-pressing",
        "finishing": "Finition",
        "box_threat": "Présence dans la surface",
        "link_play": "Jeu de connexion",
        "defensive_work": "Travail sans ballon",
    },
    "en": {
        "distribution": "Short distribution",
        "long_distribution": "Long distribution",
        "sweeping": "Space coverage",
        "build_up": "First build-up",
        "progression": "Progression",
        "ground_control": "Ground control",
        "aerial_control": "Aerial control",
        "risk_control": "Risk management",
        "delivery": "Delivery quality",
        "ball_security": "Ball security",
        "defending": "Channel defending",
        "attacking_support": "Attacking support",
        "circulation": "Circulation",
        "ball_winning": "Ball winning",
        "transition_control": "Transition control",
        "duel_presence": "Duel presence",
        "creation": "Creation",
        "territorial_impact": "Territorial impact",
        "one_v_one": "One-v-one",
        "goal_threat": "Goal threat",
        "counterpress": "Counterpress",
        "finishing": "Finishing",
        "box_threat": "Box threat",
        "link_play": "Link play",
        "defensive_work": "Out-of-possession work",
    },
    "ar": {
        "distribution": "التوزيع القصير",
        "long_distribution": "التوزيع الطويل",
        "sweeping": "تغطية المساحة خلف الدفاع",
        "build_up": "بناء اللعب",
        "progression": "التقدم بالكرة",
        "ground_control": "السيطرة الأرضية",
        "aerial_control": "السيطرة الهوائية",
        "risk_control": "إدارة المخاطر",
        "delivery": "جودة الإرسال",
        "ball_security": "الأمان بالكرة",
        "defending": "الدفاع على الرواق",
        "attacking_support": "الدعم الهجومي",
        "circulation": "تدوير الكرة",
        "ball_winning": "افتكاك الكرة",
        "transition_control": "التحكم في التحولات",
        "duel_presence": "الحضور في الثنائيات",
        "creation": "صناعة اللعب",
        "territorial_impact": "التأثير الميداني",
        "one_v_one": "واحد ضد واحد",
        "goal_threat": "الخطورة الهجومية",
        "counterpress": "الضغط العكسي",
        "finishing": "الإنهاء",
        "box_threat": "الخطورة داخل المنطقة",
        "link_play": "الربط الهجومي",
        "defensive_work": "العمل دون كرة",
    },
}


KEY_METRICS = {
    "goalkeeper": ("Passes accurate, %", "Long passes", "Long passes accurate, %", "Progressive passes", "Interceptions", "Lost balls in own half"),
    "centre_back": ("Passes accurate, %", "Progressive passes", "Defensive challenges won, %", "Aerial challenges won, %", "Interceptions", "Lost balls in own half"),
    "wide_defender": ("Passes accurate, %", "Progressive passes", "Passes into the penalty box", "Defensive challenges won, %", "Interceptions", "Lost balls"),
    "holding_midfielder": ("Passes accurate, %", "Progressive passes", "Defensive challenges won, %", "Interceptions", "Ball recoveries", "Lost balls in own half"),
    "central_midfielder": ("Passes accurate, %", "Progressive passes", "Key passes", "Challenges won, %", "Final third entries", "Ball recoveries"),
    "attacking_midfielder": ("Key passes", "Progressive passes", "Dribbles", "Shots", "Actions in opponent's box", "Ball recoveries in opponent's half"),
    "forward": ("Shots", "xG (expected goals)", "Actions in opponent's box", "Passes accurate, %", "Attacking challenges won, %", "Lost balls"),
}


UNIT_METRICS = {
    "defence": ("Passes accurate, %", "Progressive passes", "Defensive challenges won, %", "Aerial challenges won, %", "Lost balls in own half"),
    "midfield": ("Passes accurate, %", "Progressive passes", "Final third entries", "Challenges won, %", "Ball recoveries in opponent's half"),
    "corridors": ("Progressive passes", "Passes into the penalty box", "Crosses", "Defensive challenges won, %", "Lost balls"),
    "attack": ("Shots", "xG (expected goals)", "Actions in opponent's box", "Attacking challenges won, %", "Key passes"),
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


def _position(row):
    return str(row.get("Position") or "").strip().upper()


def _group(row):
    return POSITION_GROUPS.get(_position(row), "central_midfielder")


def _metric_value(row, name, mode):
    if mode == "rate":
        return _rate(row.get(name))
    value = _number(row.get(name), missing_zero=True)
    if mode == "p90":
        minutes = _minutes(row)
        return value * 90 / minutes if minutes else None
    return value


def _metric_mode(name):
    if name in RATE_WEIGHTS or "%" in name:
        return "rate"
    return "p90"


def _format_metric(value, mode):
    if value is None:
        return "-"
    if mode == "rate":
        return f"{value:.0f}%"
    if abs(value) >= 10:
        return f"{value:.1f}/90"
    formatted = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{formatted}/90"


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


def _confidence(minutes, language):
    if minutes < 20:
        code, score = "very_low", 25
    elif minutes < 45:
        code, score = "limited", 45
    elif minutes < 75:
        code, score = "moderate", 70
    else:
        code, score = "high", 90
    copy = TEXT[language]
    return {
        "code": code,
        "score": score,
        "label": copy["confidence"][code],
        "explanation": copy["confidence_text"][code],
        "minutes": int(minutes),
    }


def _role_dimensions(target, population, group, language):
    dimensions = []
    for item in ROLE_DIMENSIONS.get(group, ROLE_DIMENSIONS["central_midfielder"]):
        key, specifications = item[0], item[1:]
        scores = []
        evidence = []
        for name, mode, direction in specifications:
            target_value = _metric_value(target, name, mode)
            population_values = [
                _metric_value(player, name, mode) for player in population
            ]
            percentile = _percentile(target_value, population_values, direction)
            if percentile is None:
                continue
            scores.append(percentile)
            evidence.append(
                {
                    "metric": name,
                    "label": METRIC_LABELS.get(language, {}).get(name, name),
                    "value": target_value,
                    "display": _format_metric(target_value, mode),
                    "percentile": percentile,
                    "direction": direction,
                }
            )
        if scores:
            dimensions.append(
                {
                    "key": key,
                    "label": DIMENSION_LABELS[language].get(key, key),
                    "score": round(sum(scores) / len(scores)),
                    "evidence": evidence,
                }
            )
    return dimensions


def _aggregate_rows(rows, label=None):
    rows = list(rows)
    if not rows:
        return {}
    total_minutes = sum(_minutes(row) for row in rows)
    headers = {key for row in rows for key in row}
    result = {
        "Player": label or " + ".join(str(row.get("Player") or "") for row in rows),
        "Team": str(rows[0].get("Team") or ""),
        "Position": "/".join(dict.fromkeys(_position(row) for row in rows)),
        "Minutes played": total_minutes,
    }
    for name in headers:
        if name in {"Player", "Team", "Position", "Minutes played", "№"}:
            continue
        if name == "Index":
            indexes = [_number(row.get(name)) for row in rows]
            indexes = [value for value in indexes if value is not None]
            result[name] = round(sum(indexes) / len(indexes), 1) if indexes else "-"
            continue
        if name in RATE_WEIGHTS:
            denominator = RATE_WEIGHTS[name]
            weighted = []
            for row in rows:
                attempts = _number(row.get(denominator), missing_zero=True)
                rate = _rate(row.get(name))
                if attempts > 0 and rate is not None:
                    weighted.append((attempts, rate))
            total_attempts = sum(attempts for attempts, _value in weighted)
            result[name] = (
                sum(attempts * value for attempts, value in weighted)
                / total_attempts
                / 100
                if total_attempts
                else "-"
            )
            continue
        if name.endswith(", % of total"):
            weighted = []
            for row in rows:
                attempts = _number(row.get("Final third entries"), missing_zero=True)
                rate = _rate(row.get(name))
                if attempts > 0 and rate is not None:
                    weighted.append((attempts, rate))
            total_attempts = sum(attempts for attempts, _value in weighted)
            result[name] = (
                sum(attempts * value for attempts, value in weighted)
                / total_attempts
                / 100
                if total_attempts
                else "-"
            )
            continue
        if "%" not in name:
            result[name] = sum(
                _number(row.get(name), missing_zero=True) for row in rows
            )
    return result


def _same_role_codes(position):
    if position in {"RWB", "RB"}:
        return {"RWB", "RB"}
    if position in {"LWB", "LB"}:
        return {"LWB", "LB"}
    if position in {"RCF", "CF", "ST"}:
        return {"RCF", "CF", "ST"}
    if position == "LCF":
        return {"LCF", "CF", "ST"}
    if position.startswith("R"):
        return {position, position[1:]}
    if position.startswith("L"):
        return {position, position[1:]}
    return {position}


def _direct_codes(position, group):
    side = "right" if position.startswith("R") else "left" if position.startswith("L") else "centre"
    if group == "wide_defender":
        return {"LB", "LWB"} if side == "right" else {"RB", "RWB"} if side == "left" else {"LB", "RB", "LWB", "RWB"}
    if group in {"forward", "attacking_midfielder"}:
        return {"LCB", "LB", "LWB"} if side == "right" else {"RCB", "RB", "RWB"} if side == "left" else {"CB", "LCB", "RCB"}
    return UNIT_POSITIONS.get("midfield", set())


def _comparison_block(target, opponents, codes, title, language, key_metrics):
    selected = [row for row in opponents if _position(row) in codes]
    if not selected:
        return None
    counterpart = _aggregate_rows(selected)
    metrics = []
    for name in key_metrics[:5]:
        mode = _metric_mode(name)
        target_value = _metric_value(target, name, mode)
        opponent_value = _metric_value(counterpart, name, mode)
        if target_value is None and opponent_value is None:
            continue
        metrics.append(
            {
                "metric": name,
                "label": METRIC_LABELS.get(language, {}).get(name, name),
                "target": target_value,
                "target_display": _format_metric(target_value, mode),
                "opponent": opponent_value,
                "opponent_display": _format_metric(opponent_value, mode),
                "lower_is_better": name in {"Lost balls", "Lost balls in own half"},
            }
        )
    return {
        "title": title,
        "players": [str(row.get("Player") or "") for row in selected],
        "positions": [str(row.get("Position") or "") for row in selected],
        "minutes": round(_minutes(counterpart)),
        "metrics": metrics,
    }


def _unit_comparisons(rows, teams, language):
    copy = TEXT[language]
    comparisons = []
    for unit, positions in UNIT_POSITIONS.items():
        team_rows = {
            team: [
                row for row in rows
                if str(row.get("Team") or "") == team and _position(row) in positions
            ]
            for team in teams
        }
        aggregates = {
            team: _aggregate_rows(items, label=team)
            for team, items in team_rows.items()
        }
        metric_rows = []
        wins = defaultdict(int)
        for name in UNIT_METRICS[unit]:
            mode = _metric_mode(name)
            values = {
                team: _metric_value(aggregates[team], name, mode)
                if aggregates[team]
                else None
                for team in teams
            }
            present = [value for value in values.values() if value is not None]
            if not present:
                continue
            lower_is_better = name in {"Lost balls", "Lost balls in own half"}
            ranked = [
                (team, value) for team, value in values.items() if value is not None
            ]
            if len(ranked) == 2 and ranked[0][1] != ranked[1][1]:
                winner = min(ranked, key=lambda item: item[1])[0] if lower_is_better else max(ranked, key=lambda item: item[1])[0]
                wins[winner] += 1
            metric_rows.append(
                {
                    "metric": name,
                    "label": METRIC_LABELS.get(language, {}).get(name, name),
                    "mode": mode,
                    "values": values,
                    "display": {team: _format_metric(value, mode) for team, value in values.items()},
                    "lower_is_better": lower_is_better,
                }
            )
        if wins:
            winner, won = max(wins.items(), key=lambda item: item[1])
            verdict = copy["unit_edge"].format(
                team=winner,
                won=won,
                total=len(metric_rows),
            )
        else:
            verdict = copy["unit_even"]
        comparisons.append(
            {
                "key": unit,
                "label": copy["units"][unit],
                "teams": list(teams),
                "player_counts": {team: len(team_rows[team]) for team in teams},
                "metrics": metric_rows,
                "verdict": verdict,
            }
        )
    return comparisons


def _player_card(row, target_population, group, language):
    dimensions = _role_dimensions(row, target_population, group, language)
    score = round(sum(item["score"] for item in dimensions) / len(dimensions)) if dimensions else None
    return {
        "name": str(row.get("Player") or ""),
        "team": str(row.get("Team") or ""),
        "position": _position(row),
        "minutes": round(_minutes(row)),
        "index": _number(row.get("Index")),
        "profile_score": score,
    }


def _narrative(target, dimensions, confidence, language):
    group = _group(target)
    name = str(target.get("Player") or "")
    minutes = round(_minutes(target))
    position = _position(target)
    copy = TEXT[language]
    role = copy["roles"][group]
    summary = copy["sample_summary"].format(
        player=name,
        minutes=minutes,
        position=position,
        role=role,
        confidence=confidence["label"],
    )
    if dimensions:
        best = max(dimensions, key=lambda item: item["score"])
        weak = min(dimensions, key=lambda item: item["score"])
        summary += " " + copy["relative_profile"].format(
            best=best["label"], weak=weak["label"]
        )
    else:
        summary += " " + copy["no_relative_profile"]

    passes = _number(target.get("Passes"), missing_zero=True)
    pass_rate = _rate(target.get("Passes accurate, %"))
    actions = _number(target.get("Actions"), missing_zero=True)
    action_rate = _rate(target.get("Actions successful, %"))
    losses = _number(target.get("Lost balls"), missing_zero=True)
    strengths, risks, development = [], [], []

    if language == "en":
        if pass_rate is not None and passes >= 5 and pass_rate >= 75:
            strengths.append(f"Reliable circulation: {passes:.0f} passes at {pass_rate:.0f}% accuracy.")
        if action_rate is not None and actions >= 8 and action_rate >= 70:
            strengths.append(f"Positive overall execution: {action_rate:.0f}% successful actions.")
        if pass_rate is not None and passes >= 4 and pass_rate < 65:
            risks.append(f"Connection quality was fragile ({pass_rate:.0f}% from {passes:.0f} passes).")
        if losses >= 3:
            risks.append(f"{losses:.0f} ball losses reduced continuity after receiving.")
    elif language == "ar":
        if pass_rate is not None and passes >= 5 and pass_rate >= 75:
            strengths.append(f"تدوير موثوق للكرة: {passes:.0f} تمريرات بدقة {pass_rate:.0f}٪.")
        if action_rate is not None and actions >= 8 and action_rate >= 70:
            strengths.append(f"تنفيذ عام إيجابي بنسبة نجاح {action_rate:.0f}٪.")
        if pass_rate is not None and passes >= 4 and pass_rate < 65:
            risks.append(f"جودة الربط كانت محدودة: دقة {pass_rate:.0f}٪ من {passes:.0f} تمريرات.")
        if losses >= 3:
            risks.append(f"فقدان الكرة {losses:.0f} مرات حد من استمرارية اللعب.")
    else:
        if pass_rate is not None and passes >= 5 and pass_rate >= 75:
            strengths.append(f"Circulation fiable : {passes:.0f} passes à {pass_rate:.0f} % de réussite.")
        if action_rate is not None and actions >= 8 and action_rate >= 70:
            strengths.append(f"Exécution globale positive : {action_rate:.0f} % d’actions réussies.")
        if pass_rate is not None and passes >= 4 and pass_rate < 65:
            risks.append(f"Qualité de connexion fragile ({pass_rate:.0f} % sur {passes:.0f} passes).")
        if losses >= 3:
            risks.append(f"{losses:.0f} pertes de balle ont limité la continuité après réception.")

    if group == "goalkeeper":
        if language == "en":
            risks.append(
                "This export contains no save or post-shot data, so shot-stopping cannot be assessed from the XLSX alone."
            )
            development.extend((
                "Scan both pressure and the next line before receiving a back-pass.",
                "Vary short build-up and long distribution according to the opponent's pressing structure.",
                "Validate starting position, depth and space coverage behind the back line through video.",
            ))
        elif language == "ar":
            risks.append(
                "لا يتضمن هذا الملف بيانات التصديات أو ما بعد التسديدة، لذلك لا يمكن تقييم إيقاف التسديدات من ملف XLSX وحده."
            )
            development.extend((
                "مسح الضغط والخط التالي قبل استلام التمريرة الخلفية.",
                "التنويع بين البناء القصير والتوزيع الطويل حسب بنية ضغط المنافس.",
                "تأكيد وضعية البداية والعمق وتغطية المساحة خلف خط الدفاع بالفيديو.",
            ))
        else:
            risks.append(
                "L’export ne contient ni arrêts ni données post-tir : le shot-stopping ne peut pas être évalué avec le XLSX seul."
            )
            development.extend((
                "Scanner simultanément la pression et la ligne suivante avant de recevoir une passe en retrait.",
                "Alterner relance courte et distribution longue selon la structure du pressing adverse.",
                "Valider en vidéo la position de départ, la profondeur et la couverture derrière la ligne défensive.",
            ))
    elif group == "forward":
        shots = _number(target.get("Shots"), missing_zero=True)
        box_actions = _number(target.get("Actions in opponent's box"), missing_zero=True)
        attacking_duels = _number(target.get("Attacking challenges"), missing_zero=True)
        attacking_rate = _rate(target.get("Attacking challenges won, %"))
        if language == "en":
            if box_actions >= 2:
                strengths.append(f"Reached the scoring zone with {box_actions:.0f} actions inside the opposition box.")
            if shots == 0:
                risks.append("Box presence did not turn into a shot or measurable finishing threat.")
            if attacking_duels and attacking_rate is not None and attacking_rate < 45:
                risks.append(f"Direct-play retention was limited ({attacking_rate:.0f}% attacking duels won).")
            development.extend((
                "Scan before receiving and orient the first touch away from pressure.",
                "Connect drop-support, lay-off and immediate box attack in the same sequence.",
                "Improve contact preparation and body leverage when securing direct passes.",
            ))
        elif language == "ar":
            if box_actions >= 2:
                strengths.append(f"وصل إلى منطقة التسجيل عبر {box_actions:.0f} إجراءات داخل منطقة المنافس.")
            if shots == 0:
                risks.append("الحضور داخل المنطقة لم يتحول إلى تسديدة أو خطورة تهديفية قابلة للقياس.")
            if attacking_duels and attacking_rate is not None and attacking_rate < 45:
                risks.append(f"تثبيت الكرات المباشرة كان محدودا بنسبة {attacking_rate:.0f}٪ في الثنائيات الهجومية.")
            development.extend((
                "رفع جودة المسح قبل الاستلام وتوجيه اللمسة الأولى بعيدا عن الضغط.",
                "ربط النزول للاستلام والتمرير من لمسة ثم مهاجمة المنطقة مباشرة.",
                "تطوير وضعية الجسم واستعمال القوة لتثبيت الكرات المباشرة.",
            ))
        else:
            if box_actions >= 2:
                strengths.append(f"Accès à la zone de finition avec {box_actions:.0f} actions dans la surface adverse.")
            if shots == 0:
                risks.append("La présence dans la surface ne s’est pas transformée en tir ni en menace de finition mesurable.")
            if attacking_duels and attacking_rate is not None and attacking_rate < 45:
                risks.append(f"Fixation des ballons directs limitée ({attacking_rate:.0f} % de duels offensifs gagnés).")
            development.extend((
                "Scanner avant la réception et orienter la première touche hors pression.",
                "Enchaîner décrochage, remise et attaque immédiate de la surface.",
                "Améliorer la préparation du contact et les appuis pour sécuriser le jeu direct.",
            ))
    elif group == "wide_defender":
        box_passes = _number(target.get("Passes into the penalty box"), missing_zero=True)
        box_rate = _rate(target.get("Passes into the penalty box accurate, %"))
        defensive_duels = _number(target.get("Defensive challenges"), missing_zero=True)
        defensive_rate = _rate(target.get("Defensive challenges won, %"))
        interceptions = _number(target.get("Interceptions"), missing_zero=True)
        crosses = _number(target.get("Crosses"), missing_zero=True)
        if language == "en":
            if box_passes and box_rate is not None and box_rate >= 70:
                strengths.append(f"Produced {box_passes:.0f} accurate pass into the penalty area.")
            if defensive_duels and defensive_rate is not None and defensive_rate >= 60:
                strengths.append(f"Won {defensive_rate:.0f}% of defensive duels, albeit on a small volume.")
            if interceptions:
                strengths.append(f"Added {interceptions:.0f} interception through anticipation.")
            if crosses == 0:
                risks.append("No crossing action was recorded, limiting evidence of final-third delivery.")
            development.extend((
                "Receive open to the pitch and accelerate the next progressive action.",
                "Coordinate overlap timing with the inside player before delivering early or cut-back crosses.",
                "Maintain a side-on stance to defend forward while protecting the space behind.",
            ))
        elif language == "ar":
            if box_passes and box_rate is not None and box_rate >= 70:
                strengths.append(f"قدم {box_passes:.0f} تمريرة ناجحة داخل منطقة الجزاء.")
            if defensive_duels and defensive_rate is not None and defensive_rate >= 60:
                strengths.append(f"فاز بنسبة {defensive_rate:.0f}٪ من الثنائيات الدفاعية رغم صغر الحجم.")
            if interceptions:
                strengths.append(f"أضاف {interceptions:.0f} اعتراض بفضل التوقع.")
            if crosses == 0:
                risks.append("لم تسجل أي عرضية، لذلك لا توجد أدلة كافية على جودة الإرسال في الثلث الأخير.")
            development.extend((
                "الاستلام بوضعية مفتوحة وتسريع الإجراء التقدمي التالي.",
                "تنسيق توقيت التداخل مع اللاعب الداخلي قبل العرضية المبكرة أو الخلفية.",
                "الحفاظ على وضعية جانبية للدفاع للأمام مع حماية المساحة في الخلف.",
            ))
        else:
            if box_passes and box_rate is not None and box_rate >= 70:
                strengths.append(f"Une passe réussie dans la surface adverse ({box_passes:.0f} tentative).")
            if defensive_duels and defensive_rate is not None and defensive_rate >= 60:
                strengths.append(f"{defensive_rate:.0f} % de duels défensifs gagnés, sur un faible volume.")
            if interceptions:
                strengths.append(f"{interceptions:.0f} interception obtenue grâce à l’anticipation.")
            if crosses == 0:
                risks.append("Aucun centre enregistré : la qualité de livraison dans le dernier tiers reste à observer.")
            development.extend((
                "Recevoir ouvert vers le jeu et accélérer l’action progressive suivante.",
                "Coordonner le timing du dédoublement avec le joueur intérieur avant le centre précoce ou en retrait.",
                "Conserver une posture de trois-quarts pour défendre vers l’avant sans exposer l’espace dans le dos.",
            ))
    else:
        if language == "en":
            development.extend((
                "Improve scanning before receiving to reduce decision time.",
                "Connect the next progressive action immediately after ball recovery.",
                "Review spacing and body orientation with the unit on video.",
            ))
        elif language == "ar":
            development.extend((
                "تحسين المسح قبل الاستلام لتقليص زمن القرار.",
                "ربط استرجاع الكرة مباشرة بالفعل التقدمي التالي.",
                "مراجعة المسافات ووضعية الجسم مع الخط بالفيديو.",
            ))
        else:
            development.extend((
                "Améliorer la prise d’information avant réception pour réduire le temps de décision.",
                "Enchaîner immédiatement l’action progressive après récupération.",
                "Revoir en vidéo les distances et l’orientation du corps avec le compartiment.",
            ))

    return {
        "executive_summary": summary,
        "strengths": strengths or [copy["strength_fallback"]],
        "risks": risks or [copy["risk_fallback"]],
        "development": development,
        "sample_caution": copy["sample_caution"],
    }


def analyse_match_dataset(rows, player_name, language="fr"):
    """Build a complete, JSON-safe analysis for one player and one match."""
    language = language if language in TEXT else "fr"
    rows = [dict(row) for row in rows if isinstance(row, dict)]
    target = next(
        (row for row in rows if _plain(row.get("Player")) == _plain(player_name)),
        None,
    )
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
    teams = [team for team in (target_team, opponent_team) if team]
    group = _group(target)
    population = [row for row in rows if _group(row) == group and _minutes(row) > 0]
    if len(population) < 3:
        target_unit = next(
            (positions for positions in UNIT_POSITIONS.values() if _position(target) in positions),
            set(),
        )
        population = [row for row in rows if _position(row) in target_unit and _minutes(row) > 0]

    dimensions = _role_dimensions(target, population, group, language)
    confidence = _confidence(_minutes(target), language)
    key_metrics = []
    for name in KEY_METRICS.get(group, KEY_METRICS["central_midfielder"]):
        mode = _metric_mode(name)
        value = _metric_value(target, name, mode)
        percentile = _percentile(
            value,
            [_metric_value(row, name, mode) for row in population],
            -1 if name in {"Lost balls", "Lost balls in own half"} else 1,
        )
        key_metrics.append(
            {
                "metric": name,
                "label": METRIC_LABELS.get(language, {}).get(name, name),
                "value": value,
                "display": _format_metric(value, mode),
                "percentile": percentile,
                "mode": mode,
            }
        )

    same_team_peers = [
        row for row in population
        if str(row.get("Team") or "") == target_team
        and _plain(row.get("Player")) != _plain(player_name)
    ]
    peer_cards = [
        _player_card(row, population, group, language) for row in same_team_peers
    ]
    peer_cards.sort(
        key=lambda item: (
            item["profile_score"] is not None,
            item["profile_score"] or -1,
            item["minutes"],
        ),
        reverse=True,
    )

    opponents = [row for row in rows if str(row.get("Team") or "") == opponent_team]
    position = _position(target)
    copy = TEXT[language]
    matchups = [
        _comparison_block(
            target,
            opponents,
            _same_role_codes(position),
            copy["homologue"],
            language,
            KEY_METRICS.get(group, ()),
        ),
        _comparison_block(
            target,
            opponents,
            _direct_codes(position, group),
            copy["direct_channel"],
            language,
            KEY_METRICS.get(group, ()),
        ),
    ]

    narrative = _narrative(target, dimensions, confidence, language)
    profile_score = (
        round(sum(item["score"] for item in dimensions) / len(dimensions))
        if dimensions
        else None
    )
    return {
        "version": ANALYSIS_VERSION,
        "available": True,
        "language": language,
        "player": {
            "name": str(target.get("Player") or player_name),
            "team": target_team,
            "opponent": opponent_team,
            "position": position,
            "role_group": group,
            "role_label": copy["roles"][group],
            "minutes": round(_minutes(target)),
            "index": _number(target.get("Index")),
            "profile_score": profile_score,
        },
        "confidence": confidence,
        "dimensions": dimensions,
        "key_metrics": key_metrics,
        "same_compartment": peer_cards[:6],
        "matchups": [item for item in matchups if item],
        "unit_comparisons": _unit_comparisons(rows, teams, language),
        "narrative": narrative,
        "population": {
            "role_group": group,
            "players": len(population),
            "description": (
                "Players in the same role family from both teams, normalised per 90 "
                "minutes for volume metrics."
            ),
        },
        "methodology": {
            "rate_aggregation": "weighted_by_attempts",
            "volume_normalisation": "per_90",
            "comparison_scales": ["player", "unit", "team"],
            "event_data_limit": (
                "Off-ball movements, tactical instructions and pressing intention "
                "require video confirmation."
            ),
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
    return analyse_match_dataset(
        rows,
        getattr(match.subscription.player, "name", ""),
        language=language,
    )
