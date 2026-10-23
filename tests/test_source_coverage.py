from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from commentscope.factory import minimal_claims as mc, minimal_membership as mm
from commentscope.factory.automatic_contract import digest
from commentscope.factory.position_frames import source_packet, validate_snapshot_source, validate_source
from commentscope.ingestion import load_snapshot
from experiments.minimal_discovery_probe import extract
from test_minimal_factory import proposition, extraction, membership


class SourceCoverageTests(unittest.TestCase):
    def setUp(self):
        base = load_snapshot(Path('tests/fixtures/synthetic-snapshot.json')).snapshot
        self.snapshot = replace(base, usage=replace(base.usage, expires_at='2099-01-01T00:00:00Z'),
            comments=(replace(base.comments[0], comment_id='a',
            text_original='Adopt P.', parent_id=None),))
        self.source = source_packet(self.snapshot, 'a', include_video_context=True)

    def test_context_is_snapshot_bound_and_never_an_evidence_address(self):
        packet = mc.packet(self.source)
        self.assertEqual(packet['VIDEO_CONTEXT_ONLY']['title'], self.snapshot.video.title)
        self.assertEqual([p['text'] for p in packet['ORIGINAL_SEGMENTS']], ['Adopt P.'])
        self.assertEqual(validate_snapshot_source(self.snapshot, self.source), self.source)
        for key in ('video_id', 'title', 'primary_language'):
            changed = deepcopy(self.source); changed['video_context'][key] = 'foreign metadata'
            with self.assertRaises(ValueError): validate_snapshot_source(self.snapshot, changed)
        value = {'sources': [{'source_id':'a', 'status':'covered',
                 'claims':[{**proposition('Adopt P.'), 'evidence_segment_ids':['VIDEO_CONTEXT_ONLY']}]}]}
        with self.assertRaises(ValueError): mc.bind_extraction([self.source], {'output':value})
        changed = deepcopy(self.source); changed['video_context']['evidence'] = 'invented'
        with self.assertRaises(ValueError): validate_source(changed)

    def test_changed_video_cannot_reuse_old_membership_votes(self):
        records = extraction([self.source], {'a':['Adopt P.']}); candidates = mc.candidates(records)
        pairs = [{'source_id':'a', 'candidate_id':candidates[0]['id']}]
        batch = membership([self.source], candidates, pairs)
        mm.assemble_map(self.snapshot, candidates, [batch])
        changed = replace(self.snapshot, video=replace(self.snapshot.video, title='A different topic'))
        with self.assertRaises(ValueError): mm.assemble_map(changed, candidates, [batch])
        changed_record = deepcopy(records[0]); changed_record['source']['video_context']['title'] = 'Other'
        with self.assertRaises(ValueError): mc.validate(changed_record)

    def test_legacy_packet_remains_supported_without_fabricated_metadata(self):
        legacy = source_packet(self.snapshot, 'a')
        self.assertNotIn('video_context', legacy)
        self.assertNotIn('VIDEO_CONTEXT_ONLY', mc.packet(legacy))
        validate_snapshot_source(self.snapshot, legacy)
        self.assertEqual(mc.claim_id('Adopt P.'), 'MC'+digest(['minimal-claims-20261016-v2', 'Adopt P.']))

    def test_status_schema_disallows_contradictions_before_binding(self):
        req = mc.extraction_request([self.source])
        branches = req['schema']['properties']['sources']['items']['anyOf']
        by_status = {b['properties']['status']['const']: b['properties']['claims'] for b in branches}
        for status in ('non_substantive','unresolved'):
            self.assertEqual(by_status[status]['maxItems'], 0)
            value = {'sources':[{'source_id':'a','status':status,'claims':[proposition('Adopt P.')]}]}
            with self.assertRaises(ValueError): mc.bind_extraction([self.source], {'output':value})
        self.assertEqual(by_status['covered']['minItems'], 1)
        prior = extraction([self.source], {'a':['Adopt P.']}, {'a':'partial'})
        extra = mc.extraction_request([self.source], prior)
        branches = extra['schema']['properties']['sources']['items']['anyOf']
        statuses = {b['properties']['status']['const']: b for b in branches}
        self.assertNotIn('non_substantive', statuses)
        self.assertEqual(statuses['covered']['properties']['claims']['minItems'], 0)
        complete = mc.bind_extraction([self.source], {'output':{'sources':[
            {'source_id':'a','status':'covered','claims':[]}]}}, prior)
        self.assertEqual(complete[0]['claims'], prior[0]['claims'])

    def test_diagnostic_keeps_neighbor_and_limits_partial_supplement(self):
        originals = [{'id':s,'text':'Adopt P.','parent':None} for s in ('bad','partial','good')]
        class Runner:
            def __init__(self): self.calls=[]
            def call(self, stage, req):
                sid = req['data']['ORIGINALS'][0]['source_id']; self.calls.append((stage,sid))
                if sid == 'bad': rows=[]
                else:
                    status = 'partial' if sid == 'partial' else 'covered'
                    claims = [] if req['data']['PREVIOUS'] else [proposition('Adopt P.')]
                    rows=[{'source_id':sid,'status':status,'claims':claims}]
                return {'raw':'scripted','output':{'sources':rows},'errors':[]}
        runner=Runner()
        with TemporaryDirectory() as tmp:
            output = extract(Path(tmp), runner, originals,
                             inspect=lambda req:{'request_sha256':digest(req),'fits':True})
        self.assertEqual(output['unextracted_source_ids'], ['bad'])
        self.assertEqual(len(output['errors']), 1)
        self.assertEqual([sid for stage,sid in runner.calls], ['bad','partial','good','partial'])
        self.assertEqual(next(r for r in output['extractions'] if r['source']['id']=='partial')['additional_passes'], 1)
        self.assertFalse(output['quality_gate_passed'])


if __name__ == '__main__': unittest.main()
