"""Diagnostic retrieval only: similarity selects comparisons, never membership."""
from collections import Counter
import math
import re

VERSION = 'candidate-search-0.1'
POLICIES = ('same_mode', 'cross_mode', 'hybrid')


def search(units, vectors, policy='hybrid'):
    if policy not in POLICIES or len(units) != len(vectors) or len(units) > 512:
        raise ValueError('Invalid diagnostic retrieval input')
    ids = [u['claim_id'] for u in units]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate unit ID')
    if not units:
        return {}
    rows, dimension = [], None
    for vector in vectors:
        if (not isinstance(vector, list) or not vector or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in vector) or
                dimension is not None and len(vector) != dimension):
            raise ValueError('Invalid embedding')
        dimension = len(vector)
        norm = math.sqrt(sum(v*v for v in vector))
        if not norm or not math.isfinite(norm):
            raise ValueError('Invalid embedding norm')
        rows.append([v/norm for v in vector])
    tokens = [Counter(re.findall(r'\w+', u['statement'].casefold())) for u in units]
    df = Counter(t for row in tokens for t in row)
    lexical = [{t: (1+math.log(n))*math.log(1+len(units)/df[t]) for t, n in row.items()} for row in tokens]
    norms = [math.sqrt(sum(v*v for v in row.values())) for row in lexical]
    result = {}
    for i, unit in enumerate(units):
        eligible = [j for j, other in enumerate(units) if i != j and
                    unit['source_comment_id'] != other['source_comment_id'] and
                    (policy != 'same_mode' or unit['mode'] == other['mode'] != 'unclear')]
        cosine = {j: max(-1., min(1., sum(a*b for a, b in zip(rows[i], rows[j])))) for j in eligible}
        ranked = sorted(eligible, key=lambda j: (-cosine[j], ids[j]))
        if policy != 'hybrid':
            chosen = [j for j in ranked if cosine[j] >= .55][:8]
            result[ids[i]] = [{'claim_id': ids[j], 'cosine': cosine[j]} for j in chosen]
            continue
        lex = {j: sum(v*lexical[j].get(t, 0) for t, v in lexical[i].items())/(norms[i]*norms[j])
               if norms[i] and norms[j] else 0. for j in eligible}
        # Fixed 8 semantic + 4 lexical slots. No semantic approval or topic filter here.
        chosen = ranked[:8]
        extra = sorted((j for j in eligible if j not in chosen and lex[j] > 0),
                       key=lambda j: (-lex[j], ids[j]))[:4]
        result[ids[i]] = [{'claim_id': ids[j], 'cosine': cosine[j], 'lexical': lex[j],
                          'route': 'embedding' if j in chosen else 'lexical'} for j in [*chosen, *extra]]
    return result


def funnel(units, candidates):
    by_id = {u['claim_id']: u for u in units}
    eligible = [uid for uid, rows in candidates.items() if len({by_id[i]['source_comment_id']
                for i in [uid, *[r['claim_id'] for r in rows]]}) >= 3]
    return {'claims': len(units), 'with_neighbors': sum(bool(v) for v in candidates.values()),
            'eligible_anchors': len(eligible), 'directed_edges': sum(map(len, candidates.values())),
            'cross_mode_edges': sum(by_id[a]['mode'] != by_id[r['claim_id']]['mode']
                                    for a, rows in candidates.items() for r in rows)}
