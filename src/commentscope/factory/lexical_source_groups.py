"""Deterministic full-original TF-IDF groups; no model vectors or review labels.

Grouping proposes places to look for shared statements. Similarity never counts
as stance support. Every supplied source remains in exactly one discovery group.
"""
from array import array
from collections import Counter
import math
import re
from commentscope.factory import minimal_claims as mc
from commentscope.factory.named_candidate_census import STOP

VERSION='own-original-lexical-groups-20261023-v2'

def features(text):
    words=re.findall(r"[a-z0-9]+(?:'[a-z]+)?",text.lower())
    terms=[w for w in words if w not in STOP]
    return Counter([*terms,*(' '.join(p) for p in zip(words,words[1:]))])

def groups(sources,*,size=12):
    ss=mc.source_index(sources)
    if not 2<=size<=12 or not 2<=len(ss)<=5000:
        raise ValueError('Discovery needs2..5000 originals and groups of2..12')
    ids=sorted(ss);docs=[features(ss[sid]['text']) for sid in ids];df=Counter()
    for doc in docs:df.update(doc.keys())
    vectors=[]
    for doc in docs:
        v={t:(1+math.log(count))*(1+math.log((1+len(ids))/(1+df[t]))) for t,count in doc.items()}
        norm=math.sqrt(sum(x*x for x in v.values()))
        vectors.append({t:x/norm for t,x in v.items()} if norm else {})
    n=len(ids);scores=array('f',[0])*(n*n)
    for i,a in enumerate(vectors):
        for j in range(i):
            b=vectors[j];small,large=(a,b) if len(a)<len(b) else (b,a)
            score=sum(v*large.get(t,0) for t,v in small.items())
            scores[i*n+j]=scores[j*n+i]=score
    # Exact repetitions of one word have cosine1 but supply little discoverable
    # content. Prioritize similarity with bounded lexical information, without
    # filtering any source or using a stance/source-specific whitelist.
    cohesion={i:min(1,len(docs[i])/24)*sum(sorted((scores[i*n+j] for j in range(n) if j!=i),reverse=True)[:2])/min(2,n-1) for i in range(n)}
    seeds=sorted(range(n),key=lambda i:(-cohesion[i],ids[i]));remaining=set(range(n));result=[]
    for seed in seeds:
        if seed not in remaining:continue
        ranked=sorted(remaining,key=lambda j:(-scores[seed*n+j],ids[j]));ranked.remove(seed)
        take=min(size,len(remaining))
        if len(remaining)-take==1:take-=1
        selected=[seed,*ranked[:take-1]]
        if len(selected)<2:raise ValueError('No singleton discovery group may be hidden')
        result.append([ss[ids[j]] for j in selected]);remaining.difference_update(selected)
    if remaining or sorted(s['id'] for g in result for s in g)!=ids:
        raise ValueError('Every original must remain in exactly one discovery group')
    return result
