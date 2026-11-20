"""Owned process trees: deadlines, lease loss, and parent death on Windows/POSIX."""
import ctypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
import psutil

_worker_job = None  # Intentionally held until OS process teardown, never closed per task.


class WindowsJob:
    def __init__(self):
        from ctypes import wintypes as w
        class IO(ctypes.Structure):
            _fields_=[(n,ctypes.c_ulonglong) for n in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Basic(ctypes.Structure):
            _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',w.DWORD),
                ('min_working',ctypes.c_size_t),('max_working',ctypes.c_size_t),('active',w.DWORD),
                ('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
        class Extended(ctypes.Structure):
            _fields_=[('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),
                ('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        self.api.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];self.api.CreateJobObjectW.restype=w.HANDLE
        self.api.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
        self.api.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
        self.api.GetCurrentProcess.restype=w.HANDLE
        self.api.CloseHandle.argtypes=[w.HANDLE]
        self.handle=self.api.CreateJobObjectW(None,None)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        info=Extended();info.basic.flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle,9,ctypes.byref(info),ctypes.sizeof(info)):
            self.close();raise ctypes.WinError(ctypes.get_last_error())

    def assign(self,handle):
        if not self.api.AssignProcessToJobObject(self.handle,handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle);self.handle=None


def ensure_worker_job():
    """Outer job closes even if Worker is forcibly killed during child startup."""
    global _worker_job
    if os.name=='nt' and _worker_job is None:
        job=WindowsJob()
        try:job.assign(job.api.GetCurrentProcess())
        except BaseException:job.close();raise
        _worker_job=job


def start_owned(command,**kwargs):
    ensure_worker_job()
    job=None;proc=None
    try:
        if os.name=='nt':
            job=WindowsJob()
            # Suspend before Python's venv launcher can create an escaping descendant.
            proc=subprocess.Popen(command,creationflags=0x08000000|0x4,**kwargs)
            job.assign(int(proc._handle))
            psutil.Process(proc.pid).resume()
        else:
            proc=subprocess.Popen(command,start_new_session=True,**kwargs)
        return proc,job
    except BaseException:
        if job:job.close()
        if proc:
            try:proc.kill();proc.wait(timeout=5)
            except (OSError,subprocess.TimeoutExpired):pass
        raise


def stop_owned(proc,job):
    if job:job.close()  # All descendants, including a venv launcher's Python process.
    elif os.name!='nt':
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=5)


def parent_pipe_guard():
    """Used in child after its request line. EOF means parent died or withdrew."""
    if os.name=='nt':
        # A blocking os.read holds the Windows CRT descriptor lock. Imports that
        # query stdin (e.g. progress libraries) can then deadlock on isatty().
        import msvcrt
        from ctypes import wintypes as w
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.PeekNamedPipe.argtypes=[w.HANDLE,ctypes.c_void_p,w.DWORD,ctypes.c_void_p,ctypes.POINTER(w.DWORD),ctypes.c_void_p]
        handle=msvcrt.get_osfhandle(sys.stdin.fileno())
        while True:
            available=w.DWORD()
            if not api.PeekNamedPipe(handle,None,0,None,ctypes.byref(available),None):break
            if available.value:break
            time.sleep(.2)
        os._exit(137)
    elif os.read(sys.stdin.fileno(),1)==b'':
        if os.name!='nt':
            os.killpg(os.getpgrp(),signal.SIGKILL)
        os._exit(137)
