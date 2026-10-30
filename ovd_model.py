# -*- coding: utf-8 -*-
"""
Общие элементы имитационной модели процессов центра обслуживания воздушного
движения (ОВД) и вариант «общий пул» (задачи могут передаваться между рабочими
местами); используется в разделе 5.6 статьи.

Классы задач: A — ОВД пилотируемых ВС; B — заявки на использование воздушного
пространства; C — координация и контроль полётов БВС; D — нештатные ситуации с БВС.

Варианты пула: priority — жёсткие приоритеты D > A > C > B; dynamic — индекс
срочности (правило (6)) без резерва; dyn_res — индекс срочности и резерв.
Параметры по умолчанию в Config — демонстрационные; параметры статьи задаются
в run_experiments.py.
"""
import heapq, math, random, statistics as st
from dataclasses import dataclass, field, replace

# ============================ ПАРАМЕТРЫ МОДЕЛИ ============================
@dataclass
class Config:
    # Штат и смена
    N: int = 6                    # число рабочих мест диспетчеров
    shift_min: float = 720.0      # продолжительность смены, мин (12 ч)
    warmup_min: float = 60.0      # период установления, исключается из статистики, мин

    # Интенсивность потоков задач:  lambda_k(x) = base_k + per_flight_k * x,  задач/ч
    # x — интенсивность полётов БВС, полётов/ч
    base_per_hour: dict = field(default_factory=lambda: {'A': 54.0, 'B': 0.0, 'C': 0.0, 'D': 0.0})
    per_flight:    dict = field(default_factory=lambda: {'A': 0.0,  'B': 1.0, 'C': 2.0, 'D': 0.1})

    # Среднее время выполнения задачи, мин
    mean_service:  dict = field(default_factory=lambda: {'A': 4.0, 'B': 10.0, 'C': 3.0, 'D': 8.0})
    # Норматив допустимого времени ожидания, мин
    target_wait:   dict = field(default_factory=lambda: {'A': 2.0, 'B': 30.0, 'C': 5.0, 'D': 1.0})
    # Веса процессов в интегральном показателе K
    weight:        dict = field(default_factory=lambda: {'A': 1.0, 'B': 1.0, 'C': 1.0, 'D': 3.0})

    cv: float = 0.5               # коэффициент вариации времени выполнения (логнормальное распр.)

    # Резерв (руководитель полётов)
    theta_on: float = 1.0         # порог включения: max U >= theta_on
    theta_off: float = 0.5        # порог отключения: max U < theta_off

    # Закреплённые рабочие места (П1): номер места -> обслуживаемые классы
    static_map: dict = None       # None = построить автоматически: N-2 мест A, 1 место B, 1 место C+D

    def static(self):
        if self.static_map is not None:
            return self.static_map
        m = {i: 'A' for i in range(self.N - 2)}
        m[self.N - 2] = 'B'; m[self.N - 1] = 'CD'
        return m

# ========================== ПАРАМЕТРЫ ЭКСПЕРИМЕНТОВ ==========================
X_RANGE = [0, 1, 2, 3, 4, 5, 6, 7]       # интенсивности полётов БВС, полётов/ч
X_MAIN = 6                               # базовая точка для табл. 2 и рис. 3, 4
THETAS = [0.25, 0.5, 1.0, 1.5, 2.0, 3.0] # пороги включения резерва (рис. 4)
CVS = [0.3, 0.5, 1.0]                    # коэффициенты вариации (табл. 3)
NS = [5, 8]                              # число рабочих мест (табл. 3)
POLICIES = ['static', 'priority', 'dynamic', 'dyn_res']
NAMES = {'static': 'П1: закреплённые места', 'priority': 'П2: жёсткие приоритеты',
         'dynamic': 'П3: индекс срочности', 'dyn_res': 'П4: предлагаемый метод',
         'prio7': 'П2 + постоянное доп. место'}
CL = ['A', 'B', 'C', 'D']
PRIO = {'D': 0, 'A': 1, 'C': 2, 'B': 3}

# ============================== МОДЕЛЬ ==============================
def lam(cfg, x):
    """Интенсивность потоков, задач/мин."""
    return {k: (cfg.base_per_hour[k] + cfg.per_flight[k] * x) / 60.0 for k in CL}

def service_time(rng, cfg, k):
    m = cfg.mean_service[k]; s2 = math.log(1 + cfg.cv ** 2)
    return rng.lognormvariate(math.log(m) - s2 / 2, math.sqrt(s2))

def urgency(cfg, k, qs, now):
    """Индекс срочности U_k = (t - t_k^0) / tau_k."""
    return (now - qs[k][0]) / cfg.target_wait[k]

def choose(cfg, pol, server, qs, now, static):
    cand = [k for k in CL if qs[k]]
    if not cand:
        return None
    if pol == 'static':
        cand = [k for k in cand if k in static[server]]
        return min(cand, key=lambda k: PRIO[k]) if cand else None
    if pol == 'priority':
        return min(cand, key=lambda k: PRIO[k])
    if 'D' in cand:                      # уровень 1: нештатные ситуации безусловно
        return 'D'
    return max(cand, key=lambda k: urgency(cfg, k, qs, now))   # уровень 2

def run(cfg, pol, x, seed):
    """Один прогон смены. Возвращает показатели по процессам, загрузку, долю резерва R и K."""
    N, T, WARM = cfg.N, cfg.shift_min, cfg.warmup_min
    static = cfg.static()
    rng = random.Random(seed); L = lam(cfg, x); reserve = (pol == 'dyn_res')
    NSRV = N + 1 if reserve else N
    ev = []; qs = {k: [] for k in CL}; busy = [False] * NSRV; busyt = 0.0
    waits = {k: [] for k in CL}
    res_active = False; res_on_t = None; res_time = 0.0; cnt = [0]
    for k in CL:
        if L[k] > 0:
            heapq.heappush(ev, (rng.expovariate(L[k]), 0, 'arr', k))

    def push(t, typ, o):
        cnt[0] += 1; heapq.heappush(ev, (t, cnt[0], typ, o))

    def maxU(now):
        c = [urgency(cfg, k, qs, now) for k in CL if qs[k]]
        return max(c) if c else -1

    def start(s, now):
        nonlocal busyt, res_active, res_time, res_on_t
        if s == N:                       # резервный ресурс
            if not res_active:
                busy[s] = False; return
            if maxU(now) < cfg.theta_off and not qs['D']:
                res_active = False; busy[s] = False
                if now >= WARM: res_time += now - max(res_on_t, WARM)
                return
        k = choose(cfg, pol, s, qs, now, static)
        if k is None:
            busy[s] = False
            if s == N and res_active:
                res_active = False
                if now >= WARM: res_time += now - max(res_on_t, WARM)
            return
        t0 = qs[k].pop(0); d = service_time(rng, cfg, k)
        if t0 >= WARM: waits[k].append(now - t0)
        busy[s] = True
        if s < N and WARM <= now < T: busyt += min(d, T - now)
        push(now + d, 'dep', s)

    while ev:
        now, _, typ, o = heapq.heappop(ev)
        if typ == 'arr':
            if now > T: continue
            qs[o].append(now); push(now + rng.expovariate(L[o]), 'arr', o)
            for s in range(N):
                if not busy[s]:
                    start(s, now)
                    if not any(qs.values()): break
        elif typ == 'dep':
            start(o, now)
        if reserve and not res_active and all(busy[:N]) and maxU(now) >= cfg.theta_on:
            res_active = True; res_on_t = now; start(N, now)
        if reserve and not res_active and all(busy[:N]) and any(qs.values()):
            tnext = min(qs[k][0] + cfg.theta_on * cfg.target_wait[k] for k in CL if qs[k])
            if tnext > now: push(tnext, 'chk', None)
    if res_active: res_time += T - max(res_on_t, WARM)

    out = {}
    for k in CL:
        w = waits[k]
        if w:
            out[k] = {'mean': st.mean(w), 'p_ok': sum(v <= cfg.target_wait[k] for v in w) / len(w)}
    out['util'] = busyt / (N * (T - WARM)); out['res'] = res_time / (T - WARM)
    num = sum(cfg.weight[k] * out[k]['p_ok'] for k in CL if k in out)
    den = sum(cfg.weight[k] for k in CL if k in out)
    out['K'] = num / den
    return out

def ci(v):
    return 1.96 * st.stdev(v) / math.sqrt(len(v)) if len(v) > 1 else 0.0

def series(cfg, pol, x, reps, seed0):
    """Серия прогонов: средние и 95-% доверительные интервалы."""
    runs = [run(cfg, pol, x, seed0 + r) for r in range(reps)]
    row = {}
    for k in CL:
        m = [q[k]['mean'] for q in runs if k in q]; p = [q[k]['p_ok'] for q in runs if k in q]
        if m: row[k] = {'mean': st.mean(m), 'ci': ci(m), 'p_ok': st.mean(p), 'p_ci': ci(p)}
    for key in ['util', 'res', 'K']:
        v = [q[key] for q in runs]; row[key] = st.mean(v); row[key + '_ci'] = ci(v)
    return row

