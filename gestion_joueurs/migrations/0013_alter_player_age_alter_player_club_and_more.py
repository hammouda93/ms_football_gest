# Generated by Django 4.2.16 on 2024-10-15 10:38

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('gestion_joueurs', '0012_video_info'),
    ]

    operations = [
        migrations.AlterField(
            model_name='player',
            name='age',
            field=models.IntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Age'),
        ),
        migrations.AlterField(
            model_name='player',
            name='club',
            field=models.CharField(default='', max_length=100, verbose_name='Club Name'),
        ),
        migrations.AlterField(
            model_name='player',
            name='email',
            field=models.EmailField(default='', max_length=254, verbose_name='Email Address'),
        ),
        migrations.AlterField(
            model_name='player',
            name='league',
            field=models.CharField(choices=[('L1', 'Ligue 1 Tunisie'), ('L2', 'Ligue 2 Tunisie'), ('LY', 'Libye'), ('OC', 'Other Country')], default='L1', max_length=2, verbose_name='League'),
        ),
        migrations.AlterField(
            model_name='player',
            name='name',
            field=models.CharField(default='', max_length=100, verbose_name='Player Name'),
        ),
        migrations.AlterField(
            model_name='player',
            name='whatsapp_number',
            field=models.CharField(blank=True, max_length=15, null=True, validators=[django.core.validators.RegexValidator(message='Le numéro de WhatsApp doit être au format +999999999999 ou 999999999.', regex='^\\+?1?\\d{9,15}$')], verbose_name='WhatsApp Number'),
        ),
        migrations.CreateModel(
            name='Payment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('payment_date', models.DateField(auto_now_add=True)),
                ('payment_type', models.CharField(choices=[('advance', 'Advance'), ('final', 'Final')], max_length=50)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('player', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='gestion_joueurs.player')),
                ('video', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='gestion_joueurs.video')),
            ],
        ),
    ]
