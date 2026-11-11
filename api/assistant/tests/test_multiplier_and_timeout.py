"""Tests for explicit multiplier sanitization and bounded planning timeout budgets."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from assistant.domain_schema import expression_has_multiplier, extract_explicit_multiplier
from assistant.local_engine import LocalAnswer
from assistant.query_planner import (
    OUTPUT,
    PlanningValidationError,
    _parse_response,
    _sanitize_review_result,
    plan_question,
    planning_budget,
)


class MultiplierSanitizationTests(SimpleTestCase):
    def test_extract_explicit_multiplier_recognizes_named_and_numeric_forms(self):
        self.assertEqual(extract_explicit_multiplier("outstanding balance is more than double the amount"), 2.0)
        self.assertEqual(extract_explicit_multiplier("more than twice their latest invoice"), 2.0)
        self.assertEqual(extract_explicit_multiplier("more than triple their credit limit"), 3.0)
        self.assertEqual(extract_explicit_multiplier("more than 4000 times the amount"), 4000.0)
        self.assertEqual(extract_explicit_multiplier("at least 2.5x the latest bill"), 2.5)
        self.assertIsNone(extract_explicit_multiplier("list all active suppliers"))

    def test_expression_has_multiplier_matches_ast_nodes(self):
        mult_expr = {
            "operator": "-",
            "left": {"table": "cte_balances", "column": "outstanding_balance"},
            "right": {
                "expression": {
                    "operator": "*",
                    "left": 2,
                    "right": {"table": "cte_latest", "column": "latest_invoice_amount"},
                }
            },
        }
        self.assertTrue(expression_has_multiplier(mult_expr, 2))
        self.assertFalse(expression_has_multiplier(mult_expr, 3))
        self.assertTrue(
            expression_has_multiplier(
                {"operator": "*", "left": {"table": "inv", "column": "total"}, "right": 4000},
                4000,
            )
        )

    def test_spurious_double_multiplier_rejection_is_sanitized_to_approve(self):
        question = "list down all the suppliers whose outstanding balance is more than double the amount of their latest invoice"
        proposal = {
            "plans": [
                {
                    "id": "suppliers_over_double",
                    "base_table": "core_parties",
                    "select": [{"table": "core_parties", "column": "name", "alias": "supplier_name"}],
                    "filters": [
                        {
                            "expression": {
                                "operator": "-",
                                "left": {"table": "cte_balances", "column": "outstanding_balance"},
                                "right": {
                                    "expression": {
                                        "operator": "*",
                                        "left": 2,
                                        "right": {"table": "cte_latest", "column": "latest_invoice_amount"},
                                    }
                                },
                            },
                            "operator": ">",
                            "value": 0,
                        }
                    ],
                }
            ]
        }
        review = {
            "verdict": "clarify",
            "issues": [
                "The candidate uses a fixed multiplier of 2 instead of allowing for dynamic input as requested for future requests.",
            ],
            "clarification": "Please specify the exact multiplier to use (e.g., 2 for double).",
        }
        issues, clarification = _sanitize_review_result(question, proposal, review)
        self.assertEqual(issues, [])
        self.assertEqual(clarification, "")
        self.assertEqual(review["verdict"], "approve")

    def test_genuine_multiplier_mismatch_is_not_masked(self):
        question = "list suppliers whose balance is more than 4000 times their latest invoice"
        proposal = {
            "plans": [
                {
                    "id": "suppliers_over_double",
                    "base_table": "core_parties",
                    "select": [{"table": "core_parties", "column": "name", "alias": "supplier_name"}],
                    "filters": [
                        {
                            "expression": {
                                "operator": "*",
                                "left": 2,
                                "right": {"table": "cte_latest", "column": "latest_invoice_amount"},
                            },
                            "operator": "<",
                            "value": 0,
                        }
                    ],
                }
            ]
        }
        review = {
            "verdict": "revise",
            "issues": [
                "The candidate uses a fixed multiplier of 2 instead of the requested 4000.",
            ],
            "clarification": "",
        }
        issues, _ = _sanitize_review_result(question, proposal, review)
        self.assertEqual(len(issues), 1)
        self.assertEqual(review["verdict"], "revise")


class PlanningBudgetTests(SimpleTestCase):
    @patch("assistant.query_planner.client")
    def test_expired_planning_budget_raises_non_retryable_error_without_calling_openai(self, mock_client):
        mock_client.responses.create = MagicMock()
        with planning_budget(0.0):
            with self.assertRaises(PlanningValidationError) as ctx:
                plan_question("list suppliers", "schema")
        self.assertFalse(ctx.exception.retryable)
        mock_client.responses.create.assert_not_called()

    def test_spurious_18000_multiplier_and_gt_ambiguity_complaints_are_sanitized(self):
        question = "list down all the suppliers whose outstanding balance is more than 18000 times of the amount of their latest invoice"
        proposal = {
            "plans": [
                {
                    "id": "suppliers_18000x",
                    "base_table": "core_parties",
                    "select": [{"table": "core_parties", "column": "name", "alias": "supplier_name"}],
                    "filters": [
                        {
                            "table": "cte_balances",
                            "column": "outstanding_balance",
                            "operator": ">",
                            "value": {
                                "operator": "*",
                                "left": 18000,
                                "right": {"table": "cte_latest", "column": "latest_invoice_amount"},
                            },
                        }
                    ],
                }
            ]
        }
        review = {
            "verdict": "revise",
            "issues": [
                "The multiplier for the outstanding balance comparison is incorrectly stated as 18000; it does not reflect the user's explicit ratio requirement of 'more than 18000 times' the amount of their latest invoice, which should be represented as a literal '18000'.",
                "The plan needs to ensure that the comparison for outstanding balances is clearly indicated as '>' rather than allowing for ambiguity.",
            ],
            "clarification": "Please confirm the exact ratio you intended to use for the outstanding balance compared to their latest invoice amount.",
        }
        issues, clarification = _sanitize_review_result(question, proposal, review)
        self.assertEqual(issues, [])
        self.assertEqual(clarification, "")
        self.assertEqual(review["verdict"], "approve")

    def test_parse_response_lifts_nested_comparison_filter_and_strips_extra_expr_keys(self):
        payload = {
            "intent": "records",
            "resolved_question": "list suppliers",
            "analysis_contract": {
                "goal": "List suppliers",
                "entity": "core_parties",
                "metric": "suppliers",
                "grain": "one row per supplier",
                "scope": "all non-deleted suppliers",
                "context_used": [],
                "assumptions": [],
                "ambiguities": [],
                "requirements": [{"requirement": "Filter by 18000x ratio", "status": "supported", "plan_indexes": [0], "limitation": ""}],
            },
            "plans": [
                {
                    "base_table": "core_parties",
                    "select": [{"table": "core_parties", "column": "name", "alias": "supplier_name"}],
                    "filters": [
                        {
                            "expression": {
                                "operator": ">",
                                "left": {"table": "cte_balances", "column": "outstanding_balance"},
                                "right": {
                                    "operator": "*",
                                    "left": 18000,
                                    "right": {"table": "cte_latest", "column": "latest_invoice_amount"},
                                    "unexpected_extra": "should_be_stripped",
                                },
                            }
                        }
                    ],
                }
            ],
        }
        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(refusal=None, content=json.dumps(payload)))]
        )
        parsed = _parse_response(fake_response, OUTPUT, "list suppliers")
        flt = parsed["plans"][0]["filters"][0]
        self.assertEqual(flt["operator"], ">")
        self.assertEqual(flt["table"], "cte_balances")
        self.assertEqual(flt["column"], "outstanding_balance")
        self.assertNotIn("unexpected_extra", flt["value"])

    @patch("assistant.local_engine.evaluate_query", return_value={"passed": True, "score": 100, "threshold": 85, "checks": [], "reasons": []})
    def test_execute_canonical_fallback_renders_and_marks_answered(self, mock_eval_q):
        ans = LocalAnswer("apptimate_test", {"user_id": 1}, "list suppliers")
        plan = {
            "base_table": "core_parties",
            "select": [{"table": "core_parties", "column": "name", "alias": "supplier"}],
            "filters": [{"table": "core_parties", "column": "deleted_at", "operator": "IS NULL", "value": None}],
        }
        fake_result = {
            "results": [{"supplier": "Supplier A"}],
            "truncated": False,
            "query_audit": {
                "selected_fields": [{"table": "core_parties", "column": "name", "alias": "supplier"}],
                "filters": [],
                "group_by": [],
                "having": [],
                "compiled_sql": "SELECT name FROM core_parties",
            },
            "mcp_read_at": "2026-11-11T09:00:00",
        }
        with patch.object(ans, "query", return_value=fake_result):
            ok = ans._execute_canonical_fallback(plan, {"tables": {"core_parties": {"name": "varchar"}}}, {"retrieved_tables": ["core_parties"]})
        self.assertTrue(ok)
        self.assertEqual(ans.status, "answered")
        self.assertTrue(any("Supplier A" in p for p in ans.parts))
