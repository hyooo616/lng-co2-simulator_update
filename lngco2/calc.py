"""
공정 계산 모듈 (물성: CoolProp)

이 파일 하나로 "기존 냉동기 방식"과 "LNG 냉열 연계 방식"의 CO2 액화 전력을 계산한다.
DWSIM 결과와 대조하는 기준값이자, 웹 시뮬레이터가 쓰는 계산 엔진이다.

단위 약속
  - 압력: 함수 안에서는 Pa, 입력/출력은 bar(a)
  - 온도: 입력/출력은 ℃, CoolProp 호출 때만 K
  - 엔탈피: kJ/kg,  전력: kWh/t(CO2 1톤당)
CoolProp의 CO2는 Span-Wagner, 메탄은 Setzmann-Wagner 기준식을 쓴다.
(DWSIM의 Peng-Robinson보다 정밀한 '참값'에 가까운 식이라 교차 확인용으로 좋다.)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import math

from CoolProp.CoolProp import PropsSI

K0 = 273.15
BAR = 1e5
ATM_BAR = 1.01325

# 월별 LNG 송출 비율(연평균 = 1.0). 1월~12월.
# [가정] 한국가스공사 용도별 월 공급량(도시가스+발전) 2023~2025 연도별 비율의 평균(숫자표 10/26, monthly_lng.csv와 같은 값).
# 광양 터미널 월별 송출량은 공개되지 않아 전국 비율을 대리 지표로 쓴다. 2025년 2월 ÷ 8월 = 1.84배(공시값과 같음).
DEFAULT_MONTHLY = (1.552, 1.354, 1.154, 0.862, 0.793, 0.743, 0.810, 0.832, 0.720, 0.772, 1.022, 1.385)


@dataclass
class Basis:
    """설계 기준. 기획안 7장 표와 같은 값이어야 한다."""
    lng_tpy: float = 1.0e6          # 냉열을 쓰는 LNG 양 [t/년]
    p_liq_barg: float = 7.0         # 액화(저장) 압력, 게이지 [barg]. 저압 운송 7, 중압 15
    p_feed_bara: float = 1.013      # 포집 CO2 압력 [bara]
    T_feed_C: float = 35.0          # 포집 CO2 온도
    n_stages: int = 3               # 압축 단수
    eta_comp: float = 0.80          # 압축기 등엔트로피 효율
    T_inter_C: float = 35.0         # 단간·후단 냉각 온도(냉각수)
    subcool_K: float = 2.0          # 제품을 포화온도보다 몇 도 더 차갑게
    dT_app_K: float = 5.0           # CO2 쪽 열교환기 최소 온도차
    dT_app_lng_K: float = 10.0      # LNG 쪽 열교환기(E-202) 최소 온도차
    T_cond_ref_C: float = 40.0      # 냉동기 응축 온도(냉각수 + 5)
    eta_carnot: float = 0.50        # 냉동기 성능 = 이론(카르노) 성능 × 이 값
    refrig_mode: str = "two_level"  # 기존 방식 냉동: "two_level"(2단, 공정한 비교) | "single"(1단)
    p_lng_bar: float = 70.0         # LNG 송출 압력 [bar]
    T_lng_tank_C: float = -162.0    # 탱크 LNG 온도
    eta_pump: float = 0.75          # 펌프 효율
    dp_lng_extra_bar: float = 1.0   # E-202를 끼워서 늘어나는 LNG 쪽 압력손실 [bar]
    loop_fluid: str = "Ethane"      # 중간 열매체
    loop_margin_K: float = 4.0      # 열매체 온도를 CO2 삼중점보다 최소 몇 도 위로
    dp_loop_bar: float = 2.0        # 열매체 루프 순환 압력손실 [bar]
    loop_loss: float = 0.05         # 냉열 전달 중 손실(외부 열침입) 비율
    other_aux_kwh_t: float = 1.0    # 계장·히트트레이싱 등 기타 보조 전력 [kWh/t] [가정]
    design_basis: str = "annual"    # "annual"(연평균 기준) | "summer"(여름 최저 기준)
    monthly: tuple = DEFAULT_MONTHLY
    hours_per_year: float = 8000.0  # 연간 가동 시간 [h] [가정]

    def p_liq_bara(self) -> float:
        return self.p_liq_barg + ATM_BAR


# ---------------------------------------------------------------- 물성 도우미
def h(fluid: str, T_C: float, p_bar: float) -> float:
    """엔탈피 [kJ/kg]"""
    return PropsSI("H", "T", T_C + K0, "P", p_bar * BAR, fluid) / 1e3


def T_from_h(fluid: str, h_kJ: float, p_bar: float) -> float:
    """엔탈피·압력 → 온도 [℃] (2상 영역이면 포화온도)"""
    return PropsSI("T", "H", h_kJ * 1e3, "P", p_bar * BAR, fluid) - K0


def Tsat(fluid: str, p_bar: float) -> float:
    return PropsSI("T", "P", p_bar * BAR, "Q", 0, fluid) - K0


def Psat(fluid: str, T_C: float) -> float:
    return PropsSI("P", "T", T_C + K0, "Q", 0, fluid) / BAR


def kJkg_to_kWh_t(x: float) -> float:
    """kJ/kg → kWh/t  (1 kJ/kg = 1 MJ/t = 1/3.6 kWh/t)"""
    return x / 3.6


# ---------------------------------------------------------------- 1. CO2 압축
def compression(b: Basis) -> dict:
    """다단 압축 + 단간 냉각. 단마다 같은 압력비."""
    p_in, p_out = b.p_feed_bara, b.p_liq_bara()
    r = (p_out / p_in) ** (1.0 / b.n_stages)
    stages, w_total, q_cw = [], 0.0, 0.0
    p, T_in = p_in, b.T_feed_C
    for i in range(b.n_stages):
        p2 = p * r
        h1 = h("CO2", T_in, p)
        s1 = PropsSI("S", "T", T_in + K0, "P", p * BAR, "CO2")
        h2s = PropsSI("H", "S", s1, "P", p2 * BAR, "CO2") / 1e3
        h2 = h1 + (h2s - h1) / b.eta_comp
        T2 = T_from_h("CO2", h2, p2)
        q_cool = h2 - h("CO2", b.T_inter_C, p2)        # 단간(또는 후단) 냉각기가 빼는 열
        stages.append({"stage": i + 1, "p_in_bara": p, "p_out_bara": p2, "T_in_C": T_in,
                       "T_out_C": T2, "w_kJkg": h2 - h1, "q_cooler_kJkg": q_cool})
        w_total += h2 - h1
        q_cw += q_cool
        p, T_in = p2, b.T_inter_C
    return {"pressure_ratio": r, "stages": stages, "w_kJkg": w_total,
            "w_kWh_t": kJkg_to_kWh_t(w_total), "q_cw_kJkg": q_cw}


# ---------------------------------------------------------------- 2. 액화 열량
def liquefaction_duty(b: Basis) -> dict:
    """35℃ 기체 CO2를 포화온도 - subcool 의 액체로 만들 때 빼야 하는 열"""
    p = b.p_liq_bara()
    Ts = Tsat("CO2", p)
    T_prod = Ts - b.subcool_K
    h_in = h("CO2", b.T_inter_C, p)
    h_dew = PropsSI("H", "P", p * BAR, "Q", 1, "CO2") / 1e3
    h_bub = PropsSI("H", "P", p * BAR, "Q", 0, "CO2") / 1e3
    h_out = h("CO2", T_prod, p)
    return {"p_bara": p, "Tsat_C": Ts, "T_prod_C": T_prod, "h_in": h_in, "h_dew": h_dew,
            "h_bub": h_bub, "h_out": h_out,
            "q_total_kJkg": h_in - h_out,
            "q_sensible_kJkg": h_in - h_dew,
            "q_latent_kJkg": h_dew - h_bub,
            "q_subcool_kJkg": h_bub - h_out}


# ---------------------------------------------------------------- 3. 기존 방식 냉동기
def cop(b: Basis, T_evap_C: float) -> float:
    """냉동기 성능계수 = 카르노 × eta"""
    Te, Tc = T_evap_C + K0, b.T_cond_ref_C + K0
    return b.eta_carnot * Te / (Tc - Te)


def refrigeration_baseline(b: Basis, liq: dict) -> dict:
    """기존 방식: 전기 냉동기로 액화 열을 전부 뺀다.
    single   : 한 온도(가장 낮은 증발온도)에서 전부 냉각
    two_level: 예냉(높은 증발온도) + 응축(낮은 증발온도) 2단. 현업에서 흔한 구성이라 공정한 비교 기준.
    """
    p = liq["p_bara"]
    T_e_low = liq["T_prod_C"] - b.dT_app_K
    q = liq["q_total_kJkg"]
    single = q / cop(b, T_e_low)
    best = {"T1_C": None, "w_kJkg": single, "q1": 0.0, "q2": q}
    if b.refrig_mode == "two_level":
        T_hi = b.T_inter_C - 1.0
        T_lo = liq["Tsat_C"] + 0.5
        n = 120
        for i in range(n + 1):
            T1 = T_lo + (T_hi - T_lo) * i / n          # 예냉 출구 온도 후보
            q1 = liq["h_in"] - h("CO2", T1, p)
            q2 = q - q1
            w = q1 / cop(b, T1 - b.dT_app_K) + q2 / cop(b, T_e_low)
            if w < best["w_kJkg"]:
                best = {"T1_C": T1, "w_kJkg": w, "q1": q1, "q2": q2}
    w = best["w_kJkg"] if b.refrig_mode == "two_level" else single
    return {"mode": b.refrig_mode, "T_evap_low_C": T_e_low, "cop_low": cop(b, T_e_low),
            "precool_out_C": best["T1_C"], "q_precool_kJkg": best["q1"], "q_main_kJkg": best["q2"],
            "w_kJkg": w, "w_kWh_t": kJkg_to_kWh_t(w),
            "w_single_kWh_t": kJkg_to_kWh_t(single)}


# ---------------------------------------------------------------- 4. LNG 냉열과 열매체 루프
def lng_side(b: Basis, liq: dict) -> dict:
    T_triple = PropsSI("Ttriple", "CO2") - K0                       # -56.56 ℃
    T_loop = max(liq["T_prod_C"] - b.dT_app_K, T_triple + b.loop_margin_K)
    approach_E201 = liq["T_prod_C"] - T_loop                          # E-201 차가운 쪽 온도차
    p_loop = Psat(b.loop_fluid, T_loop)
    hfg = (PropsSI("H", "T", T_loop + K0, "Q", 1, b.loop_fluid)
           - PropsSI("H", "T", T_loop + K0, "Q", 0, b.loop_fluid)) / 1e3
    rho_loop = PropsSI("D", "T", T_loop + K0, "Q", 0, b.loop_fluid)

    # LNG 펌프 출구 상태(기지에 원래 있는 펌프. 우리 비용이 아님)
    p_tank = ATM_BAR
    h_tank = h("Methane", b.T_lng_tank_C, p_tank)
    s_tank = PropsSI("S", "T", b.T_lng_tank_C + K0, "P", p_tank * BAR, "Methane")
    h_p_s = PropsSI("H", "S", s_tank, "P", b.p_lng_bar * BAR, "Methane") / 1e3
    h_pump_out = h_tank + (h_p_s - h_tank) / b.eta_pump
    T_pump_out = T_from_h("Methane", h_pump_out, b.p_lng_bar)

    T_lng_out = T_loop - b.dT_app_lng_K
    cold_kJkg = h("Methane", T_lng_out, b.p_lng_bar) - h_pump_out   # LNG 1kg이 주는 냉열
    co2_per_lng = cold_kJkg * (1 - b.loop_loss) / liq["q_total_kJkg"]

    # 참고: LNG를 상온(10℃)까지 데울 때 전체 냉열과, 그중 일로 바꿀 수 있는 최대치(엑서지)
    T0 = 15.0
    h10 = h("Methane", 10.0, b.p_lng_bar)
    s_p = PropsSI("S", "H", h_pump_out * 1e3, "P", b.p_lng_bar * BAR, "Methane")
    s10 = PropsSI("S", "T", 10.0 + K0, "P", b.p_lng_bar * BAR, "Methane")
    exergy = (h_pump_out - h10) - (T0 + K0) * (s_p - s10) / 1e3
    rho_lng = PropsSI("D", "H", h_pump_out * 1e3, "P", b.p_lng_bar * BAR, "Methane")

    return {"T_loop_C": T_loop, "approach_E201_K": approach_E201, "p_loop_bar": p_loop,
            "hfg_loop_kJkg": hfg, "rho_loop": rho_loop,
            "T_lng_pump_out_C": T_pump_out, "T_lng_out_C": T_lng_out,
            "cold_kJkg_LNG": cold_kJkg, "co2_per_lng": co2_per_lng,
            "cold_total_to_10C_kJkg": h10 - h_pump_out,
            "exergy_to_10C_kWh_tLNG": kJkg_to_kWh_t(exergy),
            "rho_lng": rho_lng}


def pumping(b: Basis, liq: dict, lng: dict) -> dict:
    """열매체 순환 펌프 + LNG 쪽 추가 압력손실 [kWh/tCO2]"""
    m_loop = liq["q_total_kJkg"] / lng["hfg_loop_kJkg"]               # kg 열매체 / kg CO2
    w_loop = m_loop * (b.dp_loop_bar * BAR / lng["rho_loop"]) / b.eta_pump / 1e3   # kJ/kg CO2
    m_lng = 1.0 / lng["co2_per_lng"]                                   # kg LNG / kg CO2
    w_lng = m_lng * (b.dp_lng_extra_bar * BAR / lng["rho_lng"]) / b.eta_pump / 1e3
    return {"m_loop_per_co2": m_loop, "w_loop_kWh_t": kJkg_to_kWh_t(w_loop),
            "w_lng_extra_kWh_t": kJkg_to_kWh_t(w_lng),
            "w_total_kWh_t": kJkg_to_kWh_t(w_loop + w_lng)}


# ---------------------------------------------------------------- 5. 월별 하이브리드 운전
def monthly_hybrid(b: Basis, liq: dict, lng: dict, base: dict) -> dict:
    f = [x / (sum(b.monthly) / 12.0) for x in b.monthly]               # 평균 1로 정규화
    ratio = lng["co2_per_lng"]
    if b.design_basis == "summer":
        co2_tpy = b.lng_tpy * min(f) * ratio
    else:
        co2_tpy = b.lng_tpy * ratio
    load_m = co2_tpy / 12.0
    rows, deficit_t = [], 0.0
    # 보조 냉동기는 기존 방식과 같은 구성(같은 kWh/t)으로 모자란 몫만 처리한다고 본다
    for m, fm in enumerate(f, start=1):
        cap = b.lng_tpy / 12.0 * fm * ratio                           # 이 달 냉열로 액화 가능한 CO2 [t]
        deficit = max(0.0, load_m - cap)
        deficit_t += deficit
        rows.append({"month": m, "factor": fm, "lng_t": b.lng_tpy / 12.0 * fm,
                     "capacity_co2_t": cap, "load_co2_t": load_m, "aux_co2_t": deficit,
                     "surplus_co2_t": max(0.0, cap - load_m)})
    aux_share = deficit_t / co2_tpy
    max_aux_share = max(r["aux_co2_t"] for r in rows) / load_m
    return {"co2_tpy": co2_tpy, "rows": rows, "aux_share": aux_share,
            "max_aux_share": max_aux_share,
            "aux_kWh_t": aux_share * base["w_kWh_t"]}


# ---------------------------------------------------------------- 6. 전체
def run(b: Basis | None = None) -> dict:
    b = b or Basis()
    comp = compression(b)
    liq = liquefaction_duty(b)
    base = refrigeration_baseline(b, liq)
    lng = lng_side(b, liq)
    pump = pumping(b, liq, lng)
    mon = monthly_hybrid(b, liq, lng, base)

    baseline_kWh_t = comp["w_kWh_t"] + base["w_kWh_t"]
    lng_kWh_t = comp["w_kWh_t"] + mon["aux_kWh_t"] + pump["w_total_kWh_t"] + b.other_aux_kwh_t
    saving_kWh_t = baseline_kWh_t - lng_kWh_t
    return {
        "basis": asdict(b),
        "compression": comp, "liquefaction": liq, "baseline_refrig": base,
        "lng": lng, "pumping": pump, "monthly": mon,
        "summary": {
            "co2_tpy": mon["co2_tpy"],
            "co2_tph": mon["co2_tpy"] / b.hours_per_year,
            "lng_tpy": b.lng_tpy,
            "co2_per_lng": lng["co2_per_lng"],
            "compression_kWh_t": comp["w_kWh_t"],
            "baseline_cooling_kWh_t": base["w_kWh_t"],
            "baseline_total_kWh_t": baseline_kWh_t,
            "lng_aux_chiller_kWh_t": mon["aux_kWh_t"],
            "lng_pumps_kWh_t": pump["w_total_kWh_t"],
            "lng_other_kWh_t": b.other_aux_kwh_t,
            "lng_total_kWh_t": lng_kWh_t,
            "saving_kWh_t": saving_kWh_t,
            "saving_pct": saving_kWh_t / baseline_kWh_t * 100.0,
            "cooling_saving_pct": (base["w_kWh_t"] - mon["aux_kWh_t"] - pump["w_total_kWh_t"]
                                   - b.other_aux_kwh_t) / base["w_kWh_t"] * 100.0,
            "saving_MWh_y": saving_kWh_t * mon["co2_tpy"] / 1e3,
            "T_loop_C": lng["T_loop_C"], "p_loop_bar": lng["p_loop_bar"],
            "freeze_margin_K": lng["T_loop_C"] - (PropsSI("Ttriple", "CO2") - K0),
        },
    }


if __name__ == "__main__":
    import json
    r = run()
    print(json.dumps(r["summary"], indent=2, ensure_ascii=False))
