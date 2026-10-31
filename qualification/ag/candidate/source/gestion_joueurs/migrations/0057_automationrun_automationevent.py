from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('gestion_joueurs', '0056_alter_video_deadline'),
    ]

    operations = [
        migrations.CreateModel(
            name='AutomationRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pipeline', models.CharField(choices=[('highlights', 'Highlights'), ('intro', 'Présentation'), ('delivery', 'Livraison')], max_length=20)),
                ('state', models.CharField(choices=[('queued', 'En attente'), ('running', 'En cours'), ('waiting_external', 'Action externe attendue'), ('failed', 'Échec'), ('succeeded', 'Terminé'), ('cancelled', 'Annulé')], default='queued', max_length=24)),
                ('current_stage', models.CharField(choices=[('queued', 'Dans la file'), ('transfermarkt', 'Données Transfermarkt'), ('chatgpt_image', 'Image ChatGPT'), ('kling_video', 'Animation Kling'), ('sportsbase_discovery', 'Recherche des matchs SportsBase'), ('sportsbase_generation', 'Génération All Actions'), ('sportsbase_download', 'Téléchargement des matchs'), ('premiere_project', 'Préparation Premiere Pro'), ('human_review', 'Sélection des actions'), ('premiere_final', 'Montage final Premiere Pro'), ('export', 'Export vidéo'), ('export_validation', 'Vérification du MP4'), ('youtube_upload', 'Mise en ligne YouTube'), ('youtube_validation', 'Vérification du lien YouTube'), ('delivery_update', 'Mise à jour de la livraison'), ('whatsapp', 'Notification WhatsApp'), ('completed', 'Terminé')], default='queued', max_length=40)),
                ('progress_current', models.PositiveIntegerField(default=0)),
                ('progress_total', models.PositiveIntegerField(default=0)),
                ('progress_percent', models.PositiveSmallIntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])),
                ('message', models.CharField(blank=True, max_length=500)),
                ('error_code', models.CharField(blank=True, max_length=80)),
                ('error_detail', models.TextField(blank=True)),
                ('artifacts', models.JSONField(blank=True, default=dict)),
                ('claimed_by', models.CharField(blank=True, max_length=120)),
                ('claim_token', models.CharField(blank=True, max_length=64)),
                ('attempt_count', models.PositiveIntegerField(default=0)),
                ('is_active', models.BooleanField(default=True)),
                ('claimed_at', models.DateTimeField(blank=True, null=True)),
                ('last_heartbeat_at', models.DateTimeField(blank=True, null=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('video', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='automation_runs', to='gestion_joueurs.video')),
            ],
            options={
                'ordering': ('-updated_at', '-pk'),
            },
        ),
        migrations.CreateModel(
            name='AutomationEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stage', models.CharField(choices=[('queued', 'Dans la file'), ('transfermarkt', 'Données Transfermarkt'), ('chatgpt_image', 'Image ChatGPT'), ('kling_video', 'Animation Kling'), ('sportsbase_discovery', 'Recherche des matchs SportsBase'), ('sportsbase_generation', 'Génération All Actions'), ('sportsbase_download', 'Téléchargement des matchs'), ('premiere_project', 'Préparation Premiere Pro'), ('human_review', 'Sélection des actions'), ('premiere_final', 'Montage final Premiere Pro'), ('export', 'Export vidéo'), ('export_validation', 'Vérification du MP4'), ('youtube_upload', 'Mise en ligne YouTube'), ('youtube_validation', 'Vérification du lien YouTube'), ('delivery_update', 'Mise à jour de la livraison'), ('whatsapp', 'Notification WhatsApp'), ('completed', 'Terminé')], max_length=40)),
                ('state', models.CharField(choices=[('queued', 'En attente'), ('running', 'En cours'), ('waiting_external', 'Action externe attendue'), ('failed', 'Échec'), ('succeeded', 'Terminé'), ('cancelled', 'Annulé')], max_length=24)),
                ('progress_percent', models.PositiveSmallIntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])),
                ('message', models.CharField(blank=True, max_length=500)),
                ('details', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='events', to='gestion_joueurs.automationrun')),
            ],
            options={
                'ordering': ('-created_at', '-pk'),
            },
        ),
        migrations.CreateModel(
            name='AutomationWorker',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('worker_id', models.CharField(max_length=120, unique=True)),
                ('display_name', models.CharField(blank=True, max_length=160)),
                ('host_name', models.CharField(blank=True, max_length=160)),
                ('version', models.CharField(blank=True, max_length=40)),
                ('state', models.CharField(choices=[('idle', 'Connecté'), ('busy', 'Occupé'), ('error', 'Erreur'), ('stopping', 'Arrêt en cours')], default='idle', max_length=20)),
                ('current_pipeline', models.CharField(blank=True, max_length=20)),
                ('current_stage', models.CharField(blank=True, max_length=40)),
                ('capabilities', models.JSONField(blank=True, default=dict)),
                ('last_error', models.TextField(blank=True)),
                ('last_seen_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('current_video', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='automation_workers', to='gestion_joueurs.video')),
            ],
            options={
                'ordering': ('-last_seen_at', 'worker_id'),
            },
        ),
        migrations.AddIndex(
            model_name='automationrun',
            index=models.Index(fields=['video', 'pipeline', 'is_active'], name='gj_autorun_video_pipe_idx'),
        ),
        migrations.AddIndex(
            model_name='automationrun',
            index=models.Index(fields=['state', 'updated_at'], name='gj_autorun_state_time_idx'),
        ),
        migrations.AddIndex(
            model_name='automationevent',
            index=models.Index(fields=['run', 'created_at'], name='gj_autoevent_run_time_idx'),
        ),
        migrations.AddConstraint(
            model_name='automationrun',
            constraint=models.UniqueConstraint(condition=models.Q(('is_active', True)), fields=('video', 'pipeline'), name='unique_active_automation_pipeline'),
        ),
    ]
