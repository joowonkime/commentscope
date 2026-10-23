"""Offline correct-comment utilization, separate from runtime support counts.

References must be frozen BEFORE the run and their hash pinned in its plan.
Output reviews are made afterwards, against the frozen output and sources.
Hashes detect changed inputs, not biased evaluators or dishonest chronology.
This module counts supplied review judgments; it is not a semantic classifier,
agent approval mechanism, or an independent human gold evaluation.
"""
from collections import Counter
from copy import deepcopy

from commentscope.factory.automatic_contract import digest
from commentscope.factory import opinion_map
from commentscope.factory import acceptance
from commentscope.factory.fact_checks import live, nonempty
from commentscope.ingestion import normalize_snapshot

VERSION = 'correct-comment-utilization-0.1'
GOAL_REVISION = 'factory-goal-20261014-r4'
ELIGIBILITY = ('meaningful', 'non_substantive', 'uncertain')
SUPPORT = ('supported', 'not_supported', 'uncertain')
CLUSTER = ('coherent', 'invalid', 'uncertain')


def _fields(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise ValueError('Unexpected evaluation fields')


def _canonical(snapshot):
    live(snapshot.usage.expires_at)
    if len(snapshot.comments) > 1000:
        raise ValueError('MVP snapshot cap exceeded')
    if len({c.comment_id for c in snapshot.comments}) != len(snapshot.comments):
        raise ValueError('Duplicate source IDs')
    ids = {c.comment_id for c in normalize_snapshot(snapshot)
           if c.text_analysis and c.duplicate_of is None}
    return {c.comment_id: c.text_original for c in snapshot.comments if c.comment_id in ids}


def freeze_reference(snapshot, rows, *, evaluator, protocol, scope_ids=None):
    """Construct an explicit denominator, including exclusions and uncertainties.

    A subset is labelled sample-only, never promoted to a corpus score. Empty
    source text is mechanically excluded by the shared normalization contract;
    semantic exclusions require a rationale. Aliases cannot enlarge the scope.
    """
    sources = _canonical(snapshot)
    if not nonempty(evaluator) or not nonempty(protocol):
        raise ValueError('Evaluator and pre-output protocol required')
    scope = list(sources) if scope_ids is None else list(scope_ids)
    if (any(not isinstance(s, str) or s not in sources for s in scope)
            or len(set(scope)) != len(scope)):
        raise ValueError('Unique canonical evaluation scope required')
    indexed = {}
    for row in rows:
        _fields(row, 'source_id source_sha256 eligibility reason')
        sid = row['source_id']
        if (not isinstance(sid, str) or sid not in scope or sid in indexed
                or row['eligibility'] not in ELIGIBILITY or not nonempty(row['reason'])
                or row['source_sha256'] != digest(sources[sid])):
            raise ValueError('Invalid, duplicate or changed denominator judgment')
        indexed[sid] = deepcopy(row)
    if set(indexed) != set(scope):
        raise ValueError('Every scoped source needs a label, including uncertain')
    return {'artifact_kind': VERSION + '-reference', 'goal_revision': GOAL_REVISION,
            'snapshot_sha256': digest(snapshot.to_dict()),
            'scope': 'full_corpus' if set(scope) == set(sources) else 'sample',
            'canonical_population': len(sources), 'scope_ids': sorted(scope),
            'evaluator': evaluator, 'protocol': protocol,
            'rows': [indexed[sid] for sid in sorted(scope)]}


def _validate_reference(snapshot, reference, expected_hash):
    _fields(reference, 'artifact_kind goal_revision snapshot_sha256 scope '
                      'canonical_population scope_ids evaluator protocol rows')
    rebuilt = freeze_reference(snapshot, reference['rows'], evaluator=reference['evaluator'],
                               protocol=reference['protocol'], scope_ids=reference['scope_ids'])
    if rebuilt != reference or not nonempty(expected_hash) or digest(reference) != expected_hash:
        raise ValueError('Reference differs from snapshot or pre-run pinned hash')


def evaluate(snapshot, reference, perspectives, assessments, review, *, expected_reference_sha256,
             acceptance_profile=None, expected_acceptance_sha256=None):
    """Evaluate the frozen output without feeding review labels back to runtime.

    ``review`` binds to the full opinion_map output, not a hand-selected list of
    good agents. It contains cluster and support judgments with rationales.
    Missing judgments remain unreviewed. Correct utilization is a lower bound
    from verified memberships, not a prediction about unreviewed comments.
    """
    _validate_reference(snapshot, reference, expected_reference_sha256)
    if acceptance_profile is not None:
        acceptance.validate(acceptance_profile, expected_acceptance_sha256)
    elif expected_acceptance_sha256 is not None:
        raise ValueError('Missing pinned acceptance profile')
    mapped = opinion_map.build(snapshot, perspectives, assessments)
    _fields(review, 'map_sha256 evaluator clusters supports')
    if review['map_sha256'] != digest(mapped) or not nonempty(review['evaluator']):
        raise ValueError('Review must bind to the complete frozen output')
    lookup = {p['id']: p for p in mapped['perspectives']}
    sources = _canonical(snapshot)
    admitted = {(r['perspective_id'], r['canonical_source_id'])
                for r in mapped['assessments'] if r['relation'] == 'supported'}
    cluster_reviews = {}
    for row in review['clusters']:
        _fields(row, 'perspective_id claim_sha256 verdict reason')
        pid = row['perspective_id']
        if (not isinstance(pid, str) or pid not in lookup or pid in cluster_reviews
                or row['claim_sha256'] != digest(lookup[pid]['claim'])
                or row['verdict'] not in CLUSTER or not nonempty(row['reason'])):
            raise ValueError('Invalid, duplicate or changed cluster review')
        cluster_reviews[pid] = row['verdict']
    support_reviews = {}
    for row in review['supports']:
        _fields(row, 'perspective_id source_id claim_sha256 source_sha256 verdict reason')
        pid, sid = row['perspective_id'], row['source_id']
        if not isinstance(pid, str) or not isinstance(sid, str):
            raise ValueError('Canonical review IDs required')
        key = (pid, sid)
        if (key not in admitted or key in support_reviews
                or row['claim_sha256'] != digest(lookup[pid]['claim'])
                or row['source_sha256'] != digest(sources[sid])
                or row['verdict'] not in SUPPORT or not nonempty(row['reason'])):
            raise ValueError('Invalid, duplicate or changed support review')
        support_reviews[key] = row['verdict']

    labels = {r['source_id']: r['eligibility'] for r in reference['rows']}
    meaningful = {sid for sid, label in labels.items() if label == 'meaningful'}
    excluded = {sid for sid, label in labels.items() if label == 'non_substantive'}
    unresolved = {sid for sid, label in labels.items() if label == 'uncertain'}
    if acceptance_profile is not None:
        if reference['scope'] != 'full_corpus' or unresolved:
            raise ValueError('r5 corpus utilization requires the complete fixed reference')
        acceptance.check_scope(acceptance_profile, 'G4', len(sources), len(meaningful))
    support_counts = Counter(support_reviews.get(key, 'unreviewed') for key in admitted)
    used, per_cluster = set(), []
    for pid, p in lookup.items():
        members = set(p['supported_canonical_ids'])
        correct = {sid for sid in members if support_reviews.get((pid, sid)) == 'supported'}
        # Two distinct reviewed contributors are the structural floor for a
        # shared cluster, NOT agent eligibility (which still requires >=3).
        # Excluded/uncertain reference labels cannot manufacture that floor.
        contributors = {sid for sid in correct if labels.get(sid) == 'meaningful'}
        utilized = (contributors if cluster_reviews.get(pid) == 'coherent'
                    and len(contributors) >= 2 else set())
        used.update(utilized)
        per_cluster.append({'perspective_id': pid, 'counted_support': len(members),
                            'reviewed_supported': len(correct),
                            'incorrect_support': sum(support_reviews.get((pid, sid)) == 'not_supported'
                                                     for sid in members),
                            'unresolved_support': sum(support_reviews.get((pid, sid)) in (None, 'uncertain')
                                                      for sid in members),
                            'cluster_review': cluster_reviews.get(pid, 'unreviewed'),
                            'utilized_scope_ids': sorted(utilized),
                            'agent_approved': False})

    reference_conflicts = sorted({sid for (pid, sid), verdict in support_reviews.items()
                                 if verdict == 'supported' and sid in excluded})
    denominator_complete = not unresolved
    rate = len(used) / len(meaningful) if meaningful and denominator_complete else None
    # All counted relations, including extra wrong edges from an otherwise
    # correctly utilized source, remain in the support gate's denominator.
    cluster_gate = all(cluster_reviews.get(pid) == 'coherent'
                       for pid, p in lookup.items() if p['supported_canonical_ids'])
    support_gate = (bool(admitted) and support_counts['supported'] == len(admitted)
                    and cluster_gate and not reference_conflicts)
    numerator, denominator = acceptance.ratio(acceptance_profile)
    coverage_gate = bool(rate is not None and len(used) * denominator >= len(meaningful) * numerator)
    result = {'artifact_kind': VERSION, 'goal_revision': GOAL_REVISION,
            'reference_sha256': digest(reference), 'map_sha256': digest(mapped),
            'review_sha256': digest(review), 'scope': reference['scope'],
            'canonical_population': len(sources), 'evaluated_sources': len(labels),
            'meaningful_sources': len(meaningful), 'excluded_source_ids': sorted(excluded),
            'unresolved_eligibility_ids': sorted(unresolved),
            'utilized_source_ids': sorted(used), 'unutilized_meaningful_ids': sorted(meaningful - used),
            'correct_comment_utilization': rate, 'coverage_target_met': coverage_gate,
            'support_counts': {v: support_counts[v] for v in (*SUPPORT, 'unreviewed')},
            'counted_support_relations': len(admitted),
            'support_validity_passed': support_gate, 'reference_conflict_ids': reference_conflicts,
            'per_cluster': per_cluster,
            'corpus_clustering_target_met': (reference['scope'] == 'full_corpus'
                                             and coverage_gate and support_gate),
            'agent_approval': 'not_evaluated', 'mvp_acceptance': 'not_evaluated',
            'limitations': ['Supplied reviewer judgments are not independent gold or guaranteed truth.',
                            'The pre-run plan must pin the reference hash before seeing output.',
                            'Unreviewed assignments contribute no correct-utilization credit.',
                            'Comment-level coverage does not establish minority-perspective recall.']}
    if acceptance_profile is not None:
        result.update(artifact_kind='correct-comment-utilization-0.2',
                      goal_revision=acceptance_profile['goal_revision'],
                      acceptance_revision=acceptance_profile['acceptance_revision'],
                      acceptance_profile_sha256=digest(acceptance_profile),
                      reference_goal_revision=reference['goal_revision'],
                      minimum_utilized_sources=acceptance.minimum(acceptance_profile))
    return result
