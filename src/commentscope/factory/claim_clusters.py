"""Small, inspectable claim-to-candidate slice; no automatic semantic approval.

python -m commentscope.factory.claim_clusters SNAPSHOT EXTRACTION --output RUN.json
Use --review REVIEW.json --render-only with the stored run to attach an AI review
without rerunning embeddings. All research artifacts must stay out of public Git.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import html
import importlib.metadata
import json
import math
import os
from pathlib import Path

from commentscope.cluster_baseline import MODEL, REVISION, token_chunks
from commentscope.contracts.claims import VERSION as CLAIM_VERSION, bind_source, validate_extraction
from commentscope.ingestion import load_snapshot, normalize_snapshot
from commentscope.storage import write_json_exclusive
from commentscope.file_integrity import file_sha256

VERSION = 'claim-candidates-0.1'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return file_sha256(path)


def prepare(snapshot_path, extraction_path):
    loaded = load_snapshot(snapshot_path)
    snapshot = loaded.snapshot
    if snapshot.usage.expires_at and datetime.fromisoformat(snapshot.usage.expires_at.replace('Z', '+00:00')) <= datetime.now(timezone.utc):
        raise ValueError('Snapshot expired')
    if len(snapshot.comments) > 1000:
        raise ValueError('Current phase limited to 1000 source comments')
    extraction = read_json(extraction_path)
    if extraction.get('snapshot_sha256') != loaded.sha256 or extraction.get('schema_version') != CLAIM_VERSION:
        raise ValueError('Extraction snapshot or contract version mismatch')
    results = extraction.get('results')
    if not isinstance(results, list) or not 1 <= len(results) <= 60:
        raise ValueError('This integration slice supports 1..60 selected comments')
    sources = {c.comment_id: c for c in snapshot.comments}
    aliases = {c.comment_id: c.duplicate_of for c in normalize_snapshot(snapshot)}
    units, records, seen = [], [], set()
    for result in results:
        cid = result['comment_id']
        if cid in seen or cid not in sources:
            raise ValueError('Duplicate or unknown extraction source ID')
        seen.add(cid)
        source = sources[cid]
        parent = sources.get(source.parent_id)
        if result.get('source') != source.text_original or result.get('parent_context') != (parent.text_original if parent else None):
            raise ValueError('Extraction source or parent text changed')
        errors = validate_extraction(result.get('output'), source.text_original)
        if result.get('finish_reason') != 'stop':
            errors.append('incomplete_generation')
        # Revalidate raw output; never trust a stored contract_pass or model-supplied IDs.
        status = 'blocked' if errors else ('duplicate_alias' if aliases[cid] else 'included')
        record = {'comment_id': cid, 'status': status, 'errors': errors, 'duplicate_of': aliases[cid],
                  'eligibility': result.get('output', {}).get('eligibility') if isinstance(result.get('output'), dict) else None}
        records.append(record)
        if status != 'included':
            continue
        bound = bind_source(result['output'], cid, source.text_original)
        units.extend(bound['claims'])
    units.sort(key=lambda c: c['claim_id'])
    if len(units) > 300:
        raise ValueError('This small slice supports at most 300 claims')
    retained = seen | {sources[c].parent_id for c in seen if sources[c].parent_id in sources}
    return {'artifact_kind': VERSION, 'snapshot_sha256': loaded.sha256, 'expires_at': snapshot.usage.expires_at,
            'extraction_sha256': sha(extraction_path), 'sampling': extraction.get('sampling'),
            'extraction_metadata': {k: extraction.get(k) for k in ['model', 'model_revision', 'runtime', 'prompt_version', 'prompt_sha256', 'generation_schema_version', 'schema_sha256', 'seed', 'request_settings']},
            'source_count': len(snapshot.comments), 'selected_count': len(results), 'source_records': records,
            'sources': {cid: {'text': sources[cid].text_original, 'parent_id': sources[cid].parent_id} for cid in sorted(retained)},
            'claims': units, 'semantic_review_status': 'pending'}


def embedding_text(claim):
    return '\n'.join(str(claim[k]) for k in ['issue', 'claim', 'reason', 'condition'] if claim[k])


def embed(texts):
    """Pinned, local CPU inference; save every vector with its exact input text."""
    if not texts:
        return []
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(4)
    model = SentenceTransformer(MODEL, revision=REVISION, device='cpu', trust_remote_code=False,
                                model_kwargs={'use_safetensors': True})
    chunks, owners, weights = [], [], []
    for index, text in enumerate(texts):
        for chunk, weight in token_chunks(model.tokenizer, text, model.max_seq_length):
            chunks.append(chunk)
            owners.append(index)
            weights.append(weight)
    encoded = model.encode(chunks, batch_size=32, normalize_embeddings=True, show_progress_bar=True)
    vectors = np.zeros((len(texts), encoded.shape[1]), dtype=np.float64)
    for owner, weight, vector in zip(owners, weights, encoded):
        vectors[owner] += weight * vector
    return vectors.tolist()


def average_linkage(vectors, threshold):
    """Deterministic bounded O(n^3) reference implementation, not a scalable engine."""
    if not math.isfinite(threshold) or not 0 < threshold < 1:
        raise ValueError('threshold must be finite and between 0 and 1')
    normalized, dimension = [], None
    for row in vectors:
        if not row or any(type(v) not in (int, float) or not math.isfinite(v) for v in row):
            raise ValueError('Invalid embedding values')
        if dimension is not None and len(row) != dimension:
            raise ValueError('Embedding dimensions differ')
        dimension = len(row)
        norm = math.sqrt(sum(v*v for v in row))
        if norm == 0 or not math.isfinite(norm):
            raise ValueError('Invalid embedding norm')
        normalized.append([v/norm for v in row])
    distances = [[1-max(-1, min(1, sum(a*b for a, b in zip(x, y)))) for y in normalized] for x in normalized]
    groups = [[i] for i in range(len(vectors))]
    while len(groups) > 1:
        choices = ((sum(distances[a][b] for a in groups[i] for b in groups[j]) / (len(groups[i])*len(groups[j])), i, j)
                   for i in range(len(groups)) for j in range(i+1, len(groups)))
        distance, i, j = min(choices)
        if distance >= threshold:
            break
        groups[i] = sorted(groups[i] + groups[j])
        del groups[j]
    return sorted(groups, key=lambda g: (-len(g), g)), normalized


def build(prepared, vectors, threshold=0.45):
    if len(vectors) != len(prepared['claims']):
        raise ValueError('Embedding count mismatch')
    groups, vectors = average_linkage(vectors, threshold)
    claims = prepared['claims']
    clusters = []
    for number, indexes in enumerate(groups, 1):
        members = [claims[i] for i in indexes]
        source_ids = sorted({c['source_comment_id'] for c in members})
        stances = sorted({c['stance'] for c in members} - {'neutral', 'unclear'})
        clusters.append({'id': f'CC{number:03d}', 'claim_ids': [c['claim_id'] for c in members],
                         'source_ids': source_ids, 'unique_source_count': len(source_ids),
                         'status': 'candidate_needs_review' if len(source_ids) >= 3 else 'rare_unreviewed',
                         'stance_labels': stances, 'warnings': ['multiple_stance_labels_require_review'] if len(stances) > 1 else []})
    return {**prepared, 'created_at': datetime.now(timezone.utc).isoformat(),
            'algorithm': 'bounded-cosine-average-linkage', 'threshold': threshold,
            'embedding': {'model': MODEL, 'revision': REVISION, 'pooling': 'token-weighted mean of normalized chunks',
                          'claim_ids': [c['claim_id'] for c in claims], 'texts': [embedding_text(c) for c in claims], 'vectors': vectors},
            'clusters': clusters, 'summary': {'source_count': prepared['source_count'], 'selected': prepared['selected_count'],
                'extraction_statuses': dict(Counter(r['status'] for r in prepared['source_records'])),
                'eligibility': dict(Counter(r['eligibility'] for r in prepared['source_records'] if r['status'] == 'included')),
                'claims': len(claims), 'groups': len(clusters), 'candidates_ge3_sources': sum(c['unique_source_count'] >= 3 for c in clusters),
                'accepted_perspectives': 0},
            'limitations': ['Purposive development slice, not representative evaluation', 'Structural validation does not establish semantic fidelity',
                           'No automatic stance compatibility or semantic gate', 'No automatic acceptance, agent generation, or whole-corpus processing']}


def validate_review(report, review, report_hash):
    if review.get('candidate_report_sha256') != report_hash or review.get('reviewer') != 'assistant' or review.get('human_approved') is not False:
        raise ValueError('AI review provenance mismatch or premature approval')
    clusters = {c['id']: c for c in report['clusters']}
    units = {c['claim_id']: c for c in report['claims']}
    seen = set()
    for item in review['findings']:
        cid = item['cluster_id']
        if cid in seen or cid not in clusters or item['status'] not in ['propose_for_user_review', 'split_needed', 'reject', 'uncertain', 'rare']:
            raise ValueError('Invalid cluster review decision')
        seen.add(cid)
        ids = item['evidence_claim_ids']
        if not ids or len(ids) != len(set(ids)) or not set(ids) <= set(clusters[cid]['claim_ids']):
            raise ValueError('Review evidence outside cluster or repeated')
        if item['status'] == 'propose_for_user_review':
            if set(ids) != set(clusters[cid]['claim_ids']):
                raise ValueError('Whole-cluster proposal must account for all members; split first')
            if len({units[i]['source_comment_id'] for i in ids}) < 3 or not item.get('common_claim', '').strip():
                raise ValueError('Proposal needs common claim and 3 unique sources')
        children = item.get('proposed_groups', [])
        if children:
            if item['status'] != 'split_needed' or len(children) < 2:
                raise ValueError('Partition proposal requires split decision and at least two children')
            assigned, child_ids = [], set()
            for child in children:
                if not child.get('id') or child['id'] in child_ids or not child.get('common_claim', '').strip():
                    raise ValueError('Invalid proposed child identity or common claim')
                child_ids.add(child['id'])
                members = child['evidence_claim_ids']
                if not members or not set(members) <= set(clusters[cid]['claim_ids']):
                    raise ValueError('Invalid proposed child members')
                if child.get('status') not in ['propose_for_user_review', 'uncertain', 'rare']:
                    raise ValueError('Proposed split cannot approve a child')
                if child['status'] == 'propose_for_user_review' and len({units[i]['source_comment_id'] for i in members}) < 3:
                    raise ValueError('Proposed child needs 3 unique sources')
                assigned.extend(members)
            if len(assigned) != len(set(assigned)) or set(assigned) != set(clusters[cid]['claim_ids']):
                raise ValueError('Proposed split must partition all parent claims exactly once')


def render(report, review=None, report_hash=None):
    if review is not None:
        validate_review(report, review, report_hash)
    esc = lambda x: html.escape(str(x), quote=True)
    parts = ['<!doctype html><html lang="ko"><meta charset="utf-8"><title>주장 클러스터 검수</title>',
             '<style>body{font:16px system-ui;max-width:1100px;margin:30px auto;padding:16px}article{border:1px solid #bbb;margin:20px 0;padding:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere}.review{background:#eef5ff;padding:12px}</style>',
             '<h1>주장 → 후보 클러스터 → 원문 검수</h1><p>AI 검수 초안. 승인된 관점/agent가 아닙니다. 조건·이유·개인 범위·누락을 확인하세요.</p>',
             '<pre>'+esc(json.dumps(report['summary'], ensure_ascii=False, indent=2))+'</pre>']
    findings = {f['cluster_id']: f for f in review['findings']} if review else {}
    claims = {c['claim_id']: c for c in report['claims']}
    for cluster in report['clusters']:
        cid = cluster['id']
        parts.append('<article id="'+esc(cid)+'"><h2>'+esc(cid)+' · 원문 '+str(cluster['unique_source_count'])+'개 · '+esc(cluster['status'])+'</h2>')
        if cid in findings:
            finding = findings[cid]
            parts.append('<div class="review"><h3>AI 검수 초안 / 사용자 승인 대기</h3><p>'+esc(finding.get('rationale_ko', ''))+'</p>')
            for child in finding.get('proposed_groups', []):
                count = len({claims[i]['source_comment_id'] for i in child['evidence_claim_ids']})
                parts.append('<h4>'+esc(child['id'])+' · 원문 '+str(count)+'개 · '+esc(child['status'])+'</h4><p><strong>'+esc(child['common_claim'])+'</strong></p><p>'+esc(child.get('rationale_ko', ''))+'</p><ul>')
                for caveat in child.get('caveats', []):
                    parts.append('<li>'+esc(caveat)+'</li>')
                parts.append('</ul><p>근거 확인: '+' · '.join('<a href="#'+esc(i)+'">'+str(n)+'</a>' for n, i in enumerate(child['evidence_claim_ids'], 1))+'</p>')
            parts.append('<p>피드백: 공통 설명이 적절한가요? 합치거나 분리할 원문, 빠진 조건을 알려주세요.</p><details><summary>검수 결정/출처 ID</summary><pre>'+esc(json.dumps(finding, ensure_ascii=False, indent=2))+'</pre></details></div>')
        for claim_id in cluster['claim_ids']:
            claim = claims[claim_id]
            source = report['sources'][claim['source_comment_id']]
            parts.append('<h3 id="'+esc(claim_id)+'">'+esc(claim['claim'])+'</h3><p>원문 ID: '+esc(claim['source_comment_id'])+'</p><pre>'+esc(source['text'])+'</pre>')
            if source['parent_id']:
                parent = report['sources'].get(source['parent_id'])
                parts.append('<details><summary>부모 문맥 (지지 근거 아님)</summary><pre>'+esc(parent['text'] if parent else '[parent unavailable]')+'</pre></details>')
            parts.append('<details><summary>추출된 필드/인용</summary><pre>'+esc(json.dumps(claim, ensure_ascii=False, indent=2))+'</pre></details>')
        parts.append('</article>')
    parts.append('<h2>선택 표본 전체 처리 상태 — 실패/0 claims도 숨기지 않음</h2>')
    for record in report['source_records']:
        parts.append('<details><summary>'+esc(json.dumps(record, ensure_ascii=False))+'</summary><pre>'+esc(report['sources'][record['comment_id']]['text'])+'</pre></details>')
    parts.append('</html>')
    return '\n'.join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot')
    parser.add_argument('extraction')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--threshold', type=float, default=0.45)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--render-only', type=Path, help='Saved candidate JSON; output must be a new HTML path')
    args = parser.parse_args()
    if os.path.lexists(args.output) or (not args.render_only and os.path.lexists(str(args.output)+'.html')):
        parser.error('Output exists; choose new paths')
    if args.render_only:
        # Still validate source retention and hashes before showing research artifacts.
        prepared = prepare(args.snapshot, args.extraction)
        report = read_json(args.render_only)
        if report.get('snapshot_sha256') != prepared['snapshot_sha256'] or report.get('extraction_sha256') != prepared['extraction_sha256']:
            parser.error('Saved report source mismatch')
        page = render(report, read_json(args.review) if args.review else None, sha(args.render_only))
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(page)
    else:
        if args.review:
            parser.error('Attach review only after candidate report exists, using --render-only')
        if not math.isfinite(args.threshold) or not 0 < args.threshold < 1:
            parser.error('threshold must be finite and between 0 and 1')
        prepared = prepare(args.snapshot, args.extraction)
        report = build(prepared, embed([embedding_text(c) for c in prepared['claims']]), args.threshold)
        report['embedding']['versions'] = {p: importlib.metadata.version(p) for p in ['torch', 'sentence-transformers', 'numpy']}
        write_json_exclusive(args.output, report)
        with Path(str(args.output)+'.html').open('x', encoding='utf-8') as stream:
            stream.write(render(report))
        print(json.dumps(report['summary'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
