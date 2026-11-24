"""Best-effort local journal for Apify Actor submissions, never for polling."""
import json
import logging
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone


_LOG_NAME = 'apify-submit.jsonl'
_MAX_BYTES = 2 * 1024 * 1024
_LOCK = threading.Lock()  # The single hub worker has separate monitor and case threads.
_LOGGER = logging.getLogger(__name__)
_BINDING = re.compile(r'(run|group|case):([0-9a-f]{32})')
_TYPE = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,63}')
_SQLITE = re.compile(r'SQLITE_[A-Z0-9_]{1,63}')


def _append(directory, line):
    with _LOCK:
        folder = directory / 'logs'
        folder.mkdir(exist_ok=True)
        path = folder / _LOG_NAME
        if path.exists() and path.stat().st_size + len(line) > _MAX_BYTES:
            path.replace(folder / (_LOG_NAME + '.1'))
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_BINARY', 0)
        with os.fdopen(os.open(path, flags, 0o600), 'ab') as stream:
            stream.write(line)


class SubmissionTrace:
    def __init__(self, directory, binding):
        self.directory = directory
        self.binding = binding
        match = _BINDING.fullmatch(binding)
        self.kind, self.local_id = match.groups() if match else (None, None)
        self.stage = 'prepare_payload'
        self.dispatch_started = False
        self.http_status = None
        self.has_run_id = False
        self.error = {}

    def _event(self, event):
        if self.local_id is None:
            return  # Do not echo unknown identifiers or arbitrary request data.
        entry = dict(at_utc=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                     kind=self.kind, local_id=self.local_id, event=event, stage=self.stage,
                     dispatch_started=self.dispatch_started, http_status=self.http_status,
                     has_run_id=self.has_run_id, **self.error)
        line = (json.dumps(entry, separators=(',', ':')) + '\n').encode('ascii')
        try:
            _append(self.directory, line)
        except OSError:
            # A bad log path must not turn a paid submission into a retryable failure.
            try:
                _LOGGER.warning('Apify submission journal unavailable: %s', line.decode('ascii').rstrip())
            except Exception:
                pass  # Diagnostics must not interfere with the task outcome.

    def __enter__(self):
        self._event('started')
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc is not None:
            if not self.error:
                self.capture_error(exc)
            self._event('failed')
        from task_feedback import current
        step = current()
        if step is not None and step.stage == 'apify_submit':
            step.http(self.http_status)
            step.transport(self.dispatch_started, self.has_run_id)
            step.error_type(self.error.get('error_type'))
            if exc is None:
                return
            step.move({
                'prepare_payload':'apify_payload', 'select_key':'apify_key', 'init_client':'apify_connection',
                'prepare_request':'apify_connection', 'read_response':'apify_response',
                'decode_json':'apify_response', 'validate_response':'apify_response',
                'validate_run_id':'apify_run_id', 'persist_run_id':'apify_record',
            }.get(self.stage, 'apify_submit'))
            if not self.dispatch_started and self.stage in ('prepare_payload','select_key','init_client','prepare_request'):
                step.mark('blocked')
            elif self.http_status in (400,401,402,403,404,422,429) and not self.has_run_id:
                step.mark('failed')

    def capture_error(self, exc):
        name = type(exc).__name__
        self.error['error_type'] = name if _TYPE.fullmatch(name) else 'Exception'
        if isinstance(exc, sqlite3.Error):
            sqlite_name = getattr(exc, 'sqlite_errorname', None)
            if isinstance(sqlite_name, str) and _SQLITE.fullmatch(sqlite_name):
                self.error['sqlite_error'] = sqlite_name

    def before_transport(self, _request):
        # HTTPX invokes this before transport, not after delivery to Apify.
        self.stage = 'transport'
        self.dispatch_started = True
        self._event('dispatch_started')

    def observe_response(self, response):
        # The response hook runs before body reading; keep the status even if reading times out.
        if self.http_status is None:
            status = response.status_code
            self.http_status = status if type(status) is int and 100 <= status <= 599 else None
            self.stage = 'read_response'
            self._event('http_response')

    def received_run_id(self):
        # Do not log the response body or even its run ID value. Record presence only.
        self.has_run_id = True
        self.stage = 'persist_run_id'
        self._event('run_id_received')

    def saved(self):
        self._event('run_id_saved')
