import threading
from django.conf import settings
from .models import Notification,Video,Invoice,Player,Payment,VideoStatusHistory,User
from django.utils import timezone
import logging
from asgiref.sync import sync_to_async, asyncio  # Fix for async Django ORM queries
import threading
from datetime import datetime, timedelta
from decimal import Decimal

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
    """Synchronous function to fetch players by video status."""
    try:
        logger.info(f"Fetching players for status: {status}")
        normalized_status = status.strip().lower().replace(" ", "_")

        videos = list(Video.objects.filter(status=normalized_status))
        players = [video.player.name for video in videos]

        logger.info(f"Players found: {players}" if players else f"No players found for this status '{normalized_status}'.")

        return players if players else [f"No players found for status '{normalized_status}'."]

    except Exception as e:
        logger.error(f"Error fetching players: {e}")
        return [f"Error fetching players: {str(e)}"]

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





def fetch_videos_by_deadline_sync(deadline_filter: str):
    """Fetch videos based on deadline filters."""
    try:
        today = datetime.now().date()
        # Filtering by deadline and excluding 'delivered' and 'problematic' status
        if deadline_filter == 'past':
            videos = Video.objects.filter(deadline__lt=today).exclude(status__in=['delivered', 'problematic'])
        elif deadline_filter == 'today':
            videos = Video.objects.filter(deadline=today).exclude(status__in=['delivered', 'problematic'])
        elif deadline_filter == '3_days':
            three_days_from_now = today + timedelta(days=3)
            videos = Video.objects.filter(deadline__gte=today, deadline__lte=three_days_from_now).exclude(status__in=['delivered', 'problematic'])
        elif deadline_filter == '1_week':
            one_week_from_now = today + timedelta(weeks=1)
            videos = Video.objects.filter(deadline__gte=today, deadline__lte=one_week_from_now).exclude(status__in=['delivered', 'problematic'])
        elif deadline_filter == '2_weeks':
            two_weeks_from_now = today + timedelta(weeks=2)
            videos = Video.objects.filter(deadline__gte=today, deadline__lte=two_weeks_from_now).exclude(status__in=['delivered', 'problematic'])
        elif deadline_filter == '1_month':
            one_month_from_now = today + timedelta(days=30)
            videos = Video.objects.filter(deadline__gte=today, deadline__lte=one_month_from_now).exclude(status__in=['delivered', 'problematic'])
        else:
            return ["Invalid deadline filter"]

        return [f"{video.player.name} - {video.deadline}" for video in videos] if videos else ["No videos found for this period."]
    
    except Exception as e:
        return [f"Error fetching videos: {str(e)}"]

async def get_videos_by_deadline(deadline_filter: str):
    """Run the fetch_videos_by_deadline_sync function in a separate thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_videos_by_deadline_sync, deadline_filter)


def fetch_players_by_invoice_status_sync(status: str):
    """Fetch players whose invoices have the specified status."""
    try:
        invoices = Invoice.objects.filter(status=status).exclude(video__status='problematic')
        players = [invoice.video.player.name for invoice in invoices if invoice.video and invoice.video.player]

        if players:
            return players
        return [f"No players found with invoice status '{status}'."]

    except Exception as e:
        return [f"Error fetching players: {str(e)}"]

async def get_players_by_invoice_status(status: str):
    """Run fetch_players_by_invoice_status_sync in a separate thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_players_by_invoice_status_sync, status)


#Payment
def fetch_payment_details_sync(player_name: str):
    """Synchronous function to fetch the payment details of a player."""
    try:
        logger.info(f"Fetching payment details for player: {player_name}")
        player = Player.objects.get(name__iexact=player_name)  # Case-insensitive search
        logger.info(f"Player {player_name} found.")

        video = Video.objects.filter(player=player).order_by("-video_creation_date").first()  # Get the first video linked to the player
        if not video:
            logger.warning(f"No video found for player {player_name}.")
            return f"No video found for player {player_name}."
        
        video_status = video.status
        invoice = Invoice.objects.filter(video=video).first()  # Get the related invoice
        
        if not invoice:
            logger.warning(f"No invoice found for player {player_name}'s video.")
            return f"No invoice found for {player_name}'s video."
        
        logger.info(f"Invoice found: {invoice.amount_paid}/{invoice.total_amount} - {invoice.status}")
        response = f"{player.name} paid {invoice.amount_paid} of {invoice.total_amount}: the video is {invoice.status}. (status: {video_status})"
        
        return response, player.id, video_status,player.name

    except Player.DoesNotExist:
        logger.error(f"Player {player_name} not found.")
        return "❌ Joueur introuvable.", None, None, None
    except Exception as e:
        logger.error(f"Error fetching payment details for player {player_name}: {str(e)}")
        return f"Error fetching payment details: {str(e)}", None, None, None

async def get_payment_details(player_name: str):
    """Run the synchronous fetch_payment_details_sync function in a separate thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_payment_details_sync, player_name)

def process_payment_sync(player_id: int, amount: float, payment_method: str, user: int):
    """Synchronous function to process payment and update the invoice."""
    try:
        logger.info(f"Processing payment of {amount} for player {player_id} using {payment_method}.")
        player = Player.objects.get(id=player_id)
        video = Video.objects.filter(player=player).order_by("-video_creation_date").first()
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
            created_by_id=created_by_user ,
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

async def process_payment(player_id: int, amount: float, payment_method: str, user: int):
    """Run the synchronous process_payment_sync function in a separate thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, process_payment_sync, player_id, amount, payment_method, user)





def update_video_status_sync(player_name: str, new_status: str, user : int):
    """Synchronously update the status of the latest video for a given player."""
    try:
        logger.info(f"Updating video status for player: {player_name} to {new_status}")
        logger.info(f"Updating video by the user in utilis.py: {user}")
        player = Player.objects.get(name__iexact=player_name)
        video = Video.objects.filter(player=player).order_by("-video_creation_date").first()

        if not video:
            logger.warning(f"No video found for player {player_name}.")
            return f"No video found for player {player_name}."
        
        if video.status == new_status:
            logger.info(f"Status is already '{new_status}', no update needed.")
            return f"ℹ️ Le statut est déjà '{new_status}'. Aucune modification effectuée."

        previous_status = video.status
        video.status = new_status
        video.save()
        # 🔹 Récupérer l'utilisateur Django en fonction de l'ID Telegram
        created_by_user = User.objects.get(id=1) if user == 5853993816 else User.objects.get(id=2)
        # Log the status change
        VideoStatusHistory.objects.create(
            video=video,
            editor=video.editor,
            status=new_status,
            changed_at=timezone.now(),
            created_by_id = created_by_user,
            comment=f"Status changed"
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
                            recipient=admin,
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
                            recipient=admin,
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
                    recipient=admin,
                    message=f"📌 La vidéo '{video}' a été finalisée par {video.editor.user.username} et attend validation par un administrateur.",
                    notification_type='inter_user',
                    video=video,
                    sent_by=created_by_user,
                    player=video.player
                )

        logger.info(f"Video status updated to {new_status}")
        return f"✅ Le statut de la vidéo de {player.name} a été mis à jour en '{new_status}'."
    
    except Player.DoesNotExist:
        logger.error(f"Player {player_name} not found.")
        return "❌ Joueur introuvable."
    except Exception as e:
        logger.error(f"Error updating video status: {str(e)}")
        return f"Error updating video status: {str(e)}"

async def update_video_status(player_name: str, new_status: str, user : int):
    """Run the synchronous update_video_status_sync function in a separate thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, update_video_status_sync, player_name, new_status, user)