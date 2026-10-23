"""Topic-independent surface grammar tests; no semantic accuracy claim."""
from copy import deepcopy
import unittest
from commentscope.factory import explicit_discourse as ed


def parse(text,sid='source'):
    return ed.parse({'id':sid,'text':text,'parent':None})


def edge_texts(record):
    nodes={n['id']:n for n in record['nodes']}
    return [(e['relation'],nodes[e['parent_id']]['span']['text'],nodes[e['ground_id']]['span']['text']) for e in record['edges']]


class ExplicitDiscourseTests(unittest.TestCase):
    def test_leading_considering_premise_is_not_hidden_inside_the_value_position(self):
        text='Considering we spend upwards of $50,000 per prisoner per year, UBI seems like a deal.'
        graph=parse(text)
        self.assertEqual(edge_texts(graph),[('reason','UBI seems like a deal.',
            'Considering we spend upwards of $50,000 per prisoner per year,')])
        self.assertFalse(graph['holds']);ed.validate(graph)
        nodes={n['id']:n for n in graph['nodes']};edge=graph['edges'][0]
        self.assertEqual(ed.ground_for(graph,edge['id'],edge['parent_id'])['ground'],nodes[edge['ground_id']])
        for topic in ['the archive','the clinic','the train route']:
            other=parse(f'Considering that {topic} costs $1,000 a year, keeping it open seems worthwhile.')
            self.assertEqual(len(other['edges']),1);self.assertFalse(other['holds'])

    def test_ambiguous_or_incomplete_leading_premises_stay_held(self):
        for text in ['Considering costs, delays, and access, choose P.',
                     'Considering costs choose P.','Considering, choose P.',
                     'Considering costs, .','We are considering costs, choose P.',
                     'Considering costs because demand is high, choose P.']:
            with self.subTest(text=text):
                graph=parse(text);self.assertTrue(graph['holds']);self.assertFalse(graph['edges'])
                self.assertEqual(graph['nodes'][0]['span']['text'],text)

    def test_reason_belongs_to_its_own_statement_not_previous_topic(self):
        record=parse('Preserve the archive. Open on Sunday because weekdays are busy.')
        self.assertEqual(edge_texts(record),[('reason','Open on Sunday','because weekdays are busy.')])
        self.assertEqual(record['nodes'][0]['span']['text'],'Preserve the archive.')
        self.assertFalse(record['semantic_approval']);self.assertFalse(record['attribution_verified'])
        self.assertEqual(record['model_calls'],0);ed.validate(record)

    def test_independent_statements_and_uncertainty_never_create_implicit_edges(self):
        for text in ('The route is short. I am unsure whether it is accessible.',
                     'Keep the park public. Also add accessible paths.',
                     '책임이 중요합니다. 시행 시점은 아직 결정하지 못했습니다.'):
            record=parse(text);self.assertFalse(record['edges']);self.assertEqual(len(record['nodes']),2)

    def test_concessions_are_separate_without_becoming_conditions(self):
        for connector in ('although','even though','ALTHOUGH'):
            record=parse('I prefer rail '+connector+' it may be slower.')
            self.assertEqual(edge_texts(record),[('concession','I prefer rail',connector+' it may be slower.')])
            self.assertFalse(record['holds'])

    def test_condition_remains_in_complete_parent(self):
        for connector in ('only if','only when','ONLY IF'):
            text='I agree '+connector+' all shifts are covered.';record=parse(text)
            self.assertEqual(edge_texts(record),[('necessary_condition',text,connector+' all shifts are covered.')])
        text='추가 비용이 없을 때만 이 계획에 찬성합니다.'
        self.assertEqual(edge_texts(parse(text)),[('necessary_condition',text,'추가 비용이 없을 때만')])

    def test_korean_explicit_causal_fragment_keeps_adjacent_parent_and_full_text(self):
        text='회의를 온라인으로 진행해야 합니다. 이동 시간을 줄이기 때문입니다.'
        record=parse(text)
        self.assertEqual(edge_texts(record),[('reason','회의를 온라인으로 진행해야 합니다.','이동 시간을 줄이기 때문입니다.')])
        self.assertFalse(record['holds'])
        self.assertFalse(parse('이동 시간을 줄이기 때문입니다.')['edges'])
        self.assertFalse(parse('회의를 온라인으로 진행해야 합니다.\n\n이동 시간을 줄이기 때문입니다.')['edges'])

    def test_quotation_content_cannot_become_an_own_reason(self):
        record=parse('They say "Quit because it is difficult." I disagree: continue.')
        self.assertFalse(record['edges'])
        self.assertEqual(record['nodes'][-1]['span']['text'],'I disagree: continue.')
        self.assertEqual(record['nodes'][0]['kind'],'unresolved_statement')
        self.assertEqual(record['quotation_ranges'][0]['text'],'"Quit because it is difficult."')
        self.assertFalse(parse('They say “Quit because it is difficult.”')['edges'])

    def test_unbalanced_quotes_negated_nested_and_unknown_operators_are_preserved(self):
        texts=['Use P not because Q but because R.','Use P because Q only if R.',
               'Use P unless Q.','Use P since Q.','Use P (because Q).',
               'Why use P because Q?','"Use P because Q.','Only if Q, use P.']
        for text in texts:
            with self.subTest(text=text):
                record=parse(text);self.assertTrue(record['holds']);self.assertFalse(record['edges'])
                self.assertEqual(record['source']['text'],text)
                self.assertEqual(record['nodes'][0]['span']['text'],text)

    def test_topic_substitution_and_whitespace_do_not_change_parent_rule(self):
        topics=['library','train route','community clinic','audio archive','ocean survey','school garden']
        for topic in topics:
            for space in (' ','  ','\t'):
                text=f'Keep the {topic}.{space}Open it earlier{space}because visitors arrive early.'
                record=parse(text);edges=edge_texts(record)
                self.assertEqual(len(edges),1)
                self.assertEqual(edges[0],('reason','Open it earlier','because visitors arrive early.'))
                self.assertFalse(record['holds'])

    def test_apostrophe_and_abbreviation_do_not_break_source_boundaries(self):
        record=parse("Dr. Lee's team prefers rail because it doesn't require parking.")
        self.assertEqual(len(record['statements']),1);self.assertEqual(len(record['edges']),1)
        self.assertFalse(record['quotation_ranges']);self.assertFalse(record['holds'])

    def test_exact_reproducibility_and_graph_mutation_rejection(self):
        source={'id':'s','text':'Use buses because air quality matters.','parent':None}
        record=ed.parse(source)
        self.assertEqual(record,ed.parse(deepcopy(source)))
        for mutate in (lambda r:r['edges'][0].update(parent_id='other_source'),
                       lambda r:r['nodes'][0]['span'].update(text='Generated claim.'),
                       lambda r:r['source'].update(parent={'id':'new','text':'Different context.'}),
                       lambda r:r.update(semantic_approval=True)):
            changed=deepcopy(record);mutate(changed)
            with self.assertRaises(ValueError):ed.validate(changed)

    def test_source_has_no_video_candidate_or_gold_parameters(self):
        source={'id':'any-video-comment','text':'Use buses because air quality matters.','parent':None}
        with self.assertRaises(ValueError):ed.parse({**source,'candidate':'Use buses.'})
        first=ed.parse(source);second=ed.parse({**source,'id':'another-video-comment'})
        self.assertEqual(edge_texts(first),edge_texts(second))
        self.assertNotEqual(first['edges'][0]['id'],second['edges'][0]['id'])

    def test_ground_export_refuses_different_position_or_other_source(self):
        graph=parse('Preserve the archive. Open on Sunday because weekdays are busy.')
        edge=graph['edges'][0]
        proof=ed.ground_for(graph,edge['id'],edge['parent_id'])
        self.assertEqual(proof['position']['span']['text'],'Open on Sunday')
        self.assertFalse(proof['candidate_alignment_verified'])
        with self.assertRaises(ValueError):ed.ground_for(graph,edge['id'],graph['nodes'][0]['id'])
        other=parse('Preserve the archive. Open on Sunday because weekdays are busy.',sid='another')
        with self.assertRaises(ValueError):ed.ground_for(other,edge['id'],edge['parent_id'])


if __name__=='__main__':unittest.main()
