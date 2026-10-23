from copy import deepcopy
import unittest

from commentscope.factory import batch_stances as batch
from commentscope.providers.generation_limits import allocate
from commentscope.providers.host_resources import POLICY
from experiments import model_selection_20261016 as p


class ModelSelectionTests(unittest.TestCase):
    def test_preflight_rejects_each_resource(self):
        host = {'available_mb': 5000, 'committed_bytes': 4*1024**3,
                'commit_limit': 16*1024**3, 'disk_free_bytes': 10*1024**3}
        self.assertEqual(p.preflight_reasons(host, 7000), [])
        for key, value, reason in [('available_mb', 2000, 'idle_ram'),
                                   ('committed_bytes', 14*1024**3, 'idle_commit'),
                                   ('disk_free_bytes', 1024**3, 'low_host_disk')]:
            low = {**host, key: value}
            self.assertIn(reason, p.preflight_reasons(low, 7000))
        self.assertIn('idle_gpu', p.preflight_reasons(host, 6000))

    def test_modes_differ_only_in_thinking(self):
        base = {'server': {'path': '/unused'}, 'models': {'baseline': {'path': '/unused'}},
                'runtime': {'threads': 6, 'memory_profile': {
                    'version': 'local-memory-profile-0.4', 'load_mode': 'mmap',
                    'cache_ram_mib': 0, 'cache_idle_slots': False, 'host_resource_policy': deepcopy(POLICY),
                    'kv_cache': {'k': 'q8_0', 'v': 'q8_0'}, 'flash_attention': 'on', 'batch_size': 512,
                    'ubatch_size': 128, 'host_buffer': False, 'repack': False,
                    'device': 'none', 'op_offload': False}}}
        original = deepcopy(base)
        off, on = p.deployment(base, 'off'), p.deployment(base, 'on')
        self.assertEqual(base, original)
        for key in ('reasoning', 'reasoning_budget', 'template_kwargs'):
            off['runtime'].pop(key); on['runtime'].pop(key)
        self.assertEqual(off, on)
        self.assertEqual(off['runtime']['gpu_layers'], 99)
        self.assertEqual(off['runtime']['memory_profile']['host_resource_policy'], POLICY)
        with self.assertRaises(ValueError): p.deployment(base, 'auto')

    def test_authored_target_is_explicit_unapproved_fixture(self):
        target = p.fixed_candidate()
        batch.validate_candidate(target)
        self.assertFalse(target['semantic_approval'])
        self.assertEqual(target['nominee_source_ids'], ['fixture'])

    def test_equal_answer_capacity(self):
        request = {'system': 's', 'data': {}, 'schema': {}, 'max_tokens': 3072}
        off = allocate(request, {'context': 8192, 'reasoning': 'off', 'reasoning_budget': 0})
        on = allocate(request, {'context': 8192, 'reasoning': 'on', 'reasoning_budget': 1024})
        self.assertEqual(off['max_tokens'], 3072)
        self.assertEqual(on['max_tokens'], 4096)
        self.assertEqual(request['max_tokens'], 3072)

    def test_transfer_labels_not_in_request(self):
        items = [{'id': sid, 'text': text, 'parent': None} for sid, text, _ in p.TRANSFER]
        candidate = p.fixed_candidate()
        request = batch.membership_request(items, [candidate], [
            {'source_id': item['id'], 'candidate_id': candidate['id']} for item in items])
        self.assertEqual(set(request['data']), {'ORIGINALS', 'CANDIDATES', 'PAIRS'})
        self.assertNotIn('reference', request['data'])


if __name__ == '__main__': unittest.main()
