# -*- coding: utf-8 -*-
"""Проверка независимости K от продолжительности смены (4, 7, 12 ч), 150 прогонов."""
import sys, dataclasses, statistics as st
sys.path.insert(0,'.')
import run_experiments as R, sector_model as S
V={'С1':dict(rule='prio'),'С3р':dict(rule='prio',reserve='qlen',rdelay=1.0,rcap=0.25),'С4':dict(rule='urg',reserve='float')}
for T in (240,420,720):
  c=dataclasses.replace(R.cfg,shift_min=float(T))
  for x in (5,10):
    row=[]
    for n,kw in V.items():
      o=[S.run(c,x,1000+i,**kw) for i in range(150)]
      row.append(f"{n} K={st.mean(r['K'] for r in o):.3f} R={st.mean(r['R'] for r in o):.2f}")
    print(T//60,'ч x=',x,' | '.join(row))
