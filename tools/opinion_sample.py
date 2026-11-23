"""Draw a private Explore worksheet or export its reviewed, aggregate-only counts."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from commentscope.product.analysis import from_factory


def sample_ids(scope, video_id):
    if not scope or len(set(scope)) != len(scope):
        raise ValueError('Expected distinct processed comment IDs')
    def rank(comment_id):
        key = f'commentscope-opinions-v1\0{video_id}\0{comment_id}'
        return sha256(key.encode()).digest(), comment_id
    return sorted(scope, key=rank)[:50]


def worksheet(directory, issue):
    if not issue.strip():
        raise ValueError('Supply the issue to review before drawing a sample')
    analysis = from_factory(directory)
    analysis.live()
    plan = json.loads((directory / 'plan.json').read_text(encoding='utf-8'))
    snapshot = json.loads(Path(plan['snapshot']).read_text(encoding='utf-8'))
    scope = plan.get('scope_ids')
    if not scope or set(scope) != set(analysis.presentation['likes_by_source']):
        raise ValueError('The processed canonical comment frame is unavailable')
    rows = {c['comment_id']: c for c in snapshot['comments']}
    picked = sample_ids(scope, snapshot['video']['video_id'])
    comments = []
    for ident in picked:
        source = rows[ident]
        parent = rows.get(source['parent_id'])
        comments.append({'id':ident, 'text':source['text_original'],
                         'parent_context':parent['text_original'] if parent else None,
                         'classification':None, 'supports':[]})
    return {'analysis_id':analysis.id, 'issue':issue, 'population':len(scope),
            'perspectives':{p['id']:p['text'] for p in analysis.public()['perspectives']},
            'comments':comments}


def summarize(drawn, reviewed, reviewer):
    if reviewer not in ('ai','human'):
        raise ValueError('Identify who reviewed the sample')
    if any(drawn[key] != reviewed.get(key) for key in ('analysis_id','issue','population','perspectives')):
        raise ValueError('The drawn analysis, issue or perspectives changed')
    expected = {c['id']:c for c in drawn['comments']}
    submitted = reviewed['comments']
    if len(submitted) != len(expected) or {c['id'] for c in submitted} != expected.keys():
        raise ValueError('Review every drawn comment exactly once')
    supports = dict.fromkeys(drawn['perspectives'], 0)
    status = Counter()
    unmatched = 0
    for row in submitted:
        if any(row.get(k) != expected[row['id']][k] for k in ('text','parent_context')):
            raise ValueError('Review the original comment in its original context')
        classification = row.get('classification')
        views = row.get('supports')
        if classification not in ('position','no_position','unclear'):
            raise ValueError('Classify every sampled comment')
        if (not isinstance(views, list) or any(v not in supports for v in views)
                or len(views) != len(set(views)) or views and classification != 'position'):
            raise ValueError('Only explicit positions can support registered perspectives, once each')
        status[classification] += 1
        if classification == 'position' and not views:
            unmatched += 1
        for view in views:
            supports[view] += 1
    return {'analysis_id':drawn['analysis_id'], 'issue':drawn['issue'], 'reviewer':reviewer,
            'population':drawn['population'], 'sample_size':len(submitted), 'positions':status['position'],
            'no_position':status['no_position'], 'unclear':status['unclear'],
            'unmatched':unmatched, 'supports':supports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    draw = commands.add_parser('draw')
    draw.add_argument('directory', type=Path)
    draw.add_argument('issue')
    draw.add_argument('private_worksheet', type=Path)
    report = commands.add_parser('summarize')
    report.add_argument('directory', type=Path)
    report.add_argument('private_worksheet', type=Path)
    report.add_argument('--reviewer', required=True, choices=('ai','human'))
    args = parser.parse_args()
    if args.action == 'draw':
        value = worksheet(args.directory, args.issue)
        with args.private_worksheet.open('x', encoding='utf-8') as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write('\n')
    else:
        reviewed = json.loads(args.private_worksheet.read_text(encoding='utf-8'))
        value = summarize(worksheet(args.directory, reviewed['issue']), reviewed, args.reviewer)
        print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
