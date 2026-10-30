# -*- coding: utf-8 -*-
"""Модель центра ОВД при жёсткой секторизации (основная модель статьи).

run(cfg, x, seed, rule, reserve, th, rp_classes, nsec, QON) — один прогон смены.
  rule:    'prio' — жёсткие приоритеты D > A > C > B внутри сектора (С1, С3);
           'urg'  — правило (6): D, затем максимальный индекс срочности (С2, С4);
  reserve: None — без помощи (С1, С2);
           'qlen' — помощь по докладу: резерв подключается к сектору с наибольшим
                    числом ожидающих задач, если их не меньше QON (С3);
           'float' — предлагаемый метод: резерв по индексу срочности, порог th (С4);
           'dedicated' — постоянное место для классов rp_classes из всех секторов.
rdelay — задержка доклада, мин (условие должно сохраняться); rcap — предельная
доля смены, в течение которой помощь может оказываться (например, 0,25 для РП).
Возвращает доли задач в нормативе по классам, K, долю работы резерва R и
загруженность рабочих мест (rho — секторы, rhoR — резерв).
"""
import heapq, math, random, statistics as st
import ovd_model as M
CL=M.CL; PRIO=M.PRIO
def run(cfg,x,seed,rule='prio',reserve=None,th=1.0,rp_classes=None,nsec=None,QON=2,rdelay=0.0,rcap=None):
    """Жёсткая секторизация. rule: 'prio' (D>A>C>B) или 'urg' (D, затем max U) внутри сектора.
    reserve: None | 'float' — РП подключается к сектору с max U>=th, берёт задачу оттуда;
             'dedicated' — РП постоянно выполняет классы rp_classes из всех секторов."""
    N=nsec or cfg.N; T,WARM=cfg.shift_min,cfg.warmup_min
    rng=random.Random(seed); L=M.lam(cfg,x); ev=[]; cnt=[0]
    qs=[{k:[] for k in CL} for _ in range(N)]; rq={k:[] for k in CL}
    busy=[False]*N; rbusy=False; ractive=False; ron=None; rtime=0.0; rall=0.0; pend=[False]
    waits={k:[] for k in CL}
    bt={}
    def push(t,typ,o):
        cnt[0]+=1; heapq.heappush(ev,(t,cnt[0],typ,o))
    for k in CL:
        if L[k]>0: push(rng.expovariate(L[k]),'arr',k)
    U=lambda q,k,now:(now-q[k][0])/cfg.target_wait[k]
    def pick(q,now):
        cand=[k for k in CL if q[k]]
        if not cand: return None
        if rule=='prio' : return min(cand,key=lambda c:PRIO[c])
        if 'D' in cand: return 'D'
        return max(cand,key=lambda c:U(q,c,now))
    def serve(q,k,now,who):
        t0=q[k].pop(0)
        if t0>=WARM: waits[k].append(now-t0)
        d=M.service_time(rng,cfg,k)
        a,b=max(now,WARM),min(now+d,T)
        if b>a: bt[who]=bt.get(who,0)+b-a
        push(now+d,'dep',who)
    def start(s,now):
        k=pick(qs[s],now)
        if k is None: busy[s]=False; return
        busy[s]=True; serve(qs[s],k,now,s)
    def maxU_sec(now):
        best=(-1,None)
        for s in range(N):
            for k in CL:
                if qs[s][k]:
                    u=U(qs[s],k,now)+ (100 if k=='D' else 0)
                    if u>best[0]: best=(u,s)
        return best
    def maxQ(now):
        best=(-1,None)
        for s_ in range(N):
            n=sum(len(qs[s_][k]) for k in CL)
            if n>best[0]: best=(n,s_)
        return best
    def rstart(now):
        nonlocal rbusy,ractive,rtime,rall
        if reserve=='qlen':
            n,s_=maxQ(now)
            over=rcap is not None and ractive and (rall+now-ron)/max(now,1e-9)>=rcap
            if n<=0 or over:
                rbusy=False
                if ractive:
                    ractive=False; rall+=now-ron
                    if now>WARM: rtime+=now-max(ron,WARM)
                return
            k=pick(qs[s_],now); rbusy=True; serve(qs[s_],k,now,'R'); return
        if reserve=='combo':
            # 4-й диспетчер: ведёт заявки B из всех секторов, в остальное время помогает сектору с max U>=th
            u,s=maxU_sec(now)
            kb=pick(rq,now)
            ub=U(rq,kb,now) if kb else -1
            if s is not None and u>=th and u>ub:
                k=pick(qs[s],now); rbusy=True; serve(qs[s],k,now,'R'); return
            if kb: rbusy=True; serve(rq,kb,now,'R'); return
            if s is not None and u>=0: 
                k=pick(qs[s],now); rbusy=True; serve(qs[s],k,now,'R'); return
            rbusy=False; return
        if reserve=='dedicated':
            k=pick(rq,now)
            if k is None: rbusy=False; return
            rbusy=True; serve(rq,k,now,'R'); return
        u,s=maxU_sec(now)
        over=rcap is not None and ractive and (rall+now-ron)/max(now,1e-9)>=rcap
        if u< th/2 or s is None or over:
            rbusy=False
            if ractive:
                ractive=False; rall+=now-ron
                if now>WARM: rtime+=now-max(ron,WARM)
            return
        k=pick(qs[s],now); rbusy=True; serve(qs[s],k,now,'R')
    while ev:
        now,_,typ,o=heapq.heappop(ev)
        if typ=='arr':
            if now>T: continue
            push(now+rng.expovariate(L[o]),'arr',o)
            if reserve in ('dedicated','combo') and o in rp_classes:
                rq[o].append(now)
                if not rbusy: rstart(now)
            else:
                s=rng.randrange(N); qs[s][o].append(now)
                if not busy[s]: start(s,now)
                elif reserve=='combo' and not rbusy: rstart(now)
        elif typ=='dep':
            if o=='R': rstart(now)
            else:
                start(o,now)
        capok=lambda t: rcap is None or rall/max(t,1e-9)<rcap
        if typ=='rep':
            pend[0]=False
            if reserve=='qlen' and not ractive and maxQ(now)[0]>=QON and capok(now):
                ractive=True; ron=now
                if not rbusy: rstart(now)
        elif reserve=='qlen' and not ractive:
            n,s_=maxQ(now)
            if n>=QON:
                if rdelay>0:
                    if not pend[0]: pend[0]=True; push(now+rdelay,'rep',None)
                elif capok(now):
                    ractive=True; ron=now
                    if not rbusy: rstart(now)
        if reserve=='float' and not ractive:
            u,s=maxU_sec(now)
            if s is not None and u>=th and capok(now):
                ractive=True; ron=now
                if not rbusy: rstart(now)
            elif s is not None:
                tn=min(qs[ss][k][0]+th*cfg.target_wait[k] for ss in range(N) for k in CL if qs[ss][k])
                if tn>now: push(tn,'chk',None)
    if ractive: rtime+=T-max(ron,WARM)
    out={}
    for k in CL:
        w=waits[k]
        if w:
            out[k]=sum(v<=cfg.target_wait[k] for v in w)/len(w); out['w'+k]=st.mean(w)
            out['l2'+k]=sum(v>2*cfg.target_wait[k] for v in w)/len(w)
            out['p95'+k]=sorted(w)[min(len(w)-1,int(0.95*len(w)))]
    out['K']=sum(cfg.weight[k]*out[k] for k in CL if k in out)/sum(cfg.weight[k] for k in CL if k in out)
    ac=[(v,cfg.target_wait[k]) for k in 'ABC' for v in waits[k]]
    if ac:
        out['viol']=sum(v>t for v,t in ac)/len(ac); out['viol2']=sum(v>2*t for v,t in ac)/len(ac)
    out['R']=rtime/(T-WARM) if reserve in ('float','qlen') else (1.0 if reserve in ('dedicated','combo') else 0.0)
    out['rho']=[bt.get(s,0)/(T-WARM) for s in range(N)]; out['rhoR']=bt.get('R',0)/(T-WARM)
    return out
