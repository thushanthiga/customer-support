"""Authoritative Data Catalog Service for Apptimate One ERP.

Loads and slices the permanent ERP database catalog (uploads/apptimate_db_catalog.md)
so the query planner receives only the exact relevant tables, relationships,
and canonical analytical recipes for the user's specific query.
"""
import os
import re
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

CATALOG_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "uploads", "apptimate_db_catalog.md")

_CACHED_CATALOG: Optional[str] = None
_CACHED_SECTIONS: Dict[str, str] = {}


def invalidate_catalog_cache() -> None:
    """Invalidate in-memory cache to force reloading from disk."""
    global _CACHED_CATALOG, _CACHED_SECTIONS
    _CACHED_CATALOG = None
    _CACHED_SECTIONS = {}
    logger.info("[CATALOG_SERVICE] In-memory catalog cache invalidated.")


def _load_catalog() -> str:
    global _CACHED_CATALOG
    if _CACHED_CATALOG is None:
        try:
            with open(CATALOG_FILE_PATH, "r", encoding="utf-8") as f:
                _CACHED_CATALOG = f.read()
            logger.info("[CATALOG_SERVICE] Successfully loaded database catalog from %s (%d bytes)",
                        CATALOG_FILE_PATH, len(_CACHED_CATALOG))
        except Exception as exc:
            logger.error("[CATALOG_SERVICE] Failed to read catalog from %s: %s", CATALOG_FILE_PATH, exc)
            _CACHED_CATALOG = ""
    return _CACHED_CATALOG


def _parse_sections() -> Dict[str, str]:
    global _CACHED_SECTIONS
    if _CACHED_SECTIONS:
        return _CACHED_SECTIONS

    raw = _load_catalog()
    if not raw:
        return {}

    # Extract major sections using markdown header splitting
    pattern = r"(## \d+\. [^\n]+)"
    splits = re.split(pattern, raw)
    sections = {}
    current_key = "header"
    if splits:
        sections[current_key] = splits[0].strip()

    for i in range(1, len(splits), 2):
        header = splits[i].strip()
        body = splits[i + 1].strip() if i + 1 < len(splits) else ""
        content = f"{header}\n\n{body}"
        if "Inventory" in header:
            sections["inventory"] = content
        elif "Sales" in header:
            sections["sales"] = content
        elif "Procurement" in header:
            sections["procurement"] = content
        elif "Finance" in header:
            sections["finance"] = content
        elif "Core Master" in header:
            sections["core"] = content
        elif "Human Resources" in header:
            sections["hr"] = content
        elif "CRM" in header:
            sections["crm"] = content
        elif "Cross-Table Relationship Matrix" in header:
            sections["relationships"] = content
        elif "Canonical Analytical Recipes" in header:
            # Further split individual recipes
            sections["all_recipes"] = content
            recipe_splits = re.split(r"(### Recipe \d+:[^\n]+)", body)
            for j in range(1, len(recipe_splits), 2):
                rec_title = recipe_splits[j].strip()
                rec_body = recipe_splits[j + 1].strip() if j + 1 < len(recipe_splits) else ""
                rec_content = f"{rec_title}\n\n{rec_body}"
                if "Minimum Stock" in rec_title:
                    sections["recipe_min_stock"] = rec_content
                elif "Demand & Restocking" in rec_title:
                    sections["recipe_demand_restock"] = rec_content
                elif "Comparing Aggregate Balance" in rec_title or "Latest Record" in rec_title:
                    sections["recipe_cte_balance_latest"] = rec_content
                elif "Warehouse Stock vs Open" in rec_title:
                    sections["recipe_stock_vs_demand"] = rec_content

    _CACHED_SECTIONS = sections
    return _CACHED_SECTIONS


def _matches_any(text: str, keywords: List[str]) -> bool:
    """Return True if any keyword appears in text with whole-word matching for short acronyms."""
    for kw in keywords:
        if len(kw) <= 3:
            if re.search(r"\b" + re.escape(kw) + r"\b", text):
                return True
        else:
            if kw in text:
                return True
    return False


def get_catalog_slice(question: str) -> str:
    """Return a targeted Markdown slice containing only the relevant tables and recipes for question."""
    sections = _parse_sections()
    if not sections:
        return ""

    q_lower = (question or "").lower()
    selected = []

    # 1. Complex comparison keywords (CTE recipes)
    is_cte_comparison = any(term in q_lower for term in (
        "double", "twice", "triple", "times", "latest", "most recent", "more than",
        "greater than", "less than total", "exceed", "compared to"
    ))

    # 2. Domain matching
    # Finance / AP / Suppliers
    if _matches_any(q_lower, ["supplier", "vendor", "party", "bill", "invoice", "payable", "ap", "ar", "due"]):
        if "finance" in sections:
            selected.append(sections["finance"])
        if "core" in sections and sections["core"] not in selected:
            selected.append(sections["core"])
        if is_cte_comparison and "recipe_cte_balance_latest" in sections:
            selected.append(sections["recipe_cte_balance_latest"])

    # Customers / Receivables / AR
    if _matches_any(q_lower, ["customer", "client", "debtor"]):
        if "finance" in sections and sections["finance"] not in selected:
            selected.append(sections["finance"])
        if "core" in sections and sections["core"] not in selected:
            selected.append(sections["core"])

    # Inventory / Minimum / Replenishment / Stock
    if _matches_any(q_lower, ["stock", "inventory", "item", "product", "sku", "minimum", "min_stock", "replenish", "risk", "reorder"]):
        if "inventory" in sections and sections["inventory"] not in selected:
            selected.append(sections["inventory"])
        if _matches_any(q_lower, ["minimum", "min_stock", "replenish", "risk", "reorder", "lesser than", "threshold", "item master"]):
            if "recipe_min_stock" in sections:
                selected.append(sections["recipe_min_stock"])

    # Sales / Demand / Restocking / Velocity
    if _matches_any(q_lower, ["demand", "selling", "popular", "fast moving", "bestseller", "restock", "seasonal", "velocity"]):
        if "sales" in sections and sections["sales"] not in selected:
            selected.append(sections["sales"])
        if "inventory" in sections and sections["inventory"] not in selected:
            selected.append(sections["inventory"])
        if "recipe_demand_restock" in sections:
            selected.append(sections["recipe_demand_restock"])

    # Open demand / sales order backlog
    if _matches_any(q_lower, ["backlog", "unfulfilled", "open order", "open sales"]):
        if "sales" in sections and sections["sales"] not in selected:
            selected.append(sections["sales"])
        if "recipe_stock_vs_demand" in sections:
            selected.append(sections["recipe_stock_vs_demand"])

    # Procurement / Purchasing
    if _matches_any(q_lower, ["purchase order", "po", "grn", "goods receipt", "procurement", "requisition", "rfq"]):
        if "procurement" in sections:
            selected.append(sections["procurement"])
        if "core" in sections and sections["core"] not in selected:
            selected.append(sections["core"])

    # Human Resources & Payroll
    if _matches_any(q_lower, ["employee", "staff", "payroll", "salary", "attendance", "leave", "ot", "overtime", "designation"]):
        if "hr" in sections:
            selected.append(sections["hr"])
        if "core" in sections and sections["core"] not in selected:
            selected.append(sections["core"])

    # CRM & Pipeline
    if _matches_any(q_lower, ["lead", "crm", "pipeline", "opportunity", "quotation"]):
        if "crm" in sections:
            selected.append(sections["crm"])
        if "sales" in sections and sections["sales"] not in selected:
            selected.append(sections["sales"])

    if not selected:
        # Fallback for generic/open queries: include Core Entities + Inventory summary
        if "inventory" in sections:
            selected.append(sections["inventory"])
        if "sales" in sections:
            selected.append(sections["sales"])

    header_block = "### 📚 Domain Catalog & Verified Schema Rules\n"
    return header_block + "\n\n---\n\n".join(selected)

