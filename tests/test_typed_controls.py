"""Control reports separate source observations from host-only mutations."""
import unittest
from tools import typed_verification_controls as controls
from test_remote_verification import parsed


class SyntheticSession:
    def __init__(self,bad_norm=False):self.calls=0;self.bad_norm=bad_norm
    def call(self,stage,req):
        self.calls+=1
        if 'OWNER_POSITION' in req['data']:
            source=req['data']['ORIGINAL_CONTEXT_ONLY']['source_id'];ok=source=='video_metadata_only'
            return {'output':{'relation':'equivalent' if ok else 'different','basis':'same_assertion' if ok else 'different_scope',
                 'owner_world':'fictional_world' if source=='explicit_novel' else 'real_world','candidate_world':'real_world'}}
        state=req['data']['state']
        original=state['ORIGINAL'];fact=original.startswith(('Room A','북쪽'))
        output={k:('fact' if fact else 'prediction' if original.startswith('I favor') and k=='kind_U2' else 'value')
                  if k.startswith('kind_') else 'asserted' if k.startswith('authorship_') else 'complete' if k.startswith('coverage_') else 'none'
                for k in req['schema']['properties']}
        if original.startswith('Some people'):output.update({k:'not_asserted' for k in output if k=='authorship_U1'})
        if fact:
            for k in output:
                if k in ('relation_C1_U1','relation_C1_U3'):output[k]='restatement'
                if k=='relation_U3_U1':output[k]='necessary_fact'
            if len(state['UNITS'])==2:
                for k in output:
                    if k=='relation_C1_U1':output[k]='none'
                    if k=='relation_C1_U2':output[k]='restatement'
                    if k=='coverage_U2':output[k]='omitted'
        elif self.bad_norm and original=='Require public hearings. Accessibility matters.':
            if 'relation_C1_U1' in output:output['relation_C1_U1']='necessary_fact'
        return parsed(output)


class TypedControlsTests(unittest.TestCase):
    def test_all_cases_are_explained_and_mutations_do_not_make_new_model_calls(self):
        session=SyntheticSession();saved={};report=controls.execute(session,lambda k,v:saved.update({k:v}))
        self.assertTrue(report['all_expected']);self.assertEqual(report['positive_kept'],8)
        self.assertEqual(report['false_approval'],0);self.assertEqual(report['negative_total'],10)
        self.assertEqual(len(report['cases']),18);self.assertEqual(session.calls,14)
        self.assertFalse(report['quality_gate_passed']);self.assertIn('control-records',saved)

    def test_a_normal_type_conflict_is_recorded_without_claiming_all_pass(self):
        report=controls.execute(SyntheticSession(True),lambda k,v:None)
        self.assertFalse(report['all_expected']);self.assertEqual(report['false_approval'],0)
        self.assertEqual(report['positive_kept'],7)


if __name__=='__main__':unittest.main()
