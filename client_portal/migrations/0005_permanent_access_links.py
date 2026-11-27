from django.db import migrations, models
from django.utils import timezone


def preserve_current_links(apps, schema_editor):
    Link = apps.get_model("client_portal", "PortalAccessLink")
    # Never revive a revoked or already expired secret.
    Link.objects.using(schema_editor.connection.alias).filter(
        revoked_at__isnull=True, expires_at__gt=timezone.now(),
    ).update(expires_at=None)


class Migration(migrations.Migration):
    dependencies = [("client_portal", "0004_organizationplayer_expected_matches")]

    operations = [
        migrations.AlterField(
            model_name="portalaccesslink", name="expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="portalaccesslink", name="encrypted_token",
            field=models.TextField(blank=True, default="", editable=False),
        ),
        migrations.RunPython(preserve_current_links, reverse_code=migrations.RunPython.noop),
    ]
