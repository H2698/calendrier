# Déploiement alternatif cPanel / Passenger

La production actuelle utilise Vercel et Neon. Ce guide décrit l'alternative
cPanel demandée dans le cahier des charges ; elle ne doit être appliquée que si
l'hébergeur prend réellement en charge tous les prérequis.

## Prérequis

- Python 3.12 ou une version compatible avec Django 5.2 ;
- Application Manager / Setup Python App avec Passenger ;
- accès SSH recommandé ;
- Cron Jobs ;
- certificat SSL valide ;
- accès sortant HTTPS pour Web Push ;
- connexion PostgreSQL externe autorisée vers Neon ;
- possibilité de définir des variables d'environnement.

Les noms des menus et chemins varient selon l'hébergeur. Valider ces éléments
avec son support avant la migration.

## Installation

Cloner le dépôt dans un répertoire dédié, sans placer `.env` dans un dossier
public. Depuis le terminal cPanel :

```bash
python3.12 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python manage.py check
```

Créer l'application Python dans cPanel avec :

- racine de l'application : le dossier du dépôt ;
- fichier WSGI : `config/wsgi.py` ;
- callable : `application` ;
- environnement : production.

Si cPanel exige un fichier `passenger_wsgi.py` à la racine, utiliser ce petit
adaptateur :

```python
import os
import sys

APP_ROOT = os.path.dirname(__file__)
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from config.wsgi import application
```

## Environnement

Définir dans l'interface de l'application, et jamais dans Git :

```text
DJANGO_SECRET_KEY=<clé aléatoire longue>
DEBUG=False
USE_SQLITE=False
DATABASE_URL=<URL PostgreSQL poolée Neon avec sslmode=require>
ALLOWED_HOSTS=calendar.example.com
CSRF_TRUSTED_ORIGINS=https://calendar.example.com
TIME_ZONE=Africa/Tunis
VAPID_PUBLIC_KEY=<clé publique>
VAPID_PRIVATE_KEY=<clé privée>
VAPID_SUBJECT=mailto:admin@example.com
CRON_SECRET=<secret aléatoire>
SECURE_HSTS_SECONDS=31536000
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=<serveur SMTP>
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=<utilisateur SMTP>
EMAIL_HOST_PASSWORD=<mot de passe SMTP>
```

Redémarrer Passenger après chaque changement d'environnement.

## Base et fichiers statiques

Dans le virtualenv et avec les variables de production chargées :

```bash
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py check --deploy
```

Configurer le serveur web pour exposer `staticfiles/` sous `/static/`. Si
l'interface cPanel ne permet pas ce mapping, demander la méthode compatible à
l'hébergeur plutôt que de servir les statiques via Django en production.

## HTTPS et sécurité

Activer AutoSSL, forcer HTTPS et vérifier que le proxy transmet correctement
`X-Forwarded-Proto`. Tester ensuite les cookies Secure, CSRF, HSTS et le Service
Worker. Conserver les clés VAPID et la clé Django uniquement côté serveur.

## Cron

La méthode la plus simple sur cPanel est d'exécuter directement la commande
Django toutes les cinq minutes :

```cron
*/5 * * * * /chemin/vers/venv/bin/python /chemin/vers/app/manage.py send_due_notifications
```

Utiliser les chemins absolus fournis par l'hébergeur et vérifier que le cron
charge les mêmes variables d'environnement que Passenger. L'endpoint HTTP avec
`CRON_SECRET` reste une alternative si le cron ne peut pas charger l'application
Django directement.

## Sauvegarde, mise à jour et retour arrière

Avant une mise à jour importante :

1. vérifier la sauvegarde Neon et, si nécessaire, créer un export `pg_dump` ;
2. noter le commit actuellement déployé ;
3. récupérer le nouveau commit et installer les dépendances ;
4. appliquer les migrations puis collecter les statiques ;
5. redémarrer Passenger ;
6. effectuer les smoke tests ci-dessous.

Un retour au code précédent ne doit pas inclure une annulation destructive de
migration sans plan de restauration testé.

## Smoke tests

- `/health/` répond avec succès et confirme la base ;
- la page de connexion fonctionne en HTTPS ;
- Admin, Manager et Member accèdent uniquement aux fonctions autorisées ;
- un rendez-vous peut être créé, modifié, déplacé et annulé ;
- un Member non affecté ne reçoit aucune donnée client privée ;
- les statiques, FullCalendar et le menu mobile se chargent ;
- le cron crée le rappel une seule fois ;
- l'activation Web Push fonctionne sur un navigateur compatible ;
- l'historique contient les actions effectuées.
