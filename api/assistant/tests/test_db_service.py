from django.test import SimpleTestCase

from assistant.db_service import _resolve_items_fuzzy


class FuzzyCatalogMatchingTests(SimpleTestCase):
    def test_typo_in_iphone_resolves_to_catalog_candidate(self):
        iphone_item = {
            "id": 7,
            "sku": "IPH-16",
            "name": "iPhone 16",
            "status": "active",
            "has_variants": True,
            "is_available_sell": True,
            "is_discountable": True,
            "tracking_type": "none",
            "has_stocks": True,
        }
        phone_item = {
            **iphone_item,
            "id": 8,
            "sku": "ELE-PHO-004",
            "name": "phone",
            "has_variants": False,
        }

        class Cursor:
            def __init__(self):
                self.rows = []

            def execute(self, query, params=None):
                if "NOT LIKE 'LD-%'" in query:
                    self.rows = [iphone_item.copy(), phone_item.copy()]
                else:
                    self.rows = []

            def fetchall(self):
                return self.rows

        matched = _resolve_items_fuzzy(Cursor(), "iphione")

        self.assertEqual([item["id"] for item in matched], [7])
        self.assertGreaterEqual(matched[0]["_match_score"], 0.78)

    def test_multiword_lookup_does_not_match_on_only_one_keyword(self):
        iphone_item = {
            "id": 7,
            "sku": "IPH-16",
            "name": "iPhone 16",
            "status": "active",
            "has_variants": True,
            "is_available_sell": True,
            "is_discountable": True,
            "tracking_type": "none",
            "has_stocks": True,
        }

        class Cursor:
            def __init__(self):
                self.rows = []

            def execute(self, query, params=None):
                if "NOT LIKE 'LD-%'" in query:
                    self.rows = [iphone_item.copy()]
                else:
                    self.rows = []

            def fetchall(self):
                return self.rows

        matched = _resolve_items_fuzzy(Cursor(), "iphone unrelatedword")

        self.assertEqual(matched, [])

    def test_plural_watch_query_matches_singular_catalog_name(self):
        watch_item = {
            "id": 42,
            "sku": "WATCH-01",
            "name": "Watch",
            "status": "active",
            "has_variants": False,
            "is_available_sell": True,
            "is_discountable": True,
            "tracking_type": "none",
            "has_stocks": True,
        }

        class Cursor:
            def __init__(self):
                self.rows = []
                self.queries = []

            def execute(self, query, params=None):
                self.queries.append((query, params))
                if "name LIKE %s OR sku LIKE %s" in query and params[1] == "%watch%":
                    self.rows = [watch_item.copy()]
                else:
                    self.rows = []

            def fetchall(self):
                return self.rows

        cursor = Cursor()
        matched = _resolve_items_fuzzy(cursor, "watches")

        self.assertEqual([item["id"] for item in matched], [42])
        self.assertEqual(matched[0]["_match_score"], 1.0)
        self.assertTrue(any("%watches%" in params for _query, params in cursor.queries))
        self.assertTrue(any("%watch%" in params for _query, params in cursor.queries))

    def test_load_test_item_is_excluded_even_when_its_name_contains_watch(self):
        load_test_watch = {
            "id": 3894,
            "sku": "LD-3894-8M1B4S",
            "name": "Load Test Item 3894 JWaTCH",
            "status": "active",
            "has_variants": True,
            "is_available_sell": True,
            "is_discountable": True,
            "tracking_type": "none",
            "has_stocks": True,
        }

        class Cursor:
            def __init__(self):
                self.rows = []
                self.queries = []

            def execute(self, query, params=None):
                self.queries.append((query, params))
                if "name LIKE %s OR sku LIKE %s" in query:
                    self.rows = []
                elif "LOWER(name) LIKE %s OR LOWER(sku) LIKE %s" in query:
                    self.rows = []
                elif "NOT LIKE 'LD-%'" in query:
                    self.rows = []
                else:
                    self.rows = [load_test_watch.copy()]

            def fetchall(self):
                return self.rows

        cursor = Cursor()
        matched = _resolve_items_fuzzy(cursor, "watches display")

        self.assertEqual(matched, [])
        for query, params in cursor.queries:
            if "FROM inventory_items" in query:
                self.assertRegex(query, r"COALESCE\(sku, ''\) NOT LIKE (?:%s|'LD-%')")
                self.assertNotIn("OR id < 100", query)
            if "name LIKE %s OR sku LIKE %s" in query:
                self.assertEqual(params[0], "LD-%")

    def test_short_watch_query_does_not_suggest_unrelated_batch_products(self):
        class Cursor:
            def execute(self, query, params=None):
                self.rows = ([{'id': 12, 'sku': 'BATCH-100', 'name': 'A-batch'}]
                    if "NOT LIKE 'LD-%'" in query else [])
            def fetchall(self):
                return self.rows
        self.assertEqual(_resolve_items_fuzzy(Cursor(), 'watches'), [])
