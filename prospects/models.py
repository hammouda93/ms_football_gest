import re
from urllib.parse import quote

from django.core.validators import RegexValidator
from django.db import models


whatsapp_validator = RegexValidator(
    regex=r"^\+?[1-9]\d{7,14}$",
    message=(
        "Saisissez un numéro WhatsApp international valide, par exemple "
        "+21620123456."
    ),
)


class Prospect(models.Model):
    class Service(models.TextChoices):
        HIGHLIGHTS = "highlights", "Vidéo highlights"
        VIDEO_CV = "video_cv", "CV vidéo"
        OTHER = "other", "Autre service"

    class Position(models.TextChoices):
        GOALKEEPER = "goalkeeper", "Gardien"
        DEFENDER = "defender", "Défenseur"
        MIDFIELDER = "midfielder", "Milieu"
        FORWARD = "forward", "Attaquant"
        OTHER = "other", "Autre"

    class Status(models.TextChoices):
        NEW = "new", "Nouveau"
        CONTACTED = "contacted", "Contacté"
        INTERESTED = "interested", "Intéressé"
        CONVERTED = "converted", "Converti"
        LOST = "lost", "Perdu"

    full_name = models.CharField("Nom du joueur", max_length=120)
    whatsapp_number = models.CharField(
        "Numéro WhatsApp",
        max_length=16,
        validators=[whatsapp_validator],
    )
    email = models.EmailField("Adresse e-mail", blank=True)
    country = models.CharField("Pays", max_length=80)
    club = models.CharField("Club actuel", max_length=120, blank=True)
    position = models.CharField(
        "Poste",
        max_length=20,
        choices=Position.choices,
    )
    season = models.CharField("Saison", max_length=20)
    service_type = models.CharField(
        "Service souhaité",
        max_length=20,
        choices=Service.choices,
    )
    match_links = models.TextField("Liens des matchs")
    desired_deadline = models.DateField("Date souhaitée", blank=True, null=True)
    message = models.TextField("Informations complémentaires", blank=True)
    source = models.CharField("Source", max_length=80, default="Formulaire web")
    status = models.CharField(
        "Statut",
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True,
    )
    internal_notes = models.TextField("Notes internes", blank=True)
    created_at = models.DateTimeField("Créé le", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Prospect vidéo"
        verbose_name_plural = "Prospects vidéo"

    def __str__(self):
        return f"{self.full_name} — {self.get_service_type_display()}"

    @property
    def whatsapp_url(self):
        """Return a wa.me URL without triggering any external action."""
        phone_number = re.sub(r"\D", "", self.whatsapp_number)
        text = (
            f"Bonjour {self.full_name}, nous avons bien reçu votre demande "
            f"pour le service « {self.get_service_type_display()} ». "
            "Pouvons-nous échanger sur votre projet ?"
        )
        return f"https://wa.me/{phone_number}?text={quote(text, safe='')}"
