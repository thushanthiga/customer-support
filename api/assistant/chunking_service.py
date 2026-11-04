import os
import re
import json
import logging
from typing import List, Dict, Any
from openai import OpenAI
from django.utils import timezone
from .models import UploadedDocument, DocumentChunk

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

client = OpenAI(api_key=OPENAI_API_KEY)

def split_markdown_into_sections(md_text: str) -> List[Dict[str, Any]]:
    """
    Parses Markdown text into structured hierarchical sections based on headings (#, ##, ###, etc.)
    Preserves parent breadcrumbs and prevents orphaned chunks.
    """
    lines = md_text.splitlines()
    sections = []
    
    current_headings = {}  # {level: title}
    current_content = []
    current_title = "Document Overview"
    
    heading_regex = re.compile(r"^(#{1,6})\s+(.+)$")
    
    for line in lines:
        match = heading_regex.match(line)
        if match:
            # Save accumulated content for the previous section if exists
            content_str = "\n".join(current_content).strip()
            if content_str:
                breadcrumb = [current_headings[k] for k in sorted(current_headings.keys()) if k in current_headings]
                sections.append({
                    "title": current_title,
                    "hierarchy": list(breadcrumb),
                    "content": content_str
                })
                current_content = []
            
            level = len(match.group(1))
            title = match.group(2).strip()
            
            # Update active headings map: remove any lower or equal level headings
            current_headings = {k: v for k, v in current_headings.items() if k < level}
            current_headings[level] = title
            current_title = title
        else:
            current_content.append(line)
            
    # Add final trailing section
    final_content = "\n".join(current_content).strip()
    if final_content:
        breadcrumb = [current_headings[k] for k in sorted(current_headings.keys()) if k in current_headings]
        sections.append({
            "title": current_title,
            "hierarchy": list(breadcrumb),
            "content": final_content
        })
        
    return sections

def chunk_sections(sections: List[Dict[str, Any]], max_chunk_words: int = 500) -> List[Dict[str, Any]]:
    """
    Takes hierarchical sections and subdivides oversized sections by paragraph boundaries
    while attaching context breadcrumbs to every chunk.
    """
    final_chunks = []
    
    for sec in sections:
        title = sec["title"]
        hierarchy = sec["hierarchy"]
        content = sec["content"]
        
        words = content.split()
        if len(words) <= max_chunk_words:
            breadcrumb_header = f"[{ ' > '.join(hierarchy) if hierarchy else title }]\n"
            final_chunks.append({
                "section_title": title,
                "section_hierarchy": hierarchy,
                "content": f"{breadcrumb_header}{content}"
            })
        else:
            # Split section by paragraphs
            paragraphs = re.split(r'\n\s*\n', content)
            buffer = []
            buffer_words = 0
            
            for p in paragraphs:
                p = p.strip()
                if not p:
                    continue
                p_word_count = len(p.split())
                
                if buffer_words + p_word_count > max_chunk_words and buffer:
                    chunk_text = "\n\n".join(buffer)
                    breadcrumb_header = f"[{ ' > '.join(hierarchy) if hierarchy else title }]\n"
                    final_chunks.append({
                        "section_title": title,
                        "section_hierarchy": hierarchy,
                        "content": f"{breadcrumb_header}{chunk_text}"
                    })
                    buffer = [p]
                    buffer_words = p_word_count
                else:
                    buffer.append(p)
                    buffer_words += p_word_count
                    
            if buffer:
                chunk_text = "\n\n".join(buffer)
                breadcrumb_header = f"[{ ' > '.join(hierarchy) if hierarchy else title }]\n"
                final_chunks.append({
                    "section_title": title,
                    "section_hierarchy": hierarchy,
                    "content": f"{breadcrumb_header}{chunk_text}"
                })
                
    return final_chunks

def generate_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Generates embeddings using OpenAI text-embedding-3-small in batches."""
    if not texts:
        return []
    from django.conf import settings
    if settings.SUPPORT_DISABLE_MODEL_CALLS:
        # Verification runs keep chunks available for lexical retrieval.
        return [[] for _ in texts]
    
    all_embeddings = []
    batch_size = 64
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        # Clean newlines and nulls for embedding model
        cleaned_batch = [t.replace("\x00", "").strip() for t in batch]
        try:
            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=cleaned_batch
            )
            for data_item in response.data:
                all_embeddings.append(data_item.embedding)
        except Exception as e:
            logger.warning(f"Embedding batch failed, storing chunks for lexical fallback: {e}")
            all_embeddings.extend([[] for _ in batch])
            
    return all_embeddings

def process_and_index_document(document: UploadedDocument) -> int:
    """
    Reads the uploaded markdown file, runs hierarchical chunking, generates embeddings,
    and stores indexed chunks in the database.
    """
    if not os.path.exists(document.file_path):
        raise FileNotFoundError(f"Document file not found at: {document.file_path}")
        
    with open(document.file_path, 'r', encoding='utf-8') as f:
        md_text = f.read()
        
    sections = split_markdown_into_sections(md_text)
    raw_chunks = chunk_sections(sections)
    
    if not raw_chunks:
        logger.warning(f"No chunks generated for document: {document.title}")
        return 0
        
    # Remove existing chunks if re-indexing
    document.chunks.all().delete()
    
    texts_to_embed = [c["content"] for c in raw_chunks]
    embeddings = generate_embeddings_batch(texts_to_embed)
    
    chunk_objs = []
    for idx, (chunk_data, emb) in enumerate(zip(raw_chunks, embeddings)):
        obj = DocumentChunk(
            document=document,
            chunk_index=idx,
            section_title=chunk_data["section_title"][:255],
            section_hierarchy=chunk_data["section_hierarchy"],
            content=chunk_data["content"],
            token_count=len(chunk_data["content"].split()),
            embedding_json=json.dumps(emb) if emb else ""
        )
        chunk_objs.append(obj)
        
    DocumentChunk.objects.bulk_create(chunk_objs)
    
    document.total_chunks = len(chunk_objs)
    document.indexed_at = timezone.now()
    document.save()
    
    logger.info(f"Indexed document '{document.title}' with {len(chunk_objs)} chunks.")
    return len(chunk_objs)


def ensure_default_document_indexed():
    """Ensure the bundled markdown knowledge base in MEDIA_ROOT is indexed if no active document exists."""
    from django.conf import settings
    active = UploadedDocument.objects.filter(is_active=True).first()
    if active and DocumentChunk.objects.filter(document=active).exists():
        return active
    if active and os.path.exists(active.file_path):
        try:
            process_and_index_document(active)
            return active
        except Exception as e:
            logger.warning(f"Failed to index active document {active.title}: {e}")
    inactive = UploadedDocument.objects.order_by('-uploaded_at').first()
    if inactive and os.path.exists(inactive.file_path):
        inactive.is_active = True
        inactive.save(update_fields=['is_active'])
        if not DocumentChunk.objects.filter(document=inactive).exists():
            try:
                process_and_index_document(inactive)
            except Exception as e:
                logger.warning(f"Failed to index document {inactive.title}: {e}")
        return inactive
    media_root = getattr(settings, 'MEDIA_ROOT', None)
    if not media_root or not os.path.isdir(str(media_root)):
        return None
    md_files = sorted(
        f for f in os.listdir(media_root)
        if f.endswith(('.md', '.markdown', '.txt')) and os.path.isfile(os.path.join(media_root, f))
    )
    if not md_files:
        return None
    preferred = 'apptimate_one_deep_knowledge.md' if 'apptimate_one_deep_knowledge.md' in md_files else md_files[0]
    file_path = os.path.join(media_root, preferred)
    base, _ = os.path.splitext(preferred)
    doc = UploadedDocument.objects.create(
        title=base.replace('_', ' ').title(),
        original_filename=preferred,
        file_path=file_path,
        file_size=os.path.getsize(file_path),
        is_active=True,
    )
    try:
        process_and_index_document(doc)
    except Exception as e:
        logger.warning(f"Failed to auto-index default document {preferred}: {e}")
    return doc
