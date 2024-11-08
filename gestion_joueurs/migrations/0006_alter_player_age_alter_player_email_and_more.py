# Generated by Django 4.2.16 on 2024-10-12 10:40

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion_joueurs', '0005_player_age_player_whatsapp_number_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='player',
            name='age',
            field=models.IntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(0)]),
        ),
        migrations.AlterField(
            model_name='player',
            name='email',
            field=models.EmailField(default='player@gmail.com', max_length=254, unique=True),
        ),
        migrations.AlterField(
            model_name='player',
            name='whatsapp_number',
            field=models.CharField(blank=True, max_length=15, null=True, validators=[django.core.validators.RegexValidator(message='Le numéro de WhatsApp doit être au format +999999999999 ou 999999999.', regex='^\\+?1?\\d{9,15}$')]),
        ),
    ]
