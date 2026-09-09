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

Le bouton XLSX de SportsBase reste la source des statistiques Players : l’agent conserve
le classeur original octet pour octet, sans reconstruire son contenu depuis la page. Pour
éviter la déconnexion observée avec la copie Playwright sur le profil Chrome persistant, le
fichier original est intercepté avant le gestionnaire natif de téléchargement, puis enregistré
dans le même dossier de match. La session Chrome reste ainsi disponible pour All Actions.
Le dernier téléchargement MP4 depuis « My Videos » utilise l’événement de téléchargement
Playwright du Chrome authentifié, comme dans le flux historique qui fonctionnait. L’agent
effectue un seul clic, attend la fin du fichier original puis l’associe au bon match. Il ne
rejoue pas l’URL signée et ne modifie plus la politique de téléchargement Chrome via CDP.
La génération, l’association au match et le classement final ne changent pas.

Variables locales attendues :

```text
DJANGO_SITE_URL=https://msfootball-1a882b44ed52.herokuapp.com
DJANGO_AUTOMATION_USERNAME=...
DJANGO_AUTOMATION_PASSWORD=...
SPORTSBASE_LOGIN_URL=...
SPORTSBASE_EMAIL=...
SPORTSBASE_PASSWORD=...
SPORTSBASE_HEADLESS=false
SPORTSBASE_SUBSCRIPTION_PROFILE_DIR=D:\SportsBase_Playwright_Profile
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

## Solution de secours Dailymotion — RPA Chrome

YouTube reste le canal principal et son fonctionnement ne change pas. Si une vidéo All
Actions est bloquée, l’équipe peut lancer manuellement Dailymotion dans « Abonnements
Performance », sur la même ligne que YouTube. Le bouton devient « Réessayer » après un
échec. Lorsque le fichier est transféré mais que Dailymotion optimise encore la vidéo,
l’état devient « Upload effectué — lien à ajouter » et permet de coller le lien « Aperçu ».
Le bouton devient « Voir » dès que ce lien est enregistré. Aucun bouton de gestion
Dailymotion n’est ajouté à l’espace client : la page du match utilise automatiquement la
vidéo de secours lorsqu’elle est prête.

Comme YouTube, la publication est pilotée dans **Chrome par Playwright** : ouverture de
Studio, sélection du fichier, titre/description, catégorie Sport, langue, « non créé pour
les enfants », visibilité Privée, Enregistrer, attente de la fin du transfert, puis
« Fermer ». Dans la liste Vidéos, le RPA cible ensuite le titre exact et récupère le lien
privé « Aperçu » depuis son menu. Aucun appel à l’API Dailymotion, aucune clé API et aucun
mot de passe Dailymotion dans le code.

Le bouton « Fermer » peut être actif pendant que Studio affiche encore « Upload en cours
X % » : il n’est donc jamais utilisé comme preuve de fin. Le RPA attend obligatoirement
100 % ou un statut explicite de transfert terminé avant de fermer la fenêtre.

Ajoutez au `.env` local du PC qui exécute l’agent :

```text
DAILYMOTION_UPLOAD_ENABLED=true
DAILYMOTION_STUDIO_PROFILE_ID=x6445ea
DAILYMOTION_BROWSER_CHANNEL=chrome
DAILYMOTION_HEADLESS=false
DAILYMOTION_VIDEO_LANGUAGE=fr
DAILYMOTION_UPLOAD_TIMEOUT_MINUTES=180
DAILYMOTION_LINK_WAIT_SECONDS=0
```

Première connexion, sans envoyer de vidéo :

```powershell
python -m sportsbase_data.local_agent --check-dailymotion
```

La commande réutilise `D:\SportsBase_Playwright_Profile`. Si la session Dailymotion manque,
elle ferme le navigateur automatisé et ouvre **Chrome normal** sur ce même profil afin que la
connexion Google ne soit pas refusée comme « navigateur non sécurisé ». Connectez-vous,
ouvrez le Studio du profil `x6445ea`, fermez complètement Chrome, puis appuyez sur Entrée dans
PowerShell. Le RPA rouvre alors ce profil et vérifie Studio sans envoyer de vidéo. SportsBase
et Dailymotion utilisent ce profil l’un après l’autre, jamais simultanément ; YouTube conserve
son profil séparé. En cas d’expiration de session, relancez la même commande.

Relancez ensuite `python -m sportsbase_data.local_agent`. L’ordre existant reste inchangé :
synchronisations, YouTube, puis les essais Dailymotion demandés dans l’application interne.
Il n’y a pas de détection automatique des blocages YouTube : le bouton permet aussi de
secourir une vidéo marquée « disponible » dont le lecteur YouTube est devenu bloqué.

La visibilité Dailymotion **Privée** correspond à un accès par lien, sans apparition dans
les recherches, comme l’usage des vidéos YouTube non répertoriées. Le RPA conserve le vrai
lien de partage fourni par Studio (y compris les identifiants privés), pas l’adresse
d’édition. Ne publiez que des contenus autorisés : les règles de droits d’auteur restent
applicables sur Dailymotion.

Un reçu local est conservé dans `_dailymotion_receipts` afin d’éviter un second upload si
le retour vers Heroku est interrompu. Si Chrome s’arrête après le clic Enregistrer sans
confirmation, un reçu `needs_review` bloque un nouvel upload incertain : vérifiez le match
dans Studio. Dès que le transfert est confirmé, le reçu passe à `link_pending` : fermer
Chrome ou arrêter l’agent ne provoque alors aucun doublon. Par défaut, le RPA attend sans
limite que l’optimisation rende le menu « Aperçu » disponible et affiche sa progression.
Appuyez sur une touche dans PowerShell pour quitter cette attente : le transfert reste alors
en état `link_pending` et le lien peut être saisi dans « Abonnements Performance ». Lorsqu’il
est trouvé avant l’interruption, le lien est envoyé automatiquement à l’application. La valeur
`DAILYMOTION_LINK_WAIT_SECONDS=0` active cette attente sans limite ; une valeur positive fixe
facultativement une limite pour une exécution sans surveillance. Le lien est contrôlé puis
transformé en URL Dailymotion canonique avant d’être proposé au lecteur client. Une capture
locale dans `_dailymotion_diagnostics` aide à
diagnostiquer un changement d’interface.

Pour utiliser un lecteur Dailymotion personnalisé, configurez facultativement
`DAILYMOTION_PLAYER_ID` sur l’application Django. Appliquez la migration au déploiement :

```powershell
python manage.py migrate
```

Références officielles : [upload Studio](https://faq.dailymotion.com/hc/en-us/articles/115009030368-Upload-videos-from-your-Dailymotion-Studio),
[visibilité privée](https://faq.dailymotion.com/hc/en-us/articles/115009030028-Content-visibility).

## Rapports Performance

- Un rapport de match est créé et publié après chaque synchronisation complète.
- Un rapport de cycle est créé après chaque groupe complet de cinq matchs.
- La langue française, anglaise ou arabe est imposée par l’abonnement.
- L’équipe peut modifier le texte et le remettre en brouillon depuis l’application interne.
- Le PDF n’est pas stocké : il est régénéré depuis la dernière version enregistrée à chaque
  ouverture.
- L’e-mail de livraison part une seule fois lorsque le rapport est publié et qu’une vidéo
  YouTube ou Dailymotion est disponible.

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
6. L’agent local publie d’abord sur YouTube. Si l’équipe demande le secours Dailymotion,
   il réutilise exactement le même fichier local, renvoie uniquement l’URL obtenue et
   conserve l’empreinte du fichier pour la traçabilité.
7. Le rapport du match et, tous les cinq matchs, le rapport de cycle sont générés dans la
   langue de l’abonnement.
8. Le joueur ou son agent consulte la vidéo, les données et le PDF selon les droits déjà gérés par
   `client_portal`.
