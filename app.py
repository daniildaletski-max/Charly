import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from dynama_optimizer import run_optimizer

st.set_page_config(page_title="Primus P19-P21 Optimizer", page_icon="📈", layout="wide")

st.title("Primus Decision System — P19-P21")
st.caption("Оптимизация бюджета, маркетинга и управления капиталом для победы в DYNAMA")

with st.sidebar:
    st.header("Параметры расчёта")
    iterations = st.slider("Количество стратегий для перебора", min_value=5_000, max_value=120_000, step=5_000, value=60_000)
    seed = st.number_input("Seed (для воспроизводимости)", min_value=1, max_value=99_999_999, value=2_026_423, step=1)
    run_btn = st.button("Запустить оптимизацию", type="primary", use_container_width=True)

if "result" not in st.session_state:
    default_plan_path = Path("primus_p19_p21_optimal_plan.json")
    if default_plan_path.exists():
        with default_plan_path.open("r", encoding="utf-8") as f:
            st.session_state.result = json.load(f)
    else:
        st.session_state.result = None

if run_btn:
    with st.spinner("Считаю оптимальную стратегию..."):
        st.session_state.result = run_optimizer(iterations=int(iterations), seed=int(seed))

result = st.session_state.result

if result is None:
    st.info("Нажмите **Запустить оптимизацию** в левой панели.")
    st.stop()

col1, col2, col3 = st.columns(3)
col1.metric("Ожидаемая финальная Equity", f"€{result['expected_final_equity']:,.0f}")
col2.metric("Ожидаемый прирост Equity", f"€{result['expected_gain']:,.0f}")
col3.metric("Score модели", f"{result['best_score']:,.0f}")

st.subheader("Рекомендованные решения по периодам")
periods = result["recommended_strategy"]["periods"]
plan_df = pd.DataFrame(periods)
plan_df["total_marketing"] = plan_df["mkt_p2"] + plan_df["mkt_p3"] + plan_df.apply(
    lambda r: r["mkt_m4"] if r["launch_m4"] and r["period"] >= 20 else 0, axis=1
)
plan_df = plan_df[
    [
        "period",
        "price_p2",
        "price_p3",
        "launch_m4",
        "price_m4",
        "mkt_p2",
        "mkt_p3",
        "mkt_m4",
        "total_marketing",
        "p2_share",
        "m4_share",
    ]
]
st.dataframe(plan_df, use_container_width=True)

st.subheader("Таблица для заполнения decision form (готово к отправке)")
submission_df = plan_df[["period", "price_p2", "price_p3", "price_m4", "mkt_p2", "mkt_p3", "mkt_m4"]].copy()
submission_df.columns = ["Period", "Price P2", "Price P3", "Price M4", "Marketing P2", "Marketing P3", "Marketing M4"]
submission_df["Expand in P19"] = "YES" if result["recommended_strategy"]["expand_p19"] else "NO"
submission_df["Launch M4"] = plan_df["launch_m4"].map({True: "YES", False: "NO"})
st.dataframe(submission_df, use_container_width=True)

st.subheader("Ключевые флаги стратегии")
st.write({"expand_p19": result["recommended_strategy"]["expand_p19"]})

st.subheader("Сценарный анализ (LOW / MID / HIGH)")
scenario_rows = []
for s in result["scenario_results"]:
    scenario_rows.append(
        {
            "scenario": s["scenario"],
            "final_equity": s["final_equity"],
            "equity_gain": s["equity_gain"],
        }
    )
scenario_df = pd.DataFrame(scenario_rows)
st.dataframe(scenario_df, use_container_width=True)

for s in result["scenario_results"]:
    with st.expander(f"Детали периода — сценарий {s['scenario']}"):
        details_df = pd.DataFrame(s["period_results"])
        st.dataframe(details_df, use_container_width=True)

st.subheader("Экспорт")
json_blob = json.dumps(result, ensure_ascii=False, indent=2)
file_name = f"primus_p19_p21_plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
st.download_button(
    label="Скачать JSON-план",
    data=json_blob,
    file_name=file_name,
    mime="application/json",
)

st.caption("Система работает на основе исторических данных команды Primus (P7-P18) и сценарного моделирования.")
