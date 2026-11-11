# Hermes — statuts et livraison des vidéos (sans lien obligatoire)

Le formulaire `ProductionVideoStatusForm` de MS Football autorise déjà la livraison
sans URL finale. Le bridge `video.delivery.internal` avait une exigence supplémentaire
qui empêchait cette action.

## Changement
- `video.delivery.internal`: seul `id` est requis. `video_link` devient facultatif.
- Si l'URL est **omise**, conserver l'URL déjà enregistrée s'il y en a une.
- Si `video_link: ""` est fourni explicitement, vider le lien existant.
- Une nouvelle URL transmise reste soumise aux validations strictes de sécurité.
- `delivered` est un statut **interne**, sans envoi WhatsApp, e-mail ni publication implicite.
- La prévisualisation ne prétend pas que le fichier final est accessible sans lien.

## Tous les statuts officiels
`video.status.transition` expose `pending`, `in_progress`,
`completed_collab`, `completed` et `problematic` et utilise les
permissions du formulaire (notamment l'admin pour `completed`).
`delivered` passe par `video.delivery.internal`, maintenant sans lien requis.
Hermes doit router « livre cette vidéo sans lien » vers cette deuxième action.

## Précautions
Le chemin historique de statut reste en place ; il n'est pas remplacé par une
écriture directe dans la base. Les validations d'autorisation, d'historique,
de prévisualisation et de vérification après exécution restent applicables.

Tests CI SQLite exécutés automatiquement sur la branche, avec tests Joueurs
et Vidéos. La qualification PostgreSQL et l'intégration réelle avec Hermes
restent requises avant déploiement. Aucune configuration Heroku n'est modifiée.

## Précaution de préparation sans écriture
Le formulaire `VideoForm` peut modifier son `instance` pendant `is_valid()` même avant `save()`. Le contrat `video.production.amend` valide désormais une copie détachée de la vidéo. Les prévisualisations de date de livraison n'altèrent ni la ligne SQL ni l'objet cible conservé pour les projections.
