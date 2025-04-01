import threading
from django.conf import settings
from .models import Notification,Video
from django.utils import timezone
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


#Telegram_Bot
def get_players_by_status(status: str):
    """Fetch players by video status."""
    try:
        # Filter videos by status and return player names
        videos = Video.objects.filter(status=status)
        players = [video.player.name for video in videos]  # Assuming 'name' is a field in the Player model
        return players
    except Exception as e:
        return [f"Error fetching players: {str(e)}"]