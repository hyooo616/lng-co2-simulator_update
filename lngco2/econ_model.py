"""
[앱 포함용 사본] 원본: 팀원 C의 econ_model.py. 계산식은 그대로이고, 앱 화면에 쓰려고 반환값에 상세 항목만 더했다(B, 10/31).

economics.xlsx(v3, 10/26) 계산을 파이썬으로 그대로 옮긴 파일 (팀원 C → 팀원 B 전달용, 몬테카를로 Step 5 (3))

- 엑셀과 같은 입력을 넣으면 같은 결과가 나온다(검증: 엑셀 v3 기본값과 0.01% 이내).
- 몬테카를로는 evaluate()에 무작위 입력을 넣어 1만 번 돌리면 된다(맨 아래 예시).
- 숫자는 모두 팀 검증 전 [가정]. Turton 계수는 키트 값, 교재 원문 대조는 생략(10/22 팀 결정).
- 이 파일은 생성형 AI(Claude)로 작성했다(AI사용기록 10/22).
"""
import math

# ---------------------------------------------------------------- 기본 입력 (엑셀 '입력' 시트)
BASE = dict(
    p_elec=180.0,        # 전기요금 원/kWh
    cold_price=0.0,      # 냉열 거래가 원/t LNG
    disc=0.08,           # 할인율
    life=20,             # 설비 수명 년
    om=0.03,             # 유지보수비 비율 (CAPEX 대비 연)
    cepci=800.0, cepci_base=397.0, fx=1350.0, f_tm=1.18,
    capex_err=0.0,       # 설비비 오차 (-0.3 ~ +0.3)
    kau=26450.0,         # 배출권 원/t (운전 전략 안 1·3 미처리 비용)
    hours=8000.0,
    lng_tpy=1.0e6,
    inc_p201=0,          # P201 포함(1) / 제외(0)
    # 월별 송출 비율(연평균=1). 가스공사 용도별 월 공급량(도시가스+발전) 기준
    monthly=(1.552, 1.354, 1.154, 0.862, 0.793, 0.743, 0.810, 0.832, 0.720, 0.772, 1.022, 1.385),  # 가스공사 2023~2025 평균(10/26)
)
# 가스공사 연도별 월별 비율(각 해 월 공급량 ÷ 그 해 월평균). 몬테카를로에서 하나씩 뽑아 쓴다
YEAR_CURVES = {
    2016: (1.529, 1.276, 1.151, 0.768, 0.698, 0.718, 0.796, 0.804, 0.718, 0.889, 1.251, 1.402),
    2017: (1.514, 1.335, 1.202, 0.796, 0.647, 0.720, 0.797, 0.723, 0.631, 0.699, 1.222, 1.715),
    2018: (1.617, 1.348, 1.152, 0.909, 0.777, 0.737, 0.782, 0.762, 0.609, 0.857, 1.028, 1.422),
    2019: (1.256, 1.006, 1.009, 0.962, 0.844, 0.767, 1.009, 1.027, 0.830, 0.847, 1.058, 1.386),
    2020: (1.527, 1.341, 1.181, 0.838, 0.604, 0.655, 0.666, 0.785, 0.743, 0.850, 1.128, 1.681),
    2021: (1.609, 1.212, 1.122, 0.901, 0.753, 0.747, 0.839, 0.743, 0.727, 0.864, 1.096, 1.388),
    2022: (1.459, 1.306, 1.208, 0.850, 0.789, 0.777, 0.811, 0.717, 0.701, 0.813, 1.002, 1.566),
    2023: (1.605, 1.365, 1.089, 0.864, 0.745, 0.729, 0.791, 0.801, 0.741, 0.781, 1.075, 1.414),
    2024: (1.556, 1.230, 1.204, 0.810, 0.802, 0.804, 0.857, 0.900, 0.752, 0.750, 0.940, 1.394),
    2025: (1.496, 1.465, 1.168, 0.913, 0.832, 0.697, 0.783, 0.795, 0.667, 0.784, 1.051, 1.348),
}

# DWSIM(팀원 A, 02_DWSIM 탭 10/22) + 키트 값
CO2_TPH = 142.59121           # t/h
KIT_CO2_TPH = 141.29871
W_COMP_KW = (2147.59, 2136.52, 2114.33)
W_P201_KW = 753.33
REF_KWH = 91.71851            # 기존 2단 냉동 kWh/t [키트]
PUMP_KWH = 0.21868            # 에탄 루프 + LNG 추가 손실 kWh/t [키트]
OTHER_KWH = 1.0
KIT_AUX_MAX = 0.25

# Turton (K1, K2, K3, 최소, 최대) [키트 값]
TUR = {"comp": (2.2897, 1.3604, -0.1027, 450, 3000),
       "drive": (2.4604, 1.4191, -0.1798, 75, 2600),
       "hx": (4.8306, -0.8509, 0.3187, 10, 1000),
       "pump": (3.3892, 0.0536, 0.1538, 1, 300)}
FBM = dict(comp_cs=2.7, comp_ss=5.8, drive=1.5, hx_b1=1.63, hx_b2=1.66,
           fm={"CS/CS": 1.0, "CS/SS": 1.81, "SS/SS": 2.73},
           hx_c=(0.03881, -0.11272, 0.08183), pump_b1=1.89, pump_b2=1.35,
           pump_fm={"CS": 1.6, "SS": 2.3}, pump_c=(-0.3935, 0.3957, -0.00226))

# 장비 목록 (엑셀 '설비비' 시트): 태그, 방식, 종류, 재질, 압력 barg, DWSIM 크기, 키트 크기, 보조여부
EQ = [
    ("C101", "공통", "comp", "SS", None, 2147.59, None, False),
    ("C101-M", "공통", "drive", "-", None, 2147.59, None, False),
    ("E101", "공통", "hx", "CS/SS", 1.018, 145.58, None, False),
    ("C102", "공통", "comp", "SS", None, 2136.52, None, False),
    ("C102-M", "공통", "drive", "-", None, 2136.52, None, False),
    ("E102", "공통", "hx", "CS/SS", 3.022, 147.04, None, False),
    ("C103", "공통", "comp", "SS", None, 2114.33, None, False),
    ("C103-M", "공통", "drive", "-", None, 2114.33, None, False),
    ("E103", "공통", "hx", "CS/SS", 7.013, 150.09, None, False),
    ("R-C", "기존", "comp", "CS", None, None, 12959.7079, False),
    ("R-M", "기존", "drive", "-", None, None, 12959.7079, False),
    ("R-E1", "기존", "hx", "CS/CS", 15, None, 3732.9758, False),
    ("R-E2", "기존", "hx", "CS/SS", 7, None, 326.1105, False),
    ("R-E3", "기존", "hx", "SS/SS", 7, None, 2993.4023, False),
    ("E201", "냉열", "hx", "SS/SS", 7, 3553.88, None, False),   # 10/22 U=600 반영
    ("E202", "냉열", "hx", "SS/SS", 69, 1063.34, None, False),
    ("P-LOOP", "냉열", "pump", "SS", 10, None, 19.9973, False),
    ("A-C", "보조", "comp", "CS", None, None, 3406.8745, True),
    ("A-M", "보조", "drive", "-", None, None, 3406.8745, True),
    ("A-E1", "보조", "hx", "CS/CS", 15, None, 954.6612, True),
    ("A-E2", "보조", "hx", "SS/SS", 7, None, 774.8757, True),
    ("P201", "기지", "pump", "SS", 69, 753.33, None, False),
]


def crf(i, n):
    return i * (1 + i) ** n / ((1 + i) ** n - 1)


def fbm(kind, mat, p):
    if kind == "comp":
        return FBM["comp_ss"] if mat == "SS" else FBM["comp_cs"]
    if kind == "drive":
        return FBM["drive"]
    if kind == "hx":
        c = FBM["hx_c"]
        fp = 1.0 if p < 5 else 10 ** (c[0] + c[1] * math.log10(p) + c[2] * math.log10(p) ** 2)
        return FBM["hx_b1"] + FBM["hx_b2"] * FBM["fm"][mat] * fp
    c = FBM["pump_c"]; pp = max(p, 10)
    fp = 10 ** (c[0] + c[1] * math.log10(pp) + c[2] * math.log10(pp) ** 2)
    return FBM["pump_b1"] + FBM["pump_b2"] * FBM["pump_fm"][mat] * fp


def cp0(kind, size):
    k1, k2, k3, lo, hi = TUR[kind]
    n = max(1, math.ceil(size / hi))
    each = max(size / n, lo)
    lg = math.log10(each)
    return n * 10 ** (k1 + k2 * lg + k3 * lg * lg)


def monthly_stats(monthly):
    avg = sum(monthly) / 12
    f = [x / avg for x in monthly]
    return f, min(f)


def evaluate(**kw):
    p = dict(BASE); p.update(kw)
    f, minf = monthly_stats(p["monthly"])
    co2_tpy = CO2_TPH * p["hours"]
    co2_per_lng = co2_tpy / p["lng_tpy"]
    need = co2_tpy / 12
    cap = [p["lng_tpy"] / 12 * x * co2_per_lng for x in f]
    deficit = [max(0.0, need - c) for c in cap]
    aux_share = sum(deficit) / co2_tpy
    aux_max = max(deficit) / need
    comp_kwh = sum(W_COMP_KW) / CO2_TPH
    p201_kwh = W_P201_KW / CO2_TPH
    k = p["f_tm"] * p["cepci"] / p["cepci_base"] * p["fx"] * (1 + p["capex_err"])
    flow = CO2_TPH / KIT_CO2_TPH

    detail = []                                   # (앱용) 장비별 크기·대수·비용 기록

    def capex(scale_all=1.0, aux_on=True, record=False):
        tot = {"공통": 0.0, "기존": 0.0, "냉열": 0.0, "보조": 0.0, "기지": 0.0}
        for tag, grp, kind, mat, pr, dw, kit, aux in EQ:
            size = dw if dw is not None else kit * flow * (aux_max / KIT_AUX_MAX if aux else 1)
            if grp != "기지":
                size *= scale_all
            inc = 1.0
            if aux:
                inc = 1.0 if (aux_on and aux_max > 1e-6) else 0.0
            if grp == "기지":
                inc = p["inc_p201"]
            cost = cp0(kind, size) * fbm(kind, mat, pr if pr is not None else 0) * k * inc / 1e8
            tot[grp] += cost
            if record:
                detail.append(dict(tag=tag, grp=grp, kind=kind, size=size,
                                   n=max(1, math.ceil(size / TUR[kind][4])), cost=cost, inc=inc))
        return tot

    t = capex(record=True)
    capex_base = t["공통"] + t["기존"]
    capex_lng = t["공통"] + t["냉열"] + t["보조"] + t["기지"]
    r = crf(p["disc"], p["life"])
    base_kwh = comp_kwh + REF_KWH
    lng_kwh = comp_kwh + aux_share * REF_KWH + PUMP_KWH + OTHER_KWH + p["inc_p201"] * p201_kwh

    def annual(capx, kwh, tpy, cold):
        return capx * r + capx * p["om"] + kwh * tpy * p["p_elec"] / 1e8 + cold

    cold = p["cold_price"] * p["lng_tpy"] / 1e8
    tot_base = annual(capex_base, base_kwh, co2_tpy, 0)
    tot_lng = annual(capex_lng, lng_kwh, co2_tpy, cold)
    lcol_base = tot_base * 1e8 / co2_tpy
    lcol_lng = tot_lng * 1e8 / co2_tpy
    saving = (capex_base * p["om"] + base_kwh * co2_tpy * p["p_elec"] / 1e8) - \
             (capex_lng * p["om"] + lng_kwh * co2_tpy * p["p_elec"] / 1e8 + cold)
    dcapex = capex_lng - capex_base
    pmax = ((capex_base * p["om"] + base_kwh * co2_tpy * p["p_elec"] / 1e8) -
            (capex_lng * p["om"] + lng_kwh * co2_tpy * p["p_elec"] / 1e8) +
            (capex_base - capex_lng) * r) * 1e8 / p["lng_tpy"]
    limit = saving / r - dcapex

    # 운전 전략 안 1·3 (엑셀 '운전전략' 시트)
    t1 = capex(scale_all=minf, aux_on=False)
    capex1 = t1["공통"] + t1["냉열"] + t1["기지"]
    capex3 = t["공통"] + t["냉열"] + t["기지"]
    kwh13 = comp_kwh + PUMP_KWH + OTHER_KWH + p["inc_p201"] * p201_kwh
    tpy1 = co2_tpy * minf
    tpy3 = sum(min(c, need) for c in cap)
    tot1 = annual(capex1, kwh13, tpy1, cold)
    tot3 = annual(capex3, kwh13, tpy3, cold)
    eff = [(tot1 + (co2_tpy - tpy1) * p["kau"] / 1e8) * 1e8 / co2_tpy,
           tot_lng * 1e8 / co2_tpy,
           (tot3 + (co2_tpy - tpy3) * p["kau"] / 1e8) * 1e8 / co2_tpy]
    return dict(capex_base=capex_base, capex_lng=capex_lng, base_kwh=base_kwh, lng_kwh=lng_kwh,
                lcol_base=lcol_base, lcol_lng=lcol_lng, saving=saving, pmax=pmax, limit=limit,
                lcol_1=tot1 * 1e8 / tpy1, lcol_3=tot3 * 1e8 / tpy3, eff_1=eff[0], eff_2=eff[1], eff_3=eff[2],
                cheaper=lcol_lng < lcol_base,
                # ---- 아래는 앱 화면용으로 추가한 항목 (계산식은 위와 같음) ----
                co2_tpy=co2_tpy, co2_per_lng=co2_per_lng, comp_kwh=comp_kwh, p201_kwh=p201_kwh,
                aux_share=aux_share, aux_max=aux_max, minf=minf, f=f, cap=cap, need=need, deficit=deficit,
                crf=r, cold=cold, tot_base=tot_base, tot_lng=tot_lng, tot1=tot1, tot3=tot3,
                capex1=capex1, capex3=capex3, tpy1=tpy1, tpy3=tpy3, detail=detail)


if __name__ == "__main__":
    out = evaluate()
    for k_, v in out.items():
        print(f"{k_:12s} {v:,.3f}" if isinstance(v, float) else f"{k_:12s} {v}")

    # ---- 몬테카를로 (입력 범위 10/26 확정, 숫자표 참고). 모두 균등분포, 1만 회, 시드 42
    import random
    random.seed(42)
    N = 10000
    res = []
    for _ in range(N):
        s = dict(capex_err=random.uniform(-0.3, 0.3), p_elec=random.uniform(160, 200),
                 cold_price=random.uniform(0, 18400), disc=random.uniform(0.05, 0.10),
                 life=random.randint(15, 25), om=random.uniform(0.02, 0.04),
                 monthly=random.choice(list(YEAR_CURVES.values())),
                 kau=random.uniform(10000, 30000))
        res.append(evaluate(**s))
    p_cheaper = sum(r_["cheaper"] for r_ in res) / N
    print(f"\n기존 방식보다 쌀 확률 {p_cheaper:.1%}")
