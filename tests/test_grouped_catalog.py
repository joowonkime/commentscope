import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.perspective_groups.catalog import load_record, read, register, write_json
from tools.perspective_groups.prepare import prepare
from test_team_group_discovery import FakeClient, comment


class PreparationClient(FakeClient):
    model = 'gpt-fixture'
    def structured(self, system, payload, schema, name):
        if name == 'comment_filter':
            return {'data':{'decisions':[{'comment_id':c['comment_id'],'status':'keep','category':'opinion',
                                         'confidence':0.98,'reason':'Synthetic opinion'} for c in payload['comments']]},
                    'model':self.model,'usage':{}}
        return super().structured(system,payload,schema,name)


class GroupedCatalogTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.at = datetime.now(timezone.utc).isoformat()
        self.rows = [comment('a','찬성'),comment('b','반대'),comment('c','소수 대안'),comment('d','동의','a')]
        self.source = {'meta':{'video_id':'example1234','title':'Example','collected_at':self.at},
                       'comments':self.rows}
        self.record = prepare(self.source,self.directory,PreparationClient())

    def test_generated_groups_supply_actual_participants_and_scoped_reasons(self):
        analysis = load_record(self.record)
        views = analysis.public()['perspectives']
        self.assertEqual({p['id'] for p in views},{'g1','g2'})
        for view in views:
            allowed = analysis.allowed(view['id'])
            self.assertTrue(view['grounds'])
            for entry in allowed['allowed_entries']:
                for evidence in entry['citations']['comment_evidence']:
                    self.assertIn(evidence['source_id'],view['group']['members'])
                    self.assertEqual(evidence['span']['text'],analysis.source(evidence['source_id'])['text'])
        self.assertEqual(analysis.source('d')['PARENT_CONTEXT_ONLY']['text'],'찬성')

    def test_changed_parent_and_its_reply_are_withheld(self):
        refreshed = {'checked_at':self.at,'video_id':'example1234','requested_ids':[r['comment_id'] for r in self.rows],
                     'comments':{r['comment_id']:{'textDisplay':r['text'],'parentId':r['parent_id'],'likeCount':1} for r in self.rows}}
        refreshed['comments']['a']['textDisplay']='Changed to the opposite'
        with self.assertRaisesRegex(ValueError,'stance evidence'):
            register(self.directory,refresh=refreshed)

    def test_record_hash_binds_the_display_pool(self):
        self.record['presentation']['grouping']['retained'] += 1
        with self.assertRaisesRegex(ValueError,'presentation'):
            load_record(self.record)

    def test_prepared_persona_cannot_drift_from_the_groups(self):
        agent_path = self.directory/'03_agents/agents.json'
        staged = read(agent_path)
        self.assertEqual(staged['meta']['agent_count'], 2)
        staged['agents'][0]['stance'] = 'Unrelated position'
        write_json(agent_path, staged)
        with self.assertRaisesRegex(ValueError, 'bundle content changed'):
            register(self.directory)
