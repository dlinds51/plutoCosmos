# PlutoCOSMOS — New-session handoff

> **Last documented baseline:** v0.7.0, 2026-10-23. This is a convenience index, not a replacement for checking the latest GitHub commit.

## Where to start

**Repository:** <https://github.com/dlinds51/plutoCosmos>

Read these files in order:

1. `README.md` — goals, installation, user controls, firmware notes.
2. `DEVELOPMENT.md` — architecture, mode ownership, engineering pitfalls.
3. `docs/PROTOCOL.md` — all command and telemetry IDs plus framing.
4. `CHANGELOG.md` — delivered milestones; `ROADMAP.md` — not-yet-built ideas.
5. Current source under `pluto-cosmos-starter/bridge/` and the plugin `cmd_tlm/` + `screens/` definitions.

### Environment at the successful baseline

- ADALM-PLUTO at **`ip:192.168.2.1`** from Ubuntu/WSL2.
- Pluto firmware **v0.32** with the frequency extension applied and verified as `[70000000 1 6000000000]` at the time of testing.
- Windows / Docker Desktop / OpenC3 COSMOS interface `PLUTO_SDR_INT` uses `host.docker.internal:7350`.
- Python virtual environment uses native libiio 0.x with **`pylibiio==0.25`**.
- `readsb` is a separately built Pluto-capable binary at `$HOME/readsb/readsb`; its child environment must set `IIOD_REMOTE` to the actual Pluto URI.
- `pacat` from `pulseaudio-utils` plays Windows audio through WSLg. Optional `redsea` at `$HOME/redsea/build/redsea` for RDS.
- Three radio modes functional: Spectrum (FFT/waterfall); ADS-B (aircraft data/map/tracks); FM (audio, stereo DSP, optional RDS and audio FFT).
- User-selected default map marker **39.079046981923796, -104.86428665378747** is a **representative location**, not the user's residence.
- The reviewed v0.7.0 local package has **28 passing Python unit tests**; the hardware integration has been demonstrated by the operator. Treat optional real-world RDS metadata reception as not independently established unless a later log confirms it.

### Launch

From `pluto-cosmos-starter/`:

```bash
python3 bridge/pluto_bridge.py \
  --uri ip:192.168.2.1 \
  --readsb-path "$HOME/readsb/readsb" \
  --redsea-path "$HOME/redsea/build/redsea" \
  --fm-allow-extended \
  --verbose
```

### Baseline tests

```bash
python3 -m unittest discover -s tests -v
python3 bridge/pluto_bridge.py --simulate --verbose
python3 bridge/test_audio.py
python3 bridge/test_stereo_audio.py
```

Don't run the second bridge on 7350 concurrently with the live bridge. Stop a running bridge before directly acquiring Pluto I/Q for a standalone test.

## What broke before, so don't regress it

- libiio bindings 1.x / native library 0.x mismatch → pin compatible versions (`pylibiio==0.25` in requirements).
- LO-only Apply Settings caused broken pipes when every configuration restarted the SDR buffer → avoid RX buffer restart for frequency-only tuning.
- `readsb` segfaulted from wrong libiio default context → spawn with `IIOD_REMOTE=ip:<device>`.
- ADS-B and Python cannot both own the Pluto receiver; cleanly release/restore when changing mode.
- FM 88–108 MHz was initially rejected by the factory firmware range → hardware-specific extension was verified; application flag alone never changes hardware range.
- `pacat` is installed via `sudo apt install pulseaudio-utils`, not pip.
- High-rate audio should not be routed through COSMOS; send only visual/status telemetry.

## Ready-to-paste continuation request

> Please continue the PlutoSDR + OpenC3 COSMOS project at https://github.com/dlinds51/plutoCosmos. Start by reading README.md, DEVELOPMENT.md, CHANGELOG.md, ROADMAP.md, docs/PROTOCOL.md and docs/HANDOFF.md, then inspect the current bridge/plugin files and tests. My last known working baseline was v0.7.0 (all three modes: spectrum, ADS-B map, and stereo FM). Treat the repository's latest code as authoritative and preserve working receiver modes and COSMOS screens. I want to implement **[describe new feature/bug]**. Please provide a minimal patch, tests, an updated GEM if needed, and specific installation instructions.

## Before ending the next development session

Update this document's baseline version, test count/status, any new pitfalls and next action. Keep full historical detail in the changelog and DEVELOPMENT.md; this file should remain short and easy to read.
