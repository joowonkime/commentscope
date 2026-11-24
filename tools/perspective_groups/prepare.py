"""Prepare a new video with the team's filter, grouping and source-linked profile builder."""
import argparse
import os
from pathlib import Path

from . import filter_comments, group_comments
from .catalog import read, register, write_json
from .llm_client import create_client


def collection(path):
    raw = read(path)
    if 'meta' in raw:
        return filter_comments.load_source(path)
    video = raw['video']
    return {'meta':{'video_id':video['video_id'],'title':video['title'],'collected_at':raw['captured_at']},
            'comments':[{'comment_id':c['comment_id'],'parent_id':c.get('parent_id') or '',
                         'is_reply':bool(c.get('parent_id')),'text':c['text_original'],
                         'like_count':c.get('likes') or 0} for c in raw['comments']]}


def prepare(source, directory, client, workers=1):
    topic = source['meta']['title']
    first, second = directory/'01_filter', directory/'02_group'
    filtered = filter_comments.filter_source(source, client, first, topic=topic, model=client.model, workers=workers)
    filter_comments.save_results(first, filtered)
    retained = read(first/'filtered.json')
    groups = group_comments.group_source(retained, client, second, topic=topic, context_rows=source['comments'], workers=workers)
    group_comments.save_results(second, groups)
    record = register(directory, save_profiles=True)
    write_json(directory/'grouped.json',record)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('output', type=Path, help='Private directory for this input and its resumable model outputs')
    parser.add_argument('--provider', choices=('openrouter','openai'), default='openrouter')
    parser.add_argument('--model', required=True, help='Model to use for the explicitly requested preparation')
    parser.add_argument('--workers', type=filter_comments.positive_int, default=1)
    args = parser.parse_args()
    client = create_client(os.environ, args.provider, args.model)
    result = prepare(collection(args.snapshot), args.output, client, args.workers)
    print(result['analysis_id'], len(result['bundle']['candidates']), 'groups')
