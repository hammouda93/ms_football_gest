from __future__ import annotations

import base64
import calendar
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from gestion_joueurs.models import Video


SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
GOOGLE_SCOPES = (SHEETS_SCOPE, DRIVE_SCOPE)
SHEETS_API_ROOT = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE_API_ROOT = "https://www.googleapis.com/drive/v3/files"


class GoogleSheetError(RuntimeError):
    pass


@dataclass(frozen=True)
class OrganizationSheetSyncResult:
    row_count: int
    grand_total: Decimal
    spreadsheet_url: str


@dataclass(frozen=True)
class OrganizationSheetDeliveryResult:
    recipients: tuple[str, ...]
    shared_with: tuple[str, ...]
    permission_errors: tuple[str, ...]
    sync_result: OrganizationSheetSyncResult


def normalize_spreadsheet_reference(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    match = re.search(r"/spreadsheets/d/([^/?#]+)", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return value
    raise GoogleSheetError("Le lien ou l’ID Google Sheet n’est pas valide.")


def google_sheets_is_configured() -> bool:
    return bool(
        getattr(settings, "GOOGLE_SHEETS_ENABLED", False)
        and (
            getattr(settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "")
            or getattr(settings, "GOOGLE_SERVICE_ACCOUNT_JSON_B64", "")
        )
    )


def _service_account_info() -> dict:
    raw = getattr(settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "")
    encoded = getattr(settings, "GOOGLE_SERVICE_ACCOUNT_JSON_B64", "")
    try:
        if raw:
            return json.loads(raw)
        if encoded:
            return json.loads(base64.b64decode(encoded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise GoogleSheetError(
            "Les credentials Google du serveur sont invalides."
        ) from exc
    raise GoogleSheetError(
        "Google Sheets n’est pas configuré sur le serveur."
    )


def _access_token() -> str:
    if not google_sheets_is_configured():
        raise GoogleSheetError(
            "Google Sheets n’est pas activé dans les variables d’environnement."
        )
    try:
        from google.auth.transport.requests import Request as GoogleAuthRequest
        from google.oauth2 import service_account
    except ImportError as exc:
        raise GoogleSheetError(
            "La dépendance google-auth n’est pas installée sur le serveur."
        ) from exc

    try:
        credentials = service_account.Credentials.from_service_account_info(
            _service_account_info(),
            scopes=GOOGLE_SCOPES,
        )
        credentials.refresh(GoogleAuthRequest())
    except Exception as exc:
        raise GoogleSheetError(
            "Impossible d’authentifier le compte de service Google."
        ) from exc
    if not credentials.token:
        raise GoogleSheetError("Google n’a pas renvoyé de jeton d’accès.")
    return credentials.token


def _google_request(method: str, url: str, *, payload=None):
    headers = {
        "Authorization": f"Bearer {_access_token()}",
        "Accept": "application/json",
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    try:
        response = requests.request(
            method,
            url,
            headers=headers,
            json=payload,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise GoogleSheetError(
            "Impossible de contacter Google Sheets/Drive."
        ) from exc

    if not 200 <= response.status_code < 300:
        detail = (response.text or "").strip().replace("\n", " ")
        if len(detail) > 500:
            detail = detail[:500] + "…"
        raise GoogleSheetError(
            f"Google a refusé l’opération ({response.status_code})"
            + (f" : {detail}" if detail else ".")
        )
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {}


def _a1_tab(tab_name: str) -> str:
    safe = (tab_name or "Players").replace("'", "''")
    return f"'{safe}'"


def _order_date(video: Video):
    if video.whatsapp_conversation_date:
        return video.whatsapp_conversation_date
    if video.video_creation_date:
        return timezone.localtime(video.video_creation_date).date()
    return None


def _build_sheet_payload(organization):
    videos = list(
        Video.objects.filter(client_organization=organization)
        .select_related("player")
        .order_by("whatsapp_conversation_date", "video_creation_date", "pk")
    )

    rows = []
    monthly_totals = {month: Decimal("0") for month in calendar.month_name[1:]}
    grand_total = Decimal("0")

    for video in videos:
        order_date = _order_date(video)
        month_name = calendar.month_name[order_date.month] if order_date else ""
        price = Decimal(video.total_payment or 0)
        grand_total += price
        if month_name:
            monthly_totals[month_name] += price

        rows.append(
            [
                video.player.name,
                (
                    f"{int(video.match_package)} matchs"
                    if video.match_package
                    else ""
                ),
                float(price),
                month_name,
            ]
        )

    summary_rows = [["Monthly totals", "Price (DT)"]]
    for month in calendar.month_name[1:]:
        summary_rows.append([month, float(monthly_totals[month])])
    summary_rows.append(["Grand total", float(grand_total)])

    return rows, summary_rows, grand_total


def sync_organization_sheet(organization) -> OrganizationSheetSyncResult:
    spreadsheet_id = normalize_spreadsheet_reference(organization.google_sheet_id)
    if not spreadsheet_id:
        raise GoogleSheetError(
            "Aucun Google Sheet n’est configuré pour cette organisation."
        )

    tab = organization.google_sheet_tab or "Players"
    tab_a1 = _a1_tab(tab)
    rows, summary_rows, grand_total = _build_sheet_payload(organization)

    clear_url = (
        f"{SHEETS_API_ROOT}/{spreadsheet_id}/values:batchClear"
    )
    _google_request(
        "POST",
        clear_url,
        payload={
            "ranges": [
                f"{tab_a1}!A2:D",
                f"{tab_a1}!F1:G14",
            ]
        },
    )

    data = [
        {
            "range": f"{tab_a1}!A1:D1",
            "majorDimension": "ROWS",
            "values": [["Player name", "Number of matches", "Price (DT)", "Month"]],
        },
        {
            "range": f"{tab_a1}!F1:G14",
            "majorDimension": "ROWS",
            "values": summary_rows,
        },
    ]
    if rows:
        data.append(
            {
                "range": f"{tab_a1}!A2:D{len(rows) + 1}",
                "majorDimension": "ROWS",
                "values": rows,
            }
        )

    _google_request(
        "POST",
        f"{SHEETS_API_ROOT}/{spreadsheet_id}/values:batchUpdate",
        payload={
            "valueInputOption": "USER_ENTERED",
            "data": data,
        },
    )

    organization.google_sheet_last_synced_at = timezone.now()
    organization.google_sheet_last_error = ""
    organization.save(
        update_fields=(
            "google_sheet_last_synced_at",
            "google_sheet_last_error",
            "updated_at",
        )
    )

    return OrganizationSheetSyncResult(
        row_count=len(rows),
        grand_total=grand_total,
        spreadsheet_url=organization.google_sheet_url,
    )


def _contact_emails(organization) -> tuple[str, ...]:
    recipients = []
    seen = set()

    def add(value):
        email = (value or "").strip().lower()
        if email and email not in seen:
            seen.add(email)
            recipients.append(email)

    add(organization.email)
    memberships = (
        organization.memberships.filter(
            is_active=True,
            user__is_active=True,
        )
        .select_related("user")
        .order_by("created_at")
    )
    for membership in memberships:
        add(membership.user.email)
    return tuple(recipients)


def _existing_drive_permissions(spreadsheet_id: str) -> set[str]:
    result = _google_request(
        "GET",
        (
            f"{DRIVE_API_ROOT}/{spreadsheet_id}/permissions"
            "?supportsAllDrives=true&fields=permissions(emailAddress,type,role)"
        ),
    )
    emails = set()
    for permission in result.get("permissions", []):
        email = (permission.get("emailAddress") or "").strip().lower()
        if email:
            emails.add(email)
    return emails


def share_sheet_with_contacts(
    organization,
    recipients: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    spreadsheet_id = normalize_spreadsheet_reference(organization.google_sheet_id)
    existing = _existing_drive_permissions(spreadsheet_id)
    shared = []
    errors = []

    for email in recipients:
        if email in existing:
            shared.append(email)
            continue
        try:
            _google_request(
                "POST",
                (
                    f"{DRIVE_API_ROOT}/{spreadsheet_id}/permissions"
                    "?supportsAllDrives=true&sendNotificationEmail=false"
                ),
                payload={
                    "type": "user",
                    "role": "reader",
                    "emailAddress": email,
                },
            )
            shared.append(email)
        except GoogleSheetError as exc:
            errors.append(f"{email}: {exc}")
    return tuple(shared), tuple(errors)


def send_organization_sheet_to_contacts(
    organization,
) -> OrganizationSheetDeliveryResult:
    sync_result = sync_organization_sheet(organization)
    recipients = _contact_emails(organization)
    if not recipients:
        raise GoogleSheetError(
            "Aucun e-mail n’est enregistré pour les contacts de cette organisation."
        )

    shared, permission_errors = share_sheet_with_contacts(
        organization,
        recipients,
    )

    subject = f"MS Football — Google Sheet {organization.name}"
    body = (
        f"Bonjour,\n\n"
        f"Le Google Sheet de {organization.name} vient d’être synchronisé.\n"
        f"Commandes : {sync_result.row_count}\n"
        f"Total : {sync_result.grand_total:.2f} DT\n\n"
        f"Vous pouvez l’ouvrir ici : {sync_result.spreadsheet_url}\n\n"
        f"MS Football"
    )

    sent = []
    for email in recipients:
        try:
            count = send_mail(
                subject,
                body,
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
        except Exception as exc:
            raise GoogleSheetError(
                f"Le Sheet est synchronisé, mais l’e-mail vers {email} a échoué."
            ) from exc
        if count:
            sent.append(email)

    return OrganizationSheetDeliveryResult(
        recipients=tuple(sent),
        shared_with=shared,
        permission_errors=permission_errors,
        sync_result=sync_result,
    )


def organization_sheet_whatsapp_contacts(organization):
    if not organization.google_sheet_url:
        return []

    message = (
        f"Bonjour, voici le Google Sheet {organization.name} mis à jour : "
        f"{organization.google_sheet_url}"
    )
    contacts = []
    seen_phones = set()

    def add_contact(name, raw_phone):
        phone = re.sub(r"\D", "", raw_phone or "")
        if not phone or phone in seen_phones:
            return
        seen_phones.add(phone)
        contacts.append(
            {
                "name": name,
                "whatsapp_number": raw_phone,
                "whatsapp_url": (
                    f"https://wa.me/{phone}?text={quote(message, safe='')}"
                ),
            }
        )

    add_contact(
        organization.contact_name or organization.name,
        organization.whatsapp_number,
    )

    memberships = (
        organization.memberships.filter(
            is_active=True,
            user__is_active=True,
            user__portal_profile__isnull=False,
        )
        .select_related("user", "user__portal_profile")
        .order_by("created_at")
    )
    for membership in memberships:
        profile = membership.user.portal_profile
        add_contact(
            profile.display_name or membership.user.username,
            profile.whatsapp_number,
        )
    return contacts
