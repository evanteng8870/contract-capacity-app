# dev_app.py － 最適契約容量試算 v5.2.1（Tabs 開發版）

import datetime
import io
import os

import pandas as pd
import streamlit as st

from core_calc import run_simulation

# ====================== 共用小工具 ======================

def shift_month_local(base_date: datetime.date, delta: int) -> datetime.date:
    """
    以 base_date 為基準，往前 / 往後 delta 個月。
    固定回傳該月 1 號的日期。
    """
    month_index = base_date.year * 12 + (base_date.month - 1) + delta
    year = month_index // 12
    month = month_index % 12 + 1
    return datetime.date(year, month, 1)


# ====================== 密碼保護 ======================

CORRECT_PASSWORD = "0000"  # 開發版密碼，可自行修改


def check_password() -> bool:
    """簡單的密碼保護機制，通過回傳 True。"""

    def password_entered():
        if st.session_state["password"] == CORRECT_PASSWORD:
            st.session_state["password_correct"] = True
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input(
            "請輸入密碼：",
            type="password",
            key="password",
            on_change=password_entered,
        )
        return False

    if not st.session_state["password_correct"]:
        st.text_input(
            "請輸入密碼：",
            type="password",
            key="password",
            on_change=password_entered,
        )
        st.error("密碼錯誤，請再試一次。")
        return False

    return True


# ====================== 初始狀態 ======================

def ensure_defaults() -> None:
    """初始化所有會用到的 session_state key。"""

    if st.session_state.get("initialized_tabs"):
        return

    st.session_state["initialized_tabs"] = True

    # 基本資料（字串版，方便用 placeholder）
    st.session_state.setdefault("customer_name_str", "")
    st.session_state.setdefault("meter_no_str", "")
    st.session_state.setdefault("address_str", "")
    st.session_state.setdefault("supply_name", "高壓用電")
    st.session_state.setdefault("contract_kw_current_str", "")

    # 起算年月（預設本月）
    today = datetime.date.today()
    st.session_state.setdefault(
        "start_month_label", f"{today.year:04d}-{today.month:02d}"
    )

    # 12 個月最大需量：字串＋數值各一份
    for i in range(12):
        st.session_state.setdefault(f"md_{i}_str", "")
        st.session_state.setdefault(f"md_{i}", 0.0)

    # 試算結果
    st.session_state.setdefault("result_df", None)
    st.session_state.setdefault("best_contract_kw", None)


# ====================== PDF 報表（簡易版） ======================

def build_pdf_report(
    df_result: pd.DataFrame,
    customer_name: str,
    meter_no: str,
    address: str,
    supply_name: str,
    contract_kw_current: float,
) -> bytes:
    """
    Tabs 開發版簡易 PDF。
    如果日後要跟正式版完全一樣，可以把正式版的 build_pdf_report 搬過來取代這個函式。
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
    except ImportError:
        buffer = io.BytesIO()
        return buffer.getvalue()

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    margin_left = 20 * mm
    margin_top = height - 20 * mm
    line_h = 6 * mm

    # 標題
    c.setFont("Helvetica-Bold", 18)
    c.drawString(margin_left, margin_top, "最適契約容量試算報告（Tabs 開發版）")

    y = margin_top - 2 * line_h
    c.setFont("Helvetica", 11)
    c.drawString(margin_left, y, f"客戶名稱：{customer_name}")
    y -= line_h
    c.drawString(margin_left, y, f"台電電號：{meter_no}")
    y -= line_h
    c.drawString(margin_left, y, f"用電地址：{address}")
    y -= line_h
    c.drawString(margin_left, y, f"供電別：{supply_name}")
    y -= line_h
    c.drawString(margin_left, y, f"現行契約容量：{contract_kw_current:.0f} kW")

    # 結果摘要
    y -= 2 * line_h
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin_left, y, "試算結果節錄：")
    y -= 1.4 * line_h
    c.setFont("Helvetica", 10)

    # 找出關鍵欄位名稱
    kw_col_candidates = ["建議契約容量(kW)", "契約容量(kW)", "契約容量"]
    kw_col = next((cname for cname in kw_col_candidates if cname in df_result.columns), None)
    if kw_col is None:
        kw_col = df_result.columns[0]

    cost_col = "全年總費用(元)" if "全年總費用(元)" in df_result.columns else df_result.columns[-1]

    # 標題列
    c.drawString(margin_left, y, kw_col)
    c.drawString(margin_left + 60 * mm, y, cost_col)
    y -= line_h

    # 節錄前 8 筆
    for _, row in df_result.head(8).iterrows():
        if y < 30 * mm:
            c.showPage()
            y = margin_top

        try:
            kw_val = float(row[kw_col])
        except Exception:
            kw_val = row[kw_col]

        c.drawString(margin_left, y, f"{kw_val}")
        c.drawString(margin_left + 60 * mm, y, f"{row[cost_col]:,.0f}")
        y -= line_h

    y -= line_h
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(
        margin_left,
        y,
        "※ 本報告僅供試算參考，實際電費仍以台電電費帳單為準。",
    )

    c.showPage()
    c.save()
    pdf_value = buffer.getvalue()
    buffer.close()
    return pdf_value


# ====================== 樣式 ======================

def apply_global_style():
    """整體 CSS（深藍背景 + 手機優化）。"""
    st.markdown(
        """
        <style>
        /* 主畫面背景：深藍漸層 */
        [data-testid="stAppViewContainer"] {
            background: radial-gradient(circle at top,
                #1e3a8a 0,
                #0b1120 55%,
                #020617 100%);
            color: #ffffff;
        }

        /* 主要內容區塊間距 */
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 3rem;
        }

        /* 手機模式隱藏左上方 << 之類的 sidebar 切換按鈕 */
        @media (max-width: 1024px) {
            [data-testid="collapsedControl"],
            [data-testid="stSidebarCollapseButton"] {
                display: none !important;
            }
        }

        /* DataFrame 字體稍微小一點 */
        .stDataFrame tbody td {
            font-size: 0.85rem;
        }

                
        /* 按鈕樣式（例如「開始試算」、「清除資料」、「下載 PDF」） */
        .stButton button {
            background-color: #f97316;
            color: #ffffff;
            border-radius: 4px;
            border: none;
        }
        .stButton button:hover {
            background-color: #ea580c;
        }

        </style>
        """,
        unsafe_allow_html=True,
    )


# ====================== Tab 1：基本資料輸入 ======================

def render_basic_form():
    """Tab 1：基本資料輸入畫面。"""

    st.subheader("基本資料輸入")

    # 客戶名稱：placeholder 顯示「未命名客戶」，實際值留在 _str 裡
    name_input = st.text_input(
        "客戶名稱",
        value=st.session_state.get("customer_name_str", ""),
        placeholder="未命名客戶",
    )
    st.session_state["customer_name_str"] = name_input

    # 台電電號
    st.session_state["meter_no_str"] = st.text_input(
        "台電電號",
        value=st.session_state.get("meter_no_str", ""),
        placeholder="12-34-5678-90",
    )

    # 用電地址
    st.session_state["address_str"] = st.text_input(
        "用電地址",
        value=st.session_state.get("address_str", ""),
        placeholder="請輸入用電地址",
    )

    # 供電別
    st.session_state["supply_name"] = st.selectbox(
        "供電別",
        options=["高壓用電", "低壓用電"],
        index=0 if st.session_state.get("supply_name", "高壓用電") == "高壓用電" else 1,
    )

    # 現行契約容量：文字＋placeholder「0」，內部轉成整數
    contract_str = st.text_input(
        "現行契約容量 (kW)",
        value=st.session_state.get("contract_kw_current_str", ""),
        placeholder="0",
    )
    st.session_state["contract_kw_current_str"] = contract_str

    if contract_str.strip() == "":
        contract_kw = 0
    else:
        try:
            contract_kw = int(contract_str)
        except ValueError:
            st.warning("⚠ 現行契約容量請輸入整數 kW，已套用前次有效數值或 0。")
            contract_kw = int(st.session_state.get("contract_kw_current", 0))

    st.session_state["contract_kw_current"] = contract_kw

    
# ====================== Tab 2：12 個月最大需量 + 結果 ======================

def render_demand_and_result():
    """Tab 2：12 個月最大需量 & 試算結果。"""

    st.subheader("12 個月最大需量輸入")

def render_demand_and_result():
    """Tab 2：12 個月最大需量 & 試算結果。"""

    st.subheader("12 個月最大需量輸入")

    # ---- 起算年月選擇（移到這裡）----
    today = datetime.date.today()
    month_labels = []
    months = []
    for i in range(36):
        d = shift_month_local(today, -i)
        months.append(d)
        month_labels.append(f"{d.year:04d}-{d.month:02d}")

    current_label = st.session_state.get("start_month_label", month_labels[0])
    try:
        current_index = month_labels.index(current_label)
    except ValueError:
        current_index = 0

    choice = st.selectbox(
        "起算年月（最近三年內）",
        options=month_labels,
        index=current_index,
        help="以選定年月為第 1 筆，往前推共 12 個月份。",
    )
    st.session_state["start_month_label"] = choice

    st.markdown("---")

    # 根據起算年月產生 12 個月份（由舊到新）
    start_label = st.session_state.get("start_month_label")
    try:
        year, month = [int(x) for x in start_label.split("-")]
        start_date = datetime.date(year, month, 1)
    except Exception:
        st.error("起算年月格式錯誤，請回到『基本資料輸入』重新選擇，例如：2025-11")
        return

    # 以「起算年月」為第一格，往前推 11 個月，共 12 個月份
    # 例如起算 2025-11 → 顯示順序：2025-11、2025-10、…、2024-12
    months_desc = [shift_month_local(start_date, -i) for i in range(0, 12)]
    month_labels_desc = [f"{d.year:04d}-{d.month:02d}" for d in months_desc]

    # 12 個輸入格（文字＋placeholder「0」）
    for i, label in enumerate(month_labels_desc):
        key_str = f"md_{i}_str"
        key_num = f"md_{i}"

        md_str = st.text_input(
            f"{label} 最大需量 (kW)",
            value=st.session_state.get(key_str, ""),
            placeholder="0",
        )
        st.session_state[key_str] = md_str

        if md_str.strip() == "":
            md_val = 0.0
        else:
            try:
                md_val = float(md_str)
            except ValueError:
                st.warning(f"⚠ {label} 最大需量請輸入數字，已套用前次有效數值或 0。")
                md_val = float(st.session_state.get(key_num, 0.0))

        st.session_state[key_num] = md_val

    st.markdown("---")

    # ====== 試算 / 清除 按鈕 ======
    col_run, col_clear = st.columns([1, 1])
    with col_run:
        run_clicked = st.button("開始試算")
    with col_clear:
        clear_clicked = st.button("清除資料")

    # 清除：把 12 個月輸入 & 結果都清空
    if clear_clicked:
        for i in range(12):
            st.session_state[f"md_{i}_str"] = ""
            st.session_state[f"md_{i}"] = 0.0
        st.session_state["result_df"] = None
        st.session_state["best_contract_kw"] = None
        st.experimental_rerun()

    # ====== 試算邏輯（改成跟 app.py 一樣的介面） ======
    if run_clicked:
        # 12 個月最大需量（已經在前面用 text_input 收好）
        demand_values = [st.session_state[f"md_{i}"] for i in range(12)]

        # 這個 df_demand 只是保留用，如果之後想畫圖、檢查也可以用
        df_demand = pd.DataFrame(
            {
                "年月": month_labels_desc,
                "最大需量(kW)": demand_values,
            }
        )

        # ===== 跟 app.py 一樣先整理參數 =====
        # 客戶名稱（空的時候顯示「未命名客戶」）
        display_customer_name = (
            st.session_state.get("customer_name_str", "").strip() or "未命名客戶"
        )

        # 供電別：轉成 supply_type（HV / LV）
        supply_name = st.session_state.get("supply_name", "高壓用電")
        supply_type = "HV" if supply_name == "高壓用電" else "LV"

        # 現行契約容量
        contract_kw_value = float(st.session_state.get("contract_kw_current", 0.0))

        # 起算年月（剛剛上面用 start_date 算出來的）
        start_year = start_date.year
        start_month = start_date.month

        # 12 個月最大需量列表
        max_demands = demand_values

        # ===== 實際呼叫 run_simulation（介面完全比照 app.py）=====
        with st.spinner("計算中..."):
            try:
                (
                    current_detail,
                    current_summary,
                    scan_table,
                    best_row,
                    avg_max_demand,
                ) = run_simulation(
                    customer_name=display_customer_name,
                    supply_type=supply_type,
                    contract_kw_current=contract_kw_value,
                    start_year=start_year,
                    start_month=start_month,
                    max_demands=max_demands,
                )
            except Exception as e:
                st.error(f"試算時發生錯誤：{e}")
                return

        # 把結果存進 session_state，下面顯示用
        st.session_state["result_df"] = scan_table
        st.session_state["current_summary"] = current_summary
        st.session_state["best_contract_kw"] = (
            best_row.get("契約容量(kW)")
            if isinstance(best_row, dict) or hasattr(best_row, "get")
            else None
        )

    result_df = st.session_state.get("result_df")
    if result_df is not None:
        st.subheader("試算結果")
        st.dataframe(result_df, use_container_width=True)

        # 如果有全年總費用欄位，找出最低者
        best_kw = None
        if "全年總費用(元)" in result_df.columns:
            best_idx = result_df["全年總費用(元)"].idxmin()
            best_row = result_df.loc[best_idx]
            kw_col_candidates = ["建議契約容量(kW)", "契約容量(kW)", "契約容量"]
            kw_col = next((c for c in kw_col_candidates if c in result_df.columns), None)
            if kw_col:
                best_kw = best_row[kw_col]
                st.success(f"建議契約容量：約 {best_kw} kW（依全年總費用最低）")

        st.markdown("---")

        if st.button("下載試算報告（PDF）"):
            customer_name = (
                st.session_state.get("customer_name_str", "").strip()
                or "未命名客戶"
            )
            meter_no = st.session_state.get("meter_no_str", "")
            address = st.session_state.get("address_str", "")
            supply_name = st.session_state.get("supply_name", "高壓用電")
            contract_kw = float(st.session_state.get("contract_kw_current", 0))

            pdf_bytes = build_pdf_report(
                result_df,
                customer_name=customer_name,
                meter_no=meter_no,
                address=address,
                supply_name=supply_name,
                contract_kw_current=contract_kw,
            )

            st.download_button(
                label="下載 PDF 報告",
                data=pdf_bytes,
                file_name="契約容量試算報告_Tabs開發版.pdf",
                mime="application/pdf",
            )


# ====================== 主程式 ======================

def main():
    st.set_page_config(
        page_title="最適契約容量試算 v5.2.1（Tabs 開發版）",
        layout="wide",
    )

    if not check_password():
        st.stop()

    ensure_defaults()
    apply_global_style()

    st.caption(
        "📱 提示：此為「開發用 Tabs 版本」。"
        "上方分頁可切換「基本資料輸入」與「12 個月最大需量輸入」。"
    )

    st.title("最適契約容量試算 v5.2.1（Tabs 開發版）")

    tab_basic, tab_demand = st.tabs(["基本資料輸入", "12 個月最大需量輸入"])

    with tab_basic:
        render_basic_form()

    with tab_demand:
        render_demand_and_result()


if __name__ == "__main__":
    main()