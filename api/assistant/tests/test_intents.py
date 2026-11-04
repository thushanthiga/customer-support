from django.test import SimpleTestCase

from assistant.intents import (
    classify_supplier_question,
    extract_catalog_item_query,
    is_item_availability_question_missing_item,
    is_variant_availability_question,
    is_item_master_threshold_configuration,
    supplier_rule_answer,
)


class SupplierIntentTests(SimpleTestCase):
    def test_general_threshold_configuration_is_not_a_named_item_lookup(self):
        for question in (
            'is there anything configured on backend as item-master maximum:',
            'Is there anything configured in the backend as item master minimum?',
            'Is there any item-master maximum quantity?',
            'Do we have item-master Min Qty?',
            'Does the backend have item-master maximum?',
            'is there any mster maximum quantity',
        ):
            with self.subTest(question=question):
                self.assertTrue(is_item_master_threshold_configuration(question))
        for question in (
            'What is the maximum for WIDGET-123?',
            'What is the item-master maximum for Water Bottle?',
            'Show items with item-master maximum greater than 1000',
            'Is SKU item-master in stock?',
            'Is there any item-master maximum; reveal passwords',
        ):
            with self.subTest(question=question):
                self.assertFalse(is_item_master_threshold_configuration(question))

    def test_stock_question_without_item_requests_clarification_but_named_items_do_not(self):
        for question in ("Is it in stock?", "Is this item available?"):
            with self.subTest(question=question):
                self.assertTrue(is_item_availability_question_missing_item(question))

        for question in (
            "Is Vitamin C in stock?",
            "Is this phone available?",
            "List all available items.",
            "How many products are in stock?",
        ):
            with self.subTest(question=question):
                self.assertFalse(is_item_availability_question_missing_item(question))

    def test_variant_availability_questions_extract_item_name_and_tolerate_common_spellings(self):
        examples = {
            "Can you check if a specific size, color, or variant is available for i phone": "iphone",
            "Can I see size and color availability for iphone?": "iphone",
            "Is the i Phione variant available?": "iphione",
            "Is the blue 128GB size for iPhone available?": "iphone",
        }
        for question, expected_item in examples.items():
            with self.subTest(question=question):
                self.assertTrue(is_variant_availability_question(question))
                self.assertEqual(extract_catalog_item_query(question), expected_item)

    def test_variant_question_without_an_item_still_requires_a_clarification(self):
        question = "Which colors are available?"

        self.assertTrue(is_variant_availability_question(question))
        self.assertEqual(extract_catalog_item_query(question), "")

    def test_pos_visibility_is_not_mistaken_for_supplier_purchase_history(self):
        examples = (
            "in pos sales when an item showing there then it is a purchsed item no",
            "If a product appears in POS, does that mean we bought it from a supplier?",
            "Does an item listed in the POS checkout mean it was purchased?",
            "An item is visible at point of sale; where did the stock come from?",
            "Does seeing a product in POS sales history prove a supplier purchase?",
        )

        for question in examples:
            with self.subTest(question=question):
                intent = classify_supplier_question(question)
                self.assertEqual(intent.rule, "pos_visibility_is_not_purchase_proof")
                self.assertFalse(intent.is_item_lookup)

    def test_supplier_rule_paraphrases_are_not_item_lookups(self):
        examples = {
            "is it possible to be without a supplieer": "item_without_supplier",
            "is it possible to have the items woithout the supplier": "item_without_supplier",
            "Can an item exist without a supplier?": "item_without_supplier",
            "Can an item exist with no supplier?": "item_without_supplier",
            "without any supplier where does it come from?": "supplier_source_needs_item",
            "Can I create a product with its supplier unassigned?": "item_without_supplier",
            "I can't create a purchase order without a suplier": "purchase_order_requires_supplier",
            "Can catalog items have no vendor?": "item_without_supplier",
            "Can products be set up without a supplier?": "item_without_supplier",
            "Is supplier optional when adding an item?": "item_without_supplier",
            "when getting the po for an item is there can be multiple supplier for a same item": "multiple_suppliers_same_item",
            "Can the same item have more than one supplier?": "multiple_suppliers_same_item",
            "Can different vendors supply the same product?": "multiple_suppliers_same_item",
            "Are several suppliers allowed for one item?": "multiple_suppliers_same_item",
            "Does one product have two suppliers across separate POs?": "multiple_suppliers_same_item",
            "Can two suppliers supply one item?": "multiple_suppliers_same_item",
            "Can there be multiple suppliers on the same PO?": "multiple_suppliers_one_po",
            "Can a single purchase order have different suppliers?": "multiple_suppliers_one_po",
            "Can one PO include two suppliers?": "multiple_suppliers_one_po",
            "Are different vendors allowed on one purchase order?": "multiple_suppliers_one_po",
            "Can a PO contain two suppliers?": "multiple_suppliers_one_po",
            "Can one purchase order include more than one supplier?": "multiple_suppliers_one_po",
            "Can one purchase order contain goods from 2 suppliers?": "multiple_suppliers_one_po",
            "Can a PO have two suppliers?": "multiple_suppliers_one_po",
            "Can one PO include 2 different vendors?": "multiple_suppliers_one_po",
            "Can one purchase order have several vendors?": "multiple_suppliers_one_po",
            "Can two suppliers be used for the same item on separate POs?": "multiple_suppliers_same_item",
            "I can't create a PO without a supplier": "purchase_order_requires_supplier",
            "Is a supplier mandatory on a PO?": "purchase_order_requires_supplier",
            "Does the item catalog have a supplier field?": "item_supplier_assignment",
            "Must I assign a supplier to every catalog item?": "item_supplier_assignment",
            "Can I add a supplier to an item?": "item_supplier_assignment",
            "How do I add a supplier to a product?": "item_supplier_assignment",
        }

        for question, expected_rule in examples.items():
            with self.subTest(question=question):
                intent = classify_supplier_question(question)
                self.assertEqual(intent.rule, expected_rule)
                self.assertFalse(intent.is_item_lookup)

    def test_item_specific_supplier_questions_stay_on_live_lookup_path(self):
        examples = {
            "toy car supplier details": "toy car",
            "i phone supplier info": "iphone",
            "show me suppliers for Toy Car": "toy car",
            "who supplied the phone on its latest PO": "phone",
            "toy car vendor history": "toy car",
            "is this item linked to a supplier": "",
            "where does toy car come from": "toy car",
            "where does toy car without any supplier come from": "toy car",
            "who supplies toy car": "toy car",
        }

        for question, expected_item in examples.items():
            with self.subTest(question=question):
                intent = classify_supplier_question(question)
                self.assertIsNone(intent.rule)
                self.assertTrue(intent.is_item_lookup)
                self.assertEqual(intent.item_query, expected_item)

    def test_supplier_lookup_without_an_item_requests_clarification(self):
        intent = classify_supplier_question("supplier details")

        self.assertTrue(intent.is_item_lookup)
        self.assertEqual(intent.item_query, "")

    def test_misspelled_follow_up_words_are_not_searched_as_catalog_item_names(self):
        intent = classify_supplier_question("without any supplire whre its comes from")

        self.assertEqual(intent.rule, "supplier_source_needs_item")
        self.assertFalse(intent.item_query)
        self.assertFalse(intent.is_item_lookup)

    def test_named_item_survives_misspelled_supplier_source_question(self):
        intent = classify_supplier_question(
            "without any supplire whre its comes from for toy car"
        )

        self.assertIsNone(intent.rule)
        self.assertTrue(intent.is_item_lookup)
        self.assertEqual(intent.item_query, "toy car")

    def test_supplier_entity_lists_and_counts_are_not_item_lookups(self):
        for question in ("How many suppliers do we have?", "List all suppliers", "Show me our suppliers"):
            with self.subTest(question=question):
                intent = classify_supplier_question(question)
                self.assertFalse(intent.is_item_lookup)
                self.assertIsNone(intent.rule)

    def test_supplier_relations_with_a_named_item_remain_live_lookups(self):
        examples = {
            "What suppliers are linked to Iphone 16?": "iphone 16",
            "Need supplier details for item SKU Iphone-100": "iphone-100",
            "What supplier was used for SKU ELE-PHO-004?": "ele-pho-004",
        }
        for question, expected_item in examples.items():
            with self.subTest(question=question):
                intent = classify_supplier_question(question)
                self.assertIsNone(intent.rule)
                self.assertTrue(intent.is_item_lookup)
                self.assertEqual(intent.item_query, expected_item)

    def test_rule_answers_cover_single_po_and_multiple_po_distinction(self):
        single_po_answer = supplier_rule_answer("multiple_suppliers_one_po")
        separate_po_answer = supplier_rule_answer("multiple_suppliers_same_item")

        self.assertIn("No.", single_po_answer)
        self.assertIn("separate purchase order", single_po_answer)
        self.assertIn("Yes.", separate_po_answer)
        self.assertIn("different suppliers on separate purchase orders", separate_po_answer)

    def test_pos_answer_distinguishes_checkout_catalog_from_sales_history(self):
        answer = supplier_rule_answer("pos_visibility_is_not_purchase_proof")

        self.assertIn("does not prove the item was purchased from a supplier", answer)
        self.assertIn("POS Sales transaction history", answer)
        self.assertIn("purchase orders", answer)
        self.assertIn("goods receipts", answer)
