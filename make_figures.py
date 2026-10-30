# -*- coding: utf-8 -*-
"""Построение рисунков 2–4 статьи по results/res.json."""
import json, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt, numpy as np
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
plt.rcParams.update({'font.family':'DejaVu Serif','font.size':10,'axes.grid':True,'grid.alpha':0.3,'savefig.dpi':300})
r=json.load(open('results/res.json')); m=r['main']; XS=[0,2,4,5,6,8,10,12,14,16]
NAMES={'S1':'С1: без помощи','S2':'С2: индекс срочности в секторе','S3':'С3: помощь по докладу (идеализированная)','S3r':'С3р: помощь по докладу (реалистичная)',
       'S4':'С4: предлагаемый метод (резерв по индексу)','S5':'Четыре сектора (постоянное 4-е место)'}
ST={'S1':('k','--','s'),'S2':('0.45','-.','^'),'S3':('0.35','-','o'),'S3r':('0.35',(0,(5,2)),'o'),'S4':('k','-','D'),'S5':('0.55',':','v')}
fig,ax=plt.subplots(figsize=(6.3,3.6))
for p in ['S1','S2','S3','S3r','S4','S5']:
    y=[m[f'{p}|{x}']['K'] for x in XS]; e=[m[f'{p}|{x}']['K_ci'] for x in XS]
    c,ls,mk=ST[p]; ax.errorbar(XS,y,yerr=e,color=c,ls=ls,marker=mk,ms=4,mfc=('white' if p=='S3r' else c),lw=2.2 if p=='S4' else 1.2,capsize=2,label=NAMES[p])
ax.set_xlabel('Интенсивность полётов БВС x, полётов/ч'); ax.set_ylabel('Интегральный показатель K')
ax.set_ylim(0.3,1.0); ax.set_xticks(XS)
ax.axvline(9,color='0.5',lw=0.8,ls=':'); ax.text(9.15,0.33,'Кз = 0,70\nпри 3 секторах',fontsize=7,color='0.3'); ax.legend(fontsize=7,loc='lower center',bbox_to_anchor=(0.5,1.01),ncol=2,frameon=False)
fig.tight_layout(); fig.savefig('results/fig2.png')
fig,ax=plt.subplots(figsize=(6.3,3.0)); pols=['S1','S2','S3','S4']; procs=['A','B','C']
lab={'A':'A: ОВД\nпилотируемых ВС','B':'B: заявки\nна ИВП','C':'C: координация\nи контроль БВС','D':'D: нештатные\nситуации с БВС'}
w=0.2; hatch=['','///','...','xxx']
for i,p in enumerate(pols):
    v=[m[f'{p}|10'][k] for k in procs]
    ax.bar(np.arange(3)+(i-1.5)*w,v,w,color=['white','0.85','0.6','0.25'][i],edgecolor='k',hatch=hatch[i],label=NAMES[p])
ax.set_xticks(range(3)); ax.set_xticklabels([lab[k] for k in procs],fontsize=8)
ax.set_ylabel('Доля задач в пределах норматива'); ax.set_ylim(0,1.0); ax.legend(fontsize=7,loc='lower center',bbox_to_anchor=(0.5,1.01),ncol=2,frameon=False)
fig.tight_layout(); fig.savefig('results/fig3.png')
th=['0.25','0.5','1.0','1.5','2.0','3.0']; tv=[float(t) for t in th]
K=[r['th'][t]['K'] for t in th]; R=[r['th'][t]['R'] for t in th]
fig,ax=plt.subplots(figsize=(6.3,3.0)); ax2=ax.twinx(); ax2.grid(False)
ax.plot(tv,K,'k-o',label='K'); ax2.plot(tv,R,'--s',color='0.4',label='Доля времени работы резерва R')
ax.set_xlabel('Порог включения резерва θ'); ax.set_ylabel('K'); ax2.set_ylabel('R')
ax.set_ylim(0.6,0.95); ax2.set_ylim(0.2,0.7)
h1,l1=ax.get_legend_handles_labels(); h2,l2=ax2.get_legend_handles_labels(); ax.legend(h1+h2,l1+l2,fontsize=8,loc='lower left')
fig.tight_layout(); fig.savefig('results/fig4.png')

print('ok')
