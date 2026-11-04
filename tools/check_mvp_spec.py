"""Check repository spec references and work dependencies, never model quality."""
import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from commentscope.factory import acceptance  # noqa: E402


KINDS = {'code', 'offline', 'limited_live', 'formal_gate', 'product_e2e'}
# Stable baseline IDs: changing product scope must be explicit in code review too.
PRODUCT_REQUIREMENTS = {'Explore': {'REQ-004'}, 'Converse': {'REQ-005', 'REQ-006'},
                        'Reflect': {'REQ-007'}}


def validate(document, root=ROOT):
    """Return structural errors. Evidence statements still require actual review."""
    errors = []
    if not isinstance(document, dict):
        return ['spec must be an object']
    if type(document.get('schema_version')) is not int or document['schema_version'] != 1:
        errors.append('unsupported schema_version')

    def nonempty(value):
        return isinstance(value, str) and bool(value.strip())

    def choice(value, options):
        return isinstance(value, str) and value in options

    def strings(value, label, required=False):
        if (not isinstance(value, list) or any(not nonempty(x) for x in value)
                or required and not value):
            errors.append(f'{label}: expected a list of nonempty strings')
            return []
        if len(value) != len(set(value)):
            errors.append(f'{label}: duplicate values')
        return value

    def reference(value, label, external=True):
        if not nonempty(value):
            errors.append(f'{label}: missing reference')
            return None
        if external and value.startswith('https://'):
            try:
                if urlsplit(value).netloc:
                    return None
            except ValueError:
                errors.append(f'{label}: invalid external reference')
                return None
        path = Path(value.split('#', 1)[0])
        resolved = (root / path).resolve()
        if path.is_absolute() or not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
            errors.append(f'{label}: invalid repository reference {value}')
            return None
        return resolved

    def records(key, prefix):
        value = document.get(key)
        result = {}
        if not isinstance(value, list) or not value:
            errors.append(f'{key}: expected nonempty records')
            return result
        for row in value:
            if not isinstance(row, dict) or not isinstance(row.get('id'), str):
                errors.append(f'{key}: invalid record/id')
                continue
            ident = row['id']
            if not re.fullmatch(prefix + r'-\d{3}', ident):
                errors.append(f'{key}: invalid ID {ident}')
            if ident in result:
                errors.append(f'{key}: duplicate ID {ident}')
            if not nonempty(row.get('title')):
                errors.append(f'{ident}: missing title')
            result[ident] = row
        return result

    def evidence(row):
        value = row.get('evidence')
        if not isinstance(value, list):
            errors.append(f'{row["id"]}: evidence must be a list')
            return []
        valid = []
        for item in value:
            if (not isinstance(item, dict) or not choice(item.get('kind'), KINDS)
                    or not choice(item.get('result'), {'pass', 'fail', 'partial'})
                    or any(not nonempty(item.get(k)) for k in ('scope', 'reference'))):
                errors.append(f'{row["id"]}: invalid evidence kind/scope/reference/result')
            else:
                valid.append(item)
        return valid

    for key in ('spec_version', 'baseline_commit', 'observed_date'):
        if not nonempty(document.get(key)):
            errors.append(f'missing {key}')
    for key in ('intent_document', 'workflow_document'):
        reference(document.get(key), key, external=False)
    if 'design_version' in document or 'design_document' in document:
        if not nonempty(document.get('design_version')):
            errors.append('missing design_version')
        reference(document.get('design_document'), 'design_document', external=False)

    contract = document.get('acceptance_contract')
    if not isinstance(contract, dict):
        errors.append('missing r5 acceptance_contract')
    else:
        path = reference(contract.get('path'), 'r5 contract', external=False)
        if path is not None:
            try:
                profile = json.loads(path.read_text(encoding='utf-8'))
                acceptance.validate(profile, contract.get('digest'))
            except (ValueError, OSError) as exc:
                errors.append(f'r5 acceptance contract: {exc}')

    requirements = records('requirements', 'REQ')
    tasks = records('tasks', 'TASK')
    decisions = records('decisions', 'DEC')
    for row in [*requirements.values(), *tasks.values(), *decisions.values()]:
        if 'design_refs' in row:
            for value in strings(row['design_refs'], f'{row["id"]}.design_refs', required=True):
                reference(value, f'{row["id"]}.design_refs', external=False)

    def links(row, key, target, required=False):
        values = strings(row.get(key), f'{row["id"]}.{key}', required)
        for ident in values:
            if ident not in target:
                errors.append(f'{row["id"]}.{key}: unknown reference {ident}')
        return values

    product = document.get('product_tasks')
    if not isinstance(product, dict) or set(product) != set(PRODUCT_REQUIREMENTS):
        errors.append('product_tasks must retain Explore, Converse and Reflect')
    else:
        for name, values in product.items():
            identifiers = strings(values, f'product_tasks.{name}', required=True)
            for ident in PRODUCT_REQUIREMENTS[name] - set(identifiers):
                errors.append(f'product_tasks.{name}: must retain baseline requirement {ident}')
            for ident in identifiers:
                if ident not in requirements:
                    errors.append(f'product_tasks.{name}: unknown reference {ident}')

    for ident, row in requirements.items():
        if not choice(row.get('implementation'), {'not_implemented', 'partial', 'implemented'}):
            errors.append(f'{ident}: invalid implementation status')
        for key in ('sources', 'code', 'checks'):
            for value in strings(row.get(key), f'{ident}.{key}', required=key == 'sources'):
                reference(value, f'{ident}.{key}', external=key == 'sources')
        strings(row.get('acceptance'), f'{ident}.acceptance', required=True)
        proof = evidence(row)
        if row.get('implementation') == 'implemented' and not proof:
            errors.append(f'{ident}: implemented needs scoped evidence')

    for ident, row in decisions.items():
        if not choice(row.get('status'), {'open', 'proposed', 'accepted', 'rejected'}):
            errors.append(f'{ident}: invalid decision status')
        links(row, 'requirements', requirements, required=True)
        if not nonempty(row.get('question')):
            errors.append(f'{ident}: missing decision question')
        strings(row.get('options'), f'{ident}.options', required=True)
        proof = evidence(row)
        if choice(row.get('status'), {'accepted', 'rejected'}):
            if not nonempty(row.get('selection')) or not proof:
                errors.append(f'{ident}: resolved decision needs selection and scoped evidence')

    dependencies = {}
    covered = set()
    for ident, row in tasks.items():
        covered.update(links(row, 'requirements', requirements, required=True))
        links(row, 'decisions', decisions)
        dependencies[ident] = links(row, 'depends_on', tasks)
        for key in ('deliverables', 'done_when'):
            strings(row.get(key), f'{ident}.{key}', required=True)
        kinds = strings(row.get('required_evidence'), f'{ident}.required_evidence', required=True)
        if any(kind not in KINDS - {'code'} for kind in kinds):
            errors.append(f'{ident}: invalid required_evidence kind')
        status = row.get('status')
        if not choice(status, {'todo', 'next', 'in_progress', 'done', 'deferred'}):
            errors.append(f'{ident}: invalid task status')
        proof = evidence(row)
        if choice(status, {'next', 'in_progress', 'done'}):
            for dep in dependencies[ident]:
                if dep in tasks and tasks[dep].get('status') != 'done':
                    errors.append(f'{ident}: unfinished dependency {dep}')
        if status == 'done':
            proven = {item['kind'] for item in proof if item['result'] == 'pass'}
            for kind in kinds:
                if kind not in proven:
                    errors.append(f'{ident}: missing passing {kind} evidence for done')
    for ident in requirements.keys() - covered:
        errors.append(f'{ident}: no task covers this requirement')

    visited, visiting = set(), set()

    def visit(ident):
        if ident in visiting:
            errors.append(f'dependency cycle at {ident}')
            return
        if ident in visited:
            return
        visiting.add(ident)
        for dep in dependencies.get(ident, []):
            if dep in tasks:
                visit(dep)
        visiting.remove(ident)
        visited.add(ident)

    for ident in tasks:
        visit(ident)

    resume = document.get('resume')
    if not isinstance(resume, dict) or type(resume.get('paid_execution_hold')) is not bool:
        errors.append('resume must declare next_task and paid_execution_hold')
    else:
        active = [ident for ident, row in tasks.items() if choice(row.get('status'), {'next', 'in_progress'})]
        selected = resume.get('next_task')
        if selected is None:
            if active or any(not choice(row.get('status'), {'done', 'deferred'}) for row in tasks.values()):
                errors.append('resume has no next task while unfinished work remains')
        elif not isinstance(selected, str) or selected not in tasks or active != [selected]:
            errors.append('resume must name the single active task')
        if resume.get('paid_execution_hold') and not nonempty(resume.get('hold_reason')):
            errors.append('paid execution HOLD needs a reason')
    return errors


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', action='store_true', help='Print the compact, validated next-work brief')
    args = parser.parse_args()
    try:
        document = json.loads((ROOT / 'docs/mvp-traceability.json').read_text(encoding='utf-8'))
        errors = validate(document)
    except (ValueError, OSError) as exc:
        errors = [str(exc)]
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f'Spec references/dependencies OK: {document["spec_version"]}; not semantic quality or MVP approval.')
    if args.resume:
        print(f'Baseline code: {document["baseline_commit"]}; observed: {document["observed_date"]}')
        print('Read: ' + document['intent_document'] + ' -> ' + document['workflow_document'])
        if 'design_version' in document:
            print('Design: ' + document['design_version'] + ' -> ' + document['design_document'])
        next_id = document['resume']['next_task']
        if next_id is not None:
            task = next(row for row in document['tasks'] if row['id'] == next_id)
            print(f'Next: {next_id} ({task["status"]}) {task["title"]}')
            print('Requirements: ' + ', '.join(task['requirements']))
            for value in task.get('design_refs', []):
                print('Read design: ' + value)
            for requirement in document['requirements']:
                if requirement['id'] in task['requirements']:
                    print(f'  {requirement["id"]} ({requirement["implementation"]}): {requirement["title"]}')
                    for criterion in requirement['acceptance']:
                        print(f'    acceptance: {criterion}')
                    print('    code: ' + ', '.join(requirement['code']))
                    print('    checks: ' + ', '.join(requirement['checks']))
            for key in ('deliverables', 'done_when'):
                for item in task[key]:
                    print(f'  {key}: {item}')
            for decision in document['decisions']:
                if decision['id'] in task['decisions']:
                    print(f'  {decision["id"]} ({decision["status"]}): {decision["question"]}')
                    for value in decision.get('design_refs', []):
                        print('    design: ' + value)
        else:
            print('Next: none; task evidence still needs substantive review.')
        hold = document['resume']['paid_execution_hold']
        print('Paid execution: ' + ('HOLD; ' + document['resume']['hold_reason'] if hold
                                   else 'check current request authority, plan and ledger before any call'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
