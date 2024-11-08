from celery import shared_task
from ms_football_gest.celery import app
from celery import shared_task
from django.utils import timezone
from django.db import models
from .models import Video, Notification ,Player,FinancialReport,Invoice, NonVideoIncome,Expense
from .utils import create_notification
import logging
from datetime import timedelta
from django.contrib.auth.models import User
from django.db.models import Q
from django.db.models import Sum
logger = logging.getLogger(__name__)

#@shared_task
def notify_birthday():
    logger.info("Starting birthday notification task.")

    tomorrow = timezone.now().date() + timedelta(days=1)
    tomorrow_day_month = (tomorrow.day, tomorrow.month)
    logger.info(f"Checking for players with birthdays on {tomorrow}.")

    # Filter players whose birthday is tomorrow, ignoring the year
    players = Player.objects.filter(
        Q(date_of_birth__day=tomorrow.day) & Q(date_of_birth__month=tomorrow.month)
    )
    logger.info(f"Found {players.count()} player(s) with a birthday tomorrow.")

    # Get all superusers
    super_users = User.objects.filter(is_superuser=True)
    logger.info(f"Found {super_users.count()} superuser(s) to notify.")

    for player in players:
        # Check if a birthday notification was sent in the last year
        last_notification = Notification.objects.filter(
            player=player,
            notification_type='birthday'
        ).order_by('-sent_at').first()

        if last_notification:
            days_since_last_notification = (timezone.now() - last_notification.sent_at).days
            logger.info(f"Last birthday notification for {player.name} was sent {days_since_last_notification} days ago.")

        # Determine if we should send a new notification
        if not last_notification or days_since_last_notification >= 360:
            message = f"Demain c'est l'anniversaire de {player.name}. "
            if player.client_fidel:
                message += "C'est un client fidèle. "
            if player.client_vip:
                message += "C'est un client VIP. "

            if player.whatsapp_number:
                message += f" Féliciter le sur WhatsApp au numéro : {player.whatsapp_number}."

            # Send the notification to each superuser
            for user in super_users:
                create_notification(
                    user=user,
                    message=message,
                    notification_type='birthday',
                    video=None,
                    player=player,
                )
                logger.info(f"Birthday notification sent to superuser: {user.username} for player: {player.name}")
        else:
            logger.info(f"Skipping notification for {player.name}; already sent a birthday notification within the last year.")

    logger.info("Completed birthday notification task.")



#@shared_task
def notify_pending_videos():
    threshold_time = timezone.now() + timedelta(days=2, hours=12)
    videos = Video.objects.filter(status='pending', deadline__lte=threshold_time)
    
    # Get all superusers
    super_users = User.objects.filter(is_superuser=True)

    logger.info(f"Checking for pending videos due by {threshold_time}. Found {videos.count()} videos.")

    for video in videos:
        invoice = video.invoices  # Use 'invoices' instead of 'invoice'
        if invoice.status == 'partially_paid':
            message = (
                f"'{video}' : Contactez le joueur via {video.player.whatsapp_number} pour finaliser le paiement avant le {video.deadline}. '{video.status}' : {invoice.status} "
            )
            notification_type = 'pending_payment'
        elif invoice.status == 'unpaid' :
            message = (
                f"'{video}' : Contactez le joueur via {video.player.whatsapp_number} pour vérifier s'il a encore besoin de la video. '{video.status}' : {invoice.status} "
            )
            notification_type = 'pending_check'
        elif invoice.status == 'paid':
            message = f"Commencez l'édition de la '{video}' immédiatement car la video est totalement payée. '{video.status}' : {invoice.status}"
            notification_type = 'start_editing'
        else:
            logger.warning(f"No valid payment status for  '{video}'. Skipping...")
            continue  # Skip if none of the conditions are met

        # Check if a notification of this type has already been sent for the video
        existing_notification = Notification.objects.filter(video=video, notification_type=notification_type, sent_at__isnull=False).exists()
        if existing_notification:
            logger.info(f"Notification of type '{notification_type}' already sent for '{video}'. Skipping...")
            continue  # Skip to the next video if already notified

        # Send notifications to super admins
        for user in super_users:
            create_notification(user, message, notification_type=notification_type, player=video.player,video=video)
            logger.info(f"Sent '{notification_type}' notification to {user.username} for '{video}'.")

    logger.info("Notification process completed.")

#@shared_task
def notify_in_progress_or_completed_collab_videos():
    threshold_time = timezone.now() + timedelta(days=1, hours=12)
    videos = Video.objects.filter(
        status__in=[Video.StatusChoices.IN_PROGRESS, Video.StatusChoices.COMPLETED_COLLAB],
        deadline__lte=threshold_time
    )

    # Get all superusers
    super_users = User.objects.filter(is_superuser=True)

    logger.info(f"Checking for videos in progress or completed collab due by {threshold_time}. Found {videos.count()} videos.")

    for video in videos:
        invoice = video.invoices  # Use the related name to access the invoice

        if invoice and invoice.status == 'partially_paid':
            message = (
                f"'{video}' : Contactez le joueur via {video.player.whatsapp_number} pour finaliser le paiement de la vidéo . "
                f"Le délai approche: {video.deadline}.  '{video.status}' : {invoice.status}"
            )
            notification_type = 'inprogress_payment'
        elif invoice and invoice.status == 'unpaid':
            message = (
                f"'{video}' : Contactez le joueur via {video.player.whatsapp_number} pour commencer le payement, la vidéo sera bientôt finie {video.deadline}.  '{video.status}' : {invoice.status}"
            )
            notification_type = 'inprogress_check'
        else:
            logger.warning(f"No valid payment status for video '{video}'. Skipping...")
            continue  # Skip if no valid invoice is found

        # Check if a notification of this type has already been sent for the video
        existing_notification = Notification.objects.filter(video=video, notification_type=notification_type, sent_at__isnull=False).exists()
        if existing_notification:
            logger.info(f"Notification of type '{notification_type}' already sent for video '{video}'. Skipping...")
            continue  # Skip to the next video if already notified

        # Send notifications to super admins
        for user in super_users:
            create_notification(user, message, notification_type=notification_type, player=video.player,video=video)
            logger.info(f"Sent '{notification_type}' notification to {user.username} for video '{video}'.")

    logger.info("Notification process completed.")


#@shared_task
def notify_past_deadline_status_videos():
    now = timezone.now()
    cutoff_time = now - timezone.timedelta(days=2)  # Set cutoff for 3 days past the deadline

    # Get all videos that have passed their deadline and are overdue by at least 3 days
    past_videos = Video.objects.filter(deadline__lt=cutoff_time)

    # Get all superusers
    super_users = User.objects.filter(is_superuser=True)

    logger.info(f"Checking for past deadline videos. Found {past_videos.count()} videos.")

    for video in past_videos:
        invoice = video.invoices  # Accessing the related invoice

        if video.status == Video.StatusChoices.COMPLETED:
            if invoice and invoice.status == 'paid':
                message = (
                    f" La '{video}' est en attente de livraison car le joueur a payé la totalité du montant. {invoice.status} : '{video.status}' ---> delivered "
                )
                notification_type = 'todelivered_change'
            elif invoice and invoice.status != 'paid':
                remaining_amount = invoice.total_amount - invoice.amount_paid
                message = (
                    f"'{video}' : Contactez le joueur via {video.player.whatsapp_number} finaliser le payement. RAP {remaining_amount}. '{video.status}' : {invoice.status}  " 
                )
                notification_type = 'completed_unpaid'
            else:
                logger.warning(f"No valid invoice found for video '{video}'. Skipping...")
                continue  # Skip if no valid invoice is found

        elif video.status in [Video.StatusChoices.PENDING, Video.StatusChoices.IN_PROGRESS, Video.StatusChoices.COMPLETED_COLLAB]:
            days_passed = (now.date() - video.deadline).days # Calculate days passed
            message = (
                f"'{video}' : Le délai est passé depuis {days_passed} jour(s). la video est '{video.status}' : {invoice.status} "
                f"Contacter via le joueur {video.player.whatsapp_number} pour regler la situation."
            )
            notification_type = 'deadline_passed'

        elif video.status == Video.StatusChoices.DELIVERED and invoice and invoice.status != 'paid':
            remaining_amount = invoice.total_amount - invoice.amount_paid
            message = (
                f"'{video}' : Livré Sans Recevoir la totalité de payement. Contactez le joueur via {video.player.whatsapp_number} : RAP ({remaining_amount}). '{video.status}' : {invoice.status}"
            )
            notification_type = 'delivered_unpaid'

        else:
            logger.warning(f"No valid conditions met for video '{video}'. Skipping...")
            continue  # Skip if no valid conditions are found

        # Check if a notification of this type has already been sent for the video
        existing_notification = Notification.objects.filter(video=video, notification_type=notification_type).order_by('-sent_at').first()
        if existing_notification and (now.date() - existing_notification.sent_at.date()).days < 7:
            logger.info(f"Notification of type '{notification_type}' already sent for video '{video}'. Skipping...")
            continue  # Skip if already notified within the last week

        # Send notifications to super admins
        for user in super_users:
            create_notification(user, message, notification_type=notification_type, player=video.player, video=video)
            logger.info(f"Sent '{notification_type}' notification to {user.username} for video '{video}'.")

    logger.info("Past deadline notification process completed.")

#@shared_task
def check_video_count():
    # Récupérer les vidéos avec une deadline dans 2 jours et ayant un statut 'pending', 'in_progress', ou 'completed_collab'
    now = timezone.now()
    videos = Video.objects.filter(deadline__exact=timezone.now() + timedelta(days=2), status__in=['pending', 'in_progress', 'completed_collab'])
    
    logger.info(f"Nombre de vidéos trouvées: {videos.count()}")
    
    for video in videos:
        logger.info(f"Vidéo : {video}, Statut: {video.status}, Deadline: {video.deadline}")

    if videos.count() >= 4:
        message = (f"Vous avez plus de 4 vidéos ({videos.count()}) à terminer avant la même date limite : {timezone.now() + timedelta(days=2)}")
        # Récupérer les super utilisateurs
        super_users = User.objects.filter(is_superuser=True)
        # Vérifier s'il existe déjà une notification de ce type
        existing_notification = Notification.objects.filter(notification_type='video_count', sent_at__isnull=False).order_by('-sent_at').first()
        if existing_notification:
            days_since_sent = (now.date() - existing_notification.sent_at.date()).days
            logger.warning(f"{now} - {existing_notification} ---> {days_since_sent} days since sent")
            if days_since_sent >= 1:
                for user in super_users:
                    create_notification(user, message, notification_type='video_count')
                    logger.info(f"Notification envoyée à {user.username}")  
        else:
            logger.info(f"{super_users.count()} super utilisateurs trouvés pour la notification.")
            
            # Créer une notification pour chaque super utilisateur
            for user in super_users:
                create_notification(user, message, notification_type='video_count')
                logger.info(f"Notification envoyée à {user.username}")
    else:
        logger.info("Moins de 4 vidéos à traiter, pas d'action requise.")



#@shared_task
def notify_salary_due_for_delivered_videos():
    # Calculate the threshold date (2 days after the deadline)
    threshold_date = timezone.now() - timedelta(days=2)
    
    # Find videos that are delivered and past the deadline
    delivered_videos = Video.objects.filter(status='delivered', deadline__lt=threshold_date)

    # Get all superusers
    super_users = User.objects.filter(is_superuser=True)

    logger.info(f"Checking for delivered videos past the deadline. Found {delivered_videos.count()} videos.")

    for video in delivered_videos:
        invoice = video.invoices
        if invoice : 
            if invoice.status in ['paid', 'partially_paid']:
                editor = video.editor

                # Skip sending notifications if the editor's user is a superuser
                if editor.user.is_superuser:
                    logger.info(f"Editor {editor.user.username} is a superuser. Skipping notification for video '{video}'.")
                    continue  # Skip to the next video

                # Check the salary payment status for the video editor
                if video.salary_paid_status == 'not_paid':
                    message = (
                        f"{editor.user.username} n'a pas reçu de prime pour la '{video}'. "
                        "Veuillez régler la situation de l'éditeur. "
                    )
                    notification_type = 'unpaid_salary'
                elif video.salary_paid_status == 'partially_paid':
                    message = (
                        f"{editor.user.username} attend toujours le reste de sa prime pour la '{video}'. "
                        "Veuillez régler la situation de l'éditeur. "
                    )
                    notification_type = 'p_paid_salary'
                else:
                    logger.warning(f"Unexpected salary paid status for '{editor.user.username}'. Skipping...")
                    continue
                # Check if a notification of this type has already been sent for the video
                now = timezone.now()
                existing_notification = Notification.objects.filter(video=video, notification_type=notification_type).order_by('-sent_at').first()

                if existing_notification:
                    days_since_sent = (now.date() - existing_notification.sent_at.date()).days
                    logger.warning(f"{now} - {existing_notification} ---> {days_since_sent} days since sent")
                    if days_since_sent <= 7:
                        logger.info(f"Notification of type '{notification_type}' already sent for '{video}' within the last 7 days. Skipping...")
                        continue  # Skip to the next video if already notified
                
                # Send notification to super admins
                for user in super_users:
                    create_notification(user, message, notification_type=notification_type, player=video.player, video=video)
                    logger.info(f"Sent '{notification_type}' notification to {user.username} for '{video}'.")

    logger.info("Salary notification process completed.")




#@shared_task
def generate_first_day_of_current_month_report():
    now = timezone.now()

    # Calculate the first day of the current month
    first_day_of_current_month = now.replace(day=1)

    # Check if the report for the first day of the current month already exists
    existing_first_day_report = FinancialReport.objects.filter(report_date=first_day_of_current_month).exists()

    # If the report does not exist, generate it
    if not existing_first_day_report:
        logger.info(f"Generating financial report for the first day of the current month: {first_day_of_current_month}")
        generate_report_for_day(first_day_of_current_month)
    else:
        logger.info(f"Financial report already generated for {first_day_of_current_month}. Skipping report generation.")

def generate_report_for_day(report_date):
    # Filter Invoices up to the given report date
    total_invoice_income = 0
    invoices = Invoice.objects.filter(invoice_date__lte=report_date)  # Adjust 'date' field as per your model
    for invoice in invoices:
        if invoice.amount_paid > invoice.total_amount:
            total_invoice_income += invoice.amount_paid
        else:
            total_invoice_income += invoice.total_amount

    total_paid_income = invoices.aggregate(total=Sum('amount_paid'))['total'] or 0

    # Filter Expenses up to the given report date
    expenses = Expense.objects.filter(date__lte=report_date)  # Adjust 'date' field as per your model
    total_expenses = expenses.aggregate(total=Sum('amount'))['total'] or 0

    # Filter Non-Video Income up to the given report date
    other_income = NonVideoIncome.objects.filter(date__lte=report_date).aggregate(total=Sum('amount'))['total'] or 0

    # Calculate outstanding payments and global income
    total_outstanding_payments = total_invoice_income - total_paid_income
    global_income = total_paid_income + other_income

    # Calculate net revenue if all invoices are paid
    net_revenue_if_all_paid = total_invoice_income - total_expenses

    # Create the financial report
    report = FinancialReport.objects.create(
        global_income=global_income,
        total_outstanding_income=total_outstanding_payments,
        total_income=total_paid_income,
        total_expenses=total_expenses,
        created_by=None,  # You can set this if needed
        net_revenue_if_all_paid=net_revenue_if_all_paid
    )
    report.calculate_net_profit()

    # Manually set the report_date here (will not be overridden by auto_now_add)
    report.report_date = report_date
    
    # Save the report (this will trigger auto_now_add only for the fields that need it)
    report.save()

    # Send a success message to super users
    send_report_notification(report)

def send_report_notification(report):
    # Create a custom message for the report
    report_date_str = report.report_date.strftime('%d/%m/%Y')
    message = f"Le rapport financier a été généré avec succès pour la date du {report_date_str}."

    # Get all superusers
    super_users = User.objects.filter(is_superuser=True)

    # Send the message to each superuser
    for user in super_users:
        create_notification(
            user=user,  # The superuser receiving the notification
            message=message,  # The notification message
            notification_type='financial_report',  # Custom notification type
            sent_by=None,  # The user who triggered the notification (None if it's from the system)
        )
        logger.info(f"Notification sent to {user.username}")














"""
@shared_task
def notify_pending_videos():
    videos = Video.objects.filter(status='pending', deadline__lte=timezone.now() + timedelta(days=2, hours=12))
    for video in videos:
        if video.invoice.amount_paid > 0:
            message = f"Contactez le joueur via {video.player.whatsapp} pour régler le paiement de la vidéo '{video.title}'."
            existing_notification = Notification.objects.filter(video=video, notification_type='pending_payment', sent_at__isnull=False).exists()
            if not existing_notification:
                create_notification(super_admins, message, notification_type='pending_payment', player=video.player)
        else:
            message = f"Contactez le joueur via {video.player.whatsapp} pour vérifier s'il a encore besoin de la vidéo '{video.title}'."
            existing_notification = Notification.objects.filter(video=video, notification_type='pending_check', sent_at__isnull=False).exists()
            if not existing_notification:
                create_notification(super_admins, message, notification_type='pending_check', player=video.player)


@shared_task
def notify_in_progress_videos():
    videos = Video.objects.filter(status__in=['in_progress', 'completed_collab'], deadline__lte=timezone.now() + timedelta(days=1, hours=12))
    for video in videos:
        if video.invoice.amount_paid > 0:
            message = f"Contactez le joueur via {video.player.whatsapp} pour régler le paiement de la vidéo '{video.title}'."
            existing_notification = Notification.objects.filter(video=video, notification_type='in_progress_payment', sent_at__isnull=False).exists()
            if not existing_notification:
                create_notification(super_admins, message, notification_type='in_progress_payment', player=video.player)
        else:
            message = f"Contactez le joueur via {video.player.whatsapp} pour lui dire que la vidéo sera bientôt finie."
            existing_notification = Notification.objects.filter(video=video, notification_type='in_progress_check', sent_at__isnull=False).exists()
            if not existing_notification:
                create_notification(super_admins, message, notification_type='in_progress_check', player=video.player)


@shared_task
def check_deadlines():
    videos = Video.objects.filter(deadline__lt=timezone.now()).exclude(status='delivered')
    for video in videos:
        if video.status == 'completed' and video.invoice.status != 'paid':
            amount_remaining = video.invoice.total_amount - video.invoice.amount_paid
            message = f"Appelez le joueur via {video.player.whatsapp} pour régler le montant restant: {amount_remaining}."
            existing_notification = Notification.objects.filter(video=video, notification_type='overdue_payment', sent_at__isnull=False).exists()
            if not existing_notification:
                create_notification(super_admins, message, notification_type='overdue_payment', player=video.player)
        else:
            message = f"Le délai de la vidéo '{video.title}' est passé depuis {timezone.now() - video.deadline}."
            existing_notification = Notification.objects.filter(video=video, notification_type='overdue_check', sent_at__isnull=False).exists()
            if not existing_notification:
                create_notification(super_admins, message, notification_type='overdue_check', player=video.player)


@shared_task
def check_video_count():
    videos = Video.objects.filter(deadline__lte=timezone.now() + timedelta(days=2), status__in=['pending', 'in_progress'])
    if videos.count() > 4:
        message = "Il y a plus de 4 vidéos à terminer avant la même date limite."
        existing_notification = Notification.objects.filter(notification_type='video_count', sent_at__isnull=False).exists()
        if not existing_notification:
            create_notification(super_admins, message, notification_type='video_count')


@shared_task
def check_delivered_videos():
    videos = Video.objects.filter(status='delivered', invoice__status__ne='paid')
    for video in videos:
        amount_remaining = video.invoice.total_amount - video.invoice.amount_paid
        message = f"Contactez le joueur via {video.player.whatsapp} pour régler la situation (Montant restant: {amount_remaining})."
        existing_notification = Notification.objects.filter(video=video, notification_type='delivered_check', sent_at__isnull=False).exists()
        if not existing_notification:
            create_notification(super_admins, message, notification_type='delivered_check', player=video.player)


@shared_task
def check_completed_videos():
    videos = Video.objects.filter(status='completed', deadline__lt=timezone.now())
    for video in videos:
        if video.invoice.status == 'paid':
            message = "La vidéo est finie et en attente de livraison."
        else:
            amount_remaining = video.invoice.total_amount - video.invoice.amount_paid
            message = f"La vidéo est finie mais le joueur doit payer le montant restant: {amount_remaining}."
        existing_notification = Notification.objects.filter(video=video, notification_type='completed_check', sent_at__isnull=False).exists()
        if not existing_notification:
            create_notification(super_admins, message, notification_type='completed_check', player=video.player)


@shared_task
def check_salary_after_deadline():
    videos = Video.objects.filter(status='delivered', deadline__lt=timezone.now() - timedelta(days=3))
    for video in videos:
        if video.invoice.status in ['paid', 'partially_paid']:
            if video.editor.paid_salary_status == 'unpaid':
                message = f"Régler le salaire de l'éditeur {video.editor.username}."
            elif video.editor.paid_salary_status == 'partially_paid':
                message = f"L'éditeur {video.editor.username} attend le reste de sa prime."
            existing_notification = Notification.objects.filter(video=video, notification_type='salary_notification', sent_at__isnull=False).exists()
            if not existing_notification:
                create_notification(super_admins, message, notification_type='salary_notification', player=video.player)


 """






















































@app.task
def add(x,y):
    return x + y
@shared_task
def test_taskk():
    return 'Task executed successfully!'



