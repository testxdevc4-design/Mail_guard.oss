"""
apps/worker/main.py — ARQ WorkerSettings for MailGuard OSS.

Registers:
  - ``task_send_email``   (ad-hoc enqueued task)
  - ``purge_expired_otps`` (cron every 15 minutes)

Start the worker with:
    arq apps.worker.main.WorkerSettings
"""
from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings

from apps.worker.tasks.purge_otps import purge_expired_otps
from apps.worker.tasks.send_email import task_send_email
from apps.worker.tasks.deliver_webhook import task_deliver_webhook
from core.config import settings


def _parse_redis_settings() -> RedisSettings:
    """Convert the REDIS_URL string into an ARQ RedisSettings object."""
    url = settings.REDIS_URL
    # Strip scheme: redis:// or rediss://
    use_ssl = url.startswith("rediss://")
    host_part = url.split("://", 1)[1]

    # Parse optional user:pass@host:port/db
    host = "localhost"
    port = 6379
    password = None
    database = 0

    # Remove /db suffix
    if "/" in host_part:
        host_part, db_str = host_part.rsplit("/", 1)
        try:
            database = int(db_str)
        except ValueError:
            database = 0

    # Remove user:pass@ prefix
    if "@" in host_part:
        userinfo, host_part = host_part.rsplit("@", 1)
        if ":" in userinfo:
            _, password = userinfo.split(":", 1)

    # Split host:port
    if ":" in host_part:
        host, port_str = host_part.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            port = 6379
    else:
        host = host_part

    return RedisSettings(
        host=host,
        port=port,
        password=password,
        database=database,
        ssl=use_ssl,
    )


class WorkerSettings:
    """ARQ WorkerSettings — registers all tasks and the purge cron job."""

    redis_settings = _parse_redis_settings()

    functions = [task_send_email, task_deliver_webhook]

    cron_jobs = [
        cron(purge_expired_otps, minute={0, 15, 30, 45}),
    ]

    # Keep jobs alive for up to 10 minutes to handle the 300 s final backoff.
    job_timeout = 660

    # How long to keep completed job results in Redis.
    keep_result = 3600
