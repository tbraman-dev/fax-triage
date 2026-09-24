"""Soundtrack for the promo: 120 BPM, A minor (Am F C G), cuts land on the beat.
Filtered intro, drop on the title at 6.5s, breakdown for the outro. Writes audio.wav."""
import numpy as np, wave

SR = 44100; D = 43.0; N = int(SR * D); BEAT = .5; BAR = 2.0
rng = np.random.default_rng(3)
music = np.zeros((N, 2)); drums = np.zeros((N, 2)); sfx = np.zeros((N, 2))

def add(bus, sig, t, g=1.0, pan=0.0):
    i = int(t * SR)
    if i >= N: return
    j = min(N, i + len(sig)); s = sig[:j - i] * g
    bus[i:j, 0] += s * min(1, 1 - pan); bus[i:j, 1] += s * min(1, 1 + pan)

def T(dur): return np.arange(int(SR * dur)) / SR

def saw(f, dur, fc, voices=(-0.09, 0, 0.09)):
    """Detuned additive saw, harmonics rolled off above fc (a soft lowpass)."""
    t = T(dur); s = np.zeros_like(t)
    for v in voices:
        fv = f * 2 ** (v / 12)
        for k in range(1, 16):
            if k * fv > 12000: break
            s += np.sin(2 * np.pi * k * fv * t + rng.random() * 6.28) / k / (1 + (k * fv / fc) ** 4)
    return s / len(voices)

def pluck(f, dur=.35, bright=1.0):
    t = T(dur); s = np.zeros_like(t)
    for k in range(1, 9):
        s += np.sin(2 * np.pi * k * f * t) / k * np.exp(-t * (4 + k * 6 / bright))
    return s * np.minimum(1, t / .002)

def bell(f, dur=.6):
    t = T(dur)
    return (np.sin(2 * np.pi * f * t) + .35 * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t * 8)) * np.exp(-t * 5) * np.minimum(1, t / .003)

CH = {'Am': [220, 261.6, 329.6, 440], 'F': [174.6, 220, 261.6, 349.2],
      'C': [196, 261.6, 329.6, 392], 'G': [196, 246.9, 293.7, 392]}
ROOT = {'Am': 55, 'F': 43.65, 'C': 65.41, 'G': 49}
PROG = ['Am', 'F', 'C', 'G']

# ---- pads: filter opens through the intro, drops in at the title, breaks down for the outro
pad = np.zeros((N, 2))
for b in range(int(D / BAR) + 1):
    t0 = b * BAR; ch = PROG[b % 4]
    if t0 < 6.5:   fc, g = 500 + 1500 * (t0 / 6.5) ** 2, .55
    elif t0 < 37.5: fc, g = 2600, .5
    else:          fc, g = 1400, .6
    for i, f in enumerate(CH[ch]):
        s = saw(f, BAR + .4, fc)
        e = np.minimum(1, T(BAR + .4) / .08) * np.minimum(1, (BAR + .4 - T(BAR + .4)) / .35)
        add(pad, s * e, t0, g * .22, pan=(i - 1.5) * .35)

# ---- sub bass: offbeat-pumping eighths under the groove
bass = np.zeros((N, 2))
for b in range(int(D / BAR) + 1):
    t0 = b * BAR; r = ROOT[PROG[b % 4]]
    if 6.5 <= t0 < 37.5:
        for k in range(8):
            t = T(.24); s = np.sin(2 * np.pi * r * t) + .25 * np.sin(4 * np.pi * r * t)
            add(bass, s * np.minimum(1, t / .01) * np.exp(-t * 6), t0 + k * .25 + (.125 if k % 2 == 0 else 0), .5)

# ---- 16th-note arpeggio over chord tones, an octave up
arp = np.zeros((N, 2))
pattern = [0, 2, 1, 3, 2, 1, 3, 2]
for b in range(int(D / BAR) + 1):
    t0 = b * BAR; ch = CH[PROG[b % 4]]
    if t0 >= 39.5: break
    for k in range(16):
        t = t0 + k * .125
        f = ch[pattern[k % 8]] * 2
        vel = .9 if k % 4 == 0 else .55
        bright = .6 + .8 * min(1, t / 6.5)
        add(arp, pluck(f, .3, bright), t, vel * .16, pan=.35 if k % 2 else -.35)

# ---- a short bell hook on the scan and routing sections
hook = [(0, 659.3), (.75, 587.3), (1.0, 523.3), (1.5, 440), (2.5, 523.3), (3.0, 587.3), (3.5, 659.3)]
for start in (10.5, 14.5, 20.5, 24.5):
    for dt, f in hook: add(music, bell(f), start + dt, .12, pan=.1)

# ---- drums
def kick():
    t = T(.35); f = 48 + 110 * np.exp(-t * 35)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9) + .15 * np.sin(2 * np.pi * 1800 * t) * np.exp(-t * 300)
def clap():
    n = int(SR * .2); x = rng.standard_normal(n); x = np.diff(x, prepend=0)
    e = sum(np.r_[np.zeros(int(o * SR)), np.exp(-T(.2 - o) / (.01 if k < 2 else .06))][:n] for k, o in enumerate((0, .01, .02)))
    return x * e * .3
def hat(open_=False):
    n = int(SR * (.18 if open_ else .05)); x = np.diff(rng.standard_normal(n), 2, prepend=[0, 0])
    return x * np.exp(-T(n / SR) / (.05 if open_ else .012)) * .12
def riser(dur):
    t = T(dur); x = np.diff(rng.standard_normal(len(t)), prepend=0)
    return x * (t / dur) ** 3 * .25
def impact():
    t = T(1.6); f = 38 + 60 * np.exp(-t * 12)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 2.2) * .9

for t in (0, 1.0, 1.5, 2.0, 2.5): add(drums, kick(), t, .8)
add(drums, impact(), 0, .6); add(drums, impact(), 1.5, .5)
for k in range(6): add(drums, kick(), 3.5 + k * .5, .45)
add(drums, riser(1.0), 5.5, 1.0)
for k in range(8): add(drums, clap(), 6.0 + k * .0625, .15 + k * .06)
add(drums, impact(), 6.5, .9)

side = np.ones(N)  # sidechain gain for pads/arp/bass
t = 6.5
while t < 37.49:
    add(drums, kick(), t, .9)
    add(drums, hat(open_=True), t + .25, 1.0, pan=.2)
    add(drums, hat(), t + .125, .6, pan=-.3); add(drums, hat(), t + .375, .6, pan=-.3)
    beat = round((t - 6.5) / BEAT)
    if beat % 2 == 1 and t > 9.4: add(drums, clap(), t, 1.0)
    i = int(t * SR); m = min(N, i + int(.3 * SR))
    side[i:m] = np.minimum(side[i:m], 1 - .65 * np.exp(-T((m - i) / SR) / .09))
    t += BEAT
for k in range(3): add(drums, impact(), 32.6 + k * .5, .35)
add(drums, impact(), 37.5, .7); add(drums, riser(.8), 39.1, .8); add(drums, impact(), 39.9, 1.0)

# final chord ring-out
for i, f in enumerate([110, 220, 261.6, 329.6, 440, 659.3]):
    s = saw(f, 3.1, 1800); add(music, s * np.exp(-T(3.1) * 1.1) * np.minimum(1, T(3.1) / .01), 39.9, .16, pan=(i - 2.5) * .25)

# ---- light UI sfx: soft pentatonic blips for extracted fields and landed faxes
PENTA = [880, 987.8, 1174.7, 1318.5, 1568, 1760]
for i, bt in enumerate([12.0, 12.45, 12.9, 13.35, 13.8, 14.25]): add(sfx, bell(PENTA[i], .3), bt, .09)
for i in range(17): add(sfx, bell(PENTA[i % 6] / 2, .2), 20.7 + i * .27 + .42, .05, pan=(i % 3 - 1) * .4)
def whoosh(dur=.45):
    x = np.diff(rng.standard_normal(int(SR * dur)), prepend=0); y = np.convolve(x, np.ones(12) / 12, 'same')
    return y * np.sin(np.pi * np.linspace(0, 1, len(y))) ** 2 * .5
for tt in (9.25, 19.25, 26.25, 32.25): add(sfx, whoosh(), tt, .35)

# ---- reverb on the melodic stuff
def reverb(x, secs=2.2, wet=.28):
    n = int(SR * secs); ir = rng.standard_normal((n, 2)) * np.exp(-T(secs) / (secs / 5))[:, None]
    L = 1 << int(np.ceil(np.log2(len(x) + n)))
    y = np.fft.irfft(np.fft.rfft(x, L, axis=0) * np.fft.rfft(ir, L, axis=0), L, axis=0)[:len(x)]
    y /= np.max(np.abs(y)) + 1e-9; return x + wet * y * np.max(np.abs(x))

mel = (pad + arp + bass) * side[:, None] + music
mel = reverb(mel)
out = mel + drums + reverb(sfx, 1.2, .2)
out = np.tanh(out * .9)
out /= np.max(np.abs(out)) * 1.1
fade = int(SR * .8); out[-fade:] *= np.linspace(1, 0, fade)[:, None]
w = wave.open('audio.wav', 'wb'); w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
w.writeframes((out * 32767).astype(np.int16).tobytes()); w.close()
print('wrote audio.wav')
