# Generated by Django 4.2.16 on 2024-10-20 13:26

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('gestion_joueurs', '0020_remove_invoice_due_date_remove_payment_method_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='invoice',
            name='video',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='invoices', to='gestion_joueurs.video', unique=True),
        ),
    ]
