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
