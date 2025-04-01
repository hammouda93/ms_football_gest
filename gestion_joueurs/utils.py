import threading
from django.conf import settings
from .models import Notification,Video
from django.utils import timezone
import logging




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


# Function to fetch players based on video status
def get_players_by_status(status: str):
    """Fetch players by video status, ensuring normalized input."""
    try:
        logger.info(f"Fetching players for status: {status}")  # Debugging

        # Normalize status
        normalized_status = status.strip().lower().replace(" ", "_")
        logger.info(f"Normalized status: {normalized_status}")

        # Check if status is valid
        valid_statuses = {s.value for s in Video.StatusChoices}
        if normalized_status not in valid_statuses:
            logger.warning(f"Invalid status: {normalized_status}")
            return [f"Invalid status: '{normalized_status}'. Valid options: {valid_statuses}"]

        # Fetch players
        videos = Video.objects.filter(status=normalized_status)
        players = [video.player.name for video in videos]

        if players:
            logger.info(f"Players found: {players}")
        else:
            logger.info(f"No players found for status '{normalized_status}'.")

        return players if players else [f"No players found for status '{normalized_status}'."]

    except Exception as e:
        logger.error(f"Error fetching players: {e}")
        return [f"Error fetching players: {str(e)}"]