import mimetypes
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


DEFAULT_MAX_ATTACHMENT_MB = 20


def _env(*names, default=""):
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def send_all_actions_email(*, recipient, player_name, match_label, video_path):
    """Send one All Actions file from the local agent without exposing credentials."""
    video_path = Path(video_path)
    if not recipient:
        return False, "Aucune adresse e-mail n’est renseignée pour ce joueur."
    if not video_path.is_file():
        return False, "Le fichier All Actions téléchargé est introuvable."

    max_mb = int(_env("SPORTSBASE_EMAIL_MAX_ATTACHMENT_MB", default=str(DEFAULT_MAX_ATTACHMENT_MB)))
    size_mb = video_path.stat().st_size / (1024 * 1024)
    if size_mb > max_mb:
        return (
            False,
            f"Fichier conservé localement ({size_mb:.1f} Mo) : la limite e-mail est {max_mb} Mo.",
        )

    host = _env("SPORTSBASE_SMTP_HOST", "EMAIL_HOST")
    username = _env("SPORTSBASE_SMTP_USER", "EMAIL_HOST_USER")
    password = _env("SPORTSBASE_SMTP_PASSWORD", "EMAIL_HOST_PASSWORD")
    sender = _env("SPORTSBASE_EMAIL_FROM", "DEFAULT_FROM_EMAIL", default=username)
    port = int(_env("SPORTSBASE_SMTP_PORT", "EMAIL_PORT", default="587"))
    use_tls = _env("SPORTSBASE_SMTP_USE_TLS", "EMAIL_USE_TLS", default="true").lower() in {
        "1",
        "true",
        "yes",
    }
    if not host or not sender:
        return False, "Configuration SMTP SportsBase absente sur le PC local."

    message = EmailMessage()
    message["Subject"] = f"MS Football — All Actions — {match_label}"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        "Bonjour {name},\n\n"
        "Votre compilation All Actions est disponible en pièce jointe pour le match "
        "{match}.\n\nMS Football".format(name=player_name, match=match_label)
    )

    mime_type, _encoding = mimetypes.guess_type(video_path.name)
    maintype, subtype = (mime_type or "video/mp4").split("/", 1)
    with video_path.open("rb") as handle:
        message.add_attachment(
            handle.read(),
            maintype=maintype,
            subtype=subtype,
            filename=video_path.name,
        )

    try:
        with smtplib.SMTP(host, port, timeout=60) as smtp:
            if use_tls:
                smtp.starttls()
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        return False, f"Échec de l’envoi e-mail : {exc}"
    return True, ""
