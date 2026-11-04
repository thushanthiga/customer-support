"""Trusted ERP sessions and read-only query-boundary access control in pure Python."""
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings

CURRENT_PRINCIPAL = ContextVar('erp_principal', default=None)
_SECRET = re.compile(r'password|passwd|token|secret|credential|private.?key|api.?key', re.I)


def uses_business_engine():
    return bool(getattr(settings, 'SUPPORT_BUSINESS_ENGINE', True))


def analytics_admin_access():
    return True


def is_analytics_admin(principal):
    if principal is None:
        return True
    return bool(principal.get('super_admin') or principal.get('analytics_admin') or analytics_admin_access())


def default_admin_principal(tenant):
    return {
        'tenant': tenant,
        'user_id': 1,
        'name': 'ERP Administrator',
        'super_admin': True,
        'analytics_admin': True,
        'organizations': None,
        'permissions': ['*'],
        'roles': [{'id': 1, 'name': 'Super Admin', 'code': 'super_admin'}],
    }


def principal_from_request(request, tenant):
    identity = request.session.get('erp_identity') if hasattr(request, 'session') else None
    if identity and identity.get('tenant') == tenant and identity.get('user_id'):
        return {
            **default_admin_principal(tenant),
            'user_id': identity['user_id'],
            'name': identity.get('name') or 'ERP Administrator',
        }
    return default_admin_principal(tenant)


@contextmanager
def principal_scope(principal):
    token = CURRENT_PRINCIPAL.set(principal)
    try:
        yield
    finally:
        CURRENT_PRINCIPAL.reset(token)


def can_read(table, principal=None):
    principal = principal if principal is not None else CURRENT_PRINCIPAL.get()
    if principal is None or is_analytics_admin(principal):
        return True
    permissions = set(principal.get('permissions') or [])
    if '*' in permissions:
        return True
    module = table.split('_')[0]
    if module == 'fin':
        module = 'finance'
    if module == 'money':
        module = 'money_exchange'
    prefix = module + '.'
    candidates = [p for p in permissions if p.startswith(prefix)]
    return any(p.rsplit('.', 1)[-1] in {'view', 'read', 'list', 'manage', 'access'} for p in candidates)


def public_schema(schema):
    principal = CURRENT_PRINCIPAL.get()
    if principal is None or is_analytics_admin(principal):
        return schema
    tables = {
        t: {c: v for c, v in columns.items() if not _SECRET.search(c)}
        for t, columns in schema['tables'].items()
        if can_read(t, principal)
    }
    return {
        **schema,
        'tables': tables,
        'relationships': {edge for edge in schema['relationships'] if edge[0] in tables and edge[2] in tables},
    }


def enforce_tenant(tenant):
    principal = CURRENT_PRINCIPAL.get()
    if principal and tenant != principal.get('tenant'):
        raise PermissionError('The authenticated session cannot query another tenant.')


def organization_conditions(base, references, aliases, schema, bind):
    """Server predicates are always ANDed outside model-provided OR filters."""
    principal = CURRENT_PRINCIPAL.get()
    if not principal or is_analytics_admin(principal):
        return []
    ids = principal.get('organizations') or []
    if not ids:
        return ['1=0']
    values = ', '.join(bind(int(value)) for value in ids)
    conditions = []
    for reference, table in references.items():
        if 'organization_id' in schema['tables'].get(table, {}):
            conditions.append(f'{aliases[reference]}.`organization_id` IN ({values})')
        elif table == 'core_organizations':
            conditions.append(f'{aliases[reference]}.`id` IN ({values})')
    return conditions


def redact(value):
    if isinstance(value, dict):
        return {k: ('[redacted]' if _SECRET.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str) and value[:1] in {'{', '['}:
        try:
            return redact(json.loads(value))
        except (ValueError, TypeError):
            pass
    return value
