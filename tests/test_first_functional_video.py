"""Bounded new-video scope/dispatch/runtime checks; synthetic and zero paid calls."""
from collections import Counter
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from tools import first_functional_video as f
from experiments.grounding_contract_demo import fixture
from commentscope.factory.shared_admission import PriorRequestUnavailable


class FirstFunctionalVideoTests(TestCase):
    def registry(self):return {**{'r'+str(i):dict(parent=None,text='synthetic'+str(i)) for i in range(90)},**{'c'+str(i):dict(parent={'id':'r0'},text='synthetic reply'+str(i)) for i in range(50)}}

    def test_scope_is_deterministic_disjoint_and_preserves_parent_context(self):
        registry=self.registry();before=deepcopy(registry);active,held=f.scope(registry)
        self.assertEqual((len(active),len(held)),(96,24));self.assertFalse(set(active)&set(held))
        self.assertEqual(sum(registry[s]['parent'] is None for s in active),64);self.assertEqual(sum(registry[s]['parent'] is None for s in held),16)
        self.assertEqual(f.scope(dict(reversed(list(registry.items())))),(active,held));self.assertEqual(registry,before)
        changed=deepcopy(registry)
        for s in changed.values():s['text']='Opposite opinion; labels cannot change the selection'
        self.assertEqual(f.scope(changed),(active,held))

    def test_insufficient_root_or_reply_inventory_stops_before_execution(self):
        for root_count in (True,False):
            registry=self.registry();keys=[k for k,v in registry.items() if (v['parent'] is None)==root_count]
            for k in keys[:12]:del registry[k]
            with self.assertRaises(ValueError):f.scope(registry)

    def test_three_hour_grant_reserves_enough_time_for_the_next_call(self):
        now=datetime.now(timezone.utc);auth=dict(started_at=now.isoformat(),deadline=(now+timedelta(hours=3)).isoformat())
        f.window(auth,now=now,call_seconds=180)
        with self.assertRaises(TimeoutError):f.window(auth,now=now+timedelta(hours=3,seconds=-100),call_seconds=180)
        with self.assertRaises(ValueError):f.window({**auth,'deadline':(now+timedelta(hours=4)).isoformat()},now=now)

    def session(self):
        s=f.Session.__new__(f.Session);s.registry={'s':dict(id='s',text='Adopt P.',parent=None),'held':dict(id='held',text='Do not adopt P.',parent=None)};s.allowed={'s'};s.seen=set();s.counts=Counter();return s

    def test_typed_scope_rejects_held_out_source_foreign_candidate_and_changed_original(self):
        s=self.session();c=dict(id='c',text='Adopt P.');search=dict(policy=f.SEARCH,pairs=[dict(source_id='s',candidate_id='c')]);s.pin=lambda name:[c] if name=='initial-candidates' else search
        packet=dict(state=dict(READING_INPUT=dict(ORIGINAL=f.mc.packet(s.registry['s']),CANDIDATE=dict(text=c['text']))))
        with patch.object(f.shared.Session,'decide',return_value={'ok':True}) as provider:
            self.assertEqual(s.decide('synthetic',packet),{'ok':True})
            for mutate in (lambda d:d.update(ORIGINAL=f.mc.packet(s.registry['held'])),lambda d:d['CANDIDATE'].update(text='Invented'),lambda d:d['ORIGINAL'].update(source_sha256='changed')):
                bad=deepcopy(packet);mutate(bad['state']['READING_INPUT'])
                with self.assertRaises(ValueError):s.decide('synthetic',bad)
            self.assertEqual(provider.call_count,1)

    def test_embeddings_use_only_exact_active_sources_or_discovered_candidates(self):
        s=self.session();s.pin=lambda name:[dict(id='c',text='Adopt P.')]
        with patch.object(f.shared.Session,'embed',return_value={'ok':True}) as provider:
            self.assertEqual(s.embed('sources',{'s':'Adopt P.'}),{'ok':True});self.assertEqual(s.embed('candidates',{'c':'Adopt P.'}),{'ok':True})
            for stage,texts in [('sources',{'s':'repaired'}),('sources',{'held':'Do not adopt P.'}),('candidates',{'foreign':'Adopt P.'}),('other',{})]:
                with self.assertRaises(ValueError):s.embed(stage,texts)
            self.assertEqual(provider.call_count,2)

    def test_graph_holdout_cannot_dispatch_and_settled_length_uses_existing_proof(self):
        s=self.session();s.plan={'deployment':f.e.remote.SOL,'verification_deployment':f.e.remote.SOL};s.save=lambda k,v:None
        with self.assertRaises(ValueError):s.call('source-evidence-proposal',{'data':{'ORIGINAL':{'source_id':'held'}}})
        req=dict(system='synthetic',data={'ORIGINAL':{'source_id':'s'}},schema={},max_tokens=100)
        with patch.object(f.shared.Session,'call',side_effect=f.ModelResponseUnavailable('stage','a','b')),patch.object(f.previous,'settled_hold',side_effect=PriorRequestUnavailable('settled')) as hold:
            with self.assertRaises(PriorRequestUnavailable):s.call('source-evidence-proposal',req)
            self.assertEqual(hold.call_args.args[2],req)

    def test_generated_inventory_is_pinned_and_cannot_change_on_resume(self):
        with TemporaryDirectory() as temp:
            s=self.session();s.directory=Path(temp);p=s.directory/'artifacts/initial-candidates.json';p.parent.mkdir();p.write_text('[]')
            self.assertEqual(s.pin('initial-candidates'),[]);self.assertEqual(s.pin('initial-candidates'),[]);p.write_text('[{}]')
            with self.assertRaises(ValueError):s.pin('initial-candidates')

    def test_probe_runs_all_seven_questions_and_never_invents_missing_content(self):
        calls=[];saved={}
        class Runner:
            def call(self,stage,request):
                calls.append(request);data=request['data'];entries=data['PERSPECTIVE']['allowed_entries'];question=data['QUESTION']
                value=dict(answerability='not_in_evidence',claim_ids=[],limitation='missing_evidence')
                if question==f.STANDARD[0]['text']:value=dict(answerability='grounded',claim_ids=[entries[0]['claim_id']],limitation='none')
                return dict(output=value,errors=[])
        result=f.probe(fixture(),Runner(),lambda k,v:saved.setdefault(k,v));self.assertEqual(len(calls),7);self.assertEqual(len(result['turns']),7)
        self.assertEqual(result['turns'][0]['turn']['status'],'answered');self.assertTrue(all(r['turn']['status']=='abstain' for r in result['turns'][1:]))
        self.assertTrue(all(r['other_histories_unchanged'] for r in result['turns']));self.assertEqual(len(saved),7)

    def test_completed_run_is_read_only_and_checks_artifact_integrity(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);(root/'plan.json').write_text('{}');(root/'artifacts').mkdir();p=root/'artifacts/report.json';p.write_text('{"complete":true}')
            done=dict(plan_sha256=f.sha(root/'plan.json'),artifacts={'artifacts/report.json':f.sha(p)},report={'complete':True});(root/'completed.json').write_text(json.dumps(done))
            with patch.object(f,'guard',side_effect=AssertionError('No provider dispatch')):self.assertEqual(f.run(root),{'complete':True})
            p.write_text('{}')
            with self.assertRaises(ValueError):f.run(root)
