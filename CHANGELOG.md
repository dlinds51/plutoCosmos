# Changelog

All notable project milestones are recorded here for maintainers. The release entries below reconstruct the progression through v0.7.0 from the working packages and development history. They are **not** a claim that corresponding Git tags or GitHub Releases already exist.

The suggested convention for future changes is [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), with semantic versions for changes to the bridge/plugin pair.

## [Unreleased]

- No new code shipped by this documentation package.
- Future work and priorities: [ROADMAP.md](ROADMAP.md).

## [0.7.0] — 2026-10-23

### Added
- FM stereo pilot detection / L−R reconstruction with fallback to mono when lock is absent.
- Left/right audio spectrum telemetry and plotting inside the COSMOS FM screen.
- Optional `redsea` RDS decoding for PI, PS, program type and RadioText.
- COSMOS Stereo and RDS settings/status telemetry; bridge support for `--redsea-path`.

### Validation
- 28 local Python automated tests passed, including synthetic FM stereo, subprocess and simulated command/telemetry checks. Real RDS success is not independently guaranteed by those tests.

## [0.6.0] — 2026-10-23

### Added
- Third operating mode: broadcast FM reception/demodulation controlled from COSMOS.
- Audio output to Windows speakers through `pacat` / WSLg PulseAudio.
- FM tuning, gain, volume, AGC and audio/RF-level telemetry.
- FM speaker test utility and `--fm-allow-extended` opt-in flag.

### Integration notes
- Broadcast FM reception required the Pluto's driver to expose an extended frequency range; installation used firmware v0.32. The extension changes permitted tuning limits; it does not guarantee RF performance outside standard specifications.
- `pacat` is provided by Linux APT package `pulseaudio-utils`, not pip.

## [0.5.0] — 2026-10-23

### Added
- Configurable default map reference station and home marker.
- Fixed regional ADS-B map bounds with named reference points and lat/lon grid.
- COSMOS fields for home lat/lon and map spans; Clear Tracks command.

### Note
- The example home marker is **a representative location**, not a user's personal address.

## [0.4.0] — 2026-10-23

### Added
- Native COSMOS aircraft map display generated as PNG telemetry from decoded positions.
- Per-aircraft position trails, track retention and map telemetry.

## [0.3.1] — 2026-10-23

### Fixed
- `readsb` default libiio context selection under WSL2 by setting `IIOD_REMOTE=<Pluto URI>` in the spawned subprocess environment.
- Retained existing COSMOS plugin and ADS-B telemetry contracts.

## [0.3.0] — 2026-10-23

### Added
- ADS-B/Mode S receiver using external Pluto-enabled `readsb`.
- COSMOS aircraft table (12 visible slots) and individual aircraft events.
- Mutually exclusive ADS-B and spectrum receiver ownership with automated restoration of the prior spectrum configuration.

## [0.2.0] — 2026-10-22

### Added
- Native COSMOS scrolling waterfall via compact PNG telemetry and `IMAGEVIEWER`.
- Independent RF receive bandwidth versus plotted frequency span.

## [0.1.2] — 2026-10-22

### Fixed
- Frequency-only tuning no longer needlessly recreates the Pluto DMA buffer.
- Improved libiio connection/reconfiguration resilience following observed broken-pipe errors.

## [0.1.1] — 2026-10-22

### Fixed
- Pinned `pylibiio==0.25` to match native libiio 0.x installation.

## [0.1.0] — 2026-10-22

### Added
- Initial COSMOS Pluto target, TCP command/telemetry service and FFT/peak-hold spectrum.
- WSL2 Python I/Q bridge, simulation mode, basic screens and tuning controls.

---

For exact binary packet IDs and layouts, see [docs/PROTOCOL.md](docs/PROTOCOL.md). For changes not yet implemented, see [ROADMAP.md](ROADMAP.md).
