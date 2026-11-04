from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from assistant.db_service import resolve_tenant_database


class TenantResolutionTests(SimpleTestCase):
    @patch("assistant.db_service.get_root_connection")
    def test_registered_local_domain_with_port_resolves_to_tenant_database(self, get_root_connection):
        connection = MagicMock()
        cursor = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor
        cursor.__enter__.return_value = cursor
        cursor.fetchone.side_effect = [
            {"tenant_id": "infinity"},
            {"id": "apptimate_infinity", "data": "{}"},
        ]
        get_root_connection.return_value = connection

        self.assertEqual(resolve_tenant_database("localhost:3008"), "apptimate_infinity")

    @patch("assistant.db_service.get_root_connection")
    def test_unregistered_explicit_tenant_fails_instead_of_using_default(self, get_root_connection):
        connection = MagicMock()
        cursor = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor
        cursor.__enter__.return_value = cursor
        cursor.fetchone.return_value = None
        get_root_connection.return_value = connection

        with self.assertRaisesRegex(LookupError, "not registered"):
            resolve_tenant_database("unknown.example.test")

    @patch("assistant.db_service.ALLOW_DEFAULT_TENANT", True)
    def test_missing_tenant_identifier_uses_configured_local_default(self):
        self.assertEqual(resolve_tenant_database(None), "apptimate_infinity")

    @patch("assistant.db_service.ALLOW_DEFAULT_TENANT", False)
    def test_missing_tenant_identifier_fails_when_default_tenant_is_disabled(self):
        with self.assertRaisesRegex(LookupError, "required"):
            resolve_tenant_database(None)

