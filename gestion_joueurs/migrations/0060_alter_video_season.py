"""Align stored Video season choices with the 2026/2027 VideoForm option."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gestion_joueurs", "0059_video_academy_order_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="video",
            name="season",
            field=models.CharField(
                choices=[
                    ("2022/2023", "2022/2023"),
                    ("2023/2024", "2023/2024"),
                    ("2024/2025", "2024/2025"),
                    ("2025/2026", "2025/2026"),
                    ("2026/2027", "2026/2027"),
                ],
                default="2024/2025",
                max_length=10,
            ),
        ),
    ]
