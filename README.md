# Agency Calendar

Internal agency calendar built with Django 5.2. The source is hosted on GitHub and
the application is designed for zero-configuration Django deployment on Vercel.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

For local development, keep `USE_SQLITE=True`. The health endpoint is available
at `http://127.0.0.1:8000/health/`.

## Vercel deployment

1. Import `H2698/calendrier` from GitHub into Vercel.
2. Add a Neon Postgres integration from the Vercel Marketplace, or provide a
   pooled PostgreSQL connection string as `DATABASE_URL`.
3. Set these production environment variables:

   - `DJANGO_SECRET_KEY`: a long random value
   - `DEBUG`: `False`
   - `USE_SQLITE`: `False`
   - `DATABASE_URL`: the pooled PostgreSQL connection string
   - `TIME_ZONE`: `Africa/Tunis`

Vercel detects `manage.py` and the Django WSGI application automatically. No
custom `vercel.json` routing is required.

Run migrations against the production database from a trusted environment before
promoting the deployment:

```powershell
$env:DATABASE_URL = '<production pooled connection string>'
$env:USE_SQLITE = 'False'
.\.venv\Scripts\python.exe manage.py migrate
```

Never commit `.env`, database credentials, or Django secret keys.
