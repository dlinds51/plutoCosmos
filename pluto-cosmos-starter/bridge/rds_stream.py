"""Optional redsea subprocess: demodulated 240 kSPS MPX -> decoded RDS JSON.

Threads isolate the RDS decoder from real-time PulseAudio playback. If its input
queue fills, packets are dropped rather than stalling FM audio acquisition.
"""
from __future__ import annotations
import json
import logging
import os
import queue
import shutil
import struct
import subprocess
import threading
import numpy as np

LOG=logging.getLogger('pluto_cosmos.rds')
FM_RDS_ID=9
# length, packet ID, seq, PI, PS, program type, RadioText, group count, decoder state
RDS_FMT='>IHI8s16s32s96sI32s'
RDS_SIZE=struct.calcsize(RDS_FMT)


def _fixed(text:str, n:int)->bytes:
    return str(text).encode('ascii','replace')[:n].ljust(n,b'\0')


def make_rds_status(seq:int, snapshot:dict)->bytes:
    return struct.pack(RDS_FMT,RDS_SIZE,FM_RDS_ID,seq,
                       _fixed(snapshot.get('pi','--'),8),
                       _fixed(snapshot.get('ps','--'),16),
                       _fixed(snapshot.get('prog_type','--'),32),
                       _fixed(snapshot.get('radiotext','--'),96),
                       max(0,min(int(snapshot.get('groups',0)),0xffffffff)),
                       _fixed(snapshot.get('state','WAITING'),32))


class RDSService:
    def __init__(self,program:str='redsea', simulate:bool=False,
                 log_path:str='/tmp/pluto-cosmos-redsea.log'):
        self.program=program
        self.simulate=simulate
        self.log_path=log_path
        self.proc=None
        self.log=None
        self.thread=None
        self.reader=None
        self.stopping=threading.Event()
        self.queue=queue.Queue(maxsize=6)
        self.lock=threading.Lock()
        self._data={}
        self.state='NOT STARTED'
        self.groups=0

    @property
    def running(self):
        return self.simulate or (self.proc is not None and self.proc.poll() is None)

    def start(self):
        self.stop()
        self.stopping.clear()
        self.queue=queue.Queue(maxsize=6)
        with self.lock:
            self._data={}
            self.groups=0
        if self.simulate:
            self.state='SIMULATED RDS'
            self._data={'pi':'0xDEAD','ps':'DEMO FM',
                        'prog_type':'Rock music','radiotext':'SIMULATED - NO LIVE RDS DATA'}
            return True
        executable=shutil.which(self.program)
        if not executable:
            self.state='REDSEA NOT INSTALLED'
            LOG.warning('RDS disabled: redsea not found: %s',self.program)
            return False
        self.log=open(self.log_path,'ab',buffering=0)
        try:
            self.proc=subprocess.Popen([executable,'--input','mpx','-r','240000'],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,bufsize=0)
            self.state='SEARCHING FOR RDS'
            self.thread=threading.Thread(target=self._write_loop,daemon=True)
            self.reader=threading.Thread(target=self._read_loop,daemon=True)
            self.thread.start()
            self.reader.start()
            LOG.info('redsea started: %s --input mpx -r 240000',executable)
            return True
        except Exception:
            self.stop()
            raise

    def _write_loop(self):
        while not self.stopping.is_set():
            try:
                payload=self.queue.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                if self.proc is None or self.proc.poll() is not None: break
                self.proc.stdin.write(payload)
            except (BrokenPipeError,OSError,ValueError):
                break

    def _read_loop(self):
        try:
            for raw in self.proc.stdout:
                try:
                    event=json.loads(raw.decode('utf-8','replace'))
                    if not isinstance(event,dict): continue
                except (ValueError,TypeError):
                    continue
                with self.lock:
                    pi=event.get('pi')
                    if pi and pi!=self._data.get('pi'):
                        self._data={'pi':str(pi)}
                    for key in ('ps','prog_type','radiotext'):
                        v=event.get(key)
                        if isinstance(v,str) and v.strip():
                            self._data[key]=v.strip()
                    self.groups+=1
        except (OSError,ValueError):
            pass

    def feed(self,mpx:np.ndarray):
        if not self.running or self.simulate: return
        x=np.asarray(mpx,dtype=np.float32)
        # Demodulated FM: ~1 is a 75 kHz peak frequency deviation.
        payload=np.asarray(np.clip(x*.6,-1,1)*32767,dtype='<i2').tobytes()
        try:
            self.queue.put_nowait(payload)
        except queue.Full:
            # Keep WSLg audio smooth: drop slow RDS input frames, not PCM.
            try: self.queue.get_nowait()
            except queue.Empty: pass
            try: self.queue.put_nowait(payload)
            except queue.Full: pass

    def snapshot(self):
        with self.lock:
            d=dict(self._data)
            d['groups']=self.groups
        d['state']=self.state if self.running or self.simulate else (
            'REDSEA EXITED' if self.proc is not None else self.state)
        return d

    def stop(self):
        self.stopping.set()
        proc,self.proc=self.proc,None
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1)
            try:
                if proc.stdin: proc.stdin.close()
                if proc.stdout: proc.stdout.close()
            except OSError: pass
        for t in (self.thread,self.reader):
            if t is not None and t.is_alive():
                t.join(timeout=.7)
        if self.log is not None:
            self.log.close()
            self.log=None
        self.thread=None
        self.reader=None
        if not self.simulate:
            self.state='STOPPED'
