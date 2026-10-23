"""Wait for exact source validation before counting; never invokes a model.

The existing Codex direct-review step writes semantic-review records. Selection
order is fixed by the experiment, not by a hand-selected successful source pack.
No review judgment is sent to Qwen or used to edit generated content.
"""
from pathlib import Path
from copy import deepcopy
import time
from commentscope.factory import reviewed_source_admission as gate
from commentscope.factory.claim_clusters import read_json,sha
from commentscope.storage import write_json_exclusive as write

VERSION='exact-source-review-queue-20261023-v1'

class SourceReviewQueue:
    def __init__(self,directory,priors,boundary,*,wait_seconds=600):
        self.directory=Path(directory);self.priors=[Path(p) for p in priors]
        self.boundary=boundary;self.wait_seconds=wait_seconds

    def __call__(self,accepted,status):
        self.boundary();sid=accepted['source_id'];cid=accepted['candidate_id'];rel=Path(cid)/(sid+'.json')
        paths={k:self.directory/'artifacts'/k/rel for k in gate.KINDS}
        if any(not p.resolve().is_relative_to(self.directory.resolve()) for p in paths.values()):
            raise ValueError('Source review path escapes experiment')
        artifacts={k:read_json(p) for k,p in paths.items()}
        packet=gate.packet(accepted,artifacts,{str(p):sha(p) for p in paths.values()})
        queue=self.directory/'review-queue'/rel;target=self.directory/'semantic-review'/rel
        if queue.exists():
            if read_json(queue)!=packet:raise ValueError('Immutable review queue packet changed')
        else:write(queue,packet)
        if not target.exists():
            for prior in self.priors:
                previous=prior/'semantic-review'/rel
                if not previous.exists():continue
                review=read_json(previous)
                if not gate.complete_review(review):continue
                if any(sha(path)!=expected for path,expected in review['files_sha256'].items()):
                    raise ValueError('Prior source review evidence changed')
                old={k:prior/'artifacts'/k/rel for k in gate.KINDS}
                if not all(p.exists() and sha(p)==sha(paths[k]) for k,p in old.items()):continue
                copied=deepcopy(review);copied['files_sha256']=packet['files_sha256']
                copied['reused_from']={'path':str(previous),'sha256':sha(previous),
                    'condition':'all4 immutable source/core/draft artifacts exactly identical'}
                gate.bind(accepted,packet,copied);write(target,copied);break
        started=time.monotonic()
        while not target.exists():
            self.boundary()
            if time.monotonic()-started>=self.wait_seconds:
                raise RuntimeError('Exact source review pending; no unreviewed vote counted: '+str(queue))
            time.sleep(1)
        self.boundary();review=read_json(target)
        gate.bind(accepted,packet,review)
        return packet,review
