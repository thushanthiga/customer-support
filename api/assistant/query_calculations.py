"""Small validated arithmetic and calendar predicates for business SELECTs."""
import re
from datetime import date, datetime, time, timedelta, timezone as utc_timezone
from decimal import Decimal
from django.utils import timezone


def normalize_timestamp(value,kind):
    """Convert explicit ISO offsets before binding MySQL timestamp values."""
    if kind not in {'datetime','timestamp'}:return value
    if isinstance(value,list):return [normalize_timestamp(x,kind) for x in value]
    if isinstance(value,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})',value):
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return parsed.astimezone(utc_timezone.utc).replace(tzinfo=None).isoformat(sep=' ')
    return value


def compile_arithmetic(expression, resolve_field, bind, depth=0):
    if depth > 4 or not isinstance(expression, dict) or not {"operator", "left", "right"} <= set(expression):
        raise ValueError("A calculation needs operator, left and right, with at most four nested operations.")
    raw_op = expression["operator"]
    operator = raw_op.upper() if isinstance(raw_op, str) else raw_op
    if operator not in {"+", "-", "*", "/", "GREATEST", "LEAST"}:
        raise ValueError("Calculated fields support +, -, *, /, GREATEST and LEAST only.")

    def operand(value):
        if isinstance(value, dict):
            # 1. Nested expression wrapped in 'expression'
            if "expression" in value and isinstance(value["expression"], dict):
                return compile_arithmetic(value["expression"], resolve_field, bind, depth + 1)
            # 2. Direct nested operation with operator, left, right
            if {"operator", "left", "right"} <= set(value):
                return compile_arithmetic(value, resolve_field, bind, depth + 1)
            # 3. Scalar container: {"value": 100} or {"value": {...}}
            if "value" in value and not ({"table", "column"} <= set(value)):
                return operand(value["value"])
            # 4. Table/column reference (with or without alias/coalesce) or alias reference
            if ({"table", "column"} <= set(value)) or "alias" in value or "column" in value:
                sql, kind = resolve_field(value)
                if kind not in {
                    "tinyint", "smallint", "mediumint", "int", "integer", "bigint",
                    "decimal", "numeric", "float", "double", "real", "bit"
                }:
                    raise ValueError("Calculation fields must be numeric.")
                return sql
            raise ValueError("Calculation operands must be verified table/column or alias references or finite numbers.")

        # 5. String numeric constants (e.g. "30" or "0.3")
        if isinstance(value, str):
            try:
                dec = Decimal(value)
                if dec.is_finite():
                    return bind(float(dec) if "." in value else int(dec))
            except Exception:
                pass

        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not Decimal(str(value)).is_finite():
            raise ValueError("Calculation constants must be finite numbers.")
        return bind(value)

    left, right = operand(expression["left"]), operand(expression["right"])
    if operator == "/":
        return f"({left} / NULLIF({right}, 0))"
    if operator in {"GREATEST", "LEAST"}:
        return f"{operator}({left}, {right})"
    return f"({left} {operator} {right})"


def calendar_predicate(expression,kind,operator,value,bind):
    """Interpret date-only timestamp filters as whole local calendar days."""
    if kind not in {'datetime','timestamp'}:return None
    def is_day(v):return isinstance(v,str) and bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}',v))
    def boundary(v,next_day=False):
        day=date.fromisoformat(v)+timedelta(days=int(next_day))
        local=timezone.make_aware(datetime.combine(day,time.min),timezone.get_current_timezone())
        return bind(local.astimezone(utc_timezone.utc).replace(tzinfo=None).isoformat(sep=' '))
    if operator=='BETWEEN' and isinstance(value,list) and len(value)==2 and all(is_day(v) for v in value):
        if value[0]>value[1]:raise ValueError('The start date must not be after the end date.')
        return f'({expression} >= {boundary(value[0])} AND {expression} < {boundary(value[1],True)})'
    if not is_day(value):return None
    if operator=='=':return f'({expression} >= {boundary(value)} AND {expression} < {boundary(value,True)})'
    if operator in {'!=','<>'}:return f'({expression} < {boundary(value)} OR {expression} >= {boundary(value,True)})'
    if operator=='>=':return f'{expression} >= {boundary(value)}'
    if operator=='>':return f'{expression} >= {boundary(value,True)}'
    if operator=='<=':return f'{expression} < {boundary(value,True)}'
    if operator=='<':return f'{expression} < {boundary(value)}'
    return None
