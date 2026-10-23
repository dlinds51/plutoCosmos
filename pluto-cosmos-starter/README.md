# PlutoSDR + OpenC3 COSMOS — v0.7.0

Version 0.7 adds **stereo FM playback, optional RDS station metadata, and an audio spectrum plot** to the existing working FM receiver, waterfall/spectrum analyzer, and ADS-B aircraft tracking screens.

All receiver controls and telemetry remain in **COSMOS Telemetry Viewer**. The WSL2 Python bridge demodulates the Pluto SDR's I/Q data; 48 kHz two-channel PCM audio is played through **WSLg's PulseAudio server**, which forwards playback to the default Windows audio output. COSMOS does **not** transport PCM and does **not** need a custom web interface.

## 1. Hardware requirement: FM broadcast is below Pluto's standard range

The stock PlutoSDR is rated for **325–3800 MHz**, so 88–108 MHz broadcast FM **does not work on an unmodified Pluto**. Analog Devices documents an extended-tuning configuration which may permit 70–6000 MHz, but its performance is not guaranteed outside the original rating.

Before attempting FM, stop the COSMOS bridge and test that the radio *actually accepts* an FM frequency:

```bash
python3 - <<'PY'
import adi
sdr = adi.Pluto(uri='ip:192.168.2.1')
sdr.rx_lo = 99_500_000
print('FM tuning accepted, RX LO =', sdr.rx_lo)
PY
```

If this fails with a tuning range error, the extension is not enabled; follow the official Analog Devices documentation for your exact Pluto hardware/firmware before modifying firmware settings. Do **not** run FM just by changing CLI frequency limits.

Official information:
- https://analogdevicesinc.github.io/system-level/solutions/platforms/pluto/
- https://wiki.analog.com/university/tools/pluto/devs/booting

## 2. Windows audio through WSLg

In your Ubuntu WSL2 terminal:

```bash
sudo apt update
sudo apt install -y pulseaudio-utils
python3 -m pip install -r bridge/requirements.txt

echo "PULSE_SERVER=$PULSE_SERVER"
ls -l /mnt/wslg/PulseServer
pactl info
```

The WSLg PulseAudio server should be reachable. If not, update WSL and check that WSLg GUI/audio support is enabled. WSLg's audio support is documented at https://github.com/microsoft/wslg .

Before connecting the SDR, validate audio through Windows speakers:

```bash
python3 bridge/test_audio.py
```

You should hear a **quiet 440 Hz tone** for one second. Windows output device and volume are selected in Windows, not COSMOS.

## 3. Install the updated bridge and plugin

1. Stop the old bridge with `Ctrl+C`.
2. Back up your known-good files, then replace `bridge/pluto_bridge.py` and `bridge/adsb.py` if needed. Add **`bridge/fm.py`** and `bridge/test_audio.py`.
3. Install the **`openc3-cosmos-plutosdr-0.7.0.gem`** COSMOS plugin through Admin > Plugins.
4. Copy `fm_stereo.py` and `rds_stream.py` alongside the updated bridge and FM files, then install dependencies in your existing virtual environment with `python3 -m pip install -r bridge/requirements.txt`.
5. Start the bridge:

```bash
python3 bridge/pluto_bridge.py \
  --uri ip:192.168.2.1 \
  --readsb-path "$HOME/readsb/readsb" \
  --redsea-path "$HOME/redsea/build/redsea" \
  --fm-allow-extended \
  --verbose
```

The optional `--redsea-path` argument selects the redsea binary. Omit it when using `redsea` from PATH or if you are testing audio-only without RDS.

The **`--fm-allow-extended`** flag is an explicit acknowledgement that your Pluto was verified to tune below 325 MHz. It does **not** modify the Pluto or enable the radio's extended frequency capability. If you only want to test COSMOS's FM commands without hardware/audio, use `--simulate` instead.

## 4. Operating COSMOS

Open **Telemetry Viewer > PLUTO_SDR > FM**.

- **Station (MHz)**: 88.0–108.0; select a real station you expect to receive.
- **Volume (0–1)**: software volume applied to demodulated mono PCM; start around 0.2–0.35.
- **Gain (dB)**: Pluto manual receiver gain; a value near 20–40 dB is a reasonable starting point, but watch saturation.
- **AGC**: enter 0 for manual gain or 1 for automatic gain.
- **Tune & Play** starts the FM receiver and Windows audio.
- **Apply FM settings** updates tuning, gain, AGC and volume without switching modes.
- **Stop FM / Spectrum** closes the speaker stream and restores the prior spectrum analyzer configuration.

The FM_STATUS telemetry packet reports mode, tuned frequency, volume, audio level, uncalibrated RF level, and processed I/Q buffers. FM_DSP reports pilot lock, FM_RDS reports station text, and FM_AUDIO_SPECTRUM reports left/right spectra. Audio does not pass through COSMOS. Spectrum/ADS-B/FM modes remain **mutually exclusive** on the single Pluto receiver.

If no sound, check the bridge's `ERROR` log, the COSMOS `STATUS MESSAGE`, `pactl info`, and `/tmp/pluto-cosmos-fm-audio.log`. The `test_audio.py` tone isolates audio routing problems from SDR/antenna or tuning problems.

## Processing and limitations

- **Receive-only**. Stereo demodulation and optional RDS are supported in 0.7; no station scan yet.
- Pluto I/Q at **1.2 MSPS**, complex anti-alias LPF and 5x downsample to **240 kSPS**, quadrature FM discriminator, pilot-synchronized 38 kHz difference-channel decoding (when pilot is present), 15 kHz audio low-pass and 5x decimation to **48 kHz stereo** with US **75 µs de-emphasis**.
- Continuous WSLg PulseAudio playback with `pacat --raw --format=s16le --rate=48000 --channels=2`.
- Real-time WSL2 USB forwarding and WSLg scheduling may still produce audio dropouts on some systems. Start with nearby strong stations and an FM-band antenna.
- The GUI *does not* play audio itself: audio is played by WSL2/Windows, not the browser.
- Hardware FM reception and speaker audio have **not been validated against your actual Pluto/Windows machine**. The test suite includes synthetic stereo/RDS telemetry and simulated socket tests; real stereo separation and RDS data still require verification on your own stations.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

---

## Version 0.7.0 — FM stereo, RDS and audio spectrum

**This new section supersedes the earlier 0.6.0 mono-FM processing description above.**
Version 0.7 retains the previously working spectrum analyzer, ADS-B map and FM receiver.
All displays, station tuning, volume, stereo/RDS options and telemetry remain inside COSMOS.
Only the speaker audio stays in WSLg/Windows.

**New capabilities**

- Stereo audio via coherent regeneration of the 38 kHz L−R subcarrier from the broadcast 19 kHz pilot. When no usable pilot exists, playback automatically falls back to dual mono. The output is always two-channel, 48 kHz PCM through `pacat`.
- RDS station details through optional `redsea` software in WSL2: station name (PS), program ID (PI), program type (PTY), and RadioText (RT). This is a receive-only decoder. It is *not* installed by pip.
- Two-channel audio spectrum inside COSMOS with native `ARRAYPLOT`. FFT bin indexes 0–255 cover about 0–12 kHz at 46.875 Hz/bin.
- New `FM_OPTIONS` command sets stereo and RDS on/off independently. The controls default to enabled.

### Install the Python update

Copy the following from this release's `bridge/` directory into your existing, working project's `bridge/` directory:

- **Replace:** `pluto_bridge.py`, `fm.py`
- **Add:** `fm_stereo.py`, `rds_stream.py`

The original `adsb.py`, spectrum screen, and map logic are unchanged.
Run `python3 -m pip install -r bridge/requirements.txt` in your existing `.venv` if its dependencies have not already been installed.

Install the **0.7.0 COSMOS gem**, which adds FM-specific telemetry packets 8 (`FM_AUDIO_SPECTRUM`), 9 (`FM_RDS`), and 10 (`FM_DSP`), plus command ID 114 (`FM_OPTIONS`). After upgrading, close/reopen the FM Telemetry Viewer screen.

### Verify stereo Windows speaker routing

Once your updated bridge dependencies are installed, run:

```bash
python3 bridge/test_stereo_audio.py
```

This plays a short, quiet left-channel tone followed by a different right-channel tone. No SDR hardware or COSMOS connection is required. The existing `test_audio.py` remains available for a mono check.

### Install redsea for RDS (optional)

**Stereo playback and the audio spectrum work without redsea.** To decode RDS as well:

```bash
sudo apt update
sudo apt install -y git build-essential pkg-config meson ninja-build libsndfile1-dev libliquid-dev
# Skip this clone if you already have ~/redsea
git clone https://github.com/windytan/redsea.git "$HOME/redsea"
meson setup "$HOME/redsea/build" "$HOME/redsea"
meson compile -C "$HOME/redsea/build"
"$HOME/redsea/build/redsea" --help
```

Build instructions: https://github.com/windytan/redsea . If the `meson` setup reports an unavailable library, follow that project's distribution-specific dependency instructions. This build has not been run on your WSL2 instance.

### Launch the updated bridge

```bash
python3 bridge/pluto_bridge.py \
  --uri ip:192.168.2.1 \
  --readsb-path "$HOME/readsb/readsb" \
  --redsea-path "$HOME/redsea/build/redsea" \
  --fm-allow-extended \
  --verbose
```

`--redsea-path` is optional; if omitted, the bridge looks for `redsea` on `PATH`. If it is missing, `FM_RDS DECODER_STATE` reports `REDSEA NOT INSTALLED` and FM audio continues normally.

On the **FM** COSMOS screen, tune a strong FM station as before. Set Stereo 1 and RDS 1 and click **Apply audio/RDS options**. `PILOT_LOCKED` should become 1 on stations carrying a strong 19 kHz stereo pilot, and `FM_RDS` fields will populate when the station's RDS broadcasts have been decoded. Allow several seconds or more for RDS to acquire synchronization and complete the text message; weak stations may transmit no decodable text.

**Audio path:** Pluto I/Q 1.2 MSPS → FM composite 240 kSPS → (19 kHz pilot lock + 38 kHz L/R recovery) → 48 kHz two-channel 75 µs de-emphasized PCM → WSLg PulseAudio → Windows default speakers. In parallel, the 240 kSPS *pre-de-emphasis MPX* is passed to redsea for RDS; not the 48 kHz audio. COSMOS receives only low-rate status, audio FFT, and text data.

**Testing and limitations:** Synthetic DSP tests verify stereo separation and mono fallback, and simulated COSMOS socket tests cover the new commands and packet types. Real RDS decoding and stereo performance still require verification with your Pluto and radio signals. Relative audio levels are not calibrated. `redsea` runs in a separate subprocess and may report no data on stations with weak or absent RDS. If the audio stutters, try a lower WSL2 load or switch Stereo to 0; stereo decoding consumes extra CPU. Receiver modes remain mutually exclusive.
