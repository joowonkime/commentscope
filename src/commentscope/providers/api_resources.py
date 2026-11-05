"""Bound durable API records before paid dispatch; no deletion or model loading."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import stat

from commentscope.providers.host_resources import HTTP_API_POLICY,ResourceStopRequested

STORAGE_POLICY={'version':'api-artifact-space-0.1','maximum_run_bytes':1024**3,
                'next_call_headroom_bytes':64*1024**2}


class SpaceGuard:
    def __init__(self,directory,policy,*,disk_usage=shutil.disk_usage):
        if policy!=STORAGE_POLICY:raise ValueError('Frozen API artifact storage policy required')
        self.directory=Path(directory).resolve();self.policy=deepcopy(policy)
        self.disk_usage=disk_usage;self.peak_bytes=0
        self.host_volume=Path('/mnt/c') if Path('/mnt/c').exists() else Path(self.directory.anchor)

    def used_bytes(self):
        size=0
        for path in self.directory.rglob('*'):
            try:info=path.stat()
            except FileNotFoundError:continue  # The observer atomically publishes temporary files.
            if stat.S_ISREG(info.st_mode):size+=info.st_size
        self.peak_bytes=max(self.peak_bytes,size)
        return size

    def check(self,*,additional_bytes=0):
        if type(additional_bytes) is not int or additional_bytes<0:raise ValueError('Bounded additional bytes required')
        needed=additional_bytes+self.policy['next_call_headroom_bytes']
        if self.used_bytes()+needed>self.policy['maximum_run_bytes']:
            raise ResourceStopRequested('API run record limit cannot cover the next durable write')
        floor=HTTP_API_POLICY['minimum_disk_free_bytes']
        for volume in (self.host_volume,self.directory):
            if self.disk_usage(volume).free<floor+needed:
                raise ResourceStopRequested('API disk floor cannot cover the next durable write')

    def before_write(self,value):
        size=len((json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n').encode('utf-8'))
        self.check(additional_bytes=size)

    def summary(self):
        size=self.used_bytes()
        return {'policy':deepcopy(self.policy),'used_bytes':size,'peak_bytes':self.peak_bytes,
                'remaining_bytes':max(0,self.policy['maximum_run_bytes']-size)}
