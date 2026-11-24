"""Register the team group's prepared stances with the existing conversation engine."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from commentscope.agents import seed_policy
from commentscope.factory.automatic_contract import digest
from commentscope.factory.fact_checks import claim_identity, live
from commentscope.product.analysis import Analysis
from .filter_comments import digest as team_digest, write_json


FORMAT = 'grouped-perspectives-v1'
DISPLAY_ORDER = ('g4', 'g5', 'g2', 'g3', 'g1')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def bilingual(original, english=''):
    return {'original': original, 'translation': {'en': english} if english else {}}


class GroupedAnalysis(Analysis):
    def __init__(self, bundle, provenance, presentation):
        if provenance.get('group_catalog_sha256') != digest(presentation):
            raise ValueError('Group presentation differs from the registered revision')
        super().__init__(bundle, provenance, presentation)

    def public(self):
        result = super().public()
        if result['status'] == 'expired':
            return result
        result['grouping'] = deepcopy(self.presentation['grouping'])
        for view in result['perspectives']:
            view['group'] = deepcopy(self.presentation['cards'][view['id']])
            view['support_scope'] = 'group_summary_examples'
        return result

    def source(self, source_id):
        if source_id not in self.presentation['originals']:
            return super().source(source_id)
        self.live()
        row = self.presentation['originals'][source_id]
        value = {'id': source_id, 'canonical_id': source_id, 'text': row['text']}
        parent = self.presentation['originals'].get(row['parent_id'])
        if parent:
            value['PARENT_CONTEXT_ONLY'] = {'id': row['parent_id'], 'text': parent['text']}
        return value


def load_record(record):
    if record.get('format') != FORMAT:
        raise ValueError('Unrecognized grouped analysis')
    analysis = GroupedAnalysis(record['bundle'], record['provenance'], record['presentation'])
    if (analysis.id, analysis.revision) != (record['analysis_id'], record['bundle_revision']):
        raise ValueError('Registered group bundle changed')
    return analysis


def recent_originals(decisions, refresh):
    rows = {r['comment']['comment_id']: r['comment'] for r in decisions['decisions']}
    if len(rows) != len(decisions['decisions']):
        raise ValueError('Duplicate input comment ID')
    meta = decisions['meta']['source_meta']
    if refresh is None:
        receipt_time = meta['collected_at']
        original = {i: {'text': r['text'], 'parent_id': r['parent_id'], 'likes': max(0, r['like_count'])}
                    for i, r in rows.items()}
    else:
        if set(refresh['requested_ids']) != rows.keys() or refresh['video_id'] != meta['video_id']:
            raise ValueError('Refresh is for a different video or set of comments')
        receipt_time = refresh['checked_at']
        original = {}
        for cid, current in refresh['comments'].items():
            old = rows[cid]
            if (current.get('videoId', meta['video_id']) == meta['video_id']
                    and current.get('parentId', '') == old['parent_id']
                    and current['textDisplay'].strip() == old['text'].strip()):
                original[cid] = {'text': current['textDisplay'], 'parent_id': old['parent_id'],
                                 'likes': max(0, int(current.get('likeCount', 0)))}
    # A reply can only reuse the original interpretation if its parent context also survived.
    original = {cid: row for cid, row in original.items() if not row['parent_id'] or row['parent_id'] in original}
    at = datetime.fromisoformat(receipt_time.replace('Z', '+00:00'))
    if at.tzinfo is None or at > datetime.now(timezone.utc) + timedelta(minutes=1):
        raise ValueError('Invalid source observation time')
    expiry = (at + timedelta(days=30)).isoformat()
    live(expiry)
    return original, expiry


def register(directory, reference=None, refresh=None, *, save_profiles=False):
    from .profiles import build_bundle, validate_bundle

    directory = Path(directory)
    decisions = read(directory/'01_filter/decisions.json')
    filtered = read(directory/'01_filter/filtered.json')
    grouped = read(directory/'02_group/groups.json')
    assigned_file = read(directory/'02_group/assignments.json')
    if assigned_file['meta'] != grouped['meta']:
        raise ValueError('Assignments and groups are from different runs')
    assignments = assigned_file['assignments']
    prepared = build_bundle(grouped, assigned_file, filtered)
    agent_path = directory/'03_agents/agents.json'
    if save_profiles:
        write_json(agent_path, prepared)
    elif agent_path.is_file():
        archived = validate_bundle(read(agent_path))
        if any(archived['meta'][key] != prepared['meta'][key] for key in ('content_sha256', 'grouping_sha256')):
            raise ValueError('Archived profiles and evidence differ from the supplied groups')
    profiles = {row['agent_id']: row for row in prepared['agents']}
    kept = {row['comment']['comment_id']: row['comment'] for row in decisions['decisions']
            if row['classification']['status'] == 'keep'}
    if kept != {r['comment_id']: r for r in filtered['comments']}:
        raise ValueError('Filter and group inputs differ')
    sources, expiry = recent_originals(decisions, refresh)
    meta = grouped['meta']
    info = decisions['meta']['source_meta']
    video_id = info['video_id']
    reference = reference or {}
    video = reference.get('video') or {'video_id': video_id, 'title': info.get('title') or meta['topic']}
    if video.get('video_id', video.get('id')) != video_id:
        raise ValueError('Reference material belongs to a different video')
    if reference.get('expires_at'):
        expiry = min(live(expiry), live(reference['expires_at'])).isoformat()
    catalog_path = directory/'04_web/catalog.json'
    translations = {}
    if catalog_path.is_file():
        catalog = read(catalog_path)
        if catalog['video']['video_id'] != video_id:
            raise ValueError('Translated catalog belongs to another video')
        fingerprint = prepared['meta']['content_sha256']
        if catalog['fingerprint'] != team_digest(['english-web-v2', fingerprint, grouped]):
            raise ValueError('Translated catalog is from a different group revision')
        translations = {a['agent_id']: a for a in catalog['agents']}
    groups = {g['group_id']: g for g in grouped['groups']}
    membership = {a['comment']['comment_id']: a['grouping'] for a in assignments if a['comment']['comment_id'] in sources}
    runtime = digest([Path(__file__).with_name(f).read_bytes().hex() for f in ('filter_comments.py','group_comments.py')])
    model = meta['model']
    identity = {'kind':'remote_llm','provider':'OpenAI','name':model,'revision':model,'language_scope':'multilingual',
                'runtime_sha256':runtime,'deployment_sha256':digest([meta['provider'],model,meta.get('reasoning_effort')])}
    if meta['provider'].lower() not in ('openai','openrouter') or not model.lower().removeprefix('openai/').startswith('gpt-'):
        raise ValueError('Group preparation model identity must have a supported provider')
    bundle = {'expires_at':expiry,'model':identity,'admission_policy':deepcopy(seed_policy.POLICY),
              'documents':reference.get('documents',[]),'reference_selections':reference.get('reference_selections',[]),
              'checks':[],'claims':[],'candidates':[],'relations':[],'sources':[],'source_contexts':{}}
    cards, bound_sources = {}, set()
    originals = {cid:sources[cid] for cid in membership}
    for row in list(originals.values()):
        pid = row['parent_id']
        if pid in sources:
            originals[pid] = sources[pid]

    def bind(cid, text, ids, field, owner):
        claim = {'id':cid,'text':text,'kind':'value','scope':{'entity':owner,'time':'','conditions':''},'requires':[]}
        bundle['claims'].append(claim)
        for sid in ids:
            raw = sources[sid]['text']
            bundle['relations'].append({'claim_id':cid,'claim_sha256':claim_identity(claim),'source_id':sid,
                'source_sha256':digest(raw),'span':{'start':0,'end':len(raw),'text':raw},'verdict':'supported',
                # This is the native bundle's model-observation origin, also used for remote Factory judgments.
                'origin':'local_model','trace_id':'group-summary/'+digest([meta['input_sha256'],owner,field,sid])})
            bound_sources.add(sid)

    deposits = {aid: [] for aid in groups}
    other = []
    for sid, assignment in membership.items():
        gid = assignment['primary_group_id']
        (other if gid is None else deposits[gid]).append(sid)
    order = [gid for gid in DISPLAY_ORDER if gid in groups]
    if set(order) != groups.keys():
        raise ValueError('Missing or unknown group ID')
    for gid in order:
        group = groups[gid]
        summary = profiles[gid]
        assigned = set(deposits[gid])
        translation = translations.get(gid,{})
        stance_ids = set(summary['stance_evidence_comment_ids']) & assigned
        def examples(ids, maximum=2):
            return sorted(set(ids), key=lambda sid:(len(sources[sid]['text']),sid))[:maximum]
        if not stance_ids:
            raise ValueError('Group has lost its original stance evidence')
        # Only a core-fit assignment or an explicit stance citation can also anchor the broad group name.
        eligible = {sid for sid in assigned if membership[sid]['fit']=='core'} | stance_ids
        core_examples = examples(stance_ids)
        reasons, translated, roles = [], {}, {}
        for index, item in enumerate(summary['key_arguments']):
            anchors = examples(set(item['supporting_comment_ids']) & eligible, 1)
            if not anchors:
                continue
            rid = gid+'-reason-'+str(index+1)
            statement = item['argument']
            wording = '이 관점의 댓글에서 제시한 이유는 다음과 같다. '+statement
            bind(rid, wording, anchors, 'argument/'+str(index), gid)
            core_examples.extend(anchors)
            reasons.append(rid)
            roles[rid]='reason'
            english = translation.get('arguments',[])
            if index < len(english) and english[index].get('comment_ids')==item['supporting_comment_ids']:
                translated[rid]=bilingual(wording,'A reason given from this perspective is the following. '+english[index]['text'])
        description_id = gid+'-profile'
        bind(description_id,summary['stance'],examples(stance_ids),'qualified-summary',gid)
        reasons.append(description_id)
        roles[description_id] = 'core_restatement'
        translated[description_id] = bilingual(summary['stance'],translation.get('full_stance'))
        cid=gid+'-stance'
        bind(cid,group['name'],list(dict.fromkeys(core_examples)),'primary-core-or-summary-stance',gid)
        bundle['candidates'].append({'id':gid,'core_claim_id':cid,'reason_claim_ids':reasons,'major_fact_ids':[],'argument_roles':roles})
        translated[cid]=bilingual(group['name'],translation.get('title'))
        reason=next((v['argument'] for v in summary['key_arguments'] if set(v['supporting_comment_ids']) & eligible),'')
        cards[gid]={'name':bilingual(group['name'],translation.get('title')),'stance':bilingual(summary['stance'],translation.get('stance')),
                    'subtitle':bilingual('',translation.get('subtitle')),'why':bilingual(reason,translation.get('reasoning')),
                    'claims':translated,'members':deposits[gid],'comments':len(assigned),'likes':sum(sources[i]['likes'] for i in assigned),
                    'variations':[bilingual(v['description'],t.get('text')) for i,v in enumerate(summary['within_group_variations'])
                                  if set(v['comment_ids']) & assigned for t in [(translation.get('variations',[])[i] if i<len(translation.get('variations',[])) else {})]],
                    'limitations':[bilingual(v, translation['limitations'][i] if i<len(translation.get('limitations',[])) else '') for i,v in enumerate(summary['limitations'])]}
    for sid in sorted(bound_sources):
        row=sources[sid]
        bundle['sources'].append({'id':sid,'canonical_id':sid,'text':row['text']})
        if row['parent_id'] in sources:
            parent={'id':row['parent_id'],'text':sources[row['parent_id']]['text']}
            bundle['source_contexts'][sid]={'source_sha256':digest(row['text']),'parent_sha256':digest(parent),'parent':parent}
    counts=Counter(row['classification']['status'] for row in decisions['decisions'] if row['comment']['comment_id'] in sources)
    if counts['keep']!=len(membership):
        raise ValueError('Retained comments do not form one disjoint partition')
    grouping={'collected':len(decisions['decisions']),'retained':len(membership),'review':counts['review'],'excluded':counts['exclude'],
              'unavailable':len(decisions['decisions'])-len(sources),'other':len(other),'other_ids':other,
              'other_likes':sum(sources[i]['likes'] for i in other),'likes':sum(sources[i]['likes'] for i in membership)}
    presentation={'names':{gid:groups[gid]['name'] for gid in order},'cards':cards,'grouping':grouping,'originals':originals}
    provenance={'video':video,'processing_count':len(sources),'canonical_population':len(sources),'group_catalog_sha256':digest(presentation),
                'group_input_sha256':meta['input_sha256'],'method':FORMAT,'current_quality_qualified':False}
    analysis=GroupedAnalysis(bundle,provenance,presentation)
    if len(analysis.compiled['profiles']) != len(groups):
        raise ValueError('Not every eligible group produced a usable perspective')
    return {'format':FORMAT,'analysis_id':analysis.id,'bundle_revision':analysis.revision,'bundle':bundle,'presentation':presentation,'provenance':provenance}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--reference',type=Path)
    parser.add_argument('--youtube-refresh',type=Path)
    args=parser.parse_args()
    record=register(args.directory,read(args.reference) if args.reference else None,read(args.youtube_refresh) if args.youtube_refresh else None)
    write_json(args.output,record)
    print(record['analysis_id'],len(record['bundle']['candidates']),'groups')
