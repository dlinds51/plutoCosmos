"""Read-only ADS-B integration for the Pluto COSMOS bridge.

readsb owns the Pluto while ADS-B mode is active and writes aircraft.json.
The bridge converts that structured aircraft state into native COSMOS telemetry.
"""
from __future__ import annotations

import json
import logging
import os
import math
import pathlib
import shutil
import struct
import subprocess
import tempfile
import time

LOG = logging.getLogger('pluto_cosmos.adsb')
ADSB_TABLE_ID = 4
ADSB_EVENT_ID = 5
MAX_AIRCRAFT_ROWS = 12
# All fields are fixed-width strings for a native COSMOS row matrix.
# Absence stays '-' instead of reporting a misleading zero.
COLUMNS = (
    ('ICAO', 8), ('CALLSIGN', 10), ('ALT_FT', 9), ('LAT', 11), ('LON', 12),
    ('GS_KT', 7), ('TRACK', 7), ('AGE_S', 6), ('MSGS', 8),
)
ROW_BYTES = sum(width for _, width in COLUMNS)
TABLE_PREFIX_FMT = '>IHIIII32s'  # LEN, TYPE, SEQ, UNIX_SECONDS, COUNT, TOTAL_MSGS, STATE
EVENT_PREFIX_FMT = '>IHI'       # LEN, TYPE, SEQ
TABLE_BYTES = struct.calcsize(TABLE_PREFIX_FMT) + MAX_AIRCRAFT_ROWS * ROW_BYTES
EVENT_BYTES = struct.calcsize(EVENT_PREFIX_FMT) + ROW_BYTES


def fmt_float(value, digits: int, low=None, high=None) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return '-'
    if low is not None and value < low:
        return '-'
    if high is not None and value > high:
        return '-'
    return f'{value:.{digits}f}'


def display_aircraft(raw: dict) -> dict:
    hex_addr = str(raw.get('hex') or '').strip().upper()[:8]
    callsign = str(raw.get('flight') or '').strip().upper()[:10] or '-'
    alt_raw = raw.get('alt_baro')
    if alt_raw == 'ground':
        alt = 'GROUND'
    elif isinstance(alt_raw, (int, float)) and not isinstance(alt_raw, bool) and math.isfinite(alt_raw):
        alt = str(int(round(alt_raw)))
    else:
        alt = '-'
    age = raw.get('seen')
    if not isinstance(age, (int, float)) or not math.isfinite(age) or age < 0:
        age = 99999.0
    messages = raw.get('messages')
    messages_int = int(messages) if isinstance(messages, (int, float)) and math.isfinite(messages) and messages >= 0 else 0
    return {
        'hex': hex_addr,
        'messages_int': messages_int,
        'age_float': float(age),
        'ICAO': hex_addr or '-',
        'CALLSIGN': callsign,
        'ALT_FT': alt,
        'LAT': fmt_float(raw.get('lat'), 5, -90, 90),
        'LON': fmt_float(raw.get('lon'), 5, -180, 180),
        'GS_KT': fmt_float(raw.get('gs'), 0, 0),
        'TRACK': fmt_float(raw.get('track'), 0, 0, 360),
        'AGE_S': fmt_float(age, 1, 0, 9999),
        'MSGS': str(messages_int),
    }


def normalize_aircraft(snapshot: dict, max_age: float = 60.0) -> list[dict]:
    aircraft = snapshot.get('aircraft', [])
    if not isinstance(aircraft, list):
        raise ValueError('aircraft.json: aircraft must be a list')
    result = []
    for item in aircraft:
        if not isinstance(item, dict):
            continue
        formatted = display_aircraft(item)
        if formatted['hex'] and formatted['age_float'] <= max_age:
            result.append(formatted)
    result.sort(key=lambda r: (r['age_float'], r['hex']))
    return result


def _fixed_ascii(value: str, width: int) -> bytes:
    return str(value).encode('ascii', errors='replace')[:width].ljust(width, b'\0')


def encode_row(row: dict) -> bytes:
    return b''.join(_fixed_ascii(row.get(col, '-'), width) for col, width in COLUMNS)


def make_adsb_table(seq: int, count: int, total: int, state: str, rows: list[dict]) -> bytes:
    head = struct.pack(TABLE_PREFIX_FMT, TABLE_BYTES, ADSB_TABLE_ID, seq, int(time.time()),
                       max(0, min(count, 0xffffffff)), max(0, min(int(total), 0xffffffff)),
                       _fixed_ascii(state, 32))
    empty = encode_row({col: '-' for col, _ in COLUMNS})
    return head + b''.join(encode_row(row) for row in rows[:MAX_AIRCRAFT_ROWS]) + \
        empty * (MAX_AIRCRAFT_ROWS - min(len(rows), MAX_AIRCRAFT_ROWS))


def make_adsb_event(seq: int, row: dict) -> bytes:
    return struct.pack(EVENT_PREFIX_FMT, EVENT_BYTES, ADSB_EVENT_ID, seq) + encode_row(row)


class ADSBRuntime:
    def __init__(self, uri: str, simulated: bool, readsb_path: str, log_path: str):
        self.uri = uri
        self.simulated = simulated
        self.readsb_path = readsb_path
        self.log_path = log_path
        self._tmp = None
        self._proc = None
        self._log_handle = None
        self._start_time = 0.0

    def start(self):
        if self.simulated:
            self._start_time = time.monotonic()
            return
        if self._proc is not None:
            return
        program = shutil.which(self.readsb_path)
        if not program:
            raise RuntimeError('readsb not found; compile readsb with PLUTOSDR=yes (see README)')
        if not self.uri.startswith('ip:'):
            raise ValueError('This version supports readsb --pluto-network via an ip: URI')
        host = self.uri.removeprefix('ip:')
        if not host:
            raise ValueError('Missing Pluto IP')
        self._tmp = tempfile.TemporaryDirectory(prefix='pluto_cosmos_adsb_')
        # Avoid writes to an old json file from an earlier readsb process.
        pathlib.Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = open(self.log_path, 'ab', buffering=0)
        command = [program, '--device-type', 'plutosdr', '--pluto-network', host,
                   '--write-json', self._tmp.name, '--write-json-every', '1',
                   '--quiet']
        # readsb's Pluto backend asks libiio for the default context before
        # consulting --pluto-network. In WSL2 this can select a local context
        # rather than the USB-network Pluto, causing invalid-device crashes.
        # Scope this override to readsb; leave the parent bridge unchanged.
        readsb_env = os.environ.copy()
        readsb_env['IIOD_REMOTE'] = self.uri
        LOG.info('readsb libiio default context: IIOD_REMOTE=%s', self.uri)
        try:
            self._proc = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                          stdout=self._log_handle, stderr=subprocess.STDOUT,
                                          env=readsb_env)
        except Exception:
            self.stop()
            raise
        LOG.info('ADS-B started: %s (PID %d, logs %s)', ' '.join(command),
                 self._proc.pid, self.log_path)
        self._start_time = time.monotonic()

    def snapshot(self) -> dict | None:
        if self.simulated:
            elapsed = max(0.0, time.monotonic() - self._start_time)
            return {
                'messages': int(elapsed * 30), 'aircraft': [
                    {'hex': 'AC0001', 'flight': 'DEMO101', 'alt_baro': 34000,
                     'lat': 39.50001, 'lon': -104.50003, 'gs': 441,
                     'track': 212, 'seen': 0.3, 'messages': int(elapsed * 7) + 1},
                    {'hex': 'AC0002', 'flight': 'DEMO202', 'alt_baro': 12500,
                     'lat': 38.50001, 'lon': -104.90003, 'gs': 275,
                     'track': 35, 'seen': 0.7, 'messages': int(elapsed * 5) + 1},
                    {'hex': 'AC0003', 'alt_baro': 'ground', 'seen': 1.1,
                     'messages': int(elapsed * 2) + 1},
                ]}
        if self._proc is None:
            raise RuntimeError('readsb is not running')
        if self._proc.poll() is not None:
            raise RuntimeError(f'readsb exited code {self._proc.returncode}; see {self.log_path}')
        path = pathlib.Path(self._tmp.name) / 'aircraft.json'
        if not path.exists():
            if time.monotonic() - self._start_time > 15:
                raise RuntimeError(f'No aircraft.json after 15s; see {self.log_path}')
            return None
        try:
            payload = json.loads(path.read_text(encoding='utf8'))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None  # readsb may be replacing this file, retry next second
        if not isinstance(payload, dict):
            raise ValueError('readsb returned invalid JSON root')
        # Ignore old readsb snapshots so they don't appear to be current.
        stamp = payload.get('now')
        if isinstance(stamp, (float, int)) and time.time() - stamp > 15:
            return None
        return payload

    def stop(self):
        proc, self._proc = self._proc, None
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=4)
            LOG.info('ADS-B decoder stopped')
        if self._log_handle:
            self._log_handle.close()
            self._log_handle = None
        if self._tmp:
            self._tmp.cleanup()
            self._tmp = None
