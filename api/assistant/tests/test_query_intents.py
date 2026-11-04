from django.test import SimpleTestCase

from assistant.intents import is_below_minimum_stock_question, is_variant_availability_question
from assistant.query_service import (
    is_likely_live_data_question,
    is_purchase_order_diagnostic_question,
    is_warehouse_branch_management_question,
    is_warehouse_location_count_question,
    is_warehouse_location_list_question,
    is_warehouse_navigation_question,
    is_ui_navigation_question,
    _relevant_tables,
)


class LiveDataIntentTests(SimpleTestCase):
    def test_background_offer_request_discovers_rule_and_activation_schema(self):
        schema={'tables':{
            'inventory_items':{'id':'int','is_discountable':'tinyint'},
            'sales_price_rules':{'id':'int','min_quantity':'decimal','markdown_percentage':'decimal'},
            'sales_price_lists':{'id':'int','is_active':'tinyint','end_date':'datetime'},
            'inventory_stock_balances':{'id':'int','qty_available':'decimal'}},'relationships':set()}
        context=_relevant_tables(schema,'Why is an offer blocked? Check background restrictions.',limit=1)
        for name in ('inventory_items','sales_price_rules','sales_price_lists'):
            self.assertIn('- '+name+':',context)
        self.assertIn('no minimum purchase-amount condition',context)
        self.assertIn('leaves the manual discount percentage/amount at zero',context)

    def test_generic_item_schema_includes_general_master_for_unseen_product_names(self):
        schema={'tables':{'jewelry_items':{'id':'int','name':'text'},
            'inventory_items':{'id':'int','sku':'text','name':'text'},
            'configuration_items':{'id':'int','name':'text','items':'text'}},'relationships':set()}
        context=_relevant_tables(schema,'Which products named UnseenProduct exist?',limit=1)
        self.assertIn('- inventory_items:',context)
        context=_relevant_tables(schema,'Which jewelry items are available?',limit=3)
        self.assertIn('- jewelry_items:',context)

    def test_below_minimum_stock_paraphrases_use_the_specialized_report(self):
        questions = [
            "list down all the items with stock quantity lesser than their item master minimum quantity",
            "which products have available stock below the minimum stock level",
            "show items under their min qty",
        ]
        for question in questions:
            with self.subTest(question=question):
                self.assertTrue(is_below_minimum_stock_question(question))

    def test_minimum_stock_setup_questions_are_not_report_queries(self):
        self.assertFalse(is_below_minimum_stock_question("How do I set the item master minimum quantity?"))
        self.assertFalse(is_below_minimum_stock_question("list items with stock lower than the reorder point"))

    def test_item_master_minimum_definitions_are_not_live_record_queries(self):
        questions = [
            "what is item master minimum",
            "What is the item master minimum quantity?",
            "What does the item-master minimum quantity mean?",
            "What is the item-master minimum quantity?",
            "What does the minimum stock level mean?",
            "Define minimum stock level.",
            "What is a purchase order?",
            "What does a goods receipt mean?",
        ]
        for question in questions:
            with self.subTest(question=question):
                self.assertFalse(is_likely_live_data_question(question))

    def test_item_specific_minimum_value_questions_still_use_live_data(self):
        questions = [
            "What is the item master minimum for Toy Car?",
            "What is the minimum stock level for SKU TC-100?",
            "Show Toy Car's minimum quantity.",
            "What is the status of PO-2026-00015?",
        ]
        for question in questions:
            with self.subTest(question=question):
                self.assertTrue(is_likely_live_data_question(question))

    def test_natural_record_questions_route_to_live_data(self):
        questions = [
            "Does customer Mary have overdue invoices?",
            "Is Toy Car available now?",
            "Do we have any open purchase orders?",
            "Did supplier ABC receive payment?",
            "Can I check stock for the phone?",
        ]

        for question in questions:
            with self.subTest(question=question):
                self.assertTrue(is_likely_live_data_question(question))

    def test_variant_availability_requests_use_live_data_even_when_the_item_is_misspelled(self):
        questions = [
            "Can you check if a specific size, color, or variant is available for i phone",
            "Is the i Phione variant available?",
            "Do we have the blue iPhone color variant in stock?",
        ]
        for question in questions:
            with self.subTest(question=question):
                self.assertTrue(is_variant_availability_question(question))
                self.assertTrue(is_likely_live_data_question(question))

    def test_workflow_how_to_questions_stay_out_of_live_data_queries(self):
        questions = [
            "How do I add a new item?",
            "Can I create a purchase order?",
            "How do I receive the goods against a purchase order?",
            "Why can't I add a customer?",
        ]

        for question in questions:
            with self.subTest(question=question):
                self.assertFalse(is_likely_live_data_question(question))

    def test_purchase_order_diagnostics_require_a_blocker_or_specific_record(self):
        self.assertFalse(is_purchase_order_diagnostic_question(
            "How do I receive the goods against a purchase order?"
        ))
        self.assertFalse(is_purchase_order_diagnostic_question("Can I create a purchase order?"))
        self.assertTrue(is_purchase_order_diagnostic_question(
            "Why can't I create a purchase order for Toy Car?"
        ))
        self.assertTrue(is_purchase_order_diagnostic_question(
            "What is the status of PO-2026-00015, and has it been received?"
        ))
        self.assertTrue(is_purchase_order_diagnostic_question(
            "why i am not able to purchase vitamin c"
        ))

    def test_screen_and_feature_explanations_use_documentation_not_live_records(self):
        questions = [
            "What does the POS Sales page show?",
            "What is the POS checkout screen for?",
            "What does the Sales feature do?",
        ]

        for question in questions:
            with self.subTest(question=question):
                self.assertFalse(is_likely_live_data_question(question))

    def test_pos_transaction_record_requests_still_use_live_data(self):
        self.assertTrue(is_likely_live_data_question("Show all POS sales for today"))

    def test_live_counts_remain_live_data_when_user_mentions_a_page(self):
        self.assertTrue(is_likely_live_data_question("How many items are on the inventory page?"))

    def test_store_and_location_lists_use_the_tenant_location_report(self):
        questions = [
            "list down the stores and locations",
            "show all stores",
            "what are the showroom locations?",
        ]
        for question in questions:
            with self.subTest(question=question):
                self.assertTrue(is_warehouse_location_list_question(question))
                self.assertTrue(is_likely_live_data_question(question))

    def test_location_count_question_is_not_misclassified_as_a_request_to_list_rows(self):
        for question in (
            "How many warehouses do we have?",
            "Count the active store locations",
            "What is the total number of branches?",
            "How many warehouses have stock?",
        ):
            with self.subTest(question=question):
                self.assertTrue(is_warehouse_location_count_question(question))
                self.assertFalse(is_warehouse_location_list_question(question))
                self.assertTrue(is_likely_live_data_question(question))

    def test_warehouse_and_branch_management_questions_are_guidance_not_location_lists(self):
        questions = [
            "Where do I manage warehouses and branches?",
            "How do I add a warehouse?",
            "Where can I update a store location?",
            "Where do I configure branches?",
            "Where can I manage a branch?",
        ]
        for question in questions:
            with self.subTest(question=question):
                self.assertTrue(is_warehouse_branch_management_question(question))
                self.assertFalse(is_warehouse_location_list_question(question))
                self.assertFalse(is_likely_live_data_question(question))

    def test_warehouse_page_navigation_is_distinct_from_data_and_management_queries(self):
        for question in (
            "How can I see warehouse?",
            "how can i see wherehouse",
            "Where can I view warehouses?",
            "Where do I open the warehouse screen?",
        ):
            with self.subTest(question=question):
                self.assertTrue(is_warehouse_navigation_question(question))

        for question in (
            "How many warehouses do we have?",
            "List all warehouses",
            "Which warehouse has Toy Car?",
            "How do I create a warehouse?",
        ):
            with self.subTest(question=question):
                self.assertFalse(is_warehouse_navigation_question(question))

    def test_ui_navigation_intent_is_generic_and_excludes_live_value_questions(self):
        for question in (
            "how can i see the terminal",
            "where do I open sales reports?",
            "where can I access the customer screen?",
            "how do I find purchase orders?",
            "where is invoice",
            "where can I see supplier details",
            "where is PO",
            "where to see GRN",
            "Where to see the goods receipt?",
            "Where do we manage supplier records?",
        ):
            with self.subTest(question=question):
                self.assertTrue(is_ui_navigation_question(question))

        for question in (
            "How many active terminals do we have?",
            "Where can I see if iPhone is in stock?",
            "Where can I see supplier details for Toy Car?",
            "Where can I see current invoices?",
            "Where can I see stock for the phone?",
            "List all warehouses",
        ):
            with self.subTest(question=question):
                self.assertFalse(is_ui_navigation_question(question))

        self.assertFalse(is_likely_live_data_question("where is invoice"))
        self.assertTrue(is_likely_live_data_question("What is the status of invoice INV-2026-15?"))
        self.assertTrue(is_likely_live_data_question("Where can I see current invoices?"))
        self.assertTrue(is_likely_live_data_question("Where can I see stock for the phone?"))
        self.assertFalse(is_likely_live_data_question("Where can I see supplier details?"))
        self.assertTrue(is_likely_live_data_question("Where can I see supplier details for Toy Car?"))
        self.assertFalse(is_likely_live_data_question("Where do we manage supplier records?"))

    def test_declarative_navigation_matches_shared_context_classification(self):
        from assistant.request_context import is_navigation_request,navigation_subject
        for question,subject in [
            ('I need to find sales','sales'),
            ('I want to open POS sales','POS sales'),
            ('We would like to access payroll','payroll'),
            ('I am trying to locate purchase orders','purchase orders'),
            ('I am looking for inventory items','inventory items'),
            ('Please help me find the sales screen','sales'),
            ('Can you help me to find POS sales?','POS sales'),
            ('Could you open the invoice screen?','invoice'),
            ('Take me to sales reports','sales reports'),
            ('Navigate to payroll','payroll'),
            ('Open price lists','price lists'),
            ('I need to find price rules','price rules'),
            ('Where can I find the price lists page?','price lists'),
        ]:
            with self.subTest(question=question):
                self.assertTrue(is_ui_navigation_question(question))
                self.assertTrue(is_navigation_request(question))
                self.assertFalse(is_likely_live_data_question(question))
                self.assertEqual(navigation_subject(question),subject)

    def test_navigation_verbs_do_not_erase_business_data_scope(self):
        from assistant.request_context import is_navigation_request
        for question in [
            'I need to find POS sales under 50',
            'I need to find sales above 1000',
            'I want to see sales today',
            'I need to find sales from August',
            'I want to find sales for yesterday',
            'I need to find sales this month',
            'Help me find unpaid invoices',
            'I need to find invoice INV-123',
            'I want to find stock for the phone',
            'I need to see the total sales',
            'I need to find sales and show totals',
            'I need to find customer purchase history',
            'Where can I see current invoices?',
            'How many completed POS sales do we have?',
        ]:
            with self.subTest(question=question):
                self.assertFalse(is_ui_navigation_question(question))
                self.assertFalse(is_navigation_request(question))

    def test_creation_location_is_not_an_execution_or_full_workflow_request(self):
        from assistant.request_context import navigation_subject,navigation_location_action
        from assistant.rag_service import navigation_needs_workflow
        for question,subject in [
            ('place where we can create sales','sales'),
            ('Where can I create purchase orders?','purchase orders'),
            ('the screen where I can add items','items'),
            ('place to record expenses','expenses'),
            ('I need a place to create sales','sales'),
            ('Show me where we can create sales','sales'),
        ]:
            with self.subTest(question=question):
                self.assertTrue(is_ui_navigation_question(question))
                self.assertEqual(navigation_subject(question),subject)
                self.assertIsNotNone(navigation_location_action(question))
                self.assertFalse(navigation_needs_workflow(question))
                self.assertFalse(is_likely_live_data_question(question))
        self.assertTrue(navigation_needs_workflow('How do I create a sales order?'))
        self.assertIsNone(navigation_location_action('Create a sales order for me now'))
        self.assertFalse(is_ui_navigation_question('Where can I create sales above 1000?'))

    def test_store_inventory_detail_is_not_misrouted_to_location_list(self):
        questions = [
            "list the items and stock in each store",
            "Is Vitamin C in stock, and which warehouse has it?",
            "Which warehouse has SKU MED-COT-01 in stock?",
        ]
        for question in questions:
            with self.subTest(question=question):
                self.assertFalse(is_warehouse_location_list_question(question))
                self.assertTrue(is_likely_live_data_question(question))

    def test_goods_issue_counts_use_live_data_even_though_issue_is_a_support_keyword(self):
        self.assertTrue(is_likely_live_data_question('How many sales goods issue note lines reference inventory serial numbers?'))
