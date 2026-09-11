# Agent Windows MS Football

L’application met les vidéos dans une file. Cet agent local, démarré avec Windows,
les récupère automatiquement sans VS Code ni terminal à laisser ouvert.

Installation unique : double-cliquer sur `Installer_Agent_MS_Football.cmd`.
Le tableau de bord affiche ensuite **Agent connecté**.

Pré-requis : le Python du projet doit exister dans `.venv`, `venv`, ou être indiqué
par la variable utilisateur `MS_FOOTBALL_PYTHON`. Les identifiants et chemins restent
dans le fichier `.env` existant du projet.

`uninstall_agent.ps1` retire uniquement le démarrage automatique ; il conserve les
vidéos, les projets Premiere et les journaux.

Une fois installé, il n’y a plus besoin de VS Code : passer une vidéo à **In progress**
avec **Automation** dans l’application suffit pour la mettre en file. L’agent la prend
normalement en moins de cinq secondes et son état apparaît sur le tableau de bord.

Les options d’image OpenAI, Kling API, validation ffprobe, export Premiere et WhatsApp
sont documentées dans `.env.automation.example`. Elles sont toutes désactivées par
défaut pour préserver le processus actuellement en production. Le plugin Kling visible
dans ChatGPT reste interactif ; pour un traitement autonome en arrière-plan, il faut les
identifiants de l’API Kling Open Platform.

## Deuxième chaîne YouTube pour les Highlights finales

L’agent Highlights utilise exclusivement les variables `HIGHLIGHTS_YOUTUBE_*` pour
la livraison du MP4 final. L’agent des abonnements Performance / All Actions conserve
les variables `YOUTUBE_*`. Le téléchargement SportsBase reste commun et continue
d’utiliser son profil persistant existant ; aucune variable `SPORTSBASE_*` ne change.

Dans le fichier `.env` du projet, renseigner au minimum :

```text
HIGHLIGHTS_YOUTUBE_STUDIO_CHANNEL_ID=UC_IDENTIFIANT_DE_LA_CHAINE_HIGHLIGHTS
HIGHLIGHTS_YOUTUBE_CHROME_PROFILE_DIR=D:\YouTube_Highlights_Profile
HIGHLIGHTS_YOUTUBE_BROWSER_CHANNEL=chrome
HIGHLIGHTS_YOUTUBE_HEADLESS=false
```

Ne pas copier `D:\YouTube_MSPerformance_Profile` : ce dossier contient la session de
la chaîne Performance. Le nouveau dossier `D:\YouTube_Highlights_Profile`, placé juste
à côté, est créé automatiquement lors du premier contrôle. Fermer auparavant toute
fenêtre Chrome qui utilise l’un de ces profils, puis lancer depuis la racine du projet :

```powershell
python gestion_joueurs\automation_agent.py --check-youtube
```

Dans la fenêtre ouverte, choisir le second compte Google, se connecter si nécessaire,
puis vérifier que YouTube Studio affiche bien la chaîne Highlights. Revenir ensuite dans
PowerShell, appuyer sur Entrée, attendre la confirmation, puis laisser la fenêtre se fermer.
Le contrôle existant `python -m sportsbase_data.local_agent --check-youtube` reste réservé
à la chaîne Performance / All Actions.
