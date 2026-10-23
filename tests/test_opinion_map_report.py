from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from commentscope.factory.claim_clusters import sha
from commentscope.storage import write_json_exclusive as write
from experiments.opinion_map_report import report


class OpinionMapReportTests(TestCase):
    def prepare(self, root, *, verdict='supported', missing=False, change=False, supplement=False):
        snapshot=json.loads(Path('tests/fixtures/synthetic-snapshot.json').read_text(encoding='utf-8'))
        snapshot['usage']['expires_at']='2099-01-01T00:00:00Z'
        snapshot['comments']=snapshot['comments'][:3]
        path=root/'snapshot.json';write(path,snapshot)
        proposal={'id':'P1','claims':{'C':{'text':'Adopt policy P.'}},
                  'sources':{c['comment_id']:c['text_original'] for c in snapshot['comments']}}
        source=root/'source'
        write(source/'plan.json',{'artifact_kind':'fresh-direct-ground-product-0.1',
                                 'snapshot':str(path),'inputs':{str(path):sha(path)}})
        write(source/'completed.json',{'artifact_kind':'fresh-direct-ground-product-0.1',
              'outcomes':[{'id':'P1','state':'unprocessed_completion_budget' if supplement else 'fact_deferred'}]})
        write(source/'selected-queue.json',[proposal])
        extra=None; directory=source
        if supplement:
            extra=root/'extra';directory=extra
            write(extra/'plan.json',{'artifact_kind':'pending-core-population-diagnostic-0.1',
                'source_directory':str(source),'tasks':[{'proposal':proposal}],
                'inputs':{str(source/n):sha(source/n) for n in ('plan.json','completed.json')}})
            write(extra/'completed.json',{'artifact_kind':'pending-core-population-diagnostic-0.1',
                                          'outcomes':[{'id':'P1','state':'core_ready_not_agent'}]})
        if not missing:
            rows=[{'id':str(i),'source_id':sid,'text':text,'claim':deepcopy(proposal['claims']['C'])}
                  for i,(sid,text) in enumerate(proposal['sources'].items())]
            if change:rows[0]['claim']['text']='Changed core'
            write(directory/'candidates/P1/membership.json',{'proposals':[proposal],'rows':rows,
                                                           'actual':{r['id']:verdict for r in rows}})
        return source,extra

    def test_full_population_and_deferral_preserved_without_inference(self):
        with TemporaryDirectory() as tmp:
            source,_=self.prepare(Path(tmp)); out=report(source)
            self.assertEqual(out['coverage']['canonical_nonempty_comments'],3)
            self.assertEqual(out['perspectives'][0]['counts']['supported'],3)
            self.assertEqual(out['perspectives'][0]['upstream_agent_state'],'fact_deferred')
            self.assertEqual(out['new_inference_calls'],0)
            self.assertFalse(out['common_position_algorithm_implemented'])

    def test_partial_is_unknown_not_conditional(self):
        with TemporaryDirectory() as tmp:
            source,_=self.prepare(Path(tmp),verdict='partial'); out=report(source)
            self.assertEqual(out['perspectives'][0]['counts']['uncertain'],3)
            self.assertEqual(out['perspectives'][0]['counts']['conditional'],0)

    def test_bound_supplement_does_not_change_agent_approval(self):
        with TemporaryDirectory() as tmp:
            source,extra=self.prepare(Path(tmp),supplement=True);out=report(source,extra)
            self.assertEqual(out['perspectives'][0]['counts']['supported'],3)
            self.assertFalse(out['perspectives'][0]['agent_approved_by_map'])

    def test_missing_measured_artifact_rejected_in_both_directories(self):
        for supplement in (False,True):
            with self.subTest(supplement=supplement),TemporaryDirectory() as tmp:
                source,extra=self.prepare(Path(tmp),supplement=supplement,missing=True)
                with self.assertRaises(ValueError):report(source,extra)

    def test_changed_target_not_rebound_to_old_verdict(self):
        with TemporaryDirectory() as tmp:
            source,_=self.prepare(Path(tmp),change=True)
            with self.assertRaises(ValueError):report(source)
