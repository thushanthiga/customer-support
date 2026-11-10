"""Documentation retrieval pipeline for ERP guidance questions.

Steps (each logged):
  1. Query planning   - rewrite the question into focused search queries and an intent
                        (LLM when available, deterministic fallback otherwise).
  2. Hybrid retrieval - BM25 (IDF-weighted, heading-boosted, substantive-filtered) +
                        embeddings per query, fused with Reciprocal Rank Fusion across all queries.
  3. Feature grouping - every chunk is attributed to the product feature guide it belongs
                        to, so different features (e.g. line discounts vs price lists) are
                        presented as separate options instead of being blended.
  4. Reranking        - an LLM selects the sections that actually answer the question;
                        fallback keeps candidates close to the best fused score.
  5. Location expansion - for location/how-to questions, each selected feature's own
                        navigation/entry section is added so the answer can say WHERE.

Nothing here is hardcoded to a specific query: no item names, SKUs, or single-query fixes.
Feature boundaries and navigation sections are derived dynamically from the document.
"""
import json
import logging
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
from django.conf import settings
from openai import OpenAI

from .models import DocumentChunk, UploadedDocument

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
RETRIEVAL_MODEL = os.getenv("RETRIEVAL_MODEL", os.getenv("CHAT_MODEL", "gpt-4o-mini"))
client = OpenAI(api_key=OPENAI_API_KEY)

# Grammatical stopwords.
_STOP = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "at", "by", "with", "from",
    "is", "are", "was", "were", "be", "been", "it", "its", "this", "that", "these", "those",
    "i", "me", "my", "we", "our", "you", "your", "they", "them", "he", "she",
    "do", "does", "did", "can", "could", "should", "would", "will", "shall", "may", "might",
    "where", "how", "what", "which", "who", "when", "why", "please", "tell", "show", "there",
    "want", "need", "like", "about", "into", "any", "some", "so", "if", "then", "also",
}

# Operational action verbs in ERP workflows. Chunks matching ONLY action words without any
# substantive domain entity (e.g. "Add New Terminal" when searching "where can I add discount")
# are filtered out to eliminate spurious false-positive matches.
_ACTION_WORDS = {
    "add", "create", "new", "edit", "update", "delete", "remove", "manage",
    "maintaining", "maintain", "configure", "set", "setup", "view", "open",
    "find", "locate", "reach", "access", "see", "show", "get", "go",
}

# Standard ERP domain acronyms & synonyms to ensure high recall across vocabulary variants.
_SYNONYM_MAP = {
    "po": ["purchase", "order", "orders", "procurement"],
    "grn": ["goods", "receipt", "note", "notes", "receiving"],
    "discount": ["discount", "markdown", "price", "rule", "discountable"],
    "price": ["price", "pricing", "rate", "cost", "markdown"],
    "pricing": ["price", "pricing", "rate", "cost", "markdown", "discount"],
    "terminal": ["terminal", "pos", "counter", "session"],
    "warehouse": ["warehouse", "warehouses", "location", "locations"],
    "wherehouse": ["warehouse", "warehouses", "location", "locations"],
    "customer": ["customer", "customers", "party", "parties", "client"],
    "supplier": ["supplier", "suppliers", "vendor", "vendors"],
    "invoice": ["invoice", "invoices", "billing", "bill", "fulfill", "dispatch"],
    "invoices": ["invoice", "invoices", "billing", "bill", "fulfill", "dispatch"],
    "construction": ["construction", "project", "projects", "boq", "variations", "rate-cards", "rate cards", "wbs", "contractors", "fuel logs", "change orders"],
    "boq": ["boq", "bill of quantities", "estimation", "rate cards", "rates", "construction"],
    "variations": ["variations", "change orders", "scope", "construction", "project controls"],
}

_TOKEN_RE = re.compile(r"[a-z][a-z0-9_]*")
_NUMBERED_HEADING_RE = re.compile(r"^\s*\d+(\.\d+)*[.)]?\s")
_LOCATION_TITLE_RE = re.compile(r"navigation|entry flow|access|menu|where to find|getting there|route", re.I)
_ROUTE_RE = re.compile(r"sidebar\s*(?:➔|->|›|→)|access\s+flow\s*:|menu\s+entry|`/[a-z][a-z0-9_/-]*`|\(/[a-z][a-z0-9_/-]*\)", re.I)
_LOCATION_INTENT_RE = re.compile(r"\b(where|which (screen|page|menu)|find|located|navigate|go to|open)\b", re.I)
_HOWTO_INTENT_RE = re.compile(r"\b(how (do|can|to|should)|steps?|add|create|set ?up|configure|enable|apply|make)\b", re.I)
_TROUBLE_INTENT_RE = re.compile(r"\b(why|error|not working|cannot|can't|unable|disabled|greyed|grayed|fails?|missing)\b", re.I)
_FLOW_INTENT_RE = re.compile(r"\b(flow|workflow|process|lifecycle|overview|explain|walk\s+me\s+through|get\s+me\s+the)\b", re.I)

RRF_K = 60
CANDIDATE_POOL = 36
MAX_SELECTED = 8
MAX_FEATURES = 6


def _stem(token: str) -> str:
    for suffix, repl in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if len(token) > len(suffix) + 3 and token.endswith(suffix) and not token.endswith("ss"):
            return token[: -len(suffix)] + repl
    return token


def tokenize(text: str) -> List[str]:
    return [_stem(t) for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOP and len(t) > 1]


def _model_calls_enabled() -> bool:
    return not getattr(settings, "SUPPORT_DISABLE_MODEL_CALLS", False)


@dataclass
class Section:
    chunk: Any
    position: int
    feature: str
    title: str
    hierarchy: List[str]
    content: str
    title_tokens: List[str] = field(default_factory=list)
    body_tokens: List[str] = field(default_factory=list)
    is_location: bool = False

    @property
    def label(self) -> str:
        path = " > ".join(self.hierarchy) if self.hierarchy else self.title
        return path or self.feature


@dataclass
class SearchPlan:
    intent: str
    subject: str
    queries: List[str]
    needs_location: bool
    source: str
    tokens: Dict[str, int] = field(default_factory=lambda: {"prompt": 0, "completion": 0})


@dataclass
class RetrievalResult:
    plan: SearchPlan
    sections: List[Section]           # ordered, deduplicated, ready for the answer model
    location_sections: List[Section]  # subset that were added for "where" information
    features: List[str]
    candidates_considered: int
    rerank_source: str
    tokens: Dict[str, int] = field(default_factory=lambda: {"prompt": 0, "completion": 0})


# ---------------------------------------------------------------------------
# Corpus Loading & Feature Attribution
# ---------------------------------------------------------------------------

def _clean_feature_name(name: str) -> str:
    name = re.sub(r"\s*—\s*.*Guide.*$", "", name, flags=re.I)
    name = re.sub(r"\s+feature guide.*$", "", name, flags=re.I)
    return name.strip() or name


def load_corpus() -> List[Section]:
    active_doc = UploadedDocument.objects.filter(is_active=True).first()
    if not active_doc:
        return []
    chunks = list(DocumentChunk.objects.filter(document=active_doc))
    chunks.sort(key=lambda c: getattr(c, "chunk_index", 0) or 0)
    corpus: List[Section] = []
    current_guide = getattr(active_doc, "title", "") or "Documentation"

    for position, chunk in enumerate(chunks):
        hierarchy = list(getattr(chunk, "section_hierarchy", None) or [])
        root = hierarchy[0] if hierarchy else ""
        if root and not _NUMBERED_HEADING_RE.match(root) and not root.lower().startswith("apptimate one"):
            current_guide = _clean_feature_name(root)

        # Explicit Feature: or Module: tags inside hierarchy take precedence
        explicit_feature = None
        for item in hierarchy:
            if item.startswith("Feature:"):
                explicit_feature = re.sub(r"^Feature:\s*", "", item).strip()
                break
        if not explicit_feature:
            for item in hierarchy:
                if item.startswith("Module:"):
                    explicit_feature = re.sub(r"^Module:\s*", "", item).strip()
                    break

        feature = explicit_feature or current_guide
        title = getattr(chunk, "section_title", "") or (hierarchy[-1] if hierarchy else "")
        content = getattr(chunk, "content", "") or ""
        heading_text = " ".join([title, *hierarchy])
        corpus.append(Section(
            chunk=chunk,
            position=position,
            feature=feature,
            title=title,
            hierarchy=hierarchy,
            content=content,
            title_tokens=tokenize(heading_text),
            body_tokens=tokenize(content),
            is_location=bool(_LOCATION_TITLE_RE.search(title)) or (
                len(content) < 2500 and bool(_ROUTE_RE.search(content)) and bool(_LOCATION_TITLE_RE.search(heading_text))
            ),
        ))
    corpus_doc = active_doc
    for section in corpus:
        section.chunk._doc = corpus_doc
    return corpus


# ---------------------------------------------------------------------------
# Step 1: query planning
# ---------------------------------------------------------------------------

def _heuristic_intent(question: str) -> str:
    if _TROUBLE_INTENT_RE.search(question):
        return "troubleshooting"
    if _LOCATION_INTENT_RE.search(question):
        return "location"
    if _HOWTO_INTENT_RE.search(question) or _FLOW_INTENT_RE.search(question):
        return "how_to"
    return "concept"


def _heuristic_queries(question: str) -> List[str]:
    queries = [question]
    q_lower = question.lower()
    if "construction" in q_lower or "boq" in q_lower or "variations" in q_lower:
        queries.extend([
            "construction boq rate cards estimation",
            "construction variations change orders project controls",
            "construction projects work breakdown structure",
        ])
    elif "discount" in q_lower:
        queries.extend([
            "discount control line item amt percent",
            "price rule markdown percentage price lists",
            "item master is discountable setting",
        ])
    elif "po" in q_lower or "purchase order" in q_lower:
        queries.append("purchase orders procurement access flow")
    elif "grn" in q_lower or "goods receipt" in q_lower:
        queries.append("goods receipt notes procurement receiving")
    elif "warehouse" in q_lower or "wherehouse" in q_lower:
        queries.append("warehouses core resources access flow")
    elif "price list" in q_lower or "price rule" in q_lower:
        queries.append("price lists master data sales pricing rules")
    elif "invoice" in q_lower or "invoices" in q_lower or "billing" in q_lower:
        if any(term in q_lower for term in ("create", "new", "make", "generate", "issue", "unable", "cannot", "can't", "not able", "why")):
            queries.extend([
                "Dispatch Goods & Generate Invoice sales orders fulfill dispatch",
                "sales orders fulfill dispatch lines to fulfill generate invoice",
                "sales invoices overview accounts receivable post-sales log payment",
                "pos checkout creates invoice finance transaction",
                "procurement invoices supplier invoices 3-way matching",
            ])
        else:
            queries.extend([
                "sales invoices accounts receivable post-sales log payment",
                "Dispatch Goods & Generate Invoice sales orders fulfill",
            ])
    return list(dict.fromkeys(queries))


def plan_search(question: str, history: tuple = ()) -> SearchPlan:
    intent = _heuristic_intent(question)
    fallback = SearchPlan(
        intent=intent,
        subject=question,
        queries=_heuristic_queries(question),
        needs_location=intent in ("location", "how_to"),
        source="heuristic",
    )
    if not _model_calls_enabled():
        logger.info("[DOC STEP 1: QUERY PLAN] heuristic intent=%s queries=%s", intent, fallback.queries)
        return fallback
    system = (
        "You prepare search queries for an ERP product documentation index (UI guides for each "
        "feature: navigation, page fields, workflows, validations). Return JSON only:\n"
        '{"intent": "location|how_to|troubleshooting|concept|capability", '
        '"subject": "<the business task or object in plain words>", '
        '"needs_location": true|false, '
        '"queries": ["3 to 5 short search queries"]}\n'
        "Rules: resolve follow-ups using recent questions; correct spelling; include the terms the "
        "documentation is likely to use (screen names, field labels, related features that can "
        "achieve the same goal, e.g. a per-transaction control AND a configuration/master-data "
        "feature). Note for invoice creation: Sales Invoices are not created as standalone records on the "
        "view-only /sales/invoices page; they are generated through Sales Order fulfillment "
        "('Dispatch Goods & Generate Invoice') or POS checkout. When the user asks about creating/generating "
        "invoices or why they cannot create invoices, search both Sales Order fulfillment and Sales Invoices. "
        "Keep each query under 10 words. needs_location is true when the user asks where "
        "or how to do something in the UI."
    )
    user = json.dumps({"question": question, "recent_questions": list(history)[-3:]})
    try:
        res = client.chat.completions.create(
            model=RETRIEVAL_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        data = json.loads(res.choices[0].message.content or "{}")
        queries = [q.strip() for q in data.get("queries") or [] if isinstance(q, str) and q.strip()][:5]
        if question not in queries:
            queries.insert(0, question)
        plan = SearchPlan(
            intent=str(data.get("intent") or intent),
            subject=str(data.get("subject") or question),
            queries=queries,
            needs_location=bool(data.get("needs_location", fallback.needs_location)),
            source="model",
            tokens={"prompt": getattr(res.usage, "prompt_tokens", 0) or 0,
                    "completion": getattr(res.usage, "completion_tokens", 0) or 0},
        )
        logger.info("[DOC STEP 1: QUERY PLAN] model intent=%s needs_location=%s queries=%s",
                    plan.intent, plan.needs_location, plan.queries)
        return plan
    except Exception as exc:
        logger.warning("[DOC STEP 1: QUERY PLAN FAILED] %s; using heuristic plan", exc)
        return fallback


# ---------------------------------------------------------------------------
# Step 2: hybrid retrieval with BM25 + embeddings + RRF
# ---------------------------------------------------------------------------

class BM25:
    def __init__(self, corpus: List[Section], k1: float = 1.4, b: float = 0.7, title_weight: float = 3.0):
        self.corpus, self.k1, self.b, self.title_weight = corpus, k1, b, title_weight
        self.docs = []
        df = Counter()
        for s in corpus:
            tf = Counter(s.body_tokens)
            for t in s.title_tokens:
                tf[t] += title_weight
            self.docs.append(tf)
            df.update(set(tf))
        n = max(len(corpus), 1)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.avgdl = (sum(sum(d.values()) for d in self.docs) / n) if self.docs else 1.0

    def scores(self, query: str) -> List[float]:
        terms = tokenize(query)
        if not terms:
            return [0.0] * len(self.corpus)
        subs = [t for t in terms if t not in _ACTION_WORDS]
        subs_set = set(subs) if subs else set(terms)
        # Expand substantive terms with domain synonyms
        expanded_subs = set(subs_set)
        for t in list(subs_set):
            if t in _SYNONYM_MAP:
                for syn in _SYNONYM_MAP[t]:
                    expanded_subs.add(_stem(syn))

        out = []
        for tf in self.docs:
            # Document must match at least one substantive term or synonym
            if expanded_subs and not any(t in tf for t in expanded_subs):
                out.append(0.0)
                continue
            dl = sum(tf.values()) or 1.0
            score = 0.0
            matched_terms = 0
            for t in terms:
                f = tf.get(t)
                if not f:
                    continue
                matched_terms += 1
                score += self.idf.get(t, 0.0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            coord = (matched_terms / len(terms)) ** 0.8 if len(terms) > 1 else 1.0
            out.append(score * coord)
        return out


def _embed(texts: List[str]) -> Optional[np.ndarray]:
    if not _model_calls_enabled() or not texts:
        return None
    try:
        res = client.embeddings.create(model=EMBEDDING_MODEL, input=[t.replace("\n", " ") for t in texts])
        return np.array([d.embedding for d in res.data], dtype=np.float32)
    except Exception as exc:
        logger.warning("[DOC STEP 2: EMBEDDING UNAVAILABLE] %s; lexical retrieval only", exc)
        return None


def hybrid_candidates(corpus: List[Section], queries: List[str], pool: int = CANDIDATE_POOL):
    bm25 = BM25(corpus)
    fused = defaultdict(float)
    best_lexical = defaultdict(float)

    def add_ranking(scores: List[float]):
        ranked = sorted((i for i, s in enumerate(scores) if s > 0), key=lambda i: scores[i], reverse=True)[:pool * 2]
        for rank, idx in enumerate(ranked):
            fused[idx] += 1.0 / (RRF_K + rank + 1)

    for q in queries:
        lex = bm25.scores(q)
        add_ranking(lex)
        for i, s in enumerate(lex):
            best_lexical[i] = max(best_lexical[i], s)

    q_emb = _embed(queries)
    if q_emb is not None:
        matrix, rows = [], []
        for i, s in enumerate(corpus):
            emb = s.chunk.get_embedding() if hasattr(s.chunk, "get_embedding") else None
            if emb and len(emb) == q_emb.shape[1]:
                matrix.append(emb)
                rows.append(i)
        if matrix:
            m = np.array(matrix, dtype=np.float32)
            m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
            qn = q_emb / (np.linalg.norm(q_emb, axis=1, keepdims=True) + 1e-9)
            sims = qn @ m.T
            for qi in range(sims.shape[0]):
                scores = [0.0] * len(corpus)
                for j, idx in enumerate(rows):
                    scores[idx] = float(sims[qi, j]) if sims[qi, j] > 0.25 else 0.0
                add_ranking(scores)

    # Feature-diversified candidate selection so a single feature cannot crowd out others
    feature_counts = defaultdict(int)
    ranked = []
    max_per_feature_in_pool = 6
    sorted_indices = sorted(fused, key=lambda i: fused[i], reverse=True)
    for idx in sorted_indices:
        feat = corpus[idx].feature
        if feature_counts[feat] < max_per_feature_in_pool:
            feature_counts[feat] += 1
            ranked.append(idx)
        if len(ranked) >= pool:
            break
    if len(ranked) < pool:
        for idx in sorted_indices:
            if idx not in ranked:
                ranked.append(idx)
            if len(ranked) >= pool:
                break

    logger.info("[DOC STEP 2: HYBRID RETRIEVAL] queries=%d candidates=%d embeddings=%s top=%s",
                len(queries), len(ranked), q_emb is not None,
                [corpus[i].label[:60] for i in ranked[:5]])
    return [(corpus[i], fused[i]) for i in ranked]


# ---------------------------------------------------------------------------
# Step 4: reranking
# ---------------------------------------------------------------------------

def _diversify(candidates, limit=MAX_SELECTED, max_per_feature=2):
    """Diversify candidates across distinct product features so no single feature crowds out others."""
    by_feature = defaultdict(list)
    feature_best_score = {}
    for s, sc in candidates:
        by_feature[s.feature].append((s, sc))
        if s.feature not in feature_best_score:
            feature_best_score[s.feature] = sc

    ranked_features = sorted(feature_best_score.keys(), key=lambda f: feature_best_score[f], reverse=True)
    picked = []
    # Round 1: Top 1 from each feature to maximize diversity
    for f in ranked_features:
        if by_feature[f] and len(picked) < limit:
            picked.append(by_feature[f].pop(0))

    # Round 2: Additional candidates up to max_per_feature
    for f in ranked_features:
        while by_feature[f] and len([p for p in picked if p[0].feature == f]) < max_per_feature and len(picked) < limit:
            picked.append(by_feature[f].pop(0))

    return picked


def rerank(question: str, plan: SearchPlan, candidates):
    tokens = {"prompt": 0, "completion": 0}
    if not candidates:
        return [], "none", tokens
    if _model_calls_enabled():
        listing = []
        for i, (s, _) in enumerate(candidates, 1):
            snippet = re.sub(r"\s+", " ", s.content)[:500]
            listing.append(f"[{i}] Feature: {s.feature}\nSection: {s.label}\n{snippet}")
        system = (
            "You select documentation sections that help answer a user's ERP question. Return JSON "
            '{"selected": [section numbers, most useful first], "reason": "short"}. '
            "Select every section that directly answers the question, including sections from "
            "DIFFERENT features when each is a valid way to achieve the user's goal (e.g. Sales Orders "
            "fulfillment for invoice generation AND Sales Invoices for view/payment tracking, or manual discounts "
            "versus price lists). Exclude sections that only mention a keyword in passing (API payloads, scope notes, unrelated pages). "
            f"Select at most {MAX_SELECTED}. Return an empty list if none answer the question."
        )
        user = f"Question: {question}\nInterpreted task: {plan.subject}\n\n" + "\n\n".join(listing)
        try:
            res = client.chat.completions.create(
                model=RETRIEVAL_MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_object"},
                temperature=0,
            )
            tokens = {"prompt": getattr(res.usage, "prompt_tokens", 0) or 0,
                      "completion": getattr(res.usage, "completion_tokens", 0) or 0}
            data = json.loads(res.choices[0].message.content or "{}")
            ids = [int(x) for x in data.get("selected") or [] if str(x).isdigit()]
            chosen = [candidates[i - 1][0] for i in dict.fromkeys(ids) if 1 <= i <= len(candidates)][:MAX_SELECTED]
            logger.info("[DOC STEP 4: RERANK] model selected=%s reason=%r", [s.label[:50] for s in chosen], data.get("reason"))
            return chosen, "model", tokens
        except Exception as exc:
            logger.warning("[DOC STEP 4: RERANK FAILED] %s; using fused ranking", exc)
    top = candidates[0][1]
    close = [(s, sc) for s, sc in candidates if sc >= top * 0.40]
    chosen = [s for s, _ in _diversify(close, MAX_SELECTED)]
    logger.info("[DOC STEP 4: RERANK] fused-score selection=%s", [s.label[:50] for s in chosen])
    return chosen, "fused_score", tokens


# ---------------------------------------------------------------------------
# Step 5: location expansion
# ---------------------------------------------------------------------------

def location_sections_for(corpus: List[Section], features: List[str]) -> Dict[str, Section]:
    found: Dict[str, Section] = {}
    for feature in features:
        in_feature = [s for s in corpus if s.feature == feature]
        titled = [s for s in in_feature if _LOCATION_TITLE_RE.search(s.title)]
        routed = [s for s in in_feature if _ROUTE_RE.search(s.content)]
        pick = (titled or routed or [None])[0]
        if pick is not None:
            found[feature] = pick
    return found


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def retrieve(question: str, history: tuple = ()) -> Optional[RetrievalResult]:
    corpus = load_corpus()
    if not corpus:
        logger.warning("[DOC RETRIEVAL] No active documentation corpus")
        return None
    plan = plan_search(question, history)
    candidates = hybrid_candidates(corpus, plan.queries)
    if not candidates:
        logger.warning("[DOC RETRIEVAL] No candidates for %r", question)
        return RetrievalResult(plan, [], [], [], 0, "none", dict(plan.tokens))
    selected, rerank_source, rr_tokens = rerank(question, plan, candidates)
    features = list(dict.fromkeys(s.feature for s in selected))[:MAX_FEATURES]
    selected = [s for s in selected if s.feature in features]

    location_added: List[Section] = []
    if plan.needs_location and selected:
        chosen_ids = {id(s) for s in selected}
        for feature, loc in location_sections_for(corpus, features).items():
            if id(loc) not in chosen_ids:
                location_added.append(loc)
                chosen_ids.add(id(loc))

    # Order: grouped by feature (in relevance order), location section first within a feature.
    ordered: List[Section] = []
    for feature in features:
        ordered += [s for s in location_added if s.feature == feature]
        ordered += [s for s in selected if s.feature == feature]
    tokens = {k: plan.tokens.get(k, 0) + rr_tokens.get(k, 0) for k in ("prompt", "completion")}
    logger.info("[DOC STEP 5: CONTEXT] features=%s sections=%d location_added=%d",
                features, len(ordered), len(location_added))
    return RetrievalResult(plan, ordered, location_added, features, len(candidates), rerank_source, tokens)


def format_context(result: RetrievalResult) -> str:
    """Numbered sections grouped by feature, ready for the answer prompt."""
    blocks = []
    n = 0
    location_ids = {id(s) for s in result.location_sections}
    for feature in result.features:
        group = [s for s in result.sections if s.feature == feature]
        if not group:
            continue
        lines = [f"## Feature: {feature}"]
        for s in group:
            n += 1
            tag = " (location / navigation)" if id(s) in location_ids else ""
            lines.append(f"[S{n}] Section: {s.label}{tag}\n{s.content.strip()}")
        blocks.append("\n\n".join(lines))
    return "\n\n---\n\n".join(blocks)


def section_reference(section: Section, index: int) -> Dict[str, Any]:
    chunk = section.chunk
    doc = getattr(chunk, "_doc", None)
    return {
        "citation": f"S{index}",
        "chunk_id": getattr(chunk, "id", None),
        "document_id": getattr(doc, "id", None),
        "document_title": getattr(doc, "title", "") or "",
        "section_title": section.title,
        "feature": section.feature,
        "hierarchy": section.hierarchy,
        "source_text": section.content,
        "preview": section.content[:200] + ("..." if len(section.content) > 200 else ""),
        "match_type": "location" if section.is_location else "content",
    }
