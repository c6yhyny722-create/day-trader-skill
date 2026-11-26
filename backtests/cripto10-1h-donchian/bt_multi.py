"""10 coins, 1h Donchian-20 breakout + 4h EMA50 context + entry zone. Simulation only. Rules: REGLAS.md."""
import json, sys, csv, os, datetime as dt
from collections import Counter, defaultdict
UTC=dt.timezone.utc
N_BRK,N_STOP,EMA_N,MAXH,COST,ZONE=20,10,50,48,0.001,0.5
COINS=["BTCUSD","ETHUSD","XRPUSD","SOLUSD","HYPEUSD","ZECUSD","DOGEUSD","LINKUSD","ADAUSD","XLMUSD"]
src,outdir,now=sys.argv[1],sys.argv[2],int(sys.argv[3])

def run(coin):
    b=json.load(open(f"{src}/{coin}.json"))['bars']
    T,O,H,L,C=b['t'],b['o'],b['h'],b['l'],b['c']
    k=sum(1 for t in T if t+3600<=now); T,O,H,L,C=T[:k],O[:k],H[:k],L[:k],C[:k]
    g={}
    for i,t in enumerate(T): g.setdefault(t-t%14400,[]).append(i)
    # 4h candle = all 1h bars of that 4h window that exist (as TradingView builds it)
    ctx={}; ema=None; a=2/(EMA_N+1); n=0
    for s in sorted(g):
        c=C[g[s][-1]]; ema=c if ema is None else a*c+(1-a)*ema; n+=1
        if n>=EMA_N: ctx[s]=(c,ema)        # keyed by 4h open
    starts=sorted(ctx)
    import bisect
    def context(t_open):                   # last 4h candle that closed at or before t_open
        j=bisect.bisect_right(starts, t_open-t_open%14400-14400)-1
        return ctx[starts[j]] if j>=0 else None
    sigs=[]; trades=[]; busy={'L':-1,'S':-1}
    for i in range(N_BRK,len(T)):
        cx=context(T[i])
        if not cx: continue
        hh=max(H[i-N_BRK:i]); ll=min(L[i-N_BRK:i])
        for side in 'LS':
            if side=='L' and not (cx[0]>cx[1] and C[i]>hh): continue
            if side=='S' and not (cx[0]<cx[1] and C[i]<ll): continue
            up=side=='L'; sc=C[i]
            stop=min(L[i-N_STOP+1:i+1]) if up else max(H[i-N_STOP+1:i+1])
            R=abs(sc-stop); lvl=hh if up else ll
            zlo,zhi=(lvl,lvl+ZONE*R) if up else (lvl-ZONE*R,lvl)
            inz=zlo<=sc<=zhi
            tgt=sc+2*R if up else sc-2*R
            sigs.append(dict(coin=coin,t=T[i]+3600,side=side,close=sc,lvl=lvl,zlo=zlo,zhi=zhi,inz=inz,stop=stop,tgt=tgt))
            if i<=busy[side] or i+1>=len(T): continue
            e=i+1; entry=O[e]; res=px=None; j=e
            for j in range(e,min(e+MAXH,len(T))):
                if j>e and (O[j]<=stop if up else O[j]>=stop): res,px='stop (hueco)',O[j]; break
                if j>e and (O[j]>=tgt if up else O[j]<=tgt): res,px='objetivo (hueco)',O[j]; break
                if j==e and (entry<=stop if up else entry>=stop): res,px='stop (hueco)',entry; break
                hs=L[j]<=stop if up else H[j]>=stop; ht=H[j]>=tgt if up else L[j]<=tgt
                if hs and ht: res='indeterminado'; break
                if hs: res,px='stop',stop; break
                if ht: res,px='objetivo',tgt; break
            else:
                if e+MAXH<=len(T): res,px='tiempo 48h',C[e+MAXH-1]; j=e+MAXH-1
                else: res='abierta'
            busy[side]=j; sg=1 if up else -1
            tr=dict(sigs[-1],entry=entry,res=res,exit=px)
            if px is not None:
                gr=sg*(px-entry)/entry; tr['gross']=100*gr; tr['net']=100*(gr-2*COST)
            trades.append(tr)
    gaps=sum(1 for x,y in zip(T,T[1:]) if y-x!=3600)
    return T,sigs,trades,gaps

def stats(tr):
    d=[t for t in tr if 'net' in t]
    c=Counter(t['res'] for t in tr)
    m=sum(t['net'] for t in d)/len(d) if d else float('nan')
    return len(tr),c.get('objetivo',0)+c.get('objetivo (hueco)',0),c.get('stop',0)+c.get('stop (hueco)',0),c.get('tiempo 48h',0),c.get('indeterminado',0),c.get('abierta',0),m,sum(t['net']>0 for t in d)

allsig=[]; rows=[]; trades_all=[]
print(f"{'moneda':8} {'velas':>5} {'huecos':>6} {'desde':>10} | lado  ops obj stop 48h ind abie  media%  gan | zona: ops media%")
for coin in COINS:
    T,sigs,trades,gaps=run(coin); allsig+=sigs; trades_all+=trades
    for side,name in (('L','alcista'),('S','bajista')):
        tr=[t for t in trades if t['side']==side]; zi=[t for t in tr if t['inz']]
        n,o,s,h,ind,ab,m,w=stats(tr); nz,_,_,_,_,_,mz,_=stats(zi)
        rows.append(dict(coin=coin,lado=name,operaciones=n,objetivo=o,stop=s,tiempo_48h=h,indeterminadas=ind,abiertas=ab,media_neta_pct=round(m,3),ganadoras=w,en_zona=nz,media_neta_en_zona_pct=round(mz,3) if nz else ''))
        print(f"{coin:8} {len(T):5} {gaps:6} {dt.datetime.fromtimestamp(T[0],UTC):%Y-%m-%d} | {name:7} {n:3} {o:3} {s:4} {h:3} {ind:3} {ab:4} {m:7.3f} {w:4} | {nz:3} {mz:7.3f}")
for side,name in (('L','alcista'),('S','bajista')):
    tr=[t for t in trades_all if t['side']==side]; zi=[t for t in tr if t['inz']]
    n,o,s,h,ind,ab,m,w=stats(tr); nz,oz,sz,hz,_,_,mz,wz=stats(zi)
    print(f"TOTAL {name}: ops {n} obj {o} stop {s} 48h {h} ind {ind} abiertas {ab} media {m:.3f}% ganadoras {w} | en zona {nz} (obj {oz} stop {sz} 48h {hz}) media {mz:.3f}% | fuera de zona {n-nz}")
with open(f"{outdir}/resumen_por_moneda.csv","w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
with open(f"{outdir}/operaciones.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(['moneda','lado','senal_cierre_utc','cierre','nivel_roto','zona_desde','zona_hasta','en_zona','invalidacion','objetivo','entrada','resultado','salida','bruto_pct','neto_pct'])
    for t in trades_all:
        w.writerow([t['coin'],'alcista' if t['side']=='L' else 'bajista',dt.datetime.fromtimestamp(t['t'],UTC).strftime('%Y-%m-%d %H:%M'),t['close'],t['lvl'],round(t['zlo'],6),round(t['zhi'],6),'sí' if t['inz'] else 'no',t['stop'],round(t['tgt'],6),t['entry'],t['res'],t['exit'] if t['exit'] is not None else '',round(t.get('gross',0),3) if 'gross' in t else '',round(t['net'],3) if 'net' in t else ''])
by=defaultdict(list)
for s in allsig: by[s['t']].append(s)
multi={t:v for t,v in by.items() if len(v)>=2}
print('horas con señal',len(by),'| con 2 o más monedas a la vez',len(multi),'| máximo',max(len(v) for v in by.values()))
json.dump([dict(s,t=s['t']) for s in allsig],open(f"{outdir}/senales_todas.json","w"))
