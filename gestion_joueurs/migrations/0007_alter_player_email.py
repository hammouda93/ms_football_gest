# Generated by Django 4.2.16 on 2024-10-12 10:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion_joueurs', '0006_alter_player_age_alter_player_email_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='player',
            name='email',
            field=models.EmailField(default='', max_length=254, unique=True),
        ),
    ]
