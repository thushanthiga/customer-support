"""GPT query planning and LLM intent/follow-up resolution for the business database."""
import json
import os

from django.conf import settings
from openai import OpenAI
from jsonschema import Draft202012Validator

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-6-luna")
client = OpenAI(api_key=OPENAI_API_KEY, timeout=45.0, max_retries=1)

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
        "filter_logic": {"enum": ["AND", "OR"]},
        "having_logic": {"enum": ["AND", "OR"]},
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
    "properties": {
        "intent": {"enum": ["records", "aggregate", "diagnose", "configure", "navigation", "acknowledgement"]},
        "resolved_question": {"type": "string", "minLength": 1},
        "analysis_contract": CONTRACT,
        "plans": {"type": "array", "maxItems": 4, "items": PLAN},
        "schema_tables": {"type": "array", "maxItems": 12, "items": {"type": "string"}},
        "clarification": {"type": "string"},
        "missing_capability": {"type": "string"},
    },
    "required": ["intent", "resolved_question", "analysis_contract", "plans"],
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
    def __init__(self, message, usage=None, *, retryable=True):
        super().__init__(message)
        self.usage = usage or {}
        self.retryable = retryable


def _parse_response(response, schema):
    message = response.choices[0].message
    if getattr(message, "refusal", None) or getattr(response.choices[0], "finish_reason", None) == "length":
        raise PlanningValidationError("The planning response was refused or incomplete; no plan is approved.")
    try:
        value = json.loads(message.content or "")
    except (TypeError, ValueError) as error:
        raise PlanningValidationError("The planning response must be a complete JSON object.") from error
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
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": instructions + "\nOUTPUT JSON SCHEMA:\n" + json.dumps(output)},
                {"role": "user", "content": json.dumps({**request, "available_schema": schema}, default=str)},
            ],
            response_format={"type": "json_object"},
            reasoning_effort=os.getenv("QUERY_REASONING_EFFORT", "medium"),
            max_completion_tokens=6000,
            store=False,
        )
        _add_usage(usage, response)
        proposal = _parse_response(response, output)
        validate_contract(proposal)
        if proposal["plans"]:
            # Separate context: the reviewer does not inherit the planner's conversation.
            review_response = client.chat.completions.create(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": QUERY_REVIEW_PROMPT + "\nAPPLICATION CLOCK: " + clock},
                    {"role": "user", "content": json.dumps({
                        "question": question, "previous_questions": list(history)[-5:],
                        "available_schema": schema, "candidate": proposal,
                    }, default=str)},
                ],
                response_format={"type": "json_schema", "json_schema": {"name": "query_review", "strict": True, "schema": REVIEW}},
                reasoning_effort=os.getenv("REVIEW_REASONING_EFFORT", "low"),
                max_completion_tokens=3000,
                store=False,
            )
            _add_usage(usage, review_response)
            review = _parse_response(review_response, REVIEW)
            if review["verdict"] == "clarify":
                if not review["clarification"].strip():
                    raise PlanningValidationError("The review requested clarification without a question.")
                proposal["plans"] = []
                proposal["clarification"] = review["clarification"]
                proposal["analysis_contract"]["ambiguities"] = review["issues"] or [review["clarification"]]
                for requirement in proposal["analysis_contract"]["requirements"]:
                    requirement.update(status="needs_clarification", plan_indexes=[], limitation=review["clarification"])
            elif review["verdict"] != "approve" or review["issues"] or review["clarification"]:
                raise PlanningValidationError("Semantic plan review rejected the candidate: " + "; ".join(review["issues"] or ["Approval was inconsistent; recheck the current request."]))
            proposal["query_review"] = review
        proposal["usage"] = usage
        return proposal
    except PlanningValidationError as error:
        error.usage = usage
        raise
    except Exception as error:
        # A failed review must never silently authorize an unchecked query.
        raise PlanningValidationError("Planning or query review was unavailable; no candidate was approved.", usage, retryable=False) from error
