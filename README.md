# Oculox Core

Ce depot est le depot de deploiement de la VM **Core Oculox**. Son code est
identique au commit Gitea indique dans `SPLIT-MANIFEST.json`. La separation ne
change ni les scripts, ni les fichiers Compose, ni les profils, ni les choix de
l'assistant Malcolm.

Le Core fournit notamment Nginx, le portail, Keycloak, Dashboards, Logstash 1
et 2, Filebeat local, Arkime, Zeek, Suricata, Strelka, NetBox, l'API et les
services live deja presents dans le profil `malcolm`.

## 1. Place Du Core Dans L'installation

Ordre complet :

```text
1. Cluster OpenSearch
2. Bundle OpenSearch core
3. Core Oculox
4. Provisionnement Keycloak
5. Configuration OIDC du cluster
6. Activation Keycloak du portail et de Dashboards
7. Bundles et installation des collecteurs
```

Le Cluster doit donc etre installe avant ce Core.

### Fiche De Deploiement

Avant de commencer, noter les valeurs definitives :

| Valeur | Exemple de recette | Regle |
|---|---|---|
| `IP_CORE_OU_DNS` | `192.168.1.103` | stable et joignable par toutes les VM |
| `IP_CLUSTER` | `192.168.1.250` | endpoint OpenSearch |
| `INTERFACE_CAPTURE` | `ens33` | interface SPAN/TAP si capture Core |
| `NOM_COLLECTEUR` | `collector-01` | unique par capteur |

Une IP stable suffit en laboratoire. Chez un client, utiliser de preference un
DNS stable. La valeur `--server-name` devient l'identite HTTPS et la base des
URL Keycloak ; ne pas la changer ensuite sans rotation planifiee.

## 2. Prerequis

- Debian ou Ubuntu recent ;
- compte non root avec `sudo` ;
- heure synchronisee ;
- IP stable ou nom DNS stable ;
- acces Internet pour les images ;
- ports utilisateurs `443/TCP` et `5601/TCP` ;
- ports `5044/TCP` et `5045/TCP` autorises depuis les collecteurs ;
- endpoint OpenSearch `9200/TCP` joignable depuis le Core.

Verifier avant le clone :

```bash
sudo apt update
sudo apt install -y git curl ca-certificates
hostname -I
timedatectl status
ip -br link
df -h /
```

WISE utilise `8081` uniquement entre conteneurs. L'URL utilisateur est
`https://<IP_CORE_OU_DNS>/wise/` ; ne pas publier directement `8081`.

Ne placez jamais les bundles, mots de passe, PCAP ou fichiers `config/*.env`
dans Git.

## 3. Cloner Le Depot Core

```bash
git clone <URL_DEPOT_OCULOX_CORE> ~/oculox-core
cd ~/oculox-core
git status --short
```

La derniere commande ne doit rien afficher. Utilisez la meme version ou le meme
tag Oculox sur les trois VM. L'URL sera celle du depot Core publie apres la
recette locale.

## 4. Recuperer Et Verifier Le Bundle OpenSearch

L'installation du Cluster cree automatiquement le bundle Core dans :

```text
~/oculox-cluster/dev/generated/opensearch-cluster/client-bundles/core
```

Le transferer directement sur le Core par un canal administre :

```bash
mkdir -p ~/oculox-bundles
scp -r <UTILISATEUR_CLUSTER>@<IP_CLUSTER>:~/oculox-cluster/dev/generated/opensearch-cluster/client-bundles/core ~/oculox-bundles/
cd ~/oculox-bundles/core
sha256sum -c SHA256SUMS
cd ~/oculox-core
```

`SHA256SUMS` doit retourner uniquement `OK`.

Il n'est pas necessaire d'executer `cluster client-bundle` dans le parcours
normal. Cette commande reste disponible sur le Cluster uniquement pour
reexporter le bundle si sa copie automatique est absente ou doit etre placee
dans un autre repertoire securise.

## 5. Installer Le Core Sans Changer La Procedure

```bash
./oculox install principal \
  --server-name <IP_CORE_OU_DNS> \
  --opensearch-bundle ~/oculox-bundles/core
```

Arguments :

| Argument | Signification |
|---|---|
| `install principal` | selectionne le profil Core `malcolm` |
| `--server-name` | IP ou DNS stable utilise pour HTTPS, Keycloak et les redirect URI |
| `--opensearch-bundle` | CA, endpoint et comptes techniques limites fournis par le Cluster |

Le script execute successivement l'installateur officiel Malcolm, remet les
fichiers generes a l'operateur, importe le bundle, lance `auth_setup`, prepare
le role, valide Compose, telecharge les images et demarre la plateforme.

### Choix Dans L'installateur Malcolm

Les libelles peuvent varier legerement selon le terminal, mais les choix Core
sont les suivants :

| Ecran | Valeur attendue |
|---|---|
| Profil d'execution | `malcolm` |
| Stockage principal | OpenSearch distant / `opensearch-remote` |
| URL OpenSearch | `https://<IP_CLUSTER>:9200` |
| Verification TLS OpenSearch | `Yes` |
| Exposition des services | `Yes` pour permettre les collecteurs sur `5044/5045` |
| Capture live sur le Core | conserver le besoin du deploiement ; ne supprimer aucun service Compose |
| Interface de capture | interface SPAN/TAP reelle si la capture Core est active |
| Zeek, Suricata, Arkime | activer selon le mode de capture retenu, comme dans le depot fusionne |
| Enable Arkime WISE | `Yes` charge WISE et permet l'enrichissement ; `No` le laisse desactive sans bloquer l'installation |
| Allow Arkime WISE Configuration | `Yes` permet aux administrateurs de gerer les sources dans `WISE > Config` ; `No` rend la configuration consultable seulement |
| Arkime WISE URL | conserver `http://arkime:8081` pour le WISE local du Core ; utiliser une URL HTTPS sans identifiants uniquement pour un WISE distant |

Pour une capture Core standard avec Arkime :

| Reglage | Valeur recommandee |
|---|---|
| Capture Live Traffic with Arkime | `Yes` |
| Arkime Node Host | laisser vide ; `install principal` applique ensuite `--server-name` |
| PCAP Compression | `none`, sauf politique explicite |
| Capture with netsniff-ng | `No` |
| Capture with tcpdump | `No` |

Arkime capture deja le PCAP. Plusieurs moteurs simultanes peuvent dupliquer les
paquets et augmenter fortement CPU et disque. Zeek et Suricata peuvent rester
actifs pour l'analyse. Si le Core ne recoit aucun SPAN/TAP, desactiver la
capture dans l'assistant ne supprime pas les capacites du depot.

Apres l'assistant, Oculox renseigne automatiquement
`ARKIME_LIVE_NODE_HOST=<IP_CORE_OU_DNS>` dans `config/arkime-live.env`. Le nom
logique de capture reste `oculox`, mais Arkime utilise une adresse resolvable
pour recuperer les paquets sur le port interne Viewer `8005`. Cela evite
`Error talking to node 'oculox' using host 'oculox:8005'` sans exposer un port
utilisateur supplementaire.

`http://arkime:8081` est l'adresse WISE interne. Ne saisir ni
`https://<IP_CORE>/wise/`, ni `https://<IP_CORE>:8081/wise/`, ni un mot de passe
dans cette valeur. Si WISE est desactive, l'installation continue et sa
validation devient non applicable sans bloquer les autres services.

Le bundle importe ensuite les valeurs OpenSearch definitives. Ne remplacez pas
ses comptes techniques par un compte administrateur partage.

### Choix Dans `auth_setup`

Quand l'ecran `Configure Authentication` apparait, choisir `all`. Pour une
installation initiale en Basic avant activation controlee de Keycloak :

| Question | Reponse recommandee | Explication |
|---|---|---|
| Select authentication method | `basic` | garde un acces initial et un retour arriere |
| Store administrator username/password | `Yes` | creer le compte Basic initial, mot de passe fort |
| Regenerate HTTPS certificates | `Yes` | cree les certificats Web initiaux |
| Regenerate remote log forwarder certificates | `Yes` | prepare le mTLS Filebeat vers Logstash |
| Store remote OpenSearch username/password | `No` | le bundle Cluster a deja fourni les comptes limites |
| OpenSearch Alerting email sender | `No` sauf SMTP configure | ne pas inventer de compte SMTP |
| Generate NetBox passwords | `Yes` | secrets internes uniques |
| Generate PostgreSQL passwords | `Yes` | secrets internes uniques |
| Generate Valkey passwords | `Yes` | secrets internes uniques |
| Arkime viewer cluster secret | `Yes` | secret interne Arkime |
| Transfer certificates with `croc` | `No` | les bundles Oculox sont utilises separement |

Pour le compte Basic, saisir un nom de 4 a 32 caracteres puis deux fois un mot
de passe fort de 8 a 128 caracteres. Ne passez aucun mot de passe dans la ligne
de commande. Les questions absentes de votre ecran ne doivent pas etre forcees :
elles dependent du profil et des modes selectionnes precedemment.

Si Docker vient d'etre installe et que le groupe n'est pas encore actif, le
lanceur tente une reprise automatique. Sinon, reconnectez la session et lancez :

```bash
./oculox resume-install principal \
  --server-name <IP_CORE_OU_DNS> \
  --opensearch-bundle ~/oculox-bundles/core
```

Ne relancez pas `install` uniquement pour reprendre apres `auth_setup`.

## 6. Verifier Le Core En Basic

```bash
./oculox status
./oculox validate
./oculox verify clients
./oculox verify wise
./oculox logs nginx-proxy dashboards logstash logstash-2
```

Tous les conteneurs doivent etre `running` et, lorsqu'un healthcheck existe,
`healthy`. `./oculox verify clients` doit terminer par
`CLIENT_CONNECTIVITY_RESULT=PASS`. Si une URL WISE HTTPS a ete configuree,
`./oculox verify wise` doit terminer par `WISE_RUNTIME=PASS`. L'installation
ajoute automatiquement le compte technique Arkime a Nginx sans afficher son
mot de passe. Il ne faut pas incorporer d'identifiants dans l'URL WISE.

Les liens de champ IP et protocole de Dashboards sont generes avec l'URL
publique declaree par `--server-name`. Un clic doit rediriger vers Arkime et ne
doit jamais rester sur `/dashboards/app/iddash2ark/`.

URL de controle :

| Service | URL |
|---|---|
| Portail | `https://<IP_CORE_OU_DNS>/` |
| Dashboards | `https://<IP_CORE_OU_DNS>:5601/dashboards/` |
| Arkime | `https://<IP_CORE_OU_DNS>/arkime/` |
| WISE | `https://<IP_CORE_OU_DNS>/wise/` |
| Keycloak | `https://<IP_CORE_OU_DNS>/keycloak/` |

Les avertissements Logstash `zeek-parse unavailable` sont normaux pendant
l'initialisation. Ils doivent cesser apres le demarrage du pipeline
`malcolm-zeek`. S'ils persistent plusieurs minutes :

```bash
./oculox logs logstash logstash-2
./oculox restart logstash logstash-2
./oculox status
```

## 7. Provisionner Keycloak

Le provisionnement ne remplace pas encore le mode Basic : il cree le realm,
les clients, groupes, roles, secrets et le compte administrateur initial.

```bash
./oculox keycloak provision --admin-username oculox-initial-admin
./oculox keycloak report
./oculox keycloak credentials
./oculox keycloak verify-hardening
```

`--admin-username` choisit le nom du compte humain initial. Les mots de passe
sont generes dans `dev/generated/keycloak-initial-credentials.env`, protege en
mode `600` et ignore par Git. Enregistrez-les dans un coffre. `report` doit
contenir `"result": "PASS"`.

Quelques `connection refused` ou `503` peuvent apparaitre pendant le premier
demarrage de Keycloak. Le script attend automatiquement. Ne pas interrompre :
la validite est determinee par le code retour final, le rapport `PASS` et
`verify-hardening`, pas par une tentative transitoire.

Le meme rapport doit contenir `arkime_wise_read_access` et
`arkime_wise_read_write_access`. Le groupe `oculox-admins` doit posseder les
deux. Aucune commande Keycloak supplementaire n'est requise, que WISE ait ete
active ou non dans l'assistant.

La CA publique Web necessaire au Cluster est :

```text
dev/generated/web-trust/oculox-web-ca.crt
```

Copiez uniquement cette CA publique vers la VM Cluster :

```bash
scp dev/generated/web-trust/oculox-web-ca.crt \
  <UTILISATEUR_CLUSTER>@<IP_CLUSTER>:/tmp/oculox-web-ca.crt
```

Sur le Cluster, configurer ensuite OIDC avant d'activer Dashboards :

```bash
./oculox cluster configure-oidc \
  --keycloak-auth-url https://<IP_CORE_OU_DNS>/keycloak \
  --realm oculox \
  --keycloak-ca /tmp/oculox-web-ca.crt
./oculox cluster validate
```

## 8. Activer Le SSO

Revenir sur le Core :

```bash
./oculox keycloak activate-portal
./oculox keycloak activate-dashboards
./oculox restart nginx-proxy keycloak dashboards
./oculox keycloak verify-portal
./oculox keycloak verify-dashboards
./oculox keycloak verify-hardening
```

`activate-portal` remplace le controle Basic du portail par Keycloak.
`activate-dashboards` configure le client OIDC de Dashboards. Les commandes de
retour arriere restent disponibles :

```bash
./oculox keycloak deactivate-dashboards
./oculox keycloak deactivate-portal
./oculox restart dashboards nginx-proxy
```

## 9. Creer Les Utilisateurs Humains

Ouvrir `https://<IP_CORE_OU_DNS>/keycloak/admin/`, utiliser le compte initial,
puis creer chaque utilisateur dans le realm `oculox`. Affecter l'utilisateur a
`/oculox-users` et a un groupe fonctionnel :

- `/oculox-admins` ;
- `/oculox-analysts` ;
- `/oculox-incident-response` ;
- `/oculox-viewers`.

Ne donnez pas les roles techniques `oculox_logstash`, `oculox_dashboards` ou
`oculox_api` aux humains. Exiger le changement du mot de passe initial et
l'enrolement TOTP lors de la premiere connexion.

Le provisionnement attribue automatiquement l'administration WISE aux membres
de `/oculox-admins`. Lorsque WISE a ete active dans l'assistant, ces
administrateurs peuvent ajouter et modifier les sources dans `WISE > Config`.
Les autres groupes fonctionnels disposent uniquement de la consultation WISE.
Lorsque WISE est desactive, les roles restent presents dans Keycloak mais
n'activent aucun service et ne bloquent pas l'installation.

Apres une modification de groupe ou de role, fermer la session navigateur et
se reconnecter : un jeton deja emis ne contient pas les nouveaux roles.

## 10. Preparer Un Collecteur

```bash
mkdir -p ~/oculox-bundles
./oculox collector-bundle <NOM_COLLECTEUR> <IP_CORE_OU_DNS> \
  ~/oculox-bundles/<NOM_COLLECTEUR>
cd ~/oculox-bundles/<NOM_COLLECTEUR>
sha256sum -c SHA256SUMS
```

Chaque collecteur doit recevoir son propre bundle.

## 11. Exploitation

```bash
./oculox start
./oculox restart [service...]
./oculox status
./oculox logs [service...]
./oculox pull
./oculox validate
./oculox stop
```

`stop` conserve les volumes. N'utilisez pas `docker compose down -v`.

Apres un redemarrage de VM :

```bash
cd ~/oculox-core
./oculox start
./oculox status
./oculox verify clients
./oculox verify wise
```

`restart` reconcilie d'abord le Compose rendu puis redemarre les services
demandes. Cela applique les changements de ports, mounts et variables que
`docker compose restart` seul n'appliquerait pas.

## 12. Depannage Et Recette Finale

| Symptome | Cause probable | Action |
|---|---|---|
| Docker refuse l'acces | groupe Docker non recharge | reconnecter SSH puis `resume-install` |
| checksum bundle invalide | transfert incomplet | recopier depuis le Cluster |
| OpenSearch refuse TLS | CA, heure ou endpoint incorrect | verifier bundle et horloge |
| WISE retourne `401` | session/role ou compte technique | nouvelle connexion puis `verify wise` |
| WISE affiche zero requete | aucune recherche Arkime | generer du trafic puis consulter Stats |
| Dashboards: Application Not Found | ancien lien/session | redemarrer Dashboards et rouvrir la session |
| Logstash attend `zeek-parse` | pipeline en initialisation | attendre puis lire les deux logs |

Le Core est accepte lorsque les services sont sains, `validate`,
`verify clients`, `verify wise` et les trois controles Keycloak passent, les
liens Dashboards ouvrent Arkime, et une recette Collecteur se termine par
`INGESTION_RESULT=PASS`. Sauvegarder hors Git `config/*.env`, les identifiants
Keycloak, les bundles non distribues et les donnees persistantes.

Documentation technique complementaire :

- `dev/keycloak/11_configuration_keycloak_detaillee_keep_it_simple.md` ;
- `dev/docs/13_installation_resiliente_principal_hedgehog.md` ;
- `docs/UPSTREAM_README.md`.
