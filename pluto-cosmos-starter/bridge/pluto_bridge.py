#!/usr/bin/env python3
"""PLUTO_SDR ↔ OpenC3 COSMOS spectrum and ADS-B bridge (receive-only)."""
from __future__ import annotations

import argparse
import base64
import logging
import math
import gc
import zlib
import select
import socket
import struct
import time
from dataclasses import dataclass

import numpy as np

from adsb import (ADSBRuntime, AircraftMap, make_adsb_table, make_adsb_event, make_adsb_map,
                  normalize_aircraft, ADSB_TABLE_ID, ADSB_EVENT_ID, ADSB_MAP_ID)

LOG = logging.getLogger("pluto_cosmos")
PORT = 7350
BINS = 512
PKT_SPECTRUM = 1
PKT_STATUS = 2
PKT_WATERFALL = 3
PKT_ADSB_MAP = 6
CMD_CONFIG = 100
CMD_START = 101
CMD_STOP = 102
CMD_CLEAR_HOLD = 103
CMD_CONFIG_V2 = 104
CMD_WF_RANGE = 105
CMD_CLEAR_WF = 106
CMD_ADSB_START = 107
CMD_ADSB_STOP = 108
CONFIG_FMT = ">IHQIIIffBB"
CONFIG_SIZE = struct.calcsize(CONFIG_FMT)  # 36 bytes
CONFIG_V2_FMT = ">IHQIIIffBBI"  # Existing CONFIG + receive RF bandwidth
CONFIG_V2_SIZE = struct.calcsize(CONFIG_V2_FMT)  # 40 bytes
WF_RANGE_FMT = ">IHff"
WF_RANGE_SIZE = struct.calcsize(WF_RANGE_FMT)  # 14 bytes
WATERFALL_FMT = ">IHI6fI"  # length/id/seq, left/center/right/floor/ceiling/row seconds, valid rows
WF_BINS = 256
WF_ROWS = 96
SPECTRUM_FMT = ">IHI5fI4f"
SPECTRUM_SIZE = struct.calcsize(SPECTRUM_FMT) + 2 * BINS * 4
MAX_FRAME = 16384


@dataclass
class Config:
    center_hz: int = 915_000_000
    span_hz: int = 1_600_000
    sample_rate: int = 2_000_000
    fft_size: int = 2048
    gain_db: float = 40.0
    averages: int = 8
    agc: int = 0
    fps: int = 2
    rf_bandwidth_hz: int = 1_600_000  # independent of zoom/display span

    def validate(self, fmin: float, fmax: float) -> None:
        if not fmin * 1e6 <= self.center_hz <= fmax * 1e6:
            raise ValueError(f"Center frequency must be {fmin:g}–{fmax:g} MHz")
        if not 520_833 <= self.sample_rate <= 20_000_000:
            raise ValueError("Sample rate must be 520833–20000000 SPS")
        if not 50_000 <= self.span_hz <= self.sample_rate:
            raise ValueError("Span must be 50 kHz through sample rate")
        if not 200_000 <= self.rf_bandwidth_hz <= self.sample_rate:
            raise ValueError("RF filter bandwidth must be 200 kHz through sample rate")
        if self.fft_size not in (256, 512, 1024, 2048, 4096, 8192):
            raise ValueError("FFT must be 256/512/1024/2048/4096/8192")
        if not 0 <= self.gain_db <= 70 or not math.isfinite(self.gain_db):
            raise ValueError("Gain must be 0–70 dB")
        if self.averages not in (1, 2, 4, 8, 16, 32):
            raise ValueError("Averages must be 1/2/4/8/16/32")
        if self.agc not in (0, 1):
            raise ValueError("AGC must be 0 or 1")
        if self.fps not in (1, 2, 5):
            raise ValueError("Update rate must be 1, 2, or 5 Hz")


class InputSource:
    def __init__(self, uri: str, simulated: bool):
        self.simulated = simulated
        self.uri = uri
        self.dev = None
        self.applied: Config | None = None
        self.phase = 0
        self.rng = np.random.default_rng(12345)

    def _apply_hardware(self, cfg: Config) -> None:
        # Do not churn the RX DMA buffer / sample-rate filter just to retune.
        # Refreshing all attributes on every CONFIG was unnecessarily disruptive.
        import adi  # type: ignore
        new_device = self.dev is None
        if new_device:
            self.dev = adi.Pluto(uri=self.uri)
        d = self.dev
        old = self.applied if not new_device else None

        new_buffer_samples = cfg.fft_size * cfg.averages
        old_buffer_samples = old.fft_size * old.averages if old else None
        buffer_change = old is None or old_buffer_samples != new_buffer_samples
        rate_change = old is None or old.sample_rate != cfg.sample_rate
        # Changing the capture rate or buffer size needs DMA-buffer recreation.
        if buffer_change or rate_change:
            LOG.info("SDR: restarting RX buffer (samples=%d, rate=%d)",
                     new_buffer_samples, cfg.sample_rate)
            d.rx_destroy_buffer()

        if rate_change:
            LOG.info("SDR: sample_rate=%d", cfg.sample_rate)
            d.sample_rate = int(cfg.sample_rate)
        # Analog RF bandwidth is independent of displayed/zoomed span.
        target_bw = cfg.rf_bandwidth_hz
        old_bw = old.rf_bandwidth_hz if old else None
        if old is None or old_bw != target_bw:
            LOG.info("SDR: rx_rf_bandwidth=%d", target_bw)
            d.rx_rf_bandwidth = int(target_bw)
        if old is None or old.center_hz != cfg.center_hz:
            LOG.info("SDR: rx_lo=%d", cfg.center_hz)
            d.rx_lo = int(cfg.center_hz)
        if old is None:
            d.rx_enabled_channels = [0]
        if old is None or old.agc != cfg.agc:
            LOG.info("SDR: AGC=%d", cfg.agc)
            d.gain_control_mode_chan0 = "slow_attack" if cfg.agc else "manual"
        if not cfg.agc and (old is None or old.agc or old.gain_db != cfg.gain_db):
            LOG.info("SDR: gain=%g dB", cfg.gain_db)
            d.rx_hardwaregain_chan0 = float(cfg.gain_db)
        if buffer_change or rate_change:
            d.rx_buffer_size = int(new_buffer_samples)

        # Mark active only if *all* device changes have succeeded.
        self.applied = cfg
        # A single subsequent discard clears samples acquired before retuning.
        self.discard_next = (old is None or old.center_hz != cfg.center_hz or
                             buffer_change or rate_change)

    def release(self) -> None:
        """Release SDR handles before readsb claims the one Pluto receiver."""
        device = self.dev
        self.dev = None
        self.applied = None
        self.discard_next = False
        if device is not None:
            try:
                device.rx_destroy_buffer()
            except (OSError, ConnectionError) as exc:
                LOG.warning('SDR buffer release warning: %s', exc)
            del device
            gc.collect()

    def configure(self, cfg: Config) -> None:
        if self.simulated:
            self.applied = cfg
            return
        try:
            self._apply_hardware(cfg)
        except (OSError, ConnectionError) as exc:
            # libiio's persistent socket can become invalid following a reset
            # (e.g. -104 / ECONNRESET). Reconstruct the IIO context once.
            LOG.warning("SDR libiio failure: %s; reopening Pluto context once", exc)
            self.dev = None
            self.applied = None
            self._apply_hardware(cfg)

    def receive(self, cfg: Config) -> np.ndarray:
        if not self.simulated:
            try:
                if getattr(self, "discard_next", False):
                    self.dev.rx()  # discard samples from the previous tuning
                    self.discard_next = False
                return np.asarray(self.dev.rx(), dtype=np.complex64)
            except (OSError, ConnectionError) as exc:
                LOG.warning("SDR receive error: %s; reconnecting once", exc)
                self.dev = None
                self.applied = None
                self._apply_hardware(cfg)
                self.dev.rx()  # discard first capture after reconnect
                self.discard_next = False
                return np.asarray(self.dev.rx(), dtype=np.complex64)
        n = cfg.fft_size * cfg.averages
        # Two local test signals at +125 kHz and -300 kHz relative to center.
        idx = np.arange(n, dtype=np.float64)
        x = (650 * np.exp(1j * 2 * np.pi * 125_000 * (idx + self.phase) / cfg.sample_rate)
             + 250 * np.exp(-1j * 2 * np.pi * 300_000 * (idx + self.phase) / cfg.sample_rate))
        noise = self.rng.normal(0, 25, n) + 1j * self.rng.normal(0, 25, n)
        self.phase += n
        return np.asarray(x + noise, dtype=np.complex64)


def calculate_spectrum(iq: np.ndarray, cfg: Config) -> tuple[np.ndarray, float, float, float]:
    """Returns 512 cropped power bins, peak Hz, peak dBFS, and RBW Hz.

    Relative power uses approximate 12-bit Pluto full scale; values are dBFS,
    NOT calibrated dBm. DC spur is intentionally not corrected here.
    """
    n = cfg.fft_size
    count = len(iq) // n
    if count < 1:
        raise ValueError("No full FFT windows acquired")
    frames = np.asarray(iq[:count * n], dtype=np.complex128).reshape(count, n)
    w = np.hanning(n)
    scale = (2048.0 * float(np.sum(w))) ** 2
    shifted = np.fft.fftshift(np.fft.fft(frames * w, axis=1), axes=1)
    # Average powers in linear units, never average logged dB values.
    power = np.mean(np.abs(shifted) ** 2, axis=0) / scale
    frequencies = np.fft.fftshift(np.fft.fftfreq(n, d=1.0 / cfg.sample_rate))
    display_axis = np.linspace(-cfg.span_hz / 2, cfg.span_hz / 2, BINS)
    # Interpolate linear power; display only the central configured span.
    displayed = np.interp(display_axis, frequencies, power)
    level = (10 * np.log10(np.maximum(displayed, 1e-15))).astype(np.float32)
    pk = int(np.argmax(displayed))
    return level, cfg.center_hz + float(display_axis[pk]), float(level[pk]), cfg.sample_rate / n


def make_spectrum_frame(cfg: Config, seq: int, levels: np.ndarray, hold: np.ndarray,
                        peak_hz: float, peak_dbfs: float, rbw_hz: float) -> bytes:
    header = struct.pack(
        SPECTRUM_FMT,
        SPECTRUM_SIZE, PKT_SPECTRUM, seq,
        cfg.center_hz / 1e6,
        (cfg.center_hz - cfg.span_hz / 2) / 1e6,
        (cfg.center_hz + cfg.span_hz / 2) / 1e6,
        cfg.sample_rate / 1e6, cfg.span_hz / 1e6,
        cfg.fft_size,
        cfg.gain_db,
        peak_hz / 1e6,
        peak_dbfs,
        rbw_hz / 1000.0,
    )
    return (header + np.asarray(levels, dtype=">f4").tobytes()
            + np.asarray(hold, dtype=">f4").tobytes())


def make_status_frame(seq: int, message: str) -> bytes:
    payload = message.encode("ascii", "replace")[:63].ljust(64, b"\x00")
    return struct.pack(">IHI64s", 74, PKT_STATUS, seq, payload)


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    payload = tag + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xffffffff)


def _waterfall_palette() -> bytes:
    # perceptually ordered-ish palette: dark navy -> blue -> cyan -> amber -> white
    stops = ((0, (4, 8, 24)), (48, (10, 26, 86)),
             (110, (20, 93, 178)), (170, (30, 204, 196)),
             (218, (245, 178, 52)), (255, (255, 250, 210)))
    result = bytearray()
    for i in range(256):
        for j in range(1, len(stops)):
            if i <= stops[j][0]:
                x0, rgb0 = stops[j-1]
                x1, rgb1 = stops[j]
                t = (i - x0) / (x1 - x0)
                result.extend(int(a + (b - a) * t + 0.5) for a, b in zip(rgb0, rgb1))
                break
    return bytes(result)


WF_PALETTE = _waterfall_palette()


class WaterfallHistory:
    """Small rolling relative-power spectrogram encoded for native IMAGEVIEWER."""
    def __init__(self, rows: int = WF_ROWS):
        self.rows = rows
        self.power = np.full((rows, WF_BINS), -160.0, dtype=np.float32)
        self.valid = 0
        self.floor_dbfs = -115.0
        self.ceiling_dbfs = -35.0

    def reset(self):
        self.power.fill(-160.0)
        self.valid = 0

    def set_range(self, floor: float, ceiling: float):
        if not (math.isfinite(floor) and math.isfinite(ceiling)
                and -160 <= floor < ceiling <= 20 and ceiling - floor >= 10):
            raise ValueError('Waterfall floor/ceiling invalid (-160..20 dBFS, >=10 dB apart)')
        self.floor_dbfs = float(floor)
        self.ceiling_dbfs = float(ceiling)

    def add(self, levels: np.ndarray):
        if len(levels) != BINS:
            raise ValueError(f'Expected {BINS} FFT bins')
        # Max pool adjacent FFT display bins; this preserves narrow bursts.
        row = np.asarray(levels, dtype=np.float32).reshape(WF_BINS, 2).max(axis=1)
        self.power[1:] = self.power[:-1].copy()
        self.power[0] = row
        self.valid = min(self.valid + 1, self.rows)

    def png(self) -> bytes:
        # Indexed-color PNG, standard library only. Scale 256x96 -> 768x192.
        scaled = np.clip(np.rint((self.power - self.floor_dbfs) *
                     (255.0 / (self.ceiling_dbfs - self.floor_dbfs))), 0, 255).astype(np.uint8)
        scaled = np.repeat(np.repeat(scaled, 3, axis=1), 2, axis=0)
        height, width = scaled.shape
        # Filter 0 for each PNG scanline; zlib handles repeat runs efficiently.
        raw = b''.join(b'\x00' + scaled[i].tobytes() for i in range(height))
        png = bytearray(b'\x89PNG\r\n\x1a\n')
        png.extend(_png_chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 3, 0, 0, 0)))
        png.extend(_png_chunk(b'PLTE', WF_PALETTE))
        png.extend(_png_chunk(b'IDAT', zlib.compress(raw, level=5)))
        png.extend(_png_chunk(b'IEND', b''))
        return bytes(png)


def make_waterfall_frame(cfg: Config, seq: int, waterfall: WaterfallHistory) -> bytes:
    image = base64.b64encode(waterfall.png())
    # COSMOS APPEND_ITEM PNG_BASE64 0 STRING reads the variable-length suffix.
    total = struct.calcsize(WATERFALL_FMT) + len(image)
    head = struct.pack(WATERFALL_FMT, total, PKT_WATERFALL, seq,
                       (cfg.center_hz - cfg.span_hz / 2) / 1e6,
                       cfg.center_hz / 1e6,
                       (cfg.center_hz + cfg.span_hz / 2) / 1e6,
                       waterfall.floor_dbfs, waterfall.ceiling_dbfs,
                       1.0 / cfg.fps, waterfall.valid)
    return head + image


def decode_frames(buffer: bytearray) -> list[tuple[int, bytes]]:
    result = []
    while len(buffer) >= 4:
        length = struct.unpack_from(">I", buffer)[0]
        if not 6 <= length <= MAX_FRAME:
            raise ValueError(f"Invalid frame size {length}")
        if len(buffer) < length:
            break
        frame = bytes(buffer[:length])
        del buffer[:length]
        result.append((struct.unpack_from(">H", frame, 4)[0], frame))
    return result


def serve(args: argparse.Namespace) -> None:
    cfg = Config()
    cfg.validate(args.min_rf_mhz, args.max_rf_mhz)
    source = InputSource(args.uri, args.simulate)
    try:
        source.configure(cfg)
    except Exception:
        LOG.exception("Pluto initialization failed. Check libiio routing / connectivity")
        raise
    adsb = ADSBRuntime(uri=args.uri, simulated=args.simulate,
                       readsb_path=args.readsb_path, log_path=args.readsb_log)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((args.listen, args.port))
        listener.listen(1)
        LOG.info("Serving %s:%d; simulate=%s", args.listen, args.port, args.simulate)
        while True:
            conn, addr = listener.accept()
            LOG.info("COSMOS connected from %s", addr)
            with conn:
                # Use a finite timeout on blocking writes. sendall() on a
                # nonblocking socket can fail spuriously with EAGAIN.
                conn.settimeout(5.0)
                input_buffer = bytearray()
                seq = 0
                running = True
                hold = np.full(BINS, -160, dtype=np.float32)
                waterfall = WaterfallHistory()
                last_wf_emit = 0.0
                next_send = time.monotonic()
                last_status = 0.0
                status = "SIMULATION" if args.simulate else "PLUTO CONNECTED"
                mode = 'spectrum'
                adsb_seq = 0
                next_adsb = 0.0
                aircraft_seen_messages = {}
                adsb_map = AircraftMap()
                try:
                    conn.sendall(make_status_frame(seq, status))
                    while True:
                        now = time.monotonic()
                        readable, _, _ = select.select([conn], [], [], (max(0, min(0.1, next_send - now)) if running else 0.1))
                        if readable:
                            chunk = conn.recv(65536)
                            if chunk == b"":
                                break
                            if chunk:
                                input_buffer.extend(chunk)
                                for typ, frame in decode_frames(input_buffer):
                                    try:
                                        if typ in (CMD_CONFIG, CMD_CONFIG_V2):
                                            if typ == CMD_CONFIG_V2:
                                                if len(frame) != CONFIG_V2_SIZE:
                                                    raise ValueError('CONFIG_V2 frame length mismatch')
                                                (length, _, hz, span, sps, fft, gain, avg, agc,
                                                 fps, rx_bw) = struct.unpack(CONFIG_V2_FMT, frame)
                                            else:
                                                if len(frame) != CONFIG_SIZE:
                                                    raise ValueError('CONFIG frame length mismatch')
                                                (length, _, hz, span, sps, fft, gain, avg,
                                                 agc, fps) = struct.unpack(CONFIG_FMT, frame)
                                                rx_bw = min(cfg.rf_bandwidth_hz, sps)
                                            new = Config(hz, span, sps, fft, gain, int(avg), agc, fps, rx_bw)
                                            new.validate(args.min_rf_mhz, args.max_rf_mhz)
                                            LOG.info('CONFIG received: center=%.6f MHz, span=%.3f MHz, '
                                                     'sps=%d, rx_bw=%d, fft=%d, gain=%.1f, avg=%d, agc=%d, fps=%d',
                                                     new.center_hz / 1e6, new.span_hz / 1e6,
                                                     new.sample_rate, new.rf_bandwidth_hz, new.fft_size,
                                                     new.gain_db, new.averages, new.agc, new.fps)
                                            if mode == 'spectrum':
                                                source.configure(new)
                                            if (new.center_hz != cfg.center_hz or new.span_hz != cfg.span_hz
                                                    or new.sample_rate != cfg.sample_rate or
                                                    new.fft_size != cfg.fft_size or
                                                    new.rf_bandwidth_hz != cfg.rf_bandwidth_hz):
                                                waterfall.reset()
                                            cfg = new
                                            hold.fill(-160)
                                            last_wf_emit = 0.0
                                            next_send = time.monotonic()
                                            status = ('CONFIG APPLIED' if mode == 'spectrum'
                                                      else 'SPECTRUM CONFIG SAVED - ADSB ACTIVE')
                                        elif typ == CMD_WF_RANGE:
                                            if len(frame) != WF_RANGE_SIZE:
                                                raise ValueError('WF_RANGE frame length mismatch')
                                            _, _, floor, ceiling = struct.unpack(WF_RANGE_FMT, frame)
                                            waterfall.set_range(floor, ceiling)
                                            last_wf_emit = 0.0
                                            status = 'WATERFALL RANGE APPLIED'
                                        elif typ == CMD_CLEAR_WF:
                                            if len(frame) != 6:
                                                raise ValueError('CLEAR_WF frame length mismatch')
                                            waterfall.reset()
                                            last_wf_emit = 0.0
                                            status = 'WATERFALL CLEARED'
                                        elif typ == CMD_ADSB_START:
                                            if len(frame) != 6:
                                                raise ValueError('ADSB_START frame length mismatch')
                                            if mode != 'adsb':
                                                was_running = running
                                                running = False
                                                source.release()
                                                try:
                                                    adsb.start()
                                                except Exception:
                                                    source.configure(cfg)
                                                    running = was_running
                                                    raise
                                                mode = 'adsb'
                                                aircraft_seen_messages.clear()
                                                adsb_map.reset()
                                                adsb_seq = 0
                                                next_adsb = 0.0
                                            status = 'ADSB SIMULATED' if args.simulate else 'ADSB STARTING 1090 MHZ'
                                        elif typ == CMD_ADSB_STOP:
                                            if len(frame) != 6:
                                                raise ValueError('ADSB_STOP frame length mismatch')
                                            if mode == 'adsb':
                                                adsb.stop()
                                                mode = 'spectrum'
                                                source.configure(cfg)
                                                running = True
                                                next_send = time.monotonic()
                                                waterfall.reset()
                                                hold.fill(-160)
                                            status = 'SPECTRUM RESTORED'
                                        elif typ == CMD_START:
                                            if mode == 'adsb':
                                                adsb.stop()
                                                mode = 'spectrum'
                                                source.configure(cfg)
                                                waterfall.reset()
                                                hold.fill(-160)
                                            running = True
                                            next_send = time.monotonic()
                                            status = "RUNNING"
                                        elif typ == CMD_STOP:
                                            if mode == 'spectrum':
                                                running = False
                                                status = "STOPPED"
                                            else:
                                                status = 'ADSB ACTIVE - USE RETURN TO SPECTRUM'
                                        elif typ == CMD_CLEAR_HOLD:
                                            hold.fill(-160)
                                            status = "PEAK HOLD CLEARED"
                                        else:
                                            raise ValueError(f"Unknown command ID {typ}")
                                        LOG.info("%s", status)
                                    except Exception as exc:
                                        LOG.exception("Command processing failed (type=%s)", typ)
                                        status = f"ERROR: {exc}"
                                    # Keep socket errors separate from command errors.
                                    # On a dead COSMOS socket, only the outer loop
                                    # handles disconnection; do not send again here.
                                    conn.sendall(make_status_frame(seq, status))
                        now = time.monotonic()
                        if mode == 'adsb' and now >= next_adsb:
                            adsb_seq = (adsb_seq + 1) % (2 ** 32)
                            try:
                                snapshot = adsb.snapshot()
                                if snapshot is None:
                                    count = 0
                                    rows = []
                                    raw_total = 0
                                    state = 'WAITING FOR ADS-B DATA'
                                else:
                                    raw_total = snapshot.get('messages', 0)
                                    rows = normalize_aircraft(snapshot)
                                    count = len(rows)
                                    state = ('SIMULATED AIRCRAFT - NOT LIVE' if args.simulate
                                             else 'LIVE 1090 MHZ')
                                    # Send structured aircraft updates. Includes updated
                                    # aircraft, not just aircraft with positions.
                                    for row in rows[:30]:
                                        identity = row['hex']
                                        messages = row['messages_int']
                                        if messages > aircraft_seen_messages.get(identity, -1):
                                            conn.sendall(make_adsb_event(adsb_seq, row))
                                        aircraft_seen_messages[identity] = messages
                                    current = set(r['hex'] for r in rows)
                                    aircraft_seen_messages = {k:v for k,v in aircraft_seen_messages.items()
                                                              if k in current}
                                conn.sendall(make_adsb_table(adsb_seq, count, raw_total, state, rows))
                                conn.sendall(make_adsb_map(adsb_seq, adsb_map.update(rows)))
                            except Exception as exc:
                                LOG.exception('ADS-B decoder/poll failed')
                                adsb.stop()
                                mode = 'spectrum'
                                try:
                                    source.configure(cfg)
                                    running = True
                                except Exception as restore_exc:
                                    LOG.error('Spectrum restore failed: %s', restore_exc)
                                    running = False
                                status = f'ERROR ADSB: {str(exc)[:44]}'
                                conn.sendall(make_status_frame(seq, status))
                            next_adsb = time.monotonic() + 1.0
                        if mode == 'spectrum' and running and now >= next_send:
                            try:
                                iq = source.receive(cfg)
                                levels, peak_hz, peak_dbfs, rbw = calculate_spectrum(iq, cfg)
                            except Exception as exc:
                                LOG.exception("SDR spectrum acquisition failed; pausing stream")
                                running = False
                                status = f"ERROR: SDR receive: {exc}"
                                conn.sendall(make_status_frame(seq, status))
                                last_status = time.monotonic()
                                continue
                            hold = np.maximum(hold, levels)
                            waterfall.add(levels)
                            seq = (seq + 1) % (2 ** 32)
                            conn.sendall(make_spectrum_frame(cfg, seq, levels, hold,
                                                             peak_hz, peak_dbfs, rbw))
                            # Cap PNG telemetry to ~1 packet/sec even at 5 FFT/s.
                            if time.monotonic() - last_wf_emit >= 1.0:
                                conn.sendall(make_waterfall_frame(cfg, seq, waterfall))
                                last_wf_emit = time.monotonic()
                            next_send = time.monotonic() + 1 / cfg.fps
                        elif mode == 'spectrum' and not running and now - last_status > 2:
                            conn.sendall(make_status_frame(seq, status))
                            last_status = now
                except (ConnectionError, OSError) as exc:
                    LOG.warning("COSMOS disconnected: %s", exc)
                except Exception:
                    LOG.exception("Bridge fault; waiting for COSMOS reconnection")
                finally:
                    if mode == 'adsb':
                        adsb.stop()
                        try:
                            source.configure(cfg)
                        except Exception:
                            LOG.exception('Could not restore spectrum on COSMOS disconnect')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulate", action="store_true", help="Synthetic FFT and fictional ADS-B data; no hardware")
    parser.add_argument("--readsb-path", default="readsb", help="readsb executable, compiled with PLUTOSDR=yes")
    parser.add_argument("--readsb-log", default="/tmp/pluto-cosmos-readsb.log", help="readsb process log")
    parser.add_argument("--uri", default="ip:192.168.2.1", help="Pluto libiio URI")
    parser.add_argument("--listen", default="0.0.0.0", help="Local listener bind IP")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--min-rf-mhz", type=float, default=325,
                        help="Change ONLY if your Pluto has been validated below 325 MHz")
    parser.add_argument("--max-rf-mhz", type=float, default=3800,
                        help="Change ONLY if your Pluto has been validated above 3800 MHz")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    serve(args)


if __name__ == "__main__":
    main()
