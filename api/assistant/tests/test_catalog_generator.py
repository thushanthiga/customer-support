import os
import sys
import tempfile
from unittest.mock import MagicMock, patch
from django.core.management import call_command
from django.test import SimpleTestCase
from assistant.catalog_generator import generate_database_catalog
from assistant.apps import AssistantConfig


class CatalogGeneratorTests(SimpleTestCase):
    def test_generate_database_catalog_success(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = [
            # 1. columns query
            [
                {
                    "TABLE_NAME": "inventory_items",
                    "COLUMN_NAME": "id",
                    "COLUMN_TYPE": "bigint unsigned",
                    "IS_NULLABLE": "NO",
                    "COLUMN_KEY": "PRI",
                    "COLUMN_DEFAULT": None,
                    "EXTRA": "auto_increment",
                    "COLUMN_COMMENT": "",
                },
                {
                    "TABLE_NAME": "inventory_items",
                    "COLUMN_NAME": "name",
                    "COLUMN_TYPE": "varchar(255)",
                    "IS_NULLABLE": "NO",
                    "COLUMN_KEY": "",
                    "COLUMN_DEFAULT": None,
                    "EXTRA": "",
                    "COLUMN_COMMENT": "",
                },
            ],
            # 2. foreign keys query
            [
                {
                    "TABLE_NAME": "inventory_items",
                    "COLUMN_NAME": "category_id",
                    "REFERENCED_TABLE_NAME": "inventory_categories",
                    "REFERENCED_COLUMN_NAME": "id",
                }
            ],
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_target = os.path.join(tmp_dir, "test_catalog.md")
            with patch("assistant.db_service.get_tenant_connection", return_value=mock_conn):
                success = generate_database_catalog(tenant_db="apptimate_test", target_file=tmp_target)
                self.assertTrue(success)
                self.assertTrue(os.path.exists(tmp_target))

                with open(tmp_target, "r", encoding="utf-8") as f:
                    content = f.read()

                self.assertIn("# Apptimate One ERP — Authoritative Database Catalog", content)
                self.assertIn("Module 1: Inventory & Stock Management", content)
                self.assertIn("Cross-Table Relationship Matrix", content)
                self.assertIn("Canonical Analytical Recipes & CTE Query Patterns", content)
                self.assertIn("Recipe 1: Items Below Item Master Minimum Stock", content)
                self.assertIn("`inventory_items`", content)

    def test_generate_database_catalog_db_error_is_graceful(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_target = os.path.join(tmp_dir, "test_catalog.md")
            with patch("assistant.db_service.get_tenant_connection", side_effect=RuntimeError("Connection refused")):
                success = generate_database_catalog(tenant_db="apptimate_test", target_file=tmp_target)
                self.assertFalse(success)
                self.assertFalse(os.path.exists(tmp_target))

    def test_update_catalog_management_command(self):
        with patch("assistant.catalog_generator.generate_database_catalog", return_value=True) as mock_gen:
            call_command("update_catalog", tenant="apptimate_custom")
            mock_gen.assert_called_once_with(tenant_db="apptimate_custom", target_file=None)

    def test_apps_ready_skips_during_test_command(self):
        cfg = AssistantConfig("assistant", sys.modules[AssistantConfig.__module__])
        with patch("assistant.catalog_generator.generate_database_catalog") as mock_gen:
            # sys.argv contains 'test' during test execution
            cfg.ready()
            mock_gen.assert_not_called()

