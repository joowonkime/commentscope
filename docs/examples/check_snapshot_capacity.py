"""Reproduce snapshot-count boundaries with synthetic inputs and no API calls.

Run at the repository root with Python 3.12+: python docs/examples/check_snapshot_capacity.py
This diagnoses current routing; it does not raise limits or test live throughput.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT, ROOT / 'src'):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from commentscope.factory.framed_corpus import sources
from commentscope.ingestion import load_snapshot
from tools import prepared_video_trial as trial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    base = load_snapshot(ROOT / 'tests/fixtures/synthetic-snapshot.json').snapshot
    def snapshot(count):
        return replace(base,
            usage=replace(base.usage, expires_at='2099-01-01T00:00:00Z'),
            comments=tuple(replace(base.comments[0], comment_id=f'capacity-{i}',
                parent_id=None, text_original=f'Synthetic option {i} should be discussed.')
                for i in range(count)))
    rows = []
    for count, maximum, accepted in ((1000, None, True), (1001, None, False),
                                      (1001, 3000, True), (3000, 3000, True)):
        try:
            registry = sources(snapshot(count), **({} if maximum is None else
                                                   {'maximum_comments': maximum}))
            row = {'raw_comments': count, 'explicit_maximum': maximum,
                   'accepted': True, 'canonical_sources': len(registry)}
        except ValueError as exc:
            row = {'raw_comments': count, 'explicit_maximum': maximum,
                   'accepted': False, 'error': str(exc)}
        assert row['accepted'] is accepted, row
        rows.append(row)
    (ROOT / 'runs').mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='handoff-capacity-', dir=ROOT / 'runs') as folder:
        root = Path(folder)
        snap = root / 'snapshot.json'
        snap.write_text(json.dumps(snapshot(1001).to_dict()), encoding='utf-8')
        private_inputs = [root / name for name in ('references.json', 'owner.json', 'policy.json')]
        for path in private_inputs:
            path.write_text('{}', encoding='utf-8')
        def forbidden(*args, **kwargs):
            raise AssertionError('Network/provider preflight is forbidden in this audit')
        with patch.object(trial.e, 'key_metadata', side_effect=forbidden) as key, \
             patch.object(trial.e, 'provider_preflight', side_effect=forbidden) as provider, \
             patch.object(trial.e, 'embedding_preflight', side_effect=forbidden) as embedding, \
             patch.object(trial.decisions, 'preflight', side_effect=forbidden) as typed:
            try:
                trial.prepare(root / 'execution', snap, *private_inputs,
                    user_request='Synthetic capacity diagnostic; no model or money authorization.')
            except ValueError as exc:
                assert str(exc) == 'MVP snapshot cap exceeded', str(exc)
                prepared = {'raw_comments': 1001, 'accepted': False, 'error': str(exc)}
            else:
                raise AssertionError('Reassess capacity documentation: prepare behavior changed')
            assert all(mock.call_count == 0 for mock in (key, provider, embedding, typed))
    result = {'synthetic_only': True, 'provider_calls': 0, 'model_calls': 0,
              'registry_cases': rows, 'prepared_video_prepare': prepared,
              'full_3000_comment_pipeline_executed': False,
              'diagnosis': 'The registry supports explicit3000, but prepared_video.prepare '
                           'uses its default1000 before the declared3000 check.'}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                               encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
