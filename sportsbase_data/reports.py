"""Editable performance reports and dynamic PDF rendering."""

import re
from collections import defaultdict

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from .analysis_engine import build_match_analysis
from .models import (
    PerformanceReport,
    SportsBaseMatch,
    SportsBaseSubscription,
    SportsBaseYouTubeUpload,
)
from .report_pdf import render_performance_pdf


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
        "mail_subject": "Votre rapport et vos All Actions sont prêts — MS Performance",
        "mail_intro": (
            "L’analyse de votre dernière rencontre est terminée. Votre rapport "
            "et votre vidéo All Actions sont disponibles dans votre espace joueur."
        ),
        "mail_subject_report_only": "Votre rapport de match est prêt — MS Performance",
        "mail_intro_report_only": (
            "L’analyse de votre dernière rencontre est terminée. Votre rapport "
            "est disponible dans votre espace joueur."
        ),
        "match": "Match",
        "watch": "Regarder All Actions",
        "portal_match": "Voir le match et All Actions dans votre portail",
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
        "mail_subject": "Your report and All Actions are ready — MS Performance",
        "mail_intro": (
            "The analysis of your latest match is complete. Your report and "
            "All Actions video are available in your player space."
        ),
        "mail_subject_report_only": "Your match report is ready — MS Performance",
        "mail_intro_report_only": (
            "The analysis of your latest match is complete. Your report is available "
            "in your player space."
        ),
        "match": "Match",
        "watch": "Watch All Actions",
        "portal_match": "View the match and All Actions in your portal",
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
        "mail_subject": "تقريرك وفيديو جميع اللقطات جاهزان — MS Performance",
        "mail_intro": (
            "اكتمل تحليل مباراتك الأخيرة. التقرير وفيديو جميع اللقطات متاحان الآن في مساحة اللاعب الخاصة بك."
        ),
        "mail_subject_report_only": "تقرير مباراتك جاهز — MS Performance",
        "mail_intro_report_only": (
            "اكتمل تحليل مباراتك الأخيرة. التقرير متاح الآن في مساحة اللاعب الخاصة بك."
        ),
        "match": "المباراة",
        "watch": "مشاهدة جميع اللقطات",
        "portal_match": "مشاهدة المباراة وجميع اللقطات في بوابتك",
        "report": "تحميل تقرير المحلل",
    },
}


METRIC_LABELS = {
    "fr": {
        "Minutes played": "Minutes jouées",
        "Matches played": "Matchs joués",
        "Time on the field, %": "Temps sur le terrain",
        "Passes": "Passes",
        "Passes accurate, %": "Passes réussies",
        "Challenges": "Duels",
        "Challenges won, %": "Duels gagnés",
        "Shots": "Tirs",
        "Shots on target, %": "Tirs cadrés",
        "Crosses": "Centres",
        "Crosses accurate, %": "Centres réussis",
        "Aerial challenges": "Duels aériens",
        "Aerial challenges won, %": "Duels aériens gagnés",
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
        "Matches played": "المباريات الملعوبة",
        "Time on the field, %": "نسبة الوقت على أرض الملعب",
        "Passes": "التمريرات",
        "Passes accurate, %": "دقة التمرير",
        "Challenges": "الثنائيات",
        "Challenges won, %": "الثنائيات الناجحة",
        "Shots": "التسديدات",
        "Shots on target, %": "التسديدات المؤطرة",
        "Crosses": "العرضيات",
        "Crosses accurate, %": "العرضيات الناجحة",
        "Aerial challenges": "الثنائيات الهوائية",
        "Aerial challenges won, %": "الثنائيات الهوائية الناجحة",
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
    analysis = build_match_analysis(match, language=language)
    if analysis.get("available"):
        narrative = analysis.get("narrative") or {}
        executive_summary = narrative.get("executive_summary") or copy[
            "match_summary"
        ]
        strengths = narrative.get("strengths") or []
        risks = narrative.get("risks") or []
        development = narrative.get("development") or []
        improvements = risks + development
    else:
        executive_summary = copy["match_summary"]
        strengths, improvements = _match_observations(metrics, language)
    defaults = {
        "subscription": match.subscription,
        "report_type": PerformanceReport.ReportType.MATCH,
        "cycle_number": None,
        "language": language,
        "status": PerformanceReport.Status.PUBLISHED,
        "title": copy["match_title"].format(fixture=fixture),
        "executive_summary": executive_summary,
        "strengths": _bullets(strengths or [copy["no_strength"]]),
        "improvement_areas": _bullets(improvements or [copy["no_improvement"]]),
        "metrics": metrics,
        "analysis_payload": analysis,
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
        report.analysis_payload = analysis
        report.match_ids = [match.sportsbase_match_id]
        report.generated_at = timezone.now()
        fields = [
            "language",
            "metrics",
            "analysis_payload",
            "match_ids",
            "generated_at",
            "updated_at",
        ]
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


def render_report_pdf(report):
    return render_performance_pdf(report)


def send_ready_delivery_notification(report):
    report = PerformanceReport.objects.select_related(
        "subscription__player", "match__youtube_upload"
    ).get(pk=report.pk)
    if (
        report.notification_sent_at
        or report.status != PerformanceReport.Status.PUBLISHED
        or report.report_type != PerformanceReport.ReportType.MATCH
        or not report.match_id
    ):
        return False

    subscription = report.subscription
    if not subscription.email_delivery_enabled:
        return False
    upload = None
    if subscription.youtube_delivery_enabled:
        try:
            upload = report.match.youtube_upload
        except SportsBaseYouTubeUpload.DoesNotExist:
            return False
        if (
            upload.status != SportsBaseYouTubeUpload.Status.UPLOADED
            or not upload.youtube_url
        ):
            return False
        # Les notifications envoyées avant cette migration étaient enregistrées
        # sur l'upload YouTube. On recopie ce marqueur pour éviter un doublon.
        if upload.notification_sent_at:
            report.notification_sent_at = upload.notification_sent_at
            report.notification_error = upload.notification_error
            report.save(
                update_fields=(
                    "notification_sent_at",
                    "notification_error",
                    "updated_at",
                )
            )
            return False

    recipient = (subscription.player.email or "").strip()
    if not recipient:
        report.notification_error = "Aucune adresse e-mail n’est renseignée pour ce joueur."
        report.save(update_fields=("notification_error", "updated_at"))
        return False

    language = report.language if report.language in COPY else "fr"
    copy = COPY[language]
    fixture = (
        f"{report.match.home_team} {report.match.score} "
        f"{report.match.away_team}"
    ).strip()
    if subscription.youtube_delivery_enabled:
        subject = f"{copy['mail_subject']} — {fixture}"
        body_parts = (
            copy["mail_intro"],
            f"{copy['match']} : {fixture}",
            "MS Performance",
        )
    else:
        subject = f"{copy['mail_subject_report_only']} — {fixture}"
        body_parts = (
            copy["mail_intro_report_only"],
            f"{copy['match']} : {fixture}",
            "MS Performance",
        )
    message = EmailMessage(
        subject=subject,
        body="\n\n".join(body_parts),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    try:
        sent = bool(message.send(fail_silently=False))
    except Exception as exc:
        report.notification_error = str(exc)
        report.save(update_fields=("notification_error", "updated_at"))
        if upload is not None:
            upload.notification_error = str(exc)
            upload.save(update_fields=("notification_error", "updated_at"))
        return False
    if sent:
        sent_at = timezone.now()
        report.notification_sent_at = sent_at
        report.notification_error = ""
        report.save(
            update_fields=(
                "notification_sent_at",
                "notification_error",
                "updated_at",
            )
        )
        if upload is not None:
            upload.notification_sent_at = sent_at
            upload.notification_error = ""
            upload.save(
                update_fields=(
                    "notification_sent_at",
                    "notification_error",
                    "updated_at",
                )
            )
    return sent
