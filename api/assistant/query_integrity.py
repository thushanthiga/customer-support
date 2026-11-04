"""Deterministic analytical invariants, independent of model approval or phrasing."""


def trusted_relationships(schema):
    """Only database constraints or explicitly configured application mappings execute."""
    return set(schema.get('declared_relationships', ())) | set(schema.get('application_relationships', ()))


def field_tables(field):
    if not isinstance(field, dict):
        return set()
    if 'table' in field:
        return {field['table']}
    expression = field.get('expression', field)
    return field_tables(expression.get('left')) | field_tables(expression.get('right'))


def validate_aggregate_grain(plan, schema, references):
    """Reject SUM/AVG/non-distinct COUNT when a join may multiply measure rows.

    Joins form a tree (each introduces a new reference). Starting from a measure's
    row source, every outgoing join must target a verified single-column unique
    key. Multiple expression inputs may share a common finer grain; at least one
    referenced source must preserve that grain through the full join tree.
    """
    graph = {reference: [] for reference in references}
    for join in plan.get('joins', []):
        left, right = join['left_table'], join.get('alias') or join['table']
        graph[left].append((right, join['right_column']))
        graph[right].append((left, join['left_column']))

    def unique(reference, column):
        return any(index.get('unique') is True and index.get('columns') == [column]
                   for index in schema.get('indexes', {}).get(references[reference], {}).values())

    def preserves(root):
        visited = {root}
        pending = [root]
        while pending:
            source = pending.pop()
            for target, target_column in graph[source]:
                if target in visited:
                    continue
                if not unique(target, target_column):
                    return False
                visited.add(target)
                pending.append(target)
        return True

    grains = {}
    for index, field in enumerate(plan.get('select', []), 1):
        aggregate = (field.get('aggregate') or '').upper()
        if aggregate not in {'SUM', 'AVG', 'COUNT'} or (aggregate == 'COUNT' and field.get('distinct')):
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
