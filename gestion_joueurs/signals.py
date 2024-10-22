from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Video, VideoStatusHistory, Player, Payment, Invoice, Salary, Expense
from django.utils import timezone
from decimal import Decimal
from django.db import transaction


@receiver(post_save, sender=Video)
def create_video_status_history(sender, instance, created, **kwargs):
    user = instance.editor.user if instance.editor and instance.editor.user else None
    if created:
        VideoStatusHistory.objects.create(
            video=instance,
            editor=instance.editor,
            status=instance.status,
            changed_at=timezone.now(),
            comment="Video created."
        )
    else:
        previous_status = VideoStatusHistory.objects.filter(video=instance).order_by('-changed_at').first()
        if previous_status and previous_status.status != instance.status:
            comment = "Status changed."
            if instance.status == 'delivered':
                comment = "Video Delivered."

            VideoStatusHistory.objects.create(
                video=instance,
                editor=instance.editor,
                status=instance.status,
                changed_at=timezone.now(),
                created_by=user,
                comment=comment
            )

@receiver(post_save, sender=Video)
def update_payment_for_video(sender, instance, created, **kwargs):
    user = instance.editor.user if instance.editor and instance.editor.user else None
    total_payment = Decimal(instance.total_payment or '0.00')
    advance_payment = Decimal(instance.advance_payment or '0.00')

    # Get or create an invoice for the video
    invoice, _ = Invoice.objects.get_or_create(video=instance)

    # Use a transaction to ensure atomic operations
    with transaction.atomic():
        if created:  # If a new video has been created
            # Set the total amount for the invoice
            invoice.total_amount = total_payment
            invoice.amount_paid = Decimal('0.00')
            invoice.status = 'unpaid'
            invoice.created_by = user
            invoice.save()

        # Handle payments for both creation and updates
        if advance_payment > 0:
            # Update the invoice amount paid
            previous_amount_paid = invoice.amount_paid
            invoice.amount_paid = advance_payment
            invoice.status = 'partially_paid' if invoice.amount_paid < invoice.total_amount else 'paid'
            invoice.save()

            # Determine payment type
            payment_type = 'final' if invoice.amount_paid >= invoice.total_amount else 'advance'

            # Check for existing payments
            existing_payment = Payment.objects.filter(video=instance, payment_type=payment_type).first()

            # Create or update payment record
            if not existing_payment:
                Payment.objects.create(
                    player=instance.player,
                    video=instance,
                    amount=advance_payment,
                    payment_type=payment_type,
                    created_by=user,
                    remaining_balance=invoice.total_amount - invoice.amount_paid,
                    invoice=invoice
                )
            else:
                # Update existing payment record if needed
                existing_payment.amount = advance_payment
                existing_payment.remaining_balance = invoice.total_amount - invoice.amount_paid
                existing_payment.save()
            
""" @receiver(post_save, sender=Payment)
def update_invoice_on_payment(sender, instance, created, **kwargs):
    # Update the invoice based on the payment
    if created:
        invoice = instance.invoice
        if invoice:
            invoice.amount_paid += instance.amount
            invoice.status = 'paid' if invoice.amount_paid >= invoice.total_amount else 'partially_paid'
            invoice.save()   """            

@receiver(post_save, sender=Video)
def set_league_and_club(sender, instance, created, **kwargs):
    if created:
        player = instance.player
        instance.league = player.league
        instance.club = player.club
        instance.save(update_fields=['league', 'club'])


""" @receiver(post_save, sender=Salary)
def create_expense_for_salary(sender, instance, created, **kwargs):
    if created:
        Expense.objects.create(
            description=f"Salaire pour {instance.user.username}",
            amount=instance.amount,
            date=instance.date,
            created_by=instance.created_by,
            category='salary',
            salary=instance  # Lier la dépense au salaire
        ) """



