"""Read-only review explanation; never hold a DB connection during an AI call."""
from rentwise.api.errors import ApiError
from rentwise.db.database import get_db_engine
from rentwise.engine.explain import OpenAIPlanExplainer, facts_for, render
from rentwise.engine_registry import get_engine
from rentwise.services import ai_ledger, plans


def explain_plan(plan_id, expected_plan_revision, base_state_revision, input_hash):
    def read_current():
        with get_db_engine().connect() as conn:
            view = plans.plan_view(conn, plan_id)
        if (view['status'] != 'READY' or view['revision'] != expected_plan_revision
                or view['base_state_revision'] != base_state_revision
                or view['current_state_revision'] != base_state_revision or view['input_hash'] != input_hash):
            raise ApiError(409,'STALE_EXPLANATION','변경안이 바뀌었습니다. 최신 변경안을 다시 계산해 주세요.',retryable=True)
        return view
    view = read_current()
    engine = get_engine()
    result = (engine.explain_plan(view) if hasattr(engine,'explain_plan')
        else OpenAIPlanExplainer(client=None).explain(view))
    ai_ledger.record_call(view.get('request_id'),engine.mode,result)
    if not result.payload:
        raise ApiError(422,'EXPLANATION_INPUT_INVALID','변경안 정보를 확인해 주세요.')
    current = read_current()  # Discard an explanation if another action happened during AI latency.
    if render(current,facts_for(current))['evidence_hash'] != result.payload['evidence_hash']:
        raise ApiError(409,'STALE_EXPLANATION','변경안이 바뀌었습니다. 최신 변경안을 다시 계산해 주세요.',retryable=True)
    return {'status':'OK' if result.status=='OK' else 'FALLBACK', 'explanation':result.payload,
        'call':result.call.model_dump(), 'error_code':result.error.code if result.error else None}
