# Agency Calendar

Application interne de calendrier d'agence, développée avec Django 5.2,
FullCalendar et PostgreSQL. La production est publiée sur
[Vercel](https://calendrier-hassen5.vercel.app/) depuis le dépôt
[GitHub](https://github.com/H2698/calendrier), avec Neon PostgreSQL.

## Fonctionnalités

- rôles Admin, Manager et Member avec permissions contrôlées par Django ;
- calendrier jour, semaine et mois, filtres, drag & drop et redimensionnement ;
- rendez-vous récurrents, multi-affectation et avertissement de conflits ;
- confidentialité des données client pour les membres non affectés ;
- clients, équipe, tableau de bord, paramètres et historique d'audit ;
- setup initial sécurisé des données réservé à l'Administrateur ;
- notifications internes, Web Push et rappels planifiés ;
- rapports individuels définitifs après chaque rendez-vous terminé ;
- actualisation automatique du calendrier toutes les 10 secondes ;
- interface responsive pour ordinateur, tablette et navigateur mobile.

L'authentification est assurée par Django, la base par Neon PostgreSQL et le
déploiement par Vercel. La synchronisation automatique interroge l'API Django
filtrée selon les permissions ; elle ne diffuse jamais directement les données
privées de la base.

## Installation locale

Prérequis : Python 3.12+, Node.js uniquement pour les contrôles JavaScript, et
Git.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver
```

Pour le développement local, conserver `DEBUG=True` et `USE_SQLITE=True` dans
`.env`. L'application est alors disponible sur `http://127.0.0.1:8000/` et le
contrôle de santé sur `http://127.0.0.1:8000/health/`.

## Variables d'environnement

| Variable | Production | Usage |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | obligatoire | clé aléatoire longue, uniquement côté serveur |
| `DEBUG` | `False` | désactive le mode debug |
| `USE_SQLITE` | `False` | impose PostgreSQL |
| `DATABASE_URL` | obligatoire | URL PostgreSQL poolée Neon avec SSL |
| `ALLOWED_HOSTS` | recommandé | domaines autorisés, séparés par des virgules |
| `CSRF_TRUSTED_ORIGINS` | recommandé | origines HTTPS autorisées |
| `TIME_ZONE` | `Africa/Tunis` | fuseau par défaut |
| `VAPID_PUBLIC_KEY` | Web Push | clé publique VAPID |
| `VAPID_PRIVATE_KEY` | Web Push | clé privée, jamais côté navigateur |
| `VAPID_SUBJECT` | Web Push | adresse `mailto:` de contact |
| `CRON_SECRET` | obligatoire | protège l'endpoint du scheduler |
| `SECURE_HSTS_SECONDS` | `31536000` | durée HSTS en production |
| `EMAIL_BACKEND` | mot de passe oublié | utiliser `django.core.mail.backends.smtp.EmailBackend` |
| `EMAIL_HOST`, `EMAIL_PORT` | SMTP | serveur et port du fournisseur e-mail |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | SMTP | identifiants stockés uniquement côté serveur |
| `EMAIL_USE_TLS` | généralement `True` | chiffrement SMTP STARTTLS |

Le modèle complet se trouve dans `.env.example`. Ne jamais committer `.env`,
une URL de base réelle, une clé VAPID privée ou un secret d'automatisation.
Le flux « mot de passe oublié » devient expéditeur en production lorsque les
variables SMTP sont renseignées ; le backend console reste réservé au local.

## Déploiement Vercel + Neon

1. Importer `H2698/calendrier` dans Vercel et garder la branche de production
   `main`.
2. Connecter une base Neon PostgreSQL et fournir son URL poolée dans
   `DATABASE_URL`.
3. Configurer toutes les variables de production listées ci-dessus.
4. Appliquer les migrations depuis un environnement de confiance avant de
   publier un changement qui dépend d'une nouvelle table :

   ```powershell
   $env:DATABASE_URL = '<URL PostgreSQL de production>'
   $env:DJANGO_SECRET_KEY = '<clé de production>'
   $env:DEBUG = 'False'
   $env:USE_SQLITE = 'False'
   .\.venv\Scripts\python.exe manage.py migrate --noinput
   ```

5. Pousser la branche `main`. Vercel construit et publie automatiquement le
   commit.
6. Vérifier `/health/`, la connexion, le calendrier et le scheduler.

La protection Vercel SSO reste active. Le secret de contournement destiné aux
automatisations doit être stocké uniquement dans GitHub Actions sous
`VERCEL_AUTOMATION_BYPASS_SECRET`.

## Rappels et Web Push

Les statuts avancent automatiquement sans retour arrière : un rendez-vous
`Planifié` devient `Confirmé` à son heure de début, puis `Terminé` à son heure
de fin. Si le traitement découvre après coup un rendez-vous planifié déjà fini,
il passe directement à `Terminé`. Les statuts `Annulé` et `Terminé`
ne sont jamais modifiés automatiquement. Chaque transition est auditée comme
une action système. Le workflow de cinq minutes assure le traitement en arrière-
plan ; l'ouverture du calendrier ou du dashboard applique aussi immédiatement
les transitions en attente.
Le contrôle PostgreSQL réversible s'exécute avec
`python manage.py shell -c "import runpy; runpy.run_path('tests/smoke_automatic_statuses.py')"`.

Le workflow `.github/workflows/notifications.yml` appelle toutes les cinq
minutes l'endpoint protégé `/api/cron/send-due-notifications/`. Deux secrets
GitHub sont requis :

- `CRON_SECRET`, identique à la valeur Vercel ;
- `VERCEL_AUTOMATION_BYPASS_SECRET`, fourni par Vercel Deployment Protection.

Le traitement est idempotent : un même rappel ne peut pas être envoyé deux
fois. Le navigateur doit autoriser les notifications et enregistrer une
souscription Push depuis la page Paramètres.

## Rapports de rendez-vous

Lorsqu'un rendez-vous passe à `Terminé`, chaque membre affecté reçoit une
demande de rapport et retrouve l'action à effectuer sur son tableau de bord.
Chaque participant peut envoyer un seul rapport individuel. L'envoi est
définitif : aucun écran ni endpoint ne permet ensuite de modifier le contenu.
Le membre consulte uniquement son propre rapport ; l'Administrateur et la
Gérante consultent tous les rapports du rendez-vous ainsi que la liste des
participants qui n'ont pas encore répondu.

L'historique enregistre l'auteur, la date et la longueur du rapport sans copier
son contenu. Si le compte de l'auteur est supprimé définitivement, son nom, son
adresse e-mail et son rapport restent conservés. Le rapport est lui-même
conservé lorsque le rendez-vous est archivé depuis le calendrier.
Le contrôle PostgreSQL réversible s'exécute avec
`python manage.py shell -c "import runpy; runpy.run_path('tests/smoke_appointment_reports.py')"`.

## Validation avant publication

```powershell
$env:DEBUG = 'True'
$env:USE_SQLITE = 'True'
$env:DJANGO_SECRET_KEY = 'une-cle-locale-de-test'
.\.venv\Scripts\python.exe manage.py test
node --test tests/js/calendar.test.cjs
node --test tests/js/calendar-color.test.cjs
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
```

Avec `DEBUG=False` et une clé éphémère longue, exécuter également
`manage.py check --deploy`.

## Setup initial des données

La page `/settings/data-setup/`, visible uniquement par l'Administrateur,
regroupe la configuration initiale de l'agence : nom, logo, fuseau horaire,
délai de rappel et types de rendez-vous. Elle affiche aussi un résumé des
membres, clients, types actifs et rendez-vous présents dans la base.

L'opération est non destructive : les données et types existants sont
conservés, et un type désactivé portant le même nom est réactivé. La date du
dernier setup et une trace d'audit sont enregistrées. L'URL PostgreSQL, les
mots de passe et les secrets restent exclusivement dans les variables du
serveur et ne sont jamais affichés ou modifiables depuis cette page.

## Exploitation et sauvegardes

L'Administrateur et la Gérante peuvent supprimer un rendez-vous depuis sa
fenêtre de détail, après confirmation. La suppression archive uniquement
l'occurrence sélectionnée : elle disparaît du calendrier et des tableaux de
bord, tandis que ses données et la trace `appointment_deleted` restent dans
l'historique. Les rappels et notifications non envoyés sont supprimés ; les
notifications déjà envoyées sont conservées. Les membres ordinaires n'ont pas
accès au bouton ni à l'endpoint de suppression.
Le contrôle PostgreSQL réversible s'exécute avec
`python manage.py shell -c "import runpy; runpy.run_path('tests/smoke_appointment_deletion.py')"`.

À la création d'un membre, le formulaire propose une couleur disponible avec
un sélecteur visuel et le code hexadécimal. Le mode automatique (activé par
défaut) revérifie la couleur à l'enregistrement ; une sélection manuelle
désactive ce mode et conserve le choix de l'administrateur. Sans JavaScript,
décocher le mode automatique pour enregistrer le choix manuel.
L'API attribue aussi une couleur disponible si `calendar_color` est omis ou vide.
L'attribution ignore la casse, réserve les couleurs des membres inactifs et
sérialise les créations PostgreSQL pour éviter les doublons automatiques.
La palette s'étend après épuisement des couleurs prédéfinies. Les couleurs
existantes ne sont pas modifiées ; le sélecteur est aussi disponible sur la
fiche membre et dans les paramètres du profil. Un choix manuel peut être partagé.

Dans Équipe, l'Admin et la Gérante peuvent utiliser « Supprimer », puis
confirmer sur la page dédiée. La suppression est définitive : le compte,
le profil, les notifications et les abonnements push sont effacés. L'adresse
e-mail est libérée et les anciennes sessions ne permettent plus d'accéder au site.
Les rendez-vous et clients restent conservés ; seuls les liens d'affectation
du membre sont retirés (les autres participants restent inchangés).
L'historique conserve une trace indépendante : identité du membre, identité
de l'auteur, date, anciens liens de création/modification et affectations.
Les anciennes actions du membre restent attribuées à son identité mémorisée,
même après effacement du compte. Aucun mot de passe n'est enregistré dans l'audit.
Les comptes archivés avant ce changement apparaissent dans « Anciens comptes
archivés » : leur suppression définitive exige une confirmation explicite.
Aucune migration n'efface automatiquement ces comptes. Un compte recréé avec
la même adresse possède un nouvel identifiant, sans récupérer les anciens accès.
Pour vérifier ce parcours sur la base configurée (y compris PostgreSQL),
`python manage.py shell -c "import runpy; runpy.run_path('tests/smoke_team_deletion.py')"`
utilise uniquement des comptes synthétiques dans une transaction annulée.
Ce contrôle n'envoie aucune notification et ne supprime aucun compte existant.
La suppression de son propre compte ou d'un administrateur est interdite.
La Gérante n'obtient pas pour autant le droit de créer des comptes ou de
modifier leurs rôles.

- surveiller les déploiements Vercel et les exécutions du workflow GitHub ;
- vérifier périodiquement `/health/` et les notifications échouées ;
- utiliser les mécanismes de sauvegarde/restauration du projet Neon ;
- avant une migration sensible, produire si nécessaire un export PostgreSQL
  avec `pg_dump` et tester sa restauration dans une base séparée ;
- ne jamais restaurer directement sur la production sans validation préalable.

Une procédure d'hébergement alternative est disponible dans
[`docs/CPANEL_DEPLOYMENT.md`](docs/CPANEL_DEPLOYMENT.md).
