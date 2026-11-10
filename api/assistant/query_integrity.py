"""Deterministic analytical invariants, independent of model approval or phrasing."""


def trusted_relationships(schema):
    """Only database constraints or explicitly configured application mappings execute."""
    return set(schema.get('declared_relationships', ())) | set(schema.get('application_relationships', ()))


def field_tables(field):
    if not isinstance(field, dict):
        return set()
    found = set()
    if field.get('table'):
        found.add(field['table'])
    expression = field.get('expression')
    if isinstance(expression, dict):
        found |= field_tables(expression)
    if 'left' in field or 'right' in field:
        found |= field_tables(field.get('left')) | field_tables(field.get('right'))
    cw = field.get('case_when')
    if isinstance(cw, dict):
        for cond in cw.get('conditions') or []:
            found |= field_tables(cond)
            if isinstance(cond, dict):
                found |= field_tables(cond.get('value'))
        found |= field_tables(cw.get('then')) | field_tables(cw.get('else_value'))
    return found


def validate_aggregate_grain(plan, schema, references):
    """Reject SUM/AVG/non-distinct COUNT when a join may multiply measure rows.

    Joins form a tree (each introduces a new reference). Starting from a measure's
    row source, every outgoing join must target a verified unique key (single-column
    or composite key fully satisfied by join columns and AND-scoped equality filters).
    Multiple expression inputs may share a common finer grain; at least one
    referenced source must preserve that grain through the full join tree.
    """
    graph = {reference: [] for reference in references}
    for join in plan.get('joins', []):
        left, right = join['left_table'], join.get('alias') or join['table']
        extra = [x for x in (join.get('extra_on') or []) if isinstance(x, dict)]
        right_cols = {join['right_column']} | {
            x['right_column'] for x in extra if x.get('right_column')
        }
        left_cols = {join['left_column']} | {
            x['left_column'] for x in extra
            if x.get('left_column') and x.get('left_table', left) == left
        }
        graph[left].append((right, right_cols))
        graph[right].append((left, left_cols))

    is_and_filters = (plan.get('filter_logic') or 'AND').upper() == 'AND'

    def unique(reference, joined_cols):
        table_name = references.get(reference)
        table_indexes = schema.get('indexes', {}).get(table_name, {}).values()
        # 1. Unique index fully covered by the join columns (e.g. PRIMARY KEY id or composite CTE key)
        if any(
            index.get('unique') is True
            and index.get('columns')
            and set(index.get('columns')) <= joined_cols
            for index in table_indexes
        ):
            return True

        # 2. Composite unique index where remaining key columns are constrained by AND-filters/scope
        constrained_cols = set()
        if is_and_filters:
            ref_filters = [
                f for f in plan.get('filters', [])
                if isinstance(f, dict) and f.get('table') == reference
            ]
            constrained_cols = {
                f.get('column') for f in ref_filters
                if f.get('column')
                and (f.get('operator') or '').upper() in ('=', 'IS', 'IS NULL')
            }
        if 'organization_id' in schema.get('tables', {}).get(table_name, {}):
            constrained_cols.add('organization_id')

        for index in table_indexes:
            if index.get('unique') is True:
                cols = index.get('columns', [])
                if cols and (joined_cols & set(cols)):
                    remaining = set(cols) - joined_cols
                    if remaining <= constrained_cols:
                        return True
        return False

    def preserves(root):
        visited = {root}
        pending = [root]
        while pending:
            source = pending.pop()
            for target, target_cols in graph[source]:
                if target in visited:
                    continue
                if not unique(target, target_cols):
                    return False
                visited.add(target)
                pending.append(target)
        return True

    grains = {}
    for index, field in enumerate(plan.get('select', []), 1):
        aggregate = (field.get('aggregate') or '').upper()
        win_func = ((field.get('window') or {}).get('function') or '').upper()
        check_agg = aggregate or (win_func if win_func in {'SUM', 'AVG', 'COUNT'} else '')
        if check_agg not in {'SUM', 'AVG', 'COUNT'} or (check_agg == 'COUNT' and field.get('distinct')):
            continue
        roots = field_tables(field) or {plan['base_table']}
        safe_roots = sorted(root for root in roots if root in graph and preserves(root))
        alias = field.get('alias') or f'field_{index}'
        if not safe_roots:
            raise ValueError(
                f'Aggregate {alias} may double-count or bias source rows through a non-unique or '
                'unverified join. Aggregate at the measure source without fan-out; use COUNT DISTINCT '
                'for unique-entity counts. Do not repair SUM by making amounts DISTINCT.'
            )
        grains[alias] = safe_roots[0]
    return grains
