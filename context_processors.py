from .models import Notification  # Importez votre modèle Notification

def notifications(request):
    user_notifications = []
    if request.user.is_authenticated:
        user_notifications = Notification.objects.filter(user=request.user, is_read=False)  # Exclure les notifications vues
    
    return {'notifications': user_notifications}