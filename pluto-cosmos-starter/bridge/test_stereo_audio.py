#!/usr/bin/env python3
"""Quick WSLg speaker routing check: left tone, then right tone (no Pluto)."""
import numpy as np
from fm import WSLgAudio, FM_AUDIO_RATE

print('Testing Windows stereo speaker routing: LEFT first, then RIGHT.')
print('Turn Windows speaker volume low before running this test.')
sink=WSLgAudio(channels=2)
try:
    sink.start()
    for channel, hz in ((0,440),(1,660)):
        print('LEFT speaker' if channel==0 else 'RIGHT speaker',flush=True)
        t=np.arange(FM_AUDIO_RATE,dtype=np.float64)/FM_AUDIO_RATE
        fade=np.minimum(1.0,np.minimum(t,1-t)*12)
        pcm=np.zeros((FM_AUDIO_RATE,2),dtype=np.int16)
        pcm[:,channel]=np.asarray(.10*fade*np.sin(2*np.pi*hz*t)*32767,dtype=np.int16)
        for piece in np.array_split(pcm,10):
            sink.write(piece)
finally:
    sink.stop()
print('Stereo test complete.')
