# Generated by Django 4.2.16 on 2024-11-02 20:29

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('gestion_joueurs', '0037_alter_invoice_status'),
    ]

    operations = [
        migrations.RenameField(
            model_name='notification',
            old_name='type',
            new_name='notification_type',
        ),
    ]