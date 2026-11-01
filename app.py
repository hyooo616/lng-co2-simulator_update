"""
LNG 냉열 CO2 액화 시뮬레이터 (Streamlit)

실행:  streamlit run app.py
계산은 lngco2/team.py → econ_model.py가 한다(DWSIM 장비 크기 + 경제성 엑셀 v3, 숫자표와 같은 값).
이 파일은 화면만 그린다.
"""
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lngco2 import econ_model, team

DEFAULT_MONTHLY = econ_model.BASE["monthly"]      # 가스공사 2023~2025 평균(숫자표 10/26)

st.set_page_config(page_title="LNG 냉열 CO₂ 액화 시뮬레이터", layout="wide")

GREY, BLUE, LIGHT, RED = "#9aa0a6", "#1a73e8", "#c6dafc", "#d93025"
MONTHS = [f"{m}월" for m in range(1, 13)]


def load_profile(uploaded) -> tuple:
    """월별 송출 비율: 업로드 > data/monthly_profile.csv > 기본값"""
    src = uploaded or (Path(__file__).parent / "data" / "monthly_profile.csv")
    try:
        df = pd.read_csv(src)
        col = "factor" if "factor" in df.columns else df.columns[-1]
        vals = [float(x) for x in df[col].tolist()][:12]
        if len(vals) == 12:
            return tuple(vals), "CSV"
    except Exception:
        pass
    return DEFAULT_MONTHLY, "기본 가정"


@st.cache_data(show_spinner=False)
def load_mc(path: str) -> pd.DataFrame:
    """Step 5 몬테카를로 결과(1만 행). 앱에서 다시 돌리지 않고 읽기만 한다."""
    return pd.read_csv(path)


@st.cache_data(show_spinner=False)
def compute(monthly, power, cold, disc, life, err, om, kau, inc_p201):
    return team.evaluate_team(monthly, power, cold, disc, life, err, om, kau, inc_p201)


# ------------------------------------------------------------------ ① 입력 패널
sb = st.sidebar
sb.header("① 조건 바꾸기")
sb.caption("설계 기준(액화 7 barg, LNG 연 100만 t, 기존 방식 냉동 2단)은 숫자표 확정값으로 고정되어 있다.")
power = sb.slider("전기요금 (원/kWh)", 140, 220, 180, step=5,
                  help="산업용(을) 대기업 182.7원(2024.10). 호남 지역요금 인하 시 최대 18원 낮아짐")
cold = sb.slider("냉열 거래가 (원/t LNG)", 0, 30000, 0, step=1000)
disc = sb.slider("할인율 (%)", 4.0, 12.0, 8.0, step=0.5) / 100
life = sb.slider("설비 수명 (년)", 10, 30, 20)
err = sb.slider("설비비 오차 (%)", -30, 30, 0, step=5) / 100
om = sb.slider("유지보수비 (설비비의 %/년)", 1.0, 5.0, 3.0, step=0.5) / 100
with sb.expander("고급 설정"):
    kau = st.number_input("배출권 가격 (원/t, 운전 전략 안 1·3의 미처리 CO₂ 비용)", value=26450, step=1000)
    inc_p201 = st.checkbox("기지 LNG 펌프(P201) 비용·전력 포함", value=False,
                           help="팀 확정: 제외(기지 기존 설비, 10/22). 포함하면 전력과 설비비가 늘어난다.")
    up = st.file_uploader("월별 송출 비율 CSV", type="csv",
                          help="tools/kogas_csv_to_profile.py 로 만든 파일. 12개 값")

monthly, profile_src = load_profile(up)

out = compute(monthly, power, cold, disc, life, err, om, kau, inc_p201)
s, ind = out["calc"]["summary"], out["indicators"]

# ------------------------------------------------------------------ ② 결과 카드
st.title("LNG 냉열로 CO₂ 액화하기: 얼마나 아끼나")
st.caption(f"CO₂ 처리량 {s['co2_tpy']/1e4:,.0f}만 t/년 · LNG 1t당 CO₂ {s['co2_per_lng']:.2f}t · "
           f"월별 송출 비율: {profile_src} · 계산 기준: 팀 확정값(숫자표)")
c1, c2, c3, c4 = st.columns(4)
c1.metric("톤당 액화 전력", f"{s['lng_total_kWh_t']:.0f} kWh/t",
          f"-{s['saving_pct']:.0f}% (기존 {s['baseline_total_kWh_t']:.0f})", delta_color="inverse")
c2.metric("톤당 액화비", f"{ind['lcol_lng_krw_t']/1e4:.2f}만 원/t",
          f"-{ind['lcol_cut_pct']:.0f}% (기존 {ind['lcol_baseline_krw_t']/1e4:.2f}만)",
          delta_color="inverse")
c3.metric("연간 절감액", f"{ind['yearly_saving_krw']/1e8:,.0f}억 원/년")
c4.metric("연계비 한도", f"{ind['max_extra_invest_krw']/1e8:,.0f}억 원", "이하면 손해 아님 (NPV = 0)",
          delta_color="off")
st.caption(f"연계비 한도: 연계 배관·부지·인허가 등 아직 모르는 추가비를 이 금액까지 써도 "
           f"{life}년 동안 손해가 아니다(할인율 {disc*100:.1f}% 기준).")

tab3, tab4, tab5, tab_op, tab_mc, tab6, tab7 = st.tabs(
    ["③ 월별 냉열", "④ 냉열 거래가격", "⑤ 민감도", "운전 전략 비교", "불확실성", "공정 상세", "가정·출처"])

# ------------------------------------------------------------------ ③ 월별
with tab3:
    rows = pd.DataFrame(out["calc"]["monthly"]["rows"])
    fig = go.Figure()
    fig.add_bar(x=MONTHS, y=rows["capacity_co2_t"] / 1e4, name="그 달 냉열로 액화 가능한 CO₂",
                marker_color=LIGHT)
    fig.add_bar(x=MONTHS, y=rows["aux_co2_t"] / 1e4, name="모자라서 보조 냉동기가 맡는 몫",
                marker_color=GREY, base=rows["capacity_co2_t"] / 1e4)
    fig.add_scatter(x=MONTHS, y=rows["load_co2_t"] / 1e4, name="액화해야 할 CO₂",
                    mode="lines+markers", line=dict(color=BLUE, width=3))
    fig.update_layout(barmode="overlay", yaxis_title="만 t/월", height=420,
                      legend=dict(orientation="h", y=-0.15), margin=dict(t=30))
    st.plotly_chart(fig, use_container_width=True)
    st.write(f"보조 냉동기가 맡는 몫은 연간 {out['calc']['monthly']['aux_share']*100:.1f}%, "
             f"가장 모자란 달은 {out['calc']['monthly']['max_aux_share']*100:.0f}%다.")

# ------------------------------------------------------------------ ④ 거래가격
with tab4:
    pmax = ind["cold_price_max_krw_tLNG"]
    xs = [x * pmax * 1.3 / 40 for x in range(41)]
    gain0 = pmax * s["lng_tpy"]
    lng_rev = [x * s["lng_tpy"] / 1e8 for x in xs]
    hub = [(gain0 - x * s["lng_tpy"]) / 1e8 for x in xs]
    fig = go.Figure()
    fig.add_vrect(x0=0, x1=pmax, fillcolor=BLUE, opacity=0.08, line_width=0,
                  annotation_text="둘 다 이득인 구간", annotation_position="top left")
    fig.add_scatter(x=xs, y=lng_rev, name="LNG 기지 수입", line=dict(color=GREY, width=3))
    fig.add_scatter(x=xs, y=hub, name="CO₂ 허브의 이득(냉열값 낸 뒤)", line=dict(color=BLUE, width=3))
    fig.add_hline(y=0, line_color="#5f6368")
    fig.update_layout(xaxis_title="냉열 거래가 (원/t LNG)", yaxis_title="억 원/년", height=420,
                      legend=dict(orientation="h", y=-0.2), margin=dict(t=30))
    st.plotly_chart(fig, use_container_width=True)
    st.write(f"냉열 값은 0원에서 **{pmax:,.0f}원/t LNG** 사이에서 정해진다. "
             f"전기값만 따지면 {ind['cold_value_power_only_krw_tLNG']:,.0f}원, "
             f"냉동기를 덜 사는 설비비 이득까지 더하면 상한이 {pmax:,.0f}원이다.")

# ------------------------------------------------------------------ ⑤ 민감도
with tab5:
    base_gain = ind["lcol_baseline_krw_t"] - ind["lcol_lng_krw_t"]
    cases = [                       # 숫자표 '몬테카를로 입력 범위'(10/26 확정)와 같은 범위
        ("전기요금 160 ↔ 200원", dict(power=160), dict(power=200)),
        ("할인율 5 ↔ 10%", dict(disc=0.05), dict(disc=0.10)),
        ("설비 수명 15 ↔ 25년", dict(life=15), dict(life=25)),
        ("유지보수비 2 ↔ 4%", dict(om=0.02), dict(om=0.04)),
        ("설비비 -30 ↔ +30%", dict(err=-0.3), dict(err=0.3)),
        ("냉열 거래가 0 ↔ 1.84만 원", dict(cold=0), dict(cold=18400)),
    ]
    args = dict(monthly=monthly, power=power, cold=cold, disc=disc, life=life, err=err, om=om, kau=kau,
                inc_p201=inc_p201)
    bars = []
    for label, lo, hi in cases:
        vals = []
        for over in (lo, hi):
            o = compute(**{**args, **over})["indicators"]
            vals.append(o["lcol_baseline_krw_t"] - o["lcol_lng_krw_t"])
        bars.append((label, min(vals), max(vals)))
    bars.sort(key=lambda x: x[2] - x[1])
    fig = go.Figure()
    fig.add_bar(y=[b[0] for b in bars], x=[b[2] - b[1] for b in bars], base=[b[1] for b in bars],
                orientation="h", marker_color=BLUE, name="범위")
    fig.add_vline(x=base_gain, line_color="#5f6368", line_dash="dash")
    fig.update_layout(xaxis_title="톤당 액화비 절감액 (원/t CO₂)", height=420, showlegend=False,
                      margin=dict(t=30))
    st.plotly_chart(fig, use_container_width=True)
    st.write(f"점선은 현재 조건의 절감액 {base_gain:,.0f}원/t. 막대가 길수록 결론을 크게 흔드는 변수다.")

# ------------------------------------------------------------------ 운전 전략 비교
with tab_op:
    strat = out["strategies"]
    NAME = {"안 1": "안 1 · 여름 최저 설계", "안 2": "안 2 · 보조 냉동기 병행", "안 3": "안 3 · 처리량 감축"}
    st.write("냉열이 모자란 달(주로 여름)에 어떻게 운전할지 세 가지를 비교한다. "
             "표의 비용은 모두 현재 왼쪽 입력(전기요금, 할인율, 수명, 설비비 오차, 배출권 가격 등)으로 계산한다.")
    tbl = pd.DataFrame([{
        "안": NAME[x["안"]], "운전 방식": x["내용"],
        "연간 처리량(만 t)": round(x["처리량_t"] / 1e4, 1),
        "처리 못 하는 CO₂(만 t)": round(x["미처리_t"] / 1e4, 1),
        "설비비(억 원)": round(x["설비비_억"]),
        "연간 비용(억 원/년)": round(x["연간비용_억"], 1),
        "톤당 비용(원/t)": round(x["톤당비용"]),
        "실효 톤당 비용(원/t)": round(x["실효비용"]),
    } for x in strat])
    st.dataframe(tbl, use_container_width=True, hide_index=True)
    best = min(strat, key=lambda x: x["실효비용"])
    st.write(f"전기요금 {power}원/kWh, 배출권 {kau:,.0f}원/t 조건에서는 **{NAME[best['안']]}**의 실효 톤당 비용이 "
             f"가장 낮다({best['실효비용']:,.0f}원/t).")
    st.caption(f"실효 톤당 비용 = (연간 비용 + 처리 못 한 CO₂ × 배출권 가격) ÷ 목표 처리량 {s['co2_tpy']/1e4:,.1f}만 t. "
               "안 1·3은 처리 못 한 CO₂를 배출권 가격으로 환산해 더해야 안 2와 공정하게 비교된다.")
    mrows = pd.DataFrame(out["calc"]["monthly"]["rows"])
    cap, need = mrows["capacity_co2_t"], mrows["load_co2_t"]
    fig = go.Figure()
    fig.add_bar(x=MONTHS, y=cap / 1e4, name="그 달 냉열로 처리 가능한 CO₂", marker_color=LIGHT)
    fig.add_scatter(x=MONTHS, y=[strat[0]["처리량_t"] / 12 / 1e4] * 12, name=f"{NAME['안 1']} 처리량",
                    mode="lines+markers", line=dict(color=GREY, width=3))
    fig.add_scatter(x=MONTHS, y=need / 1e4, name=f"{NAME['안 2']} 처리량(전량)", mode="lines+markers",
                    line=dict(color=BLUE, width=3))
    fig.add_scatter(x=MONTHS, y=[min(c, n) / 1e4 for c, n in zip(cap, need)], name=f"{NAME['안 3']} 처리량",
                    mode="lines+markers", line=dict(color=RED, width=3, dash="dash"))
    fig.update_layout(yaxis_title="만 t/월", height=420, legend=dict(orientation="h", y=-0.2),
                      margin=dict(t=30))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("계절 단위 저장으로 부족분을 메우는 안은 몇 달 치 CO₂나 냉열을 저장해야 해서 제외했다.")

# ------------------------------------------------------------------ 불확실성
with tab_mc:
    mc_path = Path(__file__).parent / "data" / "mc_results.csv"
    if not mc_path.exists():
        st.info("data/mc_results.csv가 없다. Step 5 몬테카를로 노트북이 만든 파일을 data 폴더에 올려 주세요.")
    else:
        mc = load_mc(str(mc_path))
        n_mc, p_cheaper = len(mc), mc["cheaper"].mean()
        st.subheader(f"기존 방식보다 쌀 확률 {p_cheaper:.1%}")
        st.write(f"확실하지 않은 입력 7개를 숫자표의 확정 범위 안에서 균등분포로 {n_mc:,}번 뽑아 계산했다(난수 시드 42). "
                 f"냉열 방식 톤당 액화비는 중간값 {mc['lcol_lng'].median():,.0f}원/t, "
                 f"90% 구간 {mc['lcol_lng'].quantile(.05):,.0f}~{mc['lcol_lng'].quantile(.95):,.0f}원/t다. "
                 "이 그림은 앱에서 다시 계산하지 않고 미리 계산한 결과 파일을 읽어서 보여 준다.")
        fig = go.Figure()
        fig.add_histogram(x=mc["lcol_base"] / 1e4, nbinsx=60, name="기존 방식", marker_color=GREY, opacity=0.6)
        fig.add_histogram(x=mc["lcol_lng"] / 1e4, nbinsx=60, name="냉열 방식", marker_color=BLUE, opacity=0.8)
        fig.update_layout(barmode="overlay", xaxis_title="톤당 액화비 (만 원/t CO₂)", yaxis_title="빈도",
                          height=420, legend=dict(orientation="h", y=-0.2), margin=dict(t=30))
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("**결과에 영향이 큰 입력 순위** (순위상관계수 ρ: +면 그 입력이 클수록 냉열 방식 액화비가 커진다)")
        names = {"capex_err": "설비비 오차", "p_elec": "전기요금", "cold_price": "냉열 거래가", "disc": "할인율",
                 "life": "설비 수명", "om": "유지보수비율", "summer_min": "여름 최저 월 비율(연도별 곡선)"}
        rho = mc[list(names)].rank().corrwith(mc["lcol_lng"].rank())
        rho = rho.reindex(rho.abs().sort_values().index)
        fig = go.Figure(go.Bar(x=rho.values, y=[names[k] for k in rho.index], orientation="h",
                               marker_color=[BLUE if v >= 0 else GREY for v in rho.values],
                               text=[f"{v:+.2f}" for v in rho.values], textposition="outside"))
        fig.update_layout(xaxis_title="순위상관계수 ρ", height=380, margin=dict(t=30),
                          xaxis=dict(range=[-1, 1.15]))
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("**냉열 거래가에 따른 확률** (거래가는 협상으로 정하는 값이라 범위를 넓게 잡을수록 순위가 높게 나온다)")
        grp = pd.cut(mc["cold_price"], bins=[0, 6000, 12000, 16000, 18400], include_lowest=True,
                     labels=["0~6,000", "6,000~12,000", "12,000~16,000", "16,000~18,400"])
        byp = mc.groupby(grp, observed=True)["cheaper"].agg(["mean", "count"])
        byp = pd.DataFrame({"냉열 거래가 구간(원/t LNG)": byp.index.astype(str),
                            "기존 방식보다 쌀 확률": [f"{v:.1%}" for v in byp["mean"]],
                            "계산 횟수": byp["count"].values})
        st.dataframe(byp, use_container_width=True, hide_index=True)
        st.caption("입력 범위(숫자표 10/26 확정, 모두 균등분포): 설비비 오차 ±30%, 전기요금 160~200원/kWh, "
                   "냉열 거래가 0~18,400원/t LNG, 할인율 5~10%, 설비 수명 15~25년, 유지보수비 2~4%, "
                   "월별 비율은 2016~2025 연도별 곡선 10개 중 1개. 숫자는 모두 팀 검증 전 [가정]이다.")

# ------------------------------------------------------------------ 공정 상세
with tab6:
    calc = out["calc"]
    st.caption("값 출처: 숫자표(10/26) — DWSIM full_process.dwxmz(Peng-Robinson)와 경제성 엑셀 v3. "
               "E-201 U=600, E-202 U=500 W/m²K는 상세 설계 검증 전 예비값이고, P201(LNG 펌프)은 기지 기존 설비라 제외했다.")
    st.subheader("전력 내역 (kWh/t CO₂)")
    st.table(pd.DataFrame({
        "항목": ["CO₂ 압축", "냉각·액화(냉동기)", "여름 보조 냉동기", "열매체·LNG 펌프", "기타 보조", "합계"],
        "기존 방식": [s["compression_kWh_t"], s["baseline_cooling_kWh_t"], 0, 0, 0,
                   s["baseline_total_kWh_t"]],
        "LNG 냉열": [s["compression_kWh_t"], 0, s["lng_aux_chiller_kWh_t"], s["lng_pumps_kWh_t"],
                   s["lng_other_kWh_t"], s["lng_total_kWh_t"]],
    }).set_index("항목").map(lambda v: f"{v:,.1f}"))
    lq, ln = calc["liquefaction"], calc["lng"]
    st.subheader("핵심 운전 조건")
    st.table(pd.DataFrame({
        "항목": ["CO₂ 액화 압력", "CO₂ 포화온도", "제품 온도", "에탄 루프 온도", "에탄 루프 압력",
               "동결 여유(삼중점 대비)", "E-201 최소 온도차", "LNG 펌프 출구", "LNG 출구(E-202)"],
        "값": [f"{lq['p_bara']:.2f} bara", f"{lq['Tsat_C']:.1f} ℃", f"{lq['T_prod_C']:.1f} ℃",
              f"{ln['T_loop_C']:.1f} ℃", f"{ln['p_loop_bar']:.2f} bar", f"{s['freeze_margin_K']:.1f} K",
              f"{ln['approach_E201_K']:.1f} K", f"{ln['T_lng_pump_out_C']:.1f} ℃",
              f"{ln['T_lng_out_C']:.1f} ℃"],
    }))
    st.subheader("장비 목록과 설비비 (총모듈비, 억 원)")
    eq = out["equipment"]
    tbl = []
    for grp, name in (("common", "공통"), ("baseline", "기존 방식"), ("lng", "LNG 냉열")):
        for r in eq[grp]:
            unit = "kW" if r["type"] in ("compressor", "pump") else "m²"
            tbl.append({"구분": name, "장비": r["name"], "크기": f"{r['size']:,.0f} {unit}",
                        "대수": r["units"], "설비비(억)": round(r["C_TM_krw"] / 1e8, 1)})
    st.dataframe(pd.DataFrame(tbl), use_container_width=True, hide_index=True)
    st.write(f"설비비 합계: 기존 {eq['capex_baseline']/1e8:,.0f}억 원, "
             f"LNG 냉열 {eq['capex_lng']/1e8:,.0f}억 원 (개념설계 추정, ±30%)")

# ------------------------------------------------------------------ 가정·출처
with tab7:
    st.markdown(r"""
- 계산 기준(팀 확정값): DWSIM full_process.dwxmz(Peng-Robinson) 장비 크기 + 경제성 엑셀 v3. 숫자표 10/26과 같은 값이다. E-201 U=600, E-202 U=500 W/m²K는 상세 설계 검증 전 예비값, P201(LNG 펌프)은 기지 기존 설비라 제외
- 물성(기준값 계산): CoolProp(CO₂ Span-Wagner, 메탄 Setzmann-Wagner, 에탄 Buecker-Wagner 기준식)
- 설비비: Turton, *Analysis, Synthesis and Design of Chemical Processes* 부록 A 상관식 (CEPCI 397 → 800 환산). 계수는 키트 값이고 교재 원문 대조는 하지 않았다(10/22 팀 결정)
- CEPCI: 2023 연평균 797.9 (Chemical Engineering, 2024.3.25). 2025는 2024 대비 +1.6%
- 환율: 1,345.75원/달러 (2026.10.2) → 1,350원 사용
- 전기요금: 산업용(을) 대기업 182.7원/kWh (2024.10.24 인상 후, S&P Global 2024.10.23)
- 배출권: KAU25 경매 26,450원/t (2026.6.10, 아시아경제)
- CO₂ 품질: Northern Lights 사양서 2024 (수분 30ppm 이하)
- 월별 송출: 한국가스공사 용도별 월 공급량(도시가스+발전) 2023~2025 연도별 비율의 평균. 광양 월별 송출량은 공개되지 않아 전국 비율을 대리 지표로 쓴다. 2025년 2월÷8월 = 1.84배로 공시값과 같다
- 열전달계수 U: 고압 기체 150\~500, 유기물 응축 300\~1,200 W/m²K 범위 안에서 가정
- 문헌 비교: 압력별 경향은 Deng 외(2019, Int. J. Refrig. 103:301-315), Roussanaly 외(2021, Energies 14(18) 5635)와 비교한다. 문헌 액화비 절대값(13\~21달러/t)은 원문 확인 전이라 쓰지 않는다 [확인 필요]
- 한계: 실험 검증 없음, 포집 공정과 불순물 제거 설비는 범위 밖, 계절 단위 저장안 제외, 광양 배출원 감소 가능성(전기로 전환)
""")
    st.info(f"배출권 가격 {kau:,.0f}원/t와 액화비를 바로 비교하면 안 된다. 액화는 포집·수송·저장으로 이어지는 "
            f"CCS 비용의 한 단계다. 참고로 지금 조건에서 액화 단계 비용은 기존 방식 "
            f"{ind['lcol_baseline_krw_t']:,.0f}원/t, LNG 냉열 방식 {ind['lcol_lng_krw_t']:,.0f}원/t이다.")
