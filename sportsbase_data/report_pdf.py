"""Professional multilingual PDF renderer for SportsBase performance reports."""

import io
import math
import re
from html import escape
from pathlib import Path
from urllib.parse import urlparse


PDF_COPY = {
    "fr": {
        "brand": "ANALYSE DE PERFORMANCE",
        "role": "PROFIL DE POSTE",
        "position_map": "POSITION(S) JOUÉE(S)",
        "primary_position": "Poste principal",
        "secondary_position": "Poste secondaire",
        "minutes": "MINUTES",
        "reliability": "FIABILITÉ",
        "index": "INDEX SPORTSBASE",
        "mission_score": "SCORE DE MISSION",
        "verdict": "Verdict de l’analyste",
        "decisive_facts": "Faits décisifs de la rencontre",
        "rankings": "Repères dans le match",
        "index_team": "Rang Index — équipe",
        "index_match": "Rang Index — match",
        "index_position": "Rang Index — poste homologue",
        "index_note": "L’Index SportsBase et son rang sont toujours lus avec les missions du poste. Une 1re place dans l’équipe ou le match constitue un signal fort dans le verdict final.",
        "role_missions": "Missions du poste",
        "mission_note": "Chaque score juge uniquement cette apparition. Les missions et critères sont classés selon leur importance pour le poste.",
        "score_explained": "Comment le score de mission est calculé",
        "configured_weight": "POIDS POSTE",
        "effective_weight": "POIDS EFFECTIF",
        "criterion": "CRITÈRE",
        "criterion_score": "NOTE CRITÈRE",
        "contribution": "POINTS DANS LE SCORE",
        "weighted_total": "TOTAL PONDÉRÉ",
        "score_reasons": "CRITÈRES QUI EXPLIQUENT LA NOTE",
        "score_total_note": "Total pondéré avant arrondi : {raw} points. Score de mission final : {score}/100.",
        "impact_drivers": "Pourquoi les actions décisives comptent dans la note",
        "impact_note": "Chaque ligne ci-dessous appartient au calcul : elle n’est pas ajoutée après le verdict.",
        "position_benchmark": "Profil saisonnier face à la moyenne du poste",
        "benchmark_position": "Référence retenue : {position} ({percent} % du profil SportsBase) · saison {season}",
        "benchmark_match": "Joueur — valeur réelle /90",
        "benchmark_average": "Moyenne du poste /90",
        "benchmark_raw": "Échelle de l’axe",
        "benchmark_difference": "ÉCART",
        "not_assessed": "Non évalué",
        "coverage": "données observées",
        "key_metrics": "Indicateurs clés du poste",
        "performance_reading": "Lecture du match par phase",
        "performance_note": "Une seule lecture, sans doublon : implication globale, contribution offensive puis contribution défensive. Les définitions sont placées directement sous les KPI utiles.",
        "raw_note": "Totaux réels du match, sans projection sur 90 minutes. Un taux est toujours présenté avec son dénominateur.",
        "indicator": "INDICATEUR",
        "real_value": "VALEUR RÉELLE",
        "sample": "ÉCHANTILLON",
        "reading": "LECTURE",
        "glossary": "Comprendre les KPI",
        "meaning": "CE QUE CELA SIGNIFIE",
        "maps": "Empreinte terrain",
        "heatmap": "Carte de chaleur",
        "touches": "Carte des contacts ballon",
        "heat_note": "La heatmap décrit les zones d’activité enregistrées. Elle ne remplace pas un suivi GPS complet des courses sans ballon.",
        "touch_note": "La carte des contacts montre où le joueur a réellement touché le ballon. La présence territoriale doit être associée à la qualité des actions.",
        "thirds": "Répartition sur les tiers affichés",
        "lanes": "Répartition par couloir",
        "left": "Gauche affichée",
        "middle": "Milieu",
        "right": "Droite affichée",
        "wide": "Largeur",
        "half_space": "Demi-espaces",
        "central": "Axe",
        "strengths": "Ce qui a été bien fait",
        "risks": "Points à améliorer",
        "development": "Plan d’action individuel",
        "video_check": "À confirmer avec la vidéo All Actions",
        "comparisons": "Repères individuels — comparaison secondaire",
        "comparison_note": "Aucune analyse collective ou par compartiment n’est réalisée. La comparaison directe concerne uniquement l’homologue adverse au même poste ou à son équivalent strict dans une autre organisation.",
        "player": "JOUEUR",
        "position": "POSTE",
        "profile": "MISSION",
        "matchups": "Homologue adverse au poste équivalent",
        "global_leaders": "Meilleures performances individuelles des deux équipes",
        "global_note": "Pour les pourcentages de réussite, le classement exige au moins 3 tentatives. Le nombre de réussites et le dénominateur restent visibles.",
        "match_leader": "MEILLEUR DES DEUX ÉQUIPES",
        "target_rank": "RANG DU JOUEUR",
        "target": "JOUEUR",
        "opponent": "ADVERSAIRE",
        "not_comparable": "* volume non comparable : temps de jeu trop différents",
        "appendix": "Toutes les données SportsBase",
        "full_data_note": "Toutes les colonnes du fichier Players XLSX sont présentées. Une action absente apparaît à 0 ; un pourcentage sans tentative reste non évalué afin de ne pas inventer un taux de réussite.",
        "role_kpi": "KPI PRIORITAIRE DU POSTE",
        "decisive_kpi": "DONNÉE DÉCISIVE",
        "columns_presented": "{count} colonnes SportsBase présentées",
        "method": "Méthodologie et limites",
        "method_text": "Le moteur analyse uniquement le joueur et les missions de son poste. Il conserve les totaux réels, adapte la lecture aux entrées courtes, réduit le poids des faibles échantillons et considère qu’une absence d’occasion n’est pas une faiblesse. Il ne produit aucune analyse collective ni conclusion liée au résultat du match.",
        "source": "Références méthodologiques",
        "prepared": "Préparé par l’équipe d’analyse MS Performance",
        "page": "Page",
        "unavailable": "Les données complètes du fichier Players XLSX ne sont pas disponibles pour ce match.",
        "no_data": "Aucune donnée exploitable.",
        "no_comparison": "Aucun joueur comparable n’est disponible sur cette rencontre.",
    },
    "en": {
        "brand": "PERFORMANCE ANALYSIS",
        "role": "POSITION PROFILE",
        "position_map": "PLAYED POSITION(S)",
        "primary_position": "Primary position",
        "secondary_position": "Secondary position",
        "minutes": "MINUTES",
        "reliability": "RELIABILITY",
        "index": "SPORTSBASE INDEX",
        "mission_score": "MISSION SCORE",
        "verdict": "Analyst verdict",
        "decisive_facts": "Decisive match facts",
        "rankings": "Match reference points",
        "index_team": "Index rank — team",
        "index_match": "Index rank — match",
        "index_position": "Index rank — counterpart position",
        "index_note": "SportsBase Index and rank are always read alongside position missions. Ranking first in the team or match is a strong signal in the final verdict.",
        "role_missions": "Position missions",
        "mission_note": "Each score assesses this appearance only. Missions and criteria are ordered by importance for the position.",
        "score_explained": "How the mission score is calculated",
        "configured_weight": "POSITION WEIGHT",
        "effective_weight": "EFFECTIVE WEIGHT",
        "criterion": "CRITERION",
        "criterion_score": "CRITERION SCORE",
        "contribution": "POINTS IN FINAL SCORE",
        "weighted_total": "WEIGHTED TOTAL",
        "score_reasons": "CRITERIA BEHIND THE SCORE",
        "score_total_note": "Weighted total before rounding: {raw} points. Final mission score: {score}/100.",
        "impact_drivers": "Why decisive actions count in the score",
        "impact_note": "Every line below belongs to the calculation; it is not added after the verdict.",
        "position_benchmark": "Season profile against the position average",
        "benchmark_position": "Selected reference: {position} ({percent}% of the SportsBase profile) · season {season}",
        "benchmark_match": "Player — real value /90",
        "benchmark_average": "Position average /90",
        "benchmark_raw": "Axis scale",
        "benchmark_difference": "GAP",
        "not_assessed": "Not assessed",
        "coverage": "observed data",
        "key_metrics": "Position-specific key indicators",
        "performance_reading": "Match reading by phase",
        "performance_note": "One non-redundant reading: overall involvement, attacking contribution, then defensive contribution. Definitions sit directly below the useful KPIs.",
        "raw_note": "Real match totals, with no 90-minute projection. Every rate is shown with its denominator.",
        "indicator": "INDICATOR",
        "real_value": "REAL VALUE",
        "sample": "SAMPLE",
        "reading": "READING",
        "glossary": "Understanding the KPIs",
        "meaning": "WHAT IT MEANS",
        "maps": "Pitch footprint",
        "heatmap": "Heatmap",
        "touches": "Ball-touch map",
        "heat_note": "The heatmap describes recorded activity zones; it is not a complete GPS record of off-ball running.",
        "touch_note": "The touch map shows where the player actually contacted the ball. Territorial presence must be paired with action quality.",
        "thirds": "Distribution across displayed thirds",
        "lanes": "Distribution by lane",
        "left": "Displayed left",
        "middle": "Middle",
        "right": "Displayed right",
        "wide": "Wide lanes",
        "half_space": "Half-spaces",
        "central": "Central lane",
        "strengths": "What was done well",
        "risks": "Points to improve",
        "development": "Individual action plan",
        "video_check": "To confirm through All Actions video",
        "comparisons": "Individual reference points — secondary comparison",
        "comparison_note": "No collective or unit analysis is produced. The direct comparison uses only the opposition player in the same position or its strict equivalent in another shape.",
        "player": "PLAYER",
        "position": "POSITION",
        "profile": "MISSION",
        "matchups": "Opposition counterpart in the equivalent position",
        "global_leaders": "Best individual performances across both teams",
        "global_note": "Success-rate rankings require at least 3 attempts. Successes and denominators remain visible.",
        "match_leader": "BEST ACROSS BOTH TEAMS",
        "target_rank": "PLAYER RANK",
        "target": "PLAYER",
        "opponent": "OPPONENT",
        "not_comparable": "* non-comparable volume: playing times differ too much",
        "appendix": "All SportsBase data",
        "full_data_note": "Every column in the Players XLSX is presented. An absent event appears as 0; a percentage with no attempt remains not assessed so no success rate is invented.",
        "role_kpi": "POSITION-PRIORITY KPI",
        "decisive_kpi": "DECISIVE DATA",
        "columns_presented": "{count} SportsBase columns presented",
        "method": "Methodology and limitations",
        "method_text": "The engine analyses only the player and the missions of the position. It keeps real totals, adapts the reading to short appearances, reduces the weight of small samples and treats no opportunity as no weakness. It produces no collective analysis or match-result conclusion.",
        "source": "Methodology references",
        "prepared": "Prepared by the MS Performance analysis team",
        "page": "Page",
        "unavailable": "The full Players XLSX dataset is unavailable for this match.",
        "no_data": "No usable data.",
        "no_comparison": "No comparable player is available in this match.",
    },
    "ar": {
        "brand": "تحليل الأداء",
        "role": "ملف المركز",
        "position_map": "المراكز التي لعب فيها",
        "primary_position": "المركز الأساسي",
        "secondary_position": "المركز الثاني",
        "minutes": "الدقائق",
        "reliability": "الموثوقية",
        "index": "مؤشر سبورتس بايز",
        "mission_score": "درجة المهمة",
        "verdict": "خلاصة المحلل",
        "decisive_facts": "الوقائع الحاسمة في المباراة",
        "rankings": "الترتيب داخل المباراة",
        "index_team": "ترتيب المؤشر داخل الفريق",
        "index_match": "ترتيب المؤشر داخل المباراة",
        "index_position": "ترتيب المؤشر في نفس المركز",
        "index_note": "يقرأ مؤشر سبورتس بايز وترتيبه دائما مع مهام المركز، وتعد المرتبة الأولى داخل الفريق أو المباراة إشارة قوية في الخلاصة النهائية.",
        "role_missions": "مهام المركز",
        "mission_note": "تخص كل درجة هذه المشاركة فقط وترتب المهام والمعايير حسب أهميتها للمركز.",
        "score_explained": "كيفية حساب درجة المهمة",
        "configured_weight": "وزن المهمة",
        "effective_weight": "الوزن الفعلي",
        "criterion": "المعيار",
        "criterion_score": "درجة المعيار",
        "contribution": "النقاط في الدرجة النهائية",
        "weighted_total": "المجموع الموزون",
        "score_reasons": "المعايير التي تفسر الدرجة",
        "score_total_note": "المجموع الموزون قبل التقريب: {raw} نقطة. درجة المهمة النهائية: {score}/100.",
        "impact_drivers": "لماذا تدخل الأفعال الحاسمة في الدرجة",
        "impact_note": "كل سطر أدناه جزء من الحساب ولا يضاف بعد الخلاصة.",
        "position_benchmark": "الملف الموسمي مقارنة بمتوسط المركز",
        "benchmark_position": "المرجع المختار: {position} ({percent}% من ملف سبورتس بايز) · موسم {season}",
        "benchmark_match": "اللاعب — القيمة الحقيقية لكل 90",
        "benchmark_average": "متوسط المركز لكل 90",
        "benchmark_raw": "مقياس المحور",
        "benchmark_difference": "الفارق",
        "not_assessed": "غير مقيم",
        "coverage": "بيانات ملاحظة",
        "key_metrics": "المؤشرات الرئيسية للمركز",
        "performance_reading": "قراءة المباراة حسب مراحل اللعب",
        "performance_note": "قراءة واحدة دون تكرار: المشاركة العامة ثم المساهمة الهجومية فالدفاعية، مع شرح المؤشرات مباشرة.",
        "raw_note": "الأرقام الحقيقية للمباراة دون تحويل إلى 90 دقيقة، وكل نسبة تعرض مع عدد المحاولات.",
        "indicator": "المؤشر",
        "real_value": "القيمة الحقيقية",
        "sample": "العينة",
        "reading": "القراءة",
        "glossary": "فهم المؤشرات",
        "meaning": "المعنى",
        "maps": "البصمة داخل الملعب",
        "heatmap": "الخريطة الحرارية",
        "touches": "خريطة لمس الكرة",
        "heat_note": "تصف الخريطة الحرارية مناطق النشاط المسجلة ولا تعوض تتبع GPS الكامل.",
        "touch_note": "توضح خريطة اللمسات أين لمس اللاعب الكرة فعليا ويجب ربط الحضور بجودة الإجراء.",
        "thirds": "التوزيع على الأثلاث المعروضة",
        "lanes": "التوزيع حسب الرواق",
        "left": "اليسار المعروض",
        "middle": "الوسط",
        "right": "اليمين المعروض",
        "wide": "الأطراف",
        "half_space": "أنصاف المساحات",
        "central": "العمق",
        "strengths": "ما تم إنجازه جيدا",
        "risks": "نقاط التحسين",
        "development": "خطة العمل الفردية",
        "video_check": "يجب تأكيده بفيديو جميع اللقطات",
        "comparisons": "مراجع فردية — مقارنة ثانوية",
        "comparison_note": "لا يوجد تحليل جماعي أو حسب الخطوط، والمقارنة المباشرة تخص لاعب الخصم في نفس المركز أو ما يعادله مباشرة في تنظيم مختلف.",
        "player": "اللاعب",
        "position": "المركز",
        "profile": "المهمة",
        "matchups": "لاعب الخصم في المركز المعادل",
        "global_leaders": "أفضل الأداءات الفردية في الفريقين",
        "global_note": "يتطلب ترتيب نسب النجاح ثلاث محاولات على الأقل مع إظهار عدد النجاحات والمحاولات.",
        "match_leader": "الأفضل في الفريقين",
        "target_rank": "ترتيب اللاعب",
        "target": "اللاعب",
        "opponent": "المنافس",
        "not_comparable": "* حجم غير قابل للمقارنة بسبب اختلاف دقائق اللعب",
        "appendix": "جميع بيانات سبورتس بايز",
        "full_data_note": "تعرض جميع أعمدة ملف Players XLSX. يظهر الحدث غير المسجل بقيمة صفر، بينما تبقى النسبة دون محاولة غير مقيمة حتى لا يتم اختراع نسبة نجاح.",
        "role_kpi": "مؤشر أساسي للمركز",
        "decisive_kpi": "بيان حاسم",
        "columns_presented": "تم عرض {count} عمودا من سبورتس بايز",
        "method": "المنهجية والحدود",
        "method_text": "يحلل المحرك اللاعب ومهام مركزه فقط، ويحافظ على الأرقام الحقيقية ويتكيف مع المشاركات القصيرة ويخفض وزن العينات الصغيرة ولا يعتبر غياب الفرصة نقطة ضعف. لا ينتج تحليلا جماعيا ولا استنتاجا مرتبطا بنتيجة المباراة.",
        "source": "المراجع المنهجية",
        "prepared": "إعداد فريق تحليل MS Performance",
        "page": "صفحة",
        "unavailable": "بيانات ملف Players XLSX الكاملة غير متاحة لهذه المباراة.",
        "no_data": "لا توجد بيانات قابلة للاستعمال.",
        "no_comparison": "لا يوجد لاعب قابل للمقارنة في هذه المباراة.",
    },
}


NAVY = "#071827"
INK = "#203149"
MUTED = "#69788E"
TEAL = "#13B8A6"
TEAL_DARK = "#0D9488"
CYAN = "#43D9C7"
PALE = "#EDF7F6"
LINE = "#D8E3EA"
RED = "#D95D66"
AMBER = "#D6A63C"
GREEN = "#2EA66F"
LIGHT_RED = "#FFF0F1"
LIGHT_AMBER = "#FFF7E6"
LIGHT_GREEN = "#ECF8F2"
LIGHT_GREY = "#F4F7F9"
GOLD = "#F2B84B"
SOFT_BLUE = "#EAF3FA"


PITCH_POSITION_COORDS = {
    "GK": (0.50, 0.08),
    "LB": (0.15, 0.23), "LCB": (0.35, 0.23), "CB": (0.50, 0.23),
    "RCB": (0.65, 0.23), "RB": (0.85, 0.23),
    "LWB": (0.10, 0.39), "RWB": (0.90, 0.39),
    "LDM": (0.35, 0.40), "CDM": (0.50, 0.40), "DM": (0.50, 0.40),
    "RDM": (0.65, 0.40),
    "LM": (0.12, 0.56), "LCM": (0.35, 0.52), "CM": (0.50, 0.52),
    "RCM": (0.65, 0.52), "RM": (0.88, 0.56),
    "LAM": (0.28, 0.67), "CAM": (0.50, 0.67), "AM": (0.50, 0.67),
    "RAM": (0.72, 0.67),
    "LW": (0.13, 0.80), "RW": (0.87, 0.80), "SS": (0.50, 0.78),
    "LCF": (0.35, 0.88), "CF": (0.50, 0.88), "ST": (0.50, 0.90),
    "RCF": (0.65, 0.88),
    "DF": (0.50, 0.23), "MF": (0.50, 0.52), "FW": (0.50, 0.88),
}


def _font_path():
    candidates = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    )
    return next((path for path in candidates if path.is_file()), None)


def _rtl(value):
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(str(value)))
    except ImportError:
        return str(value)


def render_performance_pdf(report):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        Flowable,
        Image,
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    language = getattr(report, "language", "fr")
    language = language if language in PDF_COPY else "fr"
    copy = PDF_COPY[language]
    rtl = language == "ar"
    align = TA_RIGHT if rtl else TA_LEFT
    font_name = "Helvetica"
    font_path = _font_path()
    if font_path:
        font_name = "MSPerformanceUnicode"
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, str(font_path)))

    def display(value):
        value = str(value or "")
        return _rtl(value) if rtl else value

    def markup(value):
        return "<br/>".join(escape(display(line)) for line in str(value or "").splitlines())

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "MSPTitle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=25,
        leading=31,
        textColor=colors.white,
        alignment=align,
        spaceAfter=5 * mm,
    )
    cover_kicker = ParagraphStyle(
        "MSPKicker",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=9,
        leading=12,
        tracking=1.2,
        textColor=colors.HexColor(CYAN),
        alignment=align,
    )
    cover_meta = ParagraphStyle(
        "MSPCoverMeta",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=10,
        leading=15,
        textColor=colors.white,
        alignment=align,
    )
    h1 = ParagraphStyle(
        "MSPH1",
        parent=styles["Heading1"],
        fontName=font_name,
        fontSize=15,
        leading=19,
        textColor=colors.HexColor(NAVY),
        alignment=align,
        spaceBefore=1 * mm,
        spaceAfter=4 * mm,
    )
    h2 = ParagraphStyle(
        "MSPH2",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=9.5,
        leading=12,
        textColor=colors.HexColor(TEAL_DARK),
        alignment=align,
        spaceAfter=2 * mm,
    )
    body = ParagraphStyle(
        "MSPBody",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=8.2,
        leading=12.2,
        textColor=colors.HexColor(INK),
        alignment=align,
    )
    body_bold = ParagraphStyle(
        "MSPBodyBold",
        parent=body,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor(NAVY),
    )
    small = ParagraphStyle(
        "MSPSmall",
        parent=body,
        fontSize=7,
        leading=9.5,
        textColor=colors.HexColor(MUTED),
    )
    tiny = ParagraphStyle(
        "MSPTiny",
        parent=small,
        fontSize=6.2,
        leading=8,
    )
    table_head = ParagraphStyle(
        "MSPTableHead",
        parent=small,
        fontSize=6.5,
        leading=8,
        textColor=colors.white,
        alignment=align,
    )
    card_label = ParagraphStyle(
        "MSPCardLabel",
        parent=small,
        fontSize=6.2,
        leading=8,
        alignment=TA_CENTER,
    )
    card_label_left = ParagraphStyle(
        "MSPCardLabelLeft",
        parent=card_label,
        alignment=align,
    )
    card_value = ParagraphStyle(
        "MSPCardValue",
        parent=body_bold,
        fontSize=11.5,
        leading=14,
        alignment=TA_CENTER,
    )
    stamp_label = ParagraphStyle(
        "MSPStampLabel",
        parent=body_bold,
        fontSize=8,
        leading=10,
        alignment=align,
    )

    class RadarProfile(Flowable):
        def __init__(self, dimensions, width=78 * mm, height=72 * mm):
            super().__init__()
            self.dimensions = dimensions[:6]
            self.width = width
            self.height = height

        def draw(self):
            if len(self.dimensions) < 3:
                return
            canvas = self.canv
            count = len(self.dimensions)
            cx, cy = self.width / 2, self.height / 2 + 2 * mm
            radius = min(self.width, self.height) * 0.30
            canvas.saveState()
            for ring in (0.25, 0.5, 0.75, 1.0):
                points = []
                for index in range(count):
                    angle = math.pi / 2 - 2 * math.pi * index / count
                    points.append((cx + radius * ring * math.cos(angle), cy + radius * ring * math.sin(angle)))
                path = canvas.beginPath()
                path.moveTo(*points[0])
                for point in points[1:]:
                    path.lineTo(*point)
                path.close()
                canvas.setStrokeColor(colors.HexColor(LINE))
                canvas.setLineWidth(0.45)
                canvas.drawPath(path, stroke=1, fill=0)
            values = []
            for index, item in enumerate(self.dimensions):
                angle = math.pi / 2 - 2 * math.pi * index / count
                canvas.setStrokeColor(colors.HexColor(LINE))
                canvas.line(cx, cy, cx + radius * math.cos(angle), cy + radius * math.sin(angle))
                score = max(0, min(100, float(item.get("score") or 0))) / 100
                values.append((cx + radius * score * math.cos(angle), cy + radius * score * math.sin(angle)))
                label_radius = radius + 10 * mm
                lx = cx + label_radius * math.cos(angle)
                ly = cy + label_radius * math.sin(angle)
                canvas.setFillColor(colors.HexColor(INK))
                canvas.setFont(font_name, 5.5)
                label = display(item.get("label") or "")
                if math.cos(angle) > 0.25:
                    canvas.drawString(lx, ly, label)
                elif math.cos(angle) < -0.25:
                    canvas.drawRightString(lx, ly, label)
                else:
                    canvas.drawCentredString(lx, ly, label)
            path = canvas.beginPath()
            path.moveTo(*values[0])
            for point in values[1:]:
                path.lineTo(*point)
            path.close()
            canvas.setFillColor(colors.Color(0.075, 0.72, 0.65, alpha=0.25))
            canvas.setStrokeColor(colors.HexColor(TEAL_DARK))
            canvas.setLineWidth(1.4)
            canvas.drawPath(path, stroke=1, fill=1)
            for point in values:
                canvas.setFillColor(colors.HexColor(TEAL_DARK))
                canvas.circle(point[0], point[1], 1.5, stroke=0, fill=1)
            canvas.restoreState()

    class BenchmarkRadar(Flowable):
        """Two-series vector radar using raw values and axis-only normalisation."""

        def __init__(self, metrics, width=164 * mm, height=102 * mm):
            super().__init__()
            self.metrics = [item for item in metrics if item.get("comparable")][:12]
            self.width = width
            self.height = height

        @staticmethod
        def _lines(value, limit=22):
            words = str(value or "").split()
            lines = []
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if current and len(candidate) > limit:
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            if current:
                lines.append(current)
            if len(lines) > 2:
                lines = [lines[0], f"{lines[1][: max(1, limit - 1)]}…"]
            return lines or ["—"]

        def draw(self):
            if len(self.metrics) < 3:
                return
            canvas = self.canv
            count = len(self.metrics)
            cx, cy = self.width / 2, self.height / 2 + 7 * mm
            radius = min(self.width * 0.23, self.height * 0.31)
            canvas.saveState()
            for ring in (0.25, 0.5, 0.75, 1.0):
                points = []
                for index in range(count):
                    angle = math.pi / 2 - 2 * math.pi * index / count
                    points.append((cx + radius * ring * math.cos(angle), cy + radius * ring * math.sin(angle)))
                path = canvas.beginPath()
                path.moveTo(*points[0])
                for point in points[1:]:
                    path.lineTo(*point)
                path.close()
                canvas.setStrokeColor(colors.HexColor(LINE))
                canvas.setLineWidth(0.45)
                canvas.drawPath(path, stroke=1, fill=0)

            series = []
            for index, item in enumerate(self.metrics):
                angle = math.pi / 2 - 2 * math.pi * index / count
                canvas.setStrokeColor(colors.HexColor(LINE))
                canvas.line(cx, cy, cx + radius * math.cos(angle), cy + radius * math.sin(angle))
                average = max(0, min(100, float(item.get("average_normalized") or 0))) / 100
                player = max(0, min(100, float(item.get("player_normalized") or 0))) / 100
                series.append(
                    (
                        (cx + radius * average * math.cos(angle), cy + radius * average * math.sin(angle)),
                        (cx + radius * player * math.cos(angle), cy + radius * player * math.sin(angle)),
                    )
                )
                label_radius = radius + 13 * mm
                lx = cx + label_radius * math.cos(angle)
                ly = cy + label_radius * math.sin(angle)
                lines = self._lines(display(item.get("label") or item.get("metric")))
                canvas.setFillColor(colors.HexColor(INK))
                canvas.setFont(font_name, 4.8)
                for line_index, line in enumerate(lines):
                    line_y = ly - line_index * 5.5
                    if math.cos(angle) > 0.25:
                        canvas.drawString(lx, line_y, line)
                    elif math.cos(angle) < -0.25:
                        canvas.drawRightString(lx, line_y, line)
                    else:
                        canvas.drawCentredString(lx, line_y, line)

            def polygon(point_index, stroke, fill):
                points = [pair[point_index] for pair in series]
                path = canvas.beginPath()
                path.moveTo(*points[0])
                for point in points[1:]:
                    path.lineTo(*point)
                path.close()
                canvas.setStrokeColor(colors.HexColor(stroke))
                canvas.setFillColor(fill)
                canvas.setLineWidth(1.4)
                canvas.drawPath(path, stroke=1, fill=1)
                for point in points:
                    canvas.setFillColor(colors.HexColor(stroke))
                    canvas.circle(point[0], point[1], 1.3, stroke=0, fill=1)

            polygon(0, RED, colors.Color(0.85, 0.36, 0.40, alpha=0.13))
            polygon(1, TEAL_DARK, colors.Color(0.075, 0.72, 0.65, alpha=0.22))

            legend_y = 3 * mm
            canvas.setLineWidth(2)
            canvas.setStrokeColor(colors.HexColor(TEAL_DARK))
            canvas.line(cx - 55 * mm, legend_y, cx - 45 * mm, legend_y)
            canvas.setFillColor(colors.HexColor(INK))
            canvas.setFont(font_name, 6.2)
            canvas.drawString(cx - 42 * mm, legend_y - 2, display(copy["benchmark_match"]))
            canvas.setStrokeColor(colors.HexColor(RED))
            canvas.line(cx + 5 * mm, legend_y, cx + 15 * mm, legend_y)
            canvas.drawString(cx + 18 * mm, legend_y - 2, display(copy["benchmark_average"]))
            canvas.restoreState()

    class PositionPitch(Flowable):
        """Compact vector pitch with one or several match positions."""

        def __init__(self, positions, width=54 * mm, height=72 * mm, dark=False):
            super().__init__()
            self.positions = [str(code).upper() for code in positions if code][:3]
            self.width = width
            self.height = height
            self.dark = dark

        def draw(self):
            canvas = self.canv
            canvas.saveState()
            legend_height = 10 * mm
            x0, y0 = 2 * mm, legend_height
            pitch_width = self.width - 4 * mm
            pitch_height = self.height - legend_height - 2 * mm
            background = "#0B2A39" if self.dark else "#F2FAF8"
            line_color = colors.Color(1, 1, 1, alpha=0.52) if self.dark else colors.HexColor("#9FC8C1")
            canvas.setFillColor(colors.HexColor(background))
            canvas.roundRect(x0, y0, pitch_width, pitch_height, 4 * mm, stroke=0, fill=1)
            canvas.setStrokeColor(line_color)
            canvas.setLineWidth(0.65)
            inset = 3 * mm
            left, bottom = x0 + inset, y0 + inset
            usable_width = pitch_width - 2 * inset
            usable_height = pitch_height - 2 * inset
            canvas.rect(left, bottom, usable_width, usable_height, stroke=1, fill=0)
            canvas.line(left, bottom + usable_height / 2, left + usable_width, bottom + usable_height / 2)
            canvas.circle(left + usable_width / 2, bottom + usable_height / 2, 5 * mm, stroke=1, fill=0)
            canvas.circle(left + usable_width / 2, bottom + usable_height / 2, 0.7 * mm, stroke=0, fill=1)
            box_width, box_height = usable_width * 0.46, usable_height * 0.16
            box_left = left + (usable_width - box_width) / 2
            canvas.rect(box_left, bottom, box_width, box_height, stroke=1, fill=0)
            canvas.rect(box_left, bottom + usable_height - box_height, box_width, box_height, stroke=1, fill=0)
            small_width, small_height = usable_width * 0.23, usable_height * 0.07
            small_left = left + (usable_width - small_width) / 2
            canvas.rect(small_left, bottom, small_width, small_height, stroke=1, fill=0)
            canvas.rect(small_left, bottom + usable_height - small_height, small_width, small_height, stroke=1, fill=0)

            spots = []
            fallback_x = (0.50, 0.40)
            for index, code in enumerate(self.positions):
                nx, ny = PITCH_POSITION_COORDS.get(code, fallback_x)
                spots.append((left + nx * usable_width, bottom + ny * usable_height, code))
            if len(spots) > 1:
                canvas.setStrokeColor(colors.Color(0.95, 0.72, 0.29, alpha=0.75))
                canvas.setLineWidth(1.0)
                canvas.setDash(3, 2)
                path = canvas.beginPath()
                path.moveTo(spots[0][0], spots[0][1])
                for point in spots[1:]:
                    path.lineTo(point[0], point[1])
                canvas.drawPath(path, stroke=1, fill=0)
                canvas.setDash()
            for index, (x, y, code) in enumerate(spots):
                color = CYAN if index == 0 else GOLD
                canvas.setFillColor(colors.Color(0.25, 0.85, 0.78, alpha=0.18) if index == 0 else colors.Color(0.95, 0.72, 0.29, alpha=0.18))
                canvas.circle(x, y, 4.2 * mm, stroke=0, fill=1)
                canvas.setFillColor(colors.HexColor(color))
                canvas.circle(x, y, 2.8 * mm, stroke=0, fill=1)
                canvas.setFillColor(colors.HexColor(NAVY))
                canvas.setFont(font_name, 6.8)
                canvas.drawCentredString(x, y - 2.2, str(index + 1))

            canvas.setFont(font_name, 6.2)
            for index, code in enumerate(self.positions):
                canvas.setFillColor(colors.HexColor(CYAN if index == 0 else GOLD))
                prefix = copy["primary_position"] if index == 0 else copy["secondary_position"]
                label = display(f"{index + 1}  {prefix}: {code}")
                canvas.drawString(2 * mm, (6.5 - index * 3.5) * mm, label)
            canvas.restoreState()

    class ScoreRing(Flowable):
        def __init__(self, score, width=39 * mm, height=39 * mm, tone="neutral"):
            super().__init__()
            self.score = score
            self.width = width
            self.height = height
            self.tone = tone

        def draw(self):
            canvas = self.canv
            accent, _background = tone_colors(self.tone)
            score = None if self.score is None else max(0, min(100, float(self.score)))
            cx, cy = self.width / 2, self.height / 2
            radius = min(self.width, self.height) * 0.36
            canvas.saveState()
            canvas.setStrokeColor(colors.HexColor(LINE))
            canvas.setLineWidth(5.5)
            canvas.circle(cx, cy, radius, stroke=1, fill=0)
            if score is not None:
                canvas.setStrokeColor(colors.HexColor(accent))
                canvas.setLineWidth(5.5)
                canvas.setLineCap(1)
                canvas.arc(cx - radius, cy - radius, cx + radius, cy + radius, 90, -3.6 * score)
            canvas.setFillColor(colors.HexColor(NAVY))
            canvas.setFont(font_name, 15)
            canvas.drawCentredString(cx, cy + 1.5 * mm, "—" if score is None else str(round(score)))
            canvas.setFillColor(colors.HexColor(MUTED))
            canvas.setFont(font_name, 6.2)
            canvas.drawCentredString(cx, cy - 3.2 * mm, "/ 100")
            canvas.restoreState()

    class IconBadge(Flowable):
        def __init__(self, kind, color=TEAL_DARK, size=7 * mm):
            super().__init__()
            self.kind = kind
            self.color = color
            self.width = size
            self.height = size

        def draw(self):
            canvas = self.canv
            size = min(self.width, self.height)
            cx, cy = size / 2, size / 2
            canvas.saveState()
            canvas.setFillColor(colors.Color(0.05, 0.58, 0.53, alpha=0.12))
            canvas.circle(cx, cy, size * 0.46, stroke=0, fill=1)
            canvas.setStrokeColor(colors.HexColor(self.color))
            canvas.setFillColor(colors.HexColor(self.color))
            canvas.setLineWidth(1.1)
            if self.kind == "clock":
                canvas.circle(cx, cy, size * 0.28, stroke=1, fill=0)
                canvas.line(cx, cy, cx, cy + size * 0.15)
                canvas.line(cx, cy, cx + size * 0.12, cy - size * 0.08)
            elif self.kind == "shield":
                path = canvas.beginPath()
                path.moveTo(cx, cy + size * 0.30)
                path.lineTo(cx + size * 0.24, cy + size * 0.18)
                path.lineTo(cx + size * 0.18, cy - size * 0.18)
                path.lineTo(cx, cy - size * 0.31)
                path.lineTo(cx - size * 0.18, cy - size * 0.18)
                path.lineTo(cx - size * 0.24, cy + size * 0.18)
                path.close()
                canvas.drawPath(path, stroke=1, fill=0)
                canvas.line(cx - size * 0.10, cy, cx - size * 0.02, cy - size * 0.08)
                canvas.line(cx - size * 0.02, cy - size * 0.08, cx + size * 0.13, cy + size * 0.10)
            elif self.kind == "index":
                for offset, height in ((-0.19, 0.18), (0, 0.28), (0.19, 0.36)):
                    canvas.roundRect(cx + offset * size - size * 0.055, cy - size * 0.20, size * 0.11, height * size, 1, stroke=0, fill=1)
            else:
                canvas.circle(cx, cy, size * 0.28, stroke=1, fill=0)
                canvas.circle(cx, cy, size * 0.14, stroke=1, fill=0)
                canvas.circle(cx, cy, size * 0.035, stroke=0, fill=1)
            canvas.restoreState()

    class ScoreGauge(Flowable):
        def __init__(self, score, width=25 * mm, height=3.2 * mm):
            super().__init__()
            self.score = score
            self.width = width
            self.height = height

        def draw(self):
            if self.score is None:
                return
            score = max(0, min(100, float(self.score)))
            if score >= 75:
                color = TEAL_DARK
            elif score >= 55:
                color = GREEN
            elif score >= 40:
                color = AMBER
            else:
                color = RED
            canvas = self.canv
            canvas.saveState()
            canvas.setFillColor(colors.HexColor(LIGHT_GREY))
            canvas.roundRect(0, 0, self.width, self.height, self.height / 2, stroke=0, fill=1)
            fill_width = max(self.height, self.width * score / 100)
            canvas.setFillColor(colors.HexColor(color))
            canvas.roundRect(0, 0, fill_width, self.height, self.height / 2, stroke=0, fill=1)
            canvas.restoreState()

    def p(value, style=body):
        return Paragraph(markup(value), style)

    def section_title(label, number=None):
        prefix = f"{number:02d}  " if number is not None else ""
        return Paragraph(markup(prefix + label), h1)

    def tone_colors(tone):
        return {
            "excellent": (TEAL_DARK, PALE),
            "positive": (GREEN, LIGHT_GREEN),
            "warning": (AMBER, LIGHT_AMBER),
            "danger": (RED, LIGHT_RED),
            "neutral": (MUTED, LIGHT_GREY),
        }.get(tone, (MUTED, LIGHT_GREY))

    def note_box(text, tone="neutral", bold=False, width=169 * mm):
        accent, background = tone_colors(tone)
        return Table(
            [[p(text, body_bold if bold else body)]],
            colWidths=[width],
            cornerRadii=[4 * mm] * 4,
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(background)),
                    ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor(accent)),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            ),
        )

    def info_card(label, value, tone="neutral", width=40.5 * mm, icon=None):
        accent, background = tone_colors(tone)
        if icon:
            rows = [
                [IconBadge(icon, accent), p(label, card_label_left)],
                [p(value, card_value), ""],
            ]
            widths = [9 * mm, width - 9 * mm]
            heights = [9 * mm, 12 * mm]
            extra_commands = [("SPAN", (0, 1), (1, 1))]
        else:
            rows = [[p(label, card_label)], [p(value, card_value)]]
            widths = [width]
            heights = [7 * mm, 12 * mm]
            extra_commands = []
        return Table(
            rows,
            colWidths=widths,
            rowHeights=heights,
            cornerRadii=[3.5 * mm] * 4,
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(background)),
                    ("LINEABOVE", (0, 0), (-1, 0), 2.2, colors.HexColor(accent)),
                    ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor(LINE)),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ] + extra_commands
            ),
        )

    def verdict_badge(verdict, width=169 * mm):
        accent, background = tone_colors(verdict.get("tone"))
        score = verdict.get("score")
        score_text = "—" if score is None else f"{score}/100"
        return Table(
            [[p(verdict.get("label") or "—", body_bold), p(score_text, card_value)]],
            colWidths=[width * 0.74, width * 0.26],
            rowHeights=[18 * mm],
            cornerRadii=[4 * mm] * 4,
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(background)),
                    ("LINEBEFORE", (0, 0), (0, -1), 5, colors.HexColor(accent)),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(accent)),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ]
            ),
        )

    def stamp_card(item, width=82 * mm):
        accent, background = tone_colors(item.get("tone"))
        evidence = item.get("headline_evidence") or []
        evidence_text = " · ".join(
            f"{metric.get('label')}: {metric.get('display')}" for metric in evidence
        ) or copy["no_data"]
        coverage = f"{item.get('coverage', 0)} % {copy['coverage']}"
        return Table(
            [
                [p(item.get("stamp") or item.get("label"), stamp_label)],
                [p(evidence_text, small)],
                [
                    ScoreGauge(
                        item.get("score") if item.get("coverage") else None,
                        width=width - 12 * mm,
                    )
                ],
                [p(coverage, tiny)],
            ],
            colWidths=[width],
            cornerRadii=[3.5 * mm] * 4,
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(background)),
                    ("LINEABOVE", (0, 0), (-1, 0), 2.2, colors.HexColor(accent)),
                    ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor(LINE)),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            ),
        )

    def standard_table(rows, widths, header=True, repeat=True, extra_style=None):
        commands = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY if header else "#FFFFFF")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white if header else colors.HexColor(INK)),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor(LINE)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F8FA")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ]
        commands.extend(extra_style or [])
        style = TableStyle(commands)
        return Table(rows, colWidths=widths, repeatRows=1 if header and repeat else 0, style=style)

    def bullet_list(items, tone):
        accent, background = tone_colors(tone)
        flows = []
        for item in items:
            flows.append(
                Table(
                    [["", p(item, body)]],
                    colWidths=[3 * mm, 166 * mm],
                    style=TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor(accent)),
                            ("BACKGROUND", (1, 0), (1, 0), colors.HexColor(background)),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (0, 0), 0),
                            ("RIGHTPADDING", (0, 0), (0, 0), 0),
                            ("LEFTPADDING", (1, 0), (1, 0), 7),
                            ("RIGHTPADDING", (1, 0), (1, 0), 7),
                            ("TOPPADDING", (0, 0), (-1, -1), 5),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ]
                    ),
                )
            )
            flows.append(Spacer(1, 1.5 * mm))
        return flows

    def rank_text(item):
        if not item or not item.get("available"):
            return "—"
        return f"{item.get('rank')}/{item.get('total')}"

    analysis = getattr(report, "analysis_payload", None) or {}
    narrative = analysis.get("narrative") or {}
    player = analysis.get("player") or {}
    confidence = analysis.get("confidence") or {}
    verdict = analysis.get("verdict") or {}
    rankings = analysis.get("rankings") or {}
    context = analysis.get("context") or {}
    match = getattr(report, "match", None)
    subscription = getattr(report, "subscription", None)
    player_obj = getattr(subscription, "player", None)
    player_name = player.get("name") or getattr(player_obj, "name", "")
    raw_positions = player.get("positions") or player.get("position") or []
    if isinstance(raw_positions, str):
        raw_positions = re.split(r"\s*[/,;|+]\s*", raw_positions)
    positions = list(
        dict.fromkeys(
            str(code).strip().upper() for code in raw_positions if str(code).strip()
        )
    )
    fixture = ""
    if match:
        fixture = (
            f"{getattr(match, 'home_team', '')} "
            f"{getattr(match, 'score', '–')} "
            f"{getattr(match, 'away_team', '')}"
        ).strip()

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title=str(getattr(report, "title", "MS Performance")),
        author="MS Performance",
    )

    def first_page(canvas, doc):
        canvas.saveState()
        width, height = A4
        canvas.setFillColor(colors.HexColor(NAVY))
        canvas.rect(0, 0, width, height, stroke=0, fill=1)
        canvas.setFillColor(colors.HexColor(TEAL))
        canvas.rect(0, 0, 8 * mm, height, stroke=0, fill=1)
        canvas.setStrokeColor(colors.Color(1, 1, 1, alpha=0.12))
        canvas.setLineWidth(0.5)
        for offset in (32, 58, 84):
            canvas.circle(width - 7 * mm, height - offset * mm, 44 * mm, stroke=1, fill=0)
        canvas.setFillColor(colors.HexColor(CYAN))
        canvas.circle(width - 24 * mm, 24 * mm, 3 * mm, stroke=0, fill=1)
        canvas.restoreState()

    def later_pages(canvas, doc):
        canvas.saveState()
        width, height = A4
        canvas.setStrokeColor(colors.HexColor(LINE))
        canvas.line(18 * mm, height - 11 * mm, width - 18 * mm, height - 11 * mm)
        canvas.setFillColor(colors.HexColor(TEAL_DARK))
        canvas.setFont(font_name, 7)
        canvas.drawString(18 * mm, height - 8 * mm, "MS PERFORMANCE")
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawRightString(width - 18 * mm, height - 8 * mm, display(player_name))
        canvas.line(18 * mm, 10 * mm, width - 18 * mm, 10 * mm)
        canvas.drawString(18 * mm, 6 * mm, display(copy["prepared"]))
        canvas.drawRightString(width - 18 * mm, 6 * mm, f"{display(copy['page'])} {doc.page}")
        canvas.restoreState()

    story = [
        Spacer(1, 20 * mm),
        p("MS PERFORMANCE", cover_kicker),
        Spacer(1, 3 * mm),
        p(copy["brand"], cover_kicker),
        Spacer(1, 24 * mm),
        p(player_name, title_style),
        p(getattr(report, "title", ""), cover_meta),
        Spacer(1, 14 * mm),
    ]
    if fixture:
        story.append(
            Table(
                [[p(fixture, cover_meta)]],
                colWidths=[169 * mm],
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.Color(1, 1, 1, alpha=0.08)),
                        ("LINEABOVE", (0, 0), (-1, 0), 1.2, colors.HexColor(CYAN)),
                        ("LEFTPADDING", (0, 0), (-1, -1), 9),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                        ("TOPPADDING", (0, 0), (-1, -1), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ]
                ),
            )
        )
    story.append(Spacer(1, 12 * mm))
    cover_rows = [
        [
            p(copy["role"], cover_kicker),
            p(
                " · ".join(
                    value for value in (
                        player.get("role_label") or player.get("position") or "—",
                        " / ".join(positions),
                    ) if value
                ),
                cover_meta,
            ),
        ],
        [p(copy["minutes"], cover_kicker), p(player.get("minutes", "—"), cover_meta)],
        [p(copy["reliability"], cover_kicker), p(confidence.get("label") or "—", cover_meta)],
    ]
    cover_profile = Table(
            cover_rows,
            colWidths=[35 * mm, 65 * mm],
            style=TableStyle(
                [
                    ("LINEBELOW", (0, 0), (-1, -1), 0.35, colors.Color(1, 1, 1, alpha=0.2)),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            ),
        )
    pitch_block = Table(
        [[p(copy["position_map"], cover_kicker)], [PositionPitch(positions, width=57 * mm, height=73 * mm, dark=True)]],
        colWidths=[61 * mm],
        cornerRadii=[4 * mm] * 4,
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.Color(1, 1, 1, alpha=0.04)),
                ("BOX", (0, 0), (-1, -1), 0.4, colors.Color(1, 1, 1, alpha=0.16)),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        ),
    )
    story.append(
        Table(
            [[cover_profile, pitch_block]],
            colWidths=[104 * mm, 65 * mm],
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ]
            ),
        )
    )
    story.append(PageBreak())

    if not analysis.get("available"):
        story.extend(
            (
                section_title(copy["verdict"], 1),
                note_box(getattr(report, "executive_summary", "") or copy["unavailable"], "warning", True),
                Spacer(1, 5 * mm),
                p(copy["unavailable"], body),
            )
        )
        document.build(story, onFirstPage=first_page, onLaterPages=later_pages)
        return buffer.getvalue()

    story.append(section_title(copy["verdict"], 1))
    verdict_summary = Table(
        [
            [verdict_badge(verdict, width=124 * mm)],
            [Spacer(1, 2 * mm)],
            [
                note_box(
                    narrative.get("executive_summary") or getattr(report, "executive_summary", ""),
                    verdict.get("tone", "neutral"),
                    True,
                    width=124 * mm,
                )
            ],
        ],
        colWidths=[124 * mm],
        style=TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        ),
    )
    story.extend(
        [
            Table(
                [[ScoreRing(verdict.get("score"), tone=verdict.get("tone", "neutral")), verdict_summary]],
                colWidths=[42 * mm, 127 * mm],
                style=TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ]
                ),
            ),
            Spacer(1, 5 * mm),
        ]
    )
    decisive_highlights = analysis.get("decisive_highlights") or []
    if decisive_highlights:
        story.extend([p(copy["decisive_facts"], h2)])
        for highlight in decisive_highlights:
            story.extend(
                [
                    note_box(
                        f"{highlight.get('label')}\n{highlight.get('explanation')}",
                        highlight.get("tone", "excellent"),
                        True,
                    ),
                    Spacer(1, 2 * mm),
                ]
            )
    story.extend(
        [
            Table(
                [[
                    info_card(copy["minutes"], player.get("minutes", "—"), "neutral", icon="clock"),
                    info_card(copy["reliability"], confidence.get("label") or "—", "warning" if confidence.get("score", 0) < 60 else "positive", icon="shield"),
                    info_card(copy["index"], player.get("index") if player.get("index") is not None else "—", "neutral", icon="index"),
                    info_card(copy["mission_score"], "—" if player.get("profile_score") is None else f"{player.get('profile_score')}/100", verdict.get("tone", "neutral"), icon="target"),
                ]],
                colWidths=[42.25 * mm] * 4,
                style=TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 1),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
                    ]
                ),
            ),
            Spacer(1, 5 * mm),
            p(copy["rankings"], h2),
            Table(
                [[
                    info_card(copy["index_team"], rank_text(rankings.get("index_team")), "neutral", 54 * mm),
                    info_card(copy["index_match"], rank_text(rankings.get("index_match")), "neutral", 54 * mm),
                    info_card(copy["index_position"], rank_text(rankings.get("index_same_position")), "neutral", 54 * mm),
                ]],
                colWidths=[56.3 * mm] * 3,
                style=TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 1),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
                    ]
                ),
            ),
            Spacer(1, 2 * mm),
            p(copy["index_note"], tiny),
            Spacer(1, 5 * mm),
            p(copy["role_missions"], h2),
        ]
    )
    dimensions = analysis.get("dimensions") or []
    stamp_rows = []
    # The verdict page keeps the four highest-weight missions.  The full list
    # and every criterion follow immediately in the calculation pages.
    summary_dimensions = dimensions[:4]
    for index in range(0, len(summary_dimensions), 2):
        row = [stamp_card(summary_dimensions[index])]
        row.append(stamp_card(summary_dimensions[index + 1]) if index + 1 < len(summary_dimensions) else "")
        stamp_rows.append(row)
    story.append(
        Table(
            stamp_rows,
            colWidths=[84.5 * mm, 84.5 * mm],
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 1.5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 1.5),
                    ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                ]
            ),
        )
    )
    story.append(PageBreak())

    score_breakdown = analysis.get("score_breakdown") or {}
    breakdown_dimensions = score_breakdown.get("dimensions") or []
    story.extend([section_title(copy["role_missions"], 2), p(copy["mission_note"], small), Spacer(1, 4 * mm)])
    dimension_rows = [[p(copy["role_missions"], table_head), p(copy["effective_weight"], table_head), p(copy["reading"], table_head), p(copy["contribution"], table_head), p(copy["score_reasons"], table_head)]]
    for item in breakdown_dimensions:
        score_value = copy["not_assessed"] if item.get("score") is None else f"{item.get('score')}/100"
        used_criteria = sorted(
            [criterion for criterion in item.get("criteria") or [] if criterion.get("used")],
            key=lambda criterion: criterion.get("final_contribution", 0),
            reverse=True,
        )
        reason_lines = [
            f"{criterion.get('label')}: {criterion.get('display')}"
            for criterion in used_criteria[:4]
        ]
        dimension_rows.append(
            [
                p(item.get("label"), body_bold),
                p(f"{item.get('effective_weight', 0)} %", body),
                p(score_value, body),
                p(f"{item.get('contribution', 0)} pts", body_bold),
                p(" · ".join(reason_lines) if reason_lines else copy["not_assessed"], tiny),
            ]
        )
    dimension_rows.append(
        [
            p(copy["weighted_total"], body_bold),
            p("100 %", body_bold),
            p(f"{score_breakdown.get('rounded_score', '—')}/100", body_bold),
            p(f"{score_breakdown.get('contribution_total', 0)} pts", body_bold),
            p(score_breakdown.get("formula") or "", tiny),
        ]
    )
    story.append(
        standard_table(
            dimension_rows,
            [33 * mm, 20 * mm, 20 * mm, 22 * mm, 74 * mm],
            extra_style=[
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor(PALE)),
                ("LINEABOVE", (0, -1), (-1, -1), 1.2, colors.HexColor(TEAL_DARK)),
            ],
        )
    )
    story.extend([Spacer(1, 4 * mm)])
    impact_drivers = score_breakdown.get("impact_drivers") or []
    if impact_drivers:
        story.extend([p(copy["impact_drivers"], h2), p(copy["impact_note"], tiny), Spacer(1, 2 * mm)])
        impact_rows = []
        for index in range(0, min(len(impact_drivers), 6), 2):
            cells = []
            for driver in impact_drivers[index:index + 2]:
                effect = (driver.get("effect") or {}).get("code")
                tone = "positive" if effect in {"positive", "very_positive"} else "warning" if effect in {"negative", "very_negative"} else "neutral"
                cells.append(
                    note_box(
                        f"{driver.get('explanation') or ''}\n{driver.get('score_sentence') or ''}",
                        tone,
                        width=82 * mm,
                    )
                )
            if len(cells) == 1:
                cells.append("")
            impact_rows.append(cells)
        story.extend(
            [
                Table(
                    impact_rows,
                    colWidths=[84.5 * mm, 84.5 * mm],
                    style=TableStyle(
                        [
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 1),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 1),
                            ("TOPPADDING", (0, 0), (-1, -1), 1),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                        ]
                    ),
                ),
                Spacer(1, 3 * mm),
            ]
        )
    story.extend(
        [
            Spacer(1, 3 * mm),
            note_box(
                copy["score_total_note"].format(
                    raw=score_breakdown.get("contribution_total", 0),
                    score=score_breakdown.get("rounded_score", "—"),
                ),
                "neutral",
                True,
            ),
        ]
    )
    benchmark = analysis.get("position_benchmark") or {}
    section_number = 3
    if benchmark.get("available"):
        benchmark_metrics = benchmark.get("comparable_metrics") or []
        story.extend(
            [
                PageBreak(),
                section_title(copy["position_benchmark"], section_number),
                p(
                    copy["benchmark_position"].format(
                        position=benchmark.get("position_name") or benchmark.get("position_code") or "—",
                        percent=benchmark.get("position_percent", 0),
                        season=benchmark.get("season") or "—",
                    ),
                    body_bold,
                ),
                Spacer(1, 1 * mm),
                p(benchmark.get("note") or "", small),
                Spacer(1, 2 * mm),
                BenchmarkRadar(benchmark_metrics),
                Spacer(1, 1 * mm),
            ]
        )
        benchmark_rows = [[
            p(copy["indicator"], table_head),
            p(copy["benchmark_match"], table_head),
            p(copy["benchmark_average"], table_head),
            p(copy["benchmark_difference"], table_head),
        ]]
        for item in benchmark_metrics:
            difference = item.get("difference")
            precision = max(0, min(2, int(item.get("precision") or 0)))
            unit = item.get("unit")

            def radar_value(value):
                if value is None:
                    return "—"
                rendered = f"{float(value):.{precision}f}".rstrip("0").rstrip(".")
                return f"{rendered} %" if unit == "%" else f"{rendered} /90"

            if difference is None:
                difference_display = "—"
            else:
                rendered_difference = f"{float(difference):+.{precision}f}".rstrip("0").rstrip(".")
                difference_display = f"{rendered_difference} pts" if unit == "%" else f"{rendered_difference} /90"
            benchmark_rows.append(
                [
                    p(item.get("label") or item.get("metric"), small),
                    p(radar_value(item.get("season_player")), body_bold),
                    p(radar_value(item.get("position_average")), body),
                    p(difference_display, body_bold),
                ]
            )
        story.append(standard_table(benchmark_rows, [62 * mm, 39 * mm, 39 * mm, 29 * mm]))
        section_number += 1
    story.extend([PageBreak(), section_title(copy["performance_reading"], section_number), p(copy["performance_note"], small), Spacer(1, 3 * mm)])
    section_number += 1
    phase_priority = {
        "global": ("Actions", "Actions successful, %", "Passes", "Passes accurate, %", "Index"),
        "offensive": (
            "Goals", "Assists", "xG (expected goals)", "Key passes", "Chances created",
            "Involvement in scoring attacks", "Actions in opponent's box",
            "Actions in opponent's box successful, %", "Final third entries",
            "Final third entries through pass", "Final third entries through carry",
            "Progressive passes", "Dribbles", "Shots",
        ),
        "defensive": (
            "Defensive challenges", "Defensive challenges won, %", "Tackles",
            "Tackles successful, %", "Interceptions", "Aerial challenges",
            "Aerial challenges won, %", "Ball recoveries", "Lost balls in own half",
        ),
    }
    for lens in analysis.get("performance_lenses") or []:
        score = lens.get("score")
        story.extend(
            [
                Spacer(1, 3 * mm),
                Table(
                    [[p(lens.get("label"), h2), p(copy["not_assessed"] if score is None else f"{score}/100 · {lens.get('grade_label')}", body_bold)]],
                    colWidths=[124 * mm, 45 * mm],
                    style=TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(PALE)),
                            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(TEAL_DARK)),
                            ("LEFTPADDING", (0, 0), (-1, -1), 7),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                            ("TOPPADDING", (0, 0), (-1, -1), 6),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                        ]
                    ),
                ),
            ]
        )
        for sentence in lens.get("interpretation") or []:
            story.extend([Spacer(1, 1.5 * mm), note_box(sentence, lens.get("tone") or "neutral")])
        metrics_by_name = {item.get("metric"): item for item in lens.get("metrics") or []}
        visible_metrics = [metrics_by_name[name] for name in phase_priority.get(lens.get("key"), ()) if name in metrics_by_name]
        for item in lens.get("metrics") or []:
            if item in visible_metrics or item.get("score") is None:
                continue
            visible_metrics.append(item)
            if len(visible_metrics) >= 12:
                break
        metric_rows = [[p(copy["indicator"], table_head), p(copy["real_value"], table_head), p(copy["reading"], table_head), p(copy["profile"], table_head)]]
        for item in visible_metrics:
            sample = item.get("sample") or {}
            score_value = copy["not_assessed"] if item.get("score") is None else f"{item.get('score')}/100"
            metric_rows.append(
                [
                    [p(item.get("label"), body_bold), p(item.get("definition") or "", tiny)],
                    [p(item.get("display") or "0", body_bold), p(sample.get("label") or "", tiny)],
                    [p(score_value, body_bold), ScoreGauge(item.get("score"), width=23 * mm)],
                    p(item.get("mission") or "—", small),
                ]
            )
        if len(metric_rows) > 1:
            story.extend([Spacer(1, 2 * mm), standard_table(metric_rows, [69 * mm, 35 * mm, 28 * mm, 37 * mm])])

    stats = getattr(match, "player_stats", None) if match else None
    images = []
    for label, binary, note in (
        (copy["heatmap"], getattr(stats, "heatmap_png", None) if stats else None, copy["heat_note"]),
        (copy["touches"], getattr(stats, "ball_touches_png", None) if stats else None, copy["touch_note"]),
    ):
        if binary:
            raw = bytes(binary)
            image = Image(io.BytesIO(raw), width=80 * mm, height=53 * mm)
            images.append((label, image, note))
    if images:
        story.extend([PageBreak(), section_title(copy["maps"], section_number)])
        section_number += 1
        cells = []
        for label, image, note in images:
            cells.append(
                Table(
                    [[p(label, h2)], [image], [p(note, tiny)]],
                    colWidths=[82 * mm],
                    style=TableStyle(
                        [
                            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor(LINE)),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(PALE)),
                            ("LEFTPADDING", (0, 0), (-1, -1), 4),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ]
                    ),
                )
            )
        story.append(
            Table(
                [cells],
                colWidths=[84.5 * mm] * len(cells),
                style=TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 1),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
                    ]
                ),
            )
        )
        territory = context.get("territory") or {}
        if territory.get("available"):
            thirds = territory.get("displayed_thirds") or {}
            lanes = territory.get("lanes") or {}
            story.extend([Spacer(1, 6 * mm), p(copy["thirds"], h2)])
            story.append(
                Table(
                    [[
                        info_card(copy["left"], f"{thirds.get('displayed_left', 0)} %", "neutral", 54 * mm),
                        info_card(copy["middle"], f"{thirds.get('displayed_middle', 0)} %", "neutral", 54 * mm),
                        info_card(copy["right"], f"{thirds.get('displayed_right', 0)} %", "neutral", 54 * mm),
                    ]],
                    colWidths=[56.3 * mm] * 3,
                    style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]),
                )
            )
            story.extend([Spacer(1, 4 * mm), p(copy["lanes"], h2)])
            story.append(
                Table(
                    [[
                        info_card(copy["wide"], f"{lanes.get('wide', 0)} %", "neutral", 54 * mm),
                        info_card(copy["half_space"], f"{lanes.get('half_space', 0)} %", "neutral", 54 * mm),
                        info_card(copy["central"], f"{lanes.get('central', 0)} %", "neutral", 54 * mm),
                    ]],
                    colWidths=[56.3 * mm] * 3,
                    style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]),
                )
            )
            story.extend([Spacer(1, 3 * mm), p(territory.get("note"), tiny)])

    story.extend([PageBreak(), section_title(copy["strengths"], section_number)])
    section_number += 1
    story.extend(bullet_list(narrative.get("strengths") or [], "positive"))
    story.extend([Spacer(1, 3 * mm), section_title(copy["risks"], section_number)])
    section_number += 1
    story.extend(bullet_list(narrative.get("risks") or [], "warning"))
    story.extend([Spacer(1, 3 * mm), section_title(copy["development"], section_number)])
    section_number += 1
    story.extend(bullet_list(narrative.get("development") or [], "excellent"))
    story.extend([Spacer(1, 3 * mm), note_box(f"{copy['video_check']}\n{narrative.get('video_limit') or ''}", "neutral")])

    story.extend([PageBreak(), section_title(copy["comparisons"], section_number), p(copy["comparison_note"], small), Spacer(1, 5 * mm), p(copy["matchups"], h2)])
    section_number += 1
    matchup = analysis.get("same_position_comparison")
    if not matchup:
        story.append(note_box(copy["no_comparison"], "neutral"))
    else:
        title = (
            f"{matchup.get('title')} — {matchup.get('player')} · {matchup.get('team')} · "
            f"{matchup.get('position')} ({matchup.get('minutes', 0)} min)"
        )
        rows = [[p(copy["indicator"], table_head), p(copy["target"], table_head), p(copy["opponent"], table_head)]]
        has_non_comparable = False
        for item in matchup.get("metrics") or []:
            comparable = item.get("volume_comparable", True)
            has_non_comparable = has_non_comparable or not comparable
            marker = "*" if not comparable else ""
            rows.append(
                [
                    p(item.get("label"), body),
                    p(f"{item.get('target_display')}{marker}", body_bold),
                    p(f"{item.get('opponent_display')}{marker}", body),
                ]
            )
        block = [p(title, h2), standard_table(rows, [91 * mm, 39 * mm, 39 * mm])]
        if has_non_comparable:
            block.append(p(copy["not_comparable"], tiny))
        story.extend([KeepTogether(block), Spacer(1, 5 * mm)])

    story.extend([Spacer(1, 4 * mm), p(copy["global_leaders"], h2), p(copy["global_note"], tiny), Spacer(1, 3 * mm)])
    leader_rows = [[p(copy["indicator"], table_head), p(copy["target"], table_head), p(copy["target_rank"], table_head), p(copy["match_leader"], table_head)]]
    for item in analysis.get("global_benchmarks") or []:
        rank = item.get("target_rank") or {}
        rank_value = rank_text(rank)
        leaders = item.get("leaders") or []
        leader_text = "\n".join(
            f"{leader.get('name')} · {leader.get('team')} · {leader.get('position')} · "
            f"{leader.get('display')} ({leader.get('minutes')} min)"
            for leader in leaders
        ) or "—"
        leader_rows.append(
            [
                [p(item.get("label"), body_bold), p(item.get("definition") or "", tiny)],
                p(item.get("target_display") or "—", body_bold),
                p(rank_value, body),
                p(leader_text, small),
            ]
        )
    if len(leader_rows) == 1:
        leader_rows.append([p(copy["no_data"], body), p("—", body), p("—", body), p("—", body)])
    story.append(standard_table(leader_rows, [55 * mm, 30 * mm, 23 * mm, 61 * mm]))

    story.extend([PageBreak(), section_title(copy["method"], section_number), note_box(copy["method_text"], "neutral"), Spacer(1, 4 * mm)])
    section_number += 1
    if confidence.get("explanation"):
        story.extend([note_box(confidence.get("explanation"), "warning", True), Spacer(1, 4 * mm)])
    story.extend([p(narrative.get("sample_caution") or "", body), Spacer(1, 3 * mm), p(narrative.get("video_limit") or "", body), Spacer(1, 6 * mm), p(copy["source"], h2)])
    for source in analysis.get("methodology_sources") or []:
        hostname = urlparse(str(source.get("url") or "")).netloc
        story.append(p(f"{source.get('name')} — {hostname}", small))
        story.append(Spacer(1, 1 * mm))
    story.extend([Spacer(1, 10 * mm), p(copy["prepared"], body_bold)])

    story.extend(
        [
            PageBreak(),
            section_title(copy["appendix"], section_number),
            note_box(copy["full_data_note"], "neutral"),
            Spacer(1, 2 * mm),
            p(copy["columns_presented"].format(count=analysis.get("appendix_total_columns", 0)), small),
            Spacer(1, 4 * mm),
        ]
    )
    appendix_groups = analysis.get("appendix_groups") or []
    if not appendix_groups:
        story.append(note_box(copy["no_data"], "neutral"))
    for group in appendix_groups:
        story.extend([p(group.get("label"), h2), Spacer(1, 1 * mm)])
        metrics = group.get("items") or []
        rows = [[p(copy["indicator"], table_head), p(copy["real_value"], table_head), p(copy["indicator"], table_head), p(copy["real_value"], table_head)]]
        extra_style = []
        for index in range(0, len(metrics), 2):
            pair = [metrics[index], metrics[index + 1] if index + 1 < len(metrics) else {}]
            cells = []
            row_number = len(rows)
            for side, item in enumerate(pair):
                if not item:
                    cells.extend([p("", small), p("", body)])
                    continue
                marker = copy["decisive_kpi"] if item.get("decisive") else copy["role_kpi"] if item.get("role_specific") else ""
                label_cell = [p(item.get("label"), body_bold if marker else small)]
                if marker:
                    label_cell.append(p(marker, tiny))
                cells.extend([label_cell, p(item.get("display") or "0", body_bold)])
                start_column = 0 if side == 0 else 2
                if item.get("decisive"):
                    extra_style.extend(
                        [
                            ("BACKGROUND", (start_column, row_number), (start_column + 1, row_number), colors.HexColor(LIGHT_GREEN)),
                            ("LINEBEFORE", (start_column, row_number), (start_column, row_number), 2, colors.HexColor(GREEN)),
                        ]
                    )
                elif item.get("role_specific"):
                    extra_style.extend(
                        [
                            ("BACKGROUND", (start_column, row_number), (start_column + 1, row_number), colors.HexColor(PALE)),
                            ("LINEBEFORE", (start_column, row_number), (start_column, row_number), 2, colors.HexColor(TEAL_DARK)),
                        ]
                    )
            rows.append(cells)
        story.append(standard_table(rows, [54 * mm, 30.5 * mm, 54 * mm, 30.5 * mm], extra_style=extra_style))
        story.append(Spacer(1, 4 * mm))

    document.build(story, onFirstPage=first_page, onLaterPages=later_pages)
    return buffer.getvalue()
