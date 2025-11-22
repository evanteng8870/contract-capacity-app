# app.py
import datetime
import pandas as pd
import streamlit as st


st.set_page_config(page_title="最適契約容量試算 v5.2", layout="wide")

st.title("最適契約容量試算 v5.2")
st.caption("高壓 / 低壓用電 · 自動掃描契約容量 · 基本電費 + 超約附加費試算")

st.markdown("---")

# ===== 側邊欄：基本參數輸入 =====
with st.sidebar:
    st.header("基本資料輸入")

    # 客戶名稱：
    # - 顯示 placeholder「未命名客戶」
    # - 使用者點進去時，不需要刪字，直接輸入即可
    # - 若最後留空，後端自動視為「未命名客戶」
    customer_name = st.text_input(
        "客戶名稱",
        value="",  # 不預填文字
        placeholder="未命名客戶",
    )

    supply_name = st.selectbox("供電別", ["高壓用電", "低壓用電"])
    supply_type = "HV" if supply_name == "高壓用電" else "LV"

    # 現行契約容量仍維持可以輸入小數
    contract_kw_current = st.number_input(
        "現行契約容量 (kW)",
        min_value=1.0,
        step=1.0,
        value=100.0,
    )

    start_date = st.date_input(
        "起算年月（選該月任一天即可）",
        value=datetime.date.today(),
    )
    start_year = start_date.year
    start_month = start_date.month

st.subheader("12 個月最大需量輸入")
st.markdown("說明：以起算月份為第 1 筆，往前推共 12 個月份。")

# 產生 12 個月份標籤（起算月往前推）
months = []
for i in range(12):
    y, m = shift_month(start_year, start_month, -i)
    months.append((y, m))

cols = st.columns(4)
max_demands = []
for idx, (y, m) in enumerate(months):
    col = cols[idx % 4]
    with col:
        label = f"{y:04d}-{m:02d} 最大需量(kW)"
        # 最大需量：
        # - 預設為 0
        # - 不用小數點（整數）
        # - 點擊後會出數字輸入鍵盤（browser 的 number input 行為）
        v = st.number_input(
            label,
            min_value=0,
            step=1,
            value=0,
            format="%d",  # 整數，不顯示小數點
            key=f"md_{idx}",
        )
        max_demands.append(v)

st.markdown("---")

# ===== 按鈕列：開始試算 + 重新輸入 =====
col_run, col_reset = st.columns([1, 1])

with col_run:
    run_clicked = st.button("開始試算", type="primary")

with col_reset:
    reset_clicked = st.button("重新輸入")

# 按下「重新輸入」時，將 12 個最大需量欄位重設為 0
if reset_clicked:
    for idx in range(12):
        st.session_state[f"md_{idx}"] = 0
    st.info("已重新將 12 個月份的最大需量重設為 0。")

# ===== 開始試算 =====
if run_clicked:
    if any(v <= 0 for v in max_demands):
        st.error("所有最大需量必須大於 0 kW，請檢查輸入。")
    else:
        # 若客戶名稱留空，後端自動視為「未命名客戶」
        display_customer_name = customer_name.strip() or "未命名客戶"

        with st.spinner("計算中..."):
            (
                current_detail,
                current_summary,
                scan_table,
                best_row,
                avg_max_demand,
            ) = run_simulation(
                customer_name=display_customer_name,
                supply_type=supply_type,
                contract_kw_current=contract_kw_current,
                start_year=start_year,
                start_month=start_month,
                max_demands=max_demands,
            )

        st.success("試算完成 ✅")

        # ===== 現行契約總結 =====
        st.subheader("現行契約一年結算結果")
        csum = current_summary
        st.write(
            f"**客戶名稱：** {csum['客戶名稱']}  \n"
            f"**供電別：** {csum['供電別']}  \n"
            f"**現行契約容量：** {csum['現行契約容量(kW)']:.1f} kW  \n"
            f"**起算年月：** {csum['起算年月']}  \n"
        )

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("一年基本電費合計", f"{csum['一年基本電費合計']:,.0f} 元")
        col2.metric("一年超約附加費合計", f"{csum['一年超約附加費合計']:,.0f} 元")
        col3.metric("一年合計", f"{csum['一年合計']:,.0f} 元")
        col4.metric("平均每月合計", f"{csum['平均每月合計']:,.0f} 元/月")

        # ===== 現行契約每月明細 =====
        st.markdown("#### 現行契約每月明細")
        df_curr = pd.DataFrame(current_detail)
        st.dataframe(df_curr, use_container_width=True)

        # ===== 契約容量掃描結果（最佳值上下各六格） =====
        st.markdown("#### 契約容量掃描結果（最佳值上下各六格）")
        st.markdown(
            f"12 個月最大需量平均值：約 **{avg_max_demand:.0f} kW**  \n"
            "以平均值為中心，**每 1 kW** 向上 / 向下掃描至 **±200 kW**，"
            "以下僅列出「最佳契約容量」上下各六格。"
        )

        df_scan = pd.DataFrame(scan_table)
        best_cap = best_row["契約容量(kW)"]

        def highlight_best(row):
            color = "#ffcccc" if abs(row["契約容量(kW)"] - best_cap) < 1e-6 else ""
            return ["background-color: {}".format(color)] * len(row)

        st.dataframe(
            df_scan.style.apply(highlight_best, axis=1).format({
                "契約容量(kW)": "{:.0f}",
                "一年基本電費合計": "{:,.0f}",
                "一年超約附加費合計": "{:,.0f}",
                "一年合計": "{:,.0f}",
                "平均每月": "{:,.0f}",
            }),
            use_container_width=True,
        )

        # ===== 現行契約 vs 最適契約 =====
        st.markdown("#### 現行契約 vs 最適契約")

        best_total = best_row["一年合計"]
        saving = csum["一年合計"] - best_total

        colL, colR = st.columns(2)
        with colL:
            st.metric("現行契約一年總金額", f"{csum['一年合計']:,.0f} 元")
        with colR:
            st.metric(
                "最適契約一年總金額",
                f"{best_total:,.0f} 元",
                delta=f"{saving:,.0f} 元" if saving != 0 else None,
            )

        if saving > 0:
            st.success(f"採用最適契約容量時，每年可節省約 **{saving:,.0f} 元**（基本電費＋超約附加費合計）。")
        elif saving < 0:
            st.warning(f"採用最適契約容量時，每年將增加約 **{abs(saving):,.0f} 元**（基本電費＋超約附加費合計）。")
        else:
            st.info("最適契約容量與現行契約容量的一年總金額相同。")

        st.caption("※ 試算結果僅供參考，實際金額以台電帳單為準。")
else:
    st.info("請先在左側輸入資料，再按下「開始試算」。")