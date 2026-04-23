#!/usr/bin/env python3
"""
Dynama P19-P21 decision optimizer for Team Primus.

Goal: maximize expected final equity via joint optimization of:
- pricing
- marketing budget split
- production mix
- expansion decision
- M4 launch decision

Model design intentionally transparent (scenario-based + economics simulation)
so team can adjust assumptions quickly before submitting decisions.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, asdict
from typing import Dict, List


@dataclass
class ModelSpec:
    name: str
    base_price: float
    base_demand_p18: float
    unit_cost: float
    elasticity: float
    marketing_sensitivity: float


@dataclass
class DecisionPeriod:
    period: int
    price_p2: int
    price_p3: int
    mkt_p2: int  # euros
    mkt_p3: int  # euros
    p2_share: float
    launch_m4: bool
    price_m4: int
    mkt_m4: int  # euros
    m4_share: float


@dataclass
class Strategy:
    expand_p19: bool
    periods: List[DecisionPeriod]


@dataclass
class Scenario:
    name: str
    demand_mult: float
    weight: float


# Anchors from uploaded reports (P18 + trend from prior periods)
MODEL_P2 = ModelSpec(
    name="Primus2",
    base_price=2799,
    base_demand_p18=5954,
    unit_cost=1850,
    elasticity=-1.05,
    marketing_sensitivity=0.08,
)
MODEL_P3 = ModelSpec(
    name="Primus3",
    base_price=2299,
    base_demand_p18=12189,
    unit_cost=1450,
    elasticity=-0.95,
    marketing_sensitivity=0.10,
)
MODEL_M4 = ModelSpec(
    name="Primus4",
    base_price=3199,
    base_demand_p18=0,  # no history, inferred through multiplier
    unit_cost=1950,
    elasticity=-1.15,
    marketing_sensitivity=0.12,
)

SCENARIOS = [
    Scenario("LOW", demand_mult=0.90, weight=0.25),
    Scenario("MID", demand_mult=1.00, weight=0.50),
    Scenario("HIGH", demand_mult=1.12, weight=0.25),
]


def period_season_mult(period: int) -> float:
    # P19, P20, P21 season uplift assumptions
    return {19: 1.00, 20: 1.08, 21: 1.12}[period]


def demand(model: ModelSpec, period: int, scenario_mult: float, price: float, marketing_eur: int) -> float:
    base = model.base_demand_p18 * period_season_mult(period) * scenario_mult
    price_factor = (price / model.base_price) ** model.elasticity
    # diminishing returns marketing function (calibrated to game scale)
    mkt_factor = 1 + model.marketing_sensitivity * math.log1p(marketing_eur / 1_000_000)
    return max(0.0, base * price_factor * mkt_factor)


def simulate_strategy(strategy: Strategy, scenario: Scenario) -> Dict:
    # P18 closing state from uploaded reports
    equity = 28_592_440.0
    cash = 2_000_000.0
    securities = 9_953_440.0
    debt_lt = 11_761_000.0

    # inventory from P18 detailed sales report
    inv_p2 = 0.0
    inv_p3 = 0.0
    inv_m4 = 0.0

    expansion_active = False
    expansion_cost = 25_000_000.0
    expansion_depr_add = 1_250_000.0

    period_results = []

    for d in strategy.periods:
        if d.period == 19 and strategy.expand_p19:
            # finance expansion using liquidity first, then debt
            liquid = cash + securities
            use_liquid = min(liquid, 22_000_000.0)
            remaining = expansion_cost - use_liquid
            if use_liquid <= cash:
                cash -= use_liquid
            else:
                rem = use_liquid - cash
                cash = 0.0
                securities = max(0.0, securities - rem)
            debt_lt += max(0.0, remaining)
            expansion_active = True

        # capacity (P20 onwards after P19 expansion order)
        if expansion_active and d.period >= 20:
            normal_cap = 15_000.0
            overtime_cap = 4_500.0
        else:
            normal_cap = 10_000.0
            overtime_cap = 3_000.0

        total_cap = normal_cap + overtime_cap

        # M4 availability from P20 if launched at/after P20
        m4_available = d.launch_m4 and d.period >= 20

        # production allocation
        if m4_available:
            m4_prod = total_cap * d.m4_share
        else:
            m4_prod = 0.0
        rem_cap = total_cap - m4_prod
        p2_prod = rem_cap * d.p2_share
        p3_prod = rem_cap - p2_prod

        # demand & sales
        qd_p2 = demand(MODEL_P2, d.period, scenario.demand_mult, d.price_p2, d.mkt_p2)
        qd_p3 = demand(MODEL_P3, d.period, scenario.demand_mult, d.price_p3, d.mkt_p3)
        if m4_available:
            inferred_base_m4 = 4500 * period_season_mult(d.period) * scenario.demand_mult
            qd_m4 = inferred_base_m4 * (d.price_m4 / MODEL_M4.base_price) ** MODEL_M4.elasticity
            qd_m4 *= 1 + MODEL_M4.marketing_sensitivity * math.log1p(d.mkt_m4 / 1_000_000)
        else:
            qd_m4 = 0.0

        avail_p2 = inv_p2 + p2_prod
        avail_p3 = inv_p3 + p3_prod
        avail_m4 = inv_m4 + m4_prod

        sales_p2 = min(avail_p2, qd_p2)
        sales_p3 = min(avail_p3, qd_p3)
        sales_m4 = min(avail_m4, qd_m4)

        inv_p2 = max(0.0, avail_p2 - sales_p2)
        inv_p3 = max(0.0, avail_p3 - sales_p3)
        inv_m4 = max(0.0, avail_m4 - sales_m4)

        # economics
        revenue = sales_p2 * d.price_p2 + sales_p3 * d.price_p3 + sales_m4 * d.price_m4
        cogs = p2_prod * MODEL_P2.unit_cost + p3_prod * MODEL_P3.unit_cost + m4_prod * MODEL_M4.unit_cost

        marketing = d.mkt_p2 + d.mkt_p3 + (d.mkt_m4 if m4_available else 0)
        admin = 1_000_000.0
        depreciation = 1_200_000.0 + (expansion_depr_add if (expansion_active and d.period >= 20) else 0.0)
        rnd = 0.0
        if d.period == 20 and m4_available:
            rnd = 2_000_000.0

        financial_exp = 0.022 * debt_lt
        operational_profit = revenue - cogs - marketing - admin - depreciation - rnd
        pre_tax = operational_profit - financial_exp
        tax = max(0.0, pre_tax * 0.25)
        net_profit = pre_tax - tax

        equity += net_profit
        cash += net_profit

        period_results.append(
            {
                "period": d.period,
                "revenue": round(revenue),
                "net_profit": round(net_profit),
                "equity_end": round(equity),
                "sales": {
                    "p2": round(sales_p2),
                    "p3": round(sales_p3),
                    "m4": round(sales_m4),
                },
                "lost_sales": {
                    "p2": round(max(0.0, qd_p2 - sales_p2)),
                    "p3": round(max(0.0, qd_p3 - sales_p3)),
                    "m4": round(max(0.0, qd_m4 - sales_m4)),
                },
                "inventory_end": {
                    "p2": round(inv_p2),
                    "p3": round(inv_p3),
                    "m4": round(inv_m4),
                },
                "production": {
                    "p2": round(p2_prod),
                    "p3": round(p3_prod),
                    "m4": round(m4_prod),
                },
            }
        )

    return {
        "scenario": scenario.name,
        "final_equity": equity,
        "equity_gain": equity - 28_592_440.0,
        "period_results": period_results,
    }


def random_strategy(rng: random.Random) -> Strategy:
    expand = rng.choice([False, True])

    periods = []
    for period in [19, 20, 21]:
        launch_m4 = period >= 20 and rng.random() < 0.85

        periods.append(
            DecisionPeriod(
                period=period,
                price_p2=rng.choice([2799, 2899, 2999, 3099, 3199]),
                price_p3=rng.choice([2299, 2399, 2499, 2599, 2699]),
                mkt_p2=rng.choice([600_000, 800_000, 1_000_000, 1_200_000]),
                mkt_p3=rng.choice([600_000, 800_000, 1_000_000, 1_200_000]),
                p2_share=rng.choice([0.35, 0.45, 0.55, 0.65]),
                launch_m4=launch_m4,
                price_m4=rng.choice([2999, 3199, 3399]),
                mkt_m4=rng.choice([400_000, 700_000, 1_000_000]),
                m4_share=rng.choice([0.15, 0.25, 0.35]),
            )
        )

    return Strategy(expand_p19=expand, periods=periods)


def evaluate(strategy: Strategy) -> Dict:
    by_scenario = [simulate_strategy(strategy, s) for s in SCENARIOS]
    expected_final_equity = sum(r["final_equity"] * s.weight for r, s in zip(by_scenario, SCENARIOS))
    expected_gain = expected_final_equity - 28_592_440.0

    risk_penalty = min(r["equity_gain"] for r in by_scenario) * 0.15
    score = expected_gain + risk_penalty

    return {
        "strategy": strategy,
        "score": score,
        "expected_final_equity": expected_final_equity,
        "expected_gain": expected_gain,
        "scenario_results": by_scenario,
    }


def strategy_to_dict(strategy: Strategy) -> Dict:
    return {
        "expand_p19": strategy.expand_p19,
        "periods": [asdict(p) for p in strategy.periods],
    }


def optimize(iterations: int = 50_000, seed: int = 42) -> Dict:
    rng = random.Random(seed)
    best = None

    for _ in range(iterations):
        strat = random_strategy(rng)
        res = evaluate(strat)
        if best is None or res["score"] > best["score"]:
            best = res

    return best


def build_output(best: Dict) -> Dict:
    return {
        "model": "Dynama Primus P19-P21 stochastic optimizer",
        "starting_equity": 28_592_440,
        "best_score": round(best["score"], 2),
        "expected_final_equity": round(best["expected_final_equity"], 2),
        "expected_gain": round(best["expected_gain"], 2),
        "recommended_strategy": strategy_to_dict(best["strategy"]),
        "scenario_results": [
            {
                "scenario": r["scenario"],
                "final_equity": round(r["final_equity"], 2),
                "equity_gain": round(r["equity_gain"], 2),
                "period_results": r["period_results"],
            }
            for r in best["scenario_results"]
        ],
    }


def run_optimizer(iterations: int = 60_000, seed: int = 20260423) -> Dict:
    best = optimize(iterations=iterations, seed=seed)
    return build_output(best)


def main() -> None:
    output = run_optimizer(iterations=60_000, seed=20260423)

    print("=== OPTIMAL STRATEGY (expected value) ===")
    print(json.dumps(output, indent=2, ensure_ascii=False))

    with open("primus_p19_p21_optimal_plan.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
