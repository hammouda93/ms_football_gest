import threading
from django.conf import settings
from .models import Notification,Video,Invoice,Player
from django.utils import timezone
import logging
from asgiref.sync import sync_to_async, asyncio  # Fix for async Django ORM queries
import threading



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

        logger.info(f"Players found: {players}" if players else f"No players found for status '{normalized_status}'.")

        return players if players else [f"No players found for status '{normalized_status}'."]

    except Exception as e:
        logger.error(f"Error fetching players: {e}")
        return [f"Error fetching players: {str(e)}"]

async def get_players_by_status(status: str):
    """Run the synchronous fetch_players_sync function in a separate thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_players_sync, status)



def fetch_payment_details_sync(player_name: str):
    """Synchronous function to fetch the payment details of a player."""
    try:
        player = Player.objects.get(name__iexact=player_name)  # Case-insensitive search
        video = Video.objects.filter(player=player).first()  # Get the first video linked to the player
        
        if not video:
            return f"No video found for player {player_name}."
        
        invoice = Invoice.objects.filter(video=video).first()  # Get the related invoice
        
        if not invoice:
            return f"No invoice found for {player_name}'s video."
        
        return f"{player.name} paid {invoice.amount_paid} of {invoice.total_amount}: the video is {invoice.status}."
    
    except Player.DoesNotExist:
        return f"No player found with the name {player_name}."
    except Exception as e:
        return f"Error fetching payment details: {str(e)}"

async def get_payment_details(player_name: str):
    """Run the synchronous fetch_payment_details_sync function in a separate thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_payment_details_sync, player_name)