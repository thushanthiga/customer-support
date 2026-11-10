"""GPT query planning and LLM intent/follow-up resolution for the business database."""
import json
import logging
import os
import re

from django.conf import settings
from openai import OpenAI
from jsonschema import Draft202012Validator

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini")
client = OpenAI(api_key=OPENAI_API_KEY, timeout=90.0, max_retries=2)

def _supports_reasoning_effort(model: str) -> bool:
    name = (model or "").lower()
    return any(k in name for k in ("o1", "o3", "o4", "reasoning"))

REFERENCE = {
    "type": "object",
    "properties": {
        "table": {"type": "string"},
        "column": {"type": "string"},
        "alias": {"type": "string"},
        "type": {"type": "string"},
        "data_type": {"type": "string"},
    },
    "required": ["table", "column"],
    "additionalProperties": False,
}
ALIAS_REF = {
    "type": "object",
    "properties": {
        "alias": {"type": "string"},
        "table": {"type": "string"},
        "column": {"type": "string"},
        "type": {"type": "string"},
        "data_type": {"type": "string"},
    },
    "required": ["alias"],
    "additionalProperties": False,
}

FILTER_OPERATORS = [
    "=",
    "!=",
    "<>",
    "<",
    "<=",
    ">",
    ">=",
    "LIKE",
    "IN",
    "NOT IN",
    "BETWEEN",
    "IS NULL",
    "IS NOT NULL",
]

_DEFS = {
    "reference": REFERENCE,
    "alias_ref": ALIAS_REF,
    "expression": {
        "type": "object",
        "properties": {
            "operator": {
                "enum": [
                    "+",
                    "-",
                    "*",
                    "/",
                    "%",
                    "GREATEST",
                    "LEAST",
                    "=",
                    "!=",
                    "<>",
                    "<",
                    "<=",
                    ">",
                    ">=",
                ]
            },
            "left": {
                "anyOf": [
                    {"$ref": "#/$defs/reference"},
                    {"$ref": "#/$defs/alias_ref"},
                    {"type": "number"},
                    {"type": "string"},
                    {"$ref": "#/$defs/expression"},
                    {
                        "type": "object",
                        "properties": {"expression": {"$ref": "#/$defs/expression"}, "alias": {"type": "string"}},
                        "required": ["expression"],
                        "additionalProperties": False,
                    },
                ]
            },
            "right": {
                "anyOf": [
                    {"$ref": "#/$defs/reference"},
                    {"$ref": "#/$defs/alias_ref"},
                    {"type": "number"},
                    {"type": "string"},
                    {"$ref": "#/$defs/expression"},
                    {
                        "type": "object",
                        "properties": {"expression": {"$ref": "#/$defs/expression"}, "alias": {"type": "string"}},
                        "required": ["expression"],
                        "additionalProperties": False,
                    },
                ]
            },
            "alias": {"type": "string"},
        },
        "required": ["operator", "left", "right"],
        "additionalProperties": False,
    },
    "filter_item": {
        "type": "object",
        "properties": {
            "table": {"type": "string"},
            "column": {"type": "string"},
            "expression": {"$ref": "#/$defs/expression"},
            "alias": {"type": "string"},
            "operator": {"enum": FILTER_OPERATORS},
            "value": {},
        },
        "required": ["operator"],
        "anyOf": [
            {"required": ["table", "column", "operator"]},
            {"required": ["expression", "operator"]},
            {"required": ["alias", "operator"]},
        ],
        "additionalProperties": False,
    },
    "case_when": {
        "type": "object",
        "properties": {
            "conditions": {"type": "array", "minItems": 1, "maxItems": 6, "items": {"$ref": "#/$defs/filter_item"}},
            "logic": {"enum": ["AND", "OR"]},
            "then": {"anyOf": [{"$ref": "#/$defs/reference"}, {"$ref": "#/$defs/expression"}, {"type": "number"}]},
            "else_value": {"anyOf": [{"$ref": "#/$defs/reference"}, {"$ref": "#/$defs/expression"}, {"type": "number"}, {"type": "null"}]},
        },
        "required": ["conditions"],
        "additionalProperties": False,
    },
    "window_order": {
        "type": "object",
        "properties": {
            "table": {"type": "string"},
            "column": {"type": "string"},
            "alias": {"type": "string"},
            "expression": {"$ref": "#/$defs/expression"},
            "direction": {"enum": ["asc", "desc"]},
        },
        "anyOf": [
            {"required": ["table", "column"]},
            {"required": ["column"]},
            {"required": ["alias"]},
            {"required": ["expression"]},
        ],
        "additionalProperties": False,
    },
    "window": {
        "type": "object",
        "properties": {
            "function": {
                "enum": [
                    "ROW_NUMBER",
                    "RANK",
                    "DENSE_RANK",
                    "SUM",
                    "AVG",
                    "MIN",
                    "MAX",
                    "COUNT",
                    "LAG",
                    "LEAD",
                ]
            },
            "partition_by": {"type": "array", "items": {"$ref": "#/$defs/reference"}, "maxItems": 6},
            "order_by": {"type": "array", "items": {"$ref": "#/$defs/window_order"}, "maxItems": 6},
        },
        "required": ["function"],
        "additionalProperties": False,
    },
    "field": {
        "type": "object",
        "properties": {
            "table": {"type": "string"},
            "column": {"type": "string"},
            "expression": {"$ref": "#/$defs/expression"},
            "case_when": {"$ref": "#/$defs/case_when"},
            "window": {"$ref": "#/$defs/window"},
            "alias": {"type": "string"},
            "aggregate": {"enum": ["", "COUNT", "SUM", "AVG", "MIN", "MAX"]},
            "distinct": {"type": "boolean"},
            "date_part": {"enum": ["day", "month", "year"]},
            "coalesce": {"type": "number"},
        },
        "anyOf": [
            {"required": ["table", "column"]},
            {"required": ["expression", "alias"]},
            {"required": ["case_when", "alias"]},
            {"required": ["window", "alias"]},
        ],
        "additionalProperties": False,
    },
    "join_item": {
        "type": "object",
        "properties": {
            "table": {"type": "string"},
            "alias": {"type": "string"},
            "left_table": {"type": "string"},
            "left_column": {"type": "string"},
            "right_column": {"type": "string"},
            "extra_on": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {
                        "left_table": {"type": "string"},
                        "left_column": {"type": "string"},
                        "right_column": {"type": "string"},
                    },
                    "required": ["left_column", "right_column"],
                    "additionalProperties": False,
                },
            },
            "type": {"enum": ["INNER", "LEFT"]},
        },
        "required": ["table", "left_table", "left_column", "right_column"],
        "additionalProperties": False,
    },
    "having_item": {
        "type": "object",
        "properties": {
            "alias": {"type": "string"},
            "expression": {"$ref": "#/$defs/expression"},
            "operator": {"enum": FILTER_OPERATORS},
            "value": {},
        },
        "required": ["operator"],
        "anyOf": [
            {"required": ["alias", "operator"]},
            {"required": ["expression", "operator"]},
        ],
        "additionalProperties": False,
    },
    "cte_block": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "base_table": {"type": "string"},
            "select": {"type": "array", "items": {"$ref": "#/$defs/field"}, "minItems": 1, "maxItems": 16},
            "joins": {"type": "array", "maxItems": 6, "items": {"$ref": "#/$defs/join_item"}},
            "filter_logic": {"enum": ["AND", "OR"]},
            "having_logic": {"enum": ["AND", "OR"]},
            "filters": {"type": "array", "items": {"$ref": "#/$defs/filter_item"}},
            "group_by": {"type": "array", "items": {"$ref": "#/$defs/field"}},
            "having": {"type": "array", "items": {"$ref": "#/$defs/having_item"}},
            "order_by": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"alias": {"type": "string"}, "direction": {"enum": ["asc", "desc"]}},
                    "required": ["alias"],
                    "additionalProperties": False,
                },
            },
            "limit": {"anyOf": [{"type": "integer", "minimum": 1, "maximum": 5000}, {"type": "null"}]},
            "offset": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]},
        },
        "required": ["name", "base_table", "select"],
        "additionalProperties": False,
    },
    "plan": {
        "type": "object",
        "properties": {
            "ctes": {"type": "array", "maxItems": 4, "items": {"$ref": "#/$defs/cte_block"}},
            "base_table": {"type": "string"},
            "select": {"type": "array", "items": {"$ref": "#/$defs/field"}, "minItems": 1, "maxItems": 16},
            "joins": {"type": "array", "maxItems": 6, "items": {"$ref": "#/$defs/join_item"}},
            "filter_logic": {"enum": ["AND", "OR"]},
            "having_logic": {"enum": ["AND", "OR"]},
            "filters": {"type": "array", "items": {"$ref": "#/$defs/filter_item"}},
            "group_by": {"type": "array", "items": {"$ref": "#/$defs/field"}},
            "having": {"type": "array", "items": {"$ref": "#/$defs/having_item"}},
            "order_by": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"alias": {"type": "string"}, "direction": {"enum": ["asc", "desc"]}},
                    "required": ["alias"],
                    "additionalProperties": False,
                },
            },
            "limit": {"anyOf": [{"type": "integer", "minimum": 1, "maximum": 500}, {"type": "null"}]},
            "offset": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]},
        },
        "required": ["base_table", "select"],
        "additionalProperties": False,
    },
}

EXPRESSION = _DEFS["expression"]
FILTER_ITEM = _DEFS["filter_item"]
CASE_WHEN = _DEFS["case_when"]
WINDOW_ORDER = _DEFS["window_order"]
WINDOW = _DEFS["window"]
FIELD = _DEFS["field"]
JOIN_ITEM = _DEFS["join_item"]
HAVING_ITEM = _DEFS["having_item"]
CTE_BLOCK = _DEFS["cte_block"]
PLAN = {"$defs": _DEFS, **_DEFS["plan"]}

REQUIREMENT = {
    "type": "object",
    "properties": {
        "requirement": {"type": "string", "minLength": 1},
        "status": {"enum": ["supported", "unsupported", "needs_clarification"]},
        "plan_indexes": {"type": "array", "items": {"type": "integer", "minimum": 0}, "uniqueItems": True},
        "limitation": {"type": "string"},
    },
    "required": ["requirement", "status", "plan_indexes", "limitation"],
    "additionalProperties": False,
}
CONTRACT = {
    "type": "object",
    "properties": {
        **{name: {"type": "string", "minLength": 1} for name in ("goal", "entity", "metric", "grain", "scope")},
        **{name: {"type": "array", "items": {"type": "string"}} for name in ("context_used", "assumptions", "ambiguities")},
        "requirements": {"type": "array", "minItems": 1, "items": REQUIREMENT},
    },
    "required": ["goal", "entity", "metric", "grain", "scope", "context_used", "assumptions", "ambiguities", "requirements"],
    "additionalProperties": False,
}
OUTPUT = {
    "type": "object",
    "$defs": _DEFS,
    "properties": {
        "intent": {"enum": ["records", "aggregate", "diagnose", "configure", "navigation", "acknowledgement"]},
        "resolved_question": {"type": "string", "minLength": 1},
        "analysis_contract": CONTRACT,
        "plans": {"type": "array", "maxItems": 4, "items": {"$ref": "#/$defs/plan"}},
        "schema_tables": {"type": "array", "maxItems": 12, "items": {"type": "string"}},
        "clarification": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "missing_capability": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["intent", "resolved_question", "analysis_contract"],
    "additionalProperties": False,
}
REVIEW = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "revise", "clarify"]},
        "issues": {"type": "array", "items": {"type": "string"}},
        "clarification": {"type": "string"},
    },
    "required": ["verdict", "issues", "clarification"],
    "additionalProperties": False,
}


class PlanningValidationError(ValueError):
    """A candidate failed structural or semantic checks; it must not execute."""
    def __init__(self, message, usage=None, *, retryable=True, candidate=None, review=None):
        super().__init__(message)
        self.usage = usage or {}
        self.retryable = retryable
        self.candidate = candidate
        self.review = review


def _normalize_expr_enums(expr, base_table=None):
    if not isinstance(expr, dict):
        return
    if isinstance(expr.get("expression"), dict):
        _normalize_expr_enums(expr["expression"], base_table)
    if isinstance(expr.get("operator"), str):
        raw_op = expr["operator"].upper()
        OP_SYNONYMS = {
            "MULTIPLY": "*",
            "MULTIPLICATION": "*",
            "TIMES": "*",
            "MUL": "*",
            "X": "*",
            "DIVIDE": "/",
            "DIVISION": "/",
            "DIV": "/",
            "ADD": "+",
            "PLUS": "+",
            "SUBTRACT": "-",
            "SUBTRACTION": "-",
            "MINUS": "-",
        }
        if raw_op in OP_SYNONYMS:
            expr["operator"] = OP_SYNONYMS[raw_op]
        elif raw_op in {"SUM", "COUNT", "AVG", "MIN", "MAX"}:
            left = expr.get("left")
            right = expr.get("right")
            if isinstance(left, dict) and isinstance(right, dict):
                col_l = str(left.get("column", "")).lower()
                col_r = str(right.get("column", "")).lower()
                if (("due" in col_l and "settle" in col_r) or ("total" in col_l and "paid" in col_r) or ("order" in col_l and "return" in col_r) or ("demand" in col_r)):
                    expr["operator"] = "-"
                else:
                    expr["operator"] = "+"
            else:
                expr["operator"] = "+"
        else:
            expr["operator"] = raw_op
    for side in ("left", "right"):
        val = expr.get(side)
        if isinstance(val, str):
            clean_str = val.strip()
            if clean_str.replace(".", "", 1).isdigit() or (clean_str.startswith("-") and clean_str[1:].replace(".", "", 1).isdigit()):
                expr[side] = float(clean_str) if "." in clean_str else int(clean_str)
        elif isinstance(val, dict):
            if "value" in val and not ({"table", "column"} <= set(val)):
                inner_v = val["value"]
                if isinstance(inner_v, str) and (inner_v.replace(".", "", 1).isdigit() or (inner_v.startswith("-") and inner_v[1:].replace(".", "", 1).isdigit())):
                    expr[side] = float(inner_v) if "." in inner_v else int(inner_v)
                else:
                    expr[side] = inner_v
            else:
                if base_table and val.get("column") and not val.get("table") and not val.get("alias"):
                    val["table"] = base_table
                _normalize_expr_enums(val, base_table)


def _normalize_block_enums(block):
    if not isinstance(block, dict):
        return

    # Handle window at the block level (often output by models for CTEs)
    if "window" in block and isinstance(block["window"], dict):
        win = block.pop("window")
        if not any(isinstance(s, dict) and "window" in s for s in block.get("select", [])):
            block.setdefault("select", []).append({
                "window": win,
                "alias": "rn",
            })

    # Remove any extraneous commentary keys on block level
    allowed_block_keys = {
        "name", "base_table", "select", "joins", "filter_logic", "having_logic",
        "filters", "group_by", "having", "order_by", "limit", "offset", "ctes"
    }
    for k in list(block.keys()):
        if k not in allowed_block_keys:
            block.pop(k, None)

    for logic_key in ("filter_logic", "having_logic"):
        val = block.get(logic_key)
        if isinstance(val, str) and val.strip().upper() in {"AND", "OR"}:
            block[logic_key] = val.strip().upper()
        else:
            block.pop(logic_key, None)
    for j in block.get("joins") or []:
        if isinstance(j, dict):
            allowed_join_keys = {"table", "alias", "left_table", "left_column", "right_column", "extra_on", "type"}
            for k in list(j.keys()):
                if k not in allowed_join_keys:
                    j.pop(k, None)
            if isinstance(j.get("type"), str):
                j["type"] = j["type"].upper()
    for idx, sel in enumerate((block.get("select") or []) + (block.get("group_by") or []), 1):
        if not isinstance(sel, dict):
            continue
        if {"operator", "left", "right"} <= set(sel) and "expression" not in sel:
            sel["expression"] = {
                "operator": sel.pop("operator"),
                "left": sel.pop("left"),
                "right": sel.pop("right"),
            }
        allowed_sel_keys = {"table", "column", "expression", "case_when", "window", "alias", "aggregate", "distinct", "date_part", "coalesce"}
        for k in list(sel.keys()):
            if k not in allowed_sel_keys:
                sel.pop(k, None)
        expr = sel.get("expression")
        if isinstance(expr, dict):
            raw_op = str(expr.get("operator") or expr.get("function") or "").upper()
            if raw_op in {"ROW_NUMBER", "RANK", "DENSE_RANK", "LAG", "LEAD"} or "partition_by" in expr or ("order_by" in expr and not any(k in expr for k in ("left", "right"))):
                sel["window"] = {
                    "function": raw_op if raw_op else "ROW_NUMBER",
                    "partition_by": expr.get("partition_by") or [],
                    "order_by": expr.get("order_by") or [],
                }
                sel.pop("expression", None)
            elif not ({"left", "right"} <= set(expr.keys())):
                # expr lacks binary left/right
                if "table" in expr or "column" in expr:
                    if expr.get("table") and not sel.get("table"):
                        sel["table"] = expr["table"]
                    if expr.get("column") and not sel.get("column"):
                        sel["column"] = expr["column"]
                    if raw_op in {"SUM", "COUNT", "AVG", "MIN", "MAX"} and not sel.get("aggregate"):
                        sel["aggregate"] = raw_op
                    sel.pop("expression", None)
                elif "alias" in expr and not sel.get("column"):
                    sel["column"] = expr["alias"]
                    sel.pop("expression", None)
                elif raw_op in {"SUM", "COUNT", "AVG", "MIN", "MAX"}:
                    if not sel.get("aggregate"):
                        sel["aggregate"] = raw_op
                    if "left" in expr and isinstance(expr["left"], dict):
                        if expr["left"].get("table"):
                            sel["table"] = expr["left"]["table"]
                        if expr["left"].get("column"):
                            sel["column"] = expr["left"]["column"]
                    sel.pop("expression", None)
            elif raw_op in {"SUM", "COUNT", "AVG", "MIN", "MAX"}:
                if not sel.get("aggregate"):
                    sel["aggregate"] = raw_op
                if "left" in expr and isinstance(expr["left"], dict):
                    if expr["left"].get("table") and not sel.get("table"):
                        sel["table"] = expr["left"]["table"]
                    if expr["left"].get("column") and not sel.get("column"):
                        sel["column"] = expr["left"]["column"]
                if raw_op == "COUNT" and sel.get("alias") in {"sales_frequency", "order_frequency"}:
                    sel["distinct"] = True
                if sel.get("table") or sel.get("column"):
                    sel.pop("expression", None)
        if isinstance(sel.get("aggregate"), str):
            sel["aggregate"] = sel["aggregate"].upper()
        if isinstance(sel.get("date_part"), str):
            sel["date_part"] = sel["date_part"].lower()
        if "expression" in sel:
            if not sel.get("alias"):
                sel["alias"] = f"calc_field_{idx}"
            sel.pop("table", None)
            sel.pop("column", None)
            _normalize_expr_enums(sel.get("expression"), block.get("base_table"))
        elif "case_when" in sel:
            if not sel.get("alias"):
                sel["alias"] = f"calc_field_{idx}"
            sel.pop("table", None)
            sel.pop("column", None)
        elif "window" in sel:
            if not sel.get("alias"):
                sel["alias"] = f"calc_field_{idx}"
            sel.pop("table", None)
            sel.pop("column", None)
        elif sel.get("column") and not sel.get("table") and block.get("base_table"):
            sel["table"] = block["base_table"]
        win = sel.get("window")
        if isinstance(win, dict):
            if isinstance(win.get("function"), str):
                win["function"] = win["function"].upper()
            for ob in win.get("order_by") or []:
                if isinstance(ob, dict):
                    if isinstance(ob.get("direction"), str):
                        ob["direction"] = ob["direction"].lower()
                    else:
                        ob["direction"] = "desc"
                    if ob.get("column") and not ob.get("table") and block.get("base_table"):
                        ob["table"] = block["base_table"]
                    if ob.get("alias") and not ob.get("column"):
                        ob["column"] = ob.pop("alias")
                        if not ob.get("table") and block.get("base_table"):
                            ob["table"] = block["base_table"]
                    _normalize_expr_enums(ob.get("expression"), block.get("base_table"))
        cw = sel.get("case_when")
        if isinstance(cw, dict):
            if isinstance(cw.get("logic"), str):
                cw["logic"] = cw["logic"].upper()
            _normalize_expr_enums(cw.get("then"), block.get("base_table"))
            _normalize_expr_enums(cw.get("else_value"), block.get("base_table"))
            for cond in cw.get("conditions") or []:
                if isinstance(cond, dict):
                    if isinstance(cond.get("operator"), str):
                        cond["operator"] = cond["operator"].upper()
                    _normalize_expr_enums(cond.get("expression"), block.get("base_table"))
                    _normalize_expr_enums(cond.get("value"), block.get("base_table"))
    base_t = block.get("base_table")
    selected_aliases = {
        s.get("alias"): s
        for s in (block.get("select") or [])
        if isinstance(s, dict) and s.get("alias")
    }

    # Normalize filters (WHERE)
    raw_filters = block.get("filters") or []
    normalized_filters = []
    for flt in raw_filters:
        if not isinstance(flt, dict):
            continue
        flt_alias = flt.get("alias") or flt.get("column")
        # If an aggregate or window alias was placed into filters, move it to having
        if flt_alias and flt_alias in selected_aliases:
            target_sel = selected_aliases[flt_alias]
            if target_sel.get("aggregate") or target_sel.get("window"):
                flt_copy = dict(flt)
                flt_copy["alias"] = flt_alias
                flt_copy.pop("table", None)
                flt_copy.pop("column", None)
                block.setdefault("having", []).append(flt_copy)
                continue

        # If model gave left/right on filter
        if "left" in flt and "value" not in flt:
            left_v = flt.pop("left")
            if "right" in flt:
                flt["value"] = flt.pop("right")
            if isinstance(left_v, dict):
                if {"operator", "left", "right"} <= set(left_v):
                    flt["expression"] = left_v
                elif left_v.get("column"):
                    flt["column"] = left_v["column"]
                    if left_v.get("table"):
                        flt["table"] = left_v["table"]
                elif left_v.get("alias"):
                    flt["alias"] = left_v["alias"]

        allowed_flt_keys = {"table", "column", "expression", "alias", "operator", "value"}
        for k in list(flt.keys()):
            if k not in allowed_flt_keys:
                flt.pop(k, None)
        f_expr = flt.get("expression")
        if isinstance(f_expr, dict) and not ({"operator", "left", "right"} <= set(f_expr.keys())):
            if "table" in f_expr or "column" in f_expr:
                if f_expr.get("table") and not flt.get("table"):
                    flt["table"] = f_expr["table"]
                if f_expr.get("column") and not flt.get("column"):
                    flt["column"] = f_expr["column"]
                flt.pop("expression", None)
            elif "alias" in f_expr and not flt.get("alias"):
                flt["alias"] = f_expr["alias"]
                flt.pop("expression", None)
            else:
                flt.pop("expression", None)
        if flt.get("column") and not flt.get("table") and not flt.get("expression") and base_t:
            flt["table"] = base_t
        if isinstance(flt.get("operator"), str):
            flt["operator"] = flt["operator"].upper()
        _normalize_expr_enums(flt.get("expression"), base_t)
        val = flt.get("value")
        if isinstance(val, dict):
            if "expression" in val and isinstance(val["expression"], dict):
                _normalize_expr_enums(val["expression"], base_t)
            elif {"operator", "left", "right"} <= set(val):
                _normalize_expr_enums(val, base_t)
            elif "value" in val and not ({"table", "column"} <= set(val)):
                flt["value"] = val["value"]
            else:
                _normalize_expr_enums(val, base_t)
        normalized_filters.append(flt)
    if "filters" in block:
        block["filters"] = normalized_filters

    # Normalize having (HAVING)
    raw_having = block.get("having") or []
    normalized_having = []
    for h in raw_having:
        if not isinstance(h, dict):
            continue
        # having_item schema strictly allows: alias, expression, operator, value
        if not h.get("alias") and h.get("column"):
            col_name = h.pop("column")
            if col_name in selected_aliases:
                h["alias"] = col_name
            else:
                matched = [s.get("alias") for s in (block.get("select") or []) if isinstance(s, dict) and s.get("column") == col_name and s.get("alias")]
                h["alias"] = matched[0] if matched else col_name
        h.pop("table", None)
        h.pop("column", None)

        allowed_having_keys = {"alias", "expression", "operator", "value"}
        for k in list(h.keys()):
            if k not in allowed_having_keys:
                h.pop(k, None)
        h_expr = h.get("expression")
        if isinstance(h_expr, dict) and not ({"operator", "left", "right"} <= set(h_expr.keys())):
            if h_expr.get("alias"):
                h["alias"] = h_expr["alias"]
                h.pop("expression", None)
            elif h_expr.get("column"):
                h["alias"] = h_expr["column"]
                h.pop("expression", None)
            else:
                h.pop("expression", None)
        if isinstance(h.get("operator"), str):
            h["operator"] = h["operator"].upper()
        _normalize_expr_enums(h.get("expression"), base_t)

        val = h.get("value")
        if isinstance(val, dict):
            if "column" in val and "alias" not in val:
                c_name = val["column"]
                if c_name in selected_aliases:
                    h["value"] = {"alias": c_name}
                else:
                    matched = [s.get("alias") for s in (block.get("select") or []) if isinstance(s, dict) and s.get("column") == c_name and s.get("alias")]
                    if matched:
                        h["value"] = {"alias": matched[0]}
            if "expression" in val and isinstance(val["expression"], dict):
                _normalize_expr_enums(val["expression"])
            elif {"operator", "left", "right"} <= set(val):
                _normalize_expr_enums(val)
            elif "value" in val and not ({"table", "column"} <= set(val)):
                h["value"] = val["value"]
            else:
                _normalize_expr_enums(val)
        normalized_having.append(h)
    if "having" in block:
        block["having"] = normalized_having
    for ob in block.get("order_by") or []:
        if isinstance(ob, dict):
            if not ob.get("alias") and ob.get("column"):
                ob["alias"] = ob.pop("column")
                ob.pop("table", None)
            allowed_ob_keys = {"alias", "direction"}
            for k in list(ob.keys()):
                if k not in allowed_ob_keys:
                    ob.pop(k, None)
            if isinstance(ob.get("direction"), str):
                ob["direction"] = ob["direction"].lower()
            else:
                ob["direction"] = "asc"
    for num_key in ("limit", "offset"):
        if num_key in block:
            if isinstance(block[num_key], str) and block[num_key].isdigit():
                block[num_key] = int(block[num_key])
            elif not isinstance(block[num_key], int):
                block.pop(num_key, None)


def _parse_response(response, schema, question=""):
    message = response.choices[0].message
    if getattr(message, "refusal", None) or getattr(response.choices[0], "finish_reason", None) == "length":
        raise PlanningValidationError("The planning response was refused or incomplete; no plan is approved.")
    try:
        value = json.loads(message.content or "")
    except (TypeError, ValueError) as error:
        raise PlanningValidationError("The planning response must be a complete JSON object.") from error

    # Case-insensitive normalization of enum values before strict schema validation
    if isinstance(value, dict):
        if schema is not REVIEW:
            for k in ("clarification", "missing_capability"):
                if k in value and value[k] is None:
                    value.pop(k, None)

        def _recover_base_table(blk):
            if not isinstance(blk, dict):
                return
            if not blk.get("base_table") and blk.get("table"):
                blk["base_table"] = blk.pop("table")
            if not blk.get("base_table"):
                for s in blk.get("select") or []:
                    if isinstance(s, dict) and s.get("table"):
                        blk["base_table"] = s["table"]
                        break
            if not blk.get("base_table"):
                for f in blk.get("filters") or []:
                    if isinstance(f, dict) and f.get("table"):
                        blk["base_table"] = f["table"]
                        break
            if not blk.get("base_table"):
                for j in blk.get("joins") or []:
                    if isinstance(j, dict) and j.get("left_table"):
                        blk["base_table"] = j["left_table"]
                        break
                    elif isinstance(j, dict) and j.get("table"):
                        blk["base_table"] = j["table"]
                        break
            if not blk.get("base_table"):
                blk["base_table"] = "inventory_items"

        if isinstance(value.get("plans"), list):
            q_lower = (question or "").lower()
            is_restock = bool(re.search(r"\b(?:restock|restore|replenish|enough stock|enough stocks|have stock|have stocks|hot selling|best selling|top selling|seasonal)\b", q_lower))

            if not is_restock and len(value["plans"]) > 1:
                named_ctes = [p for p in value["plans"] if isinstance(p, dict) and p.get("name")]
                if len(named_ctes) >= len(value["plans"]) - 1:
                    # All or all but one plans have a 'name' -> this is a multi-step CTE query
                    non_ctes = [p for p in value["plans"] if isinstance(p, dict) and not p.get("name")]
                    if non_ctes:
                        main_plan = non_ctes[-1]
                        ctes = [p for p in value["plans"] if p is not main_plan]
                    else:
                        main_plan = value["plans"][-1]
                        main_plan.pop("name", None)
                        ctes = value["plans"][:-1]
                    main_plan.setdefault("ctes", []).extend(ctes)
                    value["plans"] = [main_plan]

            if len(value["plans"]) == 1 and isinstance(value["plans"][0], dict) and value["plans"][0].get("ctes"):
                value.pop("schema_tables", None)
                for req in (value.get("analysis_contract", {}).get("requirements", [])):
                    if req.get("status") == "supported" and (not req.get("plan_indexes") or any(idx >= 1 for idx in req["plan_indexes"])):
                        req["plan_indexes"] = [0]

            for p in value["plans"]:
                if isinstance(p, dict):
                    _recover_base_table(p)
                    for cte in p.get("ctes") or []:
                        if isinstance(cte, dict):
                            _recover_base_table(cte)
                            _normalize_block_enums(cte)
                    _normalize_block_enums(p)

            if value.get("clarification") is None:
                value.pop("clarification", None)

    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        # Report shape and path, not an echoed model output or arbitrary business text.
        details = [f"{'.'.join(map(str, e.absolute_path)) or 'output'}: invalid {e.validator}" for e in errors[:5]]
        raise PlanningValidationError("Output contract validation failed: " + "; ".join(details))
    return value


def validate_contract(proposal):
    plans = proposal["plans"]
    contract = proposal["analysis_contract"]
    if proposal.get("schema_tables") and plans:
        raise PlanningValidationError("Schema discovery and executable plans must be separate steps.")
    if (contract["ambiguities"] or proposal.get("clarification")) and plans:
        raise PlanningValidationError("Resolve blocking ambiguity before executing a plan.")
    if proposal.get("schema_tables"):
        # Schema discovery is in flight; executable plans will be authored once tables are supplied.
        return
    covered = set()
    for requirement in contract["requirements"]:
        indexes = requirement["plan_indexes"]
        if any(index >= len(plans) for index in indexes):
            raise PlanningValidationError("A requirement references a nonexistent plan index.")
        if requirement["status"] == "supported":
            if not indexes:
                raise PlanningValidationError("Each supported requirement needs an executable evidence plan.")
            covered.update(indexes)
        elif indexes or not requirement["limitation"].strip():
            raise PlanningValidationError("Unresolved requirements need a limitation and no claimed evidence plans.")
    if covered != set(range(len(plans))):
        raise PlanningValidationError("Every executable plan must establish a supported requested requirement.")
    if not plans and not any(proposal.get(k) for k in ("clarification", "missing_capability", "schema_tables")):
        raise PlanningValidationError("A planless result must request clarification/discovery or state an unsupported capability.")
    if contract["ambiguities"] and not proposal.get("clarification"):
        raise PlanningValidationError("Unresolved ambiguity requires an actionable clarification.")


def _add_usage(total, response):
    usage = getattr(response, "usage", None)
    for name in ("prompt_tokens", "completion_tokens"):
        total[name] += getattr(usage, name, 0) or 0


def plan_question(question, schema, history=(), failures=(), *, allow_discovery=True):
    if getattr(settings, "SUPPORT_DISABLE_MODEL_CALLS", False):
        raise RuntimeError("Model calls are disabled for this verification run.")
    from django.utils import timezone
    from .prompts import ADMIN_QUERY_PROMPT, QUERY_REVIEW_PROMPT

    clock = timezone.localtime().isoformat() + "; timezone: " + settings.TIME_ZONE
    output = OUTPUT
    instructions = ADMIN_QUERY_PROMPT + "\nAPPLICATION CLOCK: " + clock
    if not allow_discovery:
        output = {**OUTPUT, "properties": {k: v for k, v in OUTPUT["properties"].items() if k != "schema_tables"}}
        instructions += "\nRequested schemas are supplied. Return supported plans or a precise clarification/missing_capability; do not request schema_tables again."
    request = {"question": question, "previous_questions": list(history)[-5:], "validation_feedback": list(failures)[-8:]}
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "source": "provider", "model": CHAT_MODEL}
    try:
        planner_kwargs = {
            "model": CHAT_MODEL,
            "messages": [
                {"role": "system", "content": instructions + "\nOUTPUT JSON SCHEMA:\n" + json.dumps(output)},
                {"role": "user", "content": json.dumps({**request, "available_schema": schema}, default=str)},
            ],
            "response_format": {"type": "json_object"},
            "max_completion_tokens": 6000,
            "store": False,
        }
        query_effort = os.getenv("QUERY_REASONING_EFFORT", "").strip().lower()
        if query_effort and query_effort not in {"none", "off", "false"} and _supports_reasoning_effort(CHAT_MODEL):
            planner_kwargs["reasoning_effort"] = query_effort
        logger.info("[PLANNER: LLM PROMPT SENT] Calling model=%s (allow_discovery=%s, failures_count=%d)",
                    CHAT_MODEL, allow_discovery, len(failures))
        response = client.chat.completions.create(**planner_kwargs)
        _add_usage(usage, response)
        proposal = _parse_response(response, output, question=question)
        logger.info("[PLANNER: LLM RAW RESPONSE] Tokens: prompt=%d, completion=%d. Plans count: %d, schema_tables: %s",
                    usage["prompt_tokens"], usage["completion_tokens"], len(proposal.get("plans", [])), proposal.get("schema_tables"))
        validate_contract(proposal)
        logger.info("[PLANNER: CONTRACT VALIDATED] Goal=%r, Metric=%r",
                    proposal["analysis_contract"].get("goal"), proposal["analysis_contract"].get("metric"))
        if proposal["plans"] or proposal.get("clarification"):
            # Also review question-only answers: unnecessary clarification is a
            # quality failure, just as a query for the wrong metric is.
            # Separate context: the reviewer does not inherit the planner's conversation.
            review_kwargs = {
                "model": CHAT_MODEL,
                "messages": [
                    {"role": "system", "content": QUERY_REVIEW_PROMPT + "\nAPPLICATION CLOCK: " + clock},
                    {"role": "user", "content": json.dumps({
                        "question": question, "previous_questions": list(history)[-5:],
                        "available_schema": schema, "candidate": proposal,
                    }, default=str)},
                ],
                "response_format": {"type": "json_schema", "json_schema": {"name": "query_review", "strict": True, "schema": REVIEW}},
                "max_completion_tokens": 3000,
                "store": False,
            }
            review_effort = os.getenv("REVIEW_REASONING_EFFORT", "").strip().lower()
            if review_effort and review_effort not in {"none", "off", "false"} and _supports_reasoning_effort(CHAT_MODEL):
                review_kwargs["reasoning_effort"] = review_effort
            logger.info("[REVIEWER: LLM SENT] Calling reviewer %s...", CHAT_MODEL)
            review_response = client.chat.completions.create(**review_kwargs)
            _add_usage(usage, review_response)
            review = _parse_response(review_response, REVIEW)
            clean_clarification = (review.get("clarification") or "").strip()
            if clean_clarification.lower() in {"none", "none.", "n/a", "null"}:
                clean_clarification = ""
            review["clarification"] = clean_clarification

            real_issues = [
                i for i in (review.get("issues") or [])
                if isinstance(i, str) and i.strip().lower() not in {"none", "none.", "n/a", "null", "no issues", "no issues found", "no issues.", "no issue"}
            ]
            review["issues"] = real_issues

            logger.info("[REVIEWER: VERDICT] Verdict=%s, issues=%s, clarification=%s",
                        review.get("verdict"), review.get("issues"), review.get("clarification"))
            if review["verdict"] == "clarify":
                if not review["clarification"]:
                    raise PlanningValidationError("The review requested clarification without a question.")
                proposal["plans"] = []
                proposal["clarification"] = review["clarification"]
                proposal["analysis_contract"]["ambiguities"] = review["issues"] or [review["clarification"]]
                for requirement in proposal["analysis_contract"]["requirements"]:
                    requirement.update(status="needs_clarification", plan_indexes=[], limitation=review["clarification"])
            elif review["verdict"] != "approve" or real_issues or clean_clarification:
                proposal["query_review"] = review
                proposal["usage"] = usage
                raise PlanningValidationError(
                    "Semantic plan review rejected the candidate: " + "; ".join(real_issues or ["Approval was inconsistent; recheck the current request."]),
                    usage,
                    candidate=proposal,
                    review=review,
                )
            proposal["query_review"] = review
        proposal["usage"] = usage
        return proposal
    except PlanningValidationError as error:
        error.usage = usage
        raise
    except Exception as error:
        import openai
        is_transient = isinstance(error, (openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError))
        logger.warning("[PLANNER: API EXCEPTION] %s: %s (transient=%s)", type(error).__name__, error, is_transient)
        # A failed review must never silently authorize an unchecked query.
        raise PlanningValidationError("Planning or query review was unavailable; no candidate was approved.", usage, retryable=is_transient) from error
