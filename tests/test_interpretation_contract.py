from copy import deepcopy
from itertools import product
import unittest

from commentscope.factory import contextual_interpretation as ci
from commentscope.factory import explicit_discourse as ed, literal_discovery as ld
from test_contextual_propositions import original
from test_contextual_identity import value


def accepted_branches(schema, output):
    # This contract uses only strict complete objects and string enumerations.
    # Actual llama grammar acceptance is covered by a separate frozen model run.
    matches=[]
    for branch in schema['anyOf']:
        if (branch['type']=='object' and branch['additionalProperties'] is False
                and set(output)==set(branch['required'])==set(branch['properties'])
                and all(isinstance(output[k],str) and output[k] in p['enum']
                        for k,p in branch['properties'].items())):
            matches.append(branch)
    return matches


class InterpretationContractTests(unittest.TestCase):
    def test_setting_is_available_only_for_the_existing_initial_heading_contract(self):
        for text in ('Every passenger keeps their own ticket.','Every visitor keeps their own pass.'):
            graph=ed.parse(original(text));node=ld.roots(graph)[0];output=value(function='setting')
            self.assertFalse(accepted_branches(ci.request(graph,node)['schema'],output))
            with self.assertRaises(ValueError):ci.bind(graph,node,{'output':output})
            old=ci.bind(graph,node,{'output':output},ci.CONSTRAINED)
            self.assertEqual(ci.decision(graph,node,old)['contribution'],'context')
        graph=ed.parse(original('Moon Colony! Everyone has food.'));node=ld.roots(graph)[0]
        self.assertEqual(len(accepted_branches(ci.request(graph,node)['schema'],value(function='setting'))),1)

    def test_wire_grammar_and_binder_agree_for_every_authorship_function_cue_combination(self):
        for text in ('Several towns fund night buses.',
                     'My neighbor said "Trains should run overnight."',
                     'Look at the study "Forest Cities".'):
            graph=ed.parse(original(text));node=ld.roots(graph)[0]
            req=ci.request(graph,node);props=ci.output_properties(graph,node)
            for function,author,cue in product(ci.FUNCTIONS,('author','other','unclear'),
                                               props['attribution_cue']['enum']):
                output=value(function=function,authorship=author,attribution_cue=cue)
                matches=accepted_branches(req['schema'],output)
                # No overlapping branch can silently select a different role.
                self.assertLessEqual(len(matches),1)
                if matches:
                    record=ci.bind(graph,node,{'output':output})
                    self.assertFalse(record['semantic_approval'])
                else:
                    with self.assertRaises(ValueError):ci.bind(graph,node,{'output':output})

    def test_actual_failure_shapes_are_not_generatable_or_repaired(self):
        graph=ed.parse(original('I recommend the study "Forest Cities".'));node=ld.roots(graph)[0]
        req=ci.request(graph,node)
        for output in (value(attribution_cue='A1'),value(authorship='other'),
                       value(function='reported_view'),value(attribution_cue='A999'),
                       {**value(),'invented_quote':'Trains are bad.'}):
            self.assertFalse(accepted_branches(req['schema'],output))
            before=deepcopy(output)
            with self.assertRaises(ValueError):ci.bind(graph,node,{'output':output})
            self.assertEqual(output,before)

    def test_title_and_other_speech_remain_semantic_choices_not_automatic_approval(self):
        graph=ed.parse(original('Some people say "Museum tickets should be free."'));node=ld.roots(graph)[0]
        for output in (value(),value(authorship='other',attribution_cue='A1'),
                       value(function='reported_view',attribution_cue='A1'),
                       value(authorship='unclear',attribution_cue='A1')):
            self.assertEqual(len(accepted_branches(ci.request(graph,node)['schema'],output)),1)
            self.assertFalse(ci.bind(graph,node,{'output':output})['semantic_approval'])

    def test_v2_requests_and_records_remain_flat_and_exactly_replayable(self):
        graph=ed.parse(original('I believe garden fees should be waived.'));node=ld.roots(graph)[0]
        req=ci.request(graph,node,ci.ATTRIBUTED)
        self.assertNotIn('anyOf',req['schema'])
        record=ci.bind(graph,node,{'output':value()},ci.ATTRIBUTED)
        self.assertEqual(ci.decision(graph,node,record)['authorship'],'asserted')
        self.assertEqual(record,ci.bind(graph,node,{'output':record['output']},record['artifact_kind']))
        current=ci.bind(graph,node,{'output':value()})
        self.assertNotEqual(record['request_sha256'],current['request_sha256'])


if __name__=='__main__':unittest.main()
