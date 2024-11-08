# Generated by Django 4.2.16 on 2024-10-28 12:47

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion_joueurs', '0032_player_player_creation_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='player',
            name='client_fidel',
            field=models.BooleanField(default=False, verbose_name='Client Fidèle'),
        ),
        migrations.AddField(
            model_name='player',
            name='client_vip',
            field=models.BooleanField(default=False, verbose_name='Client VIP'),
        ),
        migrations.AddField(
            model_name='player',
            name='position',
            field=models.CharField(choices=[('GK', 'Goalkeeper'), ('DF', 'Defender'), ('MF', 'Midfielder'), ('FW', 'Forward')], default='DF', max_length=2, verbose_name='Position'),
        ),
    ]