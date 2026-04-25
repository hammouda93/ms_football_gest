import threading
from django.conf import settings
from .models import Notification,Video,Invoice,Player,Payment,VideoStatusHistory,User,VideoEditor
from django.utils import timezone
import logging
from asgiref.sync import sync_to_async, asyncio  # Fix for async Django ORM queries
import threading
from datetime import datetime, timedelta, date
from decimal import Decimal
from django.db.models import OuterRef, Subquery
import requests
from datetime import datetime
import re
import requests
from html import unescape


def clean_text(value):
    if not value:
        return ""
    return " ".join(unescape(value).split()).strip()


def extract_meta_content(html, meta_name=None, meta_property=None):
    if meta_name:
        pattern = rf'<meta\s+name="{re.escape(meta_name)}"\s+content="([^"]*)"'
    elif meta_property:
        pattern = rf'<meta\s+property="{re.escape(meta_property)}"\s+content="([^"]*)"'
    else:
        return ""

    match = re.search(pattern, html, re.IGNORECASE)
    return clean_text(match.group(1)) if match else ""


def extract_js_value(html, key):
    pattern = rf"{re.escape(key)}\s*:\s*'([^']*)'"
    match = re.search(pattern, html, re.IGNORECASE)
    return clean_text(match.group(1)) if match else ""


def map_transfermarkt_position(position_text):
    text = (position_text or "").lower()

    if any(x in text for x in ["goalkeeper", "gardien"]):
        return "GK"
    if any(x in text for x in [
        "defender", "centre-back", "center-back", "left-back", "right-back",
        "arrière", "défenseur", "lateral", "back"
    ]):
        return "DF"
    if any(x in text for x in [
        "midfield", "midfielder", "milieu", "central midfield",
        "defensive midfield", "attacking midfield"
    ]):
        return "MF"
    if any(x in text for x in [
        "forward", "striker", "winger", "ailier", "attaquant",
        "centre-forward", "center-forward"
    ]):
        return "FW"

    return "DF"


def extract_birth_date_from_description(description):
    # exemple dans ton HTML :
    # * 12 juil. 1999 à Guayaquil, Équateur
    match = re.search(r"\*\s*(\d{1,2}\s+[^\s]+\s+\d{4})", description)
    if not match:
        return ""

    raw = match.group(1).strip()

    months = {
        "janv.": "01", "févr.": "02", "mars": "03", "avr.": "04",
        "mai": "05", "juin": "06", "juil.": "07", "août": "08",
        "sept.": "09", "oct.": "10", "nov.": "11", "déc.": "12",
        "jan": "01", "feb": "02", "mar": "03", "apr": "04",
        "may": "05", "jun": "06", "jul": "07", "aug": "08",
        "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    }

    parts = raw.split()
    if len(parts) != 3:
        return ""

    day = parts[0].zfill(2)
    month = months.get(parts[1].lower())
    year = parts[2]

    if not month:
        return ""

    return f"{year}-{month}-{day}"


def parse_transfermarkt_player(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.transfermarkt.fr/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
    }

    session = requests.Session()

    response = session.get(
        url,
        headers=headers,
        timeout=20,
        allow_redirects=True,
    )

    if response.status_code == 403:
        raise ValueError(
            "Transfermarkt bloque l'import automatique pour le moment. "
            "Réessayez plus tard ou remplissez le joueur manuellement."
        )

    response.raise_for_status()
    html = response.text

    og_title = extract_meta_content(html, meta_property="og:title") or ""
    description = extract_meta_content(html, meta_name="description") or ""

    name = extract_js_value(html, "eVar27") or ""
    club = extract_js_value(html, "eVar3") or ""
    league_name = extract_js_value(html, "eVar4") or ""

    name = re.sub(r"\s*\(\d+\)$", "", name).strip()
    club = re.sub(r"\s*\(\d+\)$", "", club).strip()
    league_name = re.sub(r"\s*\([A-Z0-9]+\)$", "", league_name).strip()

    if not name and og_title:
        name = og_title.split(" - ")[0].strip()

    position = map_transfermarkt_position(description)

    league = "OC"
    league_name_lower = league_name.lower()

    if "tunisie" in league_name_lower and "ligue 1" in league_name_lower:
        league = "L1"
    elif "tunisie" in league_name_lower and "ligue 2" in league_name_lower:
        league = "L2"
    elif "libye" in league_name_lower:
        league = "LY"

    date_of_birth = extract_birth_date_from_description(description)

    return {
        "name": name,
        "date_of_birth": date_of_birth,
        "club": club,
        "position": position,
        "league": league,
        "league_name_raw": league_name,
        "description_raw": description,
    }


# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Debugging: Print when bot starts
logger.info("Bot is starting...")
_thread_locals = threading.local()
def get_current_user():
    return getattr(_thread_locals, 'user', None)

def set_current_user(user):
    _thread_locals.user = user


def create_notification(user, message, notification_type='update', video=None, player=None,sent_by=None):
    Notification.objects.create(
        user=user,
        message=message,
        is_read=False,  # Default to unread
        video=video,
        player=player,
        notification_type=notification_type,  # Use the correct field name
        sent_at = timezone.now(),
        sent_by = sent_by
    )

# Create a thread-local storage
_thread_locals = threading.local()

def set_signal_processing(should_process):
    _thread_locals.should_process_signals = should_process

def should_process_signals():
    return getattr(_thread_locals, 'should_process_signals', True)


def fetch_players_sync(status: str):
    """Synchronous function to fetch players by video status with additional details."""
    try:
        logger.info(f"Fetching players for status: {status}")
        normalized_status = status.strip().lower().replace(" ", "_")
        
        if normalized_status == "delivered":
            # Get delivered videos & annotate with latest delivery date
            videos = Video.objects.filter(status="delivered").annotate(
                delivery_date=Subquery(
                    VideoStatusHistory.objects.filter(video=OuterRef("pk"), status="delivered")
                    .order_by("-changed_at")
                    .values("changed_at")[:1]
                    )
                ).order_by("-delivery_date")
        else:
            # Sort by nearest deadline first
            videos = list(Video.objects.filter(status=normalized_status).order_by("deadline"))

        result = []
        for video in videos:
            editor_name = video.editor.user.username  # Get the editor's name
            payment_status_icon = {
                "unpaid": "❌",
                "partially_paid": "❌⚠️",
                "paid": "✅"
            }.get(video.invoices.status, "Unknown")

            if normalized_status == "delivered":
                # Fetch the latest delivery date
                delivery_date = video.delivery_date.strftime('%d-%m-%Y')
                info = f"{payment_status_icon}{video.player.name}|{delivery_date}|{editor_name}"
            else:
                deadline = video.deadline.strftime("%d-%m-%Y")
                info = f"{payment_status_icon}{video.player.name}|{deadline}|{editor_name}"

            result.append(info)

        return result[:80] if result else [f"No videos found for status '{normalized_status}'."]

    except Exception as e:
        logger.error(f"Error fetching videos: {e}")
        return [f"Error fetching videos: {str(e)}"]

async def get_players_by_status(status: str):
    """Run the synchronous fetch_players_sync function in a separate thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_players_sync, status)


def search_players_sync(partial_name: str):
    """Search for players whose names contain the given partial name."""
    try:
        players = Player.objects.filter(name__icontains=partial_name)[:5]  # Limit to 5 results
        if not players:
            return []
        return [player.name for player in players]
    
    except Exception as e:
        return f"Error fetching players: {str(e)}"
async def search_players(partial_name: str):
    """Run the synchronous search_players_sync function asynchronously."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, search_players_sync, partial_name)




def search_video_for_player_sync(player_id: int):
    """Fetch videos associated with a given player ID (synchronously)."""
    try:
        videos = Video.objects.filter(player__id=player_id).values("id", "club", "season", "status").order_by('-video_creation_date')
        return list(videos) if videos else []
    except Exception as e:
        return f"Error fetching videos: {str(e)}"    
async def search_video_for_player(player_id: int):
    """Run the synchronous search_video_for_player_sync function asynchronously."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, search_video_for_player_sync, player_id)





def fetch_videos_by_deadline_sync(deadline_filter: str):
    """Fetch videos based on deadline filters, including payment status, editor, and video status icons."""
    try:
        today = datetime.now().date()

        # Filtering by deadline and excluding 'delivered' and 'problematic' status
        if deadline_filter == 'past':
            videos = Video.objects.filter(deadline__lt=today).exclude(status__in=['delivered', 'problematic']).order_by("deadline")
        elif deadline_filter == '3_days_ago':
            three_days_ago = today - timedelta(days=3)
            videos = Video.objects.filter(deadline__gte=three_days_ago,deadline__lt=today).exclude(status__in=['delivered', 'problematic']).order_by("deadline")
        elif deadline_filter == 'today':
            videos = Video.objects.filter(deadline=today).exclude(status__in=['delivered', 'problematic'])
        elif deadline_filter == '3_days':
            three_days_from_now = today + timedelta(days=3)
            videos = Video.objects.filter(deadline__gte=today, deadline__lte=three_days_from_now).exclude(status__in=['delivered', 'problematic']).order_by("deadline")
        elif deadline_filter == '1_week':
            one_week_from_now = today + timedelta(weeks=1)
            videos = Video.objects.filter(deadline__gte=today, deadline__lte=one_week_from_now).exclude(status__in=['delivered', 'problematic']).order_by("deadline")
        elif deadline_filter == '2_weeks':
            two_weeks_from_now = today + timedelta(weeks=2)
            videos = Video.objects.filter(deadline__gte=today, deadline__lte=two_weeks_from_now).exclude(status__in=['delivered', 'problematic']).order_by("deadline")
        elif deadline_filter == '1_month':
            one_month_from_now = today + timedelta(days=30)
            videos = Video.objects.filter(deadline__gte=today, deadline__lte=one_month_from_now).exclude(status__in=['delivered', 'problematic']).order_by("deadline")
        elif deadline_filter == 'upcoming':
            videos = Video.objects.filter(deadline__gte=today).exclude(status__in=['delivered', 'problematic']).order_by("deadline")
        else:
            return ["Invalid deadline filter"]

        result = []
        for video in videos:
            # Payment status icons
            payment_icon = {
                "unpaid": "❌",
                "partially_paid": "❌⚠️",
                "paid": "✅"
            }.get(video.invoices.status, "❓")

            # Video status icons
            status_icon = {
                "pending": "😴",
                "in_progress": "🎬",
                "completed_collab": "🏁🧑‍💻",
                "completed": "🏁",
                "delivered": "✅"
            }.get(video.status, "❓")

            editor_name = video.editor.user.username if video.editor else "Unknown Editor"
            deadline_formatted = video.deadline.strftime("%d-%m-%Y")

            video_info = f"{status_icon}{video.player.name}|{editor_name}|{deadline_formatted}|💰{payment_icon}"
            result.append(video_info)

        return result if result else ["No videos found for this period."]
    
    except Exception as e:
        return [f"Error fetching videos: {str(e)}"]

async def get_videos_by_deadline(deadline_filter: str):
    """Run the fetch_videos_by_deadline_sync function in a separate thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_videos_by_deadline_sync, deadline_filter)


def fetch_players_by_invoice_status_sync(status: str):
    """Fetch players whose invoices have the specified status with video details."""
    try:
        invoices = Invoice.objects.filter(status=status).exclude(video__status="problematic")

        # Subquery to get the most recent 'delivered' date
        latest_delivery_date = VideoStatusHistory.objects.filter(
            video=OuterRef("pk"), status="delivered"
        ).order_by("-changed_at").values("changed_at")[:1]

        videos = Video.objects.filter(id__in=invoices.values("video_id")).annotate(
            delivery_date=Subquery(latest_delivery_date)
        )

        # Sorting logic
        delivered_videos = videos.filter(status="delivered").order_by("-delivery_date")
        non_delivered_videos = videos.exclude(status="delivered").order_by("deadline")

        # If paid, show non-delivered first, otherwise delivered first
        if status == "paid":
            sorted_videos = list(non_delivered_videos) + list(delivered_videos)
        else:
            sorted_videos = list(delivered_videos) + list(non_delivered_videos)

        result = []
        today = date.today()
        urgent_threshold = today + timedelta(days=3)  # Deadline threshold (3 days)

        for video in sorted_videos:
            editor_name = video.editor.user.username
            payment_status = video.invoices.status
            deadline = video.deadline if video.deadline else None

            # Default icon logic
            if payment_status in ["unpaid", "partially_paid"] and video.status in [
                "in_progress", "completed_collab", "completed", "delivered"
            ]:
                call_icon = "☎️"
            elif status == 'paid': 
                call_icon = "✅"
            else:
                call_icon = "⏳"
            # Urgency-based icons
            urgent_icon = "🎬"  # Default icon
            if video.status == "delivered":
                urgent_icon = "✅"  # Delivered videos get a checkmark
            elif video.status == "pending":
                urgent_icon = "😴"  # Pending videos (waiting to start)
            elif video.status == "completed":
                urgent_icon = "🏁"  # Completed videos
            elif video.status == "completed_collab":
                urgent_icon = "🏁🧑‍💻"  # Completed by collaboration
            elif deadline <= urgent_threshold or deadline < today:  # Urgent cases
                if payment_status == "partially_paid":
                    urgent_icon += "⚠️"  # Work needed
                elif payment_status == "paid" and video.status != "delivered":
                    urgent_icon += "🔥"  # Priority work

            # Formatting output
            if video.status == "delivered":
                delivery_date = video.delivery_date.strftime("%d-%m-%Y") if video.delivery_date else "Unknown"
                info = f"{urgent_icon}{video.player.name}|{editor_name}|{delivery_date}|💰{call_icon}"
            else:
                formatted_deadline = deadline.strftime("%d-%m-%Y") if deadline else "Unknown"
                info = f"{urgent_icon}{video.player.name}|{editor_name}|{formatted_deadline}|💰{call_icon}"

            result.append(info.strip())

        return result[:80] if result else [f"No players found with invoice status '{status}'."]

    except Exception as e:
        return [f"Error fetching players: {str(e)}"]

async def get_players_by_invoice_status(status: str):
    """Run fetch_players_by_invoice_status_sync in a separate thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_players_by_invoice_status_sync, status)


def fetch_payment_details_sync(player_name: str,video_id: int = None):
    """Synchronous function to fetch the payment details of a player."""
    logger.info(f"🛠️ Inside fetch_payment_details_sync with player: {player_name}, Video ID: {video_id}")
    try:
        logger.info(f"Fetching payment details for player: {player_name}")
        player = Player.objects.get(name__iexact=player_name)  # Case-insensitive search
        logger.info(f"Player {player_name} found.")
        logger.info(f"Video ID passed: {video_id}, Type: {type(video_id)}")
        if video_id is not None:  # Explicitly check for None
            logger.info(f"Fetching video with ID: {video_id}")
            video = Video.objects.filter(id=video_id).first()
            if not video:
                logger.warning(f"⚠️ Video ID {video_id} not found. Defaulting to latest video.")
                return f"No video found for player {player_name}."
        else:
            logger.info(f"Fetching latest video for {player_name}")
            video = Video.objects.filter(player=player).order_by("-video_creation_date").first()
            
        
        video_status = video.status
        invoice = Invoice.objects.filter(video=video).first()  # Get the related invoice
        video_id = video.id
        if not invoice:
            logger.warning(f"No invoice found for player {player_name}'s video.")
            return f"No invoice found for {player_name}'s video."
        
        # Convert amounts to integers
        amount_paid = int(invoice.amount_paid)
        total_amount = int(invoice.total_amount)

        # Payment status icons
        payment_status_icons = {
            "unpaid": "❌",
            "partially_paid": "❌⚠️",
            "paid": "✅"
        }
        paid_icon = payment_status_icons.get(invoice.status, "❓")

        # Video status icons
        video_status_icons = {
            "pending": "😴",
            "in_progress": "🎬",
            "completed_collab": "🏁🧑‍💻",
            "completed": "🏁",
            "delivered": "✅"
        }
        status_icon = video_status_icons.get(video_status, "❓")

        # Get editor's name
        editor_name = video.editor.user.username if video.editor else "Unknown"

        # Delivery date or Deadline
        today = datetime.now().date()
        if video_status == "delivered":
            delivery_date = video.status_history.filter(status="delivered").order_by("-changed_at").first()
            date_info = f"📅 Delivered on {delivery_date.changed_at.strftime('%d-%m-%Y')}" if delivery_date else "📅 Delivery date unknown"
        else:
            if video.deadline:
                if video.deadline < today:  
                    date_info = f"⏳❗ Past Deadline: {video.deadline.strftime('%d-%m-%Y')}"  # Past deadline  
                elif today <= video.deadline <= (today + timedelta(days=3)):  
                    date_info = f"⏳ Urgent: {video.deadline.strftime('%d-%m-%Y')}"  # Within 3 days  
                else:  
                    date_info = f"📆 Scheduled: {video.deadline.strftime('%d-%m-%Y')}"  # More than 3 days away  
            else:
                date_info = "⏳ No deadline set"

        # Build response message
        response = (
            f"{paid_icon} {player.name} paid {amount_paid} of {total_amount}.\n"
            f"🎥 Video Status: {video_status} {status_icon}\n"
            f"✏️ Edited by: {editor_name}\n"
            f"{date_info}"
        )

        return response, player.id, video_status, player.name, editor_name, video_id 

    except Player.DoesNotExist:
        logger.error(f"Player {player_name} not found.")
        return "❌ Joueur introuvable.", None, None, None, None
    except Exception as e:
        logger.error(f"Error fetching payment details for player {player_name}: {str(e)}")
        return f"Error fetching payment details: {str(e)}", None, None, None, None

async def get_payment_details(player_name: str,video_id: int = None):
    """Run the synchronous fetch_payment_details_sync function in a separate thread."""
    logger.info(f"🔍 Calling fetch_payment_details_sync with player: {player_name}, Video ID: {video_id}")
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_payment_details_sync, player_name,video_id)



def process_payment_sync(player_id: int, amount: float, payment_method: str, user: int,video_id: int = None):
    """Synchronous function to process payment and update the invoice."""
    try:
        logger.info(f"Processing payment of {amount} for player {player_id} using {payment_method}.")
        player = Player.objects.get(id=player_id)
        video = Video.objects.filter(id=video_id).first()
        invoice = Invoice.objects.filter(video=video).order_by("-invoice_date").first()

        if not invoice:
            logger.error(f"No invoice found for player {player_id}.")
            return False

        # Convert amount to Decimal
        decimal_amount = Decimal(str(amount))  # Use str to preserve precision

        payment_type = "final" if invoice.amount_paid + decimal_amount >= invoice.total_amount else "advance"
        # 🔹 Récupérer l'utilisateur Django en fonction de l'ID Telegram
        created_by_user = User.objects.get(id=1) if user == 5853993816 else User.objects.get(id=2)
        # Save Payment with payment_method
        Payment.objects.create(
            player=player,
            video=video,
            amount=decimal_amount,
            payment_type=payment_type,
            payment_method=payment_method,
            created_by=created_by_user ,
            remaining_balance=max(Decimal('0.00'), invoice.total_amount - (invoice.amount_paid + decimal_amount)),
            invoice=invoice
        )

        # Update Invoice
        invoice.amount_paid += decimal_amount
        invoice.status = "paid" if invoice.amount_paid >= invoice.total_amount else "partially_paid"
        invoice.save()

        logger.info(f"Payment processed successfully for player {player_id}.")
        return True

    except Player.DoesNotExist:
        logger.error(f"Player {player_id} not found.")
        return False
    except Exception as e:
        logger.error(f"Error processing payment for player {player_id}: {str(e)}")
        return False

async def process_payment(player_id: int, amount: float, payment_method: str, user: int,video_id: int = None):
    """Run the synchronous process_payment_sync function in a separate thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, process_payment_sync, player_id, amount, payment_method, user,video_id)





def update_video_status_sync(player_name: str, new_status: str, user : int,video_id: int = None):
    """Synchronously update the status of the latest video for a given player."""
    try:
        logger.info(f"Updating video status for player: {player_name} to {new_status}")
        logger.info(f"Updating video by the user in utilis.py: {user}")
        player = Player.objects.get(name__iexact=player_name)
        video = Video.objects.filter(id=video_id).first()

        if not video:
            logger.warning(f"No video found for player {player_name}.")
            return f"No video found for player {player_name}."
        
        if video.status == new_status:
            logger.info(f"Status is already '{new_status}', no update needed.")
            return f"ℹ️ Le statut est déjà '{new_status}'. Aucune modification effectuée."
        created_by_user = User.objects.get(id=1) if user == 5853993816 else User.objects.get(id=2)
        logger.info(f"utilisateur {created_by_user.username} trouvé pour l'ID {created_by_user.id} correspondant à {user}")
        previous_status = video.status
        video.status = new_status
        Video.objects.filter(id=video.id).update(status=new_status)       
        VideoStatusHistory.objects.create(
            video=video,
            editor=video.editor,
            status=new_status,
            created_by = created_by_user,
            comment="Status changed"
        )
        # 🔹 Vérifier si la vidéo est "completed" et si le paiement est réglé
        if new_status == "completed":
            invoice = getattr(video, 'invoices', None)  # Récupérer la facture liée (OneToOneField)
            if invoice:
                if invoice.status != 'paid':
                    # Notifier les super admins
                    super_admins = User.objects.filter(is_superuser=True)
                    for admin in super_admins:
                        create_notification(
                            user=admin,
                            message=f"📢 La vidéo {video} est terminée. Contactez le joueur via {video.player.whatsapp_number} pour finaliser le paiement et livrer la vidéo.",
                            notification_type='inter_user',
                            video=video,
                            sent_by=created_by_user,
                            player=video.player
                        )
            else:
                if video.advance_payment < video.total_payment:
                    # Notifier les super admins
                    super_admins = User.objects.filter(is_superuser=True)
                    for admin in super_admins:
                        create_notification(
                            user=admin,
                            message=f"📢 La vidéo {video} est terminée. Contactez le joueur via {video.player.whatsapp_number} pour finaliser le paiement et livrer la vidéo.",
                            notification_type='inter_user',
                            video=video,
                            sent_by=created_by_user,
                            player=video.player
                        )

        # 🔹 Si la vidéo est "completed_collab", notifier les super admins
        if new_status == "completed_collab":
            super_admins = User.objects.filter(is_superuser=True)
            for admin in super_admins:
                create_notification(
                    user=admin,
                    message=f"📌 La vidéo '{video}' a été finalisée par {video.editor.user.username} et attend validation par un administrateur.",
                    notification_type='inter_user',
                    video=video,
                    sent_by=created_by_user,
                    player=video.player
                )

        logger.info(f"Video status updated to {new_status}")
        # Define status icons
        status_icons = {
            "pending": "😴",
            "in_progress": "🎬",
            "completed_collab": "🏁🧑‍💻",
            "completed": "🏁",
            "delivered": "✅",
        }

        # Get icons for old and new statuses
        old_status_icon = status_icons.get(video.status, "❓")
        new_status_icon = status_icons.get(new_status, "❓")

        # Return message with icons
        return f"✅ Le statut de la vidéo de {player.name} a été mis à jour de {old_status_icon} {video.status} en {new_status_icon} '{new_status}'."
    
    except Player.DoesNotExist:
        logger.error(f"Player {player_name} not found.")
        return "❌ Joueur introuvable."
    except Exception as e:
        logger.error(f"Error updating video status: {str(e)}")
        return f"Error updating video status: {str(e)}"

async def update_video_status(player_name: str, new_status: str, user : int,video_id: int = None):
    """Run the synchronous update_video_status_sync function in a separate thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, update_video_status_sync, player_name, new_status, user,video_id)




def get_available_editors_sync():
    """Fetch a list of available video editors synchronously."""
    try:
        editors = VideoEditor.objects.filter(user__isnull=False).values_list("user__username", flat=True)
        return list(editors)
    except Exception as e:
        logger.error(f"Error fetching video editors: {str(e)}")
        return []

def update_video_editor_sync(player_name: str, new_editor: str, user_id: int,video_id: int = None):
    """Synchronously update the editor of the latest video for a given player."""
    try:
        player = Player.objects.get(name__iexact=player_name)
        video = Video.objects.filter(id=video_id).first()

        if not video:
            return f"❌ Aucun vidéo trouvé pour {player_name}."

        # Get the new editor object from VideoEditor (linked to User)
        new_editor_obj = VideoEditor.objects.get(user__username=new_editor)

        # Update the video editor
        video.editor = new_editor_obj
        video.save()

        logger.info(f"Editor updated successfully for {player_name} to {new_editor}.")
        return f"✅ L'éditeur a été mis à jour avec succès : {new_editor}"
    except Player.DoesNotExist:
        return "❌ Joueur introuvable."
    except VideoEditor.DoesNotExist:
        return "❌ Éditeur introuvable."
    except Exception as e:
        logger.error(f"Error updating editor for {player_name}: {str(e)}")
        return f"❌ Erreur lors de la mise à jour de l'éditeur: {str(e)}"
    

async def get_available_editors():
    """Fetch a list of available video editors asynchronously."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, get_available_editors_sync)

async def update_video_editor(player_name: str, new_editor: str, user_id: int,video_id: int = None):
    """Run the synchronous update_video_editor_sync function in a separate thread asynchronously."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, update_video_editor_sync, player_name, new_editor, user_id,video_id)