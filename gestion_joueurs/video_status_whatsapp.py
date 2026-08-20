import re
from decimal import Decimal
from urllib.parse import quote

from django.utils import timezone

from .models import Invoice, Video


PAYMENT_MODE_CHOICES = (
    ("auto", "Selon le paiement enregistré"),
    ("advance", "Parler de l’avance"),
    ("full", "Demander le paiement total ou le solde"),
    ("none", "Ne pas parler du paiement"),
)

NOTIFICATION_PAYMENT_MODES = {
    "pending_payment": "full",
    "pending_check": "advance",
    "start_editing": "auto",
    "inprogress_payment": "full",
    "inprogress_check": "advance",
    "todelivered_change": "auto",
    "completed_unpaid": "full",
    "deadline_passed": "auto",
    "delivered_unpaid": "full",
}

NOTIFICATION_STATUS_OVERRIDES = {
    "pending_payment": Video.StatusChoices.PENDING,
    "pending_check": Video.StatusChoices.PENDING,
    "start_editing": Video.StatusChoices.PENDING,
    "todelivered_change": Video.StatusChoices.COMPLETED,
    "completed_unpaid": Video.StatusChoices.COMPLETED,
    "delivered_unpaid": Video.StatusChoices.DELIVERED,
}

NON_PLAYER_NOTIFICATION_TYPES = {
    "birthday",
    "financial_report",
    "p_paid_salary",
    "unpaid_salary",
    "video_count",
}


def _decimal(value):
    return Decimal(value or 0).quantize(Decimal("0.01"))


def _format_amount(value):
    formatted = format(_decimal(value), "f").rstrip("0").rstrip(".")
    return (formatted or "0").replace(".", ",")


def get_payment_snapshot(video):
    """Return the current financial state, using the invoice as source of truth."""
    try:
        invoice = video.invoices
    except Invoice.DoesNotExist:
        invoice = None

    if invoice:
        total = _decimal(invoice.total_amount)
        amount_paid = _decimal(invoice.amount_paid)
    else:
        total = _decimal(video.total_payment)
        amount_paid = _decimal(video.advance_payment)

    remaining = max(total - amount_paid, Decimal("0.00"))

    if total > 0 and remaining == 0:
        status = "paid"
        status_label = "Payé intégralement"
    elif amount_paid > 0:
        status = "partially_paid"
        status_label = "Avance / paiement partiel enregistré"
    else:
        status = "unpaid"
        status_label = "Aucun paiement enregistré"

    return {
        "status": status,
        "status_label": status_label,
        "total": total,
        "amount_paid": amount_paid,
        "remaining": remaining,
        "total_display": _format_amount(total),
        "amount_paid_display": _format_amount(amount_paid),
        "remaining_display": _format_amount(remaining),
    }


def _recommended_payment_mode(status, payment_snapshot):
    if status == Video.StatusChoices.PROBLEMATIC:
        return "none", "Ne pas mentionner le paiement"

    if payment_snapshot["status"] == "paid":
        return "full", "Confirmer que le paiement total est reçu"

    if status in (Video.StatusChoices.COMPLETED, Video.StatusChoices.DELIVERED):
        if payment_snapshot["status"] == "partially_paid":
            return "full", "Demander le solde avant la livraison"
        return "full", "Demander le paiement total avant la livraison"

    if payment_snapshot["status"] == "partially_paid":
        return "full", "Confirmer l’avance reçue et rappeler le solde"

    return "advance", "Demander l’avance convenue"


def _payment_paragraph(payment_snapshot, payment_mode, video_status):
    if payment_mode == "none":
        return ""

    payment_status = payment_snapshot["status"]

    if payment_status == "paid":
        return "Le paiement total a bien été reçu. Merci."

    if payment_mode == "advance":
        if payment_status == "partially_paid":
            if video_status == Video.StatusChoices.DELIVERED:
                return (
                    "Une avance a bien été enregistrée, mais le solde reste à régler."
                )
            return (
                "Ton avance a bien été enregistrée. "
                "Le solde restera à régler avant la livraison de la vidéo."
            )
        return (
            "Aucune avance n’est encore enregistrée. "
            "Merci de régler l’avance convenue."
        )

    if payment_status == "partially_paid":
        if video_status == Video.StatusChoices.DELIVERED:
            return "Une avance a bien été enregistrée, mais le solde reste à régler."
        return (
            "Ton avance a bien été enregistrée. "
            "Le solde reste à régler avant la livraison de la vidéo."
        )

    if video_status == Video.StatusChoices.DELIVERED:
        return (
            "La vidéo a été livrée, mais le paiement n’est pas encore enregistré. "
            "Merci de régulariser le montant convenu."
        )

    if video_status == Video.StatusChoices.COMPLETED:
        return (
            "La vidéo est terminée, mais le paiement n’est pas encore enregistré. "
            "Merci de régler le montant total avant la livraison."
        )

    return (
        "Le paiement total n’est pas encore enregistré. "
        "Merci de régler le montant convenu."
    )


def _status_paragraph(video, status, event_date=None):
    status_date = (event_date or timezone.localdate()).strftime("%d/%m/%Y")
    paragraphs = {
        Video.StatusChoices.PENDING: (
            f"Ta commande de vidéo pour la saison {video.season} "
            f"a bien été enregistrée le {status_date}."
        ),
        Video.StatusChoices.IN_PROGRESS: (
            f"Nous avons commencé le travail sur ta vidéo le {status_date}."
        ),
        Video.StatusChoices.COMPLETED_COLLAB: (
            f"Le premier montage de ta vidéo a été terminé le {status_date} "
            "et nous passons "
            "maintenant à la phase de finition."
        ),
        Video.StatusChoices.COMPLETED: (
            f"Ta vidéo est maintenant terminée depuis le {status_date}."
        ),
        Video.StatusChoices.DELIVERED: (
            f"Ta vidéo a été livrée le {status_date}."
        ),
        Video.StatusChoices.PROBLEMATIC: (
            f"Depuis la mise à jour du {status_date}, une vérification "
            "supplémentaire est nécessaire sur ta vidéo. "
            "Nous te contacterons pour préciser la suite."
        ),
    }
    return paragraphs.get(status, "Le statut de ta vidéo vient d’être mis à jour.")


def build_status_message(
    video,
    status,
    payment_snapshot,
    payment_mode="auto",
    event_date=None,
):
    if payment_mode == "auto":
        payment_mode, _label = _recommended_payment_mode(status, payment_snapshot)

    paragraphs = [
        f"Bonjour {video.player.name} 👋",
        _status_paragraph(video, status, event_date),
    ]

    if video.deadline and status not in (
        Video.StatusChoices.DELIVERED,
        Video.StatusChoices.PROBLEMATIC,
    ):
        formatted_deadline = video.deadline.strftime('%d/%m/%Y')
        if video.deadline < timezone.localdate():
            paragraphs.append(
                f"La date de livraison prévue était le {formatted_deadline} "
                "et elle est maintenant dépassée."
            )
        else:
            paragraphs.append(
                f"La date de livraison prévue est le {formatted_deadline}."
            )

    payment_paragraph = _payment_paragraph(payment_snapshot, payment_mode, status)
    if payment_paragraph:
        paragraphs.append(payment_paragraph)

    if status == Video.StatusChoices.DELIVERED and video.video_link:
        paragraphs.append(f"Voici le lien de la vidéo : {video.video_link}")

    paragraphs.append("Moataz — MS Football")
    return "\n\n".join(paragraphs)


def build_status_notification_context(video):
    payment_snapshot = get_payment_snapshot(video)
    messages = {}
    recommendations = {}

    for status, _label in Video.StatusChoices.choices:
        recommended_mode, recommendation_label = _recommended_payment_mode(
            status,
            payment_snapshot,
        )
        recommendations[status] = {
            "mode": recommended_mode,
            "label": recommendation_label,
        }
        messages[status] = {
            mode: build_status_message(video, status, payment_snapshot, mode)
            for mode, _mode_label in PAYMENT_MODE_CHOICES
        }

    return {
        "status_whatsapp_messages": messages,
        "status_payment_recommendations": recommendations,
        "payment_mode_choices": PAYMENT_MODE_CHOICES,
        "payment_snapshot": payment_snapshot,
        "player_has_whatsapp": bool(normalize_whatsapp_number(video.player.whatsapp_number)),
    }


def normalize_whatsapp_number(number):
    return re.sub(r"\D", "", number or "")


def build_whatsapp_url(number, message):
    phone_number = normalize_whatsapp_number(number)
    if not phone_number:
        return None
    return f"https://wa.me/{phone_number}?text={quote(message, safe='')}"


def build_notification_whatsapp_message(notification):
    """Build a player-facing message from an internal video notification."""
    video = getattr(notification, "video", None)
    player = getattr(notification, "player", None) or getattr(video, "player", None)
    notification_type = getattr(notification, "notification_type", "")

    if (
        not video
        or not player
        or notification_type in NON_PLAYER_NOTIFICATION_TYPES
        or not normalize_whatsapp_number(player.whatsapp_number)
    ):
        return ""

    payment_snapshot = get_payment_snapshot(video)
    status = NOTIFICATION_STATUS_OVERRIDES.get(notification_type, video.status)
    payment_mode = NOTIFICATION_PAYMENT_MODES.get(notification_type, "auto")
    notification_datetime = notification.sent_at or notification.created_at
    if timezone.is_aware(notification_datetime):
        notification_date = timezone.localtime(notification_datetime).date()
    else:
        notification_date = notification_datetime.date()

    return build_status_message(
        video,
        status,
        payment_snapshot,
        payment_mode,
        event_date=notification_date,
    )


def build_notification_whatsapp_url(notification):
    message = build_notification_whatsapp_message(notification)
    if not message:
        return None

    player = notification.player or notification.video.player
    return build_whatsapp_url(player.whatsapp_number, message)
