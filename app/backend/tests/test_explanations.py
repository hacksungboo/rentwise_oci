"""Read-only explanation endpoint with real plan/ledger and a fake provider."""
from dataclasses import replace
from decimal import Decimal
import json

import pytest
from sqlalchemy import select, update

from rentwise.engine import RealEngine
from rentwise.engine.interpret import OpenAIInterpreter, ProviderFailure
from .engine.test_explain import FakeClient


def draft(admin,monkeypatch):
    from rentwise.services import plans
    monkeypatch.setattr(plans,'get_engine',lambda:RealEngine())
    r=admin.post('/api/v1/requests',json={'source_customer_id':'C-H','text':'오늘 회수를 14시로 변경','received_at':'2026-10-16T09:00:00+09:00'})
    rid=r.json()['id']
    op=dict(operation='RESCHEDULE',kind='PICKUP',target_job_id='J-PICK1',item_id='PR-A',asset_ids=['P01'],quantity=1,
        source_customer_id='C-H',destination_customer_id=None,window_start='2026-10-16T14:00:00+09:00',
        window_end='2026-10-16T14:10:00+09:00',due_at='2026-10-16T17:00:00+09:00',rental_end_at=None,priority_hint='NORMAL',evidence=[])
    saved=admin.put(f'/api/v1/requests/{rid}/interpretation',json={'expected_request_revision':1,
        'payload':{'schema_version':'rental.intent.v1','operations':[op],'needs_confirmation':[]},'acknowledged_paths':[]})
    assert saved.status_code==200,saved.text
    planned=admin.post('/api/v1/plans',json={'request_id':rid,'interpretation_revision':saved.json()['interpretation']['revision'],'base_state_revision':7})
    assert planned.status_code==201 and planned.json()['status']=='READY',planned.text
    return planned.json()


def setup_engine(monkeypatch,client):
    from rentwise.services import explanations,ai_ledger
    monkeypatch.setattr(ai_ledger,'settings',replace(ai_ledger.settings,ai_budget_usd='1'))
    ai_ledger.sync_limit()
    engine=RealEngine(interpreter=OpenAIInterpreter(client=client,budget=ai_ledger.LedgerBudget()))
    monkeypatch.setattr(explanations,'get_engine',lambda:engine)


def send(admin,p,**changes):
    return admin.post(f"/api/v1/plans/{p['id']}/explanation",json=dict(
        expected_plan_revision=p['revision'],base_state_revision=p['base_state_revision'],input_hash=p['input_hash'],**changes))


def before_after():
    from rentwise.db import database,tables as T
    with database.get_db_engine().connect() as conn:
        return (database.read_snapshot(conn),[dict(r) for r in conn.execute(select(T.workspace_state)).mappings()],
            [dict(r) for r in conn.execute(select(T.plans)).mappings()],
            [dict(r) for r in conn.execute(select(T.audit_log)).mappings()])


def test_explanation_uses_stored_plan_records_cost_and_changes_no_operating_rows(admin,monkeypatch):
    from rentwise.db import database,tables as T
    p=draft(admin,monkeypatch)
    def outside_transaction():assert database.get_db_engine().pool.checkedout()==0
    client=FakeClient(before_return=outside_transaction);setup_engine(monkeypatch,client)
    before=before_after();r=send(admin,p)
    assert r.status_code==200,r.text
    payload=r.json()
    assert payload['status']=='OK' and payload['explanation']['source']=='AI'
    assert payload['explanation']['plan_id']==p['id'] and len(client.calls)==1
    summary=' '.join(payload['explanation']['paragraphs'])
    assert '15:00' in summary and 'P02' in summary and '14:30' in summary
    assert '12:00' in ' '.join(payload['explanation']['preserved'])
    assert before_after()==before
    with database.get_db_engine().connect() as conn:
        row=conn.execute(select(T.ai_ledger)).mappings().one()
        assert Decimal(str(row['reserved_usd']))==Decimal('.052') and row['status']=='SETTLED'
        call=conn.execute(select(T.ai_calls)).mappings().one()
        assert call['prompt_version']=='rental-plan-explain-v1.0' and call['status']=='OK'


@pytest.mark.parametrize('field,value',[('expected_plan_revision',2),('base_state_revision',999),('input_hash','wrong')])
def test_old_revision_or_hash_is_rejected_before_billing(admin,monkeypatch,field,value):
    p=draft(admin,monkeypatch);client=FakeClient();setup_engine(monkeypatch,client)
    body={'expected_plan_revision':p['revision'],'base_state_revision':p['base_state_revision'],'input_hash':p['input_hash']}
    body[field]=value
    r=admin.post(f"/api/v1/plans/{p['id']}/explanation",json=body)
    assert r.status_code==409 and r.json()['error']['code']=='STALE_EXPLANATION'
    assert not client.calls


@pytest.mark.parametrize('closed',['hold','confirm'])
def test_held_or_confirmed_plan_does_not_call_ai(admin,monkeypatch,closed):
    p=draft(admin,monkeypatch);client=FakeClient();setup_engine(monkeypatch,client)
    body={'expected_plan_revision':1,'reason':'보류'} if closed=='hold' else {'expected_plan_revision':1,'base_state_revision':7}
    assert admin.post(f"/api/v1/plans/{p['id']}/{closed}",json=body).status_code==200
    assert send(admin,p).status_code==409 and not client.calls


def test_state_change_during_model_call_discards_output_and_retains_cost(admin,monkeypatch):
    from rentwise.db import database,tables as T
    p=draft(admin,monkeypatch)
    def another_actor():
        with database.get_db_engine().begin() as conn:
            conn.execute(update(T.workspace_state).values(state_revision=8))
    client=FakeClient(before_return=another_actor);setup_engine(monkeypatch,client)
    r=send(admin,p)
    assert r.status_code==409 and len(client.calls)==1
    with database.get_db_engine().connect() as conn:
        assert conn.execute(select(T.ai_ledger.c.status)).scalar_one()=='SETTLED'
        assert conn.execute(select(T.plans.c.status).where(T.plans.c.id==p['id'])).scalar_one()=='READY'


def test_timeout_returns_system_summary_and_does_not_block_confirmation(admin,monkeypatch):
    from rentwise.db import database,tables as T
    p=draft(admin,monkeypatch);client=FakeClient(ProviderFailure('AI_TIMEOUT'));setup_engine(monkeypatch,client)
    r=send(admin,p)
    assert r.status_code==200,r.text
    assert r.json()['status']=='FALLBACK' and r.json()['explanation']['source']=='SYSTEM'
    assert r.json()['error_code']=='AI_TIMEOUT' and len(client.calls)==1
    with database.get_db_engine().connect() as conn:
        assert conn.execute(select(T.ai_ledger.c.status)).scalar_one()=='UNKNOWN'
    done=admin.post(f"/api/v1/plans/{p['id']}/confirm",json={'expected_plan_revision':1,'base_state_revision':7})
    assert done.status_code==200,done.text


def test_only_admin_can_request_paid_explanations(admin,monkeypatch):
    p=draft(admin,monkeypatch);client=FakeClient();setup_engine(monkeypatch,client)
    assert admin.delete('/api/v1/sessions/current').status_code==200
    assert send(admin,p).status_code==401
    assert admin.post('/api/v1/sessions',json={'username':'e1','password':'rentwise2026'}).status_code==200
    assert send(admin,p).status_code==403 and not client.calls


def test_maximum_explanation_usage_is_fully_covered_by_real_ledger_reservation(admin,monkeypatch):
    from rentwise.db import database,tables as T
    class MaximumUsage(FakeClient):
        def create(self,body,*,timeout):
            out=super().create(body,timeout=timeout)
            out['usage'].update(input_tokens=16000,output_tokens=1000,input_tokens_details={'cached_tokens':0})
            return out
    p=draft(admin,monkeypatch);setup_engine(monkeypatch,MaximumUsage())
    assert send(admin,p).status_code==200
    with database.get_db_engine().connect() as conn:
        row=conn.execute(select(T.ai_ledger)).mappings().one()
        assert Decimal(str(row['reserved_usd']))==Decimal(str(row['settled_usd']))==Decimal('.052')
