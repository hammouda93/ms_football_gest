"""Professional multilingual PDF renderer for SportsBase performance reports."""

import io
import math
from html import escape
from pathlib import Path
from urllib.parse import urlparse


PDF_COPY = {
    "fr": {
        "brand": "ANALYSE DE PERFORMANCE",
        "role": "PROFIL DE POSTE",
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
        "score_total_note": "Total pondéré avant arrondi : {raw} points. Score de mission final : {score}/100.",
        "not_assessed": "Non évalué",
        "coverage": "données observées",
        "key_metrics": "Indicateurs clés du poste",
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
        "score_total_note": "Weighted total before rounding: {raw} points. Final mission score: {score}/100.",
        "not_assessed": "Not assessed",
        "coverage": "observed data",
        "key_metrics": "Position-specific key indicators",
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
        "score_total_note": "المجموع الموزون قبل التقريب: {raw} نقطة. درجة المهمة النهائية: {score}/100.",
        "not_assessed": "غير مقيم",
        "coverage": "بيانات ملاحظة",
        "key_metrics": "المؤشرات الرئيسية للمركز",
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

    def note_box(text, tone="neutral", bold=False):
        accent, background = tone_colors(tone)
        return Table(
            [[p(text, body_bold if bold else body)]],
            colWidths=[169 * mm],
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

    def info_card(label, value, tone="neutral", width=40.5 * mm):
        accent, background = tone_colors(tone)
        return Table(
            [[p(label, card_label)], [p(value, card_value)]],
            colWidths=[width],
            rowHeights=[7 * mm, 12 * mm],
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
                ]
            ),
        )

    def verdict_badge(verdict):
        accent, background = tone_colors(verdict.get("tone"))
        score = verdict.get("score")
        score_text = "—" if score is None else f"{score}/100"
        return Table(
            [[p(verdict.get("label") or "—", body_bold), p(score_text, card_value)]],
            colWidths=[128 * mm, 41 * mm],
            rowHeights=[18 * mm],
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
            [[p(item.get("stamp") or item.get("label"), stamp_label)], [p(evidence_text, small)], [p(coverage, tiny)]],
            colWidths=[width],
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
    story.append(Spacer(1, 22 * mm))
    cover_rows = [
        [p(copy["role"], cover_kicker), p(player.get("role_label") or player.get("position") or "—", cover_meta)],
        [p(copy["minutes"], cover_kicker), p(player.get("minutes", "—"), cover_meta)],
        [p(copy["reliability"], cover_kicker), p(confidence.get("label") or "—", cover_meta)],
    ]
    story.append(
        Table(
            cover_rows,
            colWidths=[55 * mm, 114 * mm],
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

    story.extend(
        [
            section_title(copy["verdict"], 1),
            verdict_badge(verdict),
            Spacer(1, 4 * mm),
            note_box(narrative.get("executive_summary") or getattr(report, "executive_summary", ""), verdict.get("tone", "neutral"), True),
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
                    info_card(copy["minutes"], player.get("minutes", "—"), "neutral"),
                    info_card(copy["reliability"], confidence.get("label") or "—", "warning" if confidence.get("score", 0) < 60 else "positive"),
                    info_card(copy["index"], player.get("index") if player.get("index") is not None else "—", "neutral"),
                    info_card(copy["mission_score"], "—" if player.get("profile_score") is None else f"{player.get('profile_score')}/100", verdict.get("tone", "neutral")),
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
    for index in range(0, len(dimensions), 2):
        row = [stamp_card(dimensions[index])]
        row.append(stamp_card(dimensions[index + 1]) if index + 1 < len(dimensions) else "")
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
    dimension_rows = [[p(copy["role_missions"], table_head), p(copy["effective_weight"], table_head), p(copy["reading"], table_head), p(copy["contribution"], table_head)]]
    for item in breakdown_dimensions:
        score_value = copy["not_assessed"] if item.get("score") is None else f"{item.get('score')}/100"
        dimension_rows.append(
            [
                p(item.get("label"), body_bold),
                p(f"{item.get('effective_weight', 0)} %", body),
                p(score_value, body),
                p(f"{item.get('contribution', 0)} pts", body_bold),
            ]
        )
    dimension_rows.append(
        [
            p(copy["weighted_total"], body_bold),
            p("100 %", body_bold),
            p(f"{score_breakdown.get('rounded_score', '—')}/100", body_bold),
            p(f"{score_breakdown.get('contribution_total', 0)} pts", body_bold),
        ]
    )
    story.append(
        Table(
            [[
                RadarProfile(dimensions, width=70 * mm),
                standard_table(
                    dimension_rows,
                    [37 * mm, 20 * mm, 20 * mm, 23 * mm],
                    extra_style=[
                        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor(PALE)),
                        ("LINEABOVE", (0, -1), (-1, -1), 1.2, colors.HexColor(TEAL_DARK)),
                    ],
                ),
            ]],
            colWidths=[66 * mm, 103 * mm],
            style=TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]),
        )
    )
    story.extend([Spacer(1, 4 * mm), note_box(score_breakdown.get("formula") or "", "neutral"), PageBreak(), p(copy["score_explained"], h1), Spacer(1, 2 * mm)])
    criteria_rows = [[
        p(copy["role_missions"], table_head),
        p(copy["criterion"], table_head),
        p(copy["real_value"], table_head),
        p(copy["criterion_score"], table_head),
        p(copy["contribution"], table_head),
    ]]
    criteria_style = []
    row_index = 1
    effect_backgrounds = {
        "very_positive": LIGHT_GREEN,
        "positive": PALE,
        "negative": LIGHT_AMBER,
        "very_negative": LIGHT_RED,
        "unobserved": LIGHT_GREY,
    }
    for dimension in breakdown_dimensions:
        mission_text = (
            f"{dimension.get('label')}\n"
            f"{copy['configured_weight']}: {dimension.get('configured_weight', 0)} % · "
            f"{copy['effective_weight']}: {dimension.get('effective_weight', 0)} %"
        )
        for criterion_index, criterion in enumerate(dimension.get("criteria") or []):
            effect = criterion.get("effect") or {}
            score_value = copy["not_assessed"] if criterion.get("score") is None else f"{criterion.get('score')}/100"
            criteria_rows.append(
                [
                    p(mission_text if criterion_index == 0 else "", small if criterion_index else body_bold),
                    [p(criterion.get("label"), body_bold), p(criterion.get("definition") or "", tiny), p(f"{copy['effective_weight']}: {criterion.get('criterion_weight', 0)} %", tiny)],
                    p(criterion.get("display") or "0", body_bold),
                    [p(score_value, body_bold), p(effect.get("label") or "", tiny)],
                    p(f"{criterion.get('final_contribution', 0)} pts", body),
                ]
            )
            background = effect_backgrounds.get(effect.get("code"))
            if background:
                criteria_style.append(("BACKGROUND", (3, row_index), (4, row_index), colors.HexColor(background)))
            row_index += 1
    if len(criteria_rows) == 1:
        criteria_rows.append([p(copy["no_data"], body), p("—", body), p("—", body), p("—", body), p("—", body)])
    story.append(standard_table(criteria_rows, [34 * mm, 65 * mm, 24 * mm, 24 * mm, 22 * mm], extra_style=criteria_style))
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
    story.extend([PageBreak(), section_title(copy["key_metrics"], 3), p(copy["raw_note"], small), Spacer(1, 3 * mm)])
    metric_rows = [[p(copy["indicator"], table_head), p(copy["real_value"], table_head), p(copy["sample"], table_head), p(copy["reading"], table_head)]]
    for item in analysis.get("key_metrics") or []:
        sample = item.get("sample") or {}
        sample_text = sample.get("label") or (copy["no_data"] if item.get("display") == "—" else "—")
        percentile = item.get("percentile")
        score = item.get("score")
        reading = "—"
        if score is not None:
            reading = f"{score}/100"
        if percentile is not None:
            reading += f" · P{percentile}" if reading != "—" else f"P{percentile}"
        metric_rows.append(
            [
                [p(item.get("label"), body_bold), p(item.get("definition") or "", tiny)],
                p(item.get("display"), body_bold),
                p(sample_text, tiny),
                p(reading, body),
            ]
        )
    story.append(standard_table(metric_rows, [67 * mm, 34 * mm, 39 * mm, 29 * mm]))
    story.append(PageBreak())

    story.extend([section_title(copy["glossary"], 4)])
    glossary_rows = [[p(copy["indicator"], table_head), p(copy["meaning"], table_head)]]
    for item in analysis.get("glossary") or []:
        glossary_rows.append([p(item.get("label"), body_bold), p(item.get("definition"), body)])
    if len(glossary_rows) == 1:
        glossary_rows.append([p(copy["no_data"], body), p("—", body)])
    story.append(standard_table(glossary_rows, [55 * mm, 114 * mm]))

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
        story.extend([PageBreak(), section_title(copy["maps"], 5)])
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

    story.extend([PageBreak(), section_title(copy["strengths"], 6)])
    story.extend(bullet_list(narrative.get("strengths") or [], "positive"))
    story.extend([Spacer(1, 3 * mm), section_title(copy["risks"], 7)])
    story.extend(bullet_list(narrative.get("risks") or [], "warning"))
    story.extend([Spacer(1, 3 * mm), section_title(copy["development"], 8)])
    story.extend(bullet_list(narrative.get("development") or [], "excellent"))
    story.extend([Spacer(1, 3 * mm), note_box(f"{copy['video_check']}\n{narrative.get('video_limit') or ''}", "neutral")])

    story.extend([PageBreak(), section_title(copy["comparisons"], 9), p(copy["comparison_note"], small), Spacer(1, 5 * mm), p(copy["matchups"], h2)])
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

    story.extend([PageBreak(), section_title(copy["method"], 10), note_box(copy["method_text"], "neutral"), Spacer(1, 4 * mm)])
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
            section_title(copy["appendix"], 11),
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
