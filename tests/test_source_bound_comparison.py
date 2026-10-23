from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentscope.factory import position_frames as frames
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json
from commentscope.storage import write_json_exclusive as write
from experiments import source_bound_comparison as comparison
from experiments.framed_cluster_controls import TARGET


NOTICE = {'target':'public meeting notices','statement':'Public meeting notices should be accessible to blind residents.',
          'entity':'public meeting notices','time':'','conditions':''}
VOLUNTARY = {'target':'safety reviews','statement':'Safety reviews should remain voluntary.',
             'entity':'safety reviews','time':'','conditions':''}


class FakeRunner:
    def __init__(self, *, fail_proposal=False, fail_member=False):
        self.fail_proposal=fail_proposal; self.fail_member=fail_member; self.calls=[]

    def call(self, stage, request):
        self.calls.append((stage,deepcopy(request)))
        data=request['data']
        if stage.endswith('-proposals'):
            if stage.startswith('frame_views') and self.fail_proposal:
                return {'errors':['call_failed'],'output':None}
            units=data.get('POSITION_VIEWS',data.get('POSITION_ANCHORS'))
            nominees=[u['id'] for u in units]
            contracts=[TARGET] if stage.startswith('frame_views') else [TARGET,NOTICE,VOLUNTARY]
            return {'errors':[],'output':{'candidates':[{'contract':deepcopy(c),'nominees':nominees} for c in contracts]}}
        sid=data['SOURCE_ID']; contract=data['CANDIDATE']
        if sid=='B' and self.fail_member:return {'errors':['call_failed'],'output':None}
        if contract==TARGET:
            relation='supported' if sid in 'ABC' else {'D':'conditional','E':'opposed','F':'unrelated'}[sid]
        elif contract==NOTICE:
            relation='supported' if sid=='F' else 'unrelated'
        else:
            relation='supported' if sid=='E' else 'unrelated'
        return {'errors':[],'output':{'relation':relation,'authorship':'asserted_or_endorsed',
            'scope_preserved':'yes','evidence_segment_ids':['S000']}}


class SourceBoundComparisonTests(unittest.TestCase):
    def setUp(self):
        self.snapshot=comparison.synthetic_snapshot(); self.records=[]
        for comment in self.snapshot.comments:
            packet=frames.source_packet(self.snapshot,comment.comment_id)
            position={'target':'reviews','statement':frames.validate_source(packet)[0]['text'],
                'mode':'normative','entity':'reviews','time':'','segment_ids':['S000'],'qualifications':[],'reasons':[]}
            self.records.append(frames.bind(packet,{'errors':[],'output':{'status':'positions','positions':[position]}}))

    def execute(self, **kwargs):
        saved={}; runner=FakeRunner(**kwargs)
        output=comparison.compare(self.snapshot,self.records,runner,lambda k,v:saved.update({k:deepcopy(v)}))
        return output,runner,saved

    def test_all_generated_candidates_and_every_source_are_evaluated(self):
        output,runner,saved=self.execute()
        self.assertEqual(len(runner.calls),2+6+18)
        self.assertEqual(output['frame_views']['candidate_count'],1)
        self.assertEqual(output['source_bound']['candidate_count'],3)
        self.assertEqual(output['source_bound']['scheduled_pair_count'],18)
        self.assertEqual(output['source_bound']['completed_pair_count'],18)
        self.assertEqual(len({(r['candidate_id'],r['source_id']) for r in output['source_bound']['scheduled_pairs']}),18)
        for arm in comparison.ARMS:
            self.assertIn(arm+'/output',saved)
            self.assertFalse(output[arm]['quality_gate_passed'])
            self.assertTrue(output[arm]['semantic_review_required'])

    def test_nominees_do_not_become_support_votes(self):
        output,_,_=self.execute()
        for arm in comparison.ARMS:
            candidate=next(c for c in output[arm]['candidates'] if c['contract']==TARGET)
            self.assertEqual(len(candidate['nominees']),6)
            counts=output[arm]['model_counts'][candidate['id']]
            self.assertEqual(counts['supported'],3)
            self.assertEqual(counts['conditional'],1)

    def test_failed_relation_remains_unassessed_and_in_population(self):
        output,_,_=self.execute(fail_member=True)
        self.assertEqual(output['source_bound']['completed_pair_count'],15)
        self.assertEqual(len(output['source_bound']['errors']),3)
        for counts in output['source_bound']['model_counts'].values():
            self.assertEqual(counts['unassessed'],1)
        for arm in comparison.ARMS:
            self.assertEqual(output[arm]['map']['opinion_map']['coverage']['canonical_nonempty_comments'],6)

    def test_failed_arm_does_not_disappear_or_select_other_candidates(self):
        output,runner,_=self.execute(fail_proposal=True)
        self.assertEqual(output['frame_views']['candidate_count'],0)
        self.assertEqual(output['frame_views']['errors'][0]['stage'],'proposal')
        self.assertEqual(output['source_bound']['candidate_count'],3)
        self.assertEqual(len(runner.calls),20)

    def test_requests_contain_no_reference_labels_and_membership_is_raw_source_only(self):
        _,runner,_=self.execute()
        for stage,request in runner.calls:
            self.assertNotIn('expected',str(request['data']))
            self.assertNotIn('reference',str(request['data']))
            if not stage.endswith('-proposals'):
                self.assertEqual(set(request['data']),{'SOURCE_ID','ORIGINAL_SEGMENTS','PARENT_CONTEXT','CANDIDATE'})
        left=runner.calls[0][1]
        right=next(req for stage,req in runner.calls if stage=='source_bound-proposals')
        self.assertEqual(left['schema'],right['schema'])
        self.assertEqual(left['max_tokens'],right['max_tokens'])

    def test_current_uncapped_cycle_is_required_before_other_inputs(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(comparison,'PRIVATE_ROOT',Path(tmp)):
            cycle=Path(tmp)/'cycle.json'
            write(cycle,{'goal_revision':'factory-goal-20261014-r4','cycle_id':'mvp-factory-20261014',
                         'limit_seconds':28800,'analysis_seconds':3600})
            with self.assertRaisesRegex(ValueError,'uncapped'):
                comparison.prepare(Path(tmp)/'new',Path('missing'),Path('missing'),cycle)

    def test_existing_trial_is_not_overwritten_or_retried(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(comparison,'PRIVATE_ROOT',Path(tmp)):
            directory=Path(tmp)/'trial';directory.mkdir()
            with self.assertRaises(ValueError):comparison.prepare(directory,Path('missing'),Path('missing'),Path('missing'))
            write(directory/'started.json',{'pid':1})
            with self.assertRaisesRegex(ValueError,'silently retried'):comparison.run(directory)

    def preflight(self, tmp, *, headroom=11*1024**3, available=9000):
        directory=Path(tmp);plan={'preflight':comparison.PREFLIGHT}
        write(directory/'plan.json',plan)
        return comparison.preflight(directory,plan,observe=lambda:{'available_mb':available,
            'committed_bytes':20*1024**3,'commit_limit':20*1024**3+headroom,'disk_free_bytes':18*1024**3})

    def test_preflight_rejects_known_insufficient_loading_margin_without_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError,'Model not started'):
                self.preflight(tmp,headroom=7*1024**3)
            row=read_json(Path(tmp)/'preflight/0001.json')
            self.assertFalse(row['admitted']);self.assertEqual(row['new_model_calls'],0)
            self.assertFalse((Path(tmp)/'started.json').exists())

    def test_preflight_sufficient_resources_are_not_quality_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            report=self.preflight(tmp)
            self.assertTrue(report['admitted']);self.assertFalse(report['quality_gate_passed'])

    def test_preflight_failure_is_recorded_and_does_not_allow_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);plan={'preflight':comparison.PREFLIGHT};write(directory/'plan.json',plan)
            with self.assertRaises(RuntimeError):comparison.preflight(directory,plan,observe=lambda:{})
            self.assertEqual(read_json(directory/'preflight/0001.json')['reasons'],['resource_observation_failed'])


if __name__=='__main__':unittest.main()
