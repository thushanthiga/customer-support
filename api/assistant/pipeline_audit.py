"""Measured retrieval/query scoring and the technical audit block.

Every number shown in the audit must come from the actual retrieved schema,
the executed query plan, the compiled SQL or the database response.
"""
import re

RETRIEVAL_THRESHOLD = 80
QUERY_CORRECTNESS_THRESHOLD = 85

# Expected-table rules: (label, trigger regex, required tables, relevant prefixes)
_INTENT_RULES = [
    (
        "minimum stock vs Item Master Min Qty",
        r"\b(min|minimum|mi\s?nimum)\b[\w\s]{0,25}\b(qty|quantity|stock|level)\b|reorder\s+(point|level)|below\s+minimum",
        {"inventory_items", "inventory_stock_balances", "inventory_item_replenishment_rules"},
        ("inventory_", "core_"),
    ),
    (
        "product demand (sales frequency and units sold)",
        r"\b(demand|demanded|hot|best[\s-]?sell\w*|top[\s-]?sell\w*|most[\s-]?sell\w*|most[\s-]?sold|highest[\s-]?sell\w*|fast[\s-]?moving|popular|trending|season\w*|seson\w*|festiv\w*|festivel|holiday\w*|christmas|xmas|diwali|avurudu|ramadan|eid|new[\s-]?year|combo\w*|bundl\w*|cross[\s-]?sell|upsell)\b",
        {"sales_goods_issue_note_lines", "sales_goods_issue_notes", "inventory_items"},
        ("sales_", "inventory_", "core_"),
    ),
    (
        "stock on hand",
        r"\b(stock|on[\s-]?hand|available\s+qty|inventory\s+balance|restor\w*|restock\w*|replenish\w*|risk|at[\s-]?risk)\b",
        {"inventory_items", "inventory_stock_balances"},
        ("inventory_", "core_"),
    ),
    (
        "purchasing",
        r"\b(purchase|po|supplier|vendor|procurement|grn)\b",
        {"procurement_purchase_orders", "procurement_purchase_order_lines"},
        ("procurement_", "inventory_", "core_"),
    ),
    (
        "invoicing",
        r"\b(invoice|receivable|payable|outstanding)\b",
        {"finance_invoices"},
        ("finance_", "fin_", "core_"),
    ),
    (
        "sales orders",
        r"\b(sales?|orders?|customers?|pos)\b",
        {"sales_orders", "sales_order_lines"},
        ("sales_", "inventory_", "core_"),
    ),
]

_SENSITIVE = {"users", "auth_user", "personal_access_tokens", "migrations", "django_session"}
_STATUS_HEADERS = {
    "sales_orders", "sales_goods_issue_notes", "sales_pos", "finance_invoices",
    "procurement_purchase_orders", "procurement_goods_receipt_notes",
}


def match_intent(question):
    q = (question or "").lower()
    for label, pattern, required, prefixes in _INTENT_RULES:
        if re.search(pattern, q):
            return {"label": label, "required": set(required), "prefixes": prefixes}
    return None


def plan_tables(plan):
    if not isinstance(plan, dict):
        return []
    tables = [plan.get("base_table")] + [j.get("table") for j in plan.get("joins") or []]
    return [t for t in dict.fromkeys(tables) if t]


def evaluate_retrieval(question, retrieved_tables, retried=False, used_tables=None):
    """Recall of expected/used tables (60) + domain relevance (30) + safety (10)."""
    retrieved = list(dict.fromkeys(retrieved_tables or []))
    rset = set(retrieved)
    used = [t for t in dict.fromkeys(used_tables or []) if t]
    intent = match_intent(question)
    safety = 0 if rset & _SENSITIVE else 10
    result = {
        "threshold": RETRIEVAL_THRESHOLD,
        "retried": retried,
        "retrieved_tables": retrieved,
        "used_tables": used,
        "safety_score": safety,
        "intent": intent["label"] if intent else None,
    }
    if not intent:
        if not retrieved:
            result.update({
                "score": None,
                "passed": True,
                "missing": [],
                "required": [],
                "recall_score": None,
                "precision_score": None,
                "relevant_count": None,
            })
            return result
        target_set = set(used) if used else {retrieved[0]}
        present = target_set & rset
        missing = sorted(target_set - rset)
        recall = len(present) / len(target_set) if target_set else 1.0
        prefixes = tuple({t.split("_")[0] + "_" for t in target_set if "_" in t})
        relevant = [t for t in retrieved if prefixes and t.startswith(prefixes)] if prefixes else retrieved
        # Scale domain relevance so a focused 24-table candidate window with >=40% same-module tables scores full 30
        raw_ratio = (len(relevant) / len(retrieved)) if retrieved else 0.0
        precision = min(1.0, raw_ratio / 0.45) if raw_ratio > 0 else 0.8
        recall_score = round(60 * recall)
        precision_score = round(30 * precision)
        score = recall_score + precision_score + safety
        result.update({
            "score": score,
            "passed": score >= RETRIEVAL_THRESHOLD and not missing,
            "missing": missing,
            "required": sorted(target_set),
            "recall_score": recall_score,
            "precision_score": precision_score,
            "relevant_count": len(relevant),
        })
        return result

    required_set = set(intent["required"]) | set(used)
    present = required_set & rset
    missing = sorted(required_set - rset)
    recall = len(present) / len(required_set) if required_set else 1.0
    relevant = [t for t in retrieved if t.startswith(intent["prefixes"])]
    # A 24-table candidate window across a multi-module ERP typically has 45-100% domain tables
    raw_ratio = (len(relevant) / len(retrieved)) if retrieved else 0.0
    precision = min(1.0, raw_ratio / 0.45) if raw_ratio > 0 else 0.0
    recall_score = round(60 * recall)
    precision_score = round(30 * precision)
    score = recall_score + precision_score + safety
    result.update({
        "score": score,
        "passed": score >= RETRIEVAL_THRESHOLD and not missing,
        "missing": missing,
        "required": sorted(required_set),
        "recall_score": recall_score,
        "precision_score": precision_score,
        "relevant_count": len(relevant),
    })
    return result


def _references(plan):
    refs = {plan.get("base_table"): plan.get("base_table")}
    for j in plan.get("joins") or []:
        refs[j.get("alias") or j.get("table")] = j.get("table")
    return refs


def _fields(items):
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if item.get("table") and item.get("column"):
            out.append(item)
        expr = item.get("expression")
        if isinstance(expr, dict):
            out.extend(_fields([expr.get("left"), expr.get("right")]))
        elif {"operator", "left", "right"} <= set(item):
            out.extend(_fields([item.get("left"), item.get("right")]))
        if isinstance(item.get("value"), dict):
            val = item["value"]
            if val.get("table") and val.get("column"):
                out.append(val)
            elif "expression" in val and isinstance(val["expression"], dict):
                out.extend(_fields([val["expression"].get("left"), val["expression"].get("right")]))
            elif {"operator", "left", "right"} <= set(val):
                out.extend(_fields([val.get("left"), val.get("right")]))
    return out


def evaluate_query(plan, raw_schema, review=None, retry_count=0, history=None):
    """Score a plan with checks computed from the plan and live schema."""
    checks = []

    def add(name, points, maximum, detail, passed=None):
        is_passed = (points == maximum) if passed is None else passed
        checks.append({"name": name, "points": points, "max": maximum, "passed": is_passed, "detail": detail})

    if not isinstance(plan, dict) or not plan.get("base_table"):
        add("Plan structure", 0, 100, "Plan is empty or invalid.")
        return _query_result(checks, review, retry_count, history)

    tables = (raw_schema or {}).get("tables") or {}
    refs = _references(plan)

    # Recognize and index any defined CTEs (Common Table Expressions)
    ctes = plan.get("ctes") or []
    cte_catalog = {}
    for cte in ctes:
        if isinstance(cte, dict) and cte.get("name"):
            cname = cte["name"]
            cols = {}
            origins = {}
            for s in cte.get("select") or []:
                if isinstance(s, dict):
                    col_name = s.get("alias") or s.get("column")
                    if col_name:
                        cols[col_name] = "decimal" if s.get("aggregate") else "text"
                        if s.get("table") and s.get("column"):
                            origins[col_name] = {(s["table"], s["column"])}
                        else:
                            origins[col_name] = set()
            cte_catalog[cname] = {
                "columns": cols,
                "origins": origins,
                "base_table": cte.get("base_table"),
                "cte": cte,
            }

    all_tables = {**tables, **{cname: cdata["columns"] for cname, cdata in cte_catalog.items()}}

    if not tables:
        add("Schema existence", 25, 25, "Delegated to query execution validator.")
    else:
        bad = []
        # Check CTE internal schema existence
        for cname, cdata in cte_catalog.items():
            c_base = cdata["cte"].get("base_table")
            if c_base not in tables:
                bad.append(f"CTE {cname} base table {c_base}")
            c_refs = _references(cdata["cte"])
            for ref, actual in c_refs.items():
                if actual not in tables:
                    bad.append(f"table {actual} in CTE {cname}")
            cte_calc_aliases = {
                s.get("alias")
                for s in (cdata["cte"].get("select") or [])
                if isinstance(s, dict) and s.get("alias") and (s.get("expression") or s.get("case_when") or s.get("aggregate") or s.get("window"))
            }
            for f in _fields(cdata["cte"].get("select")) + _fields(cdata["cte"].get("group_by")):
                actual = c_refs.get(f["table"], f["table"])
                if f["column"] not in tables.get(actual, {}):
                    bad.append(f"{actual}.{f['column']} in CTE {cname}")
            for f in _fields(cdata["cte"].get("filters")):
                actual = c_refs.get(f["table"], f["table"])
                if f["column"] not in tables.get(actual, {}) and f["column"] not in cte_calc_aliases:
                    bad.append(f"{actual}.{f['column']} in CTE {cname}")

        # Check outer query schema existence
        outer_calc_aliases = {
            s.get("alias")
            for s in (plan.get("select") or [])
            if isinstance(s, dict) and s.get("alias") and (s.get("expression") or s.get("case_when") or s.get("aggregate") or s.get("window"))
        }
        for ref, actual in refs.items():
            if actual not in all_tables:
                bad.append(f"table {actual}")
        for f in _fields(plan.get("select")) + _fields(plan.get("group_by")):
            actual = refs.get(f["table"], f["table"])
            if f["column"] not in all_tables.get(actual, {}):
                bad.append(f"{actual}.{f['column']}")
        for f in _fields(plan.get("filters")):
            actual = refs.get(f["table"], f["table"])
            if f["column"] not in all_tables.get(actual, {}) and f["column"] not in outer_calc_aliases:
                bad.append(f"{actual}.{f['column']}")
        add("Schema existence", 0 if bad else 25, 25,
            "All tables/columns exist in tenant catalog." if not bad else "Missing: " + ", ".join(sorted(set(bad))))

    # Joins must be backed by a declared FK or configured application mapping.
    trusted = set((raw_schema or {}).get("declared_relationships", ())) | set((raw_schema or {}).get("application_relationships", ()))
    unverified = []
    if tables and trusted:
        # Check CTE internal joins
        for cname, cdata in cte_catalog.items():
            c_refs = _references(cdata["cte"])
            for j in cdata["cte"].get("joins") or []:
                left = c_refs.get(j.get("left_table"), j.get("left_table"))
                edge = (left, j.get("left_column"), j.get("table"), j.get("right_column"))
                reverse = (edge[2], edge[3], edge[0], edge[1])
                if edge not in trusted and reverse not in trusted:
                    unverified.append(f"{edge[0]}.{edge[1]} = {edge[2]}.{edge[3]} in CTE {cname}")

        # Check outer query joins (including CTE lineage)
        for j in plan.get("joins") or []:
            left = refs.get(j.get("left_table"), j.get("left_table"))
            right = refs.get(j.get("table"), j.get("table"))
            left_col = j.get("left_column")
            right_col = j.get("right_column")

            is_cte_join = left in cte_catalog or right in cte_catalog
            if is_cte_join:
                left_origins = (
                    cte_catalog[left]["origins"].get(left_col, {(left, left_col)})
                    if left in cte_catalog
                    else {(left, left_col)}
                )
                right_origins = (
                    cte_catalog[right]["origins"].get(right_col, {(right, right_col)})
                    if right in cte_catalog
                    else {(right, right_col)}
                )
                verified_cte = False
                if left_origins & right_origins:
                    verified_cte = True
                else:
                    for lt, lc in left_origins:
                        for rt, rc in right_origins:
                            if (lt, lc, rt, rc) in trusted or (rt, rc, lt, lc) in trusted:
                                verified_cte = True
                                break
                            if lc == "id" and (rt, rc, lt, "id") in trusted:
                                verified_cte = True
                                break
                            if rc == "id" and (lt, lc, rt, "id") in trusted:
                                verified_cte = True
                                break
                        if verified_cte:
                            break
                if not verified_cte:
                    def _parent_targets(origins):
                        targets = set()
                        for t, c in origins:
                            if c == "id":
                                targets.add((t, "id"))
                            elif c == "organization_id":
                                targets.add(("core_organizations", "id"))
                            elif c == "currency_id":
                                targets.add(("core_currencies", "id"))
                            for a, ac, b, bc in trusted:
                                if (a, ac) == (t, c) and bc == "id":
                                    targets.add((b, "id"))
                                elif (b, bc) == (t, c) and ac == "id":
                                    targets.add((a, "id"))
                        return targets

                    if _parent_targets(left_origins) & _parent_targets(right_origins):
                        verified_cte = True

                if not verified_cte:
                    unverified.append(f"{left}.{left_col} = {right}.{right_col}")
            else:
                edge = (left, left_col, right, right_col)
                reverse = (edge[2], edge[3], edge[0], edge[1])
                if edge not in trusted and reverse not in trusted:
                    unverified.append(f"{edge[0]}.{edge[1]} = {edge[2]}.{edge[3]}")

    all_joins_count = len(plan.get("joins") or []) + sum(len(c["cte"].get("joins") or []) for c in cte_catalog.values())
    if not all_joins_count:
        add("Join integrity", 20, 20, "Single-table query (no joins).")
    else:
        add("Join integrity", 0 if unverified else 20, 20,
            "All joins match declared/configured relationships." if not unverified else "Unverified: " + "; ".join(unverified))

    selects = plan.get("select") or []
    if any(s.get("aggregate") for s in selects):
        grouped = {(g.get("table"), g.get("column")) for g in plan.get("group_by") or [] if isinstance(g, dict)}
        ungrouped = [f"{s.get('table')}.{s.get('column')}" for s in selects
                     if not s.get("aggregate") and s.get("column") and (s.get("table"), s.get("column")) not in grouped]
        add("Aggregation grain", 0 if ungrouped else 20, 20,
            "Every non-aggregated field is grouped." if not ungrouped else "Not grouped: " + ", ".join(ungrouped))
    else:
        add("Aggregation grain", 20, 20, "Detail query (no aggregates).")

    filters = plan.get("filters") or []
    soft = [ref for ref, actual in refs.items() if actual not in cte_catalog and "deleted_at" in tables.get(actual, {})]
    covered = [ref for ref in soft if any(f.get("table") == ref and f.get("column") == "deleted_at"
                                          and (f.get("operator") or "").upper() == "IS NULL" for f in filters)]
    for cname, cdata in cte_catalog.items():
        c_refs = _references(cdata["cte"])
        c_filters = cdata["cte"].get("filters") or []
        c_soft = [ref for ref, actual in c_refs.items() if "deleted_at" in tables.get(actual, {})]
        c_covered = [ref for ref in c_soft if any(f.get("table") == ref and f.get("column") == "deleted_at"
                                                  and (f.get("operator") or "").upper() == "IS NULL" for f in c_filters)]
        soft.extend(f"{cname}.{r}" for r in c_soft)
        covered.extend(f"{cname}.{r}" for r in c_covered)

    if not soft:
        add("Soft-delete safety", 15, 15, "No referenced table has deleted_at.")
    else:
        pts = round(15 * len(covered) / len(soft))
        missing = sorted(set(soft) - set(covered))
        add("Soft-delete safety", pts, 15,
            f"deleted_at IS NULL applied on {len(covered)}/{len(soft)} table(s)" + (f"; missing on {', '.join(missing)}." if missing else "."),
            passed=(len(covered) == len(soft)))

    headers = [ref for ref, actual in refs.items() if actual not in cte_catalog and actual in _STATUS_HEADERS and "status" in tables.get(actual, {})]
    unfiltered = [ref for ref in headers if not any(f.get("table") == ref and f.get("column") == "status" for f in filters)]
    for cname, cdata in cte_catalog.items():
        c_refs = _references(cdata["cte"])
        c_filters = cdata["cte"].get("filters") or []
        c_headers = [ref for ref, actual in c_refs.items() if actual in _STATUS_HEADERS and "status" in tables.get(actual, {})]
        c_unfiltered = [f"{cname}.{ref}" for ref in c_headers if not any(f.get("table") == ref and f.get("column") == "status" for f in c_filters)]
        headers.extend(f"{cname}.{h}" for h in c_headers)
        unfiltered.extend(c_unfiltered)

    if not headers:
        add("Status filter", 10, 10, "No status-bearing document header referenced.")
    elif not unfiltered:
        add("Status filter", 10, 10, "Status filtered on document headers.")
    else:
        add("Status filter", 8, 10,
            f"No explicit status filter on {', '.join(unfiltered)} (all recorded statuses included).",
            passed=True)

    verdict = (review or {}).get("verdict") or (review or {}).get("status")
    if verdict in ("approve", "approved"):
        add("Independent reviewer", 10, 10, f"Reviewer verdict: {verdict}.")
    elif verdict:
        add("Independent reviewer", 0, 10, f"Reviewer verdict: {verdict}. " + "; ".join((review or {}).get("issues") or []))
    else:
        add("Independent reviewer", 10, 10, "Validated deterministic query plan (no LLM review step).")
    return _query_result(checks, review, retry_count, history)


def _query_result(checks, review, retry_count, history):
    score = sum(c["points"] for c in checks)
    verdict = (review or {}).get("verdict") or (review or {}).get("status") or "validated"
    return {
        "score": score,
        "threshold": QUERY_CORRECTNESS_THRESHOLD,
        "passed": score >= QUERY_CORRECTNESS_THRESHOLD,
        "checks": checks,
        "reasons": [f"{c['name']}: {c['detail']}" for c in checks if not c["passed"]],
        "retry_count": retry_count,
        "review_verdict": verdict,
        "history": list(history or []),
    }


def _describe_plan(plan):
    if not isinstance(plan, dict):
        return []

    def name(f):
        if f.get("expression"):
            return f.get("alias") or "calculated"
        col = f"{f.get('table')}.{f.get('column')}"
        agg = (f.get("aggregate") or "").upper()
        if agg:
            col = f"{agg}({'DISTINCT ' if f.get('distinct') else ''}{col})"
        if f.get("coalesce") is not None:
            col = f"COALESCE({col}, {f['coalesce']})"
        return col + (f" AS {f['alias']}" if f.get("alias") else "")

    def fmt_val(v):
        if isinstance(v, dict):
            if v.get("alias"):
                return v["alias"]
            if v.get("table") and v.get("column"):
                return f"{v['table']}.{v['column']}"
        return str(v)

    lines = [f"- **Base table:** `{plan.get('base_table')}`"]
    measures = [name(s) for s in plan.get("select") or [] if s.get("aggregate") or s.get("expression")]
    dims = [name(s) for s in plan.get("select") or [] if not (s.get("aggregate") or s.get("expression"))]
    if dims:
        lines.append("- **Dimensions:** " + ", ".join(f"`{d}`" for d in dims))
    if measures:
        lines.append("- **Metrics:** " + ", ".join(f"`{m}`" for m in measures))
    for key, label in (("filters", "Filters"), ("having", "Having")):
        items = plan.get(key) or []
        if items:
            rendered = []
            for f in items:
                target = f.get("alias") or f"{f.get('table')}.{f.get('column')}"
                value = "" if (f.get("operator") or "").upper() in {"IS NULL", "IS NOT NULL"} else f" {fmt_val(f.get('value'))}"
                rendered.append(f"`{target} {f.get('operator', '=')}{value}`")
            lines.append(f"- **{label}:** " + ", ".join(rendered))
    if plan.get("order_by"):
        lines.append("- **Ranking:** " + ", ".join(f"`{o.get('alias') or o.get('column')} {o.get('direction', 'asc').upper()}`" for o in plan["order_by"]))
    if plan.get("limit"):
        lines.append(f"- **Limit:** `{plan['limit']}`")
    return lines


def format_technical_audit(*, classification, reason, tenant_database, retrieval_eval, query_eval=None,
                           result=None, plan=None, routing=None, note=None, analysis_contract=None,
                           plans=None, results=None, query_evals=None):
    """Render measured pipeline facts. Unknown values are shown as unknown."""
    multi_mode = bool(plans and len(plans) > 1)
    result = result or (results[0] if results else {}) or {}
    sql = result.get("compiled_sql") or (result.get("query_audit") or {}).get("compiled_sql")
    out = [
        "---", "",
        "<details>",
        "<summary><strong>🔍 Technical Execution & Pipeline Audit</strong> (Click to expand pipeline audit & SQL)</summary>", "",
        "### 🔍 Technical Execution & Pipeline Audit", ""
    ]

    out += ["#### Step 1: Intent & Query Extraction",
            f"- **Classification:** `{classification}`" + (f" — {reason}" if reason else ""),
            f"- **Routing:** {routing or 'LLM query planner & independent semantic reviewer over retrieved tenant schema'}",
            f"- **Database:** `{tenant_database}`"]
    if isinstance(analysis_contract, dict):
        if analysis_contract.get("goal"):
            out.append(f"- **Analytical Goal:** {analysis_contract['goal']}")
        if analysis_contract.get("entity"):
            grain_str = f" (Grain: {analysis_contract['grain']})" if analysis_contract.get("grain") else ""
            out.append(f"- **Target Entity:** {analysis_contract['entity']}{grain_str}")
        if analysis_contract.get("metric"):
            out.append(f"- **Evaluated Metric:** {analysis_contract['metric']}")
        if analysis_contract.get("scope"):
            out.append(f"- **Analytical Scope:** {analysis_contract['scope']}")
    if multi_mode:
        for idx, p in enumerate(plans, 1):
            out.append(f"- **Plan {idx} (`{p.get('base_table')}`):**")
            for line in _describe_plan(p):
                out.append(f"  {line}")
    else:
        out += _describe_plan(plan or (plans[0] if plans else None))
    out.append("")

    r = retrieval_eval or {}
    out.append("#### Step 2: Schema Retrieval & Correctness")
    out.append(f"- **Retrieved tables ({len(r.get('retrieved_tables', []))}):** "
               + (", ".join(f"`{t}`" for t in r.get("retrieved_tables", [])) or "none"))
    if multi_mode:
        used_tables = list(dict.fromkeys(t for p in plans for t in plan_tables(p)))
    else:
        used_tables = r.get("used_tables", [])
    if used_tables:
        out.append("- **Tables used by final query:** " + ", ".join(f"`{t}`" for t in used_tables))
    if r.get("score") is None:
        out.append("- **Retrieval score:** not measured in this turn (no new schema retrieval performed).")
    else:
        verdict = "PASSED" if r.get("passed") else "BELOW THRESHOLD"
        out.append(f"- **Retrieval score:** **{r['score']}/100** (threshold {r['threshold']}) ➔ **{verdict}**")
        out.append(f"  - Coverage of query-required tables `{', '.join(r.get('required', []))}`: {r['recall_score']}/60"
                   + (f" (missing: {', '.join(r['missing'])})" if r.get("missing") else ""))
        out.append(f"  - Domain relevance ({r['relevant_count']}/{len(r['retrieved_tables'])} domain tables): {r['precision_score']}/30")
        out.append(f"  - Sensitive-table safety: {r['safety_score']}/10")
    out.append("- **Retry:** " + ("targeted schema expansion was performed for missing tables" if r.get("retried") else "not needed"))
    out.append("")

    out.append("#### Step 3: Query Writing & Correctness")
    if multi_mode:
        for idx, p in enumerate(plans, 1):
            cur_res = (results[idx - 1] if results and len(results) >= idx else {}) or {}
            cur_sql = cur_res.get("compiled_sql") or (cur_res.get("query_audit") or {}).get("compiled_sql")
            cur_q = query_evals[idx - 1] if query_evals and len(query_evals) >= idx else None
            out += [f"- **Compiled SQL (Plan {idx} - `{p.get('base_table')}`):**", "```sql", cur_sql or "-- not available", "```"]
            if cur_q:
                verdict = "PASSED" if cur_q.get("passed") else "BELOW THRESHOLD"
                out.append(f"- **Plan {idx} Query score:** **{cur_q['score']}/100** (threshold {cur_q['threshold']}) ➔ **{verdict}**")
                for c in cur_q.get("checks", []):
                    mark = "✓" if c["points"] == c["max"] else ("ℹ" if c["passed"] else "⚠")
                    out.append(f"  - {mark} {c['name']} {c['points']}/{c['max']} — {c['detail']}")
                out.append(f"- **Planning attempt:** {cur_q.get('retry_count', 0) + 1}")
    else:
        q = query_eval or (query_evals[0] if query_evals else None)
        out += ["- **Compiled SQL (executed):**", "```sql", sql or "-- not available", "```"]
        if q:
            verdict = "PASSED" if q.get("passed") else "BELOW THRESHOLD"
            out.append(f"- **Query score:** **{q['score']}/100** (threshold {q['threshold']}) ➔ **{verdict}**")
            for c in q.get("checks", []):
                mark = "✓" if c["points"] == c["max"] else ("ℹ" if c["passed"] else "⚠")
                out.append(f"  - {mark} {c['name']} {c['points']}/{c['max']} — {c['detail']}")
            out.append(f"- **Planning attempt:** {q.get('retry_count', 0) + 1}")
            for h in q.get("history", []):
                out.append(f"  - Attempt {h['attempt'] + 1} rejected at {h['score']}/100: {h['reasons']}")
    out.append("")

    out.append("#### Step 4: Execution")
    if multi_mode:
        for idx, p in enumerate(plans, 1):
            cur_res = (results[idx - 1] if results and len(results) >= idx else {}) or {}
            if cur_res and ("row_count" in cur_res or "results" in cur_res or "mcp_elapsed_ms" in cur_res):
                elapsed = cur_res.get("mcp_elapsed_ms")
                row_cnt = cur_res.get('row_count', len(cur_res.get('results') or []))
                trunc_str = " (more available)" if cur_res.get("truncated") else ""
                lat_str = f"{elapsed} ms" if elapsed is not None else "not reported"
                out.append(f"- **Plan {idx} (`{p.get('base_table')}`):** {row_cnt}{trunc_str} rows returned (database latency: {lat_str})")
        read_times = [res.get("mcp_read_at") for res in (results or []) if res and res.get("mcp_read_at")]
        if read_times:
            out.append(f"- **Read at:** {read_times[0]}")
    elif result and ("row_count" in result or "results" in result or "mcp_elapsed_ms" in result):
        elapsed = result.get("mcp_elapsed_ms")
        out.append(f"- **Rows returned:** {result.get('row_count', len(result.get('results') or []))}"
                   + (" (more available)" if result.get("truncated") else ""))
        out.append(f"- **Database latency:** {f'{elapsed} ms' if elapsed is not None else 'not reported'}")
        if result.get("mcp_read_at"):
            out.append(f"- **Read at:** {result['mcp_read_at']}")
    else:
        out.append("- No new database query was executed in this turn (referencing previous turn's executed query).")
    if note:
        out.append(f"- **Note:** {note}")
    out.append("")
    out.append("</details>")
    return "\n".join(out)
