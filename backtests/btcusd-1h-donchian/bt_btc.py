"""BTCUSD 1h Donchian-20 breakout with 4h EMA50 context. Simulation only. Rules: REGLAS.md."""
import json, sys, csv, datetime as dt
from zoneinfo import ZoneInfo
UTC=dt.timezone.utc; MAD=ZoneInfo('Europe/Madrid')
N_BRK, N_STOP, EMA_N, MAXH, COST = 20, 10, 50, 48, 0.001
src, out, now = sys.argv[1], sys.argv[2], int(sys.argv[3])
b=json.load(open(src))['bars']
T,O,H,L,C=b['t'],b['o'],b['h'],b['l'],b['c']
k=sum(1 for t in T if t+3600<=now); T,O,H,L,C=T[:k],O[:k],H[:k],L[:k],C[:k]   # closed bars only
# 4h candles from complete groups of 1h bars, aligned to UTC 00/04/...
h4={}
for i,t in enumerate(T): h4.setdefault(t-t%14400,[]).append(i)
h4=sorted((s,ix) for s,ix in h4.items() if len(ix)==4)
ema=None; ctx={}   # 4h close time -> (close, ema)
a=2/(EMA_N+1); n4=0
for s,ix in h4:
    c=C[ix[-1]]; ema=c if ema is None else a*c+(1-a)*ema; n4+=1
    if n4>=EMA_N: ctx[s+14400]=(c,ema)
def context(t_open):   # last 4h candle closed at or before this 1h bar opens
    end=t_open-t_open%14400
    return ctx.get(end)
trades=[]; busy={'L':-1,'S':-1}
for i in range(N_BRK, len(T)-1):
    cx=context(T[i])
    if not cx: continue
    hh=max(H[i-N_BRK:i]); ll=min(L[i-N_BRK:i])
    for side in ('L','S'):
        if i<=busy[side]: continue
        if side=='L' and not (cx[0]>cx[1] and C[i]>hh): continue
        if side=='S' and not (cx[0]<cx[1] and C[i]<ll): continue
        sc=C[i]
        if side=='L': stop=min(L[i-N_STOP+1:i+1]); tgt=sc+2*(sc-stop)
        else:         stop=max(H[i-N_STOP+1:i+1]); tgt=sc-2*(stop-sc)
        e=i+1; entry=O[e]; res=px=None; j=e
        for j in range(e, min(e+MAXH, len(T))):
            up = side=='L'
            if j>e and (O[j]<=stop if up else O[j]>=stop): res,px='stop (hueco)',O[j]; break
            if j>e and (O[j]>=tgt if up else O[j]<=tgt): res,px='objetivo (hueco)',O[j]; break
            if j==e and (entry<=stop if up else entry>=stop): res,px='stop (hueco)',entry; break
            hs = L[j]<=stop if up else H[j]>=stop
            ht = H[j]>=tgt if up else L[j]<=tgt
            if hs and ht: res='indeterminado'; break
            if hs: res,px='stop',stop; break
            if ht: res,px='objetivo',tgt; break
        else:
            if e+MAXH<=len(T): res,px='tiempo 48h',C[e+MAXH-1]; j=e+MAXH-1
            else: res='abierta'          # not enough closed bars yet
        busy[side]=j
        sgn=1 if side=='L' else -1; risk=abs(entry-stop)
        r=dict(lado='alcista' if side=='L' else 'bajista',
               senal_cierre_utc=dt.datetime.fromtimestamp(T[i]+3600,UTC).strftime('%Y-%m-%d %H:%M'),
               senal_cierre_madrid=dt.datetime.fromtimestamp(T[i]+3600,UTC).astimezone(MAD).strftime('%Y-%m-%d %H:%M'),
               nivel_roto=round(hh if side=='L' else ll,2), cierre_senal=sc, stop=round(stop,2), objetivo=round(tgt,2),
               entrada=entry, resultado=res,
               salida_vela_utc=dt.datetime.fromtimestamp(T[j],UTC).strftime('%Y-%m-%d %H:%M'),
               salida=round(px,2) if px is not None else '')
        if px is not None:
            g=sgn*(px-entry)/entry; r['bruto_pct']=round(100*g,3); r['neto_pct']=round(100*(g-2*COST),3)
            r['neto_R']=round((sgn*(px-entry)-COST*(entry+px))/risk,3) if risk>0 else ''
        trades.append(r)
with open(out,'w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=['lado','senal_cierre_utc','senal_cierre_madrid','nivel_roto','cierre_senal','stop','objetivo','entrada','resultado','salida_vela_utc','salida','bruto_pct','neto_pct','neto_R'])
    w.writeheader(); w.writerows(trades)
from collections import Counter
print('velas 1h cerradas',len(T), dt.datetime.fromtimestamp(T[0],UTC), '->', dt.datetime.fromtimestamp(T[-1]+3600,UTC),'| primer contexto 4h',dt.datetime.fromtimestamp(min(ctx),UTC))
mid=T[0]+(T[-1]-T[0])//2
for side in ('alcista','bajista'):
    tr=[t for t in trades if t['lado']==side]; done=[t for t in tr if 'neto_pct' in t]
    print(f"\n{side}: señales {len(tr)} {dict(Counter(t['resultado'] for t in tr))}")
    if done:
        print(f"  cerradas {len(done)} ganadoras {sum(t['neto_pct']>0 for t in done)} media neta {sum(t['neto_pct'] for t in done)/len(done):.3f}% media bruta {sum(t['bruto_pct'] for t in done)/len(done):.3f}% suma neta {sum(t['neto_pct'] for t in done):.2f}% media R {sum(t['neto_R'] for t in done)/len(done):.3f}")
        for half,f in (('1ª mitad',lambda t:t['senal_cierre_utc']<dt.datetime.fromtimestamp(mid,UTC).strftime('%Y-%m-%d %H:%M')),('2ª mitad',lambda t:t['senal_cierre_utc']>=dt.datetime.fromtimestamp(mid,UTC).strftime('%Y-%m-%d %H:%M'))):
            x=[t for t in done if f(t)]
            if x: print(f"  {half}: {len(x)} ops, media neta {sum(t['neto_pct'] for t in x)/len(x):.3f}%")
print('mitad', dt.datetime.fromtimestamp(mid,UTC))
# current state
i=len(T)-1; cx=context(T[i]+3600)
print('ultima vela cerrada',dt.datetime.fromtimestamp(T[i]+3600,UTC),'cierre',C[i],'4h cierre/ema',cx,'max20',max(H[i-19:i+1]),'min20',min(L[i-19:i+1]))
