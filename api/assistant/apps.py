import os
import sys
import logging
from django.apps import AppConfig

logger = logging.getLogger(__name__)


class AssistantConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'assistant'

    def ready(self):
        # 1. Skip catalog regeneration during non-server management commands (e.g. tests, migrations)
        skip_commands = {'test', 'makemigrations', 'migrate', 'collectstatic', 'check', 'update_catalog'}
        if any(arg in skip_commands for arg in sys.argv):
            return

        # 2. In runserver mode, only execute in the main serving worker (RUN_MAIN == 'true'),
        #    not the autoreload watcher process, preventing duplicate execution.
        #    If not runserver (e.g. gunicorn, uwsgi, asgi, or runserver --noreload), execute once.
        is_runserver = any('runserver' in arg for arg in sys.argv)
        if is_runserver and os.environ.get('RUN_MAIN') != 'true':
            return

        # 3. Regenerate authoritative catalog from live DB on fresh server startup
        try:
            from .catalog_generator import generate_database_catalog
            generate_database_catalog()
        except Exception as exc:
            logger.warning("[ASSISTANT_CONFIG] Database catalog generation skipped on startup: %s", exc)

