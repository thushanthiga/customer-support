from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from assistant.models import DocumentChunk, UploadedDocument
from assistant.navigation_reference import MARKER, PREFIX, navigation_sections, read_menu_registry, read_contextual_menus, render_reference


class Command(BaseCommand):
    help = "Sync verified default menu destinations into the managed platform knowledge document and its navigation index."

    def add_arguments(self, parser):
        parser.add_argument("--document-id", type=int)

    def handle(self, *args, **options):
        document = (UploadedDocument.objects.filter(id=options["document_id"]).first()
                    if options["document_id"] else UploadedDocument.objects.filter(is_active=True).first())
        if not document:
            raise CommandError("No knowledge document selected.")
        source = Path(document.file_path)
        if not options["document_id"] and source.name != "apptimate_one_deep_knowledge.md":
            raise CommandError("The active document is not the managed platform guide; select a document explicitly.")
        repository = Path(__file__).resolve().parents[5]
        entries = read_menu_registry(repository / "packages/core-lib/src/constants/menus.ts")
        entries.extend(read_contextual_menus(repository))
        reference = render_reference(entries)
        contents = source.read_text().split(MARKER)[0].rstrip() + "\n\n" + reference
        with transaction.atomic():
            # Existing feature chunks and their IDs stay intact for old chat references.
            DocumentChunk.objects.filter(document=document, section_title__startswith=PREFIX).delete()
            index = (DocumentChunk.objects.filter(document=document).aggregate(value=Max("chunk_index"))["value"] or 0) + 1
            DocumentChunk.objects.bulk_create([
                DocumentChunk(document=document, chunk_index=index + offset, section_title=section["title"],
                    section_hierarchy=section["hierarchy"], content=section["content"], token_count=len(section["content"].split()))
                for offset, section in enumerate(navigation_sections(entries))
            ])
            source.write_text(contents)
            document.total_chunks = DocumentChunk.objects.filter(document=document).count()
            document.file_size = source.stat().st_size
            document.indexed_at = timezone.now()
            document.save(update_fields=["total_chunks", "file_size", "indexed_at"])
        self.stdout.write(f"Synced {len(entries)} documented default destinations; navigation retrieval requires no embeddings.")
