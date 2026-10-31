from django.core.management.base import BaseCommand
from django.utils import timezone
from gestion_joueurs.models import Notification, Video  # Adjust import based on your app structure
from datetime import timedelta
from django.contrib.auth.models import User
from utils import create_notification

class Command(BaseCommand):
    help = 'Send reminder notifications'

    def handle(self, *args, **kwargs):
        now = timezone.now()
        # Example: Get videos with deadlines approaching in 2 days
        upcoming_deadlines = Video.objects.filter(deadline__gte=now, deadline__lte=now + timedelta(days=2))

        for video in upcoming_deadlines:
            # Check if a notification has already been sent for this video
            if not Notification.objects.filter(video=video, type='reminder').exists():
                # Notify all relevant users (e.g., editors, assigned users)
                if video.editor and video.editor.user:
                    create_notification(video.editor.user, f"Reminder: The deadline for video '{video}' is approaching!", notification_type='reminder', video=video)

        self.stdout.write(self.style.SUCCESS('Reminder notifications sent.'))