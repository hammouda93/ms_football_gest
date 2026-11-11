# Hermes — paiements des commandes vidéo Highlights

Périmètre exclusif : `finance.highlight.payment.record`. Aucun abonnement Performance n'est créé ou modifié dans cette branche. Aucun code de paiement bancaire n'est appelé.

## Commande utilisateur
Exemple : « Ajoute 150 DT par virement pour la commande vidéo 1980. »

Hermes utilise le contrat existant avec `video`, `amount` (texte décimal) et `payment_method`. Trois moyens disponibles : `cash`, `bank_transfer`, `la_poste`.

Le champ `payment_type` n'est **plus exigé**. Le backend le calcule automatiquement après vérification du solde réel : `partial` ou `final`. Les clients Hermes qui envoient déjà ce champ restent compatibles : la valeur enregistrée reste calculée à partir du solde.

## Contrôles
- Facture de la commande obligatoire.
- Montant strictement positif ; refus d'un montant supérieur au reste à payer.
- Prévisualisation : montant, total, payé, restant et état futur de la facture.
- Préparation scellée, relecture des données et conflit de snapshot si une autre opération modifie le paiement entre validation et exécution.
- Exécution de la vue Django existante `record_payment` ; vérification d'une seule nouvelle ligne et de la nouvelle facture.
- Aucune capture bancaire, aucun WhatsApp ni e-mail et aucune activation d'abonnement Performance.
- Aucune écriture réelle n'est effectuée sans consentement natif du propriétaire.

Le déploiement Heroku et le plugin Hermes existant restent inchangés tant que la CI et les contrôles de production ne sont pas validés.
