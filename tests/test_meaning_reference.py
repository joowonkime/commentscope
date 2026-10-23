from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.storage import write_json_exclusive as write
from experiments import meaning_reference as m
from tests import test_stance_agents as fixtures


class MeaningReferenceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name); self.snapshot_path = self.root/'snapshot.json'
        fixture = fixtures.StanceAgentTests(); fixture.setUp(); self.snapshot = fixture.snapshot
        write(self.snapshot_path, self.snapshot.to_dict())
        self.ids = list(m.utilization._canonical(self.snapshot))
        self.protocol = self.root/'protocol.json'
        write(self.protocol, {'artifact_kind': 'offline-meaning-reference-protocol-0.1',
              'goal_revision': m.utilization.GOAL_REVISION, 'snapshot_file_sha256': sha(self.snapshot_path),
              'canonical_population': len(self.ids), 'evaluator': 'synthetic-not-real-reference'})

    def part(self, start, end, label='meaningful', name='part.json'):
        path = self.root/name
        write(path, {'artifact_kind': 'offline-meaning-reference-part-0.1',
            'snapshot_file_sha256': sha(self.snapshot_path), 'evaluator': 'synthetic-not-real-reference',
            'canonical_indices': [start, end], 'rows': [
                {'source_id': self.ids[i], 'eligibility': label, 'reason': 'Synthetic fixture judgment.'}
                for i in range(start, end+1)]})
        return path

    def test_partial_is_reported_not_frozen_or_sample_pass(self):
        part = self.part(0, 1)
        report, reference = m.assemble(self.snapshot_path, self.protocol, [part])
        self.assertEqual(report['missing_indices'], list(range(2, len(self.ids))))
        self.assertFalse(report['ready_to_freeze']); self.assertIsNone(reference)
        with patch.object(m, 'PRIVATE_ROOT', self.root):
            with self.assertRaises(ValueError): m.freeze(self.root/'output', self.snapshot_path, self.protocol, [part])
        self.assertFalse((self.root/'output').exists())

    def test_whole_reference_and_source_hashes(self):
        a = self.part(0, 1); b = self.part(2, len(self.ids)-1, 'non_substantive', 'part2.json')
        report, reference = m.assemble(self.snapshot_path, self.protocol, [b, a])
        self.assertTrue(report['ready_to_freeze']); self.assertEqual(reference['scope'], 'full_corpus')
        m.utilization._validate_reference(self.snapshot, reference, digest(reference))
        self.assertEqual(report['eligibility_counts']['non_substantive'], len(self.ids)-2)

    def test_overlap_and_displacement_are_rejected(self):
        a = self.part(0, 2); b = self.part(2, len(self.ids)-1, name='part2.json')
        with self.assertRaises(ValueError): m.assemble(self.snapshot_path, self.protocol, [a, b])
        changed = read_json(a); changed['rows'].reverse()
        bad = self.root/'bad.json'; write(bad, changed)
        with self.assertRaises(ValueError): m.assemble(self.snapshot_path, self.protocol, [bad])

    def test_changed_snapshot_or_evaluator_rejected(self):
        a = self.part(0, len(self.ids)-1)
        for key, value in [('snapshot_file_sha256', '0'*64), ('evaluator', 'different')]:
            changed = read_json(a); changed[key] = value
            bad = self.root/(key+'.json'); write(bad, changed)
            with self.assertRaises(ValueError): m.assemble(self.snapshot_path, self.protocol, [bad])

    def test_uncertainty_blocks_freeze_and_explicit_revisions_preserve_draft(self):
        a = self.part(0, len(self.ids)-1, 'uncertain'); before = sha(a)
        report, reference = m.assemble(self.snapshot_path, self.protocol, [a]); self.assertIsNone(reference)
        sources = m.utilization._canonical(self.snapshot)
        revision = self.root/'revisions.json'; write(revision, {
            'artifact_kind': 'offline-meaning-reference-revisions-0.1', 'snapshot_file_sha256': sha(self.snapshot_path),
            'draft_inputs': report['inputs'], 'rows': [{'source_id': sid, 'source_sha256': digest(sources[sid]),
                'previous_eligibility': 'uncertain', 'eligibility': 'meaningful',
                'reason': 'Re-examined original context before outputs.'} for sid in self.ids]})
        result, reference = m.assemble(self.snapshot_path, self.protocol, [a], revision)
        self.assertTrue(result['ready_to_freeze']); self.assertEqual(result['revision_count'], len(self.ids))
        self.assertEqual(sha(a), before); self.assertIn(str(revision), result['inputs'])

    def test_freeze_private_manifest_no_overwrite(self):
        part = self.part(0, len(self.ids)-1); output = self.root/'runs'/'frozen'
        with patch.object(m, 'PRIVATE_ROOT', self.root/'runs'):
            reference = m.freeze(output, self.snapshot_path, self.protocol, [part])
            self.assertEqual(read_json(output/'manifest.json')['reference_sha256'], digest(reference))
            with self.assertRaises(ValueError): m.freeze(output, self.snapshot_path, self.protocol, [part])
            with self.assertRaises(ValueError): m.freeze(self.root/'public', self.snapshot_path, self.protocol, [part])


if __name__ == '__main__': unittest.main()
