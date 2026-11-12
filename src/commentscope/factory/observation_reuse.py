"""Read-only observation reuse with original wire, route and receipt evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json
from commentscope.factory.shared_admission import PriorRequestUnavailable
from commentscope.providers import remote_verification as remote,openrouter
from commentscope.providers.generation_limits import allocate

VERSION='exact-original-observation-reuse-20261113-v1'


def file_sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def object_array(path,*,chunk_size=65536):
    """Stream complete top-level JSON objects; never split or edit an object."""
    decoder=json.JSONDecoder();buffer='';eof=False
    with Path(path).open(encoding='utf-8') as f:
        def fill():
            nonlocal buffer,eof
            part=f.read(chunk_size);eof=not part;buffer+=part
        def ready():
            nonlocal buffer
            while not buffer.strip() and not eof:fill()
            buffer=buffer.lstrip()
        ready()
        if not buffer.startswith('['):raise ValueError('JSON object array required')
        buffer=buffer[1:];first=True
        while True:
            ready()
            if first and buffer.startswith(']'):
                buffer=buffer[1:];break
            while True:
                try:value,end=decoder.raw_decode(buffer);break
                except json.JSONDecodeError:
                    if eof:raise ValueError('Incomplete original JSON object array') from None
                    fill()
            if not isinstance(value,dict):raise ValueError('Only complete batch objects allowed')
            yield value;first=False;buffer=buffer[end:];ready()
            if buffer.startswith(']'):buffer=buffer[1:];break
            if not buffer.startswith(','):raise ValueError('Original array delimiter changed')
            buffer=buffer[1:]
        while not eof:fill()
        if buffer.strip():raise ValueError('Trailing original array content')


def build_index(archives):
    """archives selects explicit families per original run, not best responses."""
    entries={};origins=[]
    for directory,families in archives:
        directory=Path(directory).resolve();plan=read_json(directory/'plan.json');plan_sha=file_sha(directory/'plan.json')
        done=read_json(directory/'completed.json')
        if done['plan_sha256']!=plan_sha:raise ValueError('Original completion changed')
        if 'output_sha256' in done and file_sha(directory/'artifacts/output.json')!=done['output_sha256']:raise ValueError('Original output changed')
        origins.append(dict(directory=str(directory),plan_sha256=plan_sha,completed_sha256=file_sha(directory/'completed.json')))
        for path in sorted((directory/'calls').glob('*.request.json')):
            stage=path.name.split('-',1)[1].removesuffix('.request.json')
            role=next((k for k in ('generation','verification') if stage.startswith(k+'-')),None)
            if role is None:continue
            family=re.sub(r'-[a-f0-9]{20}$','',stage[len(role)+1:])
            if family not in families:continue
            saved=read_json(path);actual=saved['request'];deployment=plan['deployment' if role=='generation' else 'verification_deployment']
            if saved['plan_sha256']!=plan_sha or saved['request_sha256']!=digest(actual):raise ValueError('Original request binding changed')
            response=path.with_name(path.name.replace('.request.json','.result.json'))
            row=dict(family=family,actual_request_sha256=digest(actual),deployment=deployment,
                original_plan_sha256=plan_sha,request_file=str(path),request_file_sha256=file_sha(path),
                response_file=str(response),response_file_sha256=file_sha(response) if response.exists() else None)
            entries.setdefault(digest([family,digest(actual),digest(deployment)]),[]).append(row)
    return dict(version=VERSION,origins=origins,entries=entries)


class OriginalObservations:
    def __init__(self,index,save):
        if index['version']!=VERSION:raise ValueError('Explicit original observation index required')
        self.index=index;self.save=save;self.reused=set();self.blocked=set()

    def lookup(self,family,request,deployment):
        actual=allocate(request,openrouter.generation_allocation(deployment,require_explicit=True))
        key=digest([family,digest(actual),digest(deployment)]);rows=self.index['entries'].get(key)
        if rows is None:return None
        if len(rows)!=1:
            self.blocked.add(key);raise PriorRequestUnavailable('Ambiguous original attempts cannot be retried')
        row=rows[0]
        if file_sha(row['request_file'])!=row['request_file_sha256']:raise ValueError('Original cached request changed')
        saved=read_json(row['request_file'])
        if saved['request']!=actual or saved['plan_sha256']!=row['original_plan_sha256']:raise ValueError('Original request differs')
        if row['response_file_sha256'] is None:
            self.blocked.add(key);raise PriorRequestUnavailable('Original unfinished attempt remains unavailable')
        if file_sha(row['response_file'])!=row['response_file_sha256']:raise ValueError('Original cached response changed')
        result=read_json(row['response_file'])
        if result.get('errors'):
            self.blocked.add(key);self.save('original-unavailable/'+key,row)
            raise PriorRequestUnavailable('Original failed model response is not a retry grant')
        remote.parsed_receipt(result,actual,deployment)
        self.save('original-reuse/'+key,{**row,'logical_request_sha256':digest(request),'result_sha256':digest(result)})
        self.reused.add(key);return deepcopy(result)
