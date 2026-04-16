from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Video, VideoStatusHistory, Player, Payment, Invoice, Salary, Expense
from django.utils import timezone
from decimal import Decimal
from django.db import transaction
from .utils import get_current_user,create_notification
from django.contrib.auth.models import User
from .views import thread_local
from .utils import should_process_signals  # Import the utility functions
from django.db.models import Sum
import logging
# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

@receiver(post_save, sender=Video)
def create_video_status_history(sender, instance, created, **kwargs):
    user = instance.editor.user if instance.editor and instance.editor.user else None
    User_Connected = get_current_user()
    
    if created:
        # Créer l'historique du statut de la vidéo
        VideoStatusHistory.objects.create(
            video=instance,
            editor=instance.editor,
            status=instance.status,
            changed_at=timezone.now(),
            created_by=get_current_user(),
            comment="Video created."
        )
        print(f"'user connected :'{User_Connected}")
        # Notifier l'éditeur de la nouvelle vidéo
        if user and user != User_Connected:
            create_notification(user, f"Vous avez été assigné à une nouvelle vidéo : {instance}", 'inter_user', video=instance,sent_by=User_Connected,player=instance.player)

        # Vérifier si le statut de la vidéo est "completed" lors de la création
        if instance.status == 'completed':
            if instance.advance_payment <= instance.total_payment :
                # Notifier les super admins
                super_admins = User.objects.filter(is_superuser=True)
                for admin in super_admins:
                    create_notification(admin, f"la {instance} est finie, contacter le joueur via {instance.player.whatsapp_number} pour finaliser le payement livrer la vidéo", 'inter_user', video=instance,sent_by=User_Connected,player=instance.player)

    else:
        logger.info("we are in signals.py")
        previous_status = VideoStatusHistory.objects.filter(video=instance).order_by('-changed_at').first()
        previous_editor = getattr(thread_local, 'previous_editor', None)
        new_editor = instance.editor

        if previous_editor and previous_editor != new_editor:
            if new_editor.user and not new_editor.user.is_superuser:
                create_notification(new_editor.user, f"Vous avez été assigné à une nouvelle vidéo : {instance}", video=instance,sent_by=User_Connected,player=instance.player)

        if previous_status and previous_status.status != instance.status:
            comment = "Status changed."
            if instance.status == 'delivered':
                comment = "Video Delivered."

            VideoStatusHistory.objects.create(
                video=instance,
                editor=instance.editor,
                status=instance.status,
                changed_at=timezone.now(),
                created_by=get_current_user(),
                comment=comment
            )

            # Vérifier si le statut de la vidéo est "completed"
            if instance.status == 'completed':
                invoice = instance.invoices  # Récupérer l'objet Invoice
                if invoice:  # Vérifier si l'invoice existe
                    invoice_status = invoice.status
                    if invoice_status != 'paid':
                        # Notifier les super admins
                        super_admins = User.objects.filter(is_superuser=True)
                        for admin in super_admins:
                            create_notification(admin, f"la {instance} est finie, contacter le joueur via {instance.player.whatsapp_number} pour finaliser le payement livrer la vidéo", 'inter_user', video=instance,sent_by=User_Connected,player=instance.player)
                else:
                    if instance.advance_payment <= instance.total_payment :
                        # Notifier les super admins
                        super_admins = User.objects.filter(is_superuser=True)
                        for admin in super_admins:
                            create_notification(admin, f"la {instance} est finie, contacter le joueur via {instance.player.whatsapp_number} pour finaliser le payement livrer la vidéo", 'inter_user', video=instance,sent_by=User_Connected,player=instance.player)
            if not User_Connected.is_superuser:
                print('user is not super admin')
                if instance.status == 'completed_collab':
                    super_admins = User.objects.filter(is_superuser=True)
                    for admin in super_admins:
                        create_notification(admin, f"La '{instance}' a été finie par {instance.editor.user.username} et en attente de finition par l'un des admins.", 'inter_user', video=instance,sent_by=User_Connected,player=instance.player)


@receiver(post_save, sender=Video)
def update_payment_for_video(sender, instance, created, **kwargs):
    """
    La création / mise à jour financière est maintenant gérée explicitement dans la vue.
    On ne fait plus de logique comptable ici pour éviter les doublons et incohérences.
    """
    return

           

@receiver(post_save, sender=Video)
def set_league_and_club(sender, instance, created, **kwargs):
    if created:
        player = instance.player
        instance.league = player.league
        instance.club = player.club
        instance.save(update_fields=['league', 'club'])





