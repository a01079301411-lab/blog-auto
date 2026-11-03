import numpy as np, wave, sys
import json as _json
SR = 44100
# 길이는 plan.json 장면 합계를 따른다 (기본 15초)
DUR = sum(d for _, d in _json.load(open(sys.argv[2]))['plan']) if len(sys.argv) > 2 else 15.0
N = int(SR * DUR)
rng = np.random.default_rng(7)

def env(n, a=0.005, d=0.2):
    t = np.arange(n) / SR
    e = np.minimum(1, t / a) * np.exp(-t / d)
    return e

def add(buf, sig, t0, gain=1.0):
    i = int(t0 * SR)
    if i >= len(buf): return
    s = sig[:len(buf) - i]
    buf[i:i + len(s)] += s * gain

def kick():
    n = int(0.35 * SR); t = np.arange(n) / SR
    f = 50 + 110 * np.exp(-t * 30)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * env(n, 0.002, 0.12)

def clap():
    n = int(0.25 * SR)
    noise = rng.standard_normal(n)
    # simple bandpass via difference of moving averages
    k1 = np.convolve(noise, np.ones(4) / 4, 'same'); k2 = np.convolve(noise, np.ones(40) / 40, 'same')
    return (k1 - k2) * env(n, 0.002, 0.07)

def hat():
    n = int(0.08 * SR)
    noise = rng.standard_normal(n)
    hp = noise - np.convolve(noise, np.ones(6) / 6, 'same')
    return hp * env(n, 0.001, 0.025)

def tone(freq, length, a=0.01, d=0.5, harm=(1, .5, .25)):
    n = int(length * SR); t = np.arange(n) / SR
    s = sum(h * np.sin(2 * np.pi * freq * (i + 1) * t) for i, h in enumerate(harm))
    return s * env(n, a, d)

def pop(f0=900):
    n = int(0.12 * SR); t = np.arange(n) / SR
    f = f0 * (1 + 1.2 * np.exp(-t * 60))
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.001, 0.04)

def whoosh():
    n = int(0.35 * SR); t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    out = np.zeros(n); y = 0.0
    a = 0.02 + 0.25 * np.sin(np.pi * t / t[-1])
    for i in range(n):
        y += a[i] * (noise[i] - y); out[i] = y
    return out * np.sin(np.pi * t / t[-1]) ** 2

def ding():
    return tone(1568, 0.8, 0.002, 0.25, (1, .3, .15)) + tone(2093, 0.8, 0.002, 0.2, (0.5,))

def tick():
    return pop(1800) * 0.5

music = np.zeros(N); sfx = np.zeros(N)
bpm = 118; beat = 60 / bpm
# chords (C - Am - F - G) as soft pads + bass
chords = [[261.6, 329.6, 392.0], [220.0, 261.6, 329.6], [174.6, 220.0, 261.6], [196.0, 246.9, 293.7]]
bass = [65.4, 55.0, 87.3, 98.0]
b = 0; t = 0.0
while t < DUR:
    bar = int(b // 4) % 4
    if b % 4 == 0:
        for f in chords[bar]:
            add(music, tone(f, beat * 4, 0.08, 1.4, (1, .2)), t, 0.06)
    add(music, tone(bass[bar], beat * 0.9, 0.005, 0.25, (1, .3)), t, 0.22)
    add(music, kick(), t, 0.55 if b % 2 == 0 else 0.0)
    if b % 2 == 1: add(music, clap(), t, 0.22)
    add(music, hat(), t + beat / 2, 0.10)
    add(music, hat(), t, 0.06)
    b += 1; t += beat

# SFX timeline from plan
import json
plan=json.load(open(sys.argv[2]))['plan'] if len(sys.argv)>2 else [['cover',2.5],['math',4.0],['usp',5.0],['offer',3.5]]
t0=0.0
for name,dur in plan:
    if t0>0: add(sfx, whoosh(), t0-0.12, 0.35)
    if name=='cover':
        add(sfx,pop(700),0.0,0.45); add(sfx,pop(1000),0.15,0.4)
    elif name=='math':
        add(sfx,pop(800),t0+0.05,0.4); add(sfx,pop(950),t0+0.25,0.3)
        for k in range(10): add(sfx,tick(),t0+0.55+k*0.105,0.5)
        add(sfx,ding(),t0+1.65,0.35)
    elif name=='usp':
        add(sfx,pop(800),t0+0.05,0.4)
        for i in range(3): add(sfx,pop(1000),t0+0.4+i*0.5,0.4); add(sfx,ding()*0.4,t0+0.52+i*0.5,0.25)
    elif name=='quiz_opts':
        add(sfx,pop(800),t0+0.05,0.4)
        for i in range(3): add(sfx,pop(1000),t0+0.35+i*0.3,0.4)
        k=t0+1.2
        while k<t0+dur-0.05: add(sfx,tick(),k,0.7); k+=0.5
    elif name=='quiz_reveal':
        for i in range(3): add(sfx,pop(1200),t0+0.25+i*0.4,0.4)
        add(sfx,ding(),t0+1.7,0.4); add(sfx,pop(600),t0+1.85,0.5)
    elif name.startswith('reason'):
        add(sfx,pop(700),t0,0.45); add(sfx,pop(1000),t0+0.2,0.35); add(sfx,ding()*0.6,t0+0.45,0.3)
    elif name=='offer':
        add(sfx,pop(700),t0+0.05,0.4); add(sfx,ding(),t0+0.55,0.35); add(sfx,pop(1100),t0+1.05,0.4)
    t0+=dur

mix = music + sfx
# fade in/out
fi = int(0.05 * SR); fo = int(0.6 * SR)
mix[:fi] *= np.linspace(0, 1, fi); mix[-fo:] *= np.linspace(1, 0, fo)
mix = np.tanh(mix * 1.1)
mix = mix / np.max(np.abs(mix)) * 0.89
st = np.stack([mix, mix], 1)
pcm = (st * 32767).astype(np.int16)
with wave.open(sys.argv[1], 'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
