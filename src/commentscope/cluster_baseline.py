"""Local V0 experiment: semantic candidates, NEVER accepted perspectives.

Run with python -m commentscope.cluster_baseline SNAPSHOT --output ARTIFACT.
Download model weights only; comment inference runs on CPU locally.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import html
import importlib.metadata
import json
import os
from pathlib import Path

from commentscope.ingestion import load_snapshot, normalize_snapshot
from commentscope.storage import write_json_exclusive

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"


def token_chunks(tokenizer, text, max_length):
    """Cover every original token; account for decode/re-encode expansion."""
    tokens = tokenizer.encode(text, add_special_tokens=False, truncation=False)
    start = 0
    budget = max_length - tokenizer.num_special_tokens_to_add(pair=False)
    if budget < 1:
        raise ValueError('Model token budget too small')
    while start < len(tokens):
        size = min(budget, len(tokens)-start)
        while True:
            decoded = tokenizer.decode(tokens[start:start+size], skip_special_tokens=True)
            if len(tokenizer.encode(decoded, add_special_tokens=True, truncation=False)) <= max_length:
                break
            if size == 1:
                raise ValueError('Single-token round-trip exceeds model budget')
            size = max(1, size//2)
        yield decoded, size
        start += size


def validate_audit(report, audit):
    if audit['snapshot_sha256'] != report['snapshot_sha256']:
        raise ValueError('Audit source digest mismatch')
    clusters = {g['id']:set(g['members']) for g in report['clusters']}
    for finding in audit['findings']:
        if not finding['evidence_ids'] or not set(finding['evidence_ids']) <= clusters.get(finding['cluster'], set()):
            raise ValueError('Audit evidence must belong to the cited cluster')


def review_html(report, audit=None):
    """No scripts, external resources, or unescaped source text."""
    esc = lambda value: html.escape(str(value), quote=True)
    parts = ['<!doctype html><html lang="ko"><meta charset="utf-8">',
             '<title>CommentScope V0 검수</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:20px}article{border:1px solid #aaa;padding:18px;margin:20px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#555}</style>',
             '<h1>V0 클러스터 검수 — 확정 관점 아님</h1>',
             '<p>원문 의미 유사도만 사용. 찬반 분리·주장 추출·사실 검증 없음. 3개 이상도 검수 전 후보이며 에이전트가 아닙니다.</p>',
             '<p>검수 기준: 같은 이슈인가? 입장/이유/조건이 호환되는가? 인용이 주장을 지지하는가? split/merge/rare/uncertain 중 무엇인가?</p>',
             '<pre>'+esc(json.dumps(report['summary'], ensure_ascii=False, indent=2))+'</pre>']
    sources = report['sources']
    if audit is not None:
        validate_audit(report, audit)
        parts.append('<h2>탐색적 검수: 아직 에이전트로 사용하면 안 됩니다</h2><p>AI 보조 검토이며 독립적인 사람의 정답 라벨이나 정확도 측정이 아닙니다.</p>')
        for finding in audit['findings']:
            parts.append('<p><a href="#'+esc(finding['cluster'])+'">'+esc(finding['cluster'])+'</a>: '+esc(finding['rationale_ko'])+'</p>')
    for group in report['clusters']:
        parts.append('<article id="'+esc(group['id'])+'"><h2>'+esc(group['id'])+' · '+str(len(group['members']))+' sources · '+esc(group['status'])+'</h2>')
        parts.append('<p>대표 원문 (자동 요약/관점명이 아님): '+esc(sources[group['representatives'][0]]['text'])+'</p>')
        parts.append('<small>평균 내부 cosine '+esc(group['mean_pair_cosine'])+' · 가까운 후보 '+esc(group['nearest_cluster'])+'</small>')
        parts.append('<details><summary>전체 근거 / 부모 문맥</summary>')
        for cid in group['members']:
            source = sources[cid]
            parts.append('<h3>'+esc(cid)+'</h3><pre>'+esc(source['text'])+'</pre>')
            if source['parent_id']:
                parent = sources.get(source['parent_id'])
                parts.append('<small>Parent: '+esc(source['parent_id'])+'</small><pre>'+esc(parent['text'] if parent else '[parent unavailable]')+'</pre>')
        parts.append('</details></article>')
    parts.append('</html>')
    return '\n'.join(parts)


def run(snapshot_path, output, threshold=0.45):
    if not 0 < threshold < 1:
        raise ValueError('threshold must be between 0 and 1')
    if os.path.lexists(output) or os.path.lexists(str(output)+'.html'):
        raise FileExistsError('Choose new output paths; never overwrite artifacts')
    loaded = load_snapshot(snapshot_path)
    s = loaded.snapshot
    if s.usage.expires_at and datetime.fromisoformat(s.usage.expires_at.replace('Z', '+00:00')) <= datetime.now(timezone.utc):
        raise ValueError('Snapshot expired; refresh or review retention before processing')
    rows = sorted((c for c in normalize_snapshot(s) if c.duplicate_of is None and c.text_analysis), key=lambda c:c.comment_id)
    if not 2 <= len(rows) <= 10000:
        raise ValueError('V0 supports 2..10000 canonical nonempty comments')
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer
    from sklearn.cluster import AgglomerativeClustering
    torch.set_num_threads(4)
    model = SentenceTransformer(MODEL, revision=REVISION, device='cpu', trust_remote_code=False,
                                model_kwargs={'use_safetensors': True})
    # Pool all nonoverlapping token chunks; never silently truncate long comments.
    chunks, owners, weights = [], [], []
    for i, row in enumerate(rows):
        for decoded, size in token_chunks(model.tokenizer, row.text_analysis, model.max_seq_length):
            chunks.append(decoded)
            owners.append(i)
            weights.append(size)
    # Input token IDs are re-encoded from decoded chunks; track any overflow explicitly.
    overflow = sum(len(model.tokenizer.encode(c, add_special_tokens=True)) > model.max_seq_length for c in chunks)
    if overflow:
        raise ValueError('Token chunk round-trip overflow; reduce chunk size before running')
    encoded = model.encode(chunks, batch_size=32, normalize_embeddings=True, show_progress_bar=True)
    vectors = np.zeros((len(rows), encoded.shape[1]), dtype=np.float32)
    for owner, weight, vector in zip(owners, weights, encoded):
        vectors[owner] += weight * vector
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if not np.isfinite(vectors).all() or (norms == 0).any():
        raise ValueError('Invalid embeddings')
    vectors /= norms
    similarities = np.clip(vectors @ vectors.T, -1, 1)
    def labels_at(value):
        return AgglomerativeClustering(n_clusters=None, metric='cosine', linkage='average', distance_threshold=value).fit_predict(vectors)
    sweeps = []
    for value in sorted(set([0.35,0.45,0.55,threshold])):
        counts = Counter(map(int, labels_at(value)))
        sweeps.append({'distance_threshold':value,'groups':len(counts),'groups_ge3':sum(n>=3 for n in counts.values()),'sources_in_ge3':sum(n for n in counts.values() if n>=3),'largest':max(counts.values())})
    labels = labels_at(threshold)
    partitions = {}
    for i, label in enumerate(labels):
        partitions.setdefault(int(label), []).append(i)
    groups = sorted(partitions.values(), key=lambda ids:(-len(ids), rows[ids[0]].comment_id))
    clusters, centers = [], []
    for number, ids in enumerate(groups, 1):
        block = similarities[np.ix_(ids,ids)]
        scores = block.mean(axis=1)
        representatives = sorted(range(len(ids)),key=lambda i:(-float(scores[i]),rows[ids[i]].comment_id))[:5]
        center = vectors[ids].mean(axis=0)
        centers.append(center / np.linalg.norm(center))
        clusters.append({'id':f'C{number:03d}','status':'candidate_needs_review' if len(ids)>=3 else 'rare_unreviewed',
                         'members':[rows[i].comment_id for i in ids],
                         'representatives':[rows[ids[i]].comment_id for i in representatives],
                         'mean_pair_cosine':float((block.sum()-len(ids))/(len(ids)*(len(ids)-1))) if len(ids)>1 else None})
    near = np.array(centers) @ np.array(centers).T
    np.fill_diagonal(near,-np.inf)
    for i, group in enumerate(clusters):
        j = int(near[i].argmax())
        group['nearest_cluster'] = clusters[j]['id'] if len(clusters)>1 else None
        group['nearest_cosine'] = float(near[i,j]) if len(clusters)>1 else None
    report = {'artifact_kind':'v0_semantic_candidate_review','created_at':datetime.now(timezone.utc).isoformat(),
              'snapshot_id':s.snapshot_id,'snapshot_sha256':loaded.sha256,'expires_at':s.usage.expires_at,
              'model':MODEL,'model_revision':REVISION,'algorithm':'cosine-average-agglomerative',
              'threshold':threshold,'pooling':'token-weighted mean of normalized nonoverlapping chunk embeddings',
              'versions':{p:importlib.metadata.version(p) for p in ['torch','sentence-transformers','scikit-learn','numpy']},
              'summary':{'source_count':len(s.comments),'canonical_nonempty':len(rows),'token_chunks':len(chunks),
                         'groups':len(clusters),'candidates_ge3':sum(len(g['members'])>=3 for g in clusters),'accepted_perspectives':0},
              'threshold_sweep':sweeps,'clusters':clusters,
              'sources':{c.comment_id:{'text':c.text_original,'parent_id':c.parent_id} for c in s.comments},
              'limitations':['No eligibility filtering or claim extraction','No stance compatibility gate','No automatic perspective acceptance','Threshold sweep is sensitivity, not accuracy','English-heavy single-video sample; not multilingual validation','Partial threads; embedded mentions remain; local review only']}
    write_json_exclusive(output,report)
    with open(str(output)+'.html','x',encoding='utf-8') as handle:
        handle.write(review_html(report))
    print(json.dumps({'output':str(output),'summary':report['summary'],'threshold_sweep':sweeps},indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot')
    parser.add_argument('--output',required=True)
    parser.add_argument('--threshold',type=float,default=0.45)
    args=parser.parse_args()
    run(args.snapshot,args.output,args.threshold)
