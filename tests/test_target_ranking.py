from copy import deepcopy
import unittest
from unittest.mock import patch

from commentscope.factory import source_first, target_ranking as ranking
from commentscope.factory.automatic_contract import digest
from commentscope.providers import target_ranking_nli as provider
from test_source_first import output


def fixture():
    texts=['Safety reviews should be required for operators.',
           'Safety reviews should be required.',
           'Safety reviews should be required before opening.']
    sources={f's{i}':text for i,text in enumerate(texts)}
    units=[source_first.bind(sid,text,{'errors':[],'output':output(text)})['units'][0]
           for sid,text in sources.items()]
    proposal={'id':'C1','claims':{'C':ranking.target(units[0])},'sources':sources,
              'anchor_unit_id':units[0]['claim_id'],'candidate_unit_ids':[u['claim_id'] for u in units]}
    return [proposal],units


def scored(scheduled, preferred):
    rows=[]
    for p in scheduled['pairs']:
        score=.95 if p['target_unit_id']==preferred else .1
        rows.append({'id':p['id'],'pair_sha256':digest(p),'errors':[],
                     'scores':{'entailment':score,'neutral':1-score,'contradiction':0.}})
    return {'rows':rows}


class TargetRankingTests(unittest.TestCase):
    def test_selects_one_existing_alternative_without_admitting_any_member(self):
        proposals,units=fixture(); scheduled=ranking.schedule(proposals,units)
        result=ranking.assemble(proposals,units,scheduled,scored(scheduled,units[1]['claim_id']))
        self.assertEqual(len(scheduled['pairs']),6)
        self.assertEqual(len(result['alternatives']),1)
        alt=result['alternatives'][0]
        self.assertEqual(alt['claims']['C'],ranking.target(units[1]))
        self.assertEqual(alt['sources'],proposals[0]['sources'])
        self.assertEqual(alt['parent_candidate_id'],'C1')
        self.assertFalse(result['membership_approval']);self.assertFalse(alt['semantic_approval'])

    def test_preserves_original_if_it_ranks_first(self):
        proposals,units=fixture(); s=ranking.schedule(proposals,units)
        self.assertEqual(ranking.assemble(proposals,units,s,scored(s,units[0]['claim_id']))['alternatives'],[])

    def test_same_source_units_cannot_inflate_estimated_support(self):
        proposals,units=fixture()
        units.append({**deepcopy(units[2]),'claim_id':'another-unit-from-same-source'})
        proposals[0]['candidate_unit_ids'].append(units[-1]['claim_id'])
        s=ranking.schedule(proposals,units); r=ranking.assemble(proposals,units,s,scored(s,units[1]['claim_id']))
        self.assertEqual(r['rankings'][0]['ranked'][0]['estimated_other_source_count'],2)
        self.assertTrue(all(p['premise_source_id']!=next(u['source_comment_id'] for u in units if u['claim_id']==p['target_unit_id']) for p in s['pairs']))

    def test_conditions_are_in_ranking_text_and_selected_target(self):
        proposals,units=fixture(); units[1]['condition']='if access is free'
        s=ranking.schedule(proposals,units)
        self.assertTrue(all('if access is free' in p['hypothesis'] for p in s['pairs'] if p['target_unit_id']==units[1]['claim_id']))
        r=ranking.assemble(proposals,units,s,scored(s,units[1]['claim_id']))
        self.assertEqual(r['alternatives'][0]['claims']['C']['scope']['conditions'],'if access is free')

    def test_incomplete_unbound_or_invalid_scores_are_rejected(self):
        ps,us=fixture(); s=ranking.schedule(ps,us); results=scored(s,us[1]['claim_id'])
        changed=deepcopy(results);changed['rows'].pop()
        with self.assertRaises(ValueError):ranking.assemble(ps,us,s,changed)
        changed=deepcopy(results);changed['rows'][0]['pair_sha256']='bad'
        with self.assertRaises(ValueError):ranking.assemble(ps,us,s,changed)
        changed=deepcopy(results);changed['rows'][0]['scores']['entailment']=float('nan')
        with self.assertRaises(ValueError):ranking.assemble(ps,us,s,changed)

    def test_errors_are_preserved_and_never_scored_as_support(self):
        ps,us=fixture(); s=ranking.schedule(ps,us); results=scored(s,us[1]['claim_id'])
        for row in results['rows']:row.update(errors=['input_too_long'],scores=None)
        r=ranking.assemble(ps,us,s,results)
        self.assertEqual(len(r['pair_errors']),6);self.assertEqual(r['alternatives'],[])

    def test_budget_defers_whole_group_without_silent_pair_sampling(self):
        ps,us=fixture()
        with patch.object(ranking,'MAX_PAIRS',2):s=ranking.schedule(ps,us)
        self.assertEqual(s['pairs'],[]);self.assertEqual(s['deferred'],[{'id':'C1','reason':'ranking_pair_budget'}])

    def test_incompatible_frames_and_unknown_quotes_fail(self):
        ps,us=fixture();bad=deepcopy(us);bad[1]['stance']='oppose'
        with self.assertRaises(ValueError):ranking.schedule(ps,bad)
        bad=deepcopy(us);bad[1]['quote']='fabricated'
        with self.assertRaises(ValueError):ranking.schedule(ps,bad)

    def test_empty_worker_does_not_load_model(self):
        with patch.object(provider,'LocalNLI') as model:
            r=provider.generate(provider.VERSION,{'pairs':[]},{},1)
        model.assert_not_called();self.assertEqual(r['rows'],[]);self.assertFalse(r['membership_approval'])
