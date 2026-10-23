# PlutoSDR + OpenC3 COSMOS — Phase 1 Starter (v0.1)

An initial, receive-only **PLUTO_SDR COSMOS target** with a WSL2 Python SDR bridge and a native COSMOS Spectrum screen.

**Status:** source code and binary framing unit-tested in a simulated source. Not hardware-tested on your PlutoSDR or installed in your particular COSMOS release; treat it as a **starter implementation**, not a turnkey certified plugin.

## What works in this version

- COSMOS `PLUTO_SDR` commands for configure, start, stop, clear peak hold.
- Spectrum telemetry: 512 relative-power bins plus 512 peak-hold bins, sent over one length-framed TCP session.
- Native COSMOS `ARRAYPLOT` screen with editable center MHz, span MHz, sample rate MSPS, FFT size, gain, averaging, AGC and updates per second.
- Python service runs either a **synthetic** two-tone RF demo or actual ADALM-PLUTO via `pyadi-iio` / libiio.
- Automatic spectrum metadata: left and right frequency, center, max peak frequency and dBFS level, FFT resolution bandwidth.
- Receive only: no Pluto TX code.

**Current plot limitation:** `ARRAYPLOT` plots bin **indices 0–511**, not absolute MHz, because its X-axis setting is static. COSMOS shows actual **left and right MHz** and **peak MHz** alongside the plot. A subsequent custom Vue widget can show a calibrated, live MHz x-axis, waterfall, pan/zoom and cursors.

## Folder structure

```
bridge/pluto_bridge.py                   WSL2 SDR acquisition/FFT and TCP server
bridge/requirements.txt                 WSL2 Python dependencies
cosmos-plugin/plugin.txt                Target and TCP/IP client interface
cosmos-plugin/openc3-cosmos-plutosdr.gemspec
cosmos-plugin/targets/PLUTO_SDR/cmd_tlm/{cmd,tlm}.txt
cosmos-plugin/targets/PLUTO_SDR/screens/spectrum.txt
tests/test_bridge.py                    Offline tests for framing and FFT
```

## Step 1: WSL2 dependencies and connectivity

In Ubuntu on WSL2:

```bash
sudo apt update
sudo apt install -y python3-venv libiio-utils libiio0
cd /path/to/pluto-cosmos-starter
python3 -m venv .venv
source .venv/bin/activate
pip install -r bridge/requirements.txt
```

`libiio` package names differ between Ubuntu releases. If packages are missing, install libiio using Analog Devices' current distribution guidance for that Ubuntu release, then retry. Test whether the **Windows USB virtual-Ethernet Pluto interface** is visible from WSL2:

```bash
ping -c 3 192.168.2.1
iio_info -u ip:192.168.2.1
python3 -c 'import adi; s=adi.Pluto(uri="ip:192.168.2.1"); print(s.rx_lo)'
```

Pluto normally appears to Windows as a USB composite device with a virtual-Ethernet interface at `192.168.2.1` (factory default). **Prefer IP/libiio from WSL2 rather than first attempting USB device passthrough with `usbipd-win`**. Linux guest routes to host virtual adapters vary across WSL versions; `ping`/`iio_info` should be tested rather than assumed.

### Run with no hardware first

```bash
python3 bridge/pluto_bridge.py --simulate
```

The demo creates simulated signals at **+125 kHz** and **−300 kHz** relative to the configured center frequency. Moving the center changes the frequency labels of the synthetic demo peaks, without requiring a receiver.

### Run with physical Pluto

```bash
python3 bridge/pluto_bridge.py --uri ip:192.168.2.1
```

The defaults are 915 MHz center, 1.6 MHz displayed span, 2 MSPS, 2048 FFT, gain 40 dB manual, 8 averages, 2 display updates/s. Connect an antenna suited to the band. These settings only enable RX.

**Important**: the standard PlutoSDR is officially rated for **325–3800 MHz**. Standard broadcast FM **88–108 MHz cannot be assumed to work**. Only if you have individually verified a frequency-extension modification should you start with `--min-rf-mhz 70 --max-rf-mhz 6000`. The flags *only relax this bridge's validation*; they do **not** alter Pluto hardware/firmware capability.

## Step 2: Build and load the COSMOS plugin

From the `cosmos-plugin` directory, in any shell with RubyGems installed:

```bash
cd cosmos-plugin
gem build openc3-cosmos-plutosdr.gemspec
```

This produces `openc3-cosmos-plutosdr-0.1.0.gem`. In COSMOS, open **Admin → Plugins** and upload the resulting `.gem`. In **Command and Telemetry Server**, enable/connect the `PLUTO_SDR_INT` interface. Then open **Telemetry Viewer → PLUTO_SDR → spectrum**.

COSMOS uses a `tcpip_client_interface.py` directed at `host.docker.internal:7350`; the bridge runs as a TCP server in WSL2. COSMOS connects to it and commands share the same TCP session used by telemetry. The 32-bit big-endian length at the start of every packet provides framing.

**Network check**: On Windows PowerShell, while bridge is listening in WSL:

```powershell
Test-NetConnection -ComputerName localhost -Port 7350
```

If this fails, address WSL2 host port forwarding/firewall first. If Windows can connect but COSMOS cannot, inspect the interface connection error and whether `host.docker.internal` resolves inside the COSMOS Docker network. With some WSL2 networking configurations you may need to change the hostname/IP in `plugin.txt`, rebuild and reinstall the gem.

## Step 3: Use the spectrum screen

1. With the bridge running and `PLUTO_SDR_INT` connected, open `spectrum`.
2. Confirm the bridge status says `SIMULATION` or `PLUTO CONNECTED` and the spectrum `SEQ` increases.
3. Edit values and click **Apply settings**. Span must not exceed sample rate.
4. Use Start/Stop to control collection; Clear Peak Hold resets accumulated peaks.
5. Read LEFT_MHZ and RIGHT_MHZ as the absolute frequency of bins 0 and 511. Peak frequency is labeled in MHz. The FFT bin resolution is `sample_rate / fft_size`; a narrower *display* span does not improve intrinsic FFT resolution.

### Common problems

- **No packets:** check `PLUTO_SDR_INT` connected, WSL listener port 7350, and Windows `Test-NetConnection`.
- **Pluto unreachable:** investigate WSL route to the USB Ethernet adapter; `iio_info` should work before the bridge does.
- **`ERROR: Span ...`:** use a display span no wider than sampling rate.
- **`ERROR: Center frequency`:** use supported Pluto range or *verified* frequency-extension configuration.
- **Flat/odd spectrum:** check antenna/band, AGC, front-end saturation, gain, Pluto's DC spur at zero IF, sample-rate/filter settings. Relative dBFS is not calibrated absolute received power.
- **High data rate / slow updates:** start with 2 MSPS, 2048 FFT, 2 updates/s; avoid assuming the max hardware sample rate can be streamed sustainably over its USB/network interface.
- **COSMOS screen errors:** screen widgets and parser behavior may differ between releases. Start with the simplest array plot and inspect COSMOS logs for a syntax error.

## Decoder roadmap (not implemented by this v0.1 starter)

**Phase 2 — ADS-B**: `readsb` has PlutoSDR support when built with `PLUTOSDR=yes`, tuned to 1090 MHz. Use its native decoder and consume JSON aircraft-state snapshots or SBS text in a *separate* adapter that publishes a well-defined `AIRCRAFT` COSMOS telemetry packet. Retain ICAO ID (`hex`), callsign (`flight`) when broadcast, altitude, lat/lon when CPR position is resolved, speed/heading, timestamp, number of messages. Avoid falsely displaying latitude/longitude as zero when unknown; expose validity flags. Initially make ADS-B and spectrum mode mutually exclusive to avoid two independent processes opening the same Pluto receive stream.

**Phase 3 — Broadcast WFM**: only with a verified extended Pluto, or another supported VHF-capable SDR, tune to FM broadcast. GNU Radio's Pluto source → channel filter → WFM receiver → resample → audio sink is the easy route; COSMOS should send tuning commands and show radio settings/status. Demodulation and audio playback should stay outside COSMOS telemetry. GNU Radio under WSLg may play through the Windows audio device, depending on your audio setup.

**Phase 4 — custom spectrum widget**: native `ARRAYPLOT` is an expedient proof of concept. A custom OpenC3 Vue widget would give correct frequency tick labels, peak marker, mouse cursors, waterfall, persistence, and optimized graph updates.

## Validation

Run offline unit tests with:

```bash
python3 -m unittest discover -s tests -v
```

Tests cover frame sizes/type IDs, command frame assembly, partial TCP frame handling, simulated signal peak location, and invalid spectrum configurations. **They do not substitute for integration testing on actual OpenC3 or Pluto hardware.**
