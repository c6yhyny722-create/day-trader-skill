"""ORB backtest, simulation only. Rule fixed before running (see chat)."""
import json, sys, math, datetime as dt, importlib.util as u
from datetime import timezone; from zoneinfo import ZoneInfo
spec=u.spec_from_file_location('scan', sys.argv[2]); scan=u.module_from_spec(spec); spec.loader.exec_module(scan)
NY=ZoneInfo('America/New_York'); MAD=ZoneInfo('Europe/Madrid'); SLIP=0.02
b=json.load(open(sys.argv[1]))['bars']
bars={}
for i,t in enumerate(b['t']):
    x=dt.datetime.fromtimestamp(t,timezone.utc).astimezone(NY)
    bars.setdefault(x.date(),[]).append((x.time(),b['o'][i],b['h'][i],b['l'][i],b['c'][i]))
# last 60 closed NYSE sessions up to 2026-11-25
days=[];d=dt.date.fromisoformat(sys.argv[4]) if len(sys.argv)>4 else dt.date(2026,11,25)
while len(days)<60:
    if scan.session(d): days.append(d)
    d-=dt.timedelta(days=1)
days.reverse()
rows=[];missing=[]
for d in days:
    op,cl=scan.session(d)
    n=(cl.hour*60+cl.minute-570)//5
    grid=[dt.time((570+5*k)//60,(570+5*k)%60) for k in range(n)]
    s=bars.get(d,[])
    if [r[0] for r in s]!=grid: missing.append((d,len(s),n)); continue
    flat=dt.time((cl.hour*60+cl.minute-5)//60,(cl.hour*60+cl.minute-5)%60)   # 15:55 or 12:55
    orh=max(r[2] for r in s[:3]); orl=min(r[3] for r in s[:3])
    stop=math.floor((orh+orl)/2*100+1e-9)/100
    sig=next((k for k in range(3,n) if s[k][4]>orh),None)
    rec=dict(day=str(d),orh=orh,orl=orl,stop=stop)
    if sig is None:
        rec['res']='sin señal'; rows.append(rec); continue
    if sig+1>=n or s[sig+1][0]>=flat:
        rec['res']='señal sin tiempo'; rec['sig']=str(s[sig][0])[:5]; rows.append(rec); continue
    sc=s[sig][4]; R=round(sc-stop,4); tgt=round(sc+2*R,2); e=sig+1; entry=s[e][1]
    rec.update(sig=str(s[sig][0])[:5],sigclose=sc,R=R,tgt=tgt,entry=entry)
    res=None
    for k in range(e,n):
        tm,o,h,l,c=s[k]
        if tm>=flat: res,px,at='cierre',o,tm; break
        if k>e and o<=stop: res,px,at='stop (hueco)',o,tm; break
        if k>e and o>=tgt: res,px,at='objetivo (hueco)',o,tm; break
        if entry<=stop and k==e: res,px,at='stop (hueco)',entry,tm; break
        hs,ht=l<=stop,h>=tgt
        if hs and ht: res,px,at='indeterminado',None,tm; break
        if hs: res,px,at='stop',stop,tm; break
        if ht: res,px,at='objetivo',tgt,tm; break
    rec.update(res=res,exit=px,at=str(at)[:5])
    if px is not None:
        rec['gross']=round(px-entry,2); rec['net']=round(px-entry-2*SLIP,2)
    else:  # both outcomes, for transparency
        rec['net_if_stop']=round(stop-entry-2*SLIP,2); rec['net_if_tgt']=round(tgt-entry-2*SLIP,2)
    rows.append(rec)
json.dump(dict(days=[str(x) for x in days],missing=[(str(a),b_,c) for a,b_,c in missing],rows=rows),open(sys.argv[3],'w'),indent=1)
from collections import Counter
print('ventana',days[0],'->',days[-1],'sesiones',len(days),'incompletas',missing)
print('evaluadas',len(rows)); print(Counter(r['res'] for r in rows))
tr=[r for r in rows if 'net' in r]
print('operaciones con resultado',len(tr),'media neta',round(sum(r['net'] for r in tr)/len(tr),3),'media bruta',round(sum(r['gross'] for r in tr)/len(tr),3),'suma neta',round(sum(r['net'] for r in tr),2))
print('media neta en R', round(sum(r['net']/(r['entry']-r['stop']) for r in tr if r['entry']>r['stop'])/len(tr),3))
print('tardias >15:30', [r['day'] for r in rows if r.get('sig','00')>'15:30'])
for r in rows:
    if 'sig' in r: print(r['day'],r['sig'],r['sigclose'],'OR',r['orl'],r['orh'],'stop',r['stop'],'tgt',r['tgt'],'in',r['entry'],'->',r['res'],r['at'],r.get('exit'),r.get('net',(r.get('net_if_stop'),r.get('net_if_tgt'))))
    else: print(r['day'],r['res'])
