# Agent Windows MS Football

L’application met les vidéos dans une file. Cet agent local, démarré avec Windows,
les récupère automatiquement sans VS Code ni terminal à laisser ouvert.

Installation unique : clic droit sur `install_agent.ps1`, puis **Exécuter avec
PowerShell**. Le tableau de bord affiche ensuite **Agent connecté**.

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
