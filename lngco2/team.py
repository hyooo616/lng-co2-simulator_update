"""
팀 확정값 계산: DWSIM 장비 크기(팀원 A) + 경제성 엑셀 v3(팀원 C)를 앱 화면이 쓰는 모양으로 바꿔 준다.

계산 본체는 econ_model.py(팀원 C가 엑셀을 옮긴 파일)이고, 이 파일은 값을 새로 계산하지 않는다.
  - evaluate_team() 결과는 키트 엔진(calc.py·econ.py)의 evaluate() 결과와 같은 모양이라 app.py의 탭을 그대로 쓴다.
  - 설계 규모는 숫자표 확정값에 고정이다: 7 barg, LNG 연 100만 t, 연 8,000 h, 기존 방식 냉동 2단.
    그래서 LNG 사용량·액화 압력·설계 기준·냉동기 성능·루프 손실은 이 계산에서 바꿀 수 없다.
"""
from __future__ import annotations

from . import econ_model as m

YEAR_CURVES = m.YEAR_CURVES
HOURS = m.BASE["hours"]                 # 8,000 h
LNG_TPY = m.BASE["lng_tpy"]             # 100만 t/년

# 공정 상세 탭에 보여 줄 확정 운전 조건. 근거: 숫자표(10/26)
PROCESS = {
    "p_bara": 8.013,                    # 7 barg + 1.013
    "Tsat_C": -45.96,                   # 숫자표 Step 2의 1번(CoolProp)
    "T_prod_C": -47.96,                 # 숫자표 Step 3 '액화 CO₂ 제품 온도(S08)'
    "T_loop_C": -52.56,                 # CO₂ 삼중점 -56.56 + 동결 여유 4 K
    "p_loop_bar": 5.02,                 # 숫자표 Step 2의 6번
    "freeze_margin_K": 4.0,             # 숫자표 '최소 동결 여유'
    "approach_E201_K": 4.6,             # 숫자표 '기준 DWSIM 파일' (E-201 최소 온도차)
    "T_lng_pump_out_C": -158.17,        # 숫자표 Step 3 'LNG 펌프 출구 온도(L02)'
    "T_lng_out_C": -62.6,               # 숫자표 Step 2의 5b (E-202 출구)
}

NAMES = {
    "C101": "CO₂ 압축기 1단", "C101-M": "압축기 1단 구동기", "E101": "단간 냉각기 1",
    "C102": "CO₂ 압축기 2단", "C102-M": "압축기 2단 구동기", "E102": "단간 냉각기 2",
    "C103": "CO₂ 압축기 3단", "C103-M": "압축기 3단 구동기", "E103": "후단 냉각기 3",
    "R-C": "냉동 압축기", "R-M": "냉동 압축기 구동기", "R-E1": "냉매 응축기",
    "R-E2": "예냉 증발기", "R-E3": "CO₂ 응축 증발기",
    "E201": "E-201 CO₂ 응축기(에탄 증발)", "E202": "E-202 냉열 회수기", "P-LOOP": "에탄 순환 펌프",
    "A-C": "보조 냉동 압축기(여름)", "A-M": "보조 냉동 구동기", "A-E1": "보조 냉매 응축기", "A-E2": "보조 증발기",
    "P201": "LNG 펌프 P201",
}
TYPE = {"comp": "compressor", "drive": "compressor", "hx": "hx", "pump": "pump"}   # 크기 단위: kW 또는 m²
GROUP = {"공통": "common", "기존": "baseline", "냉열": "lng", "보조": "lng", "기지": "lng"}


def evaluate_team(monthly, power, cold, disc, life, err, om, kau, inc_p201=False):
    """화면 입력 → 키트 evaluate()와 같은 모양의 결과. 단위는 키트와 같다(원, t, kWh/t)."""
    r = m.evaluate(monthly=tuple(monthly), p_elec=power, cold_price=cold, disc=disc, life=life,
                   capex_err=err, om=om, kau=kau, inc_p201=int(bool(inc_p201)))
    co2_tpy, lng_tpy = r["co2_tpy"], m.BASE["lng_tpy"]
    ref = m.REF_KWH
    pumps = m.PUMP_KWH + int(bool(inc_p201)) * r["p201_kwh"]
    saving_kwh = r["base_kwh"] - r["lng_kwh"]
    yearly_saving = r["saving"] * 1e8
    d_capex = (r["capex_lng"] - r["capex_base"]) * 1e8
    f = r["f"]

    rows = []
    for i, fm in enumerate(f, start=1):
        rows.append({"month": i, "factor": fm, "lng_t": lng_tpy / 12.0 * fm,
                     "capacity_co2_t": r["cap"][i - 1], "load_co2_t": r["need"],
                     "aux_co2_t": r["deficit"][i - 1], "surplus_co2_t": max(0.0, r["cap"][i - 1] - r["need"])})

    eq = {"common": [], "baseline": [], "lng": []}
    for d in r["detail"]:
        if d["inc"] == 0:                                   # 제외된 설비(P201 제외, 보조 냉동기 불필요)
            continue
        eq[GROUP[d["grp"]]].append({"name": NAMES[tag] if (tag := d["tag"]) in NAMES else tag,
                                    "type": TYPE[d["kind"]], "size": d["size"], "units": d["n"],
                                    "C_TM_krw": d["cost"] * 1e8})
    s = lambda rows_: sum(x["C_TM_krw"] for x in rows_)
    equipment = {**eq, "capex_common": s(eq["common"]),
                 "capex_baseline": r["capex_base"] * 1e8, "capex_lng": r["capex_lng"] * 1e8}

    summary = {
        "co2_tpy": co2_tpy, "co2_tph": co2_tpy / HOURS, "lng_tpy": lng_tpy, "co2_per_lng": r["co2_per_lng"],
        "compression_kWh_t": r["comp_kwh"], "baseline_cooling_kWh_t": ref, "baseline_total_kWh_t": r["base_kwh"],
        "lng_aux_chiller_kWh_t": r["aux_share"] * ref, "lng_pumps_kWh_t": pumps, "lng_other_kWh_t": m.OTHER_KWH,
        "lng_total_kWh_t": r["lng_kwh"], "saving_kWh_t": saving_kwh, "saving_pct": saving_kwh / r["base_kwh"] * 100.0,
        "freeze_margin_K": PROCESS["freeze_margin_K"],
    }
    indicators = {
        "lcol_baseline_krw_t": r["lcol_base"], "lcol_lng_krw_t": r["lcol_lng"],
        "lcol_cut_pct": (1 - r["lcol_lng"] / r["lcol_base"]) * 100,
        "yearly_saving_krw": yearly_saving, "d_capex_krw": d_capex,
        "payback_y": (d_capex / yearly_saving) if (d_capex > 0 and yearly_saving > 0) else 0.0,
        "max_extra_invest_krw": r["limit"] * 1e8, "cold_price_max_krw_tLNG": r["pmax"],
        "cold_value_power_only_krw_tLNG": saving_kwh * r["co2_per_lng"] * power,
    }

    strategies = [
        {"안": "안 1", "내용": "여름 최저 기준 설계, 보조 냉동기 없음", "처리량_t": r["tpy1"], "설비비_억": r["capex1"],
         "연간비용_억": r["tot1"], "톤당비용": r["lcol_1"], "실효비용": r["eff_1"]},
        {"안": "안 2", "내용": "연평균 설계 + 모자란 달은 보조 냉동기", "처리량_t": co2_tpy, "설비비_억": r["capex_lng"],
         "연간비용_억": r["tot_lng"], "톤당비용": r["lcol_lng"], "실효비용": r["eff_2"]},
        {"안": "안 3", "내용": "연평균 설계 + 모자란 달은 처리량 감축", "처리량_t": r["tpy3"], "설비비_억": r["capex3"],
         "연간비용_억": r["tot3"], "톤당비용": r["lcol_3"], "실효비용": r["eff_3"]},
    ]
    for x in strategies:
        x["미처리_t"] = co2_tpy - x["처리량_t"]

    calc = {
        "summary": summary,
        "monthly": {"rows": rows, "aux_share": r["aux_share"], "max_aux_share": r["aux_max"], "co2_tpy": co2_tpy},
        "liquefaction": {"p_bara": PROCESS["p_bara"], "Tsat_C": PROCESS["Tsat_C"], "T_prod_C": PROCESS["T_prod_C"]},
        "lng": {"T_loop_C": PROCESS["T_loop_C"], "p_loop_bar": PROCESS["p_loop_bar"],
                "approach_E201_K": PROCESS["approach_E201_K"], "T_lng_pump_out_C": PROCESS["T_lng_pump_out_C"],
                "T_lng_out_C": PROCESS["T_lng_out_C"]},
    }
    return {"calc": calc, "equipment": equipment, "indicators": indicators, "strategies": strategies, "raw": r}
