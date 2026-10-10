"""Local representative-claim drafts; no approved PerspectiveSpec or agents.

python -m commentscope.factory.perspective_drafts SNAPSHOT EXTRACTION CANDIDATES
  --output artifacts/drafts.json --clusters CC001 CC002 CC003
  --model-label LABEL --model-revision REV --runtime BUILD
"""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import time
from urllib.error import URLError

from commentscope import perspective_prompt
from commentscope import perspective_prompt_v2
from commentscope import perspective_prompt_v3
from commentscope.contracts import perspective_draft as contract
from commentscope.contracts import perspective_assignment
from commentscope.factory.claim_clusters import prepare, read_json, sha, VERSION as CANDIDATE_VERSION
from commentscope.providers.local_llama import generate
from commentscope.storage import write_json_exclusive


def load_candidates(snapshot, extraction, candidates):
    prepared = prepare(snapshot, extraction)
    report = read_json(candidates)
    if report.get('artifact_kind') != CANDIDATE_VERSION or any(report.get(k) != prepared[k] for k in ['snapshot_sha256', 'extraction_sha256', 'claims']):
        raise ValueError('Candidate provenance or claims changed')
    units = {c['claim_id']: c for c in prepared['claims']}
    clusters, assigned = {}, []
    for cluster in report['clusters']:
        ids = cluster['claim_ids']
        if cluster['id'] in clusters or not ids or any(cid not in units for cid in ids):
            raise ValueError('Invalid candidate IDs or membership')
        assigned.extend(ids)
        clusters[cluster['id']] = ids
    if len(assigned) != len(set(assigned)) or set(assigned) != set(units):
        raise ValueError('Candidates must partition claims exactly once')
    return prepared, clusters


def draft_prompt_for(revision):
    prompts = {'v1': perspective_prompt, 'v2': perspective_prompt_v2, 'v3': perspective_prompt_v3}
    if revision not in prompts:
        raise ValueError('Unknown draft revision')
    return prompts[revision]


def inputs_for(prepared, ids, revision='v1'):
    draft_prompt_for(revision)
    if not 1 <= len(ids) <= 20:
        raise ValueError('Draft slice supports 1..20 claims per candidate')
    units = {c['claim_id']: c for c in prepared['claims']}
    members = {}
    for number, cid in enumerate(ids, 1):
        claim = units[cid]
        members[f'M{number:02d}'] = {'claim_id': cid, 'source_comment_id': claim['source_comment_id'],
                                  'target': prepared['sources'][claim['source_comment_id']]['text'],
                                  'extracted_claim': claim['claim'], 'scope_quote': claim['quote']}
    # Keep real source IDs in host provenance, not generated output.
    scope_key = 'scope_quote' if revision in ('v2', 'v3') else 'extracted_claim'
    payload = {'members': [{'member_id': mid, 'target': m['target'], scope_key: m[scope_key]}
                           for mid, m in members.items()]}
    return members, payload


def draft(members, payload, provider=generate, revision='v1'):
    assignment_wire = revision in ('v2', 'v3')
    schema = perspective_assignment.schema(members) if assignment_wire else contract.schema(members)
    prompt = draft_prompt_for(revision)
    started = time.perf_counter()
    response, parsed, raw, finish, canonical = None, None, None, None, None
    errors = []
    try:
        response = provider(prompt.SYSTEM, payload, schema)
        choice = response['choices'][0]
        finish = choice['finish_reason']
        raw = choice['message']['content']
        parsed = json.loads(raw)
        if assignment_wire:
            try:
                canonical = perspective_assignment.canonicalize(parsed, members)
            except ValueError as exc:
                errors = [str(exc)]
        else:
            canonical = parsed
            errors = contract.validate(parsed, members)
        if finish != 'stop':
            errors.append('incomplete_generation')
    except (URLError, TimeoutError, OSError):
        errors = ['local_transport_error']
    except (KeyError, IndexError, TypeError, ValueError):
        errors = ['invalid_response_or_json']
    return {'input': payload, 'members': members, 'generation_schema': schema,
            'generation_schema_sha256': hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(),
            'raw': raw, 'output': parsed, 'canonical_output': canonical, 'finish_reason': finish,
            'citation_mode': 'host_bound_full_target' if assignment_wire else 'model_selected_substring',
            'usage': response.get('usage') if isinstance(response, dict) else None,
            'timings': response.get('timings') if isinstance(response, dict) else None,
            'seconds': time.perf_counter()-started, 'contract_errors': errors,
            'bound_draft': contract.bind(canonical, members) if not errors else None}


def render(report):
    esc = lambda x: html.escape(str(x), quote=True)
    parts = ['<!doctype html><html lang="ko"><meta charset="utf-8"><title>로컬 모델 대표 주장 초안</title>',
             '<style>body{font:16px system-ui;max-width:1100px;margin:30px auto;padding:15px}article{border:1px solid #bbb;padding:16px;margin:20px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}blockquote{background:#eef5ff;padding:12px}</style>',
             '<h1>로컬 모델이 생성한 대표 주장 — 승인 전 초안</h1><p>이전 assistant의 분리 제안/대표 설명을 모델 입력에 넣지 않았습니다. 공통 주장이 모든 인용으로 뒷받침되는지, 일부 이유를 전체에 일반화하지 않았는지 확인하세요.</p>',
             '<pre>'+esc(json.dumps(report['summary'], ensure_ascii=False, indent=2))+'</pre>']
    for result in report['results']:
        parts.append('<article><h2>'+esc(result['cluster_id'])+'</h2><p>계약 오류: '+esc(result['contract_errors'])+'</p>')
        parts.append('<p>인용 방식: '+esc(result.get('citation_mode'))+' — 전체 원문 연결은 문장별 의미 지원을 보장하지 않습니다.</p>')
        bound = result['bound_draft']
        def statement(s):
            parts.append('<p><strong>'+esc(s['text'])+'</strong></p>')
            for citation in s['evidence']:
                parts.append('<blockquote>'+esc(citation['member_id'])+': '+esc(citation['quote'])+'</blockquote>')
        if bound:
            for group in bound['groups']:
                parts.append('<h3>'+esc(group['draft_id'])+' · 서로 다른 원문 '+str(len(group['source_ids']))+'개 · '+esc(group['status'])+'</h3>')
                statement(group['common'])
                for detail in group['details']:
                    parts.append('<h4>'+esc(detail['kind'])+' · 인용된 일부 원문에만 해당</h4>')
                    statement(detail)
            parts.append('<h3>제외와 이유</h3><pre>'+esc(json.dumps(bound['excluded'], ensure_ascii=False, indent=2))+'</pre>')
        else:
            parts.append('<p>계약 실패로 전체 초안 사용 차단. 자동 수정하지 않았습니다.</p>')
        parts.append('<details><summary>원시 모델 출력 (검사 실패 포함)</summary><pre>'+esc(result['raw'])+'</pre></details><h3>전체 입력 원문</h3>')
        for mid, member in result['members'].items():
            parts.append('<details><summary>'+esc(mid)+' · '+esc(member['source_comment_id'])+'</summary><pre>'+esc(member['target'])+'</pre><p>이전 추출 주장 (오류 가능): '+esc(member['extracted_claim'])+'</p></details>')
        parts.append('</article>')
    return '\n'.join(parts+['</html>'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot'); parser.add_argument('extraction'); parser.add_argument('candidates')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--clusters', nargs='+', required=True)
    parser.add_argument('--model-label', required=True); parser.add_argument('--model-revision', required=True)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--revision', choices=['v1', 'v2', 'v3'], default='v2')
    args = parser.parse_args()
    prepared, clusters = load_candidates(args.snapshot, args.extraction, args.candidates)
    if len(set(args.clusters)) != len(args.clusters) or not set(args.clusters) <= set(clusters) or len(args.clusters) > 3:
        parser.error('Choose 1..3 distinct known candidate IDs')
    # Prevalidate every input and output before starting any model call.
    inputs = [inputs_for(prepared, clusters[c], args.revision) for c in args.clusters]
    prompt = draft_prompt_for(args.revision)
    checkpoints = [Path(str(args.output)+f'.case-{i+1}.json') for i in range(len(inputs))]
    if any(os.path.lexists(p) for p in [args.output, Path(str(args.output)+'.html'), *checkpoints]):
        parser.error('Output exists; choose new paths')
    report = {'artifact_kind': 'local-perspective-draft-probe-0.1', 'schema_version': contract.VERSION,
              'snapshot_sha256': prepared['snapshot_sha256'], 'expires_at': prepared['expires_at'],
              'extraction_sha256': prepared['extraction_sha256'], 'candidate_report_sha256': sha(args.candidates),
              'wire_schema_version': perspective_assignment.VERSION if args.revision in ('v2', 'v3') else contract.VERSION,
              'comparison_caveat': ('v3 changes only the prompt relative to v2; same development inputs, not independent accuracy evaluation'
                  if args.revision == 'v3' else 'v2 changes prompt, assignment schema, citation mechanism and source input together; not isolated causal evidence'),
              'system_prompt': prompt.SYSTEM, 'prompt_version': prompt.VERSION,
              'prompt_sha256': hashlib.sha256(prompt.SYSTEM.encode()).hexdigest(),
              'model': args.model_label, 'model_revision': args.model_revision, 'runtime': args.runtime,
              'model_metadata_source': 'operator_supplied_not_attested',
              'request_settings': {'temperature': 0, 'seed': 407, 'max_tokens': 3000},
              'semantic_review_status': 'pending', 'accepted_perspectives': 0, 'results': []}
    for cid, (members, payload), checkpoint in zip(args.clusters, inputs, checkpoints):
        result = {'cluster_id': cid, **draft(members, payload, revision=args.revision)}
        write_json_exclusive(checkpoint, {**report, 'results': [result], 'checkpoint_only': True})
        report['results'].append(result)
        print(json.dumps({'cluster': cid, 'seconds': round(result['seconds'], 2), 'errors': result['contract_errors']}), flush=True)
    report['summary'] = {'candidates_tested': len(inputs), 'contract_pass': sum(not r['contract_errors'] for r in report['results']),
                         'total_seconds': sum(r['seconds'] for r in report['results']), 'accepted_perspectives': 0}
    write_json_exclusive(args.output, report)
    with Path(str(args.output)+'.html').open('x', encoding='utf-8') as stream:
        stream.write(render(report))
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
