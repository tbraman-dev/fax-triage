import numpy as np, wave
SR=44100; D=43.0; N=int(SR*D); out=np.zeros((N,2))
rng=np.random.default_rng(1)
def add(sig,t,g=1.0,pan=0.0):
    i=int(t*SR); j=min(N,i+len(sig))
    if i>=N: return
    s=sig[:j-i]*g; out[i:j,0]+=s*(1-max(0,pan)); out[i:j,1]+=s*(1+min(0,pan))
def env(n,a,dcy): t=np.arange(n)/SR; return np.minimum(1,t/max(a,1e-4))*np.exp(-t/dcy)
def kick(big=False):
    n=int(SR*(0.9 if big else .45)); t=np.arange(n)/SR
    f=45+(160 if big else 120)*np.exp(-t*28); ph=2*np.pi*np.cumsum(f)/SR
    s=np.sin(ph)*np.exp(-t*(3.2 if big else 7.5)); s+= .25*rng.standard_normal(n)*np.exp(-t*120)
    return np.tanh(s*1.6)
def hat(): n=int(SR*.06); x=rng.standard_normal(n); x=np.diff(x,prepend=0); return x*env(n,.001,.018)*.35
def clap():
    n=int(SR*.25); x=rng.standard_normal(n); x=x-np.convolve(x,np.ones(8)/8,'same')
    e=np.zeros(n); 
    for k,o in enumerate([0,.011,.022]): i=int(o*SR); e[i:]+=np.exp(-np.arange(n-i)/SR/(.012 if k<2 else .09))
    return x*e*.5
def tick(f=2400): n=int(SR*.05); t=np.arange(n)/SR; return np.sin(2*np.pi*f*t)*env(n,.001,.012)*.35
def whoosh(dur=.5,rev=False):
    n=int(SR*dur); x=rng.standard_normal(n); t=np.linspace(0,1,n)
    # sweep lowpass via moving filter
    y=np.zeros(n); a=0
    for i in range(0,n,256):
        c=(.02+.5*(t[i] if not rev else 1-t[i])**2); seg=x[i:i+256]
        for k in range(len(seg)): a+=c*(seg[k]-a); y[i+k]=a
    e=np.sin(np.pi*t)**2 if not rev else t**3
    return y*e*1.2
def bass(f,dur):
    n=int(SR*dur); t=np.arange(n)/SR
    s=np.sign(np.sin(2*np.pi*f*t))*.3+np.sin(2*np.pi*f*t)
    # lowpass
    s=np.convolve(s,np.ones(40)/40,'same'); return s*env(n,.005,dur*.5)*.35
def riser(dur):
    n=int(SR*dur); t=np.arange(n)/SR; f=200*2**(t/dur*3); ph=2*np.pi*np.cumsum(f)/SR
    return (np.sin(ph)*.2+rng.standard_normal(n)*.12*(t/dur))*(t/dur)**2
def stab(freqs,dur=.35):
    n=int(SR*dur); t=np.arange(n)/SR; s=sum(np.sin(2*np.pi*f*t)+.3*np.sin(4*np.pi*f*t) for f in freqs)/len(freqs)
    return s*env(n,.003,.12)*.4
def impact():
    return kick(True)*1.0
B=.5
# A: hits on each word
for t in [0,1.0,1.5,2.0,2.5]: add(impact() if t in (0,1.5) else kick(),t,.9)
for t in [0,1.5,2.0]: add(stab([220,277,330]) ,t,.5)
add(whoosh(.5),3.1,.5)
# B: ticks per word, pulse kicks
for i in range(5): add(tick(1800+i*200),3.6+i*.25,.8)
for k in range(4): add(kick(),3.5+k*.5,.55)
add(riser(1.0),5.5,.9); add(impact(),5.5,.8)
for k in range(6): add(hat(),5.5+k*.166,.6)
# C onward: groove 120bpm from 6.5 to 37.5
add(impact(),6.5,1.0); add(stab([110,165,220,277]),6.5,.8)
for i in range(4): add(tick(1500),7.5+i*.5,.9)
t=6.5
while t<37.4:
    add(kick(),t,.85)
    add(hat(),t+.25,.7,pan=.3); add(hat(),t+.375,.25,pan=-.3)
    beat=round((t-6.5)/B)
    if beat%2==1 and t>9.5: add(clap(),t,.6)
    bar=int((t-6.5)//2)
    root=[55,55,41.2,49][bar%4]
    if t>9.5: add(bass(root,.22),t+.25,.9)
    t+=B
# D: extraction ticks
for bt in [12.0,12.45,12.9,13.35,13.8,14.25]: add(tick(2600),bt,.8); add(tick(3200),bt+.15,.4)
add(impact(),15.3,.7); add(stab([196,247,294]),15.3,.5)
for i in range(30): add(tick(3500),16.9+i*.04,.12)
# transitions
for tt in [9.3,19.2,26.2,32.2,37.2]: add(whoosh(.45),tt,.45)
# E: fax landing ticks
for i in range(17): add(tick(900+(i%6)*140),20.7+i*.27+.42,.7,pan=(i%3-1)*.4)
# F: row ticks
for i in range(17): add(tick(2000),27.0+i*.1,.3)
add(stab([220,277,330]),29.3,.4); add(stab([247,311,370]),30.5,.4)
# G stats
for i in range(3): add(impact(),32.6+i*.5,.6); add(stab([220*(1+i*.12),277*(1+i*.12)]),32.6+i*.5,.35)
# H outro
add(impact(),37.5,.9); add(kick(),38.0,.7); add(stab([165,220,277,330],1.5),38.0,.5)
add(riser(.8),39.1,.6); add(impact(),39.9,1.0)
n=int(SR*3); tt=np.arange(n)/SR; pad=sum(np.sin(2*np.pi*f*tt+.3*k) for k,f in enumerate([110,165,220,277,330]))/5
add(pad*np.minimum(1,tt/.05)*np.exp(-tt/1.2)*.4,39.9,1.0)
# master
out=np.tanh(out*1.1); out/=np.max(np.abs(out))*1.12
fade=int(SR*.6); out[-fade:]*=np.linspace(1,0,fade)[:,None]
w=wave.open('audio.wav','wb'); w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((out*32767).astype(np.int16).tobytes()); w.close()
print('ok')
