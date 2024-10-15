from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, RegexValidator
from django.core.exceptions import ValidationError



class Player(models.Model):
    LEAGUE_CHOICES = [
        ('L1', 'Ligue 1 Tunisie'),
        ('L2', 'Ligue 2 Tunisie'),
        ('LY', 'Libye'),
        ('OC', 'Other Country'),
    ]

    name = models.CharField(max_length=100, default="", verbose_name="Player Name")
    club = models.CharField(max_length=100, default="", verbose_name="Club Name")
    email = models.EmailField(default="", verbose_name="Email Address")
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
        COMPLETED = 'completed', 'Completed'
        DELIVERED = 'delivered', 'Delivered'
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    editor = models.ForeignKey(VideoEditor, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.PENDING)
    advance_payment = models.DecimalField(max_digits=10, decimal_places=2)
    total_payment = models.DecimalField(max_digits=10, decimal_places=2)
    deadline = models.DateField(validators=[validate_deadline])
    video_link = models.URLField(blank=True, null=True)
    info = models.TextField(blank=True, null=True, verbose_name="Info", help_text="Additional information about the video.")
      
    def remaining_balance(self):
        """Calculates the remaining balance after advance payment."""
        return self.total_payment - self.advance_payment
    
    def __str__(self):
        return f"Video for {self.player.name} by {self.editor.user.username}"


class VideoStatusHistory(models.Model):
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='status_history')
    editor = models.ForeignKey(VideoEditor, on_delete=models.CASCADE)
    status = models.CharField(max_length=20)
    changed_at = models.DateTimeField(default=timezone.now)
    comment = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.status} by {self.editor.user.username} on {self.changed_at} for {self.video}"


class Payment(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    video = models.ForeignKey(Video, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField(auto_now_add=True)
    payment_type = models.CharField(max_length=50, choices=[('advance', 'Advance'), ('final', 'Final')])
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)  # Ajout du champ
    remaining_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)


    def __str__(self):
        return f"{self.player.name} - {self.amount} ({self.payment_type})"