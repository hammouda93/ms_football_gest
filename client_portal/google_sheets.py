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


def _player_key(value):
    """Exact, case-insensitive key: no fuzzy matching of real people."""
    import unicodedata

    return unicodedata.normalize(
        "NFKC", " ".join(str(value or "").split())
    ).casefold()


def _package_label(value):
    if value is None or value == "":
        return ""
    return f"{int(value)} matchs"


def _expected_package(value):
    match = re.fullmatch(r"\s*(3|5|10)(?:\s+matchs?)?\s*", str(value or ""), re.I)
    return int(match.group(1)) if match else None


def _sheet_price(value, *, row_number):
    if value in ("", None):
        return Decimal("0")
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    cleaned = re.sub(r"\s*DT\s*$", "", str(value), flags=re.I)
    cleaned = cleaned.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except Exception as exc:
        raise GoogleSheetError(
            f"Prix illisible à la ligne {row_number} : corrigez la cellule D."
        ) from exc


def _order_values(video):
    order_date = _order_date(video)
    month = calendar.month_name[order_date.month] if order_date else ""
    return (
        _package_label(video.match_package),
        float(video.total_payment or 0),
        month,
    )


def _existing_order_values(item):
    return (
        str(item["sent"] or "").strip(),
        _sheet_price(item["price"], row_number=item["row"]),
        str(item["month"] or "").strip().casefold(),
    )


def _video_order_values(video):
    label, price, month = _order_values(video)
    return (label, Decimal(str(price)), month.casefold())


def _sheet_rows(matrix):
    if not matrix:
        raise GoogleSheetError("Le Google Sheet est vide : synchronisation annulée.")
    header = list(matrix[0]) + [""] * max(0, 8 - len(matrix[0]))
    required = {
        0: "Player name",
        1: "Number of matches sent",
        2: "Number of matches expected",
        3: "Price (DT)",
        4: "Month",
        6: "Monthly totals",
        7: "Price (DT)",
    }
    for index, title in required.items():
        if str(header[index]).strip().casefold() != title.casefold():
            raise GoogleSheetError(
                "Le format du Sheet a changé : colonne "
                f"{chr(65 + index)} attendue « {title} ». Aucune cellule modifiée."
            )

    entries = []
    last_used_player_row = 1
    for index, source in enumerate(matrix[1:], start=2):
        cells = list(source) + [""] * max(0, 5 - len(source))
        # Never overwrite an existing manually prepared row, even if
        # the player name has not yet been entered.
        if any(value not in ("", None) for value in cells[:5]):
            last_used_player_row = index
        name = str(cells[0] or "").strip()
        if name:
            entries.append(
                {
                    "row": index,
                    "name": name,
                    "sent": cells[1],
                    "expected": cells[2],
                    "price": cells[3],
                    "month": cells[4],
                }
            )
    return entries, last_used_player_row


def _plan_sheet_merge(videos, matrix, tab_a1):
    """Return only safe cell-level writes; existing names/expected are immutable."""
    from collections import defaultdict

    entries, last_used_row = _sheet_rows(matrix)
    by_name = defaultdict(list)
    for entry in entries:
        by_name[_player_key(entry["name"])].append(entry)

    grouped_videos = defaultdict(list)
    for video in videos:
        grouped_videos[_player_key(video.player.name)].append(video)

    writes = []
    for key, video_group in grouped_videos.items():
        candidates = list(by_name.get(key, []))
        remaining_rows = list(candidates)
        remaining_videos = list(video_group)
        assignments = []

        # For repeated orders of a player, match the exact package, price
        # and month first. An ambiguous match stops ALL writes.
        for video in video_group:
            exact = [
                row for row in remaining_rows
                if _existing_order_values(row) == _video_order_values(video)
            ]
            if len(exact) > 1:
                raise GoogleSheetError(
                    f"Plusieurs lignes correspondent à « {video.player.name} ». "
                    "Vérifiez les doublons avant de synchroniser."
                )
            if len(exact) == 1:
                assignments.append((exact[0], video))
                remaining_rows.remove(exact[0])
                remaining_videos.remove(video)

        # A single remaining order and single row can be updated in place.
        if len(remaining_rows) == len(remaining_videos) == 1:
            assignments.append((remaining_rows.pop(), remaining_videos.pop()))

        if remaining_rows and remaining_videos:
            raise GoogleSheetError(
                f"Correspondance ambiguë pour « {video_group[0].player.name} » : "
                "aucune ligne ne sera écrasée. Vérifiez les commandes répétées."
            )

        for row, video in assignments:
            sent, price, month = _order_values(video)
            for letter, old_value, new_value in (
                ("B", row["sent"], sent),
                ("D", row["price"], price),
                ("E", row["month"], month),
            ):
                if letter == "D":
                    same = _sheet_price(old_value, row_number=row["row"]) == Decimal(str(price))
                else:
                    same = str(old_value or "").strip() == str(new_value)
                if not same:
                    writes.append({
                        "range": f"{tab_a1}!{letter}{row['row']}",
                        "values": [[new_value]],
                    })
            row["sent"], row["price"], row["month"] = sent, price, month

        for video in remaining_videos:
            last_used_row += 1
            sent, price, month = _order_values(video)
            # C is empty only on this NEW row; never update C on existing rows.
            writes.append({
                "range": f"{tab_a1}!A{last_used_row}:E{last_used_row}",
                "values": [[video.player.name, sent, "", price, month]],
            })
            entries.append({
                "row": last_used_row,
                "name": video.player.name,
                "sent": sent,
                "expected": "",
                "price": price,
                "month": month,
            })

    monthly_totals = {month: Decimal("0") for month in calendar.month_name[1:]}
    month_lookup = {month.casefold(): month for month in monthly_totals}
    month_lookup.update({
        "janvier": "January", "février": "February", "mars": "March",
        "avril": "April", "mai": "May", "juin": "June",
        "juillet": "July", "août": "August", "septembre": "September",
        "octobre": "October", "novembre": "November", "décembre": "December",
    })
    for entry in entries:
        amount = _sheet_price(entry["price"], row_number=entry["row"])
        if not amount:
            continue
        month = month_lookup.get(str(entry["month"] or "").strip().casefold())
        if not month:
            raise GoogleSheetError(
                f"Mois manquant ou inconnu à la ligne {entry['row']} : "
                "les totaux ne peuvent pas être calculés sans risque."
            )
        monthly_totals[month] += amount

    total = sum(monthly_totals.values(), Decimal("0"))
    summary = [float(monthly_totals[month]) for month in calendar.month_name[1:]]
    summary.append(float(total))
    existing_summary = [
        (matrix[index][7] if len(matrix) > index and len(matrix[index]) > 7 else "")
        for index in range(1, 14)
    ]
    for offset, (current, amount) in enumerate(zip(existing_summary, summary), start=2):
        if _sheet_price(current, row_number=offset) != Decimal(str(amount)):
            writes.append({
                "range": f"{tab_a1}!H{offset}",
                "values": [[amount]],
            })
    return writes, entries, total


def _remember_expected_matches(organization, entries):
    """Mirror planning into linked players only; never manufacture Player records."""
    from collections import defaultdict
    from .models import OrganizationPlayer

    rows_by_key = defaultdict(list)
    for row in entries:
        rows_by_key[_player_key(row["name"])].append(row)

    links = list(
        OrganizationPlayer.objects.filter(organization=organization, is_active=True)
        .select_related("player")
    )
    links_by_key = defaultdict(list)
    for link in links:
        links_by_key[_player_key(link.player.name)].append(link)

    for name_key, linked in links_by_key.items():
        matched_rows = rows_by_key.get(name_key, [])
        if len(linked) != 1 or len(matched_rows) != 1:
            continue
        expected = _expected_package(matched_rows[0]["expected"])
        if expected is not None and linked[0].expected_matches != expected:
            linked[0].expected_matches = expected
            linked[0].save(update_fields=("expected_matches",))


def sync_organization_sheet(organization) -> OrganizationSheetSyncResult:
    spreadsheet_id = normalize_spreadsheet_reference(organization.google_sheet_id)
    if not spreadsheet_id:
        raise GoogleSheetError(
            "Aucun Google Sheet n’est configuré pour cette organisation."
        )

    tab_a1 = _a1_tab(organization.google_sheet_tab or "Players")
    read_range = quote(f"{tab_a1}!A1:H", safe="!'")
    response = _google_request(
        "GET",
        f"{SHEETS_API_ROOT}/{spreadsheet_id}/values/{read_range}"
        "?valueRenderOption=UNFORMATTED_VALUE",
    )
    matrix = response.get("values") or []
    videos = list(
        Video.objects.filter(client_organization=organization)
        .select_related("player")
        .order_by("whatsapp_conversation_date", "video_creation_date", "pk")
    )
    writes, entries, grand_total = _plan_sheet_merge(videos, matrix, tab_a1)

    if writes:
        _google_request(
            "POST",
            f"{SHEETS_API_ROOT}/{spreadsheet_id}/values:batchUpdate",
            payload={
                "valueInputOption": "USER_ENTERED",
                "data": writes,
            },
        )

    _remember_expected_matches(organization, entries)

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
        row_count=len(videos),
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
