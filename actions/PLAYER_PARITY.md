# Hermes — parité Joueurs : incrément 1

Ce changement n'est **pas déployé** et ne modifie pas les contrats existants.

## Nouvelles actions proposées
- `player.sources.amend` — modifier les URL SportsBase et Transfermarkt d'un joueur existant, à l'aide de la validation du `PlayerForm` réel.
- `player.record.create` — créer la fiche joueur avec l'ensemble des champs scalaires du `PlayerForm` (identité, club, ligue, poste, e-mail, WhatsApp, URL SportsBase/Transfermarkt, fidélité et VIP). Déduplication par nom + date de naissance.

L'association à une organisation reste une opération séparée (`organization.link`). La création d'un compte portail n'est **pas** déclenchée par ces opérations et fera partie du lot Espaces clients. Ce découpage évite de produire un compte ou d'envoyer un e-mail à l'insu de l'utilisateur.

## Protections conservées
`actions` exige acteur autorisé, plan préparé, confirmation, préconditions, contrôles de dépendances et vérification. Les nouvelles actions sont ajoutées à la **liste de contrats connus**, mais les credentials/scopes/binding existants de production restent inchangés : elles ne sont pas immédiatement utilisables sur Heroku.

## Pour la qualification
1. Lancer les tests Django : `python manage.py test actions.test_player_contracts`.
2. Vérifier le catalogue `set(actions.registry.catalogue()) == actions.mount.APPROVED_OPERATIONS`.
3. Tester en environnement isolé le parcours native `catalogue → prepare → consentement → execute → status → verify` sur un joueur de test, y compris un rejet de formulaire, un conflit de snapshot et un double execute.
4. Après revue, déployer selon la procédure existante et mettre à jour **uniquement** les scopes/binding nécessaires via le mécanisme officiel Hermes/Heroku, sans diffuser les secrets.
5. Confirmer que le plugin Hermes voit les contrats, les utilise et relit les valeurs après exécution.

Pas de changement à `agent_api`, `data_access`, aux comptes portail ou aux workers locaux.

## Incrément 2 — Modification complète et associations
- `player.record.amend` : mise à jour d'un ou plusieurs champs de la fiche dans une seule préparation, avec `PlayerForm`.
- `player.organization.unlink` : clôture d'une association joueur-organisation **par ID de relation**, sans supprimer le joueur, l'organisation ni l'historique. Recherche de relations actives par début de nom du joueur.

Les contrats `organization.link` existants restent en place pour l'ajout / la réactivation. Les comptes clients, liens d'accès et messages de bienvenue restent hors périmètre : leurs services peuvent créer des identifiants et envoyer des e-mails, donc ils nécessitent un contrat explicite séparé.

**Validation statique seulement :** les tests ont été écrits mais pas exécutés et la nouvelle configuration Heroku n'a pas été changée.

## Incrément 3 — Association sans pack obligatoire
- `player.organization.link` : crée ou réactive une association joueur–organisation avec un `label` et un `expected_matches` facultatifs. Réutilise `OrganizationPlayerForm` côté Django ; refuse une relation déjà active et ne crée pas de commande vidéo.
- Le moteur ajoute un snapshot de la paire joueur–organisation et le readback suit cette relation, même si aucun lien vidéo n'est créé.
- `organization.link` historique continue de fonctionner inchangé : il impose les packs 3/5/10 pour son flux de commande.
