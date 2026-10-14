from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest import TestCase

from commentscope.factory import opinion_map as m
from commentscope.factory.automatic_contract import digest
from commentscope.ingestion import load_snapshot
from experiments.opinion_map_report import LEGACY


class OpinionMapTests(TestCase):
    def setUp(self):
        snapshot = load_snapshot(Path('tests/fixtures/synthetic-snapshot.json')).snapshot
        self.snapshot = replace(snapshot, usage=replace(snapshot.usage, expires_at='2099-01-01T00:00:00Z'),
                                comments=snapshot.comments[:3])
        self.perspectives = [{'id': 'P1', 'claim': {'text': 'Adopt policy P.'}, 'upstream_agent_state': 'fact_deferred'},
                             {'id': 'P2', 'claim': {'text': 'Preserve individual choice.'}, 'upstream_agent_state': 'not_evaluated'}]

    def row(self, source=0, perspective=0, relation='supported'):
        s=self.snapshot.comments[source]; p=self.perspectives[perspective]
        return {'perspective_id':p['id'], 'source_id':s.comment_id,
                'claim_sha256':digest(p['claim']), 'source_sha256':digest(s.text_original),
                'relation':relation,'evidence_ref':f'synthetic:{source}:{perspective}:{relation}'}

    def test_agent_deferral_does_not_erase_counts_or_approve_agent(self):
        out=m.build(self.snapshot,self.perspectives,[self.row(i) for i in range(3)])
        p=out['perspectives'][0]
        self.assertEqual(p['counts']['supported'],3)
        self.assertTrue(p['minimum_support_met'])
        self.assertEqual(p['upstream_agent_state'],'fact_deferred')
        self.assertFalse(p['agent_approved_by_map'])
        self.assertFalse(out['quality_gate_passed'])

    def test_missing_retrieval_is_not_negative_or_full_population_count(self):
        out=m.build(self.snapshot,self.perspectives,[self.row()])
        p=out['perspectives'][0]
        self.assertEqual(p['counts']['unassessed'],2)
        self.assertEqual(p['counts']['not_supported'],0)
        self.assertFalse(p['assessment_complete'])
        self.assertEqual(out['coverage']['sources_assessed_for_all_discovered_perspectives'],0)

    def test_conditional_and_uncertain_are_not_support(self):
        out=m.build(self.snapshot,self.perspectives,[self.row(relation='conditional'),self.row(1,relation='uncertain')])
        self.assertEqual(out['perspectives'][0]['counts']['supported'],0)
        self.assertEqual(out['perspectives'][0]['counts']['conditional'],1)
        self.assertFalse(out['perspectives'][0]['minimum_support_met'])
        self.assertEqual(LEGACY['partial'],'uncertain')
        self.assertEqual(LEGACY['unsupported'],'not_supported')

    def test_multilabel_counts_are_not_added_for_comment_coverage(self):
        out=m.build(self.snapshot,self.perspectives,[self.row(),self.row(perspective=1)])
        self.assertEqual(sum(p['counts']['supported'] for p in out['perspectives']),2)
        self.assertEqual(out['coverage']['sources_with_supported_assignment'],1)

    def test_full_assignment_does_not_claim_80_percent_perspective_recall(self):
        out=m.build(self.snapshot,self.perspectives,[self.row(i,j) for i in range(3) for j in range(2)])
        self.assertEqual(out['coverage']['supported_assignment_rate'],1)
        self.assertEqual(out['coverage']['sources_assessed_for_all_discovered_perspectives'],3)
        self.assertIsNone(out['coverage']['perspective_recall'])

    def test_repeated_evidence_and_duplicate_aliases_count_once(self):
        first=self.snapshot.comments[0]
        duplicate=replace(first,comment_id='duplicate-c1')
        self.snapshot=replace(self.snapshot,comments=self.snapshot.comments+(duplicate,))
        row=self.row(); alias=self.row(3)
        out=m.build(self.snapshot,self.perspectives,[row,row,alias])
        self.assertEqual(out['coverage']['canonical_nonempty_comments'],3)
        self.assertEqual(out['coverage']['duplicate_aliases'],1)
        self.assertEqual(out['perspectives'][0]['counts']['supported'],1)

    def test_conflicting_verdicts_are_not_silently_resolved(self):
        with self.assertRaises(ValueError):
            m.build(self.snapshot,self.perspectives,[self.row(),self.row(relation='not_supported')])

    def test_changed_text_and_target_bindings_rejected(self):
        for field in ('source_sha256','claim_sha256','source_id','perspective_id','relation'):
            row=self.row(); row[field]='unknown'
            with self.subTest(field=field),self.assertRaises(ValueError):
                m.build(self.snapshot,self.perspectives,[row])

    def test_no_candidates_is_unknown_discovery_not_perfect_coverage(self):
        out=m.build(self.snapshot,[],[])
        self.assertIsNone(out['coverage']['perspective_recall'])
        self.assertEqual(out['coverage']['sources_without_supported_assignment'],3)
        self.assertEqual(out['coverage']['sources_assessed_for_all_discovered_perspectives'],0)

    def test_duplicate_perspectives_rejected_and_inputs_unchanged(self):
        before=deepcopy(self.perspectives)
        m.build(self.snapshot,self.perspectives,[self.row()])
        self.assertEqual(before,self.perspectives)
        with self.assertRaises(ValueError):m.build(self.snapshot,self.perspectives*2,[])

    def test_expired_snapshot_is_not_republished(self):
        old=replace(self.snapshot,usage=replace(self.snapshot.usage,expires_at='2000-01-01T00:00:00Z'))
        with self.assertRaises(ValueError):m.build(old,self.perspectives,[])
