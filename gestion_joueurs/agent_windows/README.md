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
HIGHLIGHTS_YOUTUBE_CHROME_PROFILE_NAME=Default
HIGHLIGHTS_YOUTUBE_BROWSER_CHANNEL=chrome
HIGHLIGHTS_YOUTUBE_HEADLESS=false
HIGHLIGHTS_YOUTUBE_TITLE_YEAR=2026
```

Pour chaque Highlights finale, le titre est automatiquement construit sous la
forme `Best Of Nom du joueur 2026 Skills Assists And Goals`. L’image
`intro\Uploads_ChatGPT_Kling\chatgpt_presentation` (`.png`, `.jpg`, `.jpeg` ou
`.webp`) est convertie en `intro\youtube_thumbnail.jpg` au format 1280 × 720,
puis importée comme miniature personnalisée. Si cette image manque, l’agent arrête
la livraison avant l’enregistrement YouTube afin de ne pas publier sans miniature.

Ne pas copier `D:\YouTube_MSPerformance_Profile` : ce dossier contient la session de
la chaîne Performance. Pour la première connexion Highlights, fermer complètement toutes
les fenêtres Chrome, puis lancer Chrome normal — sans Playwright — avec :

```powershell
python gestion_joueurs\automation_agent.py --setup-youtube
```

Cette commande ouvre Chrome normalement avec `D:\YouTube_Highlights_Profile\Default`.
Se connecter à Google, sélectionner la chaîne Highlights et attendre l’ouverture de
YouTube Studio. Fermer ensuite complètement cette fenêtre Chrome et appuyer sur Entrée
dans PowerShell. L’agent rouvre alors le même profil avec Playwright uniquement pour
vérifier que la session est prête. Les connexions suivantes ne redemandent pas le mot
de passe.

La commande `--check-youtube` vérifie une session existante sans proposer de connexion
dans le navigateur automatisé. Si Chrome n’est pas détecté automatiquement, renseigner
`HIGHLIGHTS_YOUTUBE_CHROME_EXE` avec le chemin complet vers `chrome.exe`.
Le contrôle existant `python -m sportsbase_data.local_agent --check-youtube` reste réservé
à la chaîne Performance / All Actions.
