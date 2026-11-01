"""
경제성 모듈: 장비 크기 → 설비비(CAPEX) → 톤당 액화비, 회수기간, 냉열 거래가격 구간

장비비는 Turton 교재(Analysis, Synthesis and Design of Chemical Processes) 부록 A의
구매비 상관식과 bare module 계수를 쓴다.
  log10(Cp0) = K1 + K2*log10(A) + K3*(log10 A)^2      (CEPCI = 397 기준, 미국 달러)
  C_BM = Cp0 * F_BM,   총모듈비 C_TM = 1.18 * ΣC_BM
!! 아래 계수는 교재 부록 표 A.1, A.3, A.4와 반드시 한 번 대조한다(Step 6 체크리스트).
개념설계 단계 추정이라 정확도는 ±30% 수준으로 본다.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math

from CoolProp.CoolProp import PropsSI

from .calc import Basis, run, h, T_from_h, K0, BAR

# ---------------------------------------------------------------- Turton 계수 [교재 대조 필요]
TURTON = {
    # 이름: (K1, K2, K3, 최소, 최대, 단위)
    "compressor_centrifugal": (2.2897, 1.3604, -0.1027, 450.0, 3000.0, "kW"),
    "drive_electric":         (2.4604, 1.4191, -0.1798, 75.0, 2600.0, "kW"),
    "hx_floating_head":       (4.8306, -0.8509, 0.3187, 10.0, 1000.0, "m2"),
    "hx_kettle":              (4.4646, -0.5277, 0.3955, 10.0, 100.0, "m2"),
    "pump_centrifugal":       (3.3892, 0.0536, 0.1538, 1.0, 300.0, "kW"),
}
F_BM_COMPRESSOR = {"CS": 2.7, "SS": 5.8}     # 원심 압축기 bare module 계수
F_BM_DRIVE = 1.5
HX_B1, HX_B2 = 1.63, 1.66                     # 쉘앤튜브: F_BM = B1 + B2*F_M*F_P
HX_FM = {"CS/CS": 1.0, "CS/SS": 1.81, "SS/SS": 2.73}
HX_FP_C = (0.03881, -0.11272, 0.08183)        # 쉘·튜브 모두 압력 5~140 barg
PUMP_B1, PUMP_B2 = 1.89, 1.35
PUMP_FM = {"CS": 1.6, "SS": 2.3}
PUMP_FP_C = (-0.3935, 0.3957, -0.00226)       # 10~100 barg
CEPCI_BASE = 397.0


@dataclass
class Econ:
    power_price: float = 180.0       # 원/kWh. 산업용(을) 대기업 182.7원(2024.10 인상 후) 기준
    cold_price: float = 0.0          # 원/t LNG. LNG 기지에 내는 냉열 값
    discount: float = 0.08
    life_y: int = 20
    om_frac: float = 0.03            # 연 유지보수비 = CAPEX의 3% [가정]
    cepci: float = 800.0             # 2023 연평균 797.9, 2025는 2024 대비 +1.6% → 약 800 [가정]
    krw_per_usd: float = 1350.0      # 2026.10.2 1,345.75원 기준 반올림
    capex_err: float = 0.0           # 설비비 오차(민감도용) -0.3 ~ +0.3
    co2_comp_material: str = "SS"    # 습한 CO2를 다루는 압축기는 스테인리스가 보수적
    U_gas: float = 250.0             # W/m2K, CO2 기체 냉각 구간 [가정, 고압 기체 150~500]
    U_cond: float = 700.0            # W/m2K, 응축·증발 구간 [가정, 유기물 응축 300~1200]
    U_liq: float = 400.0             # W/m2K, 액체 구간 [가정]
    U_lng: float = 500.0             # W/m2K, E-202 LNG(초임계 고밀도)↔에탄 응축 [가정]
    T_cw_in: float = 25.0            # 냉각수 입구 온도 [가정]
    T_cw_out: float = 32.0


def crf(i: float, n: int) -> float:
    return i * (1 + i) ** n / ((1 + i) ** n - 1)


def _cp0(kind: str, size: float) -> tuple[float, int]:
    """구매비(달러, CEPCI 397). 범위를 넘으면 같은 크기 여러 대로 나눈다."""
    K1, K2, K3, lo, hi, _ = TURTON[kind]
    n = max(1, math.ceil(size / hi))
    each = max(size / n, lo)
    lg = math.log10(each)
    return n * 10 ** (K1 + K2 * lg + K3 * lg * lg), n


def _fp(C, p_barg: float) -> float:
    if p_barg < 5:
        return 1.0
    lg = math.log10(p_barg)
    return 10 ** (C[0] + C[1] * lg + C[2] * lg * lg)


def cost_compressor(kw: float, material: str) -> dict:
    cp, n = _cp0("compressor_centrifugal", kw)
    cpd, nd = _cp0("drive_electric", kw)
    return {"n": n, "C_BM_usd397": cp * F_BM_COMPRESSOR[material] + cpd * F_BM_DRIVE}


def cost_hx(area: float, fm_key: str, p_barg: float, kind: str = "hx_floating_head") -> dict:
    cp, n = _cp0(kind, area)
    fbm = HX_B1 + HX_B2 * HX_FM[fm_key] * _fp(HX_FP_C, p_barg)
    return {"n": n, "C_BM_usd397": cp * fbm}


def cost_pump(kw: float, material: str, p_barg: float) -> dict:
    cp, n = _cp0("pump_centrifugal", max(kw, 1.0))
    fbm = PUMP_B1 + PUMP_B2 * PUMP_FM[material] * _fp(PUMP_FP_C, max(p_barg, 10.0))
    return {"n": n, "C_BM_usd397": cp * fbm}


# ---------------------------------------------------------------- 열교환기 면적(구간 적분)
def area_co2_cooler(b: Basis, e: Econ, m_kgs: float, T_from: float, T_to: float,
                    T_cold_C: float) -> float:
    """CO2를 T_from → T_to로 식히는 열교환기. 차가운 쪽은 일정 온도(끓는 냉매/에탄).
    잘게 나눠서 구간마다 dA = dQ / (U·ΔT) 를 더한다(상변화 때문에 LMTD 한 번으로는 틀림)."""
    p = b.p_liq_bara()
    h1, h2 = h("CO2", T_from, p), h("CO2", T_to, p)
    h_dew = PropsSI("H", "P", p * BAR, "Q", 1, "CO2") / 1e3
    h_bub = PropsSI("H", "P", p * BAR, "Q", 0, "CO2") / 1e3
    N, A = 200, 0.0
    for i in range(N):
        ha = h1 + (h2 - h1) * (i + 0.5) / N
        dq_W = m_kgs * abs(h2 - h1) / N * 1e3
        T = T_from_h("CO2", ha, p)
        U = e.U_gas if ha > h_dew else (e.U_cond if ha >= h_bub else e.U_liq)
        dT = max(T - T_cold_C, 0.5)
        A += dq_W / (U * dT)
    return A


def area_e202(b: Basis, e: Econ, m_lng_kgs: float, T_in: float, T_out: float,
              T_loop: float) -> float:
    """E-202: LNG(초임계, 70bar) 승온 ↔ 에탄 응축(일정 온도)"""
    h1, h2 = h("Methane", T_in, b.p_lng_bar), h("Methane", T_out, b.p_lng_bar)
    N, A = 200, 0.0
    for i in range(N):
        ha = h1 + (h2 - h1) * (i + 0.5) / N
        dq_W = m_lng_kgs * (h2 - h1) / N * 1e3
        T = T_from_h("Methane", ha, b.p_lng_bar)
        A += dq_W / (e.U_lng * max(T_loop - T, 0.5))
    return A


def lmtd(dt1: float, dt2: float) -> float:
    return (dt1 - dt2) / math.log(dt1 / dt2) if abs(dt1 - dt2) > 1e-6 else dt1


def area_cw_cooler(Q_W: float, T_hot_in: float, T_hot_out: float, e: Econ, U: float) -> float:
    return Q_W / (U * lmtd(T_hot_in - e.T_cw_out, T_hot_out - e.T_cw_in))


def area_ref_condenser(Q_W: float, b: Basis, e: Econ) -> float:
    return Q_W / (e.U_cond * lmtd(b.T_cond_ref_C - e.T_cw_out, b.T_cond_ref_C - e.T_cw_in))


# ---------------------------------------------------------------- 설비 목록과 비용
def equipment(b: Basis, e: Econ, r: dict) -> dict:
    s = r["summary"]
    m = s["co2_tph"] * 1000 / 3600                 # kg/s CO2
    liq, base, lng = r["liquefaction"], r["baseline_refrig"], r["lng"]
    p_barg = b.p_liq_barg

    # 공통: CO2 압축기 + 단간 냉각기 (두 방식에 똑같이 들어감)
    common = []
    for st in r["compression"]["stages"]:
        kw = st["w_kJkg"] * m
        common.append(("CO2 압축기 %d단" % st["stage"], "compressor", kw,
                       cost_compressor(kw, e.co2_comp_material)))
        Q = st["q_cooler_kJkg"] * m * 1e3
        A = area_cw_cooler(Q, st["T_out_C"], b.T_inter_C, e, e.U_gas)
        common.append(("단간 냉각기 %d" % st["stage"], "hx", A,
                       cost_hx(A, "CS/SS", st["p_out_bara"] - 1.0)))

    # 기존 방식: 냉동기(압축기+응축기) + 증발기(CO2 냉각·액화)
    q_ref_W = liq["q_total_kJkg"] * m * 1e3
    w_ref_kW = base["w_kJkg"] * m
    baseline = [("냉동 압축기", "compressor", w_ref_kW, cost_compressor(w_ref_kW, "CS")),
                ("냉매 응축기", "hx", area_ref_condenser(q_ref_W + w_ref_kW * 1e3, b, e),
                 None)]
    baseline[1] = (baseline[1][0], "hx", baseline[1][2], cost_hx(baseline[1][2], "CS/CS", 15.0))
    if base["precool_out_C"] is not None:
        A1 = area_co2_cooler(b, e, m, b.T_inter_C, base["precool_out_C"],
                             base["precool_out_C"] - b.dT_app_K)
        A2 = area_co2_cooler(b, e, m, base["precool_out_C"], liq["T_prod_C"], base["T_evap_low_C"])
        baseline += [("예냉 증발기", "hx", A1, cost_hx(A1, "CS/SS", p_barg)),
                     ("CO2 응축 증발기", "hx", A2, cost_hx(A2, "SS/SS", p_barg))]
    else:
        A = area_co2_cooler(b, e, m, b.T_inter_C, liq["T_prod_C"], base["T_evap_low_C"])
        baseline += [("CO2 응축 증발기", "hx", A, cost_hx(A, "SS/SS", p_barg))]

    # LNG 냉열 방식: E-201(에탄 증발) + E-202(LNG) + 에탄 펌프 + 여름용 보조 냉동기
    A201 = area_co2_cooler(b, e, m, b.T_inter_C, liq["T_prod_C"], lng["T_loop_C"])
    m_lng = m / lng["co2_per_lng"]
    A202 = area_e202(b, e, m_lng, lng["T_lng_pump_out_C"], lng["T_lng_out_C"], lng["T_loop_C"])
    pump_kw = r["pumping"]["w_loop_kWh_t"] * s["co2_tph"]
    aux = r["monthly"]["max_aux_share"]
    lngcase = [("E-201 CO2 응축기(에탄 증발)", "hx", A201, cost_hx(A201, "SS/SS", p_barg)),
               ("E-202 냉열 회수기", "hx", A202, cost_hx(A202, "SS/SS", b.p_lng_bar - 1.0)),
               ("에탄 순환 펌프", "pump", pump_kw, cost_pump(pump_kw, "SS", r["lng"]["p_loop_bar"]))]
    if aux > 1e-6:
        w_aux_kW = base["w_single_kWh_t"] * 3.6 * m * aux
        A_aux = area_co2_cooler(b, e, m * aux, b.T_inter_C, liq["T_prod_C"], base["T_evap_low_C"])
        lngcase += [("보조 냉동 압축기(여름)", "compressor", w_aux_kW, cost_compressor(w_aux_kW, "CS")),
                    ("보조 냉매 응축기", "hx",
                     area_ref_condenser(q_ref_W * aux + w_aux_kW * 1e3, b, e), None),
                    ("보조 증발기", "hx", A_aux, cost_hx(A_aux, "SS/SS", p_barg))]
        i = len(lngcase) - 2
        lngcase[i] = (lngcase[i][0], "hx", lngcase[i][2], cost_hx(lngcase[i][2], "CS/CS", 15.0))

    k = e.cepci / CEPCI_BASE * e.krw_per_usd * (1 + e.capex_err) * 1.18   # → 원, 총모듈비

    def table(items):
        rows = [{"name": n, "type": t, "size": sz, "units": c["n"],
                 "C_TM_krw": c["C_BM_usd397"] * k} for (n, t, sz, c) in items]
        return rows, sum(x["C_TM_krw"] for x in rows)

    common_rows, common_sum = table(common)
    base_rows, base_sum = table(baseline)
    lng_rows, lng_sum = table(lngcase)
    return {"common": common_rows, "baseline": base_rows, "lng": lng_rows,
            "capex_common": common_sum,
            "capex_baseline": common_sum + base_sum, "capex_lng": common_sum + lng_sum}


# ---------------------------------------------------------------- 결과 지표
def evaluate(b: Basis | None = None, e: Econ | None = None) -> dict:
    b, e = b or Basis(), e or Econ()
    r = run(b)
    s = r["summary"]
    eq = equipment(b, e, r)
    C = s["co2_tpy"]
    f = crf(e.discount, e.life_y)

    def annual(capex, kwh_t, cold_cost):
        return {"capex": capex, "annualized_capex": capex * f, "om": capex * e.om_frac,
                "power": kwh_t * C * e.power_price, "cold": cold_cost}

    a_base = annual(eq["capex_baseline"], s["baseline_total_kWh_t"], 0.0)
    a_lng = annual(eq["capex_lng"], s["lng_total_kWh_t"], e.cold_price * s["lng_tpy"])
    for a in (a_base, a_lng):
        a["total"] = a["annualized_capex"] + a["om"] + a["power"] + a["cold"]
        a["lcol_krw_t"] = a["total"] / C

    # 운영비만 놓고 본 연간 이득(냉열 값 제외) → 냉열 가격 상한
    opex_gain = (a_base["om"] + a_base["power"]) - (a_lng["om"] + a_lng["power"])
    capex_gain_ann = (a_base["capex"] - a_lng["capex"]) * f
    hub_gain_before_cold = opex_gain + capex_gain_ann                # 냉열이 공짜일 때 허브의 연간 이득
    cold_price_max = hub_gain_before_cold / s["lng_tpy"]              # 원/t LNG, 이 값이면 허브 이득 0

    d_capex = a_lng["capex"] - a_base["capex"]
    yearly_saving = (a_base["om"] + a_base["power"]) - (a_lng["om"] + a_lng["power"] + a_lng["cold"])
    payback = (d_capex / yearly_saving) if (d_capex > 0 and yearly_saving > 0) else 0.0
    # 연계 배관·인허가 등 '아직 모르는 추가비'를 최대 얼마까지 써도 손해가 아닌가(NPV = 0)
    annuity = 1.0 / f
    max_extra_invest = yearly_saving * annuity - d_capex

    return {
        "calc": r, "equipment": eq, "crf": f,
        "baseline": a_base, "lng": a_lng,
        "indicators": {
            "lcol_baseline_krw_t": a_base["lcol_krw_t"],
            "lcol_lng_krw_t": a_lng["lcol_krw_t"],
            "lcol_baseline_usd_t": a_base["lcol_krw_t"] / e.krw_per_usd,
            "lcol_lng_usd_t": a_lng["lcol_krw_t"] / e.krw_per_usd,
            "lcol_cut_pct": (1 - a_lng["lcol_krw_t"] / a_base["lcol_krw_t"]) * 100,
            "yearly_saving_krw": yearly_saving,
            "d_capex_krw": d_capex,
            "payback_y": payback,
            "max_extra_invest_krw": max_extra_invest,
            "cold_price_max_krw_tLNG": cold_price_max,
            "cold_value_power_only_krw_tLNG": s["saving_kWh_t"] * s["co2_per_lng"] * e.power_price,
        },
        "econ": asdict(e),
    }


if __name__ == "__main__":
    out = evaluate()
    ind = out["indicators"]
    for k, v in ind.items():
        print(f"{k:32s} {v:,.1f}")
