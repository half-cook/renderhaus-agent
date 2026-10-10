"""Five neutral Gateway tools backed by local project storage and synthetic analysis."""
from __future__ import annotations

from providers.footage_memory import service
from providers.footage_memory.contracts import REQUESTS, request_for


def footage_memory_status(**arguments) -> dict:
    request = request_for('footage_memory_status', arguments)
    return service.fail_soft(lambda: service.status(request))


def footage_memory_build(**arguments) -> dict:
    request = request_for('footage_memory_build', arguments)
    return service.fail_soft(lambda: service.build(request))


def footage_memory_query(**arguments) -> dict:
    request = request_for('footage_memory_query', arguments)

    def query():
        with service.open_index(request) as index:
            return {'ok': True, 'status': 'ready', 'label': 'Find a moment',
                    'hits': index.query(request.query, request.scope, request.limit),
                    'simulated': True, 'training_eligible': False,
                    'message': 'Memory retrieves candidates. Verify each located segment before cutting.'}

    return service.fail_soft(query)


def footage_watch_answer(**arguments) -> dict:
    request = request_for('footage_watch_answer', arguments)
    return service.fail_soft(lambda: service.watch(request))


def footage_clip_extract(**arguments) -> dict:
    request = request_for('footage_clip_extract', arguments)
    return service.fail_soft(lambda: service.extract(request))


TOOL_HANDLERS = {fn.__name__: fn for fn in (footage_memory_status, footage_memory_build,
                                         footage_memory_query, footage_watch_answer, footage_clip_extract)}
GATEWAY_TOOLS = tuple(TOOL_HANDLERS)
DESCRIPTIONS = {
    'footage_memory_status': 'Footage memory. Check local clip duration, content hash, stale memory and whether to watch or build. Paths stay inside the current job. Free.',
    'footage_memory_build': 'Footage memory. Estimate first, then request approval for build with the exact plan_hash. One analysis call per 30-second window. All builds pause even autonomously. Dry-run creates synthetic memory; no footage is uploaded.',
    'footage_memory_query': 'Find a moment. Search existing project memory for timestamped candidates. Every hit requires a narrow Verify watch before extraction. Free local retrieval, never ground truth.',
    'footage_watch_answer': 'Verify. Watch one short clip or a narrow window with verify_hit_id. Returns timestamps and verified, refuted or ambiguous. Dry-run answers are simulated and cannot authorize a cut.',
    'footage_clip_extract': 'Footage memory. Extract verified hit_ids or explicit windows with handles through fixed local trims. Unverified selects are refused unless the caller explicitly sets allow_unverified=true. The skill must never use this override.',
}


def _schema(model) -> dict:
    raw = model.model_json_schema()
    definitions = raw.pop('$defs', {})

    def resolve(node):
        if isinstance(node, list):
            return [resolve(item) for item in node]
        if not isinstance(node, dict):
            return node
        if '$ref' in node:
            return resolve(definitions[node['$ref'].rsplit('/', 1)[-1]])
        return {key: resolve(value) for key, value in node.items()}

    return resolve(raw)


GATEWAY_SCHEMAS = [{'name': name, 'description': DESCRIPTIONS[name], 'inputSchema': _schema(REQUESTS[name])}
                   for name in GATEWAY_TOOLS]
