"""Unified pure-Python LLM-driven assistant: LLM intent/follow-up resolution, query planning, Document Search (RAG), and Database Search."""
import json
import os
import re

from django.conf import settings
from openai import OpenAI

from . import query_service
from .erp_access import public_schema, redact
from .query_planner import plan_question
from .rag_service import (
    _documented_sidebar_paths,
    retrieve_navigation_chunks,
    retrieve_relevant_chunks,
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-6-luna")
client = OpenAI(api_key=OPENAI_API_KEY)


def cell(value):
    if value is None:
        return "not recorded"
    if isinstance(value, (dict, list)):
        value = json.dumps(redact(value), ensure_ascii=False)
    return str(value).replace("|", "\\|").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")


def _format_header(name):
    acronyms = {"id": "Id", "sku": "Sku", "pos": "Pos", "po": "PO", "grn": "GRN", "ap": "AP", "ar": "AR", "qty": "Qty"}
    words = str(name).split("_")
    return " ".join(acronyms.get(w.lower(), w.capitalize()) for w in words)


def table(rows, maximum=50):
    if not rows:
        return "No matching records were found."
    columns = list(rows[0])
    text = [
        "| " + " | ".join(_format_header(k) for k in columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    for row in rows[:maximum]:
        text.append("| " + " | ".join(cell(row.get(k)) for k in columns) + " |")
    return "\n".join(text)


def _trusted_query_records(sources):
    records = []
    for source in sources:
        result = source.get("result") or {}
        if not isinstance(result, dict) or result.get("error"):
            continue
        audit = result.get("query_audit") or {}
        refs = audit.get("table_references") or {}
        fields = audit.get("selected_fields") or []
        for row in result.get("results") or []:
            for index, field in enumerate(fields, 1):
                if (
                    field.get("column")
                    not in {"sku", "po_number", "invoice_number", "grn_number", "order_number", "project_code"}
                    or field.get("aggregate")
                ):
                    continue
                identifier = row.get(field.get("alias") or f"field_{index}")
                for id_index, id_field in enumerate(fields, 1):
                    if id_field.get("table") == field.get("table") and id_field.get("column") == "id" and not id_field.get("aggregate"):
                        value = row.get(id_field.get("alias") or f"field_{id_index}")
                        if identifier and isinstance(value, int):
                            records.append({
                                "identifier": identifier,
                                "id": value,
                                "table": refs.get(field["table"], field["table"]),
                            })
    return records


def _has_requested_row_limit(question: str) -> bool:
    return bool(
        re.search(
            r"\b(?:top|first|latest|last|most\s+recent|lowest|highest)\s+\d+\b|\blimit\s+\d+\b",
            question or "",
            re.IGNORECASE,
        )
    )


def backend_join_and_analyze(successes, question):
    """Join multiple query datasets on a common key and calculate requested comparisons on backend."""
    if len(successes) < 2:
        return None

    datasets = [res.get("results") or [] for _, _, res in successes]
    if not all(datasets):
        return None

    q_lower = (question or "").lower()

    # Find common join key across datasets
    keys_list = [set(ds[0].keys()) for ds in datasets if ds]
    if len(keys_list) < 2:
        return None

    common_keys = keys_list[0] & keys_list[1]
    preferred_key = None
    for k in ["supplier_id", "party_id", "customer_id", "item_id", "id", "supplier_code", "code"]:
        if k in common_keys:
            preferred_key = k
            break

    if not preferred_key:
        return None

    # Sort datasets: aggregate summary (fewer rows) vs individual details (more rows)
    if len(datasets[0]) <= len(datasets[1]):
        ds_agg, ds_ind = datasets[0], datasets[1]
    else:
        ds_agg, ds_ind = datasets[1], datasets[0]

    # Find balance / total field in ds_agg
    bal_field = next(
        (k for k in ds_agg[0].keys() if any(t in k.lower() for t in ["balance", "outstanding", "total", "sum", "grand_total"])),
        None
    )
    if not bal_field:
        return None

    # In ds_ind, map key -> first record (latest invoice since sorted descending)
    latest_by_key = {}
    for r in ds_ind:
        kv = r.get(preferred_key)
        if kv is not None and kv not in latest_by_key:
            latest_by_key[kv] = r

    joined_rows = []
    for agg_row in ds_agg:
        kv = agg_row.get(preferred_key)
        try:
            bal = float(agg_row.get(bal_field) or 0)
        except (ValueError, TypeError):
            bal = 0.0

        ind_row = latest_by_key.get(kv)
        latest_amt = None
        latest_date = None
        if ind_row:
            latest_date = ind_row.get("invoice_date") or ind_row.get("date") or ind_row.get("created_at")
            for k in ["latest_invoice_amount_due", "latest_invoice_amount", "amount_due", "grand_total", "amount", "total"]:
                if k in ind_row and ind_row[k] is not None:
                    try:
                        latest_amt = float(ind_row[k])
                        break
                    except (ValueError, TypeError):
                        pass

        # Perform comparison if question asks for more than double
        if any(w in q_lower for w in ["double", "more than double", "2 *", "twice", "2x"]):
            if latest_amt is not None:
                if bal <= 2 * latest_amt:
                    continue  # Does not meet threshold
            elif bal <= 0:
                continue

        # Build clean user-facing record
        name = (
            f"{agg_row.get('supplier_first_name') or agg_row.get('first_name') or ''} {agg_row.get('supplier_last_name') or agg_row.get('last_name') or ''}".strip()
            or agg_row.get("supplier_name")
            or agg_row.get("name")
            or (ind_row and f"{ind_row.get('supplier_first_name') or ind_row.get('first_name') or ''} {ind_row.get('supplier_last_name') or ind_row.get('last_name') or ''}".strip())
            or (ind_row and (ind_row.get("supplier_name") or ind_row.get("name")))
            or "—"
        )
        code = (
            agg_row.get("supplier_code")
            or agg_row.get("code")
            or (ind_row and (ind_row.get("supplier_code") or ind_row.get("code")))
            or "—"
        )

        row_dict = {
            "Supplier ID": kv,
            "Supplier Code": code,
            "Supplier Name": name,
            "Outstanding Balance": f"{bal:,.2f}".rstrip("0").rstrip("."),
            "Latest Invoice Amount": f"{latest_amt:,.2f}".rstrip("0").rstrip(".") if latest_amt is not None else "No invoice recorded",
            "Latest Invoice Date": str(latest_date)[:10] if latest_date else "—",
        }
        joined_rows.append(row_dict)

    return joined_rows


def normalize_query_text(text: str) -> str:
    """Normalize common autocorrect / phonetic slips (e.g. 'sealed' -> 'sold' in sales/item context)."""
    t = text or ""
    t = re.sub(r"\bnot\s+sealed\b", "not sold", t, flags=re.IGNORECASE)
    t = re.sub(r"\bnot\s+selled\b", "not sold", t, flags=re.IGNORECASE)
    t = re.sub(r"\bsealed\s+yet\b", "sold yet", t, flags=re.IGNORECASE)
    t = re.sub(r"\bunsealed\b", "unsold", t, flags=re.IGNORECASE)
    t = re.sub(r"\bitems?\s+which\s+are\s+sealed\b", "items which are sold", t, flags=re.IGNORECASE)
    return t


def extract_item_reference(question: str, history: tuple = ()) -> dict:
    """Extract any specific product, item name, or SKU mentioned in the user query, correcting typos and resolving conversation history."""
    q_clean = (question or "").strip()
    if not q_clean or getattr(settings, "SUPPORT_DISABLE_MODEL_CALLS", False):
        return {"has_item": False}
    try:
        sys_prompt = (
            "Extract any specific product, item name, or SKU mentioned in the user question that might refer to an inventory/catalog item.\n"
            "CRITICAL RULES:\n"
            "1. Automatically fix typos, spelling mistakes, phonetic variations, or keyboard slips in the extracted item name or SKU.\n"
            "2. If the user query is a conversational follow-up or references an item from previous turns, resolve the exact item name or SKU using the conversation history context.\n"
            "3. Return JSON: {\"has_item\": true/false, \"item_name\": \"corrected standard item name or SKU\", \"raw_term\": \"original text\"}\n"
            "4. If the question is generic without any specific product (e.g. 'how do I create a quotation', 'where is sales orders', 'how to add discount'), return {\"has_item\": false}.\n"
            "5. If the user is asking about software features, capabilities, modules, or system settings (e.g., 'how to configure blockchain', 'crypto gateway', 'does it support X'), return {\"has_item\": false}."
        )
        user_msg = f"User Question: {q_clean}"
        if history:
            user_msg = f"Recent Conversation Questions: {list(history)[-3:]}\n\n" + user_msg

        res = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_msg}
            ],
            response_format={"type": "json_object"},
            reasoning_effort="none",
        )
        return json.loads(res.choices[0].message.content)
    except Exception:
        return {"has_item": False}


def lookup_item_details(item_term: str, tenant_db: str) -> dict:
    """Check whether an item exists in the ERP catalog, and fetch its availability (pieces) and configs."""
    term = (item_term or "").strip().lower()
    if not term:
        return {"searched_candidate": "", "matches": []}

    candidates = [term]
    if term.endswith("s") and not term.endswith("ss"):
        candidates.append(term[:-1])
    if term.endswith("es"):
        candidates.append(term[:-2])

    words = [w for w in re.split(r"\s+", term) if len(w) >= 3 and w not in {"the", "all", "any", "item", "items"}]
    for w in words:
        if w not in candidates:
            candidates.append(w)
            if w.endswith("s") and not w.endswith("ss"):
                candidates.append(w[:-1])

    from .mcp_client import mcp_run_select
    from .db_service import get_tenant_connection

    for cand in candidates:
        q = """
        SELECT 
            i.id, i.sku, i.name, i.status, i.is_discountable, i.is_available_sell, i.is_returnable,
            COALESCE(SUM(b.qty_on_hand), 0) AS stock_on_hand,
            COALESCE(SUM(b.qty_available), 0) AS stock_available
        FROM inventory_items i
        LEFT JOIN inventory_stock_balances b ON b.item_id = i.id
        WHERE i.deleted_at IS NULL
          AND (
            LOWER(i.name) LIKE %s
            OR LOWER(i.sku) LIKE %s
          )
        GROUP BY i.id, i.sku, i.name, i.status, i.is_discountable, i.is_available_sell, i.is_returnable
        """
        pattern = f"%{cand}%"
        rows = []
        try:
            res = mcp_run_select(q, database=tenant_db, page_size=5, params=[pattern, pattern])
            rows = res.get("rows", [])
        except Exception:
            rows = []

        if not rows:
            try:
                from decimal import Decimal
                with get_tenant_connection(tenant_db) as conn:
                    with conn.cursor() as cur:
                        cur.execute(q + " LIMIT 5", [pattern, pattern])
                        raw_rows = cur.fetchall()
                        rows = [
                            {
                                k: int(v) if isinstance(v, Decimal) and v % 1 == 0 else float(v) if isinstance(v, Decimal) else v
                                for k, v in r.items()
                            }
                            for r in raw_rows
                        ]
            except Exception:
                rows = []

        if rows:
            return {"searched_candidate": cand, "matches": rows}

    return {"searched_candidate": term, "matches": []}


def classify_query(question: str, history: tuple = ()) -> dict:
    """Classify the user inquiry as 'database', 'document', or 'general'."""
    q = normalize_query_text(question).strip()
    q_lower = q.lower()

    # Fast path: database records / aggregates
    db_prefixes = (
        "list ", "list down", "show ", "display ", "find all ", "get all ",
        "give me ", "how many ", "what is the total", "count of ", "sum of ",
        "which suppliers", "which items", "which customers", "which products",
        "items which", "suppliers whose", "customers whose"
    )
    if any(q_lower.startswith(p) for p in db_prefixes):
        return {"classification": "database", "reason": "Query requests live ERP database records or aggregates."}

    # Fast path: documentation / navigation / how-to
    doc_prefixes = (
        "how to ", "how do i ", "how can i ", "where can i ", "where do i ",
        "where is ", "where are ", "which menu", "which screen", "what does "
    )
    if any(q_lower.startswith(p) for p in doc_prefixes) or "how do i create" in q_lower:
        return {"classification": "document", "reason": "Query asks for software guidance, navigation, or feature documentation."}

    # Model classification for conceptual / ambiguous requests
    try:
        sys_prompt = (
            "You are the Request Classifier for Apptimate One ERP Support.\n"
            "Classify the user inquiry into exactly one category:\n"
            "- 'database': Asking to retrieve, filter, count, calculate, or inspect live records/data in the ERP database (items, stock, transactions, orders, invoices, suppliers, customers, prices, balances).\n"
            "- 'document': Asking about software usage, UI navigation, feature explanation, business rules, setup, or documentation.\n"
            "- 'general': Greetings or conversational acknowledgements.\n"
            "Return JSON: {\"classification\": \"database\" | \"document\" | \"general\", \"reason\": \"brief explanation\"}"
        )
        res = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": q}
            ],
            response_format={"type": "json_object"},
            reasoning_effort="none",
        )
        data = json.loads(res.choices[0].message.content)
        return {
            "classification": data.get("classification", "database"),
            "reason": data.get("reason", ""),
            "prompt_tokens": getattr(res.usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(res.usage, "completion_tokens", 0) or 0,
        }
    except Exception:
        return {"classification": "database", "reason": "Default to database search."}


class LocalAnswer:
    def __init__(self, tenant, principal, question, previous_questions=(), state=None):
        self.tenant, self.principal = tenant, principal
        self.question = normalize_query_text(question)
        self.previous = tuple(normalize_query_text(pq) for pq in previous_questions)
        self.state = state if state is not None else {}
        self.evidence, self.parts, self.failures = [], [], []
        self.data_pages = []
        self.references = []
        self.status = "answered"
        self.prompt_tokens = self.completion_tokens = 0
        self.model_source = "not_used"
        self.model_name = ""
        self._rendered_queries = False
        self._queried = False
        self._paging_title = None
        self.search_type = "database"
        self.classification_reason = ""

    def query(self, plan, label=None, question=None, top=False):
        if not plan.get("order_by"):
            fields = plan.get("select") or []
            order = [
                {"alias": x.get("alias") or f"field_{i}", "direction": "asc"}
                for i, x in enumerate(fields, 1)
                if not x.get("aggregate")
            ]
            if order:
                plan = {**plan, "order_by": order}
        resolved = _trusted_query_records(self.evidence)
        result = query_service.query_business_data(
            plan,
            self.tenant,
            user_question=question or self.question,
            resolved_records=resolved or None,
        )
        result = redact(result)
        self.evidence.append({
            "tool": "mcp:run_select",
            "arguments": {"query_plan": plan, "offset": plan.get("offset", 0)},
            "result": redact(result),
        })
        if result.get("error"):
            self.failures.append(result["error"])
            return result
        if not self._queried and not self._paging_title:
            self.state["query_pages"] = []
        self._queried = True
        if label:
            rendered = {**result, "truncated": False, "next_offset": None} if top else result
            self.render_query(rendered, label, plan)
            if top:
                self.parts.append(
                    f'Top {plan.get("limit", 50)} requested record(s), using the displayed query ordering. Older/lower-ranked records are outside this result scope.'
                )
        self.state["last_query"] = plan
        self.state["next_offset"] = result.get("next_offset")
        self.state["last_query_summary"] = {
            "row_count": result.get("row_count", len(result.get("results") or [])),
            "truncated": bool(result.get("truncated")),
        }
        return result

    def render_query(self, result, label="", plan=None):
        rows = result.get("results") or []
        fields = (result.get("query_audit") or {}).get("selected_fields", [])
        mapped = []
        for row in rows:
            mapped.append(
                {
                    field.get("alias") or field.get("column") or f"field_{index}": row.get(
                        field.get("alias") or f"field_{index}"
                    )
                    for index, field in enumerate(fields, 1)
                }
            )
        count = len(rows)
        aggregated = any(field.get("aggregate") for field in fields)
        summary = (
            f"Returned **{count} summary row(s)**."
            if aggregated
            else f"Found **{count} matching record(s)**."
        )
        self.parts.append(summary + "\n\n" + table(mapped))
        calculated = [field.get("alias") or f"field_{i}" for i, field in enumerate(fields, 1) if field.get("expression")]
        if calculated and any(row.get(name) is None for row in rows for name in calculated):
            self.parts.append(
                "A not-recorded calculated value has a missing input or an undefined division (zero divisor); it is not a zero amount."
            )
        self.data_pages.append({"title": label or (plan.get("base_table") if plan else ""), "rows": mapped, "truncated": bool(result.get("truncated"))})
        if plan:
            self._rendered_queries = True
            pages = self.state.setdefault("query_pages", [])
            title = self._paging_title or label or (plan.get("base_table") if plan else "")
            pages[:] = [p for p in pages if p["title"] != title]
            if result.get("truncated"):
                pages.append({"title": title, "plan": plan, "next_offset": result.get("next_offset")})

    def run(self):
        q = self.question.strip()
        page_request = re.fullmatch(
            r"\s*(?:next(?: page)?|more(?: rows)?|continue)(?:\s+for\s+(.+?))?\s*[.!?]*",
            q,
            re.I,
        )
        if page_request and self.state.get("last_query"):
            pages = self.state.get("query_pages")
            if pages is None:
                pages = (
                    [{"title": "Previous result", "plan": self.state["last_query"], "next_offset": self.state["next_offset"]}]
                    if self.state.get("next_offset") is not None
                    else []
                )
            requested = page_request[1]
            candidates = [p for p in pages if not requested or requested.strip(" .!?").casefold() == p["title"].casefold()]
            if not pages:
                self.parts.append("The previous query is complete; there is no next page.")
            elif len(candidates) != 1:
                self.parts.append(
                    "Which result should I continue? Use “next page for” followed by one of these result titles:\n\n"
                    + "\n".join("- " + p["title"] for p in pages)
                )
                self.status = "needs_clarification"
            else:
                page = candidates[0]
                self._paging_title = page["title"]
                plan = {**page["plan"], "offset": page["next_offset"]}
                result = self.query(plan, page["title"], question="Retrieve the next page of the same scoped records")
                if result.get("error"):
                    self.parts.append("The next page could not be retrieved: " + result["error"])
                    self.status = "lookup_failed"
            return self.payload()

        # 1. Classify the inquiry
        cls = classify_query(self.question, self.previous)
        self.search_type = cls.get("classification", "database")
        self.classification_reason = cls.get("reason", "")
        self.prompt_tokens += cls.get("prompt_tokens", 0)
        self.completion_tokens += cls.get("completion_tokens", 0)

        # 2. Route strictly according to classification
        if self.search_type == "document":
            self.documentation_answer(self.question)
            return self.payload()

        if self.search_type == "general":
            self.general_answer_reply(self.question)
            return self.payload()

        # 3. Database search (never falls back to RAG documentation)
        self.generic_answer()
        return self.payload()

    def general_answer_reply(self, question):
        q_lower = (question or "").lower()
        if any(w in q_lower for w in ["thank", "thx", "appreciate"]):
            self.parts.append("You're welcome! Let me know if you need any other reports, data checks, or ERP guidance.")
        elif any(w in q_lower for w in ["hello", "hi", "hey", "good morning", "good afternoon"]):
            self.parts.append("Hello! How can I help you today? You can ask me to look up ERP records, list sales or stock data, or guide you through any ERP screen.")
        else:
            self.parts.append("How can I assist you with Apptimate One? You can ask for live database queries or documentation guidance.")
        self.status = "answered"

    def documentation_answer(self, question=None, initial_context="", initial_refs=None):
        q = question or self.question
        context_parts = []
        merged_refs = []
        seen_keys = set()

        def add_chunks(ctx, refs):
            if ctx:
                for block in ctx.split("\n\n---\n\n"):
                    block_clean = block.strip()
                    if block_clean and block_clean not in context_parts:
                        context_parts.append(block_clean)
            for ref in refs or []:
                key = (ref.get("section_title"), (ref.get("preview") or "")[:80])
                if key not in seen_keys:
                    seen_keys.add(key)
                    merged_refs.append(ref)

        add_chunks(initial_context, initial_refs)
        if not initial_context:
            nav_ctx, nav_refs = retrieve_navigation_chunks(q, top_k=5)
            add_chunks(nav_ctx, nav_refs)
        rag_ctx, rag_refs = retrieve_relevant_chunks(q, top_k=5)
        add_chunks(rag_ctx, rag_refs)

        # Enrich context with transaction/item entry flows when action or discount is requested
        if any(w in q.lower() for w in ["discount", "price", "order", "quotation", "quote", "invoice", "pos", "sell"]):
            nav_extra_ctx, nav_extra_refs = retrieve_navigation_chunks("Sales Orders Quotations POS Items entry flow", top_k=3)
            add_chunks(nav_extra_ctx, nav_extra_refs)

        combined_context = "\n\n---\n\n".join(context_parts[:8]) if context_parts else "No specific documentation section matched."
        paths = _documented_sidebar_paths(combined_context) if context_parts else []

        # Check if question references a specific item or product in the catalog
        item_check_block = ""
        item_ref = extract_item_reference(q, self.previous)
        if item_ref.get("has_item") and item_ref.get("item_name"):
            item_name = item_ref["item_name"].strip()
            item_lookup = lookup_item_details(item_name, self.tenant)
            matches = item_lookup.get("matches", [])
            self.evidence.append({
                "tool": "mcp:check_item_availability",
                "result": {
                    "item_term": item_name,
                    "searched_candidate": item_lookup.get("searched_candidate"),
                    "found_count": len(matches),
                    "matches": matches,
                }
            })
            self.search_type = "hybrid"

            if matches:
                found_lines = []
                for m in matches:
                    found_lines.append(
                        f"- Item: **{m['name']}** (SKU: `{m['sku']}`, ID: {m['id']}) | "
                        f"Status: **{m['status']}** | "
                        f"Stock on Hand: **{m['stock_on_hand']} pieces** (Available: **{m['stock_available']} pieces**) | "
                        f"Is Discountable: **{'Yes' if m.get('is_discountable') else 'No'}** | "
                        f"Available for Sale: **{'Yes' if m.get('is_available_sell') else 'No'}**"
                    )
                item_check_block = (
                    "LIVE ERP DATABASE ITEM AVAILABILITY & CONFIGURATION CHECK:\n"
                    f"The item was verified in your live inventory catalog (`inventory_items`):\n"
                    + "\n".join(found_lines)
                    + "\n"
                )
            else:
                item_check_block = (
                    "LIVE ERP DATABASE ITEM AVAILABILITY & CONFIGURATION CHECK:\n"
                    f"NO ITEM matching '{item_name}' (or related terms) was found in your live inventory catalog (`inventory_items`).\n"
                    "The item does NOT currently exist in the database catalog (0 stock / 0 pieces available).\n"
                )

        if not getattr(settings, "SUPPORT_DISABLE_MODEL_CALLS", False):
            try:
                sys_prompt = (
                    "You are Apptimate Assist, the 24x7 Customer Support & Admin Assistant for Apptimate One ERP.\n"
                    "When explaining how to perform an action, apply a discount, configure a setting, or navigate in Apptimate One, provide a DETAILED, UI-SPECIFIC, STEP-BY-STEP guide using the EXACT menu keywords, button labels, and UI elements:\n"
                    "1. ITEM AVAILABILITY & CONFIGURATION INVENTORY CHECK (CRITICAL):\n"
                    "   - If a specific item was checked in the live database and NO MATCHING ITEM WAS FOUND in the inventory catalog:\n"
                    "     * Clearly inform the user upfront in your opening sentence that **no item matching that product was found in your inventory catalog**.\n"
                    "     * State that because the item does not exist, a discount or sale cannot currently be processed for it.\n"
                    "     * Provide the exact UI navigation to create the item first: Go to **Sidebar ➔ Inventory ➔ Catalog ➔ Items** (`/inventory/catalog/items`), click **+ New Item**, and explicitly instruct them to enable the **Is Discountable** setting.\n"
                    "     * Mention ensuring available stock/pieces are recorded (via Opening Stock or Purchase Order GRN).\n"
                    "     * Then explain how once the item is created, the discount can be applied on sales transactions (**Sidebar ➔ Sales ➔ Sales Orders** / **Sidebar ➔ Sales ➔ POS** -> line **Discount** control -> select **%** -> enter discount value).\n"
                    "   - If the item WAS FOUND in the inventory catalog:\n"
                    "     * State the item's live status, current stock availability / pieces on hand, and whether **Is Discountable** is enabled.\n"
                    "     * If **Is Discountable** is enabled: confirm that yes, the discount can be applied, and guide the user through the exact transaction steps.\n"
                    "     * If **Is Discountable** is disabled: inform the user that discounting is currently disabled for this item in its master record. Direct them to **Sidebar ➔ Inventory ➔ Catalog ➔ Items**, open the item, check **Is Discountable**, and then proceed.\n"
                    "2. EXACT SIDEBAR NAVIGATION PATHS:\n"
                    "   - Always tell the user exactly where to go in the system using standard Sidebar navigation paths in bold (e.g., **Sidebar ➔ Sales ➔ Sales Orders** (`/sales/orders`), **Sidebar ➔ Sales ➔ Quotations**, **Sidebar ➔ Sales ➔ POS**, or **Sidebar ➔ Inventory ➔ Catalog ➔ Items**).\n"
                    "   - Never use vague phrases like 'open the transaction'; always specify the exact menu path.\n"
                    "3. STEP-BY-STEP UI ACTIONS WITH EXACT BUTTON & FIELD NAMES:\n"
                    "   - State the exact buttons to click (e.g., **+ New Order** / **+ New Quotation**).\n"
                    "   - State the exact field names, dropdowns, and controls in bold (e.g., in the item row, find the **Discount** column control, click the mode dropdown to select **%** instead of **Amt**, and enter the value in the numeric input with placeholder **0.00**).\n"
                    "   - If explaining a specific item, reference the item name and details.\n"
                    "4. PREREQUISITES & TROUBLESHOOTING:\n"
                    "   - List disabling conditions (e.g., allowEditPrice setting, line marked as free quantity, unit price is zero, or missing batch selection for batch-tracked lines).\n"
                    "5. FORMATTING:\n"
                    "   - Use clean Markdown with bold UI elements, numbered steps, and section headings.\n"
                    "6. STRICT DOCUMENTATION GROUNDING & ANTI-HALLUCINATION:\n"
                    "   - Only describe features, modules, settings, or integrations that are documented in the verified documentation sections.\n"
                    "   - If the user asks about a feature, technology, or integration (e.g., blockchain, cryptocurrency, unsupported third-party gateways) that is NOT present in the verified documentation sections, clearly state that this feature is not supported or documented in Apptimate One ERP. Never fabricate non-existent menus, buttons, or workflows.\n"
                )
                user_prompt = f"User Question: {q}\n\n"
                if self.previous:
                    user_prompt += f"Recent Conversation Questions: {json.dumps(list(self.previous)[-5:])}\n\n"
                if item_check_block:
                    user_prompt += f"{item_check_block}\n\n"
                user_prompt += f"Verified Documentation Sections:\n{combined_context}"
                completion = client.chat.completions.create(
                    model=CHAT_MODEL,
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    reasoning_effort="none",
                )
                reply = (completion.choices[0].message.content or "").strip()
                if reply:
                    self.prompt_tokens += getattr(completion.usage, "prompt_tokens", 0) or 0
                    self.completion_tokens += getattr(completion.usage, "completion_tokens", 0) or 0
                    self.model_source = "provider"
                    self.model_name = CHAT_MODEL
                    self.parts.append(reply)
                    self.references = merged_refs
                    self.status = "answered"
                    if merged_refs:
                        self.evidence.append({"tool": "local_documentation", "result": {"section_count": len(merged_refs)}})
                    return True
            except Exception:
                pass

        if not context_parts:
            return False
        fallback_parts = []
        if paths:
            fallback_parts.append("Documented navigation path(s):\n" + "\n".join(f"- **{p}**" for p in paths[:5]))
        for block in context_parts[:3]:
            fallback_parts.append(block)
        self.parts.append("\n\n".join(fallback_parts))
        self.references = merged_refs
        self.status = "answered"
        self.evidence.append({"tool": "local_documentation", "result": {"section_count": len(merged_refs)}})
        return True

    def generic_answer(self):
        schema = query_service.get_business_schema_context(self.question, self.tenant, force=True, table_limit=24)
        if not schema:
            self.parts.append("Which business result or module do you mean? Include the item, report or metric you want checked.")
            self.status = "needs_clarification"
            self.evidence.append({"tool": "mcp:describe_tables", "result": {"tables": [], "business_rows_read": False}})
            return

        planning_question = self.question
        expanded_once = False
        allow_discovery = True
        successes = []
        seen = set()
        repaired = False
        unresolved = False
        proposed = {}
        for attempt in range(4):
            try:
                proposed = plan_question(
                    planning_question,
                    schema,
                    self.previous,
                    self.failures,
                    allow_discovery=allow_discovery,
                )
            except Exception:
                if successes:
                    unresolved = True
                    break
                self.parts.append("The query planner could not complete this request. No live result was verified.")
                self.status = "lookup_failed"
                self.evidence.append({"tool": "mcp:describe_tables", "result": {"error": "Planner error"}})
                return
            self.prompt_tokens += proposed.get("usage", {}).get("prompt_tokens", 0)
            self.completion_tokens += proposed.get("usage", {}).get("completion_tokens", 0)
            self.model_source = proposed.get("usage", {}).get("source", "provider")
            self.model_name = proposed.get("usage", {}).get("model", "")
            resolved_q = (proposed.get("resolved_question") or "").strip()
            if resolved_q:
                self.question = resolved_q
                planning_question = resolved_q
            if proposed.get("schema_tables"):
                current = re.findall(r"^- ([\w]+):", schema, re.M)
                if set(proposed["schema_tables"]) <= set(current):
                    self.failures.append(
                        "All requested tables are already fully described above. Produce the query plans now, or identify the exact absent field/verified relationship."
                    )
                    allow_discovery = False
                    continue
                try:
                    schema = query_service.expand_business_schema_context(
                        self.tenant, [*current, *proposed["schema_tables"]]
                    )
                    self.evidence.append(
                        {
                            "tool": "mcp:describe_tables",
                            "result": {"tables": proposed["schema_tables"], "business_rows_read": False},
                        }
                    )
                except (ValueError, PermissionError):
                    allow_discovery = False
                continue
            if not proposed.get("plans"):
                if successes:
                    break
                if attempt < 3 and not expanded_once and (proposed.get("clarification") or proposed.get("missing_capability")):
                    expanded = query_service.get_business_schema_context(
                        self.question, self.tenant, force=True, table_limit=36
                    )
                    expanded_once = True
                    if expanded and expanded != schema:
                        schema = expanded
                        continue
                if proposed.get("clarification"):
                    self.parts.append(proposed["clarification"])
                    self.status = "needs_clarification"
                    self.evidence.append({"tool": "mcp:describe_tables", "result": {"tables": proposed.get("schema_tables", []), "business_rows_read": False}})
                    return
                if proposed.get("missing_capability"):
                    self.parts.append("The discovered schema does not support this part: " + proposed["missing_capability"])
                    self.status = "unsupported"
                    self.evidence.append({"tool": "mcp:describe_tables", "result": {"tables": proposed.get("schema_tables", []), "business_rows_read": False}})
                    return
                break
            failed = False
            for plan in proposed.get("plans", [])[:4]:
                selected = plan.get("select", [])
                limit = plan.get("limit")
                if (
                    isinstance(limit, int)
                    and not isinstance(limit, bool)
                    and 0 < limit < 50
                    and not any(field.get("aggregate") for field in selected)
                    and not plan.get("group_by")
                    and not _has_requested_row_limit(self.question)
                ):
                    plan = {**plan, "limit": 50}
                fingerprint = json.dumps(plan, sort_keys=True, default=str)
                if fingerprint in seen:
                    if not any(key == fingerprint for key, _, _ in successes):
                        failed = True
                    continue
                seen.add(fingerprint)
                result = self.query(plan)
                if result.get("error"):
                    failed = True
                else:
                    successes.append((fingerprint, self.state["last_query"], result))
            unresolved = failed
            if failed and not repaired:
                targets = list(
                    dict.fromkeys(
                        table
                        for plan in proposed.get("plans", [])
                        for table in [plan.get("base_table"), *[j.get("table") for j in plan.get("joins", [])]]
                        if table
                    )
                )
                try:
                    schema = query_service.expand_business_schema_context(self.tenant, targets)
                except (ValueError, PermissionError):
                    pass
                schema += "\nSCHEMA CHECK: Recheck every referenced field against the complete columns above. Return valid plans for the current request; do not repeat unsupported fields."
                repaired = True
                allow_discovery = False
                continue
            unresolved = failed
            break
        if successes:
            # Companion check for inventory minimum stock / replenishment questions
            q_lower = (self.question or "").lower()
            is_min_stock_q = any(
                phrase in q_lower
                for phrase in [
                    "below minimum",
                    "lesser than minimum",
                    "less than minimum",
                    "minimum quantity",
                    "minimum stock",
                    "min quantity",
                    "min stock",
                    "min_stock_level",
                    "low stock",
                    "replenishment",
                    "reorder point",
                ]
            ) or any(
                "inventory_item_replenishment_rules" in str(p) for _, p, _ in successes
            )

            if is_min_stock_q:
                # 1. Check if total configured replenishment rules is known
                has_rules_count = any(
                    p.get("base_table") == "inventory_item_replenishment_rules" for _, p, _ in successes
                )
                if not has_rules_count:
                    try:
                        rules_cnt_plan = {
                            "base_table": "inventory_item_replenishment_rules",
                            "select": [
                                {
                                    "table": "inventory_item_replenishment_rules",
                                    "column": "id",
                                    "aggregate": "COUNT",
                                    "alias": "total_configured_rules",
                                }
                            ],
                        }
                        cnt_res = query_service.query_business_data(rules_cnt_plan, self.tenant)
                        if not cnt_res.get("error"):
                            successes.append(("auto_replenishment_rules_count", rules_cnt_plan, cnt_res))
                    except Exception:
                        pass

                # 2. Check if depleted / negative stock query was run
                has_depleted_query = any(
                    any(
                        h.get("alias") in ("qty_available", "stock_quantity", "quantity", "qty_on_hand")
                        and h.get("operator") in ("<=", "<")
                        and h.get("value") in (0, "0")
                        for h in (p.get("having") or [])
                    )
                    for _, p, _ in successes
                )
                if not has_depleted_query:
                    try:
                        depleted_plan = {
                            "base_table": "inventory_items",
                            "select": [
                                {"table": "inventory_items", "column": "id", "alias": "item_id"},
                                {"table": "inventory_items", "column": "sku", "alias": "sku"},
                                {"table": "inventory_items", "column": "name", "alias": "item_name"},
                                {
                                    "table": "inventory_stock_balances",
                                    "column": "qty_available",
                                    "aggregate": "SUM",
                                    "alias": "qty_available",
                                },
                                {
                                    "table": "inventory_stock_balances",
                                    "column": "qty_on_hand",
                                    "aggregate": "SUM",
                                    "alias": "qty_on_hand",
                                },
                            ],
                            "joins": [
                                {
                                    "table": "inventory_stock_balances",
                                    "left_table": "inventory_items",
                                    "left_column": "id",
                                    "right_column": "item_id",
                                    "type": "LEFT",
                                }
                            ],
                            "filters": [
                                {"table": "inventory_items", "column": "deleted_at", "operator": "IS NULL"},
                                {"table": "inventory_items", "column": "has_stocks", "operator": "=", "value": 1},
                            ],
                            "group_by": [
                                {"table": "inventory_items", "column": "id"},
                                {"table": "inventory_items", "column": "sku"},
                                {"table": "inventory_items", "column": "name"},
                            ],
                            "having": [{"alias": "qty_available", "operator": "<=", "value": 0}],
                            "order_by": [{"alias": "qty_available", "direction": "asc"}],
                            "limit": 50,
                        }
                        depleted_res = query_service.query_business_data(depleted_plan, self.tenant)
                        if not depleted_res.get("error"):
                            successes.append(("auto_depleted_stock_balances", depleted_plan, depleted_res))
                    except Exception:
                        pass

            joined_analysis = None
            if len(successes) > 1:
                joined_analysis = backend_join_and_analyze(successes, self.question)

            # Always synthesize with the LLM so the answer is shaped in user-friendly natural language
            if self.synthesize_query_results(successes, proposed, joined_analysis=joined_analysis):
                self.data_pages = []
                if unresolved:
                    self.parts.append(
                        "Some requested details could not be verified after checking the available schema."
                    )
                    self.status = "partial"
                return

            # Fallback if model call fails or is disabled
            self.data_pages = []
            if joined_analysis is not None:
                count = len(joined_analysis)
                summary = f"Found **{count} matching record(s)**." if count else "No matching records were found."
                table_md = table(joined_analysis) if count else "No matching records meet the requested condition."
                self.parts.append(summary + "\n\n" + table_md)
                return

            for _, plan, result in successes:
                self.render_query(result, "", plan)
            if unresolved:
                self.parts.append(
                    "Some requested details could not be verified after checking the available schema. The verified results are shown above; no missing values were treated as zero."
                )
                self.status = "partial"
            return
        self.parts.append(
            "I could not verify the requested records in the database with the available fields and relationships."
        )
        self.status = "unsupported"
        self.evidence.append({"tool": "mcp:describe_tables", "result": {"database": self.tenant, "verified": False}})

    def synthesize_query_results(self, successes, proposed, joined_analysis=None):
        if getattr(settings, "SUPPORT_DISABLE_MODEL_CALLS", False):
            return False
        try:
            datasets = []
            for _, plan, result in successes:
                datasets.append(
                    {
                        "table": plan.get("base_table"),
                        "row_count": result.get("row_count", len(result.get("results") or [])),
                        "filters": plan.get("filters", []),
                        "joins": plan.get("joins", []),
                        "truncated": bool(result.get("truncated")),
                        "rows": redact((result.get("results") or [])[:50]),
                    }
                )
            if joined_analysis is not None:
                datasets.append(
                    {
                        "table": "joined_and_calculated_results",
                        "row_count": len(joined_analysis),
                        "rows": joined_analysis[:50],
                    }
                )

            sys_prompt = (
                "You are Apptimate Assist, the intelligent AI Support & Analytics Assistant for Apptimate One ERP.\n"
                "Your job is to provide a user-friendly, shaped answer in clear natural language that business users can easily understand, based on the user's question and the verified live database query results.\n\n"
                "CRITICAL GUIDELINES:\n"
                "1. Natural, Conversational & Direct:\n"
                "   - For yes/no, status, or verification questions (e.g. checking whether an item has been sold, is available in stock, or an invoice has been paid):\n"
                "     Directly answer 'Yes' or 'No' in your opening sentence, followed by the specific details and context (e.g., item name, SKU, ID, active status in the inventory catalog, and whether matching transaction records were found in the database).\n"
                "   - If querying for sold items returned 0 records (or querying for unsold items returned the item), clearly state that the item has not been sold yet.\n"
                "   - For single-record lookups or counts, state the answer directly in natural language rather than just dumping a table.\n"
                "   - For listing or reporting requests (e.g. 'list down the items which are not sold yet', 'list down all the items with stock quantity lesser than their item master minimum quantity', 'list all suppliers whose balance is double their latest invoice'):\n"
                "     Give a helpful opening summary in natural language, followed ALWAYS by a clean Markdown table displaying all matching records from the results. Never withhold or omit the table.\n"
                "     Include all requested columns (e.g. Item Name, SKU, ID, Current Stock, Item Master Minimum Quantity).\n"
                "2. Professional & Clear Tone:\n"
                "   - Use bold for key names, SKUs, IDs, statuses, and amounts.\n"
                "   - Format numbers and currency values with comma separators.\n"
                "   - For item quantities and stock:\n"
                "     Always show a single clean numeric total quantity per item (e.g. 112).\n"
                "     Include Item Name, SKU, ID, and Total Quantity in the table.\n"
                "     If multiple rows exist for the same item across warehouses/batches, sum them into a single total; NEVER output a comma-separated list of individual numbers like '92, 15, 2, 3'.\n"
                "     If quantity is null or missing, show 0.\n"
                "   - Never expose technical SQL jargon (e.g. 'Checked scope:', 'deleted_at IS NULL', 'sales_order_lines.id IS NULL', or raw database joins).\n"
                "   - If no records match the criteria, clearly explain in plain English what was checked and what it means (e.g., 'No sales records were found for ...').\n"
                "   - Never invent records or numbers not present in the supplied datasets.\n"
                "3. Inventory Stock, Minimum Quantities & Replenishment Scenarios:\n"
                "   - Understand the real-world relationships between tables in Apptimate ERP:\n"
                "     * `inventory_items`: Catalog item definitions.\n"
                "     * `inventory_item_replenishment_rules`: Configured item replenishment thresholds (min_stock_level, reorder_point).\n"
                "     * `inventory_stock_balances`: Live physical stock balances across warehouses (qty_available, qty_on_hand).\n"
                "   - When asked 'which items are below minimum quantity', 'low stock items', 'reorder point', or replenishment:\n"
                "     * Scenario A: If items have configured minimum stock levels (`min_stock_level`) and stock is below that level, display those items in a Markdown table with Item Name, SKU, ID, Current Available Stock, and Minimum Quantity.\n"
                "     * Scenario B: If NO replenishment rules are configured in the system (`total_configured_rules` is 0 or no items have `min_stock_level` defined):\n"
                "       NEVER deceptively state 'No items are below minimum quantity' without explanation!\n"
                "       Clearly state that no Item Master minimum stock thresholds (`min_stock_level`) have been configured yet in replenishment rules.\n"
                "       Explain that in real-world inventory management, the baseline operational minimum is zero (0). Items with zero or negative stock are critically depleted (out of stock / oversold).\n"
                "       ALWAYS present a clean Markdown table of the items with depleted/negative stock from the query results, showing: Item Name, SKU, ID, Available Quantity, On Hand Quantity, and Configured Min Level (state 'Not Configured (0 baseline)').\n"
                "       Add a helpful recommendation advising the administrator to configure safety stock levels under Inventory > Item Master > Replenishment Rules.\n"
                "     * Scenario C: If both configured rule breaches and zero/negative stock items exist, explain both clearly."
            )
            user_prompt = f"User Question: {self.question}\n\nLive Database Query Results & Analytics:\n{json.dumps(datasets, default=str)}"
            if self.previous:
                user_prompt = f"Recent Conversation Questions: {list(self.previous)[-3:]}\n\n" + user_prompt

            completion = client.chat.completions.create(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                reasoning_effort="none",
            )
            reply = (completion.choices[0].message.content or "").strip()
            if reply:
                self.prompt_tokens += getattr(completion.usage, "prompt_tokens", 0) or 0
                self.completion_tokens += getattr(completion.usage, "completion_tokens", 0) or 0
                self.model_source = "provider"
                self.model_name = CHAT_MODEL
                self.parts.append(reply)
                self.status = "answered"
                self.data_pages = []
                return True
        except Exception:
            pass
        return False

    def payload(self):
        resolved = _trusted_query_records(self.evidence)
        if resolved:
            self.state["resolved_records"] = resolved
        basis = "Facts are rendered from verified database records; query scope, partial pages and limitations are shown. This is not a calibrated confidence probability."
        confidence = None
        confidence_type = "evidence"
        if self.status == "needs_clarification" and not self.evidence:
            basis = "Clarification is required before querying business records; no live business facts were returned for this response."
        elif self.status in {"unsupported", "lookup_failed"} and not self.evidence:
            basis = "The requested result was not retrieved; no live business query was executed and no business conclusion was verified."
        elif not self.evidence:
            basis = "No live business facts were needed or queried for this response."
            if self.status == "answered":
                confidence = 100.0
        elif all(item.get("tool") == "local_documentation" for item in self.evidence):
            basis = "Guidance and screen locations come from verified local documentation; no live transaction values were queried."
            if self.references:
                best_sim = max((float(r.get("similarity_score", 0.0)) for r in self.references), default=0.0)
                confidence = round(max(0.0, min(1.0, best_sim)) * 100.0, 1) if self.prompt_tokens else 100.0
                confidence_type = "model" if self.prompt_tokens else "evidence"
            else:
                confidence = 100.0
        elif self.status in {"answered", "partial"}:
            confidence = 100.0
        return {
            "response": "\n\n".join(self.parts),
            "answer_status": self.status,
            "tenant_database": self.tenant,
            "search_type": getattr(self, "search_type", "database"),
            "source_type": getattr(self, "search_type", "database"),
            "classification_reason": getattr(self, "classification_reason", ""),
            "confidence": confidence,
            "confidence_type": confidence_type,
            "confidence_basis": basis,
            "usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.prompt_tokens + self.completion_tokens,
                "source": self.model_source if self.prompt_tokens or self.completion_tokens else "not_used",
                "model": self.model_name,
            },
            "retrieved_references": self.references,
            "evidence": self.evidence,
            "principal": {"user_id": self.principal["user_id"], "tenant": self.tenant},
            "next_offset": self.state.get("next_offset"),
            "data_pages": self.data_pages,
        }
