"""The evaluator must catch plausible false passes."""
from pathlib import Path
import importlib.util
import unittest
from decimal import Decimal
from django.test import SimpleTestCase

metrics_path = Path(__file__).resolve().parents[3] / 'eval/metrics.py'
if not metrics_path.exists():
    raise unittest.SkipTestCase("eval/metrics.py is excluded")

spec = importlib.util.spec_from_file_location('eval_metrics', metrics_path)
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)

class EvalMetricsTests(SimpleTestCase):
    def test_swapped_columns_do_not_pass(self):
        self.assertFalse(metrics.rows_match([{'revenue':10,'cost':20}],[{'revenue':20,'cost':10}]))
    def test_missing_duplicate_row_does_not_pass(self):
        self.assertFalse(metrics.rows_match([{'n':1},{'n':1}],[{'n':1}]))
    def test_exact_decimal_equivalence_and_explicit_alias_mapping(self):
        self.assertTrue(metrics.rows_match([{'total':Decimal('12.50')}],[{'amount':12.5}],columns={'total':'amount'}))
        self.assertFalse(metrics.rows_match([{'total':Decimal('12345678901234567890.01')}],[{'total':Decimal('12345678901234567890.02')}]))
    def test_order_and_identifiers_remain_meaningful(self):
        self.assertFalse(metrics.rows_match([{'id':'001'}],[{'id':1}]))
        self.assertFalse(metrics.rows_match([{'id':1},{'id':2}],[{'id':2},{'id':1}],ordered=True))
    def test_missing_evidence_is_not_a_pass(self):
        self.assertEqual(metrics.fraction([None,None]),{'value':None,'measured':0,'eligible':2,'missing':2})
        self.assertFalse(metrics.rows_match([{'amount':None}],[{'amount':0}]))
    def test_offline_and_missing_coverage_cannot_certify(self):
        report={'mode':'offline','split':'heldout','summary':metrics.summarize([{'id':'x','checks':{'classification':True}}])}
        self.assertGreater(len(metrics.certification_failures(report)),1)
