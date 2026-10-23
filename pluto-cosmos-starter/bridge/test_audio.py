#!/usr/bin/env python3
"""Verify WSLg/PulseAudio can play to Windows speakers without using the Pluto."""
from __future__ import annotations
import math
import time
import numpy as np
from fm import WSLgAudio, FM_AUDIO_RATE

if __name__ == '__main__':
    print('Testing mono 48 kHz audio through WSLg → Windows speakers.')
    print('Set Windows speaker volume low before running this test.')
    t = np.arange(FM_AUDIO_RATE, dtype=np.float64) / FM_AUDIO_RATE
    tone = np.asarray(0.1 * np.sin(2 * math.pi * 440 * t) * 32767, dtype=np.int16)
    sink = WSLgAudio()
    try:
        sink.start()
        for block in np.array_split(tone, 10):
            sink.write(block)
            time.sleep(0.1)
        time.sleep(0.5)
        print('Test completed: did you hear a one-second 440 Hz tone?')
    finally:
        sink.stop()
