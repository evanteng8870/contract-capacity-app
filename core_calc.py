# core_calc.py
# 契約容量試算核心邏輯（不含任何 input()/print()，方便被 Streamlit 呼叫）

from dataclasses import dataclass
from typing import List, Tuple

# 低壓用電基本電費
LV_SUMMER_BASIC_RATE = 236.2      # 低壓 夏月 基本電費單價 (元/kW⋅月)
LV_NON_SUMMER_BASIC_RATE = 173.2  # 低壓 非夏月 基本電費單價 (元/kW⋅月)

# 高壓用電基本電費
HV_SUMMER_BASIC_RATE = 223.6      # 高壓 夏月 基本電費單價 (元/kW⋅月)
HV_NON_SUMMER_BASIC_RATE = 166.9  # 高壓 非夏月 基本電費單價 (元/kW⋅月)


def calc_over_penalty(max_demand_kw: float, contract_kw: float, basic_rate: float) -> float:
    """
    台電超約邏輯：
    - 超過契約容量 0~10%：超約容量 × 2 × 基本電費
    - 超過契約容量超過 10%：前 10% × 2 倍、其餘超過部分 × 3 倍
    """
    C = contract_kw
    D = max_demand_kw
    BR = basic_rate

    if D <= C:
        return 0.0

    threshold_10 = C * 1.10

    if D <= threshold_10:
        over_2 = D - C
        over_3 = 0.0
    else:
        over_2 = C * 0.10
        over_3 = D - threshold_10

    penalty = over_2 * BR * 2 + over_3 * BR * 3
    return penalty


def is_summer_month(month: int) -> bool:
    """
    夏月：6~9 月
    """
    return 6 <= month <= 9


def get_basic_rate_for_month(month: int, supply_type: str) -> float:
    """
    依月份與供電別，回傳對應的基本電費單價
    supply_type: "HV" 高壓用電, "LV" 低壓用電
    """
    summer = is_summer_month(month)

    if supply_type == "HV":
        return HV_SUMMER_BASIC_RATE if summer else HV_NON_SUMMER_BASIC_RATE
    elif supply_type == "LV":
        return LV_SUMMER_BASIC_RATE if summer else LV_NON_SUMMER_BASIC_RATE
    else:
        raise ValueError("未知的供電別，預期為 'HV' 或 'LV'")


def shift_month(year: int, month: int, delta: int) -> Tuple[int, int]:
    """
    以 (year, month) 為基準，往前/往後位移 delta 個月
    delta 可以是負數（往前）
    回傳 (new_year, new_month)
    """
    total = year * 12 + (month - 1) + delta
    new_year = total // 12
    new_month = total % 12 + 1
    return new_year, new_month


@dataclass
class ScenarioResult:
    contract_kw: float
    total_basic: float
    total_penalty: float
    annual_total: float
    avg_monthly: float


def run_simulation(
    customer_name: str,
    supply_type: str,          # "HV" or "LV"
    contract_kw_current: float,
    start_year: int,
    start_month: int,
    max_demands: List[float],  # 長度 12, index 0 = 起算月份, 往前推
):
    """
    回傳：
      - current_detail: 現行契約每月明細（list of dict）
      - current_summary: 現行契約一年總結（dict）
      - scan_table: 自動掃描契約容量結果（只保留最佳值上下各六格）
      - best_row: 最佳契約那一筆（dict）
      - avg_max_demand: 12 個月最大需量平均值（四捨五入）
    """
    if len(max_demands) != 12:
        raise ValueError("max_demands 必須剛好 12 筆資料")

    # ===== 建立 12 個月份清單（起算月份 + 往前 11 個月） =====
    months: List[Tuple[int, int]] = []
    for i in range(12):
        y, m = shift_month(start_year, start_month, -i)
        months.append((y, m))

    # ===== 現行契約月度明細 =====
    monthly_basic_rate_current = []
    monthly_basic_current = []
    monthly_penalty_current = []

    for i, (y, m) in enumerate(months):
        BR = get_basic_rate_for_month(m, supply_type)
        D = max_demands[i]

        basic_cost = contract_kw_current * BR
        penalty_cost = calc_over_penalty(D, contract_kw_current, BR)

        monthly_basic_rate_current.append(BR)
        monthly_basic_current.append(basic_cost)
        monthly_penalty_current.append(penalty_cost)

    total_basic_curr = sum(monthly_basic_current)
    total_penalty_curr = sum(monthly_penalty_current)
    annual_total_curr = total_basic_curr + total_penalty_curr
    avg_monthly_curr = annual_total_curr / 12

    current_detail = []
    for i, (y, m) in enumerate(months):
        current_detail.append({
            "年月": f"{y:04d}-{m:02d}",
            "季別": "夏月" if is_summer_month(m) else "非夏月",
            "單價(元/kW)": monthly_basic_rate_current[i],
            "最大需量(kW)": max_demands[i],
            "基本電費(元)": monthly_basic_current[i],
            "超約附加費(元)": monthly_penalty_current[i],
        })

    current_summary = {
        "客戶名稱": customer_name,
        "供電別": "高壓用電" if supply_type == "HV" else "低壓用電",
        "現行契約容量(kW)": contract_kw_current,
        "起算年月": f"{start_year:04d}-{start_month:02d}",
        "一年基本電費合計": total_basic_curr,
        "一年超約附加費合計": total_penalty_curr,
        "一年合計": annual_total_curr,
        "平均每月合計": avg_monthly_curr,
    }

    # ===== 依 12 個月最大需量平均值，自動產生契約容量候選集合 =====
    avg_max_demand_raw = sum(max_demands) / len(max_demands)
    avg_max_demand = int(round(avg_max_demand_raw))

    # 改為：以平均值為中心，向上 / 向下每 1 kW 掃描至 ±200 kW
    candidate_contracts = []

    for step in range(200, 0, -1):  # 向下
        c = avg_max_demand - step
        if c > 0:
            candidate_contracts.append(float(c))

    candidate_contracts.append(float(avg_max_demand))  # 中心

    for step in range(1, 201):  # 向上
        c = avg_max_demand + step
        candidate_contracts.append(float(c))

    candidate_contracts = sorted(set(candidate_contracts))

    # ===== 針對每一個候選契約容量計算一年成本 =====
    scenario_results: List[ScenarioResult] = []

    for C in candidate_contracts:
        monthly_basic = []
        monthly_penalty = []

        for i, (y, m) in enumerate(months):
            BR = get_basic_rate_for_month(m, supply_type)
            D = max_demands[i]

            basic_cost = C * BR
            penalty_cost = calc_over_penalty(D, C, BR)

            monthly_basic.append(basic_cost)
            monthly_penalty.append(penalty_cost)

        total_basic = sum(monthly_basic)
        total_penalty = sum(monthly_penalty)
        annual_total = total_basic + total_penalty
        avg_monthly = annual_total / 12

        scenario_results.append(
            ScenarioResult(
                contract_kw=C,
                total_basic=total_basic,
                total_penalty=total_penalty,
                annual_total=annual_total,
                avg_monthly=avg_monthly,
            )
        )

    # 找出一年合計最小的情境
    best_scenario = min(scenario_results, key=lambda s: s.annual_total)
    best_capacity = best_scenario.contract_kw

    # 只取最佳契約上下各六格
    sorted_contracts = sorted([s.contract_kw for s in scenario_results])
    best_index = sorted_contracts.index(best_capacity)
    start_index = max(0, best_index - 6)
    end_index = min(len(sorted_contracts) - 1, best_index + 6)
    display_contracts = sorted_contracts[start_index:end_index + 1]

    scan_table = []
    for s in scenario_results:
        if s.contract_kw in display_contracts:
            scan_table.append({
                "契約容量(kW)": s.contract_kw,
                "一年基本電費合計": s.total_basic,
                "一年超約附加費合計": s.total_penalty,
                "一年合計": s.annual_total,
                "平均每月": s.avg_monthly,
            })
    scan_table = sorted(scan_table, key=lambda r: r["契約容量(kW)"])

    best_row = {
        "契約容量(kW)": best_capacity,
        "一年基本電費合計": best_scenario.total_basic,
        "一年超約附加費合計": best_scenario.total_penalty,
        "一年合計": best_scenario.annual_total,
        "平均每月": best_scenario.avg_monthly,
    }

    return current_detail, current_summary, scan_table, best_row, avg_max_demand
