"""Receive-only mono broadcast FM demodulation and WSLg/PulseAudio playback.

Only sends status telemetry to OpenC3; PCM stays local to WSLg -> Windows.
"""
from __future__ import annotations

import logging
import math
import os
import shutil
import struct
import subprocess
from dataclasses import dataclass

import numpy as np
from scipy import signal

LOG = logging.getLogger('pluto_cosmos.fm')
FM_STATUS_ID = 7
FM_CMD_FMT = '>IHQffB'   # LENGTH, TYPE, frequency Hz, volume 0..1, gain, AGC
FM_CMD_SIZE = struct.calcsize(FM_CMD_FMT)  # 23 bytes
FM_STATUS_FMT = '>IHI4fI32s64s'  # length, type, seq, MHz, volume, audio rms, RF rms, frames, state, detail
FM_STATUS_SIZE = struct.calcsize(FM_STATUS_FMT)
FM_SAMPLE_RATE = 1_200_000
FM_IF_RATE = 240_000
FM_AUDIO_RATE = 48_000
FM_BUFFER_SAMPLES = 4096 * 32


@dataclass(frozen=True)
class FMSettings:
    frequency_hz: int = 99_500_000
    volume: float = 0.35
    gain_db: float = 35.0
    agc: int = 0

    def validate(self):
        if not 88_000_000 <= self.frequency_hz <= 108_000_000:
            raise ValueError('FM broadcast tuning must be 88..108 MHz')
        if not math.isfinite(self.volume) or not 0 <= self.volume <= 1:
            raise ValueError('Volume must be between 0 and 1')
        if not math.isfinite(self.gain_db) or not 0 <= self.gain_db <= 70:
            raise ValueError('Gain must be 0..70 dB')
        if self.agc not in (0, 1):
            raise ValueError('AGC must be 0 or 1')


def make_fm_status(seq: int, settings: FMSettings, rms_dbfs: float, rf_dbfs: float,
                   frames: int, state: str, detail: str = '') -> bytes:
    def encode(s, n):
        return str(s).encode('ascii', 'replace')[:n].ljust(n, b'\0')
    return struct.pack(FM_STATUS_FMT, FM_STATUS_SIZE, FM_STATUS_ID, seq,
                       settings.frequency_hz / 1e6, float(settings.volume),
                       float(rms_dbfs), float(rf_dbfs), frames,
                       encode(state, 32), encode(detail, 64))


class FMDemodulator:
    """Stateful narrow-channel FM discriminator, mono audio, US 75 us de-emphasis."""
    def __init__(self):
        # All sampling rates are integer ratios: 1.2M -> 240k -> 48k.
        self.if_lp = signal.butter(6, 105_000, btype='lowpass', fs=FM_SAMPLE_RATE, output='sos')
        self.audio_lp = signal.butter(6, 15_000, btype='lowpass', fs=FM_IF_RATE, output='sos')
        alpha = 1 - math.exp(-1 / (75e-6 * FM_AUDIO_RATE))
        self.deemph_b = [alpha]
        self.deemph_a = [1, -(1 - alpha)]
        self.reset()

    def reset(self):
        self.if_zi = np.zeros((len(self.if_lp), 2), dtype=np.complex128)
        self.audio_zi = np.zeros((len(self.audio_lp), 2), dtype=np.float64)
        self.deemph_zi = np.zeros(1, dtype=np.float64)
        self.prev_iq = 1 + 0j
        self.if_offset = 0
        self.audio_offset = 0

    def process(self, iq: np.ndarray, volume: float) -> tuple[np.ndarray, float, float]:
        iq = np.asarray(iq, dtype=np.complex64)
        if not len(iq):
            return np.array([], dtype=np.int16), -160.0, -160.0
        rf_rms = float(np.sqrt(np.mean(np.abs(iq) ** 2)))
        rf_dbfs = 20 * math.log10(max(rf_rms / 2048, 1e-9))

        # Stateful FIR-equivalent IIR filtering and phase-aligned decimation.
        iq_filt, self.if_zi = signal.sosfilt(self.if_lp, iq, zi=self.if_zi)
        start = (-self.if_offset) % 5
        if_data = iq_filt[start::5]
        self.if_offset = (self.if_offset + len(iq)) % 5
        if not len(if_data):
            return np.array([], dtype=np.int16), -160.0, rf_dbfs
        prev = np.concatenate(([self.prev_iq], if_data[:-1]))
        deviation = np.angle(if_data * np.conj(prev))
        self.prev_iq = if_data[-1]
        # 75kHz frequency deviation gives amplitude ~1 in normalized demod samples.
        demod = deviation * (FM_IF_RATE / (2 * math.pi * 75_000))
        baseband, self.audio_zi = signal.sosfilt(self.audio_lp, demod, zi=self.audio_zi)
        start = (-self.audio_offset) % 5
        audio = baseband[start::5]
        self.audio_offset = (self.audio_offset + len(baseband)) % 5
        if not len(audio):
            return np.array([], dtype=np.int16), -160.0, rf_dbfs
        audio, self.deemph_zi = signal.lfilter(self.deemph_b, self.deemph_a, audio, zi=self.deemph_zi)
        audio = np.asarray(audio, dtype=np.float64)
        level = float(np.sqrt(np.mean(audio ** 2)))
        rms_dbfs = 20 * math.log10(max(level, 1e-9))
        pcm = np.asarray(np.clip(audio * (0.85 * volume), -1, 1) * 32767, dtype=np.int16)
        return pcm, rms_dbfs, rf_dbfs


class WSLgAudio:
    """Audio sink via PulseAudio 'pacat' (WSLg forwards it to Windows speakers)."""
    def __init__(self, simulate: bool = False, log_path: str = '/tmp/pluto-cosmos-fm-audio.log', channels: int = 1):
        self.simulate = simulate
        if channels not in (1, 2):
            raise ValueError("Audio output channels must be 1 or 2")
        self.channels = channels
        self.log_path = log_path
        self.proc = None
        self.log = None
        self.samples_written = 0

    def start(self):
        if self.simulate:
            return
        executable = shutil.which('pacat')
        if not executable:
            raise RuntimeError('pacat missing: sudo apt install pulseaudio-utils')
        if not os.environ.get('PULSE_SERVER') and not os.path.exists('/mnt/wslg/PulseServer'):
            raise RuntimeError('No WSLg PulseAudio: check PULSE_SERVER / WSLg installation')
        env = os.environ.copy()
        if not env.get('PULSE_SERVER') and os.path.exists('/mnt/wslg/PulseServer'):
            env['PULSE_SERVER'] = 'unix:/mnt/wslg/PulseServer'
        command = [executable, '--playback', '--raw', '--format=s16le',
                   '--rate=48000', f'--channels={self.channels}', '--latency-msec=200']
        self.log = open(self.log_path, 'ab', buffering=0)
        try:
            self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                         stderr=self.log, env=env, bufsize=0)
        except Exception:
            self.stop()
            raise
        LOG.info('FM PCM audio output started: %s (PID %d)', ' '.join(command), self.proc.pid)

    def write(self, pcm: np.ndarray):
        pcm = np.asarray(pcm, dtype='<i2')
        if self.channels == 2 and (pcm.ndim != 2 or pcm.shape[1] != 2):
            raise ValueError('Expected stereo PCM array of shape (frames, 2)')
        if self.simulate:
            self.samples_written += len(pcm)
            return
        if self.proc is None or self.proc.poll() is not None:
            raise RuntimeError(f'PulseAudio player failed; see {self.log_path}')
        try:
            remaining = memoryview(pcm.tobytes())
            while remaining:
                written = self.proc.stdin.write(remaining)
                if written is None or written <= 0:
                    raise BrokenPipeError('audio stream wrote zero bytes')
                remaining = remaining[written:]
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError(f'Audio player pipe error: {exc}; see {self.log_path}') from exc
        self.samples_written += len(pcm)

    def stop(self):
        proc, self.proc = self.proc, None
        if proc:
            if proc.stdin:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        if self.log:
            self.log.close()
            self.log = None


class DemoFMSource:
    """Generate constant-envelope FM-modulated 1 kHz audio for protocol/DSP tests."""
    def __init__(self):
        self.sample_position = 0
        self.phase = 0.0

    def receive(self, n: int = FM_BUFFER_SAMPLES) -> np.ndarray:
        t = (np.arange(n) + self.sample_position) / FM_SAMPLE_RATE
        audio = np.sin(2 * np.pi * 1000 * t)
        instantaneous_frequency = 50_000 * audio
        phase = self.phase + np.cumsum(2 * np.pi * instantaneous_frequency / FM_SAMPLE_RATE)
        self.phase = float(phase[-1] % (2 * np.pi))
        self.sample_position += n
        return np.asarray(850 * np.exp(1j * phase), dtype=np.complex64)
