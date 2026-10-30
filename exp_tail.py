import sys, json, statistics as st
sys.path.insert(0,'.')
import run_experiments as E, sector_model as S
out=json.load(open('results/res_real.json'))
for n,kw in [('S2',E.V['S2']),('S5',E.V['S5']),('S6',E.V['S6'])]:
    rs=[S.run(E.cfg,20,10000*20+7+i,**kw) for i in range(300)]
    out[f'{n}|20']={k:st.mean(r[k] for r in rs) for k in ['K','viol','viol2']}
    print(n,{k:round(v,3) for k,v in out[f'{n}|20'].items()})
json.dump(out,open('results/res_real.json','w'),ensure_ascii=False,indent=1)
