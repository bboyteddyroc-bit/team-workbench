"""Keep the cross-process worker lease until every started worker has stopped."""
import logging
import threading
import time


def drain_workers(stop, threads, lock, timeout=10):
    stop.set()
    deadline = time.monotonic() + max(0, timeout)
    for thread in threads:
        if thread.ident is not None:
            thread.join(max(0, deadline - time.monotonic()))
    pending = [thread for thread in threads if thread.is_alive()]
    if not pending:
        if lock:
            lock.close()
        return None

    # A timeout is not evidence of termination. A non-daemon custodian prevents
    # normal process exit and retains the OS file lock during the remaining I/O.
    # An explicit OS process termination still releases it only after process death.
    logging.getLogger(__name__).warning('Worker shutdown draining %d thread(s); lease retained', len(pending))

    def finish():
        for thread in pending:
            thread.join()
        if lock:
            lock.close()

    custodian = threading.Thread(target=finish, name='hub-worker-drain', daemon=False)
    custodian.start()
    return custodian
