# Generated by Django 4.2.16 on 2024-10-22 20:41

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion_joueurs', '0027_remove_expense_description'),
    ]

    operations = [
        migrations.AddField(
            model_name='expense',
            name='description',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
