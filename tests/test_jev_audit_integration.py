"""Blind graph receipts cannot bypass existing source/owner/compiler vetoes."""
from copy import deepcopy
import unittest

from commentscope.factory import argument_dependencies as deps
from commentscope.factory import argument_observations as obs, source_arguments as sa
from commentscope.providers import openrouter_decisions as od
import test_owner_observations as fixture


def receipt(payload, overrides=None):
    labels = {k: ('value' if k.startswith('kind_') else 'asserted' if k.startswith('authorship_')
                   else 'complete' if k.startswith('coverage_') else 'none')
              for k in payload['questions']}
    labels.update(overrides or {})
    return {'id': 'synthetic', 'model': 'typesafe/jev-1.14-20261014', 'provider': 'TypeSafe',
            'usage': {'cost': 0}, 'answers': {
                k: {'type': 'choice', 'choice': labels[k], 'confidence': 1,
                    'probabilities': {v: int(v == labels[k]) for v in q['criteria']}}
                for k, q in payload['questions'].items()}}


class JevAuditIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.OwnerObservationTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.h = self.f.h

    def checks(self):
        return [deps.bind(t, [receipt(p) for p in deps.requests(t)])
                for r in self.h.records for t in deps.tasks(r, self.h.cores)]

    def audits(self, *, bad_field=None):
        out=[]; checks=self.checks()
        for t in self.f.tasks:
            req=sa.audit_request(self.h.records,self.h.cores,[t],protocol=obs.JEV_SPLIT,core_checks=self.h.checks)
            helper=deepcopy(req)
            for row in helper['data']['TASKS']:
                if row['kind']=='unit':row['LINK_TARGETS']=[]
            result=self.h.result(helper)
            for row in result['output']['observations']:
                row.pop('dependency_fidelity');row.pop('owner_relations',None)
                row['basis']='coverage_agrees' if t['kind']=='coverage' else 'normative_assertion'
                if bad_field and t['kind']=='unit':row[bad_field]='no'
            out.append(sa.bind_audit(self.h.records,self.h.cores,[t],result,protocol=obs.JEV_SPLIT,
                core_checks=self.h.checks,owner_checks=self.f.checks(),dependency_checks=checks))
        return out

    def test_new_protocol_is_explicit_and_all_existing_guards_still_compile(self):
        self.assertNotEqual(sa.SPLIT_AUDIT,obs.JEV_SPLIT)
        self.assertEqual(len(self.h.prepare(self.audits())['compiled']['profiles']),2)
        self.assertEqual(self.h.prepare(self.audits(bad_field='conditions_fidelity'))['compiled']['profiles'],[])

    def test_source_only_request_neither_sees_nor_approves_the_graph(self):
        req=sa.audit_request(self.h.records,self.h.cores,[self.f.tasks[0]],protocol=obs.JEV_SPLIT,core_checks=self.h.checks)
        self.assertNotIn('requires',str(req['data']))
        self.assertNotIn('dependency_fidelity',str(req['schema']))

    def test_receipts_bind_full_source_actual_core_order_and_complete_questions(self):
        checks=self.checks(); task=checks[0]['task']
        with self.assertRaises(ValueError):deps.bind(task,checks[0]['responses'][:-1])
        changed=deepcopy(checks);changed[0]['responses'][0]['answers'].pop(next(iter(changed[0]['responses'][0]['answers'])))
        with self.assertRaises(ValueError):deps.select(self.h.records,self.h.cores,self.f.tasks,changed)
        changed=deepcopy(self.h.cores);changed[0]['candidate']['text']='Different actual core.'
        self.assertNotEqual(deps.tasks(self.h.records[0],changed),deps.tasks(self.h.records[0],self.h.cores))

    def test_missing_receipt_and_legacy_relabel_cannot_approve_agents(self):
        audits=self.audits();audits[0]['dependency_checks']=[]
        with self.assertRaises(ValueError):self.h.prepare(audits)
        audits=self.f.audits();audits[0]['protocol']=obs.JEV_SPLIT
        with self.assertRaises(ValueError):self.h.prepare(audits)

    def test_missing_wrong_and_nonfact_prerequisites_are_rejected_by_host(self):
        t=deps.tasks(self.h.records[0],self.h.cores)[0]
        payloads=deps.requests(t); responses=[receipt(p,{'relation_U2_U1':'necessary_fact'}
            if 'relation_U2_U1' in p['questions'] else {}) for p in payloads]
        check=deps.bind(t,responses)
        guards=deps.guards(self.h.records[0],self.h.cores,[check,self.checks()[1]])
        self.assertIn('missing_factual_prerequisite',guards['U2'])
        self.assertIn('premise_type_or_authorship_unverified',guards['U2'])

    def test_unobserved_or_omitted_premise_never_means_empty_dependencies(self):
        t=deps.tasks(self.h.records[0],self.h.cores)[0]
        responses=[receipt(p,{'coverage_U2':'omitted'} if 'coverage_U2' in p['questions'] else {}) for p in deps.requests(t)]
        checks=[deps.bind(t,responses),self.checks()[1]]
        self.assertIn('premise_coverage_unverified',deps.guards(self.h.records[0],self.h.cores,checks)['U2'])

    def test_all_questions_are_partitioned_without_clipping_inventory(self):
        task=deepcopy(deps.tasks(self.h.records[0],self.h.cores)[0])
        task['units']=[{'id':'U'+str(i),'text':str(i),'evidence':[]} for i in range(1,8)]
        task['targets']={u['id']:{'text':u['text'],'unit_id':u['id']} for u in task['units']}
        payloads=deps.requests(task)
        self.assertGreater(len(payloads),1)
        keys=[k for p in payloads for k in p['questions']]
        self.assertEqual(len(keys),63);self.assertEqual(len(keys),len(set(keys)))
        self.assertTrue(all(len(p['questions'])<=16 and len(p['state']['UNITS'])==7 for p in payloads))
        self.assertTrue(all(p['state']['ORIGINAL']==task['original'] for p in payloads))

    def test_fact_graph_aliases_and_direct_core_edge_have_independent_vetoes(self):
        import json
        from pathlib import Path
        case=json.loads(Path('tests/fixtures/jev-transfer-controls.json').read_text(encoding='utf-8'))['sources'][4]
        checks=[]
        for t in deps.tasks(case['record'],case['cores']):
            results=[]
            for p in deps.requests(t):
                overrides={k:'fact' for k in p['questions'] if k.startswith('kind_')}
                for target,required in (case['expected_local'] if t['kind']=='local' else case['expected_core']).items():
                    overrides.update({'relation_'+target+'_'+a:'necessary_fact' for a in required
                        if 'relation_'+target+'_'+a in p['questions']})
                results.append(receipt(p,overrides))
            checks.append(deps.bind(t,results))
        self.assertFalse(any(deps.guards(case['record'],case['cores'],checks).values()))
        changed=deepcopy(case['record']);changed['units'][2]['core_requires_for']=[]
        self.assertIn('missing_factual_prerequisite',deps.guards(changed,case['cores'],checks)['coverage'])
        changed=deepcopy(case['record']);changed['units'][2]['requires']=['U2']
        self.assertIn('wrong_factual_prerequisite',deps.guards(changed,case['cores'],checks)['U3'])


if __name__=='__main__':unittest.main()
