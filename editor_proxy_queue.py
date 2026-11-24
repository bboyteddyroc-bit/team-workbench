"""Bounded, process-local proxy work coordinator. No jobs start on import.

This coordinator is deliberately not wired to production: process-local locking
alone cannot safely deduplicate the local and LAN workers.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock


class ProxyQueue:
    def __init__(self, capacity=16, worker=None):
        if capacity<1 or worker is None:
            raise ValueError('capacity and worker required')
        self._capacity=capacity
        self._worker=worker
        self._lock=Lock()
        self._jobs={}
        self._pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='preview-proxy')
        self._closed=False

    def submit(self,key,source_version):
        """Return queued/already_pending/full; never queue a duplicate key/version."""
        job=(key,source_version)
        with self._lock:
            if self._closed:raise RuntimeError('queue closed')
            if job in self._jobs:return 'already_pending'
            if len(self._jobs)>=self._capacity:return 'full'
            self._jobs[job]='queued'
            try:self._pool.submit(self._run,job)
            except BaseException:
                del self._jobs[job]
                raise
            return 'queued'

    def _run(self,job):
        with self._lock:self._jobs[job]='running'
        try:self._worker(*job)
        finally:
            with self._lock:self._jobs.pop(job,None)

    def pending(self):
        with self._lock:return dict(self._jobs)

    def close(self):
        with self._lock:self._closed=True
        self._pool.shutdown(wait=True)
