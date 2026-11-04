from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from assistant.rag_service import retrieve_relevant_chunks


class RagGroundingTests(SimpleTestCase):
    @patch("assistant.rag_service.get_query_embedding", return_value=[1.0, 0.0])
    @patch("assistant.rag_service.DocumentChunk.objects.filter")
    @patch("assistant.rag_service.UploadedDocument.objects.filter")
    def test_unrelated_chunk_is_not_injected_as_fallback(
        self, active_filter, chunk_filter, _embedding
    ):
        document = SimpleNamespace(id=1, title="Support guide")
        active_filter.return_value.first.return_value = document
        chunk = SimpleNamespace(
            id=7,
            section_title="Unrelated",
            section_hierarchy=["Unrelated"],
            content="A section unrelated to the query.",
            get_embedding=lambda: [0.0, 1.0],
        )
        chunk_filter.return_value = [chunk]

        context, references = retrieve_relevant_chunks("supplier source", min_similarity=0.9)

        self.assertEqual(context, "")
        self.assertEqual(references, [])

    @patch("assistant.rag_service.UploadedDocument.objects.first")
    @patch("assistant.rag_service.UploadedDocument.objects.filter")
    def test_inactive_document_is_not_used_as_implicit_fallback(self, active_filter, latest_document):
        active_filter.return_value.first.return_value = None

        context, references = retrieve_relevant_chunks("how do I create a PO")

        self.assertEqual(context, "")
        self.assertEqual(references, [])
        latest_document.assert_not_called()
