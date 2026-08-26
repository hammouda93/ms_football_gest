"""Editable performance reports and dynamic PDF rendering."""

import io
import re
from collections import defaultdict
from html import escape
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMessage
from django.urls import reverse
from django.utils import timezone

from .models import (
    PerformanceReport,
    SportsBaseMatch,
    SportsBaseSubscription,
    SportsBaseYouTubeUpload,
)


COPY = {
    "fr": {
        "match_title": "Rapport de performance — {fixture}",
        "cycle_title": "Bilan de performance — cycle {cycle}",
        "summary": "Synthèse de l’analyste",
        "strengths": "Points forts",
        "improvements": "Axes de progression",
        "notes": "Observations de l’analyste",
        "metrics": "Indicateurs clés",
        "prepared": "Rapport préparé par l’équipe d’analyse MS Performance",
        "match_summary": (
            "Cette analyse met en perspective le volume d’activité, l’efficacité "
            "technique et l’implication du joueur pendant la rencontre."
        ),
        "cycle_summary": (
            "Ce bilan regroupe cinq matchs consécutifs afin d’identifier les tendances "
            "de performance et les priorités du prochain cycle de travail."
        ),
        "no_strength": "Les données disponibles seront consolidées lors des prochaines rencontres.",
        "no_improvement": "Maintenir la régularité et continuer à enrichir les prises de décision.",
        "mail_subject": "Votre match a été analysé — MS Performance",
        "mail_intro": "Votre dernière rencontre a été traitée par notre équipe.",
        "watch": "Regarder All Actions",
        "report": "Télécharger le rapport de l’analyste",
    },
    "en": {
        "match_title": "Performance report — {fixture}",
        "cycle_title": "Performance review — cycle {cycle}",
        "summary": "Analyst summary",
        "strengths": "Strengths",
        "improvements": "Development priorities",
        "notes": "Analyst observations",
        "metrics": "Key indicators",
        "prepared": "Report prepared by the MS Performance analysis team",
        "match_summary": (
            "This analysis puts the player’s activity volume, technical efficiency "
            "and involvement during the match into context."
        ),
        "cycle_summary": (
            "This review combines five consecutive matches to identify performance "
            "trends and priorities for the next development cycle."
        ),
        "no_strength": "Available data will be consolidated over the next matches.",
        "no_improvement": "Maintain consistency and continue improving decision-making.",
        "mail_subject": "Your match has been analysed — MS Performance",
        "mail_intro": "Your latest match has been processed by our team.",
        "watch": "Watch All Actions",
        "report": "Download the analyst report",
    },
    "ar": {
        "match_title": "تقرير الأداء — {fixture}",
        "cycle_title": "تقييم الأداء — الدورة {cycle}",
        "summary": "ملخص المحلل",
        "strengths": "نقاط القوة",
        "improvements": "محاور التطوير",
        "notes": "ملاحظات المحلل",
        "metrics": "المؤشرات الرئيسية",
        "prepared": "تم إعداد التقرير من طرف فريق التحليل MS Performance",
        "match_summary": "يضع هذا التحليل حجم النشاط والنجاعة الفنية ومساهمة اللاعب خلال المباراة في سياق واضح.",
        "cycle_summary": "يجمع هذا التقييم خمس مباريات متتالية لتحديد تطور الأداء وأولويات دورة العمل القادمة.",
        "no_strength": "سيتم تعزيز القراءة بالمزيد من البيانات خلال المباريات القادمة.",
        "no_improvement": "المحافظة على الاستمرارية ومواصلة تطوير جودة اتخاذ القرار.",
        "mail_subject": "تم تحليل مباراتك — MS Performance",
        "mail_intro": "تمت معالجة مباراتك الأخيرة من طرف فريقنا.",
        "watch": "مشاهدة جميع اللقطات",
        "report": "تحميل تقرير المحلل",
    },
}


METRIC_LABELS = {
    "fr": {
        "Minutes played": "Minutes jouées",
        "Passes": "Passes",
        "Passes accurate, %": "Passes réussies",
        "Challenges": "Duels",
        "Challenges won, %": "Duels gagnés",
        "Shots": "Tirs",
        "Shots on target, %": "Tirs cadrés",
        "Key passes": "Passes clés",
        "Dribbles": "Dribbles",
        "Dribbles successful, %": "Dribbles réussis",
        "Tackles": "Tacles",
        "Tackles successful, %": "Tacles réussis",
        "Goals": "Buts",
        "Assists": "Passes décisives",
        "Index": "Index",
    },
    "en": {},
    "ar": {
        "Minutes played": "دقائق اللعب",
        "Passes": "التمريرات",
        "Passes accurate, %": "دقة التمرير",
        "Challenges": "الثنائيات",
        "Challenges won, %": "الثنائيات الناجحة",
        "Shots": "التسديدات",
        "Shots on target, %": "التسديدات المؤطرة",
        "Key passes": "التمريرات المفتاحية",
        "Dribbles": "المراوغات",
        "Dribbles successful, %": "المراوغات الناجحة",
        "Tackles": "التدخلات",
        "Tackles successful, %": "التدخلات الناجحة",
        "Goals": "الأهداف",
        "Assists": "التمريرات الحاسمة",
        "Index": "المؤشر",
    },
}


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    normalized = str(value).strip().replace("%", "").replace(",", ".")
    if normalized.casefold() in {"", "-", "–", "none", "null", "nan"}:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    return float(match.group()) if match else None


def _match_metrics(match):
    try:
        stats = match.player_stats
    except Exception:
        return {}
    metrics = {}
    for collection in (
        stats.summary_statistics,
        stats.success_rates,
        stats.detailed_statistics,
    ):
        if isinstance(collection, dict):
            metrics.update(collection)
    if stats.minutes_played is not None:
        metrics.setdefault("Minutes played", stats.minutes_played)
    if stats.index is not None:
        metrics.setdefault("Index", stats.index)
    return metrics


def _bullets(lines):
    return "\n".join(f"• {line}" for line in lines)


def _metric_label(name, language):
    return METRIC_LABELS.get(language, {}).get(name, name)


def _match_observations(metrics, language):
    strengths = []
    improvements = []
    passes = _number(metrics.get("Passes"))
    pass_rate = _number(metrics.get("Passes accurate, %"))
    duels = _number(metrics.get("Challenges"))
    duel_rate = _number(metrics.get("Challenges won, %"))
    shots = _number(metrics.get("Shots"))
    shot_rate = _number(metrics.get("Shots on target, %"))
    key_passes = _number(metrics.get("Key passes"))

    if language == "en":
        if pass_rate is not None and pass_rate >= 85:
            strengths.append(f"Reliable ball circulation with {pass_rate:.0f}% pass accuracy.")
        elif passes and pass_rate is not None and pass_rate < 70:
            improvements.append("Secure simple passing options before accelerating play.")
        if duel_rate is not None and duel_rate >= 60:
            strengths.append(f"Positive impact in duels ({duel_rate:.0f}% won).")
        elif duels and duel_rate is not None and duel_rate < 45:
            improvements.append("Improve body position and timing before engaging in duels.")
        if key_passes and key_passes >= 2:
            strengths.append("Created valuable situations through key passes.")
        if shots and shot_rate is not None and shot_rate < 35:
            improvements.append("Improve shot selection and preparation before finishing.")
    elif language == "ar":
        if pass_rate is not None and pass_rate >= 85:
            strengths.append(f"استمرارية جيدة في تداول الكرة بدقة تمرير بلغت {pass_rate:.0f}٪.")
        elif passes and pass_rate is not None and pass_rate < 70:
            improvements.append("تأمين خيارات التمرير البسيطة قبل تسريع اللعب.")
        if duel_rate is not None and duel_rate >= 60:
            strengths.append(f"تأثير إيجابي في الثنائيات بنسبة نجاح {duel_rate:.0f}٪.")
        elif duels and duel_rate is not None and duel_rate < 45:
            improvements.append("تطوير وضعية الجسم وتوقيت الدخول في الثنائيات.")
        if key_passes and key_passes >= 2:
            strengths.append("خلق وضعيات مفيدة عبر تمريرات مفتاحية.")
        if shots and shot_rate is not None and shot_rate < 35:
            improvements.append("تحسين اختيار وضعية التسديد والتحضير قبل الإنهاء.")
    else:
        if pass_rate is not None and pass_rate >= 85:
            strengths.append(f"Circulation fiable avec {pass_rate:.0f} % de passes réussies.")
        elif passes and pass_rate is not None and pass_rate < 70:
            improvements.append("Sécuriser les solutions simples avant d’accélérer le jeu.")
        if duel_rate is not None and duel_rate >= 60:
            strengths.append(f"Impact positif dans les duels ({duel_rate:.0f} % gagnés).")
        elif duels and duel_rate is not None and duel_rate < 45:
            improvements.append("Améliorer le placement du corps et le timing avant le duel.")
        if key_passes and key_passes >= 2:
            strengths.append("Création de situations utiles grâce aux passes clés.")
        if shots and shot_rate is not None and shot_rate < 35:
            improvements.append("Améliorer la sélection et la préparation des tirs.")
    return strengths, improvements


def generate_match_report(match):
    language = match.subscription.report_language
    copy = COPY[language]
    fixture = f"{match.home_team} {match.score} {match.away_team}".strip()
    metrics = _match_metrics(match)
    strengths, improvements = _match_observations(metrics, language)
    defaults = {
        "subscription": match.subscription,
        "report_type": PerformanceReport.ReportType.MATCH,
        "cycle_number": None,
        "language": language,
        "status": PerformanceReport.Status.PUBLISHED,
        "title": copy["match_title"].format(fixture=fixture),
        "executive_summary": copy["match_summary"],
        "strengths": _bullets(strengths or [copy["no_strength"]]),
        "improvement_areas": _bullets(improvements or [copy["no_improvement"]]),
        "metrics": metrics,
        "match_ids": [match.sportsbase_match_id],
        "generated_at": timezone.now(),
        "published_at": timezone.now(),
    }
    report, created = PerformanceReport.objects.get_or_create(
        match=match,
        defaults=defaults,
    )
    if not created:
        report.language = language
        report.metrics = metrics
        report.match_ids = [match.sportsbase_match_id]
        report.generated_at = timezone.now()
        fields = ["language", "metrics", "match_ids", "generated_at", "updated_at"]
        if not report.is_manually_edited:
            for field, value in defaults.items():
                if field not in {"subscription", "report_type", "cycle_number"}:
                    setattr(report, field, value)
            fields.extend(
                (
                    "language",
                    "status",
                    "title",
                    "executive_summary",
                    "strengths",
                    "improvement_areas",
                    "published_at",
                )
            )
        report.save(update_fields=tuple(dict.fromkeys(fields)))
    return report


def _cycle_metrics(matches):
    values = defaultdict(list)
    for match in matches:
        for name, value in _match_metrics(match).items():
            number = _number(value)
            if number is not None:
                values[name].append(number)
    averages = {}
    for name, numbers in values.items():
        averages[name] = round(sum(numbers) / len(numbers), 1)
    return averages


def generate_cycle_reports(subscription):
    matches = list(
        subscription.matches.filter(
            sync_state=SportsBaseMatch.SyncState.SYNCED,
            player_stats__isnull=False,
        )
        .select_related("player_stats")
        .order_by("match_date", "sportsbase_match_id")
    )
    generated = []
    complete_cycles = len(matches) // 5
    copy = COPY[subscription.report_language]
    for cycle_index in range(complete_cycles):
        cycle_number = cycle_index + 1
        group = matches[cycle_index * 5 : (cycle_index + 1) * 5]
        metrics = _cycle_metrics(group)
        strengths, improvements = _match_observations(metrics, subscription.report_language)
        defaults = {
            "language": subscription.report_language,
            "status": PerformanceReport.Status.PUBLISHED,
            "title": copy["cycle_title"].format(cycle=cycle_number),
            "executive_summary": copy["cycle_summary"],
            "strengths": _bullets(strengths or [copy["no_strength"]]),
            "improvement_areas": _bullets(improvements or [copy["no_improvement"]]),
            "metrics": metrics,
            "match_ids": [match.sportsbase_match_id for match in group],
            "generated_at": timezone.now(),
            "published_at": timezone.now(),
        }
        report, created = PerformanceReport.objects.get_or_create(
            subscription=subscription,
            report_type=PerformanceReport.ReportType.CYCLE,
            cycle_number=cycle_number,
            defaults=defaults,
        )
        if not created:
            report.language = subscription.report_language
            report.metrics = metrics
            report.match_ids = defaults["match_ids"]
            report.generated_at = timezone.now()
            fields = [
                "language",
                "metrics",
                "match_ids",
                "generated_at",
                "updated_at",
            ]
            if not report.is_manually_edited:
                for field, value in defaults.items():
                    setattr(report, field, value)
                fields.extend(
                    (
                        "language",
                        "status",
                        "title",
                        "executive_summary",
                        "strengths",
                        "improvement_areas",
                        "published_at",
                    )
                )
            report.save(update_fields=tuple(dict.fromkeys(fields)))
        generated.append(report)
    return generated


def generate_reports_for_subscription(subscription):
    reports = []
    matches = subscription.matches.filter(
        sync_state=SportsBaseMatch.SyncState.SYNCED,
        player_stats__isnull=False,
    )
    for match in matches.select_related("player_stats"):
        reports.append(generate_match_report(match))
    reports.extend(generate_cycle_reports(subscription))
    return reports


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


def render_report_pdf(report):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    language = report.language if report.language in COPY else "fr"
    copy = COPY[language]
    rtl = language == "ar"
    font_name = "Helvetica"
    font_path = _font_path()
    if font_path:
        font_name = "MSPerformanceUnicode"
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, str(font_path)))

    def display(value):
        value = str(value or "")
        return _rtl(value) if rtl else value

    def paragraph_text(value):
        lines = [escape(display(line)) for line in str(value or "").splitlines()]
        return "<br/>".join(lines)

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=report.title,
        author="MS Performance",
    )
    styles = getSampleStyleSheet()
    alignment = TA_RIGHT if rtl else TA_LEFT
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=20,
        leading=25,
        textColor=colors.HexColor("#071827"),
        alignment=alignment,
        spaceAfter=10,
    )
    heading_style = ParagraphStyle(
        "ReportHeading",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#0D9488"),
        alignment=alignment,
        spaceBefore=10,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "ReportBody",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=9.5,
        leading=15,
        textColor=colors.HexColor("#25364D"),
        alignment=alignment,
    )
    small_style = ParagraphStyle(
        "ReportSmall",
        parent=body_style,
        fontSize=8,
        textColor=colors.HexColor("#68768B"),
    )

    story = [
        Paragraph("MS PERFORMANCE", heading_style),
        Paragraph(paragraph_text(report.title), title_style),
        Paragraph(
            paragraph_text(report.subscription.player.name),
            ParagraphStyle("Player", parent=body_style, fontSize=12, leading=16),
        ),
        Spacer(1, 5 * mm),
    ]
    if report.report_type == PerformanceReport.ReportType.MATCH and report.match:
        match = report.match
        match_line = f"{match.home_team} {match.score} {match.away_team}"
        if match.match_date:
            match_line += f" · {match.match_date.strftime('%d/%m/%Y')}"
        story.append(
            Table(
                [[Paragraph(paragraph_text(match_line), body_style)]],
                colWidths=[174 * mm],
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EEF7F7")),
                        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#B7DDDA")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                        ("TOPPADDING", (0, 0), (-1, -1), 9),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                    ]
                ),
            )
        )

    sections = (
        (copy["summary"], report.executive_summary),
        (copy["strengths"], report.strengths),
        (copy["improvements"], report.improvement_areas),
        (copy["notes"], report.analyst_notes),
    )
    for heading, content in sections:
        if not content:
            continue
        story.extend(
            (
                Paragraph(display(heading), heading_style),
                Paragraph(paragraph_text(content), body_style),
            )
        )

    if report.metrics:
        metric_rows = []
        for name, value in list(report.metrics.items())[:24]:
            metric_rows.append(
                [
                    Paragraph(paragraph_text(_metric_label(name, language)), small_style),
                    Paragraph(paragraph_text(value), body_style),
                ]
            )
        story.append(Paragraph(display(copy["metrics"]), heading_style))
        story.append(
            Table(
                metric_rows,
                colWidths=[128 * mm, 46 * mm],
                repeatRows=0,
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F5F8FB")),
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#DCE4ED")),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                ),
            )
        )

    story.append(Spacer(1, 8 * mm))
    story.append(
        KeepTogether(
            [
                Paragraph(display(copy["prepared"]), small_style),
                Paragraph(
                    display(report.updated_at.strftime("%d/%m/%Y · %H:%M")),
                    small_style,
                ),
            ]
        )
    )
    document.build(story)
    return buffer.getvalue()


def send_ready_delivery_notification(upload):
    upload = SportsBaseYouTubeUpload.objects.select_related(
        "match__subscription__player", "match__performance_report"
    ).get(pk=upload.pk)
    if upload.notification_sent_at or upload.status != SportsBaseYouTubeUpload.Status.UPLOADED:
        return False
    try:
        report = upload.match.performance_report
    except PerformanceReport.DoesNotExist:
        return False
    if report.status != PerformanceReport.Status.PUBLISHED:
        return False
    recipient = (upload.match.subscription.player.email or "").strip()
    if not recipient:
        upload.notification_error = "Aucune adresse e-mail n’est renseignée pour ce joueur."
        upload.save(update_fields=("notification_error", "updated_at"))
        return False

    language = report.language if report.language in COPY else "fr"
    copy = COPY[language]
    base_url = getattr(
        settings,
        "PUBLIC_SITE_URL",
        "https://msfootball-1a882b44ed52.herokuapp.com",
    ).rstrip("/")
    report_url = base_url + reverse("performance:report_pdf", args=(report.pk,))
    body = "\n\n".join(
        (
            copy["mail_intro"],
            f"{copy['watch']} : {upload.youtube_url}",
            f"{copy['report']} : {report_url}",
            "MS Performance",
        )
    )
    message = EmailMessage(
        subject=copy["mail_subject"],
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    try:
        sent = bool(message.send(fail_silently=False))
    except Exception as exc:
        upload.notification_error = str(exc)
        upload.save(update_fields=("notification_error", "updated_at"))
        return False
    if sent:
        upload.notification_sent_at = timezone.now()
        upload.notification_error = ""
        upload.save(
            update_fields=("notification_sent_at", "notification_error", "updated_at")
        )
    return sent
