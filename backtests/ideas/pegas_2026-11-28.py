import sys,time,json
sys.path.insert(0,'trader-cripto'); import cripto as cr
def rsi_serie(xs,n=14):
    out=[None]*len(xs)
    if len(xs)<=n: return out
    g=sum(max(xs[i]-xs[i-1],0) for i in range(1,n+1))/n; p=sum(max(xs[i-1]-xs[i],0) for i in range(1,n+1))/n
    out[n]=100 if p==0 else 100-100/(1+g/p)
    for i in range(n+1,len(xs)):
        d=xs[i]-xs[i-1]; g=(g*(n-1)+max(d,0))/n; p=(p*(n-1)+max(-d,0))/n
        out[i]=100 if p==0 else 100-100/(1+g/p)
    return out
res={}
ahora=int(time.time())
for m in ["BTC","ETH","SOL","DOGE","XLM"]:
    v1,v4=cr.cargar(m,None,1095*24)
    v1,v4=cr.preparar_historia(cr.cerradas(v1,cr.H1,ahora),cr.cerradas(v4,cr.H4,ahora))
    lista=cr.senales(v1,v4); por_ts={s["cierre_ts"]:s for s in lista}
    ops=cr.operaciones_reales(v1,lista,720,cr.fugas_de(m),siguiente=True,moneda=m,spread_variable=True)
    atrs=cr.atr(v1); r1=rsi_serie([b["c"] for b in v1])
    vols=[b["v"] for b in v1]
    filas=[]
    for o in ops:
        s=por_ts[o["ts"]]; j=s["j"]; venta=s["lado"]=="VENTA"
        c4,e4=s["contexto"]
        vm=sum(vols[j-20:j])/20 if j>=20 else None
        f={
         "stop_lejos": atrs[j] and s["R"]/atrs[j]>3,
         "rsi1h_agotado": r1[j] is not None and ((venta and r1[j]<30) or ((not venta) and r1[j]>70)),
         "volumen_bajo": vm and vols[j]<0.5*vm,
         "4h_casi_gira": abs(c4-e4)/e4<0.002,
         "fin_de_semana": cr.es_fin_de_semana(s["cierre_ts"]),
        }
        filas.append({"m":m,"ts":o["ts"],"R":o["R"],**{k:bool(v) for k,v in f.items()}})
    res[m]=filas
json.dump(res,open('/tmp/pegas.json','w'))
todas=[x for v in res.values() for x in v]; todas.sort(key=lambda x:x["ts"])
n=len(todas); t1,t2=todas[n//3]["ts"],todas[2*n//3]["ts"]
per=lambda x: 0 if x["ts"]<t1 else 1 if x["ts"]<t2 else 2
mean=lambda xs: (sum(xs)/len(xs),len(xs)) if xs else (None,0)
print("total",n,"R medio",round(sum(x["R"] for x in todas)/n,3))
for k in ["stop_lejos","rsi1h_agotado","volumen_bajo","4h_casi_gira","fin_de_semana"]:
    con=[x["R"] for x in todas if x[k]]; sin=[x["R"] for x in todas if not x[k]]
    line=f"{k:15s} con {mean(con)[0]:+.3f} (n={len(con)}) sin {mean(sin)[0]:+.3f} (n={len(sin)}) |"
    for p in range(3):
        c=[x["R"] for x in todas if x[k] and per(x)==p]; s_=[x["R"] for x in todas if not x[k] and per(x)==p]
        line+=f" P{p+1}: con {mean(c)[0] if c else float('nan'):+.2f}({len(c)}) sin {mean(s_)[0]:+.2f}"
    ic=cr.intervalo_R(con) if len(con)>=20 else None
    print(line, "IC con", ic and (round(ic['bajo'],2),round(ic['alto'],2)))
