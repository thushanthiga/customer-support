from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from assistant.views import _review_generated_answer


class LiveAnswerValidationTests(SimpleTestCase):
    @patch("assistant.views.client.chat.completions.create")
    def test_accepts_an_answer_only_when_the_evidence_review_approves_it(self, create_completion):
        create_completion.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"valid": true, "reason": "The answer matches the query result."}'
            ))],
            usage=SimpleNamespace(prompt_tokens=21, completion_tokens=9),
        )

        valid, reason, prompt_tokens, completion_tokens = _review_generated_answer(
            "How many active customers do we have?",
            "There are 12 active customers.",
            [{"tool": "query_business_data", "result": {"results": [{"count": 12}]}}],
        )

        self.assertTrue(valid)
        self.assertIn("matches", reason)
        self.assertEqual((prompt_tokens, completion_tokens), (21, 9))

    @patch("assistant.views.client.chat.completions.create")
    def test_rejects_an_unrelated_or_unsupported_answer(self, create_completion):
        create_completion.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"valid": false, "reason": "The result does not contain the claimed quantity."}'
            ))],
            usage=SimpleNamespace(prompt_tokens=15, completion_tokens=8),
        )

        valid, reason, _, _ = _review_generated_answer(
            "How many active customers do we have?",
            "There are 18 warehouses.",
            [{"tool": "query_business_data", "result": {"results": [{"count": 12}]}}],
        )

        self.assertFalse(valid)
        self.assertIn("does not contain", reason)

    @patch("assistant.views.client.chat.completions.create", side_effect=RuntimeError("unavailable"))
    def test_fails_closed_when_the_review_service_is_unavailable(self, _create_completion):
        valid, reason, prompt_tokens, completion_tokens = _review_generated_answer(
            "List suppliers",
            "Here are the suppliers.",
            [],
        )

        self.assertFalse(valid)
        self.assertIn("could not be checked", reason)
        self.assertEqual((prompt_tokens, completion_tokens), (0, 0))


    @patch('assistant.views.client.chat.completions.create')
    def test_reviewer_cannot_approve_a_misquoted_scalar_count(self, completion):
        completion.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"valid": true, "reason": "Looks correct"}'))],
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=2),
        )
        sources = [{'result': {'query_audit': {'selected_fields': [{'aggregate': 'COUNT'}]},
                              'results': [{'total': 44579}]}}]
        valid, reason, _, _ = _review_generated_answer('How many inventory items?', '45,579 items', sources)
        self.assertFalse(valid)
        self.assertIn('44579', reason)
        valid, _, _, _ = _review_generated_answer('How many inventory items?', '44,579 items', sources)
        self.assertTrue(valid)
