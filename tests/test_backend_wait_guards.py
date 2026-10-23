from contextlib import contextmanager
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experiments import compare_backend_discovery as quota, compare_backend_admission as backend
from commentscope.storage import write_json_exclusive as write
from commentscope.providers.host_resources import POLICY


def observation(code,latch=False):
    return SimpleNamespace(returncode=code,stdout=json.dumps({'threshold_latched':latch}))


class BackendWaitGuards(unittest.TestCase):
    def test_stale_metadata_waits_for_fresh_before_allowing_the_next_task(self):
        with (patch.object(quota.subprocess,'run',side_effect=[observation(3),observation(0)]) as run,
              patch.object(quota.time,'sleep') as sleep):
            quota.check_quota()
        self.assertEqual(run.call_count,2);sleep.assert_called_once_with(5)

    def test_threshold_and_previously_latched_unknown_never_wait_for_cycle_end(self):
        for code in (2,3):
            with self.subTest(code=code),patch.object(quota.subprocess,'run',return_value=observation(code,True)),patch.object(quota.time,'sleep') as sleep:
                with self.assertRaises(quota.QuotaThresholdReached):quota.check_quota()
                sleep.assert_not_called()

    def test_monitor_preserves_inflight_work_on_stale_but_interrupts_at_threshold(self):
        interrupted=Event();probes=[]
        def check(*,wait_for_fresh=True):
            if wait_for_fresh:return
            probes.append('poll')
            if len(probes)==1:raise quota.QuotaMetadataUnavailable('stale')
            raise quota.QuotaThresholdReached('40 percent')
        with patch.object(quota,'check_quota',side_effect=check),patch.object(quota.os,'kill',side_effect=lambda *args:interrupted.set()) as kill:
            with quota.quota_watch(poll_seconds=.01):
                self.assertTrue(interrupted.wait(timeout=1))
        self.assertEqual(len(probes),2);self.assertEqual(kill.call_count,1)

    def test_actual_model_start_waits_for_unchanged_idle_resource_admission(self):
        with TemporaryDirectory(dir='runs') as temporary:
            root=Path(temporary);calls=[]
            @contextmanager
            def owned(deployment,name,directory):
                calls.append(name)
                write(directory/'stopped.json',{'returncode':0})
                write(directory/'resources/finished.json',{'observer_stopped':True})
                yield 'owned model'
            with (patch.object(backend,'check_quota'),patch.object(backend,'observe',side_effect=[
                 {'refusal_reasons':['idle_ram','idle_commit']},{'refusal_reasons':[]}]) as observe,
                  patch.object(backend.time,'sleep') as sleep,patch.object(backend,'owned_server',side_effect=owned)):
                with backend.lifetimes(root,{'deployment':{},'resource_policy':POLICY},1) as models:
                    self.assertEqual(models.invoke('llm',lambda:'completed'),'completed')
                self.assertEqual(observe.call_count,2);sleep.assert_called_once_with(15)
                self.assertEqual(calls,['baseline'])


if __name__=='__main__':unittest.main()
