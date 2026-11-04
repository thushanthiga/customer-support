"""Pure-Python hybrid semantic and lexical Document Search (RAG) service."""
import logging
import os
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple

import numpy as np
from openai import OpenAI

from .models import DocumentChunk, UploadedDocument

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

client = OpenAI(api_key=OPENAI_API_KEY)

_STOP_WORDS = {
    "where", "how", "can", "do", "does", "did", "i", "we", "you", "they", "see",
    "view", "open", "find", "access", "locate", "reach", "go", "get", "to", "the",
    "a", "an", "my", "our", "your", "this", "that", "screen", "page", "menu", "please",
    "me", "it", "is", "are", "in", "on", "for", "at", "of", "and", "or", "tell",
    "main", "all", "active", "inactive", "setup", "management", "master", "details", "list",
    "add", "create", "new", "edit", "update", "manage", "maintain", "configure",
    "set", "up", "record", "delete", "remove", "change", "want", "need", "what", "which",
}

_NAVIGATION_ROUTE_RE = re.compile(
    r"(?:sidebar\s*(?:➔|->|›|→)|access\s+flow\s*:|menu\s+entry\s*:|\broute\s*:|/[a-z][a-z0-9_/-]*)",
    re.IGNORECASE,
)
_SIDEBAR_PATH_RE = re.compile(
    r"\bSidebar\s*(?:➔|→|›|->)\s*"
    r"(?P<path>[A-Za-z0-9][A-Za-z0-9&'/_ -]*(?:\s*(?:➔|→|›|->)\s*[A-Za-z0-9][A-Za-z0-9&'/_ -]*)+)",
    re.IGNORECASE,
)


def cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    """Calculates cosine similarity between two vectors."""
    dot = np.dot(v1, v2)
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(dot / (norm1 * norm2))


def get_query_embedding(query_text: str) -> List[float]:
    """Generates an embedding for a user search or chat query."""
    from django.conf import settings
    if getattr(settings, "SUPPORT_DISABLE_MODEL_CALLS", False):
        raise RuntimeError("Model calls are disabled.")
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query_text.replace("\n", " ").strip(),
    )
    return response.data[0].embedding


def _normalize_token(token: str) -> str:
    token = token.lower()
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _query_terms(query: str) -> set[str]:
    return {
        _normalize_token(token)
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", (query or "").lower())
        if token.lower() not in _STOP_WORDS and len(token) > 2
    }


def _term_match(term: str, candidate_tokens: set[str]) -> bool:
    if term in candidate_tokens:
        return True
    if len(term) < 5:
        return False
    return any(
        len(candidate) >= 5 and SequenceMatcher(None, term, candidate).ratio() >= 0.85
        for candidate in candidate_tokens
    )


def _lexical_chunk_score(query: str, chunk) -> float:
    """Compute a lexical relevance score across section hierarchy, title, and content."""
    terms = _query_terms(query)
    if not terms:
        return 0.0
    title_text = f"{chunk.section_title or ''} {' '.join(chunk.section_hierarchy or [])}".lower()
    content_text = (chunk.content or "").lower()
    title_tokens = {_normalize_token(t) for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", title_text)}
    content_tokens = {_normalize_token(t) for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", content_text)}
    title_hits = sum(1 for term in terms if _term_match(term, title_tokens))
    content_hits = sum(1 for term in terms if _term_match(term, content_tokens))
    if not title_hits and not content_hits:
        return 0.0
    title_ratio = title_hits / len(terms)
    content_ratio = content_hits / len(terms)
    return min(0.99, 0.55 * title_ratio + 0.45 * content_ratio)


def retrieve_relevant_chunks(
    query: str,
    top_k: int = 6,
    min_similarity: float = 0.20,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Retrieves the most semantically and lexically relevant chunks from the currently active document.
    Returns:
        (formatted_context_str, list_of_reference_metadata)
    """
    from .chunking_service import ensure_default_document_indexed

    active_doc = UploadedDocument.objects.filter(is_active=True).first() or ensure_default_document_indexed()
    if not active_doc:
        return "", []

    chunks = list(DocumentChunk.objects.filter(document=active_doc))
    if not chunks:
        return "", []

    q_emb = None
    try:
        q_emb = np.array(get_query_embedding(query), dtype=np.float32)
    except Exception as e:
        logger.warning(f"Query embedding unavailable, using lexical retrieval fallback: {e}")

    scored_chunks = []
    for chunk in chunks:
        lex_score = _lexical_chunk_score(query, chunk)
        vec_score = 0.0
        emb_list = chunk.get_embedding()
        if q_emb is not None and emb_list:
            c_emb = np.array(emb_list, dtype=np.float32)
            if c_emb.shape == q_emb.shape:
                vec_score = cosine_similarity(q_emb, c_emb)
        if vec_score > 0:
            score = min(1.0, vec_score + 0.20 * lex_score)
        else:
            score = lex_score
        if score >= min_similarity:
            scored_chunks.append((score, chunk))

    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    top_matches = scored_chunks[:top_k]
    if not top_matches:
        return "", []

    formatted_context_pieces = []
    references = []
    for score, chunk in top_matches:
        hierarchy_str = " > ".join(chunk.section_hierarchy) if chunk.section_hierarchy else chunk.section_title
        formatted_context_pieces.append(f"### [Section: {hierarchy_str}]\n{chunk.content}")
        references.append({
            "chunk_id": chunk.id,
            "document_title": active_doc.title,
            "section_title": chunk.section_title,
            "hierarchy": chunk.section_hierarchy,
            "similarity_score": round(score, 4),
            "preview": chunk.content[:200] + ("..." if len(chunk.content) > 200 else ""),
        })

    return "\n\n---\n\n".join(formatted_context_pieces), references


def _documented_sidebar_paths(context: str) -> list[str]:
    clean = (context or "").replace("`", "").replace("**", "")
    clean = re.sub(r"\s*\(/[a-zA-Z0-9_/?&=.-]+\)", "", clean)
    paths = []
    for match in _SIDEBAR_PATH_RE.finditer(clean):
        components = [
            re.sub(r"\s+", " ", part).strip(" .,:;-")
            for part in re.split(r"\s*(?:➔|→|›|->)\s*", match.group("path"))
        ]
        if len(components) >= 2 and all(components):
            paths.append("Sidebar ➔ " + " ➔ ".join(components))
    return list(dict.fromkeys(paths))


def retrieve_navigation_chunks(query: str, top_k: int = 5) -> Tuple[str, List[Dict[str, Any]]]:
    """Retrieve route-bearing documentation chunks matching the user's navigation query."""
    subject_terms = _query_terms(query)
    if not subject_terms:
        return retrieve_relevant_chunks(query, top_k=top_k)

    from .chunking_service import ensure_default_document_indexed

    active_doc = UploadedDocument.objects.filter(is_active=True).first() or ensure_default_document_indexed()
    if not active_doc:
        return "", []

    chunks = list(DocumentChunk.objects.filter(document=active_doc))
    candidates = []
    for chunk in chunks:
        content = chunk.content or ""
        if not _NAVIGATION_ROUTE_RE.search(content):
            continue
        lex_score = _lexical_chunk_score(query, chunk)
        if lex_score > 0:
            candidates.append((lex_score, chunk))

    candidates.sort(key=lambda item: (item[0], item[1].chunk_index), reverse=True)
    selected = candidates[:top_k]
    if not selected:
        return retrieve_relevant_chunks(query, top_k=top_k)

    context_pieces, references = [], []
    for score, chunk in selected:
        hierarchy = " > ".join(chunk.section_hierarchy) if chunk.section_hierarchy else chunk.section_title
        context_pieces.append(f"### [Navigation section: {hierarchy}]\n{chunk.content}")
        references.append({
            "chunk_id": chunk.id,
            "document_title": active_doc.title,
            "section_title": chunk.section_title,
            "hierarchy": chunk.section_hierarchy,
            "similarity_score": round(score, 4),
            "preview": chunk.content[:200] + ("..." if len(chunk.content) > 200 else ""),
            "match_type": "navigation_route_retrieval",
        })
    return "\n\n---\n\n".join(context_pieces), references
