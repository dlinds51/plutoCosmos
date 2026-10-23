import importlib.util
import pathlib
import struct
import unittest

import numpy as np

MOD = pathlib.Path(__file__).resolve().parents[1] / 'bridge' / 'pluto_bridge.py'
spec = importlib.util.spec_from_file_location('pluto_bridge', MOD)
mod = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

class ProtocolTests(unittest.TestCase):
    def test_frame_structure(self):
        c = mod.Config()
        a = np.arange(mod.BINS, dtype=np.float32)
        frame = mod.make_spectrum_frame(c, 3, a, a, 915_125_000, -25, 2000)
        self.assertEqual(len(frame), mod.SPECTRUM_SIZE)
        self.assertEqual(len(frame), struct.unpack_from('>I', frame)[0])
        self.assertEqual(struct.unpack_from('>H', frame, 4)[0], 1)
        self.assertEqual(struct.unpack_from('>I', frame, 6)[0], 3)
        self.assertAlmostEqual(struct.unpack_from('>f', frame, 10)[0], 915)
    def test_config_protocol(self):
        frame = struct.pack(mod.CONFIG_FMT, mod.CONFIG_SIZE, 100, 915_000_000,
                            1_600_000, 2_000_000, 2048, 40.0, 8.0, 0, 2)
        self.assertEqual(len(frame), 36)
        buf = bytearray(frame[:5])
        self.assertEqual(mod.decode_frames(buf), [])
        buf.extend(frame[5:])
        frames = mod.decode_frames(buf)
        self.assertEqual(frames, [(100, frame)])
        self.assertEqual(buf, bytearray())
    def test_spectrum_peak(self):
        c = mod.Config()
        source = mod.InputSource('none', True)
        iq = source.receive(c)
        v, peak_hz, peak_dbfs, rbw = mod.calculate_spectrum(iq, c)
        self.assertEqual(len(v), 512)
        self.assertAlmostEqual(peak_hz, 915_125_000, delta=8_000)
        self.assertAlmostEqual(rbw, 2e6/2048, places=2)
        self.assertTrue(np.isfinite(v).all())
    def test_validation(self):
        c = mod.Config(span_hz=3e6)
        with self.assertRaises(ValueError):
            c.validate(325, 3800)

if __name__ == '__main__':
    unittest.main()
