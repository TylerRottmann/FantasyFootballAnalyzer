# Server performance setup

The app uses Redis when `REDIS_URL` is configured and falls back to per-process
memory cache for local development. Production web workers and scheduled jobs
must use the same Redis URL for cache warming and invalidation to be shared.

## Production environment

Set these values in the hosting provider's environment configuration:

```text
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=your-domain.example,www.your-domain.example
DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain.example,https://www.your-domain.example
REDIS_URL=rediss://user:password@redis-host:port/0
DB_CONN_MAX_AGE=60
SLOW_REQUEST_LOG_THRESHOLD_MS=500
```

For PgBouncer/Supabase transaction-pool hosts, the settings default to no
persistent application connection and disabled server-side cursors. Override
`DB_CONN_MAX_AGE` only after checking the pooler's mode and connection limits.
Direct PostgreSQL connections default to 60-second persistent connections.

Deploy the updated requirements, then collect static assets during release:

```powershell
python -m pip install -r requirements.txt
python manage.py collectstatic --noinput
```

WhiteNoise serves compressed, fingerprinted static files from `STATIC_ROOT`.
If the host uses a CDN or object storage for static files, configure that host
instead of serving the assets from the Django worker.

## Scheduled cache refresh

Run this command every five minutes from the host's scheduler, using the same
environment and `REDIS_URL` as the web workers:

```powershell
python manage.py refresh_external_cache
```

It refreshes the current NFL week and warms Sleeper playoff metadata. The web
request reads cached values, and a single cold start can still fetch the NFL
week once if neither a fresh nor a last-known value exists.

Projection generation updates a season cache version so Weekly Rankings rebuild
after new projections are saved. Matchup sync and league edits also produce a
new rankings cache key. Rankings snapshots remain cached for 30 minutes.

## Slow request logs

Requests over `SLOW_REQUEST_LOG_THRESHOLD_MS` emit a warning with route, status,
total duration, aggregate database duration, and query count. Use those records
to identify slow routes before changing indexes or query plans. The default
threshold is 500 ms.
