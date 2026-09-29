"""Generate simple retro sound effects as .wav files for Air Assault.
Run once: python generate_sounds.py
Produces assets/sfx/shoot.wav, explosion.wav, powerup.wav, hit.wav, combo_break.wav, menu_select.wav
"""
import struct
import math
import random
import os

SAMPLE_RATE = 22050

def write_wav(filename, samples):
    """Write a list of float samples (-1..1) as a 16-bit mono WAV."""
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    n = len(samples)
    data = b""
    for s in samples:
        clamped = max(-1.0, min(1.0, s))
        data += struct.pack("<h", int(clamped * 32767))
    with open(filename, "wb") as f:
        # WAV header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + len(data)))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))          # chunk size
        f.write(struct.pack("<H", 1))           # PCM
        f.write(struct.pack("<H", 1))           # mono
        f.write(struct.pack("<I", SAMPLE_RATE)) # sample rate
        f.write(struct.pack("<I", SAMPLE_RATE * 2))  # byte rate
        f.write(struct.pack("<H", 2))           # block align
        f.write(struct.pack("<H", 16))          # bits per sample
        f.write(b"data")
        f.write(struct.pack("<I", len(data)))
        f.write(data)
    print(f"  Created {filename} ({n} samples, {n/SAMPLE_RATE:.2f}s)")


def generate_shoot():
    """Short laser zap — descending pitch sine wave."""
    duration = 0.12
    n = int(SAMPLE_RATE * duration)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        freq = 1800 - (t / duration) * 1200   # 1800Hz -> 600Hz
        envelope = 1.0 - (t / duration)        # linear fade out
        s = math.sin(2 * math.pi * freq * t) * envelope * 0.5
        samples.append(s)
    return samples


def generate_explosion():
    """Chunky explosion — low noise burst with decay."""
    duration = 0.35
    n = int(SAMPLE_RATE * duration)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        envelope = max(0, 1.0 - (t / duration) ** 0.6) * 0.7
        noise = random.uniform(-1, 1)
        # Mix noise with a low rumble
        rumble = math.sin(2 * math.pi * 80 * t)
        s = (noise * 0.6 + rumble * 0.4) * envelope
        samples.append(s)
    return samples


def generate_powerup():
    """Ascending sparkle — quick rising arpeggio."""
    duration = 0.25
    n = int(SAMPLE_RATE * duration)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        freq = 600 + (t / duration) * 1200    # 600Hz -> 1800Hz
        envelope = 1.0 - (t / duration) ** 2
        s = math.sin(2 * math.pi * freq * t) * envelope * 0.4
        # Add harmonic shimmer
        s += math.sin(2 * math.pi * freq * 2 * t) * envelope * 0.15
        samples.append(s)
    return samples


def generate_hit():
    """Player hit — sharp noise click with short decay."""
    duration = 0.15
    n = int(SAMPLE_RATE * duration)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        envelope = max(0, 1.0 - (t / duration) ** 0.3) * 0.6
        noise = random.uniform(-1, 1)
        tone = math.sin(2 * math.pi * 200 * t)
        s = (noise * 0.7 + tone * 0.3) * envelope
        samples.append(s)
    return samples


def generate_combo_break():
    """Descending sad tone when combo is lost."""
    duration = 0.3
    n = int(SAMPLE_RATE * duration)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        freq = 500 - (t / duration) * 300     # 500Hz -> 200Hz
        envelope = 1.0 - (t / duration)
        s = math.sin(2 * math.pi * freq * t) * envelope * 0.35
        s += math.sin(2 * math.pi * freq * 0.5 * t) * envelope * 0.15
        samples.append(s)
    return samples


def generate_menu_select():
    """Short click/boop for menu navigation."""
    duration = 0.06
    n = int(SAMPLE_RATE * duration)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        envelope = 1.0 - (t / duration)
        s = math.sin(2 * math.pi * 800 * t) * envelope * 0.3
        samples.append(s)
    return samples


if __name__ == "__main__":
    print("Generating Air Assault sound effects...")
    write_wav("assets/sfx/shoot.wav", generate_shoot())
    write_wav("assets/sfx/explosion.wav", generate_explosion())
    write_wav("assets/sfx/powerup.wav", generate_powerup())
    write_wav("assets/sfx/hit.wav", generate_hit())
    write_wav("assets/sfx/combo_break.wav", generate_combo_break())
    write_wav("assets/sfx/menu_select.wav", generate_menu_select())
    print("Done! All sound files saved to assets/sfx/")
