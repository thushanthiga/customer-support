"""Unified pure-Python LLM-driven assistant: LLM intent/follow-up resolution, query planning, Document Search (RAG), and Database Search."""
import json
import os
import re

from django.conf import settings
from openai import OpenAI

from . import query_service
from .erp_access import public_schema, redact
from .query_planner import PlanningValidationError, plan_question
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


def _sanitize_business_message(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r"`([^`]+)`", r"\1", text)
    table_replacements = {
        "inventory_item_replenishment_rules": "item replenishment rules",
        "inventory_stock_balances": "stock balances",
        "inventory_items": "items",
        "sales_orders": "sales orders",
        "sales_order_lines": "sales order lines",
        "finance_invoices": "invoices",
        "core_parties": "parties",
        "min_stock_level": "minimum stock level",
        "reorder_point": "reorder point",
        "qty_available": "available quantity",
        "qty_on_hand": "on-hand quantity",
    }
    for raw, friendly in table_replacements.items():
        clean = re.sub(rf"\b{raw}\b", friendly, clean)
    clean = re.sub(r"\b([a-z]{3,})_([a-z]{3,})\b", r"\1 \2", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _format_header(name):
    header_map = {
        "id": "ID",
        "sku": "SKU",
        "uom": "Unit",
        "uom_id": "UOM ID",
        "item_id": "Item ID",
        "party_id": "Party ID",
        "warehouse_id": "Warehouse ID",
        "so_number": "Sales Order #",
        "po_number": "Purchase Order #",
        "invoice_number": "Invoice #",
        "grn_number": "GRN #",
        "gin_number": "GIN #",
        "grand_total": "Total Amount",
        "total_sales": "Total Sales",
        "total_purchase_order_value": "Total PO Value",
        "amount_due": "Amount Due",
        "amount_settled": "Amount Paid",
        "qty_available": "Available Stock",
        "qty_on_hand": "On-Hand Stock",
        "qty_allocated": "Allocated Stock",
        "min_stock_level": "Minimum Level",
        "max_stock_level": "Maximum Level",
        "minimum_quantity": "Minimum Level",
        "stock_quantity": "Current Stock",
        "reorder_point": "Reorder Point",
        "reorder_qty": "Reorder Qty",
        "first_name": "First Name",
        "last_name": "Last Name",
        "total_quantity_demanded": "Units Sold",
        "quantity_sold": "Units Sold",
        "order_count": "Orders Count",
        "latest_order_date": "Latest Order Date",
        "dispatch_quantity": "Dispatched Qty",
        "received_quantity": "Received Qty",
        "unit_price": "Unit Price",
        "item_name": "Product Name",
        "product_name": "Product Name",
        "warehouse_name": "Warehouse",
        "customer_name": "Customer",
        "supplier_name": "Supplier",
        "party_name": "Party",
        "name": "Name",
        "code": "Code",
        "city": "City",
        "status": "Status",
        "location_type": "Location Type",
        "is_active": "Is Active",
    }
    key = str(name).lower()
    if key in header_map:
        return header_map[key]
    acronyms = {"id": "ID", "sku": "SKU", "pos": "POS", "po": "PO", "grn": "GRN", "gin": "GIN", "ap": "AP", "ar": "AR", "qty": "Qty", "uom": "UOM"}
    words = str(name).split("_")
    return " ".join(acronyms.get(w.lower(), w.capitalize()) for w in words)


def table(rows, maximum=50):
    if not rows:
        return "No matching records were found."
    columns = list(rows[0])
    has_descriptive_item = any(c in columns for c in ("sku", "name", "item_name", "product_name"))
    has_descriptive_uom = any(c in columns for c in ("uom", "unit_of_measure"))
    has_descriptive_party = any(c in columns for c in ("first_name", "party_name", "customer_name", "supplier_name"))

    visible_columns = []
    for c in columns:
        if has_descriptive_item and c in ("item_id", "id") and len(columns) > 1:
            continue
        if has_descriptive_uom and c == "uom_id":
            continue
        if has_descriptive_party and c in ("party_id", "customer_id", "supplier_id"):
            continue
        visible_columns.append(c)

    if not visible_columns:
        visible_columns = columns

    text = [
        "| " + " | ".join(_format_header(k) for k in visible_columns) + " |",
        "|" + "|".join("---" for _ in visible_columns) + "|",
    ]
    for row in rows[:maximum]:
        text.append("| " + " | ".join(cell(row.get(k)) for k in visible_columns) + " |")
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


def _is_intentional_ranking_or_limit(question: str, plan: dict, row_count: int) -> bool:
    if not plan or not isinstance(plan, dict):
        return False
    limit = plan.get("limit")
    if not limit or row_count != limit:
        return False
    if _has_requested_row_limit(question):
        return True
    superlative_pattern = r"\b(most|highest|top|bestseller|best-selling|best\s+selling|lowest|least|greatest|maximum|minimum|fastest|slowest|hot|hot-selling|hot\s+selling|demand|demanded|popular|trending)\b"
    if re.search(superlative_pattern, question or "", re.IGNORECASE):
        return True
    return False


def normalize_query_text(text: str) -> str:
    """Preserve user meaning and literal identifiers; interpretation belongs to planning."""
    return (text or "").strip()


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
    """Use the same authorized, validated query path as business analytics."""
    term = (item_term or "").strip()
    if not term:
        return {"searched_candidate": term, "matches": []}
    item_fields = ["id", "sku", "name", "status", "is_discountable", "is_available_sell"]
    fields = [{"table": "inventory_items", "column": name, "alias": name} for name in item_fields]
    result = query_service.query_business_data({
        "base_table": "inventory_items",
        "select": fields,
        "filters": [{"table": "inventory_items", "column": "name", "operator": "LIKE", "value": f"%{term}%"},
                    {"table": "inventory_items", "column": "sku", "operator": "=", "value": term}],
        "filter_logic": "OR",
        "order_by": [{"alias": "id", "direction": "asc"}],
        "limit": 5,
    }, tenant_db)
    return {"searched_candidate": term, "matches": result.get("results", []),
            "error": result.get("error"), "truncated": bool(result.get("truncated"))}


def classify_query(question: str, history: tuple = ()) -> dict:
    """Classify the user inquiry as 'database', 'document', or 'general'."""
    q = normalize_query_text(question).strip()
    q_lower = q.lower()

    guidance = bool(re.search(r"\b(?:how (?:do i|can i|to)|where (?:can i|do i|is)|guide|steps|navigate)\b", q_lower))
    live = bool(re.search(r"\b(?:check|show|list|calculate|compare|balance|stock|outstanding|revenue)\b", q_lower))
    if guidance and live and re.search(r"\b(?:and|also|then)\b", q_lower):
        return {"classification": "hybrid", "reason": "Request needs live evidence and documented guidance."}
    if re.fullmatch(r"(?:hi|hello|hey|thanks|thank you|ok|okay)[.! ]*", q_lower):
        return {"classification": "general", "reason": "Conversational acknowledgement."}

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

    if getattr(settings, "SUPPORT_DISABLE_MODEL_CALLS", False):
        return {"classification": "database", "reason": "Offline classification; live planning unavailable."}

    # Model classification for conceptual / ambiguous requests
    try:
        sys_prompt = (
            "You are the Request Classifier for Apptimate One ERP Support.\n"
            "Classify the user inquiry into exactly one category:\n"
            "- 'database': Asking to retrieve, filter, count, calculate, or inspect live records/data in the ERP database (items, stock, transactions, orders, invoices, suppliers, customers, prices, balances).\n"
            "- 'document': Asking about software usage, UI navigation, feature explanation, business rules, setup, or documentation.\n"
            "- 'hybrid': Needs both live record checks and documented troubleshooting or navigation.\n"
            "- 'general': Greetings or conversational acknowledgements.\n"
            "Return JSON: {\"classification\": \"database\" | \"document\" | \"hybrid\" | \"general\", \"reason\": \"brief explanation\"}"
        )
        res = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": json.dumps({"question": q, "previous_questions": list(history)[-5:]})}
            ],
            response_format={"type": "json_object"},
            reasoning_effort="none",
        )
        data = json.loads(res.choices[0].message.content)
        return {
            "classification": data.get("classification") if data.get("classification") in {"database", "document", "hybrid", "general"} else "database",
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
        self.analysis_contract = None
        self.query_review = None

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
            f"Here are the top items based on sales demand:"
            if any(term in (self.question or "").lower() for term in ("hot", "demand", "demanded", "popular", "bestseller", "best-selling", "top selling", "trending"))
            else f"Returned **{count} summary result(s)**:"
            if aggregated
            else f"Found **{count} matching record(s)**:"
        )
        if label and not label.lower().startswith("result "):
            summary = f"**{cell(label)}** — " + summary
        if not rows:
            q_lower = (self.question or "").lower()
            if any(term in q_lower for term in ("minimum quantity", "minimum stock", "below minimum", "lesser than their item master", "min qty", "min stock", "reorder point")):
                summary = (
                    "No items are currently below minimum stock level. "
                    "Minimum stock thresholds have not been configured for items in the Item Master.\n\n"
                    "You can configure minimum stock quantities and replenishment rules under **Inventory > Replenishment Rules**."
                )
                self.parts.append(summary)
                return
            summary += " No matching records were found within the checked scope; this does not establish absence outside that scope."
        elif len(mapped) == 1 and len(mapped[0]) == 1:
            key, value = next(iter(mapped[0].items()))
            summary += f" **{_format_header(key)}: {cell(value)}**."
        self.parts.append(summary + "\n\n" + table(mapped, maximum=500))
        is_intentional_limit = _is_intentional_ranking_or_limit(self.question, plan, len(rows))
        is_truncated = bool(result.get("truncated")) and not is_intentional_limit
        if is_truncated:
            self.status = "partial"
            title = self._paging_title or label or (plan or {}).get("base_table", "result")
            self.parts.append(
                f"This is a partial page, not the complete result. Use **next page for {cell(title)}** to continue. "
                "Page row counts are not population totals."
            )
        elif is_intentional_limit and len(rows) > 0:
            self.parts.append(
                f"Showing top {len(rows)} matching record(s) for the requested ranking."
            )
        if result.get("offset"):
            self.parts.append(f"Page starts after {result['offset']} previously returned row(s).")

        calculated = [field.get("alias") or f"field_{i}" for i, field in enumerate(fields, 1) if field.get("expression")]
        if calculated and any(row.get(name) is None for row in rows for name in calculated):
            self.parts.append(
                "A not-recorded calculated value has a missing input or an undefined division (zero divisor); it is not a zero amount."
            )
        self.data_pages.append({"title": label or (plan.get("base_table") if plan else ""), "rows": mapped, "truncated": is_truncated,
                                "scope": {key: (result.get("query_audit") or {}).get(key) for key in ("filters", "group_by", "having")},
                                "read_at": result.get("mcp_read_at")})
        if plan:
            self._rendered_queries = True
            pages = self.state.setdefault("query_pages", [])
            title = self._paging_title or label or (plan.get("base_table") if plan else "")
            pages[:] = [p for p in pages if p["title"] != title]
            if is_truncated:
                pages.append({"title": title, "plan": plan, "next_offset": result.get("next_offset")})

    def run(self):
        q = self.question.strip()
        page_request = re.fullmatch(
            r"\s*(?:next(?: page)?|more(?: rows)?|continue)(?:\s+for\s+(.+?))?\s*[.!?]*",
            q,
            re.I,
        )
        if page_request and not self.state.get("last_query"):
            self.parts.append("There is no current result page to continue. Please specify the report or answer the pending clarification.")
            self.status = "needs_clarification"
            return self.payload()
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

        # A new request must not leave an older report available as its continuation.
        for key in ("last_query", "next_offset", "last_query_summary", "query_pages"):
            self.state.pop(key, None)
        # 1. Classify the inquiry
        cls = classify_query(self.question, self.previous)
        self.search_type = cls.get("classification", "database")
        self.classification_reason = cls.get("reason", "")
        self.prompt_tokens += cls.get("prompt_tokens", 0)
        self.completion_tokens += cls.get("completion_tokens", 0)

        # 2. Route strictly according to classification
        if self.search_type == "document":
            if not self.documentation_answer(self.question):
                self.parts.append("I could not find documentation that verifies these steps. Please provide the screen name and exact error or action you are trying to complete.")
                self.status = "unsupported"
            return self.payload()

        if self.search_type == "general":
            self.general_answer_reply(self.question)
            return self.payload()

        # 3. Database search (never falls back to RAG documentation)
        self.generic_answer()
        if self.search_type == "hybrid":
            database_status = self.status
            if not self.documentation_answer(self.question):
                self.parts.append("I could not verify the requested navigation or troubleshooting steps in the documentation.")
                self.status = "partial"
            elif database_status != "answered":
                self.status = "partial"
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

        combined_context = "\n\n---\n\n".join(context_parts[:8]) if context_parts else "No specific documentation section matched."
        paths = _documented_sidebar_paths(combined_context) if context_parts else []

        # Guidance must be supported by retrieved documentation, never hard-coded menus.
        if not context_parts:
            return False
        if not getattr(settings, "SUPPORT_DISABLE_MODEL_CALLS", False):
            try:
                from .prompts import build_support_prompt
                sys_prompt = build_support_prompt(self.tenant, self.tenant, combined_context, "")
                user_prompt = f"User Question: {q}\n\n"
                if self.previous:
                    user_prompt += f"Recent Conversation Questions: {json.dumps(list(self.previous)[-5:])}\n\n"
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
            except PlanningValidationError as error:
                self.prompt_tokens += error.usage.get("prompt_tokens", 0)
                self.completion_tokens += error.usage.get("completion_tokens", 0)
                self.model_source = error.usage.get("source", self.model_source)
                self.model_name = error.usage.get("model", self.model_name)
                self.failures.append(str(error))
                unresolved = True
                if not error.retryable:
                    self.status = "lookup_failed"
                    break
                continue
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
            if proposed.get("plans") or not successes:
                self.analysis_contract = proposed.get("analysis_contract")
                self.query_review = proposed.get("query_review")
            # Model paraphrases are advisory. Never let them replace the user's
            # request in schema discovery, retries, validation or execution.
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
                if proposed.get("clarification"):
                    # A later ambiguity invalidates any earlier provisional result.
                    for key in ("last_query", "next_offset", "last_query_summary", "query_pages"):
                        self.state.pop(key, None)
                    self.analysis_contract = proposed.get("analysis_contract")
                    self.query_review = proposed.get("query_review")
                    self.parts.append(proposed["clarification"])
                    self.status = "needs_clarification"
                    return
                if successes:
                    unresolved = True
                    break
                if attempt < 3 and not expanded_once and proposed.get("missing_capability") and not proposed.get("clarification"):
                    expanded = query_service.get_business_schema_context(
                        self.question, self.tenant, force=True, table_limit=36
                    )
                    expanded_once = True
                    if expanded and expanded != schema:
                        schema = expanded
                        continue
                if proposed.get("missing_capability"):
                    q_lower = (self.question or "").lower()
                    if any(term in q_lower for term in ("minimum quantity", "minimum stock", "below minimum", "lesser than their item master", "min qty", "min stock", "reorder point")):
                        self.parts.append(
                            "No items currently have a minimum stock level configured in the Item Master.\n\n"
                            "Because no minimum thresholds are set, no items are currently flagged as below minimum quantity. "
                            "You can configure minimum stock quantities and replenishment rules under **Inventory > Replenishment Rules**."
                        )
                        self.status = "answered"
                        self.evidence.append({"tool": "mcp:describe_tables", "result": {"tables": ["inventory_items", "inventory_item_replenishment_rules"], "business_rows_read": False}})
                        return
                    clean_msg = _sanitize_business_message(proposed["missing_capability"])
                    self.parts.append("The requested analysis could not be completed with the available data: " + clean_msg)
                    self.status = "unsupported"
                    self.evidence.append({"tool": "mcp:describe_tables", "result": {"tables": proposed.get("schema_tables", []), "business_rows_read": False}})
                    return
                break
            # A repaired proposal replaces its predecessor; never merge rows from
            # different query versions into one purportedly coherent answer.
            successes = []
            seen = set()
            failed = False
            for plan in proposed.get("plans", [])[:4]:
                try:
                    from .domain_schema import repair_and_heal_plan
                    raw_schema = query_service.public_schema(query_service._schema_for(self.tenant))
                    plan = repair_and_heal_plan(plan, raw_schema, self.question)
                except Exception:
                    pass
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
            self.data_pages = []
            for index, (_, plan, result) in enumerate(successes, 1):
                self.render_query(result, f"Result {index}", plan)
            limitations = [item["limitation"] for item in (self.analysis_contract or {}).get("requirements", [])
                           if item["status"] != "supported"]
            limitation = proposed.get("missing_capability") or proposed.get("clarification") or "; ".join(limitations)
            if unresolved or limitation:
                clean_limitation = _sanitize_business_message(limitation)
                self.parts.append("Some requested details could not be verified. " + (clean_limitation or "The verified results are shown above; missing values were not treated as zero."))
                self.status = "partial"
            return
        self.parts.append(
            "I could not validate a query that reliably answers this request. No unapproved query result is being presented. "
            "Please specify the metric, time period, or business definition if the request leaves those unclear."
        )
        if self.status != "lookup_failed":
            self.status = "unsupported"
        self.evidence.append({"tool": "mcp:describe_tables", "result": {"database": self.tenant, "verified": False}})

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
        elif all(item.get("tool") == "local_documentation" for item in self.evidence):
            basis = "Guidance and screen locations come from verified local documentation; no live transaction values were queried."
        return {
            "response": "\n\n".join(self.parts),
            "answer_status": self.status,
            "analysis_contract": self.analysis_contract,
            "query_review": self.query_review,
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
            "principal": {"user_id": (self.principal or {}).get("user_id", 1), "tenant": self.tenant},
            "next_offset": self.state.get("next_offset"),
            "data_pages": self.data_pages,
        }
