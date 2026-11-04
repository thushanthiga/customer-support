from django.test import TestCase

from assistant.models import DocumentChunk, UploadedDocument
from assistant.rag_service import format_verified_navigation_answer, retrieve_navigation_chunks


class NavigationRetrievalTests(TestCase):
    def setUp(self):
        self.document = UploadedDocument.objects.create(
            title="Product help",
            original_filename="help.md",
            file_path="/tmp/help.md",
            is_active=True,
        )

    def add_chunk(self, index, title, content, hierarchy=None):
        return DocumentChunk.objects.create(
            document=self.document,
            chunk_index=index,
            section_title=title,
            section_hierarchy=hierarchy or [],
            content=content,
        )

    def test_terminal_navigation_finds_route_evidence_and_omits_keyword_only_chunks(self):
        terminal_route = self.add_chunk(
            1,
            "Terminal navigation",
            "Terminals: Sidebar ➔ Core ➔ Resources ➔ Terminals. "
            "Terminal Sessions: Sidebar ➔ Sales ➔ POS ➔ Terminal Sessions.",
            ["POS", "Navigation"],
        )
        self.add_chunk(
            2,
            "Terminal error troubleshooting",
            "If a terminal has an error, refresh the page and retry.",
            ["Support", "Troubleshooting"],
        )

        context, references = retrieve_navigation_chunks("how can i see the terminal")

        self.assertIn("Sidebar ➔ Core ➔ Resources ➔ Terminals", context)
        self.assertIn("Sidebar ➔ Sales ➔ POS ➔ Terminal Sessions", context)
        self.assertEqual([reference["chunk_id"] for reference in references], [terminal_route.id])
        self.assertEqual(references[0]["match_type"], "navigation_terms_and_route")

    def test_common_warehouse_misspelling_matches_only_warehouse_route(self):
        warehouse_route = self.add_chunk(
            1,
            "Warehouses",
            "Access Flow: Sidebar ➔ Core ➔ Resources ➔ Warehouses.",
        )
        self.add_chunk(
            2,
            "Terminals",
            "Access Flow: Sidebar ➔ Core ➔ Resources ➔ Terminals.",
        )

        context, references = retrieve_navigation_chunks("how can i see wherehouse")

        self.assertIn("Resources ➔ Warehouses", context)
        self.assertNotIn("Resources ➔ Terminals", context)
        self.assertEqual([reference["chunk_id"] for reference in references], [warehouse_route.id])

    def test_a_shared_keyword_does_not_match_a_different_screen_concept(self):
        self.add_chunk(
            1,
            "Terminals",
            "Access Flow: Sidebar ➔ Core ➔ Resources ➔ Terminals.",
        )

        context, references = retrieve_navigation_chunks("where can I see supplier terminals")

        self.assertEqual(context, "")
        self.assertEqual(references, [])

    def test_erp_abbreviations_expand_to_documented_screen_names(self):
        purchase_orders = self.add_chunk(
            1,
            "Purchase Orders",
            "Access Flow: Sidebar ➔ Procurement ➔ Orders ➔ Purchase Orders.",
        )
        goods_receipt = self.add_chunk(
            2,
            "Goods Receipt",
            "Access Flow: Sidebar ➔ Procurement ➔ Receiving ➔ Goods Receipt.",
        )

        po_context, po_references = retrieve_navigation_chunks("where is PO")
        grn_context, grn_references = retrieve_navigation_chunks("where can I open GRN")

        self.assertIn("Purchase Orders", po_context)
        self.assertEqual([reference["chunk_id"] for reference in po_references], [purchase_orders.id])
        self.assertIn("Goods Receipt", grn_context)
        self.assertEqual([reference["chunk_id"] for reference in grn_references], [goods_receipt.id])

    def test_one_character_typo_matches_the_intended_route(self):
        invoice_route = self.add_chunk(
            1,
            "Sales Invoices",
            "Access Flow: Sidebar ➔ Sales ➔ Post-Sales ➔ Sales Invoices.",
        )

        context, references = retrieve_navigation_chunks("where is invioce")

        self.assertIn("Sales Invoices", context)
        self.assertEqual([reference["chunk_id"] for reference in references], [invoice_route.id])

    def test_explicit_module_ranks_before_incidental_screen_keywords(self):
        for index,name in enumerate(['Sales Orders','Sales Returns','Sales Invoices','POS Sales','Sales Reports']):
            self.add_chunk(index,'Default navigation: Sales / '+name,
                f'Access Flow: Sidebar ➔ Sales ➔ Transactions ➔ {name}.')
        for index in range(5,11):
            self.add_chunk(index,'Default navigation: CRM / Sales '+str(index),
                f'Access Flow: Sidebar ➔ CRM ➔ Spaces ➔ Sales {index}.')
        context,refs=retrieve_navigation_chunks('where is the sales')
        self.assertEqual(len(refs),5)
        self.assertNotIn('Sidebar ➔ CRM',context)
        self.assertIn('POS Sales',context)

    def test_verified_sidebar_path_is_formatted_without_model_generated_menu_names(self):
        answer = format_verified_navigation_answer(
            "Open `Sidebar` ➔ `Core` ➔ `Resources` ➔ `Warehouses` (`/warehouses`)."
        )

        self.assertEqual(
            answer,
            "You can find **Warehouses** at **Sidebar ➔ Core ➔ Resources ➔ Warehouses**.",
        )

    def test_ambiguous_matching_paths_are_shown_as_choices(self):
        answer = format_verified_navigation_answer(
            "Sales: Sidebar ➔ Sales ➔ Post-Sales ➔ Sales Invoices. "
            "Finance: Sidebar ➔ Finance ➔ Transactions ➔ Invoices."
        )

        self.assertIn("**Sales Invoices** — **Sidebar ➔ Sales ➔ Post-Sales ➔ Sales Invoices**", answer)
        self.assertIn("**Invoices** — **Sidebar ➔ Finance ➔ Transactions ➔ Invoices**", answer)
        self.assertIn("Which one are you looking for?", answer)

    def test_unverified_navigation_text_is_not_converted_to_a_path(self):
        self.assertIsNone(format_verified_navigation_answer("Terminals are under Core resources."))

    def test_contextual_crm_leads_menu_is_included_in_reference(self):
        from pathlib import Path
        from assistant.navigation_reference import read_contextual_menus, navigation_sections
        repository = Path(__file__).resolve().parents[4]
        entries = read_contextual_menus(repository)
        leads = next(entry for entry in entries if entry['key'] == 'crm-space-leads')
        self.assertEqual(leads['route'], '/crm/spaces/{spaceId}/leads')
        section = navigation_sections([leads])[0]
        self.add_chunk(90, section['title'], section['content'], section['hierarchy'])
        context, refs = retrieve_navigation_chunks('Where can I view leads?')
        self.assertIn('CRM ➔ Spaces ➔ select a space ➔ Leads', context)
        self.assertTrue(refs)
