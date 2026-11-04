from decimal import Decimal
from unittest.mock import MagicMock, patch
from django.test import SimpleTestCase
from assistant.db_service import analyze_phantom_bom
from assistant.views import _format_bom_analysis


class BomAnalyticsTests(SimpleTestCase):
    @patch('assistant.db_service.resolve_tenant_database', return_value='apptimate_test')
    @patch('assistant.db_service.get_tenant_connection')
    @patch('assistant.db_service._resolve_items_fuzzy')
    def test_requirement_shortage_and_warehouse_scope(self, resolve, connection, _tenant):
        resolve.return_value = [{'id': 1, 'sku': 'KIT', 'name': 'Kit', '_match_score': 1}]
        cursor = MagicMock()
        connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchall.side_effect = [[{'id': 2, 'organization_id': 3}], [
            {'id': 4, 'item_id': 5, 'quantity': Decimal('2'), 'uom_id': 6, 'stock_uom_id': 6,
             'sku': 'PART', 'name': 'Part', 'status': 'active', 'deleted_at': None,
             'has_variants': False, 'tracking_type': 'none'}]]
        cursor.fetchone.side_effect = [{'id': 7}, {'available': Decimal('9')}]
        result = analyze_phantom_bom('KIT', 'localhost', quantity=5, warehouse_id=7)
        self.assertEqual(result['components'][0]['required'], 10)
        self.assertEqual(result['components'][0]['shortage'], 1)
        sql, params = cursor.execute.call_args.args
        self.assertIn('s.warehouse_id=%s', sql)
        self.assertEqual(params, (5, 3, 3, 7))
        self.assertFalse(result['production_execution_verified'])

    def test_nonpositive_demand_is_rejected_before_connection(self):
        with patch('assistant.db_service.get_tenant_connection') as connect:
            for value in (0, -1, 'NaN', 'Infinity'):
                self.assertIn('error', analyze_phantom_bom('KIT', quantity=value))
            connect.assert_not_called()

    @patch('assistant.db_service.resolve_tenant_database', return_value='apptimate_test')
    @patch('assistant.db_service.get_tenant_connection')
    @patch('assistant.db_service._resolve_items_fuzzy')
    def test_multiple_boms_require_selection_instead_of_adding_requirements(self, resolve, connection, _tenant):
        resolve.return_value = [{'id': 1, 'sku': 'KIT', 'name': 'Kit', '_match_score': 1}]
        cursor = connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [{'id': 2, 'organization_id': 3}, {'id': 4, 'organization_id': 3}]
        result = analyze_phantom_bom('KIT', 'localhost', quantity=5)
        self.assertTrue(result['ambiguous_bom'])
        self.assertEqual(result['components'], [])
        self.assertIn('Which BOM ID', _format_bom_analysis(result, 'requirements'))
        self.assertEqual(cursor.execute.call_count, 1)

    def test_invalid_mode_is_rejected_without_a_connection(self):
        with patch('assistant.db_service.get_tenant_connection') as connect:
            self.assertEqual(analyze_phantom_bom('KIT', mode='issue_stock')['error_type'], 'validation')
            connect.assert_not_called()

    def test_inactive_duplicate_or_unit_mismatch_does_not_confirm_stock(self):
        result = {'found': True, 'item': {'name': 'Kit', 'sku': 'KIT'}, 'boms': [{'id': 1}],
                  'demand': 5, 'scope': 'Selected active warehouse', 'warehouse_id': 7,
                  'components': [{'name': 'Part', 'sku': 'P', 'item_id': 4, 'status': 'inactive',
                      'deleted_at': None, 'quantity': 2, 'required': 10, 'available': 50,
                      'shortage': 0, 'duplicate': True, 'unit_compatible': False,
                      'has_variants': False, 'tracking_type': 'none'}]}
        answer = _format_bom_analysis(result, 'Check requirements and cost')
        self.assertIn('not confirmed', answer)
        self.assertIn('inactive', answer)
        self.assertIn('duplicate', answer)
        self.assertIn('unit conversion', answer)
        self.assertIn('not verified', answer)
