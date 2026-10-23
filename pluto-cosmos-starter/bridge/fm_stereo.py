"""Stereo FM multiplex processor and COSMOS audio spectrum telemetry.

Self-contained stateful DSP; receives same IQ stream as original mono decoder.
Uses the recovered 19 kHz pilot to regenerate the coherent 38 kHz L-R carrier;
falls back to dual mono when a pilot is not reliably detected.
"""
from __future__ import annotations
import math
import struct
import numpy as np
from scipy import signal
from fm import FM_SAMPLE_RATE, FM_IF_RATE, FM_AUDIO_RATE

FM_AUDIO_SPECTRUM_ID = 8
FM_DSP_STATUS_ID = 10
AUDIO_BINS = 256
AUDIO_SPECTRUM_FMT = '>IHI2f'  # bytes, packet ID, seq, bin spacing Hz, audio rate kHz
FM_DSP_STATUS_FMT = '>IHIBBBBf'  # bytes, ID, seq, requested stereo, pilot lock, RDS enabled/running, pilot relative dB


def make_audio_spectrum(seq:int, left:np.ndarray, right:np.ndarray):
    """Average dBFS relative to full-scale PCM, 256 bins from 0 to ~12 kHz."""
    spec=[]
    fft=1024
    for channel in (left,right):
        x=np.asarray(channel,dtype=np.float64)
        if len(x)<fft: x=np.pad(x,(fft-len(x),0))
        x=x[-fft:]
        w=np.hanning(fft)
        values=abs(np.fft.rfft(x*w)) / max(w.sum()/2,1)
        values=values[:AUDIO_BINS]
        spec.append((20*np.log10(np.maximum(values,1e-8))).astype('>f4'))
    size=struct.calcsize(AUDIO_SPECTRUM_FMT)+2*AUDIO_BINS*4
    return (struct.pack(AUDIO_SPECTRUM_FMT,size,FM_AUDIO_SPECTRUM_ID,seq,
                        FM_AUDIO_RATE/fft, FM_AUDIO_RATE/1000)
            +spec[0].tobytes()+spec[1].tobytes())


def make_dsp_status(seq:int, requested:int, locked:int, rds_enabled:int, rds_running:int, pilot_db:float):
    return struct.pack(FM_DSP_STATUS_FMT,struct.calcsize(FM_DSP_STATUS_FMT),FM_DSP_STATUS_ID,
                       seq,int(bool(requested)),int(bool(locked)),int(bool(rds_enabled)),
                       int(bool(rds_running)),float(pilot_db))


class FMStereoDemodulator:
    def __init__(self):
        self.if_lp=signal.butter(6,105000,fs=FM_SAMPLE_RATE,output='sos')
        self.sum_lp=signal.butter(6,15000,fs=FM_IF_RATE,output='sos')
        self.diff_bp=signal.butter(4,(23000,53000),btype='bandpass',fs=FM_IF_RATE,output='sos')
        self.diff_lp=signal.butter(6,15000,fs=FM_IF_RATE,output='sos')
        self.pilot_lp=signal.butter(3,650,fs=FM_IF_RATE,output='sos')
        alpha=1-math.exp(-1/(75e-6*FM_AUDIO_RATE))
        self.deemph_b=[alpha]
        self.deemph_a=[1, -(1-alpha)]
        self.reset()

    def reset(self):
        self.if_zi=np.zeros((len(self.if_lp),2),dtype=np.complex128)
        self.sum_zi=np.zeros((len(self.sum_lp),2))
        self.diff_bp_zi=np.zeros((len(self.diff_bp),2))
        self.diff_lp_zi=np.zeros((len(self.diff_lp),2))
        self.pilot_zi=np.zeros((len(self.pilot_lp),2),dtype=np.complex128)
        self.deemph_l=np.zeros(1)
        self.deemph_r=np.zeros(1)
        self.prev_iq=1+0j
        self.if_offset=0
        self.audio_offset=0
        self.sample_index=0
        self.last_mpx=np.zeros(0,dtype=np.float32)
        self.last_audio=np.zeros((0,2),dtype=np.float32)
        self.pilot_db=-160.0
        self.pilot_locked=False
        self._lock_counter=0

    def process(self, iq:np.ndarray, volume:float, stereo:bool=True):
        iq=np.asarray(iq,dtype=np.complex64)
        if not len(iq): return np.zeros((0,2),dtype=np.int16),-160.,-160.
        rf_rms=np.sqrt(np.mean(np.abs(iq)**2))
        rf_db=20*math.log10(max(float(rf_rms)/2048,1e-9))
        filtered,self.if_zi=signal.sosfilt(self.if_lp,iq,zi=self.if_zi)
        start=(-self.if_offset)%5
        samples=filtered[start::5]
        self.if_offset=(self.if_offset+len(iq))%5
        if not len(samples): return np.zeros((0,2),dtype=np.int16),-160.,rf_db
        prev=np.concatenate(([self.prev_iq],samples[:-1]))
        angle=np.angle(samples*np.conj(prev))
        self.prev_iq=samples[-1]
        mpx=np.asarray(angle*(FM_IF_RATE/(2*math.pi*75000)),dtype=np.float64)
        self.last_mpx=mpx.astype(np.float32)
        n=len(mpx)
        sample_ids=np.arange(n,dtype=np.float64)+self.sample_index
        self.sample_index+=n
        mono,self.sum_zi=signal.sosfilt(self.sum_lp,mpx,zi=self.sum_zi)
        # Coherent pilot reference: mixed-down 19 kHz tone then narrow 650 Hz LPF.
        pexp=np.exp(-1j*2*math.pi*19000/ FM_IF_RATE*sample_ids)
        pilot,self.pilot_zi=signal.sosfilt(self.pilot_lp,mpx*pexp,zi=self.pilot_zi)
        pilot_mag=np.abs(pilot)
        rms=math.sqrt(float(np.mean(mpx**2)))
        ratio=2*float(np.median(pilot_mag)) / max(rms,1e-7)
        self.pilot_db=20*math.log10(max(ratio,1e-8))
        # hysteresis reduces rapid stereo/mono flutter under fading.
        good=ratio>0.065
        self._lock_counter=max(-4,min(4,self._lock_counter+(1 if good else -1)))
        self.pilot_locked=self._lock_counter>=2
        if stereo and self.pilot_locked:
            subband,self.diff_bp_zi=signal.sosfilt(self.diff_bp,mpx,zi=self.diff_bp_zi)
            angle38=2*math.pi*38000/ FM_IF_RATE*sample_ids+2*np.angle(pilot)
            multiplied=2*subband*np.cos(angle38)
            difference,self.diff_lp_zi=signal.sosfilt(self.diff_lp,multiplied,zi=self.diff_lp_zi)
        else:
            # Keep differential filters warm so enabling stereo causes less of a transient.
            subband,self.diff_bp_zi=signal.sosfilt(self.diff_bp,mpx,zi=self.diff_bp_zi)
            _,self.diff_lp_zi=signal.sosfilt(self.diff_lp,subband*0,zi=self.diff_lp_zi)
            difference=np.zeros_like(mono)
        left=mono+difference
        right=mono-difference
        offset=(-self.audio_offset)%5
        left=left[offset::5]
        right=right[offset::5]
        self.audio_offset=(self.audio_offset+n)%5
        left,self.deemph_l=signal.lfilter(self.deemph_b,self.deemph_a,left,zi=self.deemph_l)
        right,self.deemph_r=signal.lfilter(self.deemph_b,self.deemph_a,right,zi=self.deemph_r)
        pcm_float=np.column_stack((left,right))
        self.last_audio=np.asarray(pcm_float,dtype=np.float32)
        level=float(np.sqrt(np.mean(pcm_float**2)))
        audio_db=20*math.log10(max(level,1e-9))
        pcm=np.asarray(np.clip(pcm_float*(.85*volume),-1,1)*32767,dtype=np.int16)
        return pcm,audio_db,rf_db
