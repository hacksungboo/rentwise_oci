"""Model routing, model-bound billing and grounded Markdown. No paid network."""
from dataclasses import replace
from decimal import Decimal

import pytest
from sqlalchemy import select

from rentwise.ai_policy import DEFAULT_MODEL, PRICE_VERSIONS, PRICES
from rentwise.contracts.types import Usage
from rentwise.db import database, tables as T
from rentwise.engine import RealEngine
from rentwise.engine.explain import OpenAIPlanExplainer, PRESENTATION_VERSION, facts_for, render
from rentwise.engine.interpret import OpenAIInterpreter, ProviderFailure
from tests.engine.test_explain import FakeClient as ExplainClient, plan
from tests.engine.test_interpret import FakeBudget, FakeClient, interpretation_input


@pytest.mark.parametrize('model_id', ['gpt-5.6-terra', 'gpt-5.6-luna'])
def test_both_ai_calls_use_selected_model_and_its_price_version(model_id):
    budget = FakeBudget(); client = FakeClient()
    interpreter = OpenAIInterpreter(client=client, budget=budget, model_id=model_id)
    r = interpreter.interpret(interpretation_input())
    assert r.status == 'OK' and client.calls[0][0]['model'] == model_id
    assert budget.settled[0][2] == PRICE_VERSIONS[model_id]
    assert budget.reservations[0][2] == Decimal('.064' if model_id == DEFAULT_MODEL else '.0064')
    budget2 = FakeBudget(); client2 = ExplainClient()
    engine = RealEngine(interpreter=OpenAIInterpreter(client=client2, budget=budget2, model_id=model_id))
    r = engine.explain_plan(plan())
    assert r.status == 'OK' and r.call.model_id == client2.calls[0]['model'] == model_id
    assert budget2.settled[0][2] == PRICE_VERSIONS[model_id]
    assert budget2.reservations[0][2] == Decimal('.052' if model_id == DEFAULT_MODEL else '.0052')


def test_defaults_are_terra_and_environment_override_remains_explicit(monkeypatch):
    from rentwise.config import Settings
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    assert Settings().openai_model == OpenAIInterpreter.from_environment().model_id == DEFAULT_MODEL
    monkeypatch.setenv('OPENAI_MODEL', 'gpt-5.6-luna')
    assert Settings().openai_model == OpenAIInterpreter.from_environment().model_id == 'gpt-5.6-luna'


@pytest.mark.parametrize('model_id', ['gpt-5.6-terra', 'gpt-5.6-luna'])
def test_ledger_prices_call_version_even_if_global_model_differs(client, monkeypatch, model_id):
    from rentwise.services import ai_ledger
    opposite = 'gpt-5.6-luna' if model_id == DEFAULT_MODEL else DEFAULT_MODEL
    monkeypatch.setattr(ai_ledger, 'settings', replace(ai_ledger.settings, ai_budget_usd='1', openai_model=opposite))
    ai_ledger.sync_limit(); b = ai_ledger.LedgerBudget()
    rid = b.reserve('model-bound', Decimal('.064'))
    usage = Usage(input_tokens=16000, cached_input_tokens=0, output_tokens=2000, reasoning_tokens=0)
    b.settle(rid, usage, PRICE_VERSIONS[model_id])
    with database.get_db_engine().connect() as conn:
        row = conn.execute(select(T.ai_ledger)).mappings().one()
    expected = (16000*PRICES[model_id][0]*Decimal('1.25')+2000*PRICES[model_id][2])/1_000_000
    assert Decimal(str(row['settled_usd'])) == expected <= Decimal(str(row['reserved_usd']))


def test_unknown_price_policy_retains_reservation(client):
    from rentwise.services import ai_ledger
    b = ai_ledger.LedgerBudget()
    from dataclasses import replace
    old = ai_ledger.settings
    ai_ledger.settings = replace(old, ai_budget_usd='1')
    try:
        ai_ledger.sync_limit(); rid = b.reserve('unknown-price', Decimal('.064'))
        with pytest.raises(ValueError, match='Unregistered'):
            b.settle(rid, Usage(input_tokens=1, output_tokens=1, cached_input_tokens=0, reasoning_tokens=0), 'unknown')
        with database.get_db_engine().connect() as conn:
            assert conn.execute(select(T.ai_ledger.c.status)).scalar_one() == 'RESERVED'
    finally:
        ai_ledger.settings = old


def test_markdown_has_grounded_sections_and_emphasizes_confirmed_values():
    p = plan(); out = render(p, facts_for(p))
    md = out['markdown']
    for title in ('### 변경 핵심', '### 변경 이유', '### 유지되는 약속', '> **확정 전 안내**'):
        assert title in md
    assert r'**10월 16일 14:30\~15:00**' in md and '**이서연**' in md and '**P02**' in md
    assert out['presentation_version'] == PRESENTATION_VERSION
    assert set(out['paragraphs']+out['preserved']) == {f['text'] for f in facts_for(p)}


def test_customer_markdown_and_newlines_cannot_inject_a_section_or_active_html():
    p = plan(); p['diff'][0]['site_name'] = '**위조**\n### 허위 확정\n[클릭](javascript:alert(1)) <script>x</script>'
    out = render(p, facts_for(p))
    md = out['markdown']
    assert '\\*\\*위조\\*\\*' in md and '\\#\\#\\# 허위 확정' in md
    assert '\n### 허위 확정' not in md and '\\[클릭\\]' in md
    assert r'<script\>x</script\>' in md  # Still text: the client never inserts HTML.


def test_model_failure_returns_the_same_structured_markdown():
    r = OpenAIPlanExplainer(client=ExplainClient(ProviderFailure('AI_TIMEOUT')), budget=FakeBudget()).explain(plan())
    assert r.status == 'ERROR' and r.payload['source'] == 'SYSTEM'
    assert r.payload['markdown'] == render(plan(), facts_for(plan()))['markdown']
