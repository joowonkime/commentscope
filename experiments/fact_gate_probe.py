"""Frozen 40-case evidence decision benchmark with an explicit mixed provenance.

Thirty Kela-document cases and ten fictional conflicting-document controls.
Assistant-authored development references, not independent gold or real-comment
fact checking. No searches, repairs, candidate promotion or threshold changes.
"""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from commentscope.factory import fact_checks as facts
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.budget import InferenceBudget
from commentscope.storage import write_json_exclusive as write
from experiments.audit_model_compare import owned_server, command, file_hash
from experiments import fact_evidence_probe as base

VERSION = 'mixed-provenance-fact-decision-benchmark-0.1'


def case_definitions():
    actual = {
        'supported': [
            ('dates', 'The Finnish basic income experiment took place in 2017 and 2018.'),
            ('sample', 'The Finnish experiment included 2,000 unemployed participants.'),
            ('age', 'Participants in the Finnish experiment were aged 25 to 58.'),
            ('amount', 'Recipients in the Finnish experiment received 560 euros per month.'),
            ('means', 'Payments in the Finnish experiment were not means-tested.'),
            ('conditions', 'The Finnish experiment made its basic income payments unconditionally.'),
            ('first-year', 'In the first year, the Finnish experiment had no employment effect at group level.'),
            ('wellbeing', 'Basic income recipients responding to the survey described their wellbeing more positively than control respondents.'),
            ('cognition', 'Basic income survey respondents had a more positive perception of their cognitive abilities than control respondents.'),
            ('finances', 'Basic income survey respondents viewed their income and economic wellbeing more positively than control respondents.')],
        'refuted': [
            ('dates', 'The Finnish basic income experiment took place in 2014 and 2015.'),
            ('sample', 'The Finnish experiment included exactly 10,000 basic income recipients.'),
            ('employment', 'All participants selected for the Finnish experiment were employed.'),
            ('age', 'All Finnish experiment recipients were aged 60 to 75.'),
            ('amount', 'Recipients in the Finnish experiment received 1,200 euros per month.'),
            ('means', 'Payments in the Finnish basic income experiment were means-tested.'),
            ('conditions', 'Payments in the Finnish experiment were conditional on the recipients working.'),
            ('first-year', 'The Finnish experiment increased employment by 20 days at group level during its first year.'),
            ('wellbeing', 'Basic income recipients responding to the survey described their wellbeing less positively than control respondents.'),
            ('satisfaction', 'Basic income survey respondents were less satisfied with their lives than control respondents.')],
        'insufficient': [
            ('mortality', 'The Finnish experiment reduced recipient mortality by 20 percent.'),
            ('control-size', 'The Finnish experiment had exactly 2,000 people in its control group.'),
            ('diagnosis', 'Clinical examinations proved that basic income cured depression in every Finnish experiment recipient.'),
            ('inflation', 'The Finnish experiment reduced the national inflation rate by two percentage points.'),
            ('later-policy', 'Finland introduced permanent nationwide basic income for all citizens in 2025.'),
            ('long-term', 'Follow-up research established that the experiment would maintain employment gains until 2050.'),
            ('children', 'Children of Finnish experiment recipients improved their school test scores by ten points.'),
            ('financing', 'A two-percentage-point VAT increase financed the Finnish basic income experiment.'),
            ('crime', 'The Finnish experiment reduced the national crime rate by five percent.'),
            ('net-cost', 'The Finnish experiment had zero net public cost after tax and benefit offsets.')]
    }
    result = []
    for expected, rows in actual.items():
        for key, text in rows:
            result.append({'id': expected+'-'+key, 'text': text, 'expected': expected,
                           'source_cohort': 'actual_kela_document',
                           'reference_reason': ('Explicit scoped statement in the supplied paragraphs.' if expected == 'supported'
                               else 'Opposed by an explicit same-scope statement in the supplied paragraphs.' if expected == 'refuted'
                               else 'The supplied paragraphs establish neither this claim nor its negation.'),
                           'entity': 'Finland national policy' if key == 'later-policy' else 'Finnish basic income experiment',
                           'time': '2025' if key == 'later-policy' else '2050' if key == 'long-term' else '2017 first year' if key == 'first-year' else 'Period stated in claim; otherwise the experiment and its survey'})
    # Deliberately fictional paired documents, never passed off as public sources.
    conflicts = [
        ('sample', 'enrolled exactly 100 adults', 'enrolled exactly 150 adults'),
        ('amount', 'paid each recipient 500 units monthly', 'paid each recipient 700 units monthly'),
        ('means', 'used means testing for eligibility', 'did not use means testing for eligibility'),
        ('employment', 'increased employment by five days per participant', 'had no effect on participant employment'),
        ('location', 'took place entirely in Harbor City', 'took place entirely in Valley City'),
        ('duration', 'lasted exactly twelve months', 'lasted exactly six months'),
        ('ages', 'enrolled only adults aged 25 to 35', 'enrolled only adults aged 45 to 55'),
        ('assignment', 'used randomized assignment', 'did not use randomized assignment'),
        ('response', 'had a survey response rate of 80 percent', 'had a survey response rate of 40 percent'),
        ('conditional', 'required recipients to work to receive payment', 'did not require recipients to work to receive payment')]
    for key, supporting, refuting in conflicts:
        text = 'The fictional Harbor Pilot of 2024 '+supporting+'.'
        result.append({'id': 'conflicting-'+key, 'text': text, 'expected': 'conflicting',
                       'source_cohort': 'synthetic_conflicting_controls', 'entity': 'fictional Harbor Pilot', 'time': '2024',
                       'support_text': text, 'refute_text': 'The fictional Harbor Pilot of 2024 '+refuting+'.',
                       'reference_reason': 'Two equally current fictional reports explicitly disagree about the same pilot and outcome.'})
    return result


def build_rows(source):
    rows = []
    for case in case_definitions():
        claim = {'id': case['id'], 'text': case['text'], 'kind': 'fact', 'requires': [],
                 'scope': {'entity': case['entity'], 'time': case['time'], 'conditions': 'Only the population, modality and comparison stated in the claim'}}
        documents, selections = [deepcopy(source['document'])], deepcopy(source['selections'])
        if case['source_cohort'] == 'synthetic_conflicting_controls':
            documents, selections = [], []
            for index, key in enumerate(['support_text', 'refute_text'], 1):
                doc = {'id': 'fictional-report-'+str(index), 'text': case[key],
                       'url': 'https://example.invalid/fictional-report-'+str(index),
                       'title': 'Fictional report '+str(index), 'publisher': 'Synthetic evaluation fixture',
                       'published_at': '2025-01-01', 'retrieved_at': source['document']['retrieved_at'],
                       'expires_at': source['expires_at'], 'source_kind': 'synthetic'}
                documents.append(doc)
                selections.append({'id': 'E'+str(index), 'document_id': doc['id'],
                                   'span': {'start': 0, 'end': len(doc['text']), 'text': doc['text']}})
        packet = facts.packet(claim, documents, selections, source['expires_at'])
        rows.append({'id': case['id'], 'claim': claim, 'expected': case['expected'],
                     'source_cohort': case['source_cohort'], 'reference_reason': case['reference_reason'],
                     'documents': documents, 'selections': selections, 'packet': packet,
                     'request_sha256': digest(facts.invocation(packet, source['model']))})
    return rows


def prepare(directory, source_directory):
    if directory.exists(): raise ValueError('Never overwrite an attempt')
    base.verify(source_directory)
    source = read_json(source_directory/'plan.json')
    plan = {k: deepcopy(source[k]) for k in ['expires_at', 'model', 'models', 'server', 'runtime']}
    plan.update({'artifact_kind': VERSION, 'rows': build_rows(source),
                 'inputs': {str(source_directory/p): sha(source_directory/p) for p in ['plan.json', 'completed.json', 'report.json']},
                 'code_sha256': {str(p): sha(p) for root in ['src/commentscope', 'experiments'] for p in sorted(Path(root).rglob('*.py'))},
                 'budget': {'cycle_id': base.CYCLE, 'limit_seconds': 28800, 'max_calls': 40, 'timeout_seconds': 90},
                 'criteria': {'unsupported_false_support_max': 0, 'supported_kept_min': 8, 'errors_max': 0},
                 'scope': 'Controlled development benchmark: 30 actual-document cases and 10 fictional conflict controls. Not a real-comment or automatic-retrieval evaluation.',
                 'independent_gold': False, 'quality_gate_passed': False, 'agents': []})
    validate(plan, model_files=True)
    write(directory/'plan.json', plan)
    print({'prepared': True, 'cases': len(plan['rows']), 'counts': dict(Counter(r['expected'] for r in plan['rows'])),
           'plan_sha256': sha(directory/'plan.json'), 'new_model_calls': 0}, flush=True)


def validate(plan, model_files=False):
    facts.live(plan['expires_at'])
    if plan['artifact_kind'] != VERSION or Counter(r['expected'] for r in plan['rows']) != dict.fromkeys(facts.STATES, 10):
        raise ValueError('Expected ten cases for each of four frozen states')
    if len({r['id'] for r in plan['rows']}) != 40: raise ValueError('Duplicate case ID')
    for field in ['inputs', 'code_sha256']:
        if any(sha(p) != h for p, h in plan[field].items()): raise ValueError('Frozen input/code changed')
    for row in plan['rows']:
        bound = facts.packet(row['claim'], row['documents'], row['selections'], plan['expires_at'])
        if bound != row['packet'] or digest(facts.invocation(bound, plan['model'])) != row['request_sha256']:
            raise ValueError('Frozen evidence request changed')
    if model_files:
        for info in [plan['server'], plan['models']['baseline']]:
            if file_hash(info['path']) != info['sha256']: raise ValueError('Deployment changed')


def summarize(plan, records):
    rows = []
    for row, record in zip(plan['rows'], records, strict=True):
        facts.validate_record(record, row['packet'], plan['model'])
        rows.append({'id': row['id'], 'expected': row['expected'], 'actual': record['state'],
                     'source_cohort': row['source_cohort'], 'matches': row['expected'] == record['state']})
    counts = {state: {'total': 10, 'exact': sum(r['matches'] for r in rows if r['expected'] == state),
                      'predictions': dict(Counter(r['actual'] for r in rows if r['expected'] == state))}
              for state in facts.STATES}
    checks = {'unsupported_false_support': sum(r['expected'] != 'supported' and r['actual'] == 'supported' for r in rows),
              'supported_kept': sum(r['expected'] == 'supported' and r['actual'] == 'supported' for r in rows),
              'errors': sum(r['actual'] in {'error', 'unassessed'} for r in rows)}
    return {'rows': rows, 'by_reference': counts, **checks,
            'fact_decision_development_gate_passed': checks['unsupported_false_support'] == 0 and checks['supported_kept'] >= 8 and checks['errors'] == 0,
            'request_elapsed_seconds': sum(r['result']['seconds'] for r in records),
            'scope': plan['scope'], 'independent_gold': False, 'quality_gate_passed': False, 'agents': []}


def execute(directory):
    plan = read_json(directory/'plan.json'); validate(plan, model_files=True)
    budget = InferenceBudget(base.DEFAULT_BUDGET, base.CYCLE)
    plan_sha = sha(directory/'plan.json')
    write(directory/'started.json', {'plan_sha256': plan_sha, 'budget_path': str(base.DEFAULT_BUDGET), 'budget_before': budget.summary()})
    provider = budget.provider(plan_sha, timeout_seconds=plan['budget']['timeout_seconds'])
    records = []
    with owned_server(plan, 'baseline', directory/'server'):
        for row in plan['rows']:
            record = facts.check(row['packet'], plan['model'], provider)
            write(directory/(row['id']+'.json'), record); records.append(record)
            print(json.dumps({'case': row['id'], 'state': record['state'], 'seconds': round(record['result']['seconds'], 2)}), flush=True)
    report = summarize(plan, records); report['budget_after'] = budget.summary()
    write(directory/'report.json', report)
    write(directory/'completed.json', {'plan_sha256': plan_sha, 'report_sha256': sha(directory/'report.json')})
    print(json.dumps({k: v for k, v in report.items() if k not in {'rows', 'budget_after'}}, indent=2))


def verify(directory):
    plan = read_json(directory/'plan.json'); validate(plan)
    if read_json(directory/'completed.json') != {'plan_sha256': sha(directory/'plan.json'), 'report_sha256': sha(directory/'report.json')}:
        raise ValueError('Completion binding changed')
    if read_json(directory/'started.json')['plan_sha256'] != sha(directory/'plan.json'):
        raise ValueError('Started plan changed')
    report = read_json(directory/'report.json')
    records = [read_json(directory/(row['id']+'.json')) for row in plan['rows']]
    if any(report[k] != v for k, v in summarize(plan, records).items()): raise ValueError('Report does not replay')
    if read_json(directory/'server/runtime.json')['command'] != command(plan, 'baseline'): raise ValueError('Runtime changed')
    if read_json(directory/'server/stopped.json')['returncode'] != 0: raise ValueError('Unclean server exit')
    print({'verified': True, 'new_model_calls': 0, 'cases': 40})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--source-dir', type=Path, default=Path('runs/fact-evidence-8b-20261013'))
    parser.add_argument('--phase', choices=['prepare', 'run', 'verify'], required=True)
    args = parser.parse_args()
    if args.phase == 'prepare': prepare(args.run_dir, args.source_dir)
    elif args.phase == 'run': execute(args.run_dir)
    else: verify(args.run_dir)


if __name__ == '__main__': main()
