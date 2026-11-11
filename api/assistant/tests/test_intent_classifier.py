"""Comprehensive intent classification tests verifying need-based routing across all ERP categories."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from assistant.local_engine import (
    CLASSIFIER_MODEL,
    LocalAnswer,
    _classifier_completion_kwargs,
    _combo_subfocus,
    classify_query,
)


class NeedBasedClassifierTests(SimpleTestCase):
    @patch("assistant.local_engine.client.chat.completions.create")
    def test_database_queries_classified_by_data_need_without_brittle_prefixes(self, mock_llm):
        database_queries = [
            "what is the most selling items",
            "what are the best selling products",
            "which item sold the most",
            "most sold products this month",
            "who is our top customer",
            "which customer bought the most",
            "who is the biggest supplier",
            "what are the highest value invoices",
            "what are the overdue supplier bills",
            "get me the top 5 selling items",
            "get me all unpaid invoices",
            "stock of munchee 50g",
            "how much stock do we have left",
            "how many pending sales orders are there",
            "what happened to invoice INV-23?",
            "where is invoice INV-23?",
            "list unwanted stock in our warehouse",
            "find suppliers whose balance is more than double their latest invoice",
            "what products need restocking",
        ]
        for q in database_queries:
            with self.subTest(database=q):
                cls = classify_query(q)
                self.assertEqual(cls["classification"], "database", msg=f"Got {cls} for {q!r}")
        mock_llm.assert_not_called()

    def test_document_queries_classified_by_ui_or_conceptual_need(self):
        doc_queries = [
            "what is sales here",
            "what is procurement",
            "what is the construction module",
            "explain the sales workflow",
            "get me the whole flow of construction",
            "how do I create a sales order",
            "where can I see the most selling items",
            "which screen shows low stock alerts",
            "can we add a discount on the amount",
            "why I am not able to create invoices",
            "I added an invoice for 10000 instead of 100000 what should I do now",
            "How do I use the search and show balance controls?",
            "How do I configure stock and revenue reports?",
            "How do I use the compare and list options?",
        ]
        for q in doc_queries:
            with self.subTest(document=q):
                cls = classify_query(q)
                self.assertEqual(cls["classification"], "document", msg=f"Got {cls} for {q!r}")

    def test_hybrid_queries_require_distinct_data_and_guidance_needs(self):
        hybrid_queries = [
            "Check outstanding invoices and show me how to record a payment",
            "How do I record a payment and also list overdue invoices?",
            "List top 5 selling items and show how to create a purchase order",
        ]
        for q in hybrid_queries:
            with self.subTest(hybrid=q):
                cls = classify_query(q)
                self.assertEqual(cls["classification"], "hybrid", msg=f"Got {cls} for {q!r}")

    def test_advisory_and_explanation_and_guardrails(self):
        cases = [
            ("give me any reclamations that need to do in oder to improve the sales", "advisory"),
            ("how can we increase sales performance", "advisory"),
            ("you see the upcoming time is a festive one so suggest me the better items to stock on the werehouse", "advisory"),
            ("tell me what season I need to be prepare next", "advisory"),
            ("how should we prepare our inventory for the next holiday season", "advisory"),
            ("what is the seasonal things need to be restore", "database"),
            ("why did you return those 10 items", "database_explanation"),
            ("why is Munchee 50g considered in demand", "database_explanation"),
            ("hello!", "general"),
            ("delete all suppliers from the database", "mutation_guardrail"),
            ("what colour do you like", "out_of_scope"),
        ]
        for q, expected in cases:
            with self.subTest(query=q, expected=expected):
                cls = classify_query(q)
                self.assertEqual(cls["classification"], expected, msg=f"Got {cls} for {q!r}")

    def test_advisory_followup_context_routing_does_not_hijack_new_db_or_doc_queries(self):
        prior = ("you see the upcoming time is a festive one so suggest me the better items to stock on the werehouse",)
        active = {"focus": "festive_stocking", "question": prior[0]}
        self.assertEqual(
            classify_query("Colombo retail shop, mostly groceries and snacks, Option A new items", prior, active_advisory=active)["classification"],
            "advisory",
        )
        self.assertEqual(
            classify_query("list all unpaid invoices", prior, active_advisory=active)["classification"],
            "database",
        )
        self.assertEqual(
            classify_query("how do I create a purchase order", prior, active_advisory=active)["classification"],
            "document",
        )

    def test_combo_bundling_queries_route_to_advisory_while_pure_howto_stays_document(self):
        prior = (
            "you see the upcoming time is a festive one so suggest me the better items to stock on the werehouse",
        )
        active = {"focus": "festive_stocking", "question": prior[0]}
        self.assertEqual(
            classify_query(
                "this is completely fine but in the stocks items we have shall we make the combo things and give a bit discount for that",
                prior,
                active_advisory=active,
            )["classification"],
            "advisory",
        )
        self.assertEqual(
            classify_query("give me the suggestions which items can make the combo")["classification"],
            "advisory",
        )
        self.assertEqual(
            classify_query(
                "give me the suggestions which items can make the combo",
                prior + ("this is completely fine but in the stocks items we have shall we make the combo things and give a bit discount for that",),
                active_advisory={"focus": "combo_bundling", "question": "shall we make combo"},
            )["classification"],
            "advisory",
        )
        self.assertEqual(
            classify_query("how do I add a combo rule in price lists")["classification"],
            "document",
        )
        self.assertEqual(
            classify_query("can we add a discount on the amount")["classification"],
            "document",
        )
        self.assertEqual(
            classify_query("what is the seasonal things need to be restore")["classification"],
            "database",
        )
        combo_prior = prior + ("give me the suggestions which items can make the combo",)
        combo_active = {"focus": "combo_bundling", "question": combo_prior[-1]}
        for followup_q, expected_sub in (
            ("What is your target margin or discount ceiling for these bundles?", "margin_ceiling"),
            ("Would you prefer to create a pre-packed Combo SKU or roll out discounts via the POS/Price List?", "setup_method"),
            ("Keep discount capped at 8% via POS Price Lists", "confirmed_preferences"),
            ("give me the suggestions which items can make the combo", "items"),
        ):
            self.assertEqual(_combo_subfocus(followup_q), expected_sub)
            self.assertEqual(classify_query(followup_q, combo_prior, active_advisory=combo_active)["classification"], "advisory")
        self.assertEqual(
            classify_query("What is your target margin or discount ceiling for these bundles?")["classification"],
            "advisory",
        )
        self.assertEqual(
            classify_query("Would you prefer to create a pre-packed Combo SKU or roll out discounts via the POS/Price List?")["classification"],
            "advisory",
        )

    @patch("assistant.local_engine.client.chat.completions.create")
    def test_conceptual_feature_and_erp_terminology_queries_route_to_document(self, mock_llm):
        conceptual_queries = [
            "what is the meaning of pricing intel",
            "what does pricing intel mean",
            "meaning of pricing intel",
            "pricing intel meaning",
            "what is pricing intel",
            "explain pricing intel",
            "what is the meaning of boq",
            "what does karigar mean",
            "explain phantom bom",
            "what is 3-way matching",
            "what does grn mean",
            "what is reorder point",
            "what is the meaning of price elasticity",
            "what is the meaning of fifo",
        ]
        for q in conceptual_queries:
            with self.subTest(conceptual=q):
                cls = classify_query(q)
                self.assertEqual(cls["classification"], "document", msg=f"Got {cls} for {q!r}")
        for q in ("what is the reorder level for AN-QA-PART-A", "what is the reorder qty for Munchee 50g"):
            with self.subTest(record_lookup=q):
                cls = classify_query(q)
                self.assertEqual(cls["classification"], "database", msg=f"Got {cls} for {q!r}")
        mock_llm.assert_not_called()

    @patch("assistant.local_engine.client.chat.completions.create")
    def test_truly_out_of_scope_queries_are_restricted_while_erp_meaning_is_not(self, mock_llm):
        restricted_queries = [
            "what colour do you like",
            "tell me a joke",
            "what is the capital of France",
            "tell me about photosynthesis",
            "what is the weather forecast tomorrow",
            "write a python script for snake game",
            "write me a poem about sales",
        ]
        for q in restricted_queries:
            with self.subTest(out_of_scope=q):
                cls = classify_query(q)
                self.assertEqual(cls["classification"], "out_of_scope", msg=f"Got {cls} for {q!r}")
        mock_llm.assert_not_called()

    @override_settings(SUPPORT_DISABLE_MODEL_CALLS=False)
    @patch("assistant.local_engine.client.chat.completions.create")
    def test_llm_guard_prevents_false_out_of_scope_or_general_restriction_on_novel_erp_terms(self, mock_llm):
        def _fake_llm_reply(cls_name, reason="test"):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"classification": cls_name, "reason": reason})))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
            )

        # Novel ERP terminology falsely classified by LLM as out_of_scope -> rescued to document
        mock_llm.return_value = _fake_llm_reply("out_of_scope", "Unknown ERP feature")
        res_oos_guard = classify_query("what is the meaning of supplier scorecard analytics screen?")
        self.assertEqual(res_oos_guard["classification"], "document")

        # Novel ERP question falsely classified as general -> rescued to document
        mock_llm.return_value = _fake_llm_reply("general", "Conversational definition")
        res_gen_guard = classify_query("what does multi-currency ledger batching do?")
        self.assertEqual(res_gen_guard["classification"], "document")

        # Pure gratitude mentioning a business noun stays general (not hijacked)
        mock_llm.return_value = _fake_llm_reply("general", "User said thanks")
        res_thanks = classify_query("thank you for checking the stock report")
        self.assertEqual(res_thanks["classification"], "general")

        # Unfamiliar genuinely off-topic request stays restricted as out_of_scope
        mock_llm.return_value = _fake_llm_reply("out_of_scope", "Entertainment recommendation")
        res_real_oos = classify_query("recommend a good netflix thriller series tonight")
        self.assertEqual(res_real_oos["classification"], "out_of_scope")

    def test_general_answer_reply_never_falsely_triggers_out_of_scope_on_erp_questions(self):
        admin = {"tenant": "apptimate_test", "user_id": 1, "name": "QA Admin", "super_admin": True, "permissions": [], "organizations": None}

        # Bypass fast-path by calling general_answer_reply directly on conceptual & greeting-prefixed ERP queries
        for q in ("what is the meaning of pricing intel", "hi, what is the meaning of pricing intel?"):
            with self.subTest(question=q):
                engine = LocalAnswer("apptimate_test", admin, q)
                with patch.object(engine, "documentation_answer", side_effect=lambda *_: (engine.parts.append("Pricing Intel docs"), setattr(engine, "status", "answered"), True)[-1]) as doc_mock:
                    engine.general_answer_reply(q)
                doc_mock.assert_called_once()
                joined = "\n".join(engine.parts)
                self.assertIn("Pricing Intel docs", joined)
                self.assertNotIn("dedicated ERP support assistant", joined)

        # Pure greeting and gratitude still receive general replies cleanly
        greet_engine = LocalAnswer("apptimate_test", admin, "hello there")
        greet_engine.general_answer_reply("hello there")
        self.assertIn("Hello!", "\n".join(greet_engine.parts))

        thanks_engine = LocalAnswer("apptimate_test", admin, "thank you for the stock report")
        thanks_engine.general_answer_reply("thank you for the stock report")
        self.assertIn("You're welcome!", "\n".join(thanks_engine.parts))

        # True out-of-scope fallback stays restricted
        oos_engine = LocalAnswer("apptimate_test", admin, "what is the capital of France")
        oos_engine.general_answer_reply("what is the capital of France")
        self.assertEqual(oos_engine.status, "answered")
        self.assertIn("dedicated ERP support assistant", "\n".join(oos_engine.parts))

    @override_settings(SUPPORT_DISABLE_MODEL_CALLS=False)
    @patch("assistant.local_engine.client.chat.completions.create")
    def test_classifier_uses_dedicated_lightweight_classifier_model_only(self, mock_llm):
        self.assertEqual(CLASSIFIER_MODEL, "gpt-5.4-nano")
        mock_llm.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"classification": "document", "reason": "ERP concept"})))],
            usage=SimpleNamespace(prompt_tokens=15, completion_tokens=8),
        )
        res = classify_query("what does credit limit control mean?")
        self.assertEqual(res["classification"], "document")
        call_kwargs = mock_llm.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "gpt-5.4-nano")
        self.assertEqual(call_kwargs["reasoning_effort"], "none")
        self.assertEqual(call_kwargs["max_completion_tokens"], 180)

        gpt41_kwargs = _classifier_completion_kwargs("gpt-4.1-mini", [{"role": "user", "content": "hi"}])
        self.assertEqual(gpt41_kwargs["model"], "gpt-4.1-mini")
        self.assertNotIn("reasoning_effort", gpt41_kwargs)
        self.assertEqual(gpt41_kwargs["max_completion_tokens"], 180)

        gpt50_kwargs = _classifier_completion_kwargs("gpt-5-nano", [{"role": "user", "content": "hi"}])
        self.assertEqual(gpt50_kwargs["reasoning_effort"], "minimal")


