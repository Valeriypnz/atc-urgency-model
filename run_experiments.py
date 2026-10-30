# -*- coding: utf-8 -*-
"""Воспроизведение всех экспериментов статьи (разделы 5.3–5.6).
python run_experiments.py           — полный расчёт (300/200 прогонов, около 3 мин)
python run_experiments.py --quick   — быстрый пробный расчёт
Результат: results/res.json; рисунки строит make_figures.py.
"""
import json, statistics as st, math, time
from dataclasses import replace
import ovd_model as M, sector_model as S, sys, os
AC_MIN=1.2   # рабочее время диспетчера на один пролёт, мин (из норматива: 0,55·60/(26…31) ≈ 1,1–1,3)
LOAD0=27*AC_MIN
cfg=M.Config(N=3, shift_min=420.0, warmup_min=60.0, base_per_hour={'A':27*AC_MIN,'B':0.0,'C':0.0,'D':27*0.0001},  # A: 27 ВС/ч по AC_MIN мин; D: 0,01 % на полёт пилотируемого ВС
   
    per_flight={'A':0.0,'B':1.0,'C':4.0,'D':0.0001}, mean_service={'A':1.0,'B':1.0,'C':1.0,'D':15.0},
    target_wait={'A':0.5,'B':30.0,'C':0.5,'D':0.5}, weight={'A':1.0,'B':1.0,'C':1.0,'D':0.0}, cv=0.5)
V={'S1':dict(rule='prio'),'S2':dict(rule='urg'),'S3':dict(rule='prio',reserve='qlen'),
   'S4':dict(rule='urg',reserve='float'),'S5':dict(rule='prio',nsec=4),
   'S6':dict(rule='prio',reserve='dedicated',rp_classes={'B','C'}),
   'S3r':dict(rule='prio',reserve='qlen',rdelay=1.0,rcap=0.25)}  # помощь РП по докладу: задержка 1 мин, не более 25 % смены
def ser(c,x,reps,seed0,**kw):
    rs=[S.run(c,x,seed0+r,**kw) for r in range(reps)]
    row={}
    for key in ['K','R','A','B','C','D','wA','wB','wC','wD','rhoR']:
        v=[r[key] for r in rs if key in r]
        if v: row[key]=st.mean(v); row[key+'_ci']=1.96*st.stdev(v)/math.sqrt(len(v)) if len(v)>1 else 0; row[key+'_n']=len(v)
    row['rho']=st.mean(st.mean(r['rho']) for r in rs); row['rhomax']=st.mean(max(r['rho']) for r in rs)
    row['allmax']=st.mean(max(max(r['rho']),r['rhoR']) for r in rs)
    return row
if __name__=='__main__':
    QUICK='--quick' in sys.argv; RM,RR=(30,20) if QUICK else (300,200)
    t=time.time(); out={'main':{},'th':{},'rob':{},'pool':{},'load':{}}
    XS=[0,5,8,10,12,15,18,20,25,30]
    for x in XS: out['load'][str(x)]=(LOAD0+5*x)/180
    for n,kw in V.items():
        for x in XS: out['main'][f'{n}|{x}']=ser(cfg,x,RM,10000*x+7,**kw)
        print(n,' '.join('%.3f'%out['main'][f'{n}|{x}']['K'] for x in XS),' R:',' '.join('%.2f'%out['main'][f'{n}|{x}']['R'] for x in XS),flush=True)
    XM=20
    for th in [0.25,0.5,1.0,1.5,2.0,3.0]:
        out['th'][str(th)]=ser(cfg,XM,RM,60000,rule='urg',reserve='float',th=th)
    print('th',{k:(round(v['K'],3),round(v['R'],3)) for k,v in out['th'].items()},flush=True)
    for cv in [0.3,0.5,1.0]:
        c=replace(cfg,cv=cv)
        for p in ['S1','S3','S4']: out['rob'][f'cv{cv}|{p}']=ser(c,XM,RR,90000,**V[p])
    for N in [2,4]:
        c=replace(cfg,N=N,base_per_hour={'A':LOAD0*N/3,'B':0,'C':0,'D':27*0.0001*N/3}); x=XM*N/3
        for p in ['S1','S3','S4']: out['rob'][f'N{N}|{p}']=ser(c,x,RR,90000,**V[p])
    for pd in [0.01,0.1]:
        c=replace(cfg,base_per_hour={'A':LOAD0,'B':0.0,'C':0.0,'D':27*pd},per_flight={'A':0.0,'B':1.0,'C':4.0,'D':pd},weight={'A':1.0,'B':1.0,'C':1.0,'D':3.0})
        for p in ['S1','S3','S4']: out['rob'][f'pD{pd}|{p}']=ser(c,XM,RM,95000,**V[p])
    print('rob',{k:(round(v['K'],3),round(v['R'],3),round(v.get('D',-1),3)) for k,v in out['rob'].items()},flush=True)
    for pol in ['priority','dynamic','dyn_res']:
        out['pool'][pol]=M.series(replace(cfg,theta_on=1.0,theta_off=0.5),pol,XM,RM,70000)
    out['pool']['prio4']=M.series(replace(cfg,N=4),'priority',XM,RM,70000)
    print('pool',{k:(round(v['K'],3),round(v['res'],3)) for k,v in out['pool'].items()})
    print('time',time.time()-t)
    os.makedirs('results',exist_ok=True); json.dump(out,open('results/res.json','w'),ensure_ascii=False,indent=1)
