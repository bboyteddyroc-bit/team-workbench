"""Experimental Windows kill-on-close job and suspended process launch.

Not integrated into the hub. A job must never be inheritable; failure to assign
or resume kills and waits for the suspended child before handles are closed.
"""
import ctypes
from ctypes import wintypes as w
import subprocess

if not hasattr(ctypes, 'WinDLL'):
    raise RuntimeError('Windows required')
k=ctypes.WinDLL('kernel32',use_last_error=True)
class BASIC(ctypes.Structure):
    _fields_=[('PerProcessUserTimeLimit',ctypes.c_longlong),('PerJobUserTimeLimit',ctypes.c_longlong),('LimitFlags',w.DWORD),('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),('ActiveProcessLimit',w.DWORD),('Affinity',ctypes.c_size_t),('PriorityClass',w.DWORD),('SchedulingClass',w.DWORD)]
class IO(ctypes.Structure):
    _fields_=[(n,ctypes.c_ulonglong) for n in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
class EXT(ctypes.Structure):
    _fields_=[('BasicLimitInformation',BASIC),('IoInfo',IO),('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]
class STARTUP(ctypes.Structure):
    _fields_=[('cb',w.DWORD),('lpReserved',w.LPWSTR),('lpDesktop',w.LPWSTR),('lpTitle',w.LPWSTR),('dwX',w.DWORD),('dwY',w.DWORD),('dwXSize',w.DWORD),('dwYSize',w.DWORD),('dwXCountChars',w.DWORD),('dwYCountChars',w.DWORD),('dwFillAttribute',w.DWORD),('dwFlags',w.DWORD),('wShowWindow',w.WORD),('cbReserved2',w.WORD),('lpReserved2',ctypes.POINTER(ctypes.c_byte)),('hStdInput',w.HANDLE),('hStdOutput',w.HANDLE),('hStdError',w.HANDLE)]
class PROCESS(ctypes.Structure):
    _fields_=[('hProcess',w.HANDLE),('hThread',w.HANDLE),('dwProcessId',w.DWORD),('dwThreadId',w.DWORD)]
def api(name,restype,args):
    f=getattr(k,name);f.restype=restype;f.argtypes=args;return f
create_job=api('CreateJobObjectW',w.HANDLE,[w.LPVOID,w.LPCWSTR])
set_job=api('SetInformationJobObject',w.BOOL,[w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD])
create_process=api('CreateProcessW',w.BOOL,[w.LPCWSTR,w.LPWSTR,w.LPVOID,w.LPVOID,w.BOOL,w.DWORD,w.LPVOID,w.LPCWSTR,w.LPVOID,ctypes.POINTER(PROCESS)])
init_attrs=api('InitializeProcThreadAttributeList',w.BOOL,[w.LPVOID,w.DWORD,w.DWORD,ctypes.POINTER(ctypes.c_size_t)])
update_attrs=api('UpdateProcThreadAttribute',w.BOOL,[w.LPVOID,w.DWORD,ctypes.c_size_t,w.LPVOID,ctypes.c_size_t,w.LPVOID,w.LPVOID])
delete_attrs=api('DeleteProcThreadAttributeList',None,[w.LPVOID])

class STARTUP_EX(ctypes.Structure):
    _fields_=[('startup',STARTUP),('attributes',w.LPVOID)]

def create_in_job(args,job,pi):
    size=ctypes.c_size_t()
    init_attrs(None,1,0,ctypes.byref(size))
    check(size.value)
    attrs=ctypes.create_string_buffer(size.value)
    check(init_attrs(attrs,1,0,ctypes.byref(size)))
    try:
        jobs=(w.HANDLE*1)(job)
        check(update_attrs(attrs,0,0x2000D,jobs,ctypes.sizeof(jobs),None,None))
        startup=STARTUP_EX();startup.startup.cb=ctypes.sizeof(startup)
        startup.attributes=ctypes.cast(attrs,w.LPVOID)
        cmd=ctypes.create_unicode_buffer(subprocess.list2cmdline([str(x) for x in args]))
        check(create_process(str(args[0]),cmd,None,None,False,0x80000|0x4|0x08000000|0x4000,None,None,ctypes.byref(startup),ctypes.byref(pi)))
    finally:
        delete_attrs(attrs)
assign=api('AssignProcessToJobObject',w.BOOL,[w.HANDLE,w.HANDLE])
resume=api('ResumeThread',w.DWORD,[w.HANDLE])
terminate=api('TerminateProcess',w.BOOL,[w.HANDLE,w.UINT])
wait=api('WaitForSingleObject',w.DWORD,[w.HANDLE,w.DWORD])
exit_code=api('GetExitCodeProcess',w.BOOL,[w.HANDLE,ctypes.POINTER(w.DWORD)])
close=api('CloseHandle',w.BOOL,[w.HANDLE])
def check(ok):
    if not ok:raise ctypes.WinError(ctypes.get_last_error())

query_job=api('QueryInformationJobObject',w.BOOL,[w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD,w.LPVOID])
terminate_job=api('TerminateJobObject',w.BOOL,[w.HANDLE,w.UINT])
open_job=api('OpenJobObjectW',w.HANDLE,[w.DWORD,w.BOOL,w.LPCWSTR])

class Accounting(ctypes.Structure):
    _fields_=[('times',ctypes.c_longlong*4),('faults',w.DWORD),('total',w.DWORD),('active',w.DWORD),('terminated',w.DWORD)]

def drain(job):
    import time
    deadline=time.monotonic()+5
    check(terminate_job(job,1))
    info=Accounting()
    while True:
        check(query_job(job,1,ctypes.byref(info),ctypes.sizeof(info),None))
        if not info.active:return
        if time.monotonic()>=deadline:raise TimeoutError('Job Object still active')
        time.sleep(.025)

def recover_job(token):
    job=open_job(0x0004|0x0008,False,job_name(token))
    if not job:
        if ctypes.get_last_error()==2:return
        check(job)
    try:drain(job)
    finally:close(job)

def job_name(token):
    import re
    if not re.fullmatch('[0-9a-f]{32}',token):raise ValueError('invalid proxy job token')
    return 'Global\\SeedanceHubPreview-'+token

class OwnedJob:
    def __init__(self,args,token=None):
        if not args:raise ValueError('empty command')
        self.job=None;self.process=None;self.pid=None
        job=create_job(None,job_name(token) if token else None);check(job)
        if token and ctypes.get_last_error()==183:
            close(job)
            raise RuntimeError('preview job already exists')
        self.job=job
        pi=PROCESS()
        try:
            limits=EXT();limits.BasicLimitInformation.LimitFlags=0x2000
            check(set_job(job,9,ctypes.byref(limits),ctypes.sizeof(limits)))
            create_in_job(args,job,pi)
            self.process=pi.hProcess;self.pid=pi.dwProcessId
            try:
                if resume(pi.hThread)==0xffffffff:raise ctypes.WinError(ctypes.get_last_error())
            finally:close(pi.hThread)
        except BaseException:
            if self.process:
                terminated=terminate(self.process,1)
                stopped=wait(self.process,5000)==0
                close(self.process);self.process=None
                close(job);self.job=None
                if not stopped:
                    raise RuntimeError('suspended child exit could not be verified')
            else:
                close(job);self.job=None
            raise
    def wait(self,ms):
        result=wait(self.process,ms)
        if result==0x102:return None
        if result!=0:raise ctypes.WinError(ctypes.get_last_error())
        code=w.DWORD();check(exit_code(self.process,ctypes.byref(code)));return code.value
    def stop(self):
        if self.process and self.wait(0) is None:
            check(terminate(self.process,1))
            if self.wait(5000) is None:raise TimeoutError('child stop unconfirmed')
    def close(self):
        if self.job:close(self.job);self.job=None
        if self.process:close(self.process);self.process=None
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
