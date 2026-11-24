"""Prepare presentation translations for a registered analysis without publishing original comments."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from commentscope.product.analysis import from_factory


def presentation_fields(analysis, issue=None):
    fields = {}
    if issue:
        fields['issue'] = issue
    for view in analysis['perspectives']:
        fields['name:' + view['id']] = view['display_name'] or view['text']
        fields['claim:' + view['core_claim_id']] = view['text']
        for ground in view['grounds']:
            fields['claim:' + ground['claim_id']] = ground['text']
    return fields


def worksheet(analysis, issue, source_language):
    if source_language not in ('ko', 'en'):
        raise ValueError('Choose ko or en for the source language')
    return {'analysis_id': analysis['analysis_id'], 'source_language': source_language, 'topics': [],
            'fields': {key: {'original': original, 'translation': ''}
                       for key, original in presentation_fields(analysis, issue).items()}}


def publish(analysis, issue, reviewed):
    source_language = reviewed['source_language']
    expected = worksheet(analysis, issue, source_language)
    if reviewed['analysis_id'] != expected['analysis_id'] or reviewed['fields'].keys() != expected['fields'].keys():
        raise ValueError('The registered analysis or its presentation fields changed')
    published = {}
    for key, field in expected['fields'].items():
        row = reviewed['fields'][key]
        if row.get('original') != field['original']:
            raise ValueError('The original presentation text changed for ' + key)
        language = row.get('source_language', source_language)
        if language not in ('ko', 'en'):
            raise ValueError('Choose ko or en for ' + key)
        target = 'en' if language == 'ko' else 'ko'
        translated = row.get('translation')
        if not isinstance(translated, str) or not translated.strip():
            raise ValueError('Supply a translation for ' + key)
        published[key] = {'sha256': sha256(field['original'].encode('utf-8')).hexdigest(),
                          target: translated.strip()}
        if language != source_language:
            published[key]['source_language'] = language
    record = {'source_language': source_language, 'fields': published}
    topics = reviewed.get('topics', [])
    if not isinstance(topics, list):
        raise ValueError('Supply topics as a list')
    if topics:
        available = {view['id'] for view in analysis['perspectives']}
        record['topics'] = []
        for topic in topics:
            if not isinstance(topic, dict) or any(not isinstance(topic.get(k), str) or not topic[k].strip()
                                                  for k in ('en', 'ko')):
                raise ValueError('Every topic needs English and Korean labels')
            members = topic.get('members')
            if not isinstance(members, list) or not members:
                raise ValueError('Every topic needs registered perspective IDs')
            for member in members:
                if not isinstance(member, str) or member not in available:
                    raise ValueError('Topic members must be unique registered perspective IDs')
                available.remove(member)
            record['topics'].append({'en': topic['en'].strip(), 'ko': topic['ko'].strip(), 'members': members})
    return {analysis['analysis_id']: record}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    draw = commands.add_parser('draw', help='write a private translation worksheet')
    draw.add_argument('run', type=Path)
    draw.add_argument('source_language', choices=['ko', 'en'])
    pack = commands.add_parser('publish', help='print the verified public catalog entry')
    pack.add_argument('run', type=Path)
    pack.add_argument('reviewed', type=Path)
    args = parser.parse_args()
    analysis = from_factory(args.run)
    analysis.live()
    catalog = Path(__file__).resolve().parents[1] / 'src/commentscope/product/opinion-samples.json'
    issue = json.loads(catalog.read_text(encoding='utf-8')).get(analysis.id, {}).get('issue')
    public = analysis.public()
    if args.command == 'draw':
        result = worksheet(public, issue, args.source_language)
    else:
        result = publish(public, issue, json.loads(args.reviewed.read_text(encoding='utf-8')))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
