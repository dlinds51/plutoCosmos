# Roadmap and engineering backlog

> **Status:** Ideas and recommendations, **not promised features**. As of v0.7.0, the Spectrum, ADS-B and FM modules are functional. This document separates proposed work from functionality that is already implemented. Update priorities after each iteration.

## Next priorities

| Priority | Proposed enhancement | Why it matters | Suggested acceptance test |
| --- | --- | --- | --- |
| P0 | Harden FM continuity and telemetry backpressure | Streaming PCM is timing-sensitive; PNG and status traffic must not stall audio | Play ≥30 min and switch modes repeatedly without underrun/hang; report glitches if any |
| P0 | Make dependency/environment checks reproducible | WSL2 native libraries, `pacat`, `readsb` and `redsea` have caused setup friction | A diagnostic check reports version/path/availability with actionable errors, does not change firmware |
| P1 | Per-mode state/error telemetry and a unified COSMOS landing screen | Make station state unmistakable after mode changes and reconnections | Viewer clearly indicates exactly one active mode; no stale statuses |
| P1 | RF/audio quality instrumentation | Help decide whether poor reception comes from antenna, gain, DSP or audio routing | Display useful signal/noise or lock indicators and audio underrun stats |
| P1 | User settings persist between bridge restarts | Editable map region and preferred stations currently start from code defaults | Restart app and reload known configuration without exposing credentials or presumed home address |
| P1 | FM station presets and station-scan workflow | Faster tuning to local stations while staying in COSMOS | Tune preset and return to prior station via commands; don't scan during ADS-B |
| P2 | ADS-B aircraft distance and bearing from reference station | More actionable map/aircraft data | Geodesic output tested against reference coordinates and proper units |
| P2 | Aircraft track export / operational session recording | Analyze reception and coverage over time | Save timestamped CSV/GeoJSON with reproducible data and no invented positions |
| P2 | Improved ADS-B map labels, range rings and selection | More usable situation display | Aircraft call signs/altitude readable, zoom/range consistent, labels avoid severe overlap |
| P2 | FM RDS reliability work / UI polish | Decoder output varies with station strength | Live PI/PS/PTY/RT observed where available; quiet stations remain valid |
| P3 | IQ record/replay and deterministic offline DSP tests | Debug regressions without an antenna or SDR | Save playback with metadata and compare decoded outputs across versions |
| P3 | Calibrated RF readout (with procedure) | Relative dBFS is not a measurement instrument | Calibration table and uncertainty notes verified with reference signal |
| P3 | Additional receive-only signal modes | Experiment with NOAA weather radio, other legal signals | Feature added as isolated mode with automated cleanup and existing modes passing |

## Design constraints / non-goals

- Keep **COSMOS as the sole controls-and-telemetry UI**; avoid a separate SDR browser dashboard unless the requirement changes.
- Keep high-rate I/Q and PCM local to WSL2; COSMOS carries display and status telemetry.
- Preserve **one active Pluto receiver owner at a time** unless adding an explicitly designed shared-RX subsystem or more radios.
- Don't silently retune outside hardware's verified permissible range.
- ADS-B is a hobby situational display, not a certified air-traffic system.
- Avoid claiming dBm, noise figure, EVM, RF signal quality or transmitter compliance without calibration and test evidence.

## Suggested next session

1. Choose one feature above, with acceptance criteria before modifying source.
2. Reproduce v0.7.0 baseline via unit tests and a quick COSMOS mode-switch smoke test.
3. Implement a small patch; add at least one regression test that failed before the change.
4. Rebuild the plugin if commands/telemetry/screens changed; test actual hardware and record anything unverified.
5. Update `CHANGELOG.md`, this file and relevant docs; commit/tag with a version.

This roadmap is intentionally editable. Completed entries should be moved to `CHANGELOG.md` rather than left as pending.
