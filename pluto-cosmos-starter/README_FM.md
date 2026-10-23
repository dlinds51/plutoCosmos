# PlutoSDR + OpenC3 COSMOS — v0.6.0

Version 0.6 adds **broadcast FM mono demodulation and Windows speaker playback** to the existing spectrum analyzer, waterfall, and ADS-B aircraft tracking screens.

All receiver controls and telemetry remain in **COSMOS Telemetry Viewer**. The WSL2 Python bridge demodulates the Pluto SDR's I/Q data; mono PCM audio is played through **WSLg's PulseAudio server**, which forwards playback to the default Windows audio output. COSMOS does **not** transport PCM and does **not** need a custom web interface.

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
3. Install the **`openc3-cosmos-plutosdr-0.6.0.gem`** COSMOS plugin through Admin > Plugins.
4. Install dependencies in your existing virtual environment with `python3 -m pip install -r bridge/requirements.txt`.
5. Start the bridge:

```bash
python3 bridge/pluto_bridge.py \
  --uri ip:192.168.2.1 \
  --readsb-path "$HOME/readsb/readsb" \
  --fm-allow-extended \
  --verbose
```

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

The FM_STATUS telemetry packet reports mode, tuned frequency, volume, audio level, uncalibrated RF level, and processed I/Q buffers. Audio does not pass through COSMOS. Spectrum/ADS-B/FM modes remain **mutually exclusive** on the single Pluto receiver.

If no sound, check the bridge's `ERROR` log, the COSMOS `STATUS MESSAGE`, `pactl info`, and `/tmp/pluto-cosmos-fm-audio.log`. The `test_audio.py` tone isolates audio routing problems from SDR/antenna or tuning problems.

## Processing and limitations

- **Receive-only**; mono WFM; no stereo separation, RDS, or station scan yet.
- Pluto I/Q at **1.2 MSPS**, complex anti-alias LPF and 5x downsample to **240 kSPS**, quadrature FM discriminator, 15 kHz audio low-pass and 5x decimation to **48 kHz mono** with US **75 µs de-emphasis**.
- Continuous WSLg PulseAudio playback with `pacat --raw --format=s16le --rate=48000 --channels=1`.
- Real-time WSL2 USB forwarding and WSLg scheduling may still produce audio dropouts on some systems. Start with nearby strong stations and an FM-band antenna.
- The GUI *does not* play audio itself: audio is played by WSL2/Windows, not the browser.


## Tests

```bash
python3 -m unittest discover -s tests -v
```
