from .models import Notification


def notifications(request):
    user_notifications = []
    unread_notifications_count = 0
    if request.user.is_authenticated:
        unread_notifications = Notification.objects.filter(
            user=request.user,
            is_read=False,
        ).select_related('video', 'player').order_by('-created_at')
        unread_notifications_count = unread_notifications.count()
        user_notifications = unread_notifications[:8]
    
    return {
        'notifications': user_notifications,
        'unread_notifications_count': unread_notifications_count,
    }
