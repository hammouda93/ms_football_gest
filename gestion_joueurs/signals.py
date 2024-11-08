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
    if not should_process_signals():
        return  # Skip processing if the flag is set to False
    
    user = instance.editor.user if instance.editor and instance.editor.user else None
    total_payment = Decimal(instance.total_payment or '0.00')
    advance_payment = Decimal(instance.advance_payment or '0.00')
    
    print(f"Processing Video: {instance.id}, Created: {created}, Total Payment: {total_payment}, Advance Payment: {advance_payment}")

    # Get or create an invoice for the video
    invoice, _ = Invoice.objects.get_or_create(video=instance)

    # Use a transaction to ensure atomic operations
    with transaction.atomic():
        if created:  # If a new video has been created
            print(f"Creating new invoice for Video: {instance.id}")
            # Set the total amount for the invoice
            invoice.total_amount = total_payment
            invoice.amount_paid = Decimal('0.00')
            invoice.status = 'unpaid'
            invoice.created_by = user
            invoice.save()
            print(f"New invoice created: {invoice.id} with total amount {total_payment}")

        # Handle payments for both creation and updates
        if advance_payment > 0 and not created:
            print(f"Processing advance payment for Video: {instance.id}")

            # Update the invoice amount paid
            previous_amount_paid = invoice.amount_paid
            invoice.total_amount = total_payment
            print(f"Invoice Total Amount : New : {total_payment} , Old :{invoice.total_amount} ")
            # Check for existing payments
            existing_payment = Payment.objects.filter(video=instance).first()

            # Create or update payment record
            if not existing_payment:
                print("No existing payment found, creating a new one.")
                invoice.amount_paid = advance_payment
                
                if invoice.amount_paid == 0:
                    invoice.status = 'unpaid'
                else:
                    invoice.status = 'partially_paid' if invoice.amount_paid < invoice.total_amount else 'paid'
                invoice.save()
                
                # Determine payment type
                payment_type = 'final' if invoice.amount_paid >= invoice.total_amount else 'advance'
                Payment.objects.create(
                    player=instance.player,
                    video=instance,
                    amount=advance_payment,
                    payment_type=payment_type,
                    created_by=user,
                    remaining_balance=invoice.total_amount - invoice.amount_paid,
                    invoice=invoice
                )
                print(f"New payment created for Video: {instance.id} with amount {advance_payment}")

            else:
                print("Existing payment found, updating it.")
                
                # Log the current state before updating
                print(f"Current existing payment details for Video: {instance.id} - Amount: {existing_payment.amount}, Remaining Balance: {existing_payment.remaining_balance}")

                # Update the existing payment details
                existing_payment.amount = advance_payment
                existing_payment.remaining_balance = invoice.total_amount - advance_payment

                # Check all payments for the video instance
                payments = Payment.objects.filter(video=instance)
                for payment in payments:
                    print(f"Payment amount: {payment.amount}")
                # Aggregate to see what the sum should be
                
  
                # Save the existing payment record
                existing_payment.save()
                total_existing_payments = payments.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
                invoice.amount_paid = total_existing_payments

                
                # Determine payment type
                payment_type = 'final' if invoice.amount_paid >= invoice.total_amount else 'advance'
                existing_payment.payment_type = payment_type
                existing_payment.save()

                # Update the invoice status
                if invoice.amount_paid == 0:
                    invoice.status = 'unpaid'
                else:
                    invoice.status = 'partially_paid' if invoice.amount_paid < invoice.total_amount else 'paid'
                
                invoice.save()
                print(f"Invoice status updated for Video: {instance.id} - New Status: {invoice.status}")

           

@receiver(post_save, sender=Video)
def set_league_and_club(sender, instance, created, **kwargs):
    if created:
        player = instance.player
        instance.league = player.league
        instance.club = player.club
        instance.save(update_fields=['league', 'club'])





