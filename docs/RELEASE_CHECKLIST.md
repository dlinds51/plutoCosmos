# PlutoCOSMOS — Development, test and release checklist

Use this checklist when changing `pluto-cosmos-starter/bridge/` or the COSMOS plugin. Keep source, plugin, tests and documentation at the **same version**.

## Before coding

- [ ] Pull latest Git branch; inspect `git status`, `git log --oneline -5`, and installed COSMOS GEM version.
- [ ] Read `README.md`, `DEVELOPMENT.md`, `docs/PROTOCOL.md` and `ROADMAP.md`.
- [ ] Name the change and write observable acceptance criteria.
- [ ] Identify which mode owns the Pluto at every stage and on every error path.
- [ ] Note expected changes to command/telemetry binary layouts, if any.

## During implementation

- [ ] Keep the change small; preserve Spectrum, ADS-B and FM behavior.
- [ ] Do not reinitialize RX DMA buffers for an LO-only tune.
- [ ] If adding/changing a packet, keep Python `struct` and COSMOS `cmd_tlm` definitions byte-for-byte compatible.
- [ ] Validate inputs (frequency bounds, sample rate, FFT size, coordinates and volumes) before hardware changes.
- [ ] Cleanly stop `readsb`, `redsea`, `pacat` and RX acquisition during transitions and failure recovery.
- [ ] Keep PCM and raw I/Q out of COSMOS telemetry; bound PNG size/rate and avoid blocking the FM audio path.
- [ ] If adding a receiver mode, add simulation behavior and tests for switching into and back out of it.

## Automated checks

From `pluto-cosmos-starter/`:

```bash
python3 -m unittest discover -s tests -v
python3 bridge/pluto_bridge.py --help
python3 bridge/pluto_bridge.py --simulate --verbose
```

- [ ] Full test suite passes; record **number, environment and result**.
- [ ] Simulated COSMOS TCP session parses length-framed commands and outputs expected packet types.
- [ ] New packet length equals `struct.calcsize(...)` + payload size; COSMOS array/string sizes match.
- [ ] New command with invalid settings yields readable status and doesn't wedge the bridge.
- [ ] Simulation is clearly identified as synthetic telemetry.
- [ ] No secrets, actual receiver address assumptions, core dumps, raw captures or virtual environments are being committed.

## Manual hardware and UI smoke test

Only run the steps relevant to the change, plus a quick pass through all three existing modes.

- [ ] `iio_info -u ip:192.168.2.1` connects to the Pluto.
- [ ] COSMOS `PLUTO_SDR_INT` connects to the running TCP bridge.
- [ ] Spectrum: graph/waterfall update; frequency-only retune works without broken pipe; sample-rate change recovers.
- [ ] ADS-B: Start/Stop mode works; receiver decoded messages/aircraft table/map update when signals exist; Clear Tracks works.
- [ ] FM: speaker test tone passes; broadcast audio plays; volume/retune/Stop controls work; stereo/mono fallback doesn't crash.
- [ ] Optional RDS: decoder launches when configured; blank metadata on non-RDS stations is not treated as a fatal error.
- [ ] Repeatedly switch Spectrum → ADS-B → Spectrum → FM → Spectrum and disconnect/reconnect COSMOS.
- [ ] Do a longer-duration run when modifying timing, threads, sockets, recording or status-rate code.

## Plugin packaging (when any COSMOS target/schema/screen changes)

```bash
cd pluto-cosmos-starter/cosmos-plugin
# Bump spec.version in openc3-cosmos-plutosdr.gemspec first.
gem build openc3-cosmos-plutosdr.gemspec
```

- [ ] Increment version in GEM specification and documentation.
- [ ] Confirm generated `.gem` filename/version and contents.
- [ ] Upload/update the COSMOS plugin; reconnect interface if necessary and reopen updated screen.
- [ ] Confirm no obsolete GEM is accidentally documented as current.
- [ ] If installed plugin conflicts with previous version, record the actual upgrade procedure rather than assuming it is always automatic.

## Commit and handoff

- [ ] Update `CHANGELOG.md` for shipped work and `ROADMAP.md` for remaining work.
- [ ] Update `DEVELOPMENT.md` / `docs/PROTOCOL.md` / `docs/HANDOFF.md` when integration knowledge changes.
- [ ] State what was tested in simulation and what was validated on real hardware.
- [ ] Commit with descriptive message and tag a verified release (optional but recommended).
- [ ] Check the public GitHub README/GEM refer to the same release.
- [ ] Preserve logs or measured results with sensitive content redacted.

See [DEVELOPMENT.md](../DEVELOPMENT.md) for the engineering rationale.
