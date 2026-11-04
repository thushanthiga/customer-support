"""GPT query planning and LLM intent/follow-up resolution for the business database."""
import json
import os

from django.conf import settings
from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-6-luna")
client = OpenAI(api_key=OPENAI_API_KEY)

REFERENCE = {
    "type": "object",
    "properties": {"table": {"type": "string"}, "column": {"type": "string"}},
    "required": ["table", "column"],
    "additionalProperties": False,
}
EXPRESSION = {
    "type": "object",
    "properties": {
        "operator": {"enum": ["+", "-", "*", "/"]},
        "left": {"anyOf": [REFERENCE, {"type": "number"}]},
        "right": {"anyOf": [REFERENCE, {"type": "number"}]},
    },
    "required": ["operator", "left", "right"],
    "additionalProperties": False,
}
FIELD = {
    "type": "object",
    "properties": {
        "table": {"type": "string"},
        "column": {"type": "string"},
        "expression": EXPRESSION,
        "alias": {"type": "string"},
        "aggregate": {"enum": ["", "COUNT", "SUM", "AVG", "MIN", "MAX"]},
        "distinct": {"type": "boolean"},
        "date_part": {"enum": ["day", "month", "year"]},
        "coalesce": {"type": "number"},
    },
    "anyOf": [{"required": ["table", "column"]}, {"required": ["expression", "alias"]}],
    "additionalProperties": False,
}
PLAN = {
    "type": "object",
    "properties": {
        "base_table": {"type": "string"},
        "select": {"type": "array", "items": FIELD, "minItems": 1, "maxItems": 12},
        "joins": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "alias": {"type": "string"},
                    "left_table": {"type": "string"},
                    "left_column": {"type": "string"},
                    "right_column": {"type": "string"},
                    "type": {"enum": ["INNER", "LEFT"]},
                },
                "required": ["table", "left_table", "left_column", "right_column"],
                "additionalProperties": False,
            },
        },
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "column": {"type": "string"},
                    "operator": {
                        "enum": [
                            "=",
                            "!=",
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
                    },
                    "value": {},
                },
                "required": ["table", "column", "operator"],
                "additionalProperties": False,
            },
        },
        "group_by": {"type": "array", "items": FIELD},
        "having": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "alias": {"type": "string"},
                    "operator": {"enum": ["=", "!=", "<", "<=", ">", ">=", "BETWEEN"]},
                    "value": {},
                },
                "required": ["alias", "operator", "value"],
                "additionalProperties": False,
            },
        },
        "order_by": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"alias": {"type": "string"}, "direction": {"enum": ["asc", "desc"]}},
                "required": ["alias"],
            },
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
        "offset": {"type": "integer", "minimum": 0},
    },
    "required": ["base_table", "select"],
    "additionalProperties": False,
}
OUTPUT = {
    "type": "object",
    "properties": {
        "intent": {"enum": ["records", "aggregate", "diagnose", "configure", "navigation", "acknowledgement"]},
        "resolved_question": {"type": "string"},
        "plans": {"type": "array", "maxItems": 4, "items": PLAN},
        "schema_tables": {"type": "array", "maxItems": 12, "items": {"type": "string"}},
        "clarification": {"type": "string"},
        "missing_capability": {"type": "string"},
    },
    "required": ["intent", "resolved_question", "plans"],
    "additionalProperties": False,
}


def plan_question(question, schema, history=(), failures=(), *, allow_discovery=True):
    if getattr(settings, "SUPPORT_DISABLE_MODEL_CALLS", False):
        raise RuntimeError("Model calls are disabled for this verification run.")
    from django.utils import timezone
    from .prompts import ADMIN_QUERY_PROMPT

    instructions = (
        ADMIN_QUERY_PROMPT
        + "\nAlways return `resolved_question` with spelling/typos corrected across ALL words and any conversational follow-up resolved from `previous_questions`."
        + "\nAPPLICATION CLOCK: "
        + timezone.localtime().isoformat()
        + "; timezone: "
        + settings.TIME_ZONE
    )
    output = OUTPUT
    if not allow_discovery:
        output = {**OUTPUT, "properties": {k: v for k, v in OUTPUT["properties"].items() if k != "schema_tables"}}
        instructions += "\nThe requested table schemas have now been supplied. Return plans for their supported fields, or a precise clarification/missing_capability. Do not request schema_tables in this planning step."
    messages = [
        {"role": "system", "content": instructions + "\nAVAILABLE SCHEMA:\n" + schema + "\nOUTPUT JSON SCHEMA:\n" + json.dumps(output)},
        {"role": "user", "content": json.dumps({"question": question, "previous_questions": list(history)[-5:]}, default=str)},
    ]
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        reasoning_effort="none",
        max_completion_tokens=2500,
        store=False,
    )
    result = json.loads(response.choices[0].message.content)
    if not isinstance(result, dict) or not isinstance(result.get("plans"), list):
        raise ValueError("The planner must return an object containing a plans array.")
    usage = response.usage
    result["usage"] = {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
        "source": "provider",
        "model": CHAT_MODEL,
    }
    return result
