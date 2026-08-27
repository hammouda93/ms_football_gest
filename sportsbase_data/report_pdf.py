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
        "confidence": "FIABILITÉ",
        "index": "INDEX SPORTSBASE",
        "executive": "Verdict de l’analyste",
        "role_profile": "Profil relatif au poste",
        "role_note": "Scores relatifs à ce match et au groupe de comparaison — pas une note de niveau absolu.",
        "key_metrics": "Indicateurs clés",
        "per90_note": "Les volumes /90 servent uniquement à comparer des temps de jeu différents. Ils ne constituent pas une projection.",
        "compartment": "Comparaison dans le même compartiment",
        "player": "Joueur",
        "position": "Poste",
        "profile": "Profil relatif",
        "matchups": "Comparaisons adverses",
        "target": "Joueur",
        "opponent": "Adversaire",
        "units": "Lecture collective par compartiment",
        "unit_explanation": "Les taux sont pondérés par le nombre de tentatives. Les remplaçants d’un même rôle sont agrégés.",
        "strengths": "Points forts observés",
        "risks": "Risques et limites",
        "development": "Axes de progression",
        "maps": "Empreinte terrain",
        "heatmap": "Carte de chaleur",
        "touches": "Carte des contacts",
        "method": "Méthodologie et limites",
        "method_text": "Lecture positionnelle à trois échelles : joueur, compartiment et équipe. Les volumes sont normalisés par 90 minutes, les pourcentages sont pondérés par les tentatives et les conclusions sont calibrées selon le temps de jeu.",
        "video_limit": "Les déplacements sans ballon, les consignes tactiques, la qualité du pressing et l’intention de jeu doivent être confirmés par la vidéo.",
        "prepared": "Préparé par l’équipe d’analyse MS Performance",
        "source": "Références méthodologiques",
        "page": "Page",
        "unavailable": "Les données complètes du fichier Players XLSX ne sont pas encore disponibles pour ce match.",
    },
    "en": {
        "brand": "PERFORMANCE ANALYSIS",
        "role": "POSITION PROFILE",
        "minutes": "MINUTES",
        "confidence": "RELIABILITY",
        "index": "SPORTSBASE INDEX",
        "executive": "Analyst verdict",
        "role_profile": "Position-relative profile",
        "role_note": "Match-relative scores within the comparison group — not an absolute ability rating.",
        "key_metrics": "Key indicators",
        "per90_note": "Per-90 volumes are used only to compare different playing times. They are not a projection.",
        "compartment": "Same-unit comparison",
        "player": "Player",
        "position": "Position",
        "profile": "Relative profile",
        "matchups": "Opponent comparisons",
        "target": "Player",
        "opponent": "Opponent",
        "units": "Collective unit analysis",
        "unit_explanation": "Rates are weighted by attempts. Substitutes in the same role are aggregated.",
        "strengths": "Observed strengths",
        "risks": "Risks and limitations",
        "development": "Development priorities",
        "maps": "Pitch footprint",
        "heatmap": "Heatmap",
        "touches": "Ball-touch map",
        "method": "Methodology and limitations",
        "method_text": "Position-specific analysis at three scales: player, unit and team. Volumes are normalised per 90, percentages are weighted by attempts and conclusions are calibrated to playing time.",
        "video_limit": "Off-ball movement, tactical instructions, pressing quality and playing intention require video confirmation.",
        "prepared": "Prepared by the MS Performance analysis team",
        "source": "Methodology references",
        "page": "Page",
        "unavailable": "The full Players XLSX dataset is not yet available for this match.",
    },
    "ar": {
        "brand": "تحليل الأداء",
        "role": "ملف المركز",
        "minutes": "الدقائق",
        "confidence": "الموثوقية",
        "index": "مؤشر سبورتس بايز",
        "executive": "خلاصة المحلل",
        "role_profile": "الملف النسبي حسب المركز",
        "role_note": "درجات نسبية خاصة بهذه المباراة ومجموعة المقارنة وليست تقييما مطلقا لمستوى اللاعب.",
        "key_metrics": "المؤشرات الرئيسية",
        "per90_note": "تستخدم أحجام كل 90 دقيقة فقط لمقارنة أوقات اللعب المختلفة وليست توقعا للمستقبل.",
        "compartment": "المقارنة داخل نفس الخط",
        "player": "اللاعب",
        "position": "المركز",
        "profile": "الملف النسبي",
        "matchups": "المقارنات مع المنافس",
        "target": "اللاعب",
        "opponent": "المنافس",
        "units": "التحليل الجماعي حسب الخطوط",
        "unit_explanation": "يتم ترجيح النسب بعدد المحاولات وتجميع البدلاء في نفس الدور.",
        "strengths": "نقاط القوة الملاحظة",
        "risks": "المخاطر والحدود",
        "development": "محاور التطوير",
        "maps": "البصمة داخل الملعب",
        "heatmap": "الخريطة الحرارية",
        "touches": "خريطة لمس الكرة",
        "method": "المنهجية والحدود",
        "method_text": "تحليل حسب المركز على ثلاثة مستويات: اللاعب والخط والفريق. يتم توحيد الأحجام لكل 90 دقيقة وترجيح النسب بالمحاولات وربط قوة الاستنتاج بوقت اللعب.",
        "video_limit": "تحتاج التحركات دون كرة والتعليمات التكتيكية وجودة الضغط ونية اللعب إلى تأكيد بالفيديو.",
        "prepared": "إعداد فريق تحليل MS Performance",
        "source": "المراجع المنهجية",
        "page": "صفحة",
        "unavailable": "بيانات ملف Players XLSX الكاملة غير متاحة بعد لهذه المباراة.",
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


def _report_type(report):
    return str(getattr(report, "report_type", "") or "")


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
        return "<br/>".join(
            escape(display(line)) for line in str(value or "").splitlines()
        )

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
    h1 = ParagraphStyle(
        "MSPH1",
        parent=styles["Heading1"],
        fontName=font_name,
        fontSize=16,
        leading=21,
        textColor=colors.HexColor(NAVY),
        alignment=align,
        spaceBefore=2 * mm,
        spaceAfter=4 * mm,
    )
    h2 = ParagraphStyle(
        "MSPH2",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=10,
        leading=13,
        textColor=colors.HexColor(TEAL_DARK),
        alignment=align,
        spaceBefore=2 * mm,
        spaceAfter=2 * mm,
    )
    body = ParagraphStyle(
        "MSPBody",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=8.4,
        leading=13,
        textColor=colors.HexColor(INK),
        alignment=align,
    )
    body_bold = ParagraphStyle(
        "MSPBodyBold",
        parent=body,
        fontSize=9.2,
        leading=13.5,
        textColor=colors.HexColor(NAVY),
    )
    small = ParagraphStyle(
        "MSPSmall",
        parent=body,
        fontSize=7.2,
        leading=10,
        textColor=colors.HexColor(MUTED),
    )
    table_head = ParagraphStyle(
        "MSPTableHead",
        parent=small,
        fontSize=7,
        leading=9,
        textColor=colors.white,
        alignment=align,
    )
    metric_value = ParagraphStyle(
        "MSPMetric",
        parent=body,
        fontSize=12,
        leading=14,
        textColor=colors.HexColor(NAVY),
        alignment=TA_CENTER,
    )
    cover_meta = ParagraphStyle(
        "MSPCoverMeta",
        parent=body,
        fontSize=10,
        leading=15,
        textColor=colors.white,
        alignment=align,
    )

    class RadarProfile(Flowable):
        def __init__(self, dimensions, width=79 * mm, height=72 * mm):
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
            radius = min(self.width, self.height) * 0.31
            canvas.saveState()
            for ring in (0.25, 0.5, 0.75, 1.0):
                points = []
                for index in range(count):
                    angle = math.pi / 2 - 2 * math.pi * index / count
                    points.extend(
                        (cx + radius * ring * math.cos(angle), cy + radius * ring * math.sin(angle))
                    )
                canvas.setStrokeColor(colors.HexColor(LINE))
                canvas.setLineWidth(0.45)
                path = canvas.beginPath()
                path.moveTo(points[0], points[1])
                for index in range(2, len(points), 2):
                    path.lineTo(points[index], points[index + 1])
                path.close()
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
                canvas.setFont(font_name, 5.8)
                label = display(item.get("label") or "")
                if math.cos(angle) > 0.25:
                    canvas.drawString(lx, ly, label)
                elif math.cos(angle) < -0.25:
                    canvas.drawRightString(lx, ly, label)
                else:
                    canvas.drawCentredString(lx, ly, label)
                canvas.setFillColor(colors.HexColor(TEAL_DARK))
                canvas.setFont(font_name, 6.5)
                canvas.drawCentredString(
                    cx + (radius + 3 * mm) * math.cos(angle),
                    cy + (radius + 3 * mm) * math.sin(angle),
                    str(round(float(item.get("score") or 0))),
                )
            path = canvas.beginPath()
            path.moveTo(*values[0])
            for point in values[1:]:
                path.lineTo(*point)
            path.close()
            canvas.setFillColor(colors.Color(0.075, 0.72, 0.65, alpha=0.26))
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

    def bullet_list(items, accent=TEAL_DARK):
        flows = []
        for item in items:
            flows.append(
                Table(
                    [["", p(item, body)]],
                    colWidths=[3 * mm, 166 * mm],
                    style=TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor(accent)),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (0, 0), 0),
                            ("RIGHTPADDING", (0, 0), (0, 0), 0),
                            ("TOPPADDING", (0, 0), (-1, -1), 3),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ]
                    ),
                )
            )
        return flows

    def info_card(label, value, color=TEAL_DARK):
        return Table(
            [[p(label, small)], [p(value, metric_value)]],
            colWidths=[53 * mm],
            rowHeights=[8 * mm, 13 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F8FA")),
                    ("LINEABOVE", (0, 0), (-1, 0), 2.2, colors.HexColor(color)),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(LINE)),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            ),
        )

    def standard_table(rows, widths, header=True, font_size=7.2):
        style = TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor(LINE)),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F8FA")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
        if not header:
            style.add("BACKGROUND", (0, 0), (-1, 0), colors.white)
        return Table(rows, colWidths=widths, repeatRows=1 if header else 0, style=style)

    analysis = getattr(report, "analysis_payload", None) or {}
    narrative = analysis.get("narrative") or {}
    player = analysis.get("player") or {}
    confidence = analysis.get("confidence") or {}
    match = getattr(report, "match", None)
    subscription = getattr(report, "subscription", None)
    player_obj = getattr(subscription, "player", None)
    player_name = player.get("name") or getattr(player_obj, "name", "")
    fixture = ""
    if match:
        fixture = f"{getattr(match, 'home_team', '')} {getattr(match, 'score', '–')} {getattr(match, 'away_team', '')}".strip()

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
    story.extend((Spacer(1, 22 * mm),))
    cover_rows = [
        [p(copy["role"], cover_kicker), p(player.get("role_label") or player.get("position") or "—", cover_meta)],
        [p(copy["minutes"], cover_kicker), p(player.get("minutes", "—"), cover_meta)],
        [p(copy["confidence"], cover_kicker), p(confidence.get("label") or "—", cover_meta)],
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
                section_title(copy["executive"], 1),
                p(getattr(report, "executive_summary", "") or copy["unavailable"], body_bold),
                Spacer(1, 5 * mm),
                p(copy["unavailable"], body),
            )
        )
    else:
        story.extend(
            (
                section_title(copy["executive"], 1),
                Table(
                    [[p(narrative.get("executive_summary") or getattr(report, "executive_summary", ""), body_bold)]],
                    colWidths=[169 * mm],
                    style=TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(PALE)),
                            ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor(TEAL_DARK)),
                            ("LEFTPADDING", (0, 0), (-1, -1), 9),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                            ("TOPPADDING", (0, 0), (-1, -1), 9),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                        ]
                    ),
                ),
                Spacer(1, 5 * mm),
                Table(
                    [[
                        info_card(copy["minutes"], player.get("minutes", "—")),
                        info_card(copy["confidence"], confidence.get("label") or "—", AMBER if confidence.get("score", 0) < 70 else TEAL_DARK),
                        info_card(copy["index"], player.get("index") if player.get("index") is not None else "—"),
                    ]],
                    colWidths=[56 * mm, 56 * mm, 56 * mm],
                    style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 1), ("RIGHTPADDING", (0, 0), (-1, -1), 1)]),
                ),
                Spacer(1, 6 * mm),
                section_title(copy["role_profile"], 2),
            )
        )
        dimensions = analysis.get("dimensions") or []
        role_rows = [[RadarProfile(dimensions), None]]
        dimension_table = [[p(item.get("label"), small), p(f"{item.get('score', 0)}/100", body_bold)] for item in dimensions]
        role_rows[0][1] = Table(
            dimension_table,
            colWidths=[52 * mm, 22 * mm],
            style=TableStyle(
                [
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#F5F8FA"), colors.white]),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor(LINE)),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            ),
        )
        story.append(Table(role_rows, colWidths=[88 * mm, 81 * mm], style=TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")])) )
        story.append(p(copy["role_note"], small))
        story.append(PageBreak())

        story.extend((section_title(copy["key_metrics"], 3), p(copy["per90_note"], small), Spacer(1, 3 * mm)))
        metric_rows = [[p(item.get("label"), table_head), p("VALEUR", table_head), p("PERCENTILE", table_head)] for item in []]
        metric_rows = [[p(copy["key_metrics"], table_head), p(copy["target"], table_head), p(copy["profile"], table_head)]]
        for item in analysis.get("key_metrics") or []:
            percentile = item.get("percentile")
            metric_rows.append([
                p(item.get("label"), small),
                p(item.get("display"), body_bold),
                p("—" if percentile is None else f"P{percentile}", body),
            ])
        story.append(standard_table(metric_rows, [97 * mm, 35 * mm, 37 * mm]))
        story.extend((Spacer(1, 6 * mm), section_title(copy["compartment"], 4)))
        peer_rows = [[p(copy["player"], table_head), p(copy["position"], table_head), p(copy["minutes"], table_head), p(copy["profile"], table_head)]]
        player_profile = player.get("profile_score")
        peer_rows.append([
            p(player_name, body_bold),
            p(player.get("position"), body),
            p(player.get("minutes"), body),
            p("—" if player_profile is None else f"{player_profile}/100", body_bold),
        ])
        for peer in analysis.get("same_compartment") or []:
            peer_rows.append([
                p(peer.get("name"), body), p(peer.get("position"), body), p(peer.get("minutes"), body),
                p("—" if peer.get("profile_score") is None else f"{peer.get('profile_score')}/100", body),
            ])
        story.append(standard_table(peer_rows, [83 * mm, 30 * mm, 25 * mm, 31 * mm]))
        story.append(PageBreak())

        story.append(section_title(copy["matchups"], 5))
        for matchup in analysis.get("matchups") or []:
            story.extend((p(matchup.get("title"), h2), p(" · ".join(matchup.get("players") or []), small)))
            rows = [[p(copy["key_metrics"], table_head), p(copy["target"], table_head), p(copy["opponent"], table_head)]]
            for item in matchup.get("metrics") or []:
                rows.append([p(item.get("label"), small), p(item.get("target_display"), body_bold), p(item.get("opponent_display"), body)])
            story.extend((standard_table(rows, [97 * mm, 36 * mm, 36 * mm]), Spacer(1, 5 * mm)))
        story.append(PageBreak())

        story.extend((section_title(copy["units"], 6), p(copy["unit_explanation"], small), Spacer(1, 3 * mm)))
        for unit in analysis.get("unit_comparisons") or []:
            teams = unit.get("teams") or []
            if len(teams) < 2:
                continue
            rows = [[p(unit.get("label"), table_head), p(teams[0], table_head), p(teams[1], table_head)]]
            for item in unit.get("metrics") or []:
                display_values = item.get("display") or {}
                rows.append([p(item.get("label"), small), p(display_values.get(teams[0], "—"), body), p(display_values.get(teams[1], "—"), body)])
            block = [p(unit.get("verdict"), h2), standard_table(rows, [93 * mm, 38 * mm, 38 * mm])]
            story.extend((KeepTogether(block), Spacer(1, 4 * mm)))
        story.append(PageBreak())

        story.append(section_title(copy["strengths"], 7))
        story.extend(bullet_list(narrative.get("strengths") or [], TEAL_DARK))
        story.extend((Spacer(1, 3 * mm), section_title(copy["risks"], 8)))
        story.extend(bullet_list(narrative.get("risks") or [], RED))
        story.extend((Spacer(1, 3 * mm), section_title(copy["development"], 9)))
        story.extend(bullet_list(narrative.get("development") or [], AMBER))

    stats = getattr(match, "player_stats", None) if match else None
    images = []
    for label, binary in (
        (copy["heatmap"], getattr(stats, "heatmap_png", None) if stats else None),
        (copy["touches"], getattr(stats, "ball_touches_png", None) if stats else None),
    ):
        if binary:
            raw = bytes(binary)
            image = Image(io.BytesIO(raw), width=81 * mm, height=54 * mm, kind="proportional")
            images.append((label, image))
    if images:
        story.extend((PageBreak(), section_title(copy["maps"], 10)))
        cells = []
        for label, image in images:
            cells.append(Table([[p(label, h2)], [image]], colWidths=[82 * mm], style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")])) )
        story.append(Table([cells], colWidths=[84 * mm for _ in cells], style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")])) )

    story.extend((PageBreak(), section_title(copy["method"], 11), p(copy["method_text"], body), Spacer(1, 3 * mm)))
    if confidence.get("explanation"):
        story.append(Table([[p(confidence.get("explanation"), body_bold)]], colWidths=[169 * mm], style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF7E6")), ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor(AMBER)), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)])))
        story.append(Spacer(1, 4 * mm))
    story.extend((p(copy["video_limit"], body), Spacer(1, 6 * mm), p(copy["source"], h2)))
    for source in analysis.get("methodology_sources") or []:
        hostname = urlparse(str(source.get("url") or "")).netloc
        story.append(p(f"{source.get('name')} — {hostname}", small))
        story.append(Spacer(1, 1 * mm))
    story.extend((Spacer(1, 12 * mm), p(copy["prepared"], body_bold)))

    document.build(story, onFirstPage=first_page, onLaterPages=later_pages)
    return buffer.getvalue()
