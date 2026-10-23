#!/usr/bin/env python3
"""PLUTO_SDR ↔ OpenC3 COSMOS phase-1 TCP bridge (receive-only)."""
from __future__ import annotations

import argparse
import logging
import math
import select
import socket
import struct
import time
from dataclasses import dataclass

import numpy as np

LOG = logging.getLogger("pluto_cosmos")
PORT = 7350
BINS = 512
PKT_SPECTRUM = 1
PKT_STATUS = 2
CMD_CONFIG = 100
CMD_START = 101
CMD_STOP = 102
CMD_CLEAR_HOLD = 103
CONFIG_FMT = ">IHQIIIffBB"
CONFIG_SIZE = struct.calcsize(CONFIG_FMT)  # 36 bytes
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

    def validate(self, fmin: float, fmax: float) -> None:
        if not fmin * 1e6 <= self.center_hz <= fmax * 1e6:
            raise ValueError(f"Center frequency must be {fmin:g}–{fmax:g} MHz")
        if not 520_833 <= self.sample_rate <= 20_000_000:
            raise ValueError("Sample rate must be 520833–20000000 SPS")
        if not 50_000 <= self.span_hz <= self.sample_rate:
            raise ValueError("Span must be 50 kHz through sample rate")
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
        self.phase = 0
        self.rng = np.random.default_rng(12345)

    def configure(self, cfg: Config) -> None:
        if self.simulated:
            return
        # Import only in hardware mode so --simulate works without libiio/pyadi-iio.
        if self.dev is None:
            import adi  # type: ignore
            self.dev = adi.Pluto(uri=self.uri)
        d = self.dev
        d.rx_destroy_buffer()  # necessary when changing buffer sizes between acquisitions
        d.sample_rate = cfg.sample_rate
        d.rx_rf_bandwidth = min(cfg.sample_rate, max(200_000, cfg.span_hz))
        d.rx_lo = cfg.center_hz
        d.rx_enabled_channels = [0]
        d.gain_control_mode_chan0 = "slow_attack" if cfg.agc else "manual"
        if not cfg.agc:
            d.rx_hardwaregain_chan0 = cfg.gain_db
        d.rx_buffer_size = cfg.fft_size * cfg.averages
        # First buffer after retuning can contain stale samples.
        d.rx()

    def receive(self, cfg: Config) -> np.ndarray:
        if not self.simulated:
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
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((args.listen, args.port))
        listener.listen(1)
        LOG.info("Serving %s:%d; simulate=%s", args.listen, args.port, args.simulate)
        while True:
            conn, addr = listener.accept()
            LOG.info("COSMOS connected from %s", addr)
            with conn:
                conn.setblocking(False)
                input_buffer = bytearray()
                seq = 0
                running = True
                hold = np.full(BINS, -160, dtype=np.float32)
                next_send = time.monotonic()
                last_status = 0.0
                status = "SIMULATION" if args.simulate else "PLUTO CONNECTED"
                try:
                    conn.sendall(make_status_frame(seq, status))
                    while True:
                        now = time.monotonic()
                        readable, _, _ = select.select([conn], [], [], (max(0, min(0.1, next_send - now)) if running else 0.1))
                        if readable:
                            try:
                                chunk = conn.recv(65536)
                            except BlockingIOError:
                                chunk = None
                            if chunk == b"":
                                break
                            if chunk:
                                input_buffer.extend(chunk)
                                for typ, frame in decode_frames(input_buffer):
                                    try:
                                        if typ == CMD_CONFIG:
                                            if len(frame) != CONFIG_SIZE:
                                                raise ValueError("CONFIG frame length mismatch")
                                            (length, _, hz, span, sps, fft, gain, avg,
                                             agc, fps) = struct.unpack(CONFIG_FMT, frame)
                                            new = Config(hz, span, sps, fft, gain, int(avg), agc, fps)
                                            new.validate(args.min_rf_mhz, args.max_rf_mhz)
                                            source.configure(new)
                                            cfg = new
                                            hold.fill(-160)
                                            next_send = time.monotonic()
                                            status = "CONFIG APPLIED"
                                        elif typ == CMD_START:
                                            running = True
                                            next_send = time.monotonic()
                                            status = "RUNNING"
                                        elif typ == CMD_STOP:
                                            running = False
                                            status = "STOPPED"
                                        elif typ == CMD_CLEAR_HOLD:
                                            hold.fill(-160)
                                            status = "PEAK HOLD CLEARED"
                                        else:
                                            raise ValueError(f"Unknown command ID {typ}")
                                        LOG.info("%s", status)
                                        conn.sendall(make_status_frame(seq, status))
                                    except Exception as exc:
                                        LOG.warning("Command failed: %s", exc)
                                        conn.sendall(make_status_frame(seq, f"ERROR: {exc}"))
                        now = time.monotonic()
                        if running and now >= next_send:
                            iq = source.receive(cfg)
                            levels, peak_hz, peak_dbfs, rbw = calculate_spectrum(iq, cfg)
                            hold = np.maximum(hold, levels)
                            seq = (seq + 1) % (2 ** 32)
                            conn.sendall(make_spectrum_frame(cfg, seq, levels, hold,
                                                             peak_hz, peak_dbfs, rbw))
                            next_send = time.monotonic() + 1 / cfg.fps
                        elif not running and now - last_status > 2:
                            conn.sendall(make_status_frame(seq, status))
                            last_status = now
                except (ConnectionError, OSError) as exc:
                    LOG.warning("COSMOS disconnected: %s", exc)
                except Exception:
                    LOG.exception("Bridge fault; waiting for COSMOS reconnection")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulate", action="store_true", help="Synthetic test signals; no hardware")
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
