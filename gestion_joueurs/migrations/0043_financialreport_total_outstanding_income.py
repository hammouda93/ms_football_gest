# Generated by Django 4.2.16 on 2024-11-05 04:10

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion_joueurs', '0042_alter_nonvideoincome_amount_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='financialreport',
            name='total_outstanding_income',
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=10),
        ),
    ]
