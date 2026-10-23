# PlutoSDR + COSMOS Starter v0.5.0

Adds a more useful ADS-B regional map inside the native COSMOS ADSB screen:

- configurable **home station marker**
- default home coordinates of **39.079046981923796, -104.86428665378747**
- **fixed regional map** centered on home instead of auto-zooming
- simple labeled regional reference points when visible
- **Clear Tracks** button
- configurable fixed **latitude span** and **longitude span**

## Upgrade notes

1. Replace `bridge/pluto_bridge.py` and `bridge/adsb.py`.
2. Upgrade the COSMOS plugin to `openc3-cosmos-plutosdr-0.5.0.gem`.
3. Install the one new Python dependency in your active virtual environment:

```bash
python3 -m pip install Pillow
```

Or install/update all bridge dependencies:

```bash
python3 -m pip install -r bridge/requirements.txt
```

4. Restart the bridge as usual:

```bash
python3 bridge/pluto_bridge.py --uri ip:192.168.2.1 --readsb-path "$HOME/readsb/readsb" --verbose
```

## ADS-B map controls

The ADSB screen now provides fields for:

- Home latitude
- Home longitude
- Latitude span (degrees)
- Longitude span (degrees)

Use **Apply map settings** to update the fixed regional view. Use **Clear tracks** to erase accumulated aircraft trails while keeping the map settings.

## Notes

- The map remains entirely inside COSMOS using `IMAGEVIEWER`.
- The map packet is still telemetry type 6 (`PLUTO_SDR ADSB_MAP`).
- Aircraft tracks are retained for about 15 minutes unless cleared.
- Restarting ADS-B mode clears track history but keeps the configured map region.

# PlutoSDR + COSMOS Starter v0.4.0

Adds an ADS-B map image inside the native COSMOS ADSB screen. The bridge now keeps a short track history per aircraft, renders a simple lat/lon map as PNG telemetry, and shows it with the built-in IMAGEVIEWER. The existing spectrum analyzer, waterfall, ADS-B table, and IIOD_REMOTE/readsb fix are retained.

## Upgrade notes

- Replace `bridge/pluto_bridge.py` and `bridge/adsb.py`.
- Upgrade the COSMOS plugin to the included `openc3-cosmos-plutosdr-0.4.0.gem`.
- Keep launching the bridge exactly as before: `python3 bridge/pluto_bridge.py --uri ip:192.168.2.1 --readsb-path "$HOME/readsb/readsb" --verbose`
- Start ADS-B mode in COSMOS. A map should appear above the aircraft table as soon as at least one aircraft position is available.

## Map behavior

- The map auto-zooms to the retained aircraft track history.
- Track history is retained for about 15 minutes and resets when ADS-B mode is restarted.
- The map is a simple lat/lon plotting surface, not a tiled street/satellite basemap.
- Bounds and track statistics are shown under the image.

## Notes

- This version still keeps everything inside COSMOS; no external web UI is required.
- The map uses telemetry packet type 6 (`PLUTO_SDR ADSB_MAP`).

---

# PlutoSDR + OpenC3 COSMOS — Spectrum, Waterfall, ADS-B (bridge hotfix v0.3.1)

This starter adds a **1090 MHz ADS-B receiver screen inside COSMOS Telemetry Viewer** to the working v0.2 spectrum analyzer and waterfall. The PlutoSDR stays receive-only. In ADS-B mode, the well-established `readsb` decoder takes ownership of the Pluto and generates `aircraft.json` in a temporary local directory. The Python bridge reads that JSON and sends small, structured binary telemetry packets to COSMOS. **No external aircraft-tracking dashboard is needed.**

**Important:** v0.3 has been tested with simulated SDR/aircraft data, not against your physical Pluto + locally compiled `readsb`. Retain a backup of your functioning v0.2 installation.

## v0.3.1 WSL2 readsb segmentation-fault workaround

The previous v0.3.0 ADS-B bridge launched readsb with `--pluto-network` but did not explicitly set libiio's default context. `readsb` currently calls `iio_create_default_context()` **before** applying its specific network option. On systems where a local IIO context is created, this can cause its Pluto driver to access devices/channels that are not present.

The updated `bridge/adsb.py` sets **`IIOD_REMOTE=ip:192.168.2.1` in readsb's subprocess environment**, leaving your main Python bridge and virtual environment unchanged. This is a plausible workaround, *not yet verified against your hardware*. COSMOS plugin version remains **v0.3.0**; do **not** reinstall the gem. Replace `bridge/adsb.py` only and restart the bridge.

If readsb still crashes, the most useful diagnostic is its existing log:

```bash
tail -n 80 /tmp/pluto-cosmos-readsb.log
ldd ~/readsb/readsb | grep -Ei 'libiio|libad9361'
```

To isolate readsb with no bridge controlling the SDR, stop the bridge with Ctrl+C and run:

```bash
IIOD_REMOTE=ip:192.168.2.1 ~/readsb/readsb \
  --device-type plutosdr --pluto-network 192.168.2.1 \
  --no-interactive --auto-exit 15
```

If it still segfaults, capture a debugger backtrace (requires `sudo apt install gdb`):

```bash
IIOD_REMOTE=ip:192.168.2.1 gdb -q -batch -ex run -ex 'thread apply all bt 12' --args \
  ~/readsb/readsb --device-type plutosdr --pluto-network 192.168.2.1 \
  --no-interactive --auto-exit 15
```

This tests a decoder binary, not aircraft signal reception. It is perfectly normal for the aircraft list to remain empty during the test.

---

## 1. Update your working v0.2 installation

1. In WSL2 press `Ctrl+C` to stop the current Python bridge; leave COSMOS/Docker running.
2. Back up your v0.2 `bridge/pluto_bridge.py` and the v0.2 plugin `.gem`.
3. Copy **both** new files into your existing project's `bridge/` directory: **`pluto_bridge.py` and `adsb.py`**. The extra module is mandatory. You can instead extract and run the complete v0.3 ZIP as a new project. Keep your already functioning Python virtual environment (the Python dependencies are unchanged).
4. In **COSMOS Admin → Plugins**, upgrade to `cosmos-plugin/openc3-cosmos-plutosdr-0.3.0.gem`. If plugin version conflicts occur, remove the previous Pluto plugin before uploading v0.3 (this may briefly disconnect the target). Reconnect the existing `PLUTO_SDR_INT` interface if needed.
5. Open the new **PLUTO_SDR → ADSB** screen in **Telemetry Viewer**. The **SPECTRUM** screen remains available and is unchanged.

## 2. Build a Pluto-enabled readsb in WSL2

The `readsb` program is a separate decoder. It **must be built with Pluto support**; many prebuilt packages support only RTL-SDR. The upstream build instructions use `make PLUTOSDR=yes`. The following is a straightforward source build for Ubuntu under WSL2 (requires network access and Ubuntu dev packages):

```bash
sudo apt update
sudo apt install -y git build-essential pkg-config \
    libiio-dev libad9361-dev libusb-1.0-0-dev \
    libncurses-dev zlib1g-dev libzstd-dev

git clone --depth 1 https://github.com/wiedehopf/readsb.git ~/readsb
make -C ~/readsb -j"$(nproc)" PLUTOSDR=yes

# Must list "ADALM-Pluto SDR options" or equivalent:
~/readsb/readsb --help | grep -A7 -i 'pluto'
```

If you already have `~/readsb`, don't clone it again; check its version/build options first. The build uses your WSL2-installed libiio and libad9361 libraries; `pylibiio==0.25` continues to support the older libiio Python setup for the spectrum bridge. Compiling readsb requires development headers as well as the native runtime libs. **Do not start a separate long-running readsb process**: the bridge launches and stops it automatically when COSMOS switches modes.

Optional standalone readsb test (stop bridge first so readsb alone owns the Pluto):

```bash
mkdir -p /tmp/adsb-test
~/readsb/readsb --device-type plutosdr --pluto-network 192.168.2.1 \
    --write-json /tmp/adsb-test --write-json-every 1
# In another terminal: cat /tmp/adsb-test/aircraft.json
# Stop the standalone decoder with Ctrl+C before restarting the bridge.
```

## 3. Start the updated bridge

```bash
# From your existing Pluto COSMOS project folder, with .venv activated:
python3 bridge/pluto_bridge.py \
    --uri ip:192.168.2.1 \
    --readsb-path "$HOME/readsb/readsb" \
    --verbose
```

Then open the **ADSB** COSMOS telemetry screen. Click **Start ADS-B reception**. The bridge will stop the spectrum receive buffer, launch `readsb`, and forward decoded aircraft to COSMOS approximately once per second. Spectrum telemetry stops during ADS-B. Return via **Return to spectrum**; it will terminate readsb, re-open the Python Pluto context, restore your prior spectrum settings, and resume FFT/waterfall reception. The spectrum screen's **Start** button also switches back to spectrum mode.

Normal log flow:

```text
INFO ADS-B started: ... --device-type plutosdr --pluto-network 192.168.2.1 ...
INFO ADSB STARTING 1090 MHZ
...
INFO ADS-B decoder stopped
INFO SDR: rx_lo=...  # prior spectrum LO restored
INFO SPECTRUM RESTORED
```

### What the ADS-B screen displays

- Up to **12 most recently heard aircraft** with **ICAO/hex**, callsign (`flight`), barometric altitude **ft**, latitude/longitude **decimal degrees**, ground speed **kt**, course/track **degrees**, last message age **seconds**, and message count. The header reports the number of aircraft heard recently, including aircraft beyond the 12 visible rows, plus the readsb message counter.
- Blank/unavailable fields are displayed as `-`; `GROUND` is different from altitude zero. A callsign, location, or speed may not be available for every detected Mode S aircraft. Position often requires a suitable antenna and multiple valid messages.
- The separate **ADSB_EVENT** packet is emitted when readsb reports a change to an aircraft's message count. COSMOS logs these as structured telemetry independently from the 1 Hz snapshot **ADSB_TABLE** packet. Events are *updates to decoded aircraft state*, not guaranteed one-to-one copies of each raw ADS-B frame.
- **No location is inferred or fabricated** for real aircraft.

Important antenna advice: the Pluto receive frequency is **1090 MHz** in ADS-B mode regardless of the spectrum screen's last frequency. Reception is much better with a 1090 MHz antenna, a clear outdoor view, and optionally a 1090 MHz bandpass filter/LNA. A generic 915 MHz antenna may pick up nearby aircraft but has uncertain 1090 MHz sensitivity. The RF gain controls in SPECTRUM are not ADS-B gain controls; readsb configures its own receiver parameters.

## 4. Test without Pluto or readsb

You can fully exercise the mode-switch protocol without installing readsb:

```bash
python3 bridge/pluto_bridge.py --simulate --verbose
```

The ADSB screen will show **SIMULATED AIRCRAFT - NOT LIVE** and fictional callsigns `DEMO101` and `DEMO202`. These are intentionally not real aircraft. Click **Return to spectrum** to resume the simulated spectrum and waterfall.

## 5. Troubleshooting

- **`readsb not found`**: pass `--readsb-path "$HOME/readsb/readsb"` and confirm the executable exists.
- **readsb exits immediately after Start ADS-B**: review `/tmp/pluto-cosmos-readsb.log`, which collects its stderr/stdout. Confirm `~/readsb/readsb --help` includes Pluto support and that `ip:192.168.2.1` is reachable. Check that no other application owns the Pluto.
- **WAITING FOR ADS-B DATA**: decoder has started but hasn't produced its first JSON snapshot. If this persists over 15 seconds, check the process log. An empty aircraft table **with a LIVE 1090 MHZ decoder state** means readsb is producing data, but no fresh aircraft have been decoded.
- **Broken pipe or libiio `-104`**: another process or a USB virtual Ethernet interruption may have broken the Pluto context. Stop readsb, restart the bridge, and confirm the independent `adi.Pluto(...).rx()` test works.
- **COSMOS screen remains blank**: ensure both Python files are v0.3, the plugin is v0.3, and `PLUTO_SDR_INT` is connected. Check `ADSB_TABLE` packet receipt in Packet Viewer. Use `--simulate` to verify the COSMOS path before debugging receiver/antenna issues.
- **Aircraft table cuts off horizontally**: COSMOS's native screen uses nine `VALUE` fields across; resize the Telemetry Viewer window or scroll horizontally as needed. No custom web widgets are installed.

## 6. Test and packet protocol

```bash
python3 -m unittest discover -s tests -v
```

- Spectrum commands (`CONFIG` 100, START 101, STOP 102, CLEAR_HOLD 103, CONFIG_V2 104), waterfall commands (105/106), and spectrum/status/waterfall telemetry packet layouts (1/2/3) are **unchanged**.
- ADSB_START 107 and ADSB_STOP 108 are 6-byte commands: `uint32 big-endian total length=6`, `uint16 command ID`.
- ADSB_TABLE telemetry ID 4 is a fixed length, big-endian packet: header (length, type, seq, UTC Unix seconds, aircraft count, total messages, 32-character decoder state), then 12 slots of fixed-width ASCII field values.
- ADSB_EVENT telemetry ID 5 is a fixed length packet: length, type, seq, one aircraft row. Field widths and `APPEND_ITEM` layouts are defined in `bridge/adsb.py` and COSMOS `targets/PLUTO_SDR/cmd_tlm/tlm.txt`.
- Original COSMOS `SPECTRUM` screen and its waterfall are preserved. ADS-B is **receive only**. COSMOS receives decoded telemetry, not high-rate raw I/Q.

## Roadmap

The next additions could be optional antenna configuration, logging/CSV export, aircraft position map within COSMOS, and FM demodulation (subject to Pluto's verified hardware receive band). The spectrum bridge still uses the previously validated retune and sample-rate reconfiguration path.
