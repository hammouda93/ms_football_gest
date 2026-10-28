# Qualification Linux action06 — candidat fermé

Ce dossier rejoue les **61 tests action06 sans modification de leurs assertions**, plus cinq tests d’isolation. Il ne déploie ni n’active le writer. Le geste d’approbation humaine indépendant reste hors de cette qualification ; la signature HMAC utilisée par les fixtures ne le démontre pas.

## Périmètre reproductible

- Base Git : `dfa8b032597832917f812a3e7fc2126d7534cf5b` ; branche CI distincte, aucun merge.
- Moteur candidat fermé : `4b3a2502125c562dd977d7d1feed7d06452196b8` (provenance locale action06). Dix fichiers `actions/`, dont les migrations réelles `0001` et `0002`, identiques par SHA256.
- Sources sélectionnées explicitement depuis la liste locale de 179 fichiers : fermeture d’imports et migrations des quatre applications réelles, soit 112 fichiers. 109 identiques aux blobs du pin et trois correctifs acteur/signaux préexistants du candidat. `SOURCE-MANIFEST.json` donne la liste et les hashes ; aucune reconstruction du moteur.
- Python **3.10.22** fourni officiellement par `actions/python-versions`, Django **4.2.20**, PostgreSQL **16.14** image officielle épinglée par digest. Runner standard public `ubuntu-24.04`, pas de larger runner, cache ni upload d’artefact.
- Actions GitHub officielles uniquement, épinglées par SHA ; `contents: read`, checkout sparse et sans credential persistant. Aucun secret GitHub/Heroku, aucune variable ou donnée production.

## Isolation

Le service PostgreSQL est neuf, éphémère et fictif : port hôte loopback55440, base `msf_action03_fiction`, rôle fixture `msf_action01_fixture_owner`, authentification trust limitée au service CI jetable. Le serveur voit son port interne5432 et son IP Docker : l’IP exacte du conteneur est attestée avant les imports, puis comparée avec `inet_server_addr()`, rôle/base/version et répertoire `/var/lib/postgresql/data`. Cela remplace la garde de chemin du cluster Windows sans la désactiver. Les clients restent limités à `127.0.0.1:55440` et le HTTP fictif à `127.0.0.1:55441`.

L’environnement est vidé avant tout import métier, dotenv neutralisé, lancement de processus, réseau externe, DNS externe, SMTP et dispatch Celery bloqués. Les écritures disque restent dans ce dossier. Deux nouveaux tests RED puis GREEN couvrent aussi bind non-loopback et datagrammes externes. Les preuves RED restent locales et ne sont pas présentées comme des exécutions Linux.

## Exécution

Le workflow `.github/workflows/action06-linux.yml` ne se déclenche que sur les pushes de la branche CI dédiée. Il vérifie les hashes, installe le harness versionné dans un venv neuf, applique les migrations métier et techniques réelles sur la base vide, puis exige66 IDs uniques réussis, incluant exactement les61 IDs précédents. Sockets concurrents, timeouts SQL, quotas partagés, rollback et readbacks sont réels.

Les logs machine incluent `RUNTIME_TARGET`, `QUALIFICATION_RESULT`, les readbacks fictifs et les refus négatifs attendus. Aucun résultat n’est préfabriqué. Les fichiers de résultat locaux du runner ne sont pas uploadés comme artefacts.

## Limites

C’est la qualification du moteur/HTTP candidat et de ses migrations sur fixtures Linux, pas une non-régression de toutes les pages, du plugin natif ou de l’exploitation Heroku. Templates/assets et intégrations historiques exclus ne sont ni copiés ni testés. Aucun réglage applicatif de production n’est modifié : tout vit sous `qualification/action06/`. L’historique préexistant du dépôt public n’est pas assaini par cette branche.
