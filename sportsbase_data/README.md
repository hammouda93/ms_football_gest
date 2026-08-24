# Abonnements Performance SportsBase

Ce module est volontairement séparé de la production des vidéos. Il ajoute un abonnement
annuel par joueur, synchronise les données SportsBase depuis le PC local et les affiche dans
le portail client existant.

## Démarrer l’agent local

Depuis la racine du projet, dans l’environnement Python habituel :

```powershell
python -m sportsbase_data.local_agent
```

L’agent traite tous les abonnements actifs, un joueur après l’autre. Un match déjà complet
n’est pas régénéré. Un match partiel ou dont la vidéo est encore en cours est repris au
passage suivant.

Variables locales attendues :

```text
DJANGO_SITE_URL=https://msfootball-1a882b44ed52.herokuapp.com
DJANGO_AUTOMATION_USERNAME=...
DJANGO_AUTOMATION_PASSWORD=...
SPORTSBASE_LOGIN_URL=...
SPORTSBASE_EMAIL=...
SPORTSBASE_PASSWORD=...
SPORTSBASE_HEADLESS=false
SPORTSBASE_SUBSCRIPTION_STORAGE_DIR=D:\Django_Projects\ms_football_gest\gestion_joueurs\sportsbase_subscriptions
SPORTSBASE_AGENT_POLL_INTERVAL=60
```

Pour l’envoi des fichiers All Actions :

```text
SPORTSBASE_SMTP_HOST=...
SPORTSBASE_SMTP_PORT=587
SPORTSBASE_SMTP_USER=...
SPORTSBASE_SMTP_PASSWORD=...
SPORTSBASE_EMAIL_FROM=...
SPORTSBASE_SMTP_USE_TLS=true
SPORTSBASE_EMAIL_MAX_ATTACHMENT_MB=20
```

Les identifiants restent uniquement dans le `.env` local. Ils ne sont jamais transmis par
l’API ni enregistrés dans la base Django.

## Flux de données

1. L’administrateur active un abonnement Performance pour un joueur qui possède déjà son URL
   SportsBase.
2. Django met une tâche en attente.
3. L’agent local récupère la tâche avec son compte interne, ouvre SportsBase et importe la
   saison courante.
4. Les données structurées et les cartes PNG sont envoyées vers Django.
5. Le fichier All Actions reste sur le PC, dans `player_.../match_.../`, puis est envoyé au
   joueur par e-mail si sa taille respecte la limite configurée.
6. Le joueur ou son agent consulte les données selon les droits déjà gérés par
   `client_portal`.
