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

## Livraison YouTube non répertoriée

La publication utilise un profil Chrome distinct du profil SportsBase. Elle est désactivée
tant que l’abonnement n’a pas l’option YouTube cochée et que la variable locale ci-dessous
n’est pas activée.

```text
YOUTUBE_UPLOAD_ENABLED=true
YOUTUBE_STUDIO_CHANNEL_ID=UCB2SMAxFXOcWDDDX5FtI9iA
YOUTUBE_CHROME_PROFILE_DIR=D:\YouTube_MSPerformance_Profile
YOUTUBE_BROWSER_CHANNEL=chrome
YOUTUBE_HEADLESS=false
YOUTUBE_UPLOAD_TIMEOUT_MINUTES=180
```

Première connexion, sans publier de vidéo :

```powershell
python -m sportsbase_data.local_agent --check-youtube
```

Connectez le profil affiché à la chaîne **MS Performance**, puis fermez la fenêtre. Ensuite,
le lancement normal traite d’abord toutes les synchronisations en attente, puis les uploads
YouTube. Une tâche échouée se reprend depuis « Abonnements Performance » sans télécharger à
nouveau la vidéo et sans resynchroniser le match. Après une publication réussie, un reçu
technique est conservé dans `_youtube_receipts` : si la connexion avec Heroku est coupée au
mauvais moment, l’agent renvoie l’URL existante au lieu de publier un doublon.

## Rapports Performance

- Un rapport de match est créé et publié après chaque synchronisation complète.
- Un rapport de cycle est créé après chaque groupe complet de cinq matchs.
- La langue française, anglaise ou arabe est imposée par l’abonnement.
- L’équipe peut modifier le texte et le remettre en brouillon depuis l’application interne.
- Le PDF n’est pas stocké : il est régénéré depuis la dernière version enregistrée à chaque
  ouverture.
- L’e-mail de livraison part une seule fois lorsque le rapport est publié et que la vidéo
  YouTube non répertoriée est disponible.

Sur Heroku, configurez également :

```text
PUBLIC_SITE_URL=https://msfootball-1a882b44ed52.herokuapp.com
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
5. Le fichier All Actions reste sur le PC, dans `player_.../match_.../`, puis une tâche de
   publication non répertoriée est créée si l’option YouTube est active.
6. L’agent local publie la vidéo, renvoie uniquement son URL et conserve l’empreinte du
   fichier pour la traçabilité.
7. Le rapport du match et, tous les cinq matchs, le rapport de cycle sont générés dans la
   langue de l’abonnement.
8. Le joueur ou son agent consulte la vidéo, les données et le PDF selon les droits déjà gérés par
   `client_portal`.
