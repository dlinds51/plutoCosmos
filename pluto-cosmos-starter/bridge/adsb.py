
"""Read-only ADS-B integration for the Pluto COSMOS bridge.

readsb owns the Pluto while ADS-B mode is active and writes aircraft.json.
The bridge converts that structured aircraft state into native COSMOS telemetry.
Also generates a simple native COSMOS map image from aircraft positions.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import math
import os
import pathlib
import shutil
import struct
import subprocess
import tempfile
import time
import zlib
from collections import deque

import numpy as np
from PIL import Image, ImageDraw, ImageFont

LOG = logging.getLogger('pluto_cosmos.adsb')
ADSB_TABLE_ID = 4
ADSB_EVENT_ID = 5
ADSB_MAP_ID = 6
MAX_AIRCRAFT_ROWS = 12
DEFAULT_HOME_LAT = 39.079046981923796
DEFAULT_HOME_LON = -104.86428665378747
DEFAULT_LAT_SPAN = 2.0
DEFAULT_LON_SPAN = 3.0
# All fields are fixed-width strings for a native COSMOS row matrix.
# Absence stays '-' instead of reporting a misleading zero.
COLUMNS = (
    ('ICAO', 8), ('CALLSIGN', 10), ('ALT_FT', 9), ('LAT', 11), ('LON', 12),
    ('GS_KT', 7), ('TRACK', 7), ('AGE_S', 6), ('MSGS', 8),
)
ROW_BYTES = sum(width for _, width in COLUMNS)
TABLE_PREFIX_FMT = '>IHIIII32s'  # LEN, TYPE, SEQ, UNIX_SECONDS, COUNT, TOTAL_MSGS, STATE
EVENT_PREFIX_FMT = '>IHI'       # LEN, TYPE, SEQ
MAP_PREFIX_FMT = '>IHI8fII'     # LEN, TYPE, SEQ, bounds/home/spans, aircraft, points
TABLE_BYTES = struct.calcsize(TABLE_PREFIX_FMT) + MAX_AIRCRAFT_ROWS * ROW_BYTES
EVENT_BYTES = struct.calcsize(EVENT_PREFIX_FMT) + ROW_BYTES

REGIONAL_FEATURES = [
    ('Denver', 39.7392, -104.9903),
    ('DIA', 39.8561, -104.6737),
    ('Castle Rock', 39.3722, -104.8561),
    ('Monument', 39.0911, -104.8728),
    ('Colorado Springs', 38.8339, -104.8214),
    ('Pueblo', 38.2544, -104.6091),
    ('Limon', 39.2639, -103.6922),
]


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
    lat_raw = raw.get('lat')
    lon_raw = raw.get('lon')
    lat_float = float(lat_raw) if isinstance(lat_raw, (int, float)) and math.isfinite(lat_raw) and -90 <= lat_raw <= 90 else None
    lon_float = float(lon_raw) if isinstance(lon_raw, (int, float)) and math.isfinite(lon_raw) and -180 <= lon_raw <= 180 else None
    return {
        'hex': hex_addr,
        'messages_int': messages_int,
        'age_float': float(age),
        'lat_float': lat_float,
        'lon_float': lon_float,
        'ICAO': hex_addr or '-',
        'CALLSIGN': callsign,
        'ALT_FT': alt,
        'LAT': fmt_float(lat_raw, 5, -90, 90),
        'LON': fmt_float(lon_raw, 5, -180, 180),
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


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    payload = tag + data
    return struct.pack('>I', len(data)) + payload + struct.pack('>I', zlib.crc32(payload) & 0xffffffff)


def _rgb_png(image: Image.Image) -> bytes:
    # Quantize to a small adaptive palette so the base64 telemetry stays compact.
    if image.mode != 'RGB':
        image = image.convert('RGB')
    image = image.convert('P', palette=Image.Palette.ADAPTIVE, colors=64)
    buf = io.BytesIO()
    image.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


class AircraftMap:
    """Simple fixed-region lat/lon map with short track history, rendered as PNG for COSMOS."""
    def __init__(self, width: int = 600, height: int = 360,
                 history_seconds: float = 900.0, max_points_per_track: int = 120,
                 home_lat: float = DEFAULT_HOME_LAT, home_lon: float = DEFAULT_HOME_LON,
                 lat_span: float = DEFAULT_LAT_SPAN, lon_span: float = DEFAULT_LON_SPAN):
        self.width = width
        self.height = height
        self.history_seconds = history_seconds
        self.max_points_per_track = max_points_per_track
        self.home_lat = float(home_lat)
        self.home_lon = float(home_lon)
        self.lat_span = float(lat_span)
        self.lon_span = float(lon_span)
        self.tracks: dict[str, deque] = {}
        self.labels: dict[str, str] = {}

    def set_region(self, home_lat: float, home_lon: float, lat_span: float, lon_span: float):
        if not (math.isfinite(home_lat) and -90 <= home_lat <= 90):
            raise ValueError('Home latitude must be -90..90')
        if not (math.isfinite(home_lon) and -180 <= home_lon <= 180):
            raise ValueError('Home longitude must be -180..180')
        if not (math.isfinite(lat_span) and 0.1 <= lat_span <= 20):
            raise ValueError('Latitude span must be 0.1..20 degrees')
        if not (math.isfinite(lon_span) and 0.1 <= lon_span <= 30):
            raise ValueError('Longitude span must be 0.1..30 degrees')
        self.home_lat = float(home_lat)
        self.home_lon = float(home_lon)
        self.lat_span = float(lat_span)
        self.lon_span = float(lon_span)

    def clear_tracks(self):
        self.tracks.clear()
        self.labels.clear()

    def reset(self):
        self.clear_tracks()

    def bounds(self) -> tuple[float, float, float, float]:
        min_lat = max(-90.0, self.home_lat - self.lat_span / 2)
        max_lat = min(90.0, self.home_lat + self.lat_span / 2)
        min_lon = max(-180.0, self.home_lon - self.lon_span / 2)
        max_lon = min(180.0, self.home_lon + self.lon_span / 2)
        return min_lat, max_lat, min_lon, max_lon

    def update(self, rows: list[dict], now: float | None = None):
        now = time.time() if now is None else now
        for row in rows:
            lat = row.get('lat_float')
            lon = row.get('lon_float')
            ident = row.get('hex')
            if ident and lat is not None and lon is not None:
                track = self.tracks.setdefault(ident, deque(maxlen=self.max_points_per_track))
                if not track or abs(track[-1][1] - lat) > 1e-5 or abs(track[-1][2] - lon) > 1e-5:
                    track.append((now, lat, lon))
                else:
                    t, _, _ = track[-1]
                    track[-1] = (now, lat, lon)
                self.labels[ident] = row.get('CALLSIGN', '-') if row.get('CALLSIGN', '-') != '-' else ident
        stale_before = now - self.history_seconds
        for ident in list(self.tracks):
            dq = self.tracks[ident]
            while dq and dq[0][0] < stale_before:
                dq.popleft()
            if not dq:
                self.tracks.pop(ident, None)
                self.labels.pop(ident, None)
        return self.snapshot()

    def snapshot(self) -> dict:
        min_lat, max_lat, min_lon, max_lon = self.bounds()
        return {
            'min_lat': float(min_lat), 'max_lat': float(max_lat),
            'min_lon': float(min_lon), 'max_lon': float(max_lon),
            'home_lat': float(self.home_lat), 'home_lon': float(self.home_lon),
            'lat_span': float(self.lat_span), 'lon_span': float(self.lon_span),
            'aircraft': len(self.tracks),
            'points': sum(len(dq) for dq in self.tracks.values()),
            'png': self.render_png(min_lat, max_lat, min_lon, max_lon),
        }

    def render_png(self, min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> bytes:
        bg = (19, 35, 53)
        grid = (55, 78, 96)
        border = (205, 220, 232)
        text = (240, 245, 250)
        muted = (170, 185, 200)
        home_color = (255, 106, 106)
        img = Image.new('RGB', (self.width, self.height), bg)
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        left, right = 60, self.width - 20
        top, bottom = 22, self.height - 42
        draw.rectangle((left, top, right, bottom), outline=border, width=1)
        lat_span = max(max_lat - min_lat, 1e-6)
        lon_span = max(max_lon - min_lon, 1e-6)

        def project(lat: float, lon: float) -> tuple[int, int]:
            x = left + int(round((lon - min_lon) / lon_span * (right - left)))
            y = top + int(round((max_lat - lat) / lat_span * (bottom - top)))
            return max(left, min(right, x)), max(top, min(bottom, y))

        # Draw grid and labels.
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            x = left + int(round((right - left) * frac))
            y = top + int(round((bottom - top) * frac))
            draw.line((x, top, x, bottom), fill=grid, width=1)
            draw.line((left, y, right, y), fill=grid, width=1)
            lon_val = min_lon + lon_span * frac
            lat_val = max_lat - lat_span * frac
            draw.text((x - 18, bottom + 6), f'{lon_val:.2f}', fill=muted, font=font)
            draw.text((4, y - 5), f'{lat_val:.2f}', fill=muted, font=font)

        # Fixed regional reference labels if visible.
        for name, lat, lon in REGIONAL_FEATURES:
            if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
                x, y = project(lat, lon)
                draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(220, 220, 130))
                draw.text((x + 5, y - 8), name, fill=(220, 220, 130), font=font)

        # Draw aircraft tracks and labels.
        palette = [
            (0, 229, 255), (255, 200, 60), (255, 90, 145), (99, 255, 132),
            (255, 143, 70), (180, 120, 255), (255, 80, 80), (126, 232, 250),
        ]
        for idx, ident in enumerate(sorted(self.tracks)):
            dq = list(self.tracks[ident])
            if not dq:
                continue
            color = palette[idx % len(palette)]
            pts = [project(lat, lon) for _, lat, lon in dq if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon]
            if not pts:
                continue
            if len(pts) >= 2:
                draw.line(pts, fill=color, width=2)
            x, y = pts[-1]
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color, outline=(255, 255, 255))
            label = self.labels.get(ident, ident)
            draw.text((x + 6, y - 10), label, fill=color, font=font)

        # Draw home marker and center label.
        hx, hy = project(self.home_lat, self.home_lon)
        draw.line((hx - 8, hy, hx + 8, hy), fill=home_color, width=2)
        draw.line((hx, hy - 8, hx, hy + 8), fill=home_color, width=2)
        draw.ellipse((hx - 5, hy - 5, hx + 5, hy + 5), outline=home_color, width=2)
        draw.text((hx + 8, hy + 8), 'HOME', fill=home_color, font=font)

        title = f'ADSB REGION  center {self.home_lat:.5f}, {self.home_lon:.5f}'
        subtitle = f'lat span {self.lat_span:.2f}°   lon span {self.lon_span:.2f}°   tracks {len(self.tracks)}'
        draw.text((left, 2), title, fill=text, font=font)
        draw.text((left, self.height - 16), subtitle, fill=text, font=font)
        return _rgb_png(img)


def make_adsb_map(seq: int, snapshot: dict) -> bytes:
    image = base64.b64encode(snapshot['png'])
    head = struct.pack(MAP_PREFIX_FMT,
                       struct.calcsize(MAP_PREFIX_FMT) + len(image),
                       ADSB_MAP_ID, seq,
                       float(snapshot['min_lat']), float(snapshot['max_lat']),
                       float(snapshot['min_lon']), float(snapshot['max_lon']),
                       float(snapshot['home_lat']), float(snapshot['home_lon']),
                       float(snapshot['lat_span']), float(snapshot['lon_span']),
                       int(snapshot['aircraft']), int(snapshot['points']))
    return head + image


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
        pathlib.Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = open(self.log_path, 'ab', buffering=0)
        command = [program, '--device-type', 'plutosdr', '--pluto-network', host,
                   '--write-json', self._tmp.name, '--write-json-every', '1',
                   '--quiet']
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
                     'lat': 39.50001 + 0.01 * math.sin(elapsed/8.0),
                     'lon': -104.50003 + 0.02 * math.cos(elapsed/8.0), 'gs': 441,
                     'track': 212, 'seen': 0.3, 'messages': int(elapsed * 7) + 1},
                    {'hex': 'AC0002', 'flight': 'DEMO202', 'alt_baro': 12500,
                     'lat': 38.50001 + 0.015 * math.cos(elapsed/10.0),
                     'lon': -104.90003 + 0.03 * math.sin(elapsed/10.0), 'gs': 275,
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
            return None
        if not isinstance(payload, dict):
            raise ValueError('readsb returned invalid JSON root')
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
