from django.core.management.base import BaseCommand
from assistant.catalog_generator import generate_database_catalog, DEFAULT_CATALOG_PATH


class Command(BaseCommand):
    help = "Update the authoritative database catalog (apptimate_db_catalog.md) from live MySQL schema metadata."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant",
            type=str,
            default=None,
            help="Tenant database name to inspect (defaults to DEFAULT_TENANT_ID or apptimate_infinity).",
        )
        parser.add_argument(
            "--output",
            type=str,
            default=None,
            help="Target markdown file path (defaults to uploads/apptimate_db_catalog.md).",
        )

    def handle(self, *args, **options):
        tenant = options.get("tenant")
        output = options.get("output")
        self.stdout.write(f"Generating authoritative ERP database catalog from live database '{tenant or 'default'}'...")
        success = generate_database_catalog(tenant_db=tenant, target_file=output)
        if success:
            self.stdout.write(self.style.SUCCESS(f"Successfully updated authoritative database catalog at {output or DEFAULT_CATALOG_PATH}!"))
        else:
            self.stdout.write(self.style.WARNING("Catalog generation could not connect to MySQL; existing catalog preserved."))

