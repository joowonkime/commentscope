"""Stop only core judgments that cannot reach the canonical support minimum.

The upper bound includes every unassessed source in every retrieval variant
with the exact same core contract. It is a scheduling proof, not a semantic
judgment. Unknowns stay unknown; admitted cores retain complete support counts.
"""
from copy import deepcopy

from commentscope.factory.automatic_contract import digest

VERSION = 'pooled-core-admission-bound-0.1'
STATES = {'supported', 'partial', 'unsupported', 'unclear', 'error'}


class CoreAdmissionBound:
    def __init__(self, rows, minimum=3):
        if type(minimum) is not int or minimum < 1:
            raise ValueError('Positive support minimum required')
        self.minimum = minimum
        self.pools = {}
        sources = {}
        for row in rows:
            if row['request_sha256'] != digest(row['request']):
                raise ValueError('Changed source request')
            sid = row['source_id']
            if sid in sources and sources[sid] != row['text']:
                raise ValueError('Changed canonical source')
            sources[sid] = row['text']
            key = digest(row['claim'])
            pool = self.pools.setdefault(key, {'claim': deepcopy(row['claim']), 'rows': {}, 'observed': {}})
            if pool['claim'] != row['claim']:
                raise ValueError('Core digest collision')
            signature = {k: deepcopy(row[k]) for k in ('source_id', 'text', 'claim', 'request', 'request_sha256')}
            if sid in pool['rows'] and pool['rows'][sid] != signature:
                raise ValueError('Conflicting duplicate core/source request')
            pool['rows'][sid] = signature

    def _pool(self, row):
        key = digest(row['claim'])
        pool = self.pools.get(key)
        signature = {k: row[k] for k in ('source_id', 'text', 'claim', 'request', 'request_sha256')}
        if pool is None or pool['rows'].get(row['source_id']) != signature:
            raise ValueError('Relation outside frozen core population')
        return key, pool

    def _summary(self, key, pool):
        supported = sum(s == 'supported' for s in pool['observed'].values())
        remaining = len(pool['rows']) - len(pool['observed'])
        return {'core_sha256': key, 'canonical_sources': len(pool['rows']),
                'assessed_sources': len(pool['observed']), 'model_support_count': supported,
                'unassessed_sources': remaining, 'support_upper_bound': supported + remaining,
                'minimum': self.minimum, 'support_count_complete': remaining == 0}

    def skip_proof(self, row):
        key, pool = self._pool(row)
        if row['source_id'] in pool['observed']:
            return None
        proof = self._summary(key, pool)
        return proof if proof['support_upper_bound'] < self.minimum else None

    def observe(self, row, state):
        _, pool = self._pool(row)
        if state not in STATES:
            raise ValueError('Only actual terminal judgments are observations')
        sid = row['source_id']
        if sid in pool['observed'] and pool['observed'][sid] != state:
            raise ValueError('Conflicting repeated judgment')
        pool['observed'][sid] = state

    def report(self):
        return {'artifact_kind': VERSION, 'minimum': self.minimum,
                'pools': [self._summary(k, p) for k, p in sorted(self.pools.items())],
                'semantic_approval': False}
