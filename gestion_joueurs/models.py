from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User

class Player(models.Model):
    name = models.CharField(max_length=100,default="")
    club = models.CharField(max_length=100,default="")
    email = models.EmailField(default="player@gmail.com")
    age = models.IntegerField(blank=True, null=True)
    whatsapp_number = models.CharField(max_length=15, blank=True, null=True)
    
    def __str__(self):
        return f'{self.name} ({self.club})'

class VideoEditor(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE,null=True, blank=True)

    def __str__(self):
        return self.user.username

class Video(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    editor = models.ForeignKey(VideoEditor, on_delete=models.CASCADE)
    status_choices = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('delivered', 'Delivered'),
    ]
    status = models.CharField(max_length=20, choices=status_choices, default='pending')
    advance_payment = models.DecimalField(max_digits=10, decimal_places=2)
    total_payment = models.DecimalField(max_digits=10, decimal_places=2)
    deadline = models.DateField()
    video_link = models.URLField(blank=True, null=True)

    def __str__(self):
        return f"Video for {self.player.name} by {self.editor.name}"

class VideoStatusHistory(models.Model):
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='status_history')
    editor = models.ForeignKey(VideoEditor, on_delete=models.CASCADE)
    status = models.CharField(max_length=20)
    changed_at = models.DateTimeField(default=timezone.now)
    comment = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.status} by {self.editor.name} on {self.changed_at} for {self.video}"
