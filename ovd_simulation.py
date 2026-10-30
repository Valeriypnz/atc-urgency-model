# -*- coding: utf-8 -*-
"""
Имитационная модель процессов центра ОВД при интеграции БАС
(метод управления на основе индекса срочности).

Один самодостаточный файл: нужен только Python 3.8+ (стандартная библиотека).

Запуск:
    python ovd_simulation.py                    сравнение способов при x = 20 (как табл. 2 статьи)
    python ovd_simulation.py --x 5              то же при 5 полётах БВС в час (текущая интенсивность)
    python ovd_simulation.py --scan             зависимость K от числа полётов БВС (как рис. 2)
    python ovd_simulation.py --ac 30 --x 8      свои исходные данные: 30 ВС/ч, 8 БВС/ч
    python ovd_simulation.py --runs 50          быстрый расчёт (по умолчанию 300 прогонов)
    python ovd_simulation.py --csv out.csv      сохранить результаты в CSV (открывается в Excel)
    python ovd_simulation.py --help             все параметры

Классы задач:
    A — обслуживание пилотируемых ВС (обращения экипажей);
    B — заявки на использование воздушного пространства (полёты БВС);
    C — координация и контроль полётов БВС (донесения);
    D — нештатные ситуации с пилотируемыми ВС и БВС.

Сравниваемые способы организации работы (жёсткая секторизация):
    С1  — без помощи, приоритеты D > A > C > B;
    С2  — индекс срочности внутри сектора, без помощи;
    С3  — помощь по докладу, идеализированная (очередь >= 2 задач, помощь сразу);
    С3р — помощь руководителя полётов по докладу, реалистичная
          (доклад через 1 мин, помощь не более 25 % смены);
    С4  — предлагаемый метод: правило (6) + резервный диспетчер,
          подключение при U >= 1, отключение при U < 0,5;
    4сек — постоянное четвёртое рабочее место (нарезка четырёх секторов);
    БВС  — постоянное отдельное место для задач B и C из всех секторов.
"""
import argparse
import csv
import heapq
import math
import random
import statistics as st

CL = ['A', 'B', 'C', 'D']                 # классы задач
PRIO = {'D': 0, 'A': 1, 'C': 2, 'B': 3}   # жёсткие приоритеты (меньше — важнее)


# =============================== ПАРАМЕТРЫ ===============================
def make_config(ac=27, calls=1.2, n_sectors=3, shift_h=7.0, warmup_h=1.0,
                p_emerg=0.0001, cv=0.5, reports=4):
    """Исходные данные модели (значения по умолчанию — табл. 1 статьи)."""
    return {
        'N': n_sectors,                  # число секторов (рабочих мест диспетчеров)
        'T': shift_h * 60,               # продолжительность смены, мин
        'WARM': warmup_h * 60,           # период установления (не учитывается), мин
        # интенсивность потоков, задач/ч:  lambda_k(x) = base_k + per_flight_k * x
        'base': {'A': ac * calls, 'B': 0.0, 'C': 0.0, 'D': ac * p_emerg},
        'per_flight': {'A': 0.0, 'B': 1.0, 'C': float(reports), 'D': p_emerg},
        # среднее время выполнения задачи, мин
        'mean': {'A': 1.0, 'B': 1.0, 'C': 1.0, 'D': 15.0},
        # норматив допустимого ожидания tau_k, мин
        'tau': {'A': 0.5, 'B': 30.0, 'C': 0.5, 'D': 0.5},
        # веса в интегральном показателе K (D оценивается отдельно, см. статью)
        'w': {'A': 1.0, 'B': 1.0, 'C': 1.0, 'D': 0.0},
        'cv': cv,                        # коэффициент вариации времени выполнения
    }


VARIANTS = {
    'С1':   dict(rule='prio'),
    'С2':   dict(rule='urg'),
    'С3':   dict(rule='prio', reserve='qlen'),
    'С3р':  dict(rule='prio', reserve='qlen', rdelay=1.0, rcap=0.25),
    'С4':   dict(rule='urg', reserve='float'),
    '4сек': dict(rule='prio', extra_sector=True),
    'БВС':  dict(rule='prio', reserve='dedicated', rp_classes={'B', 'C'}),
}
NAMES = {
    'С1': 'С1: без помощи', 'С2': 'С2: индекс в секторе',
    'С3': 'С3: по докладу, идеал.', 'С3р': 'С3р: по докладу, реал.',
    'С4': 'С4: предлагаемый метод', '4сек': 'Четыре сектора',
    'БВС': 'Место для задач по БВС',
}


def load(cfg, x):
    """Средняя загруженность диспетчера сектора, формула (2): Кз = (1/N) * sum(lambda_k * m_k)."""
    return sum((cfg['base'][k] + cfg['per_flight'][k] * x) * cfg['mean'][k] for k in CL) / 60 / cfg['N']


# ================================ МОДЕЛЬ ================================
def run(cfg, x, seed, rule='prio', reserve=None, th=1.0, rp_classes=None,
        extra_sector=False, QON=2, rdelay=0.0, rcap=None):
    """Один прогон смены (дискретно-событийное моделирование с календарём событий).

    rule:    'prio' — жёсткие приоритеты D > A > C > B; 'urg' — правило (6):
             D безусловно, иначе класс с максимальным индексом срочности U = ожидание / tau.
    reserve: None — без помощи; 'qlen' — помощь по докладу (очередь >= QON);
             'float' — резервный диспетчер по индексу срочности (порог th, отключение th/2);
             'dedicated' — постоянное место для классов rp_classes.
    rdelay — задержка доклада, мин; rcap — предельная доля смены для помощи.
    """
    N = cfg['N'] + (1 if extra_sector else 0)
    T, WARM = cfg['T'], cfg['WARM']
    rng = random.Random(seed)
    L = {k: (cfg['base'][k] + cfg['per_flight'][k] * x) / 60 for k in CL}   # задач/мин
    tau = cfg['tau']
    s2 = math.log(1 + cfg['cv'] ** 2)

    def service(k):                     # логнормальное время выполнения
        m = cfg['mean'][k]
        return rng.lognormvariate(math.log(m) - s2 / 2, math.sqrt(s2))

    ev, cnt = [], [0]                   # календарь событий (двоичная куча)
    qs = [{k: [] for k in CL} for _ in range(N)]   # очереди секторов
    rq = {k: [] for k in CL}            # очередь отдельного места (вариант «БВС»)
    busy = [False] * N
    st_ = dict(rbusy=False, ractive=False, ron=None, rtime=0.0, rall=0.0, pend=False)
    waits = {k: [] for k in CL}
    bt = {}                             # занятое время исполнителей

    def push(t, typ, o):
        cnt[0] += 1
        heapq.heappush(ev, (t, cnt[0], typ, o))

    for k in CL:
        if L[k] > 0:
            push(rng.expovariate(L[k]), 'arr', k)

    def U(q, k, now):                   # индекс срочности (5)
        return (now - q[k][0]) / tau[k]

    def pick(q, now):                   # правило выбора задачи
        cand = [k for k in CL if q[k]]
        if not cand:
            return None
        if rule == 'prio':
            return min(cand, key=lambda c: PRIO[c])
        if 'D' in cand:
            return 'D'
        return max(cand, key=lambda c: U(q, c, now))

    def serve(q, k, now, who):
        t0 = q[k].pop(0)
        if t0 >= WARM:
            waits[k].append(now - t0)
        d = service(k)
        a, b = max(now, WARM), min(now + d, T)
        if b > a:
            bt[who] = bt.get(who, 0) + b - a
        push(now + d, 'dep', who)

    def start(s, now):
        k = pick(qs[s], now)
        if k is None:
            busy[s] = False
            return
        busy[s] = True
        serve(qs[s], k, now, s)

    def maxU_sec(now):                  # сектор с наибольшим индексом (D — вне конкуренции)
        best = (-1, None)
        for s in range(N):
            for k in CL:
                if qs[s][k]:
                    u = U(qs[s], k, now) + (100 if k == 'D' else 0)
                    if u > best[0]:
                        best = (u, s)
        return best

    def maxQ():                         # сектор с наибольшей очередью
        best = (-1, None)
        for s in range(N):
            n = sum(len(qs[s][k]) for k in CL)
            if n > best[0]:
                best = (n, s)
        return best

    def r_off(now):
        st_['rbusy'] = False
        if st_['ractive']:
            st_['ractive'] = False
            st_['rall'] += now - st_['ron']
            if now > WARM:
                st_['rtime'] += now - max(st_['ron'], WARM)

    def over_cap(now):
        return (rcap is not None and st_['ractive']
                and (st_['rall'] + now - st_['ron']) / max(now, 1e-9) >= rcap)

    def capok(now):
        return rcap is None or st_['rall'] / max(now, 1e-9) < rcap

    def rstart(now):                    # резерв выбирает следующую задачу
        if reserve == 'qlen':
            n, s = maxQ()
            if n <= 0 or over_cap(now):
                r_off(now)
                return
            st_['rbusy'] = True
            serve(qs[s], pick(qs[s], now), now, 'R')
            return
        if reserve == 'dedicated':
            k = pick(rq, now)
            if k is None:
                st_['rbusy'] = False
                return
            st_['rbusy'] = True
            serve(rq, k, now, 'R')
            return
        u, s = maxU_sec(now)            # 'float' — предлагаемый метод
        if u < th / 2 or s is None or over_cap(now):
            r_off(now)
            return
        st_['rbusy'] = True
        serve(qs[s], pick(qs[s], now), now, 'R')

    def r_on(now):
        st_['ractive'] = True
        st_['ron'] = now
        if not st_['rbusy']:
            rstart(now)

    while ev:
        now, _, typ, o = heapq.heappop(ev)
        if typ == 'arr':
            if now > T:
                continue
            push(now + rng.expovariate(L[o]), 'arr', o)
            if reserve == 'dedicated' and o in rp_classes:
                rq[o].append(now)
                if not st_['rbusy']:
                    rstart(now)
            else:
                s = rng.randrange(N)
                qs[s][o].append(now)
                if not busy[s]:
                    start(s, now)
        elif typ == 'dep':
            if o == 'R':
                rstart(now)
            else:
                start(o, now)
        # помощь по докладу
        if typ == 'rep':
            st_['pend'] = False
            if reserve == 'qlen' and not st_['ractive'] and maxQ()[0] >= QON and capok(now):
                r_on(now)
        elif reserve == 'qlen' and not st_['ractive'] and maxQ()[0] >= QON:
            if rdelay > 0:
                if not st_['pend']:
                    st_['pend'] = True
                    push(now + rdelay, 'rep', None)
            elif capok(now):
                r_on(now)
        # предлагаемый метод: подключение при U >= th, иначе контрольное событие
        if reserve == 'float' and not st_['ractive']:
            u, s = maxU_sec(now)
            if s is not None and u >= th and capok(now):
                r_on(now)
            elif s is not None:
                tn = min(qs[ss][k][0] + th * tau[k] for ss in range(N) for k in CL if qs[ss][k])
                if tn > now:
                    push(tn, 'chk', None)

    if st_['ractive']:
        st_['rtime'] += T - max(st_['ron'], WARM)

    out = {}
    for k in CL:
        w = waits[k]
        if w:
            out[k] = sum(v <= tau[k] for v in w) / len(w)
    ks = [k for k in CL if k in out and cfg['w'][k] > 0]
    out['K'] = sum(cfg['w'][k] * out[k] for k in ks) / sum(cfg['w'][k] for k in ks)
    ac = [(v, tau[k]) for k in 'ABC' for v in waits[k]]
    out['viol'] = sum(v > t for v, t in ac) / len(ac) if ac else 0.0
    dur = T - WARM
    rho = [bt.get(s, 0) / dur for s in range(N)]
    rhoR = bt.get('R', 0) / dur
    out['kz_max'] = max(max(rho), rhoR)
    if reserve in ('float', 'qlen'):
        out['R'] = st_['rtime'] / dur
    elif reserve == 'dedicated':
        out['R'] = 1.0
    else:
        out['R'] = None
    return out


# ============================== ЭКСПЕРИМЕНТЫ ==============================
def series(cfg, x, runs, variant, th=1.0, seed0=1000):
    """Серия прогонов: средние значения и 95-процентный доверительный интервал K."""
    kw = dict(VARIANTS[variant])
    if kw.get('reserve') == 'float':
        kw['th'] = th
    rs = [run(cfg, x, seed0 + i, **kw) for i in range(runs)]
    def mean(key):
        v = [r[key] for r in rs if r.get(key) is not None]
        return st.mean(v) if v else None
    K = [r['K'] for r in rs]
    row = {
        'variant': variant, 'x': x, 'K': st.mean(K),
        'K_ci': 1.96 * st.stdev(K) / math.sqrt(len(K)) if len(K) > 1 else 0.0,
        'PA': mean('A'), 'PC': mean('C'),
        'PD': mean('D'),
        'viol': 100 * mean('viol'), 'kz_max': mean('kz_max'),
        'R': mean('R'),
    }
    return row


def fmt(v, nd=3):
    if v is None:
        return '—'
    return f'{v:.{nd}f}'.replace('.', ',')


def main():
    ap = argparse.ArgumentParser(description='Имитационная модель центра ОВД (индекс срочности)')
    ap.add_argument('--x', type=float, default=20, help='полётов БВС в час (по умолчанию 20)')
    ap.add_argument('--ac', type=float, default=27, help='пилотируемых ВС в час (по умолчанию 27)')
    ap.add_argument('--calls', type=float, default=1.2, help='задач класса A на один пролёт, по 1 мин каждая, т. е. 1,2 мин работы (1,2)')
    ap.add_argument('--reports', type=float, default=4, help='донесений на полёт БВС (4)')
    ap.add_argument('--sectors', type=int, default=3, help='число секторов (3)')
    ap.add_argument('--shift', type=float, default=7, help='продолжительность смены, ч (7)')
    ap.add_argument('--pd', type=float, default=0.0001, help='вероятность нештатной ситуации на полёт (0,0001)')
    ap.add_argument('--cv', type=float, default=0.5, help='коэффициент вариации времени (0,5)')
    ap.add_argument('--theta', type=float, default=1.0, help='порог подключения резерва (1,0)')
    ap.add_argument('--runs', type=int, default=300, help='число прогонов (300)')
    ap.add_argument('--variants', default='С1,С2,С3,С3р,С4,4сек,БВС', help='способы через запятую')
    ap.add_argument('--scan', action='store_true', help='расчёт K для x = 0, 5, ..., 30')
    ap.add_argument('--csv', help='сохранить результаты в CSV-файл')
    a = ap.parse_args()

    cfg = make_config(ac=a.ac, calls=a.calls, n_sectors=a.sectors, shift_h=a.shift,
                      p_emerg=a.pd, cv=a.cv, reports=a.reports)
    variants = [v.strip() for v in a.variants.split(',') if v.strip() in VARIANTS]
    rows = []

    if a.scan:
        xs = [0, 5, 8, 10, 12, 15, 18, 20, 25, 30]
        sel = [v for v in variants if v in ('С1', 'С3', 'С3р', 'С4')] or variants
        print(f'\nЗависимость K от интенсивности полётов БВС ({a.ac:g} ВС/ч, {a.sectors} сектора, '
              f'{a.runs} прогонов)\n')
        print(f'{"x":>4} {"Кз":>6} ' + ''.join(f'{v:>9}' for v in sel))
        for x in xs:
            line = f'{x:>4} {fmt(load(cfg, x), 2):>6} '
            for v in sel:
                r = series(cfg, x, a.runs, v, a.theta)
                rows.append(r)
                line += f'{fmt(r["K"]):>9}'
            print(line)
        print('\nКз — средняя загруженность диспетчера сектора (допустимо 0,55, предельно 0,70).')
    else:
        print(f'\nИсходные данные: {a.ac:g} ВС/ч, {a.x:g} полётов БВС/ч, {a.sectors} сектора, '
              f'смена {a.shift:g} ч, {a.runs} прогонов')
        rho = load(cfg, a.x)
        status = 'в норме' if rho <= 0.55 else ('выше допустимого 0,55' if rho <= 0.70
                                                 else 'ВЫШЕ ПРЕДЕЛЬНОГО 0,70')
        print(f'Средняя загруженность сектора Кз = {fmt(rho, 2)} ({status})\n')
        hdr = f'{"Способ":<26}{"K":>7}{"±95%":>7}{"PA":>7}{"PC":>7}{"Наруш.,%":>10}{"Кз max":>8}{"R":>7}'
        print(hdr)
        print('-' * len(hdr))
        for v in variants:
            r = series(cfg, a.x, a.runs, v, a.theta)
            rows.append(r)
            print(f'{NAMES[v]:<26}{fmt(r["K"]):>7}{fmt(r["K_ci"]):>7}{fmt(r["PA"]):>7}'
                  f'{fmt(r["PC"]):>7}{fmt(r["viol"], 1):>10}{fmt(r["kz_max"]):>8}{fmt(r["R"]):>7}')
        print('\nK — доля задач A–C, выполненных в пределах норматива; PA, PC — то же по классам;'
              '\nНаруш. — доля задач с нарушением норматива; Кз max — загрузка самого загруженного'
              '\nрабочего места; R — доля смены, в течение которой работает резерв.')

    if a.csv:
        keys = ['variant', 'x', 'K', 'K_ci', 'PA', 'PC', 'PD', 'viol', 'kz_max', 'R']
        with open(a.csv, 'w', newline='', encoding='utf-8-sig') as f:
            wr = csv.DictWriter(f, fieldnames=keys, delimiter=';')
            wr.writeheader()
            for r in rows:
                wr.writerow({k: ('' if r[k] is None else (str(round(r[k], 4)).replace('.', ',')
                             if isinstance(r[k], float) else r[k])) for k in keys})
        print(f'\nРезультаты сохранены: {a.csv}')


if __name__ == '__main__':
    main()
