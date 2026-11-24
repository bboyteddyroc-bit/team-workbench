"""Identify interrupted assistant work without retrying a paid submission."""
import os
import time


def process_stamp(pid):
    if pid <= 0:
        return None
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return 'unverifiable' if ctypes.get_last_error() == 5 else None
        try:
            values = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(v) for v in values)):
                return 'unverifiable'
            return str((values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        from pathlib import Path
        # Linux: field 22, parsed after the potentially space-containing comm.
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        try:
            os.kill(pid, 0)
            return 'unverifiable'
        except ProcessLookupError:
            return None
        except PermissionError:
            return 'unverifiable'


def recover_interrupted(db, owner):
    for row in db.execute("SELECT id,runner_pid,runner_stamp,created,generation FROM ai_turns WHERE owner=? AND status='pending'", (owner,)).fetchall():
        if not row['runner_pid']:
            # Legacy rows have no runner identity: don't steal an old live request
            # during a rolling upgrade. After an hour they become manual recovery.
            interrupted = row['created'] < time.time() - 3600
        else:
            stamp = process_stamp(row['runner_pid'])
            interrupted = stamp is None or (stamp != 'unverifiable' and stamp != row['runner_stamp'])
        if interrupted:
            answer = ('服务中断，提交结果需核对；有原画布时可取回，不会重新生成。'
                      if row['generation'] != '{}' else '服务中断，回答未完成；未自动重新发送。')
            db.execute("UPDATE ai_turns SET status='failed',answer=?,runner_pid=0,runner_stamp='' WHERE id=? AND status='pending'", (answer, row['id']))
