# PlutoSDR + OpenC3 COSMOS

**A commandable, receive-only software-defined radio platform with spectrum analysis, live ADS-B aircraft tracking, and stereo FM radio — controlled and monitored from OpenC3 COSMOS.**

This project connects an **Analog Devices ADALM-PLUTO (PlutoSDR)** to **OpenC3 COSMOS** using a Python bridge running in **Ubuntu on WSL2**. COSMOS supplies the user interface, commands, telemetry displays, and logging. The bridge operates the radio, performs DSP, and integrates optional decoders. FM audio plays through **WSLg to the Windows speakers** rather than through the browser.

**Current project version:** `v0.7.0` · **Status:** Spectrum, ADS-B, and FM operation demonstrated on real hardware; 28 automated tests pass. Reception quality, station metadata, and DSP performance depend on hardware, signal conditions, and local system configuration.

> **Scope:** This is a hobby/learning and systems-integration project, not a calibrated spectrum analyzer, certified surveillance receiver, or aviation-safety system. All modes are **receive-only**.

## Contents

- [Features](#features)
- [System architecture](#system-architecture)
- [Repository layout](#repository-layout)
- [Requirements](#requirements)
- [Install and run](#install-and-run)
- [Using the COSMOS screens](#using-the-cosmos-screens)
- [PlutoSDR broadcast-FM frequency extension](#plutosdr-broadcast-fm-frequency-extension)
- [Tests and simulation](#tests-and-simulation)
- [Configuration and telemetry](#configuration-and-telemetry)
- [Troubleshooting](#troubleshooting)
- [Version history](#version-history)
- [Limitations and roadmap](#limitations-and-roadmap)
- [References](#references)

## Features

| Mode | Capabilities | Output |
| --- | --- | --- |
| **Spectrum analyzer** | Center frequency, display span, independent RF bandwidth, sample rate, FFT size, gain/AGC, averaging, peak hold, color range | Live FFT trace, peak hold, signal levels, scrolling waterfall |
| **ADS-B (1090 MHz)** | Decoding via `readsb`; aircraft identity and position; track history; home marker; fixed regional map; Clear Tracks | Aircraft table, latest aircraft event, live regional plot in COSMOS |
| **Broadcast FM (88–108 MHz)** | Software-defined tuning, gain, volume; pilot-assisted stereo with mono fallback; optional RDS via `redsea` | Audio on Windows speakers; L/R audio spectrum; stereo status; RDS station metadata |

All controls and **visualizations** stay in **COSMOS Telemetry Viewer**. No separate web dashboard is required. The Pluto has one active receive chain in this design, so **Spectrum, ADS-B, and FM modes are mutually exclusive**.

### Spectrum analyzer

- Live FFT with 512 displayed bins and a separate peak-hold trace.
- Scrolling waterfall (native COSMOS `IMAGEVIEWER`, populated with bridge-generated PNG telemetry).
- User-adjustable center frequency, sample rate, FFT size, gain, AGC, smoothing/averaging, and update frequency.
- Display span is distinct from the Pluto's analog RX bandwidth: zooming the graph need not change the hardware RF filter.
- RF power values are **relative dBFS**, **not calibrated dBm**. Frequency readouts show the graph's physical limits; the native array plot itself uses bin indices.

### ADS-B receiver

- `readsb` directly captures/decodes **1090 MHz Mode S / ADS-B** from the Pluto.
- COSMOS shows up to **12 recently heard aircraft** with ICAO hex address, callsign (when provided), barometric altitude, latitude/longitude, groundspeed, track, age, and message count. The underlying count can exceed the visible rows.
- A native COSMOS map image shows aircraft positions, recent trails (roughly **15 minutes**), a home-station marker, latitude/longitude grid, and selected regional reference labels.
- **Home latitude/longitude** and **map latitude/longitude spans** are editable on the ADS-B screen. The map is a fixed region centered on home (rather than auto-zooming), and **Clear Tracks** empties history without resetting the region.
- An aircraft's position or other fields can legitimately be missing until sufficient messages have been received. A dash means *unknown*, not zero.



### FM broadcast receiver

- Wideband FM demodulation with a **1.2 MSPS I/Q input**, a **240 kSPS FM multiplex signal**, and **48 kHz two-channel PCM output**.
- Stereo separation using the broadcast **19 kHz pilot** to recover the **38 kHz L−R subcarrier**; automatically plays dual mono when a usable pilot is unavailable.
- 15 kHz audio low-pass filtering and **75 µs de-emphasis** (US broadcast standard).
- RDS decoding via optional `redsea`: **PI**, **PS (station name)**, **PTY**, and **RadioText**, if broadcast and successfully decoded.
- Live left/right audio FFT (~0–12 kHz) and pilot-lock, RDS, volume, and signal-level telemetry within COSMOS.
- Speaker playback uses `pacat` / **WSLg PulseAudio**. COSMOS never transports the high-bandwidth PCM stream.

## System architecture

```text
                        WINDOWS HOST
  ┌──────────────────────────────────────────────────────────┐
  │ Web browser → OpenC3 COSMOS (Docker Desktop)             │
  │   Telemetry Viewer: Spectrum | ADS-B | FM                │
  │   Commands, PNG/FFT/aircraft/RDS telemetry, logging      │
  └────────────────────────┬─────────────────────────────────┘
                           │ TCP/IP (host.docker.internal:7350)
  ┌────────────────────────▼─────────────────────────────────┐
  │ UBUNTU / WSL2          Python bridge                     │
  │   bridge/pluto_bridge.py                                 │
  │                                                          │
  │   Spectrum: I/Q → FFT / peak hold / waterfall PNG        │
  │   ADS-B:    readsb → aircraft.json → map / telemetry     │
  │   FM:       I/Q → FM MPX → stereo PCM + audio FFT        │
  │                            ├→ redsea → RDS telemetry     │
  │                            └→ pacat → WSLg → speakers    │
  └────────────────────────┬─────────────────────────────────┘
                           │ libiio / pyadi-iio
                           │ ip:192.168.2.1 (default)
                     ┌─────▼──────┐
                     │  PlutoSDR  │
                     │ RF → I/Q   │
                     └────────────┘
```

**Key design choices**

1. COSMOS sends structured commands and receives low-rate telemetry over one TCP connection (default **7350**).
2. DSP remains in WSL2, **not** in the browser or the COSMOS Docker container.
3. The bridge releases/reclaims the Pluto when switching modes so `readsb` and Python don't compete for the radio.
4. The waterfall and map are sent as compact **base64-encoded PNG telemetry**, displayed by native COSMOS `IMAGEVIEWER` widgets.
5. Optional RDS processing runs separately from the real-time audio path so decoder delays do not intentionally stall speaker playback.

## Repository layout

The following assumes this README is placed at the **Git repository root**, alongside `pluto-cosmos-starter/`:

```text
plutoCosmos/
├── README.md                          ← main project README (this file)
└── pluto-cosmos-starter/
    ├── README.md                      ← release-specific notes
    ├── bridge/
    │   ├── pluto_bridge.py            ← TCP server, command handler, mode switching
    │   ├── adsb.py                    ← readsb integration and aircraft map
    │   ├── fm.py                      ← receiver settings and PulseAudio sink
    │   ├── fm_stereo.py               ← stereo FM DSP and L/R audio FFT
    │   ├── rds_stream.py              ← redsea integration and RDS telemetry
    │   ├── requirements.txt           ← Python dependencies
    │   ├── test_audio.py              ← mono WSLg speaker test
    │   └── test_stereo_audio.py       ← left/right speaker test
    ├── cosmos-plugin/
    │   ├── openc3-cosmos-plutosdr-0.7.0.gem
    │   ├── openc3-cosmos-plutosdr.gemspec
    │   ├── plugin.txt                 ← interface/target definitions
    │   └── targets/PLUTO_SDR/
    │       ├── cmd_tlm/               ← binary command and telemetry definitions
    │       └── screens/               ← spectrum.txt, adsb.txt, fm.txt
    └── tests/                         ← simulated protocol/DSP regression tests
```

Paths in the commands below are relative to `pluto-cosmos-starter/`, unless otherwise noted.

## Requirements

### Hardware / host

- **Analog Devices ADALM-PLUTO** with USB virtual-Ethernet access from WSL2 (default address `192.168.2.1`).
- A suitable antenna for each service: ~100 MHz for FM, **1090 MHz** for ADS-B, and an appropriate antenna for spectrum experiments.
- Windows with **WSL2 + WSLg** (for Windows speaker playback), Ubuntu, **Docker Desktop**, and an operational **OpenC3 COSMOS** instance.
- Broadcast FM requires Pluto's **extended tuning range to be enabled and verified**; the standard specified range is approximately **325 MHz to 3.8 GHz**.

### Software dependencies

| Type | Packages / tools | Purpose |
| --- | --- | --- |
| Python (`pip`) | NumPy, `pyadi-iio`, `pylibiio==0.25`, Pillow, SciPy | Hardware access, FFT/DSP, image rendering |
| Ubuntu (`apt`) | `libiio-dev`, `libiio-utils`, `libad9361-dev` | Native radio libraries and diagnostic commands |
| Ubuntu (`apt`) | `pulseaudio-utils` (provides **`pacat`** and `pactl`) | Audio playback through WSLg |
| Optional compiled app | [`wiedehopf/readsb`](https://github.com/wiedehopf/readsb), built with `PLUTOSDR=yes` | ADS-B decoding |
| Optional compiled app | [`windytan/redsea`](https://github.com/windytan/redsea) | FM RDS metadata |

`pacat` is **not a pip dependency**. Keep it in the system-dependencies section rather than in `bridge/requirements.txt`.

> **Version compatibility:** This setup has worked with an Ubuntu native **libiio 0.x** installation and `pylibiio==0.25`. Installing Python bindings for **libiio 1.x** against a native **0.x** library can prevent `import adi` from working. The project's `requirements.txt` pins `pylibiio` accordingly; revisit the pin if you upgrade the native library stack.

## Install and run

### 1. Clone the repository and install system tools

In your **Ubuntu WSL2** terminal:

```bash
git clone https://github.com/dlinds51/plutoCosmos.git
cd plutoCosmos/pluto-cosmos-starter

sudo apt update
sudo apt install -y \
  python3-venv python3-pip git build-essential pkg-config \
  libiio-dev libiio-utils libad9361-dev libusb-1.0-0-dev \
  libncurses-dev zlib1g-dev libzstd-dev pulseaudio-utils
```

If the repository is already cloned, simply `cd` into your existing `pluto-cosmos-starter/` directory; don't clone it a second time.

### 2. Create a Python virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r bridge/requirements.txt
```

Verify that the Pluto can be contacted and read its current receiver frequency:

```bash
ping -c 3 192.168.2.1
iio_info -u ip:192.168.2.1 | head -30
python3 -c 'import adi; s=adi.Pluto(uri="ip:192.168.2.1"); print(s.rx_lo)'
```

The exact LO value varies with the current tuning. Successful communication confirms the Python/native libiio stack and IP route. A test of **actual I/Q reception** is also useful:

```bash
python3 - <<'PY'
import adi
sdr = adi.Pluto(uri='ip:192.168.2.1')
sdr.sample_rate = 2_000_000
sdr.rx_buffer_size = 4096
samples = sdr.rx()
print('Received', len(samples), 'complex I/Q samples')
PY
```

**Stop other Pluto applications before running the bridge**; competing IIO connections can prevent RX-buffer acquisition.

### 3. Build the ADS-B decoder (optional, needed for ADS-B mode)

```bash
git clone --depth 1 https://github.com/wiedehopf/readsb.git "$HOME/readsb"
make -C "$HOME/readsb" -j"$(nproc)" PLUTOSDR=yes
"$HOME/readsb/readsb" --help | grep -A7 -i pluto
```

This project starts `readsb` with `--device-type plutosdr` and `--pluto-network 192.168.2.1`. The bridge's `adsb.py` also passes **`IIOD_REMOTE=ip:192.168.2.1` to the decoder subprocess**. This avoids a default-libiio-context mismatch observed under WSL2 and does **not** need to be exported globally when using the current bridge.

### 4. Build the RDS decoder (optional, needed only for station text)

```bash
sudo apt install -y meson ninja-build libsndfile1-dev libliquid-dev

git clone https://github.com/windytan/redsea.git "$HOME/redsea"
meson setup "$HOME/redsea/build" "$HOME/redsea"
meson compile -C "$HOME/redsea/build"
"$HOME/redsea/build/redsea" --help
```

`redsea` accepts demodulated FM multiplex (MPX), from which it can decode RDS. **FM stereo and the audio spectrum do not require `redsea`**. If this build fails, check the [redsea project instructions](https://github.com/windytan/redsea) for updated distribution-specific dependencies.

### 5. Verify Windows audio (FM only)

```bash
command -v pacat
printf 'PULSE_SERVER=%s\n' "$PULSE_SERVER"
pactl info
python3 bridge/test_audio.py
python3 bridge/test_stereo_audio.py
```

Turn the Windows speaker volume down before running the tests. The first plays a short mono tone; the second tests left and right channels separately. If `pactl` cannot connect, check that WSLg audio is enabled and that `/mnt/wslg/PulseServer` is accessible.

### 6. Install the COSMOS plugin

1. Start your existing **OpenC3 COSMOS** Docker environment.
2. In **COSMOS Admin → Plugins**, install or upgrade `cosmos-plugin/openc3-cosmos-plutosdr-0.7.0.gem`.
3. Confirm that the **`PLUTO_SDR`** target and **`PLUTO_SDR_INT`** interface exist.
4. The plugin's interface points to **`host.docker.internal:7350`**. If your Docker ↔ WSL2 network differs, adjust `cosmos-plugin/plugin.txt` and rebuild/reinstall the gem rather than changing the Pluto's IP blindly.
5. Open **Telemetry Viewer → PLUTO_SDR** and select **SPECTRUM**, **ADSB**, or **FM**.

The plugin is a **COSMOS target/interface/screens package**. The Python bridge must be running separately in WSL2 for live hardware telemetry.

### 7. Start the bridge

To enable all three modes, once readsb/redsea are installed and broadcast-FM tuning has been verified:

```bash
python3 bridge/pluto_bridge.py \
  --uri ip:192.168.2.1 \
  --readsb-path "$HOME/readsb/readsb" \
  --redsea-path "$HOME/redsea/build/redsea" \
  --fm-allow-extended \
  --verbose
```

A successful startup logs the Pluto setup, followed by something like:

```text
INFO Serving 0.0.0.0:7350; simulate=False
INFO COSMOS connected from ('127.0.0.1', ...)
```

The second line occurs **after** COSMOS connects. Leave the WSL2 bridge terminal running while using COSMOS.

For **spectrum-only operation**, you can omit `--readsb-path`, `--redsea-path`, and `--fm-allow-extended`:

```bash
python3 bridge/pluto_bridge.py --uri ip:192.168.2.1 --verbose
```

The bridge does not require you to launch GNU Radio, `readsb`, `redsea`, or `pacat` manually; it starts the relevant subprocesses as needed.

## Using the COSMOS screens

### SPECTRUM

1. Select a center frequency, span, sample rate, FFT length, gain, averaging, and RF bandwidth.
2. Choose **Apply settings** to configure the Pluto.
3. Watch the live spectrum, peak hold, and scrolling waterfall.
4. Use **Clear Peak Hold**, **Clear waterfall**, **Start**, or **Stop** as needed.

Default setup is approximately **915 MHz center**, **1.6 MHz span**, **2 MSPS**, **2048-point FFT**, **40 dB manual gain**, and **2 updates/s**. These settings can be changed from the screen.

### ADSB

1. Select **Start ADS-B reception**. The bridge stops spectrum capture, releases the Pluto, and starts `readsb` at **1090 MHz**.
2. Watch the aircraft table and regional map populate as messages arrive. Position reporting can lag behind initial identity decoding.
3. Set **Home lat**, **Home lon**, **Lat span°**, and **Lon span°**, then use **Apply map settings** for a different fixed geographic region.
4. Select **Clear tracks** to erase the accumulated map trails without changing the map center.
5. Select **Return to spectrum** to stop `readsb` and restore spectrum acquisition.

Map trails are in-memory and roll off after about 15 minutes; they also reset when ADS-B mode restarts. The regional display is a **lat/lon plot with reference labels**, not a street-map basemap or a certified navigation display.

### FM

1. Check that the Pluto can tune below 325 MHz (see [FM frequency extension](#plutosdr-broadcast-fm-frequency-extension)).
2. Select a strong broadcast station, **88–108 MHz**, with a suitable FM-band antenna.
3. Start with **Volume ~0.25–0.35** and moderate gain, then click **Tune & Play**.
4. Use **Apply FM settings** to retune or update gain/AGC/volume.
5. Use **Stereo 1** and **RDS 1** with **Apply audio/RDS options** to enable both. If the pilot is weak, audio falls back to mono; RDS may remain blank on a weak or non-RDS station.
6. Watch the **pilot-lock**, **RDS metadata**, and **L/R audio spectrum** telemetry. Windows handles speaker routing/volume.
7. Click **Stop FM / Spectrum** to stop the audio stream and restore the spectrum analyzer.

**Audio path:** `Pluto I/Q → FM MPX → stereo/mono PCM → pacat → WSLg → Windows speakers`. **RDS path:** `FM MPX → redsea → station metadata → COSMOS`.

## PlutoSDR broadcast-FM frequency extension

The standard PlutoSDR operating specification starts near **325 MHz**, above the 88–108 MHz FM broadcast band. A documented configuration can widen the *permitted tuning range* to approximately **70 MHz–6 GHz** on applicable hardware/firmware, but sensitivity, selectivity, and other RF specifications are **not guaranteed** outside the rated range.

### Verify first (read-only)

```bash
iio_info -u ip:192.168.2.1 | grep fw_version
iio_attr -u ip:192.168.2.1 -c ad9361-phy RX_LO frequency_available
```

An extended configuration commonly reports:

```text
[70000000 1 6000000000]
```

The original range commonly reports:

```text
[325000000 1 3800000000]
```

For the hardware used during this project, the firmware was **v0.32**. The following configuration was used after checking the boot environment via SSH and reviewing [Analog Devices' Pluto boot configuration documentation](https://wiki.analog.com/university/tools/pluto/devs/booting):

```bash
# On the Pluto, as root over SSH, and only after reviewing your hardware/firmware:
fw_printenv attr_name
fw_printenv attr_val
fw_printenv compatible

# For the documented single-channel AD9364 compatibility setting:
fw_setenv attr_name compatible
fw_setenv attr_val ad9364
fw_setenv compatible ad9364
reboot
```

**Caution:** These are persistent boot-environment changes, not a routine prerequisite for every Pluto. Before changing anything, back up existing settings, verify your hardware revision/firmware and receiver mode, and follow Analog Devices' guidance. Avoid applying another person's settings blindly. Do not use this procedure as proof of guaranteed RF performance. The Python flag `--fm-allow-extended` **does not enable the extension**; it only allows FM tuning in the bridge once the hardware has been verified.

After reboot, verify the `frequency_available` range above, then test actual tuning with the bridge stopped:

```bash
python3 - <<'PY'
import adi
sdr = adi.Pluto(uri='ip:192.168.2.1')
sdr.rx_lo = 99_500_000
print(f'FM tuning accepted: {sdr.rx_lo / 1e6:.3f} MHz')
PY
```

## Tests and simulation

From `pluto-cosmos-starter/` with your virtual environment active:

```bash
python3 -m unittest discover -s tests -v
```

**Release v0.7.0:** 28 automated tests pass. Coverage includes framed binary packets, FFT/waterfall, reconfiguration behavior, map data, simulated ADS-B switching, synthetic FM stereo/mono tests, RDS telemetry handling, and simulated COSMOS TCP flows. These are **not** full end-to-end RF-quality or calibration tests.

To exercise COSMOS screens **without a Pluto**:

```bash
python3 bridge/pluto_bridge.py --simulate --verbose
```

Simulation generates synthetic spectrum and fictitious aircraft/FM data. Do not interpret simulated aircraft entries or RDS text as live RF reception. Use a different interface/port if a live bridge is already occupying 7350.

Audio-only checks (no Pluto required):

```bash
python3 bridge/test_audio.py
python3 bridge/test_stereo_audio.py
```

## Configuration and telemetry

### Frequently used bridge arguments

| Argument | Purpose |
| --- | --- |
| `--uri ip:192.168.2.1` | Pluto libiio context URI |
| `--listen 0.0.0.0` / `--port 7350` | Bind address and COSMOS bridge port |
| `--simulate` | Synthetic spectrum, ADS-B, and FM; no hardware or speakers |
| `--readsb-path PATH` | Optional readsb executable, built with Pluto support |
| `--readsb-log PATH` | Decoder log (default `/tmp/pluto-cosmos-readsb.log`) |
| `--redsea-path PATH` | Optional RDS executable |
| `--fm-allow-extended` | Permit 88–108 MHz FM mode once Pluto tuning is verified |
| `--min-rf-mhz` / `--max-rf-mhz` | Validate spectrum tuning limits; change only if hardware range is verified |
| `--verbose` | Verbose bridge diagnostics |

### Protocol summary

The COSMOS plugin and Python bridge communicate using a **length-framed big-endian TCP protocol**; each packet begins with a **32-bit total length** and **16-bit packet ID**. `cmd_tlm/cmd.txt` and `cmd_tlm/tlm.txt` are the authoritative command/telemetry layouts.

| Telemetry packet | ID | Description |
| --- | ---: | --- |
| `SPECTRUM` | 1 | FFT bins, peak hold, frequencies, gain, RBW |
| `STATUS` | 2 | Bridge operation and errors |
| `WATERFALL` | 3 | Waterfall PNG and frequency bounds |
| `ADSB_TABLE` | 4 | Current aircraft state (12 visible slots) |
| `ADSB_EVENT` | 5 | Updated aircraft data |
| `ADSB_MAP` | 6 | PNG regional map, bounds, home location, track counts |
| `FM_STATUS` | 7 | FM tuning/audio/RF state |
| `FM_AUDIO_SPECTRUM` | 8 | Left/right audio FFT arrays |
| `FM_RDS` | 9 | Decoded PI, station name, program type, RadioText |
| `FM_DSP` | 10 | Stereo requested, pilot lock, RDS state |

| Command IDs | Function |
| --- | --- |
| `100–106` | Spectrum configuration, Start/Stop, Clear Hold, waterfall settings |
| `107–108` | Enter/exit ADS-B mode |
| `109–110` | Configure regional map / Clear Tracks |
| `111–113` | FM Tune & Play, Stop, update settings |
| `114` | Stereo/RDS options |

The bridge sends summaries and images; **raw high-rate I/Q and live speaker PCM are not COSMOS telemetry**. Telemetry storage volume and update rates should be considered before long unattended sessions.

## Troubleshooting

| Symptom | Likely cause / next check |
| --- | --- |
| `import adi` fails with `libiio version 1.x required, found version 0` | Python binding/native library mismatch. With a native libiio 0.x installation, use the pinned `pylibiio==0.25` from `bridge/requirements.txt`; don't upgrade one side without the other. |
| Pluto not reachable from WSL2 | Check USB virtual Ethernet, `ping -c 3 192.168.2.1`, then `iio_info -u ip:192.168.2.1`. |
| `Serving 0.0.0.0:7350` but no COSMOS telemetry | Confirm `PLUTO_SDR_INT` is connected and configured for `host.docker.internal:7350`. From Windows PowerShell, `Test-NetConnection localhost -Port 7350` checks Windows → WSL forwarding, not the entire Docker path. |
| **Broken pipe** after Apply Settings | Earlier bridge revisions over-reset the SDR receive buffer or used fragile socket handling. Use the current v0.7.0 bridge and inspect `--verbose` logs. |
| `readsb` exits `-11` (segmentation fault), `Context has 2 device(s)`, or *device unavailable* | Check `/tmp/pluto-cosmos-readsb.log`; confirm `IIOD_REMOTE` is passed to readsb by the current `adsb.py`, and avoid having Python and readsb hold the RX simultaneously. Test `iio_info` against the explicit IP. |
| Aircraft detected but no lat/lon | Normal until sufficient valid ADS-B position messages are decoded. Improve antenna and line of sight; allow more time. |
| Map doesn't update | Look for advancing `ADSB_MAP SEQ`; check the map `IMAGEVIEWER` and that the installed plugin matches the bridge version. |
| Pluto rejects FM frequency with `[Errno 22] Invalid argument` | Check `RX_LO frequency_available`. The standard 325 MHz minimum excludes FM; see the verified frequency-extension section. |
| `pacat missing` | `sudo apt install -y pulseaudio-utils` (not `pip install pacat`). |
| No audio / `pactl` fails | Check `$PULSE_SERVER`, `/mnt/wslg/PulseServer`, WSLg availability, Windows output selection, and `bridge/test_audio.py`. |
| Audio is noisy or stutters | Use a broadcast-FM antenna, try a strong local station, avoid RF overload, adjust gain/AGC, reduce system load, or disable stereo temporarily. |
| RDS fields blank | RDS may not be transmitted or decodable on that station; check `redsea` installation/path, `FM_RDS DECODER_STATE`, `/tmp/pluto-cosmos-redsea.log`, and signal quality. |
| Pilot lock 0 | Mono fallback is expected on mono stations or weak/noisy pilot reception. |

Useful logs:

```bash
tail -n 60 /tmp/pluto-cosmos-readsb.log
tail -n 60 /tmp/pluto-cosmos-fm-audio.log
tail -n 60 /tmp/pluto-cosmos-redsea.log
```

## Version history

| Version | Milestone |
| --- | --- |
| **0.1.x** | Initial COSMOS target, Pluto spectrum acquisition, tuning commands; native libiio compatibility and TCP/hardware-retune fixes |
| **0.2.0** | Native COSMOS waterfall, independent display span and RF bandwidth |
| **0.3.0 / 0.3.1** | ADS-B via `readsb`, aircraft table/events, explicit `IIOD_REMOTE` context fix |
| **0.4.0** | Aircraft positions, regional map image, track history |
| **0.5.0** | Configurable home station, fixed regional bounds, labels, Clear Tracks |
| **0.6.0** | Broadcast-FM mono demodulation and WSLg/Windows audio |
| **0.7.0** | Stereo/mono fallback, optional RDS through `redsea`, left/right audio FFT |

## Limitations and roadmap

**Current limitations**

- One Pluto RX resource at a time; not multiple concurrent radio modes.
- Relative power measurements, not an instrument-grade calibrated dBm/dBµV measurement.
- The ADS-B map uses generated geographic reference graphics; no live geographic basemap or aircraft database enrichment.
- Trails are kept in memory, not automatically persisted as a geospatial session archive.
- Real-time audio responsiveness can be affected by WSL2 processing and WSLg scheduling.
- Out-of-spec Pluto broadcast-FM reception is experimental even when the driver allows tuning.

**Possible improvements**: session-based aircraft logging, distance/bearing and range rings from the station, aircraft label styling, FFT cursors and occupancy statistics, station presets, RDS reliability monitoring, I/Q capture/playback, audio recording, automated COSMOS test procedures, and additional receive-only decoders.

## References

- [OpenC3 COSMOS](https://openc3.com/) — command, telemetry, scripts, and screens.
- [Analog Devices PlutoSDR documentation](https://wiki.analog.com/university/tools/pluto) and [boot-configuration reference](https://wiki.analog.com/university/tools/pluto/devs/booting).
- [pyadi-iio](https://analogdevicesinc.github.io/pyadi-iio/) and [libiio](https://github.com/analogdevicesinc/libiio).
- [wiedehopf/readsb](https://github.com/wiedehopf/readsb) — ADS-B decoder.
- [windytan/redsea](https://github.com/windytan/redsea) — RDS decoder.
- [Microsoft WSLg](https://github.com/microsoft/wslg) — Linux-to-Windows audio support.

**Third-party libraries, firmware, decoders, and tools have their own licenses.** No repository-wide license is implied by this README; add an appropriate project `LICENSE` file before inviting redistribution or contributions.
