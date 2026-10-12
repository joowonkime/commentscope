"""Offline English document entailment comparator; never a truth certificate.

Whole selected passages are preserved. Token overflow is an error, not silent
truncation. The existing pinned CPU classifier and fixed .8 cutoff are reused.
"""
from commentscope.providers.local_nli import LocalNLI, THRESHOLD, decide

VERSION = 'whole-passage-evidence-nli-0.1'


def aggregate(rows):
    if not rows or any(row['errors'] for row in rows):
        return {'state': 'error' if rows else 'unassessed', 'supporting_ids': [], 'refuting_ids': []}
    supports = [r['id'] for r in rows if r['relation'] == 'supports']
    refutes = [r['id'] for r in rows if r['relation'] == 'contradicts']
    return {'state': 'conflicting' if supports and refutes else 'supported' if supports else 'refuted' if refutes else 'insufficient',
            'supporting_ids': supports, 'refuting_ids': refutes}


def unanimous(left, right):
    if left in {'error', 'unassessed'} or right in {'error', 'unassessed'}: return 'error'
    return left if left == right else 'insufficient'


def generate(system, data, schema, max_tokens):
    # Called once inside the bounded disposable worker: model loading and all
    # pair forwards are charged to the same cycle. No network or server access.
    if system != VERSION or schema != {} or max_tokens != 1 or set(data) != {'cases'}:
        raise ValueError('Unexpected batch contract')
    nli = LocalNLI()
    results = []
    for case in data['cases']:
        rows = []
        for evidence in case['evidence']:
            row = {'id': evidence['id'], 'errors': [], 'scores': None, 'raw': None, 'relation': None}
            try:
                premise, hypothesis = evidence['text'], case['text']
                if not all(isinstance(t, str) and t.strip() and len(t.encode()) <= 30000 for t in [premise, hypothesis]):
                    raise ValueError('Invalid text')
                inputs = nli.tokenizer(premise, hypothesis, return_tensors='pt', truncation=False)
                row['input_tokens'] = int(inputs['input_ids'].shape[1])
                if row['input_tokens'] > min(512, nli.model.config.max_position_embeddings):
                    raise ValueError('Token limit')
                with nli.torch.inference_mode():
                    logits = nli.model(**inputs).logits[0]
                    values = logits.softmax(dim=-1).tolist()
                row['raw'] = logits.tolist()
                row['scores'] = {nli.labels[i]: value for i, value in enumerate(values)}
                row['relation'] = decide(row['scores'], THRESHOLD)
            except (ValueError, RuntimeError, OSError) as exc:
                row['errors'] = [type(exc).__name__]
            rows.append(row)
        results.append({'id': case['id'], 'pairs': rows, **aggregate(rows)})
    return {'metadata': nli.metadata, 'results': results,
            'forward_pairs': sum(len(r['pairs']) for r in results), 'quality_gate_passed': False}
