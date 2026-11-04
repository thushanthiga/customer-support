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
    if depth>4 or not isinstance(expression,dict) or set(expression)!={'operator','left','right'}:
        raise ValueError('A calculation needs operator, left and right, with at most four nested operations.')
    operator=expression['operator']
    if operator not in {'+','-','*','/'}:
        raise ValueError('Calculated fields support addition, subtraction, multiplication and division only.')
    def operand(value):
        if isinstance(value,dict):
            if set(value)=={'expression'}:
                return compile_arithmetic(value['expression'],resolve_field,bind,depth+1)
            if set(value)!={'table','column'}:
                raise ValueError('Calculation operands must be verified table/column references or finite numbers.')
            sql,kind=resolve_field(value)
            if kind not in {'tinyint','smallint','mediumint','int','integer','bigint','decimal','numeric','float','double','real','bit'}:
                raise ValueError('Calculation fields must be numeric.')
            return sql
        if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not Decimal(str(value)).is_finite():
            raise ValueError('Calculation constants must be finite numbers.')
        return bind(value)
    left,right=operand(expression['left']),operand(expression['right'])
    if operator=='/':return f'({left} / NULLIF({right}, 0))'
    return f'({left} {operator} {right})'


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
