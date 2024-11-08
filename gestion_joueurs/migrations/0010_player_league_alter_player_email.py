# Generated by Django 4.2.16 on 2024-10-12 11:56

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion_joueurs', '0009_alter_player_email'),
    ]

    operations = [
        migrations.AddField(
            model_name='player',
            name='league',
            field=models.CharField(choices=[('L1', 'Ligue 1 Tunisie'), ('L2', 'Ligue 2 Tunisie'), ('LY', 'Libye'), ('OC', 'Other Country')], default='L1', help_text='Select the league the player belongs to.', max_length=2, verbose_name='League'),
        ),
        migrations.AlterField(
            model_name='player',
            name='email',
            field=models.EmailField(default='', help_text='Enter a unique email address for the player.', max_length=254, unique=True, verbose_name='Email Address'),
        ),
    ]
