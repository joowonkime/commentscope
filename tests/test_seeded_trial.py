from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from decimal import Decimal
import json

from tools import seeded_perspective_trial as trial
from commentscope.factory.claim_clusters import sha,read_json
from commentscope.storage import write_json_exclusive as write
from test_seeded_perspectives import seeded_bundle
import test_seeded_product as product_fixture
import test_minimal_pipeline as fixtures


class SeededTrialTests(TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        h=fixtures.MinimalPipelineTests();h.setUp();output=h.process(fixtures.ScriptedRunner())
        self.original=self.root/'original';snapshot=self.root/'snapshot.json'
        write(snapshot,h.snapshot.to_dict())
        refs=seeded_bundle();self.reference=self.root/'references.json'
        write(self.reference,{'documents':refs['documents'],'selections':refs['reference_selections']})
        owner=self.root/'owner.json';write(owner,{'original_financial_authority':'synthetic'})
        policy={'ledger':str(self.root/'ledger.sqlite'),'account_id':'test-original',
                'maximum_usd':'150','opening_charge_usd':'0'}
        policy_file=self.root/'policy.json';write(policy_file,policy)
        auth=self.original/'authorization.json'
        write(auth,{'financial_owner':{'file':str(owner),'sha256':sha(owner),'authorization':read_json(owner)}})
        plan={'snapshot':str(snapshot),'snapshot_sha256':sha(snapshot),'classifier':fixtures.MODEL,
              'scope_ids':[c.comment_id for c in h.snapshot.comments],'canonical_population':6,
              'authorization':{'file':str(auth),'sha256':sha(auth)},'policy_file':str(policy_file),'spend_policy':policy}
        write(self.original/'plan.json',plan);write(self.original/'artifacts/output.json',output)
        write(self.original/'completed.json',{'plan_sha256':sha(self.original/'plan.json'),
            'artifacts':{'artifacts/output.json':sha(self.original/'artifacts/output.json')}})
        self.rebuilt=self.root/'rebuilt'

    def mocks(self):
        state={'calls':3,'charged_usd':'1','reserved_calls':0,'uncertain_calls':0}
        money=type('Money',(),{'summary':lambda self,**kw:deepcopy(state)})()
        self.stack=[];self.money_state=state
        for target,value in ((trial.e,'ledger'),(trial.e,'provider_preflight'),(trial.e,'key_metadata'),
                              (trial.decisions,'preflight'),(trial.previous.previous,'history')):
            result=money if value=='ledger' else {'limit':150} if value=='key_metadata' else (3,'f'*64) if value=='history' else {}
            p=patch.object(target,value,return_value=result);p.start();self.addCleanup(p.stop)

    def test_rebuild_reuses_verified_sources_with_zero_provider_calls(self):
        with patch.object(trial.e,'key_metadata',side_effect=AssertionError('offline rebuild')):
            result=trial.rebuild(self.rebuilt,self.original,self.reference)
        self.assertEqual(result['new_model_calls'],0);self.assertEqual(len(result['profiles']),2)
        self.assertEqual([p['source_count'] for p in result['profiles']],[3,3])
        self.assertFalse(read_json(self.rebuilt/'artifacts/output.json')['fresh_upstream_inference'])
        self.assertEqual(read_json(self.original/'artifacts/output.json')['agent_inputs']['bundle'].get('admission_policy'),None)

    def test_rebuild_rejects_changed_historical_artifacts(self):
        (self.original/'artifacts/output.json').write_text('{}')
        with self.assertRaises(ValueError):trial.rebuild(self.rebuilt,self.original,self.reference)

    def test_closed_plan_same_owner_all_profiles_and_physical_request_bound(self):
        trial.rebuild(self.rebuilt,self.original,self.reference);self.mocks();directory=self.root/'live'
        result=trial.prepare(directory,self.rebuilt,user_request='synthetic explicit request')
        self.assertEqual(result['maximum_physical_calls'],48)
        plan=read_json(directory/'plan.json');self.assertEqual(len(plan['candidate_ids']),2)
        auth=trial.guard(plan)
        self.assertFalse(auth['new_money_owner']);self.assertEqual(plan['maximum_cost_usd'],'150')
        for field,value in (('questions',['invented']),('spend_policy',dict(plan['spend_policy'],account_id='reset')),
                            ('deployment',{}),('group_ids',[])):
            changed=deepcopy(plan);changed[field]=value
            (directory/'plan.json').write_text(json.dumps(changed))
            (directory/'frozen.json').write_text(json.dumps({'plan_sha256':sha(directory/'plan.json')}))
            with self.assertRaises(ValueError):trial.guard(changed)
        (directory/'plan.json').write_text(json.dumps(plan))
        (directory/'frozen.json').write_text(json.dumps({'plan_sha256':sha(directory/'plan.json')}))
        class Exhausted:
            def summary(self,**kw):return dict(calls=51,charged_usd='2',reserved_calls=0,uncertain_calls=0)
        with patch.object(trial.e,'ledger',return_value=Exhausted()):
            trial.guard(plan)
            with self.assertRaises(trial.e.BudgetExhausted):trial.guard(plan,call_seconds=30)

    def test_completed_execution_reentry_is_read_only(self):
        directory=self.root/'done';write(directory/'plan.json',{})
        write(directory/'artifacts/result.json',{'ok':True})
        write(directory/'completed.json',{'plan_sha256':sha(directory/'plan.json'),
            'artifacts':{'artifacts/result.json':sha(directory/'artifacts/result.json')},'report':{'ok':True}})
        with patch.object(trial,'guard',side_effect=AssertionError('no new work')):
            self.assertEqual(trial.run(directory),{'ok':True})

    def test_continuation_keeps_original_deadline_denominator_and_skips_attempted_profiles(self):
        from datetime import datetime,timedelta,timezone
        trial.rebuild(self.rebuilt,self.original,self.reference);self.mocks()
        parent=self.root/'parent';trial.prepare(parent,self.rebuilt,user_request='synthetic first request')
        original=read_json(parent/'plan.json');auth=read_json(parent/'authorization.json')
        write(parent/'failed.json',{'plan_sha256':sha(parent/'plan.json'),
            'authorization_sha256':sha(parent/'authorization.json'),
            'rooms':[{'mode':'one_to_one','participant_ids':original['candidate_ids'][:1]}]})
        self.money_state.update(calls=10,charged_usd='1.056')
        child=self.root/'child';result=trial.prepare(child,self.rebuilt,user_request='contract correction',continuation=parent)
        plan=read_json(child/'plan.json');new=read_json(child/'authorization.json')
        self.assertEqual(new['deadline'],auth['deadline']);self.assertEqual(new['started_at'],auth['started_at'])
        self.assertEqual(new['opening_owner'],auth['opening_owner'])
        self.assertEqual(new['phase_opening_owner']['calls'],10)
        self.assertEqual(result['already_used_physical_calls'],7)
        self.assertEqual(plan['direct_ids'],original['candidate_ids'][1:])
        self.assertEqual(plan['group_ids'],original['group_ids'])
        trial.guard(plan)
        # Even a consistently rehashed child cannot acquire a fresh denominator.
        changed=deepcopy(new);changed['opening_owner']=deepcopy(new['phase_opening_owner'])
        (child/'authorization.json').write_text(json.dumps(changed))
        plan['authorization']['sha256']=sha(child/'authorization.json')
        (child/'plan.json').write_text(json.dumps(plan))
        (child/'frozen.json').write_text(json.dumps({'plan_sha256':sha(child/'plan.json')}))
        with self.assertRaises(ValueError):trial.guard(plan)

    def test_continuation_rejects_changed_or_completed_failed_parent(self):
        trial.rebuild(self.rebuilt,self.original,self.reference);self.mocks()
        parent=self.root/'parent';trial.prepare(parent,self.rebuilt,user_request='synthetic first request')
        plan=read_json(parent/'plan.json')
        write(parent/'failed.json',{'plan_sha256':'f'*64,'authorization_sha256':sha(parent/'authorization.json'),'rooms':[]})
        with self.assertRaises(ValueError):trial.continuation_scope(parent,plan['candidate_ids'],plan['bundle_revision'])


class SeededProbeTests(TestCase):
    def test_fixed_product_probe_covers_every_profile_and_peer_round(self):
        # Uses the real ProductApp job/controller/store path with scripted models.
        h=product_fixture.SeededProductTests();h.setUp();self.addCleanup(h.doCleanups)
        saved={};rooms=trial.probe(h.app,h.analysis,lambda k,v:saved.setdefault(k,v))
        self.assertEqual(len(rooms),3)
        self.assertEqual([r['turn_count'] for r in rooms],[4,4,4])
        self.assertEqual(len(h.calls),12);self.assertEqual(len(h.decisions),12)
        self.assertTrue(any(req['data']['PEER_CONTEXT_ONLY'] for req in h.calls))
        self.assertEqual([r['participant_ids'][0] for r in rooms[:2]],['P1','P2'])

