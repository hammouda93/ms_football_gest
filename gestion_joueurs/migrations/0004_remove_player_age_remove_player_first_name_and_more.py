# Generated by Django 4.2.16 on 2024-10-10 19:33

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('gestion_joueurs', '0003_remove_player_email_remove_player_name_player_age_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='player',
            name='age',
        ),
        migrations.RemoveField(
            model_name='player',
            name='first_name',
        ),
        migrations.RemoveField(
            model_name='player',
            name='last_name',
        ),
        migrations.RemoveField(
            model_name='player',
            name='whatsapp_number',
        ),
        migrations.RemoveField(
            model_name='videoeditor',
            name='name',
        ),
        migrations.AddField(
            model_name='player',
            name='email',
            field=models.EmailField(default='player@gmail.com', max_length=254),
        ),
        migrations.AddField(
            model_name='player',
            name='name',
            field=models.CharField(default='', max_length=100),
        ),
        migrations.AlterField(
            model_name='player',
            name='club',
            field=models.CharField(default='', max_length=100),
        ),
        migrations.AlterField(
            model_name='videoeditor',
            name='user',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
    ]
