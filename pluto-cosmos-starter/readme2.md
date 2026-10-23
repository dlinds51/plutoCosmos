# PlutoSDR + OpenC3 COSMOS — Native Spectrum + Waterfall (v0.2.0)

A **receive-only** PlutoSDR test instrument where **all display and controls remain inside COSMOS Telemetry Viewer**. The WSL2 Python bridge receives I/Q samples, performs FFTs, and publishes binary COSMOS telemetry. The new waterfall is a small base64 PNG transmitted as telemetry and rendered by the built-in **IMAGEVIEWER** widget; no custom Vue dashboard, separate browser, or GNU Radio is needed for this phase.

## What's new

- Native **IMAGEVIEWER** waterfall: 256 frequency bins × 96 rolling time rows (displayed as an enlarged 768×192 indexed PNG); latest FFT is at the **top**. Color-scaled relative dBFS, not calibrated dBm.
- Independent **RF BW (MHz)** setting. Zoom/display **Span (MHz)** no longer modifies the Pluto hardware RF filter.
- COSMOS buttons **Apply waterfall colors** (floor/ceiling dBFS) and **Clear waterfall**.
- Waterfall telemetry capped to about 1 image/second; FFT/spectrum can still update at 1, 2 or 5 frames/s. Waterfall history is reset when center/span/sample rate/FFT size/RF BW change.
- Original `SPECTRUM`/`STATUS` packets, `START`/`STOP`/`CLEAR_HOLD`, and original `CONFIG` (ID 100) remain supported on the bridge. **New screen sends CONFIG_V2 (ID 104)**, carrying independent RF BW. Screen and Python bridge must both be v0.2.0 to use new controls.

## Update an existing WORKING v0.1.2 installation

1. Stop the WSL2 bridge with Ctrl+C.
2. Back up your current `bridge/pluto_bridge.py` and optional `cosmos-plugin` directory.
3. Copy the **new** `bridge/pluto_bridge.py` into the same `bridge/` folder in your existing WSL2 project. Dependencies are unchanged from v0.1.2 (`pylibiio==0.25`, numpy, pyadi-iio). Use your existing activated `.venv`.
4. From the downloadable archive, install `cosmos-plugin/openc3-cosmos-plutosdr-0.2.0.gem` using **COSMOS Admin → Plugins**. Upgrade/replace the installed older plugin; if COSMOS reports conflicting target/interface definitions, uninstall the old Pluto plugin before installing the new one (this temporarily removes PLUTO_SDR targets/screens until reinstalled). Reconnect `PLUTO_SDR_INT` in **Command and Telemetry Server** if necessary.
5. Restart the WSL2 bridge:

   ```bash
   python3 bridge/pluto_bridge.py --uri ip:192.168.2.1 --verbose
   ```

6. Close and reopen **Telemetry Viewer → PLUTO_SDR → spectrum**. Scroll down beneath the ARRAYPLOT to see the new **Waterfall** and frequency-edge readouts. Try **Span=0.25**, **RF BW=1.6** and click **Apply settings**. The bridge should *not* log `SDR: rx_rf_bandwidth` as changed just from span adjustment.
7. Start with waterfall scale **min=-115, max=-35 dBFS**. If the waterfall looks all dark/bright, adjust those values and click **Apply waterfall colors**. Bright rows/regions represent stronger signal energy.

**Important:** Changing span only crops the FFT trace. With `sample rate=2 MSPS`, `RF BW=1.6 MHz` and `span=0.25 MHz`, the analog receiver still captures ~1.6 MHz bandwidth. Note that signal power may be filtered near the wide edges. Actual usable bandwidth is limited by the receiver hardware filters and sample rate.

**Hardware note:** Standard Pluto official RF range is 325–3800 MHz. Do not assume broadcast FM 88–108 MHz works without a verified modification or separate receiver. This plugin implements no RF transmission.

## Screen controls

| COSMOS field | Initial value | Notes |
|---|---:|---|
| Center (MHz) | 915 | Pluto receive LO |
| Span (MHz) | 1.6 | Width of displayed FFT / waterfall, max sample rate |
| Sample rate (MSPS) | 2.0 | I/Q sample rate |
| RF BW (MHz) | 1.6 | **Independent** hardware RX filter bandwidth, 0.2 MHz to sample rate |
| FFT size | 2048 | 256, 512, 1024, 2048, 4096, 8192 |
| Gain (dB) | 40 | Used when AGC=0 |
| Avg FFTs | 8 | Average linear power of FFT windows per update |
| AGC | 0 | 0 manual, 1 slow-attack |
| Updates/s | 2 | FFT/telemetry update rate 1, 2 or 5 Hz |
| Waterfall min/max dBFS | -115/-35 | Adjusts palette, does not change RF |

### Graph interpretation

- **Spectrum:** built-in `ARRAYPLOT`, horizontal index 0–511. COSMOS native ARRAYPLOT does not accept dynamic X-axis MHz endpoints through widget telemetry, so the actual left/center/right frequency is shown in `VALUE` fields. Peak and RBW telemetry remain visible.
- **Waterfall:** built-in `IMAGEVIEWER` displays a PNG encoded in `PLUTO_SDR WATERFALL PNG_BASE64` telemetry. Horizontal axis is left→right frequency; newest samples are at the **top**. Native readout values under the image report left/center/right MHz. At 2 FPS, 96 rows represent up to ~48 seconds of spectrum history; the PNG is published about once a second.
- **Power:** relative to an approximate 12-bit Pluto scale (dBFS); it has **not** been calibrated into dBm. The center DC spur is not digitally suppressed.

## Start from scratch

```bash
sudo apt update
sudo apt install -y python3-venv libiio-utils libiio0
cd /path/to/pluto-cosmos-starter-v0.2.0
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r bridge/requirements.txt
python3 -c 'import adi; s=adi.Pluto(uri="ip:192.168.2.1"); print(s.rx_lo)'
python3 bridge/pluto_bridge.py --uri ip:192.168.2.1 --verbose
```

If your Ubuntu package names differ, check the libiio packaging for your release. On systems with `libiio0` 0.x, the pinned `pylibiio==0.25` is necessary. With no hardware use `python3 bridge/pluto_bridge.py --simulate` instead.

Install the bundled `.gem` from COSMOS Admin → Plugins and connect `PLUTO_SDR_INT`. The plugin's TCP client uses `host.docker.internal:7350` to reach the WSL2 bridge, same as the previous version.

## Building the plugin (optional)

```bash
cd cosmos-plugin
gem build openc3-cosmos-plutosdr.gemspec
```

Produces `openc3-cosmos-plutosdr-0.2.0.gem`.

## Protocol (for extending later)

- All packets begin `uint32 big-endian total length`, `uint16 big-endian type`. COMMAND `CONFIG` ID 100 is original 36-byte payload; `CONFIG_V2` ID 104 is original fields **plus `uint32 RF_BANDWIDTH_HZ` at the end**, total 40 bytes.
- New commands: `WF_RANGE` ID 105, total 14 bytes, two big-endian float32 values; `CLEAR_WF` ID 106, 6 bytes.
- `SPECTRUM` ID 1 and `STATUS` ID 2 have unchanged layouts. `WATERFALL` ID 3 begins with length/type/sequence, six float32 values (left/center/right MHz, palette min/max dBFS, row seconds), one uint32 valid rows, then variable-length ASCII base64 PNG in COSMOS `APPEND_ITEM PNG_BASE64 0 STRING`.
- The waterfall PNG is indexed RGB with a fixed 256-color palette. To minimize dependencies it is generated using Python's built-in `zlib`, `struct`, and `base64`; no Pillow is required. Image telemetry is throttled to approximately 1 FPS to limit browser and storage overhead.

## Validation and caveats

```bash
python3 -m unittest discover -s tests -v
```

12 automated tests include PNG chunk/CRC/format, packet protocol, independent RF BW behavior, reconnection and simulated TCP session with `CONFIG_V2`, changing waterfall colors, and clearing history.

**Not yet tested on your actual OpenC3 installation or Pluto hardware.** The previously working v0.1.2 acquisition/retune logic is retained, and the new simulated protocol tests pass. COSMOS versions may render IMAGEVIEWER differently or handle very large image telemetry differently; if you see a blank or broken image, first check if `PLUTO_SDR WATERFALL SEQ` and `VALID_ROWS` advance in Packet Viewer, then report the COSMOS viewer error. At some settings, PNG telemetry can be tens of kB per second and adds telemetry/storage load; do not run it at high frequency indefinitely without considering retention.

## Future extensions

- ADS-B (1090 MHz): use `readsb`/GNU Radio for actual decoding, publish aircraft-state packets to COSMOS. ADS-B and spectrum analyzer modes should initially be exclusive on one PlutoRX stream.
- FM audio: use GNU Radio for demodulation/playback from a supported SDR RF band; COSMOS remains the command/status UI.
