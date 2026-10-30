# -*- coding: utf-8 -*-
"""Помощь по докладу в реальных условиях (задержка доклада, ограничение 25 % для РП)
и показатели худших задержек (раздел 5.3). Результат: results/res_real.json."""
import sys, json, statistics as st, math
from dataclasses import replace
sys.path.insert(0,'.')
import run_experiments as E, sector_model as S
cfg=E.cfg
V={'S1':dict(rule='prio'),'S3':dict(rule='prio',reserve='qlen'),
   'S3d1':dict(rule='prio',reserve='qlen',rdelay=1.0),
   'S3c':dict(rule='prio',reserve='qlen',rcap=0.25),
   'S3r':dict(rule='prio',reserve='qlen',rdelay=1.0,rcap=0.25),
   'S3r05':dict(rule='prio',reserve='qlen',rdelay=0.5,rcap=0.25),
   'S3r2':dict(rule='prio',reserve='qlen',rdelay=2.0,rcap=0.25),
   'S4':dict(rule='urg',reserve='float'),
   'S4cap':dict(rule='urg',reserve='float',rcap=0.25)}  # метод при том же ограничении 25 % смены
def ser(c,x,n,seed0,**kw):
    rs=[S.run(c,x,seed0+i,**kw) for i in range(n)]
    o={}
    for k in ['K','R','A','C','D','viol','viol2','l2A','l2C','p95A','p95C','rhoR']:
        v=[r[k] for r in rs if k in r]
        if v: o[k]=st.mean(v); o[k+'_ci']=1.96*st.stdev(v)/math.sqrt(len(v)) if len(v)>1 else 0
    o['allmax']=st.mean(max(max(r['rho']),r['rhoR']) for r in rs)
    return o
if __name__=='__main__':
  out={}
  for x in [15,20]:
      for n,kw in V.items():
          out[f'{n}|{x}']=o=ser(cfg,x,300,10000*x+7,**kw)
          print(x,n,'K %.3f viol %.3f viol2 %.3f p95A %.2f p95C %.2f R %.3f max %.3f'%(o['K'],o['viol'],o['viol2'],o['p95A']*60,o['p95C']*60,o['R'],o['allmax']),flush=True)
  c=replace(cfg,base_per_hour={'A':E.LOAD0,'B':0.0,'C':0.0,'D':27*0.01},per_flight={'A':0.0,'B':1.0,'C':4.0,'D':0.01},weight={'A':1.0,'B':1.0,'C':1.0,'D':3.0})
  for n in ['S1','S3','S3r','S4']:
      out[f'pD|{n}']=o=ser(c,20,300,95000,**V[n]); print('pD0.01',n,'K %.3f D %.3f'%(o['K'],o['D']))
  json.dump(out,open('results/res_real.json','w'),ensure_ascii=False,indent=1)
