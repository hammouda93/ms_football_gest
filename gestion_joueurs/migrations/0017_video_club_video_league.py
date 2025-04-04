# Generated by Django 4.2.16 on 2024-10-18 20:16

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion_joueurs', '0016_player_date_of_birth'),
    ]

    operations = [
        migrations.AddField(
            model_name='video',
            name='club',
            field=models.CharField(default='', max_length=100, verbose_name='Club Name'),
        ),
        migrations.AddField(
            model_name='video',
            name='league',
            field=models.CharField(choices=[('L1', 'Ligue 1 Tunisie'), ('L2', 'Ligue 2 Tunisie'), ('LY', 'Libye'), ('OC', 'Other Country')], default='L1', max_length=2, verbose_name='League'),
        ),
    ]
