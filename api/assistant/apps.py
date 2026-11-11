import os
import sys
import logging
import threading
from django.apps import AppConfig

logger = logging.getLogger(__name__)


def _refresh_catalog_in_background():
    """Regenerate the tenant database catalog without blocking worker startup."""
    try:
        from .catalog_generator import generate_database_catalog
        generate_database_catalog()
    except Exception as exc:
        logger.warning("[ASSISTANT_CONFIG] Database catalog generation skipped on startup: %s", exc)


class AssistantConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'assistant'

    def ready(self):
        # 1. Skip catalog regeneration during non-server commands (tests, migrations, inline scripts)
        skip_commands = {'test', 'makemigrations', 'migrate', 'collectstatic', 'check', 'update_catalog', 'shell', '-c'}
        if any(arg in skip_commands for arg in sys.argv):
            return

        # 2. In runserver mode, only execute in the main serving worker (RUN_MAIN == 'true'),
        #    not the autoreload watcher process, preventing duplicate execution.
        is_runserver = any('runserver' in arg for arg in sys.argv)
        if is_runserver and os.environ.get('RUN_MAIN') != 'true':
            return

        # 3. Refresh authoritative catalog asynchronously so worker startup/autoreload stays instant
        threading.Thread(
            target=_refresh_catalog_in_background,
            name="assistant-catalog-refresh",
            daemon=True,
        ).start()

