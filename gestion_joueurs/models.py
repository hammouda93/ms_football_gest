from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, RegexValidator
from django.core.exceptions import ValidationError
from datetime import date
""" from .utils import send_whatsapp_message
from django.dispatch import receiver """
from django.db.models.signals import post_save


class Player(models.Model):
    LEAGUE_CHOICES = [
        ('L1', 'Ligue 1 Tunisie'),
        ('L2', 'Ligue 2 Tunisie'),
        ('LY', 'Libye'),
        ('OC', 'Other Country'),
    ]
    POSITION_CHOICES = [
        ('GK', 'Goalkeeper'),
        ('DF', 'Defender'),
        ('MF', 'Midfielder'),
        ('FW', 'Forward'),
    ]
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, default="", verbose_name="Player Name")
    club = models.CharField(max_length=100, default="", verbose_name="Club Name")
    email = models.EmailField(default="", verbose_name="Email Address")
    date_of_birth = models.DateField(blank=True, null=True)
    age = models.IntegerField(blank=True, null=True, validators=[MinValueValidator(0)], verbose_name="Age")
    whatsapp_number = models.CharField(
        max_length=15, 
        blank=True, 
        null=True, 
        validators=[RegexValidator(
            regex=r'^\+?1?\d{9,15}$', 
            message="Le numéro de WhatsApp doit être au format +999999999999 ou 999999999."
        )],
        verbose_name="WhatsApp Number",
    )
    league = models.CharField(
        max_length=2,
        choices=LEAGUE_CHOICES,
        default='L1',  # Définir la valeur par défaut à "Ligue 1 Tunisie"
        verbose_name="League",
    )
    position = models.CharField(
        max_length=2,
        choices=POSITION_CHOICES,
        default='DF',
        verbose_name="Position",
    )
    client_fidel = models.BooleanField(default=False, verbose_name="Client Fidèle")
    client_vip = models.BooleanField(default=False, verbose_name="Client VIP")
    player_creation_date = models.DateTimeField(auto_now_add=True, null=True)

    def save(self, *args, **kwargs):
        # Automatically calculate age from date_of_birth before saving
        if self.date_of_birth:
            today = date.today()
            self.age = today.year - self.date_of_birth.year - ((today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day))
        super().save(*args, **kwargs)

    def get_league_name(self):
        """Return the name of the league based on the league code."""
        return dict(self.LEAGUE_CHOICES).get(self.league, 'Unknown League')
    
    def __str__(self):
        return f'{self.name} ({self.club})'

class VideoEditor(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return self.user.username


def validate_deadline(value):
    if value < timezone.now().date():
        raise ValidationError('The deadline cannot be in the past.')

class Video(models.Model):
    class StatusChoices(models.TextChoices):
        PENDING = 'pending', 'Pending'
        IN_PROGRESS = 'in_progress', 'In Progress'
        COMPLETED_COLLAB = 'completed_collab', 'Completed Collab'
        COMPLETED = 'completed', 'Completed'
        DELIVERED = 'delivered', 'Delivered'
    class SalaryPaidStatusChoices(models.TextChoices):
        NOT_PAID = 'not_paid', 'Not Paid'
        PARTIALLY_PAID = 'partially_paid', 'Partially Paid'
        PAID = 'paid', 'Paid'
    LEAGUE_CHOICES = [
        ('L1', 'Ligue 1 Tunisie'),
        ('L2', 'Ligue 2 Tunisie'),
        ('LY', 'Libye'),
        ('OC', 'Other Country'),
    ]
    id = models.AutoField(primary_key=True)
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    editor = models.ForeignKey(VideoEditor, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.PENDING)
    advance_payment = models.DecimalField(max_digits=10, decimal_places=2)
    total_payment = models.DecimalField(max_digits=10, decimal_places=2)
    deadline = models.DateField(validators=[validate_deadline])
    video_link = models.URLField(blank=True, null=True)
    info = models.TextField(blank=True, null=True, verbose_name="Info", help_text="Additional information about the video.")
    SEASONS = [
        ('2022/2023', '2022/2023'),
        ('2023/2024', '2023/2024'),
        ('2024/2025', '2024/2025'),
        ('2025/2026', '2025/2026'),
    ]
    season = models.CharField(max_length=10, choices=SEASONS, default='2024/2025')
    club = models.CharField(max_length=100, default="", verbose_name="Club Name")
    league = models.CharField(
        max_length=2,
        choices=LEAGUE_CHOICES,
        default='L1',  # Définir la valeur par défaut à "Ligue 1 Tunisie"
        verbose_name="League",
    )
    salary_paid_status = models.CharField(
        max_length=20,
        choices=SalaryPaidStatusChoices.choices,
        default=SalaryPaidStatusChoices.NOT_PAID,  # Default value set to Not Paid
        verbose_name="Salary Payment Status"
    )
    video_creation_date = models.DateTimeField(auto_now_add=True, null=True)  # Automatically set the date/time when a video is created
    def remaining_balance(self):
        """Calculates the remaining balance after advance payment."""
        return self.total_payment - self.advance_payment
    
    def get_league_name(self):
        """Return the name of the league based on the league code."""
        return dict(self.LEAGUE_CHOICES).get(self.league, 'Unknown League')
    
    def __str__(self):
        return f"Video de {self.player.name} par {self.editor.user.username} ({self.season})"
    

class VideoStatusHistory(models.Model):
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='status_history')
    editor = models.ForeignKey(VideoEditor, on_delete=models.CASCADE)
    status = models.CharField(max_length=20)
    changed_at = models.DateTimeField(default=timezone.now)
    comment = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)  # Ajout du champ
    def __str__(self):
        return f"{self.status} by {self.editor.user.username} on {self.changed_at} for {self.video}"

    
class Invoice(models.Model):
    id = models.AutoField(primary_key=True)
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='invoices')  # Ajoutez unique=True
    invoice_date = models.DateField(auto_now_add=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=[
        ('paid', 'paid'),
        ('unpaid', 'unpaid'),
        ('partially_paid', 'partially paid'),
    ], default='unpaid')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    payment_method = models.CharField(max_length=50, choices=[
        ('cash', 'Cash'),
        ('bank_transfer', 'Virement bancaire'),
        ('la_poste', 'La poste'),
    ], blank=True, null=True)
    
    def __str__(self):
        return f"Facture pour {self.video} - Status: {self.status}"


class Payment(models.Model):
    id = models.AutoField(primary_key=True)
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField(auto_now_add=True)
    payment_type = models.CharField(max_length=50, choices=[
        ('advance', 'Advance'),
        ('final', 'Final'),
        ('partial', 'Partial'),  # Ajout d'une option pour les paiements partiels
    ])
    payment_method = models.CharField(max_length=50, choices=[
        ('cash', 'Cash'),
        ('bank_transfer', 'Virement bancaire'),
        ('la_poste', 'La poste'),
    ], blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    remaining_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')

    def __str__(self):
        return f"{self.player.name} - {self.amount} ({self.payment_type})"

class PaymentHistory(models.Model):
    id = models.AutoField(primary_key=True)
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE)
    amount_before = models.DecimalField(max_digits=10, decimal_places=2)
    amount_after = models.DecimalField(max_digits=10, decimal_places=2)
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"Change in Payment {self.payment.id} on {self.changed_at}"

class Salary(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(auto_now_add=True)
    video = models.ForeignKey('Video', on_delete=models.SET_NULL, null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='salary_creator')

    def __str__(self):
        return f"{self.user.username} - {self.amount} on {self.date}"

class Expense(models.Model):
    id = models.AutoField(primary_key=True)
    description = models.CharField(max_length=255, null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(default=timezone.now)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    category = models.CharField(max_length=100, choices=[
        ('Transport', 'Transport'),
        ('Entertainement', 'Loisirs'),
        ('Internet', 'Internet'),
        ('marketing', 'Marketing'),
        ('operational', 'Operational'),
        ('salary', 'Salary'),
        ('equipment', 'Equipment'),
        ('other', 'Other'),
    ], default='other')  # Catégorie de la dépense
    salary = models.ForeignKey('Salary', on_delete=models.SET_NULL, null=True, blank=True)
    def __str__(self):
        return f"{self.description} - {self.amount}"
    

class FinancialReport(models.Model):
    report_date = models.DateField(auto_now_add=True)
    total_income = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_expenses = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    net_profit = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)  # Revenu net
    total_outstanding_income = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    net_revenue_if_all_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    global_income = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)


    def calculate_net_profit(self):
        self.net_profit = self.total_income - self.total_expenses
        self.save()

    def __str__(self):
        return f"Financial Report for {self.report_date}"

class PaymentCategory(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name
    
class Notification(models.Model):
    TYPE_CHOICES = [
        ('inter_user', 'Inter-user Notification'),
        ('video_process', 'Video Processing Notification'),
        ('financial', 'Financial Notification'),
        ('alert', 'Alert'),
        ('reminder', 'Reminder'),
        ('update', 'Update'),
    ]
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    video = models.ForeignKey(Video, on_delete=models.CASCADE, null=True, blank=True)
    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='update')
    sent_at = models.DateTimeField(null=True, blank=True)  # New field to track when sent
    sent_by = models.ForeignKey(User, related_name="sent_notifications", on_delete=models.SET_NULL, null=True, blank=True)
    player = models.ForeignKey(Player, on_delete=models.CASCADE, null=True, blank=True)


    def __str__(self):
        return f"Notification pour {self.user.username}: {self.message}"
    

class NonVideoIncome(models.Model):
    category_choices = [
        ('freelance','Freelance'),
        ('deposit','Deposit'),
        ('coach_cv', 'CV Coach'),
        ('marketing','Marketing'),
        ('sponsorship', 'Sponsorship'),
        ('donation', 'Donation'),
        ('partnership', 'Partnership'),
        ('media', 'Media'),
        ('other', 'Other'),
    ]
    id = models.AutoField(primary_key=True)
    category = models.CharField(max_length=50, choices=category_choices)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)  # New field for user
    def __str__(self):
        return f"Revenu Non Video : {self.category} - {self.amount} ({self.date})"