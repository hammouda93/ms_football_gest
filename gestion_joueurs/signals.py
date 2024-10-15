# signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Video, VideoStatusHistory, Player, Payment
from django.utils import timezone

@receiver(post_save, sender=Video)
def create_video_status_history(sender, instance, created, **kwargs):
    if created:
        VideoStatusHistory.objects.create(
            video=instance,
            editor=instance.editor,
            status=instance.status,
            changed_at=timezone.now(),
            comment="Video created."
        )
    else:
        # Vérifier si le statut a changé
        previous_status = VideoStatusHistory.objects.filter(video=instance).order_by('-changed_at').first()
        if previous_status and previous_status.status != instance.status:
            comment = "Status changed."  # Valeur par défaut
            if instance.status == 'delivered':
                comment = "Video Delivered."  # Commentaire spécifique pour le statut "delivered"

            VideoStatusHistory.objects.create(
                video=instance,
                editor=instance.editor,
                status=instance.status,
                changed_at=timezone.now(),
                comment=comment
            )

@receiver(post_save, sender=Video)
def update_payment_for_video(sender, instance, created, **kwargs):
    user = instance.editor.user if instance.editor and instance.editor.user else None
    
    payments = []
    total_payment = instance.total_payment
    advance_payment = instance.advance_payment

    # Calculer le reste à payer
    remaining_balance = total_payment - advance_payment

    if created:  # Si une nouvelle vidéo a été créée
        if advance_payment == total_payment:
            # Enregistrer uniquement le paiement final si l'avance est égale au total
            payments.append(Payment(
                player=instance.player,
                video=instance,
                amount=total_payment,
                payment_type='final',
                payment_date=timezone.now(),
                created_by=user,
                remaining_balance=0.00  # Reste à payer est 0
            ))
        else:
            # Enregistrer uniquement le paiement d'avance
            if advance_payment > 0:
                payments.append(Payment(
                    player=instance.player,
                    video=instance,
                    amount=advance_payment,
                    payment_type='advance',
                    payment_date=timezone.now(),
                    created_by=user,
                    remaining_balance=remaining_balance  # Reste à payer calculé
                ))

    else:  # Si la vidéo a été modifiée
        if advance_payment == total_payment:
            # Enregistrer uniquement le paiement final si l'avance est égale au total
            payments.append(Payment(
                player=instance.player,
                video=instance,
                amount=total_payment,
                payment_type='final',
                payment_date=timezone.now(),
                created_by=user,
                remaining_balance=0.00  # Reste à payer est 0
            ))
        else:
            # Enregistrer uniquement le paiement d'avance
            if advance_payment > 0:
                payments.append(Payment(
                    player=instance.player,
                    video=instance,
                    amount=advance_payment,
                    payment_type='advance',
                    payment_date=timezone.now(),
                    created_by=user,
                    remaining_balance=remaining_balance  # Reste à payer calculé
                ))

    # Créer les paiements en une seule opération
    if payments:
        Payment.objects.bulk_create(payments)