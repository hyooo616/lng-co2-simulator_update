"""
팀 확정값(숫자표 10/26)이 앱 계산에 그대로 나오는지 확인하는 테스트.  실행: python -m pytest -q
이 테스트는 CoolProp 없이도 돌아간다(team.py는 econ_model.py만 쓴다).
숫자표 값을 바꾸기로 팀이 합의하면 아래 기준값도 같이 고친다.
"""
import math
from pathlib import Path

import pandas as pd

from lngco2 import econ_model, team

ROOT = Path(__file__).resolve().parents[1]
MONTHLY = (1.552, 1.354, 1.154, 0.862, 0.793, 0.743, 0.810, 0.832, 0.720, 0.772, 1.022, 1.385)


def base(**kw):
    a = dict(monthly=MONTHLY, power=180, cold=0, disc=0.08, life=20, err=0.0, om=0.03, kau=26450, inc_p201=False)
    a.update(kw)
    return team.evaluate_team(**a)


def test_card_numbers_match_number_table():
    o = base()
    s, i, eq = o["calc"]["summary"], o["indicators"], o["equipment"]
    assert round(s["baseline_total_kWh_t"], 1) == 136.6
    assert round(s["lng_total_kWh_t"], 1) == 57.3
    assert round(s["saving_pct"]) == 58
    assert round(i["lcol_baseline_krw_t"]) == 33076
    assert round(i["lcol_lng_krw_t"]) == 16923
    assert round(eq["capex_baseline"] / 1e8) == 734
    assert round(eq["capex_lng"] / 1e8) == 572
    assert round(i["yearly_saving_krw"] / 1e8) == 168
    assert round(i["cold_price_max_krw_tLNG"]) == 18426
    assert round(i["max_extra_invest_krw"] / 1e8) == 1809


def test_strategy_costs_match_number_table():
    eff = [round(x["실효비용"]) for x in base()["strategies"]]
    assert eff == [17336, 16923, 15589]


def test_monthly_shortfall_matches_number_table():
    m = base()["calc"]["monthly"]
    assert round(m["aux_share"] * 100, 1) == 12.2
    assert round(m["max_aux_share"] * 100, 1) == 28.0


def test_power_breakdown_adds_up():
    s = base()["calc"]["summary"]
    parts = s["compression_kWh_t"] + s["lng_aux_chiller_kWh_t"] + s["lng_pumps_kWh_t"] + s["lng_other_kWh_t"]
    assert math.isclose(parts, s["lng_total_kWh_t"], rel_tol=1e-9)


def test_equipment_table_adds_up():
    o = base()
    eq = o["equipment"]
    assert math.isclose(eq["capex_common"] + sum(x["C_TM_krw"] for x in eq["lng"]), eq["capex_lng"], rel_tol=1e-9)
    assert math.isclose(eq["capex_common"] + sum(x["C_TM_krw"] for x in eq["baseline"]), eq["capex_baseline"], rel_tol=1e-9)


def test_p201_excluded_by_default_and_costs_more_when_included():
    assert base(inc_p201=True)["indicators"]["lcol_lng_krw_t"] > base()["indicators"]["lcol_lng_krw_t"]


def test_higher_power_price_more_saving():
    assert base(power=200)["indicators"]["yearly_saving_krw"] > base(power=160)["indicators"]["yearly_saving_krw"]


def test_monthly_csv_is_the_team_curve():
    df = pd.read_csv(ROOT / "data" / "monthly_profile.csv")
    assert list(df["month"]) == list(range(1, 13))
    assert tuple(df["ratio"]) == econ_model.BASE["monthly"] == MONTHLY


def test_monte_carlo_file():
    mc = pd.read_csv(ROOT / "data" / "mc_results.csv")
    assert len(mc) == 10000
    assert round(mc["cheaper"].mean(), 3) == 0.964
