# Generated by Django 4.2.16 on 2024-11-03 00:15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion_joueurs', '0038_rename_type_notification_notification_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]