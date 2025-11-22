# app.py
import datetime
import io
import json
import os

import pandas as pd
import streamlit as st

from core_calc import run_simulation, shift_month

# ====== 橫幅圖片路徑 ======
BANNER_PATH = "banner_header.jpg"  # 寬版招牌圖

# ================== 共用：初始化預設值 ==================
def ensure_defaults() -> None:
    """
    第一次執行時，設定所有欄位的預設值。
    之後所有 widget 只用 key 綁定，不額外給 value/index，
    讓狀態完全由 session_state 控制。
    """
    if st.session_state.get("initialized"):
        return

    st.session_state["initialized"] = True

    # 基本資料
    st.session_state["customer_name"] = ""
    st.session_state["meter_no"] = ""
    st.session_state["address"] = ""
    st.session_state["supply_name"] = "高壓用電"
    # 契約容量：字串輸入欄位，預設空白，placeholder 顯示 0
    st.session_state["contract_kw_current"] = ""

    # 起算年月（只記「YYYY-MM」字串）
    today = datetime.date.today()
    st.session_state["start_month_label"] = f"{today.year:04d}-{today.month:02d}"

    # 12 個最大需量欄位：一律預設空白
    for i in range(12):
        st.session_state[f"md_{i}"] = ""


# ================== 清除全部資料（唯一重置按鈕） ==================
def clear_all() -> None:
    """
    清除所有輸入與計算結果，並寫回預設值。
    """
    st.session_state["customer_name"] = ""
    st.session_state["meter_no"] = ""
    st.session_state["address"] = ""
    st.session_state["supply_name"] = "高壓用電"
    st.session_state["contract_kw_current"] = ""

    today = datetime.date.today()
    st.session_state["start_month_label"] = f"{today.year:04d}-{today.month:02d}"

    for i in range(12):
        st.session_state[f"md_{i}"] = ""


# ================== PDF 字型處理 ==================
def register_cjk_font() -> str:
    """
    嘗試註冊可顯示中文的字型。
    優先使用專案目錄下的 NotoSansTC；找不到就退回 Helvetica。
    回傳給 ReportLab 使用的 fontName。
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = [
        "NotoSansTC-Regular.otf",
        "NotoSansTC-Regular.ttf",
        "NotoSansCJKtc-Regular.otf",
        os.path.join("fonts", "NotoSansTC-Regular.otf"),
        os.path.join("fonts", "NotoSansTC-Regular.ttf"),
    ]

    for path in candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("CJK", path))
                return "CJK"
            except Exception:
                continue

    # 找不到就用內建 Helvetica（中文可能 fallback 成系統行為）
    return "Helvetica"


# ================== PDF 報表產生 ==================
def build_pdf_report(
    *,
    current_summary: dict,
    df_curr: pd.DataFrame,
    df_scan: pd.DataFrame,
    best_row: dict,
    customer_name: str,
    meter_no: str,
    address: str,
    contract_kw_value: int,
    pdf_date: datetime.date,
) -> bytes:
    """
    依照目前試算結果，產生一份精簡 PDF 報表。
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        Image,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    font_name = register_cjk_font()
    styles = getSampleStyleSheet()

    styleN = ParagraphStyle(
        "NormalCJK",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=10,
        leading=14,
    )
    styleH = ParagraphStyle(
        "HeadingCJK",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=14,
        leading=18,
        spaceAfter=6,
    )
    styleTR = ParagraphStyle(
        "RightAlign",
        parent=styleN,
        alignment=2,  # 右對齊
    )

    story = []

    # 招牌圖片
    if os.path.exists(BANNER_PATH):
        img = Image(BANNER_PATH)
        max_width = A4[0] - 40 * mm
        max_height = 40 * mm
        img._restrictSize(max_width, max_height)
        story.append(img)
        story.append(Spacer(1, 8))

    # 標題與 PDF 日期
    story.append(Paragraph("最適契約容量試算報告 v5.2", styleH))
    story.append(Paragraph(f"PDF 製作日期：{pdf_date.isoformat()}", styleN))
    story.append(Spacer(1, 8))

    # ================== 一、基本資料 ==================
    story.append(Paragraph("一、基本資料", styleH))
    story.append(
        Paragraph(
            f"客戶名稱：{customer_name}<br/>"
            f"台電電號：{meter_no}<br/>"
            f"用電地址：{address}<br/>"
            f"供電別：{current_summary['供電別']}<br/>"
            f"起算年月：{current_summary['起算年月']}<br/>"
            f"現行契約容量：{current_summary['現行契約容量(kW)']:.1f} kW",
            styleN,
        )
    )
    story.append(Spacer(1, 10))

    # ================== 二、現行契約一年結算結果 ==================
    story.append(Paragraph("二、現行契約一年結算結果", styleH))

    cs = current_summary
    summary_data = [
        ["項目", "金額（元）"],
        ["一年基本電費合計", f"{cs['一年基本電費合計']:.1f}"],
        ["一年超約附加費合計", f"{cs['一年超約附加費合計']:.1f}"],
        ["一年合計", f"{cs['一年合計']:.1f}"],
    ]
    tbl_summary = Table(summary_data, hAlign="LEFT")
    tbl_summary.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
            ]
        )
    )
    story.append(tbl_summary)
    story.append(Spacer(1, 10))

    # ================== 三、現行契約與最適契約成本比較 ==================
    story.append(Paragraph("三、現行契約與最適契約成本比較", styleH))

    best_total = best_row["一年合計"]
    best_cap_kw = best_row["契約容量(kW)"]
    saving = cs["一年合計"] - best_total

    compare_data = [
        ["項目", "契約容量(kW)", "一年合計金額（元）"],
        [
            "現行契約",
            f"{contract_kw_value:.1f}",
            f"{cs['一年合計']:.1f}",
        ],
        [
            "最適契約",
            f"{best_cap_kw:.1f}",
            f"{best_total:.1f}",
        ],
    ]

    from reportlab.platypus import Table, TableStyle

    tbl_compare = Table(
        compare_data, hAlign="LEFT", colWidths=[40 * mm, 40 * mm, 60 * mm]
    )
    tbl_compare.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 1), (1, -1), "CENTER"),
                ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
            ]
        )
    )
    story.append(tbl_compare)

    if saving > 0:
        msg = f"採用最適契約容量時，每年可節省約 {saving:.1f} 元（基本電費＋超約附加費合計）。"
    elif saving < 0:
        msg = f"採用最適契約容量時，每年將增加約 {abs(saving):.1f} 元（基本電費＋超約附加費合計）。"
    else:
        msg = "最適契約容量與現行契約容量的一年總金額相同。"

    story.append(Spacer(1, 6))
    story.append(Paragraph(msg, styleN))
    story.append(Spacer(1, 10))

    # ================== helper：DataFrame → Table（含交錯底色、最佳列淡橘） ==================
    def dataframe_to_table(
        df: pd.DataFrame,
        title: str | None = None,
        best_index: int | None = None,
    ) -> None:
        from reportlab.platypus import Table, TableStyle

        if title:
            story.append(Paragraph(title, styleH))

        if df.empty:
            story.append(Paragraph("（無資料）", styleN))
            story.append(Spacer(1, 6))
            return

        df_local = df.copy()

        # 所有數字欄位四捨五入到小數點 1 位
        for col in df_local.select_dtypes(include=["number"]).columns:
            df_local[col] = df_local[col].round(1)

        data = [list(df_local.columns)] + df_local.astype(str).values.tolist()
        tbl = Table(data, hAlign="LEFT")

        style_cmds = [
            ("FONTNAME", (0, 0), (-1, -1), font_name),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]

        # 「單價」「最大需量」→置中；「電費」「附加費」「合計」→靠右
        for idx, col in enumerate(df_local.columns):
            col_name = str(col)
            if any(k in col_name for k in ["單價", "最大需量"]):
                style_cmds.append(("ALIGN", (idx, 0), (idx, -1), "CENTER"))
            elif any(k in col_name for k in ["電費", "附加費", "合計"]):
                style_cmds.append(("ALIGN", (idx, 1), (idx, -1), "RIGHT"))

        # 交錯底色（從資料列 row=1 開始）
        for row_i in range(1, len(data)):
            if best_index is not None and row_i == best_index + 1:
                # 這一列讓給淡橘色標註，不套交錯色
                continue
            bg = (
                colors.HexColor("#F9FAFB")
                if row_i % 2 == 1
                else colors.HexColor("#E5E7EB")
            )
            style_cmds.append(("BACKGROUND", (0, row_i), (-1, row_i), bg))

        # 最佳契約列：淡橘色底 + 深字
        if best_index is not None:
            row_best = best_index + 1  # header 在第 0 列
            style_cmds.append(
                ("BACKGROUND", (0, row_best), (-1, row_best), colors.HexColor("#FED7AA"))
            )
            style_cmds.append(
                ("TEXTCOLOR", (0, row_best), (-1, row_best), colors.HexColor("#7C2D12"))
            )

        tbl.setStyle(TableStyle(style_cmds))
        story.append(tbl)
        story.append(Spacer(1, 10))

    # ================== 四、現行契約每月明細 ==================
    dataframe_to_table(df_curr, "四、現行契約每月明細")

    # ================== 五、契約容量掃描結果（節錄） ==================
    # 找出最佳契約列在 df_scan 中的 index
    best_cap_kw_val = best_row["契約容量(kW)"]
    best_indices = df_scan.index[df_scan["契約容量(kW)"] == best_cap_kw_val].tolist()
    best_idx = best_indices[0] if best_indices else None

    dataframe_to_table(df_scan, "五、契約容量掃描結果（節錄）", best_index=best_idx)

    # 頁尾
    story.append(Spacer(1, 12))
    story.append(Paragraph("※ 試算結果僅供參考，實際金額以台電帳單為準。", styleN))
    story.append(Spacer(1, 18))
    story.append(Paragraph("關山水電工程股份有限公司 製作", styleTR))

    doc.build(story)
    pdf_value = buffer.getvalue()
    buffer.close()
    return pdf_value


# ================== Streamlit 基本設定 ==================
st.set_page_config(page_title="最適契約容量試算 v5.2", layout="wide")

# 先確保有預設值，再開始畫畫面
ensure_defaults()

# ================== 全局樣式（背景色 + 字型微調 + 按鈕顏色） ==================
st.markdown(
    """
    <style>
      /* 主畫面背景：深藍漸層 */
      [data-testid="stAppViewContainer"] {
          background: radial-gradient(circle at top,
                                      #1e3a8a 0,
                                      #0b1120 55%,
                                      #020617 100%);
      }

      /* 側邊欄背景：深藍灰漸層 */
      [data-testid="stSidebar"] {
          background: linear-gradient(180deg, #020617, #020617);
      }

      /* 側邊欄文字稍微亮一點 */
      [data-testid="stSidebar"] * {
          color: #e5e7eb !important;
      }

      /* 輸入框統一深色底、白字（桌機 + 手機） */
      input[type="text"], input[type="number"] {
          background-color: #020617 !important;
          color: #e5e7eb !important;
      }

      /* select 下拉顯示區（供電別、起算年月） */
      div[data-baseweb="select"] > div {
          background-color: #020617 !important;
          color: #e5e7eb !important;
      }

      /* DataFrame 表格字顏色保持高對比 */
      [data-testid="stTable"], [data-testid="stDataFrame"] {
          color: #0f172a !important;
      }

      /* metric 大字改亮一點，避免太淡 */
      [data-testid="stMetricValue"] {
          color: #e5e7eb !important;
      }

      /* ===== 按鈕顏色設定 ===== */

      /* type="primary" → 開始試算：紅色 */
      button[data-testid="baseButton-primary"] {
          background-color: #ef4444 !important;  /* red-500 */
          color: #ffffff !important;
          border-radius: 999px !important;
          border: none !important;
      }

      button[data-testid="baseButton-primary"]:hover {
          background-color: #dc2626 !important;  /* red-600 */
      }

      /* secondary 共通：圓角，無邊框 */
      button[data-testid="baseButton-secondary"] {
          border-radius: 999px !important;
          border: none !important;
      }

      /* 第一個 secondary → 清除資料並重新輸入：綠色 */
      button[data-testid="baseButton-secondary"]:first-of-type {
          background-color: #22c55e !important;  /* green-500 */
          color: #ffffff !important;
      }
      button[data-testid="baseButton-secondary"]:first-of-type:hover {
          background-color: #16a34a !important;  /* green-600 */
      }

      /* 最後一個 secondary → 下載試算結果 PDF：橘色 */
      button[data-testid="baseButton-secondary"]:last-of-type {
          background-color: #f97316 !important;  /* orange-500 */
          color: #ffffff !important;
      }
      button[data-testid="baseButton-secondary"]:last-of-type:hover {
          background-color: #ea580c !important;  /* orange-600 */
      }

    </style>
    """,
    unsafe_allow_html=True,
)

# ================== 頁首招牌圖 + 標題 ==================
if os.path.exists(BANNER_PATH):
    st.image(BANNER_PATH, use_container_width=True)

# 兩行標題（網頁版）：行距稍微縮小，手機也會自動換行
st.markdown(
    """
    <h1 style="color:#f9fafb; margin-bottom:0.1rem;">
      最適契約容量試算
    </h1>
    <h3 style="color:#f9fafb; margin-top:0;">
      版本 5.2
    </h3>
    """,
    unsafe_allow_html=True,
)

st.caption("高壓 / 低壓用電 · 自動掃描契約容量 · 基本電費 + 超約附加費試算")
st.markdown("---")

# ================== 側邊欄：基本資料輸入 ==================
with st.sidebar:
    st.header("基本資料輸入")

    # 客戶名稱
    customer_name = st.text_input(
        "客戶名稱",
        key="customer_name",
        placeholder="未命名客戶",
    )

    # 台電電號
    meter_no = st.text_input(
        "台電電號",
        key="meter_no",
        placeholder="12-34-5678-90",
    )

    # 用電地址
    address = st.text_input(
        "用電地址",
        key="address",
        placeholder="請輸入用電地址",
    )

    # 供電別
    supply_name = st.selectbox(
        "供電別",
        ["高壓用電", "低壓用電"],
        key="supply_name",
    )
    supply_type = "HV" if supply_name == "高壓用電" else "LV"

    # 現行契約容量 (kW) —— 文字輸入、只收整數，placeholder「0」
    contract_kw_current_str = st.text_input(
        "現行契約容量 (kW)",
        key="contract_kw_current",
        placeholder="0",
    )

# ================== 12 個月最大需量輸入區 ==================
st.subheader("12 個月最大需量輸入")

# 起算年月（最近三年內，轉軸在主畫面）
today = datetime.date.today()
month_labels: list[str] = []
for i in range(36):  # 最近 36 個月（含本月）
    y, m = shift_month(today.year, today.month, -i)
    month_labels.append(f"{y:04d}-{m:02d}")

default_label = f"{today.year:04d}-{today.month:02d}"
if "start_month_label" not in st.session_state:
    st.session_state["start_month_label"] = default_label
if st.session_state["start_month_label"] not in month_labels:
    st.session_state["start_month_label"] = default_label

start_month_label = st.selectbox(
    "起算年月（最近三年內）",
    month_labels,
    index=month_labels.index(st.session_state["start_month_label"]),
    key="start_month_label",
)

start_year = int(start_month_label.split("-")[0])
start_month = int(start_month_label.split("-")[1])

st.markdown("說明：以起算月份為第 1 筆，往前推共 12 個月份。")

# 產生 12 個月份標籤（起算月往前推）
months: list[tuple[int, int]] = []
for i in range(12):
    y, m = shift_month(start_year, start_month, -i)
    months.append((y, m))

max_demand_strs: list[str] = []
month_input_keys: list[str] = []

group_cols = st.columns(3, gap="large")

for col_idx in range(3):
    with group_cols[col_idx]:
        for row_idx in range(4):
            idx = col_idx * 4 + row_idx
            y, m = months[idx]
            label = f"{y:04d}-{m:02d} 最大需量(kW)"
            key = f"md_{idx}"
            month_input_keys.append(key)

            raw = st.text_input(
                label,
                key=key,
                placeholder="0",
            )
            max_demand_strs.append(raw)

st.markdown("---")

# ================== 按鈕列：開始試算 + 清除全部 ==================
col_run, col_reset_all = st.columns(2)

with col_run:
    run_clicked = st.button("開始試算", type="primary")

with col_reset_all:
    st.button("清除資料並重新輸入", on_click=clear_all)

# ================== 主體：開始試算 ==================
if run_clicked:
    # 先檢查現行契約容量
    ckw_raw = str(contract_kw_current_str).strip()
    if (not ckw_raw.isdigit()) or int(ckw_raw) <= 0:
        st.error("現行契約容量必須為大於 0 的整數（kW），請重新輸入。")
    else:
        contract_kw_value = int(ckw_raw)

        # 檢查 12 個最大需量
        max_demands: list[int] = []
        invalid_indices = []
        non_positive_indices = []

        for idx, raw in enumerate(max_demand_strs):
            s = str(raw).strip()

            if s == "":
                value = 0
            else:
                if not s.isdigit():
                    invalid_indices.append(idx)
                    value = 0
                else:
                    value = int(s)

            if value <= 0:
                non_positive_indices.append(idx)

            max_demands.append(value)

        if invalid_indices:
            month_labels_err = [
                f"{months[i][0]:04d}-{months[i][1]:02d}" for i in invalid_indices
            ]
            st.error(
                "以下月份的最大需量輸入「不是純數字」，請修正後再試算：\n\n"
                + "、".join(month_labels_err)
            )
        elif non_positive_indices:
            month_labels_err = [
                f"{months[i][0]:04d}-{months[i][1]:02d}" for i in non_positive_indices
            ]
            st.error(
                "所有最大需量必須大於 0 kW，以下月份目前為 0 或未填寫，請補齊：\n\n"
                + "、".join(month_labels_err)
            )
        else:
            display_customer_name = customer_name.strip() or "未命名客戶"
            display_meter_no = meter_no.strip() or "（未輸入）"
            display_address = address.strip() or "（未輸入）"
            calc_date = datetime.date.today()

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
                    contract_kw_current=contract_kw_value,
                    start_year=start_year,
                    start_month=start_month,
                    max_demands=max_demands,
                )

            st.success("試算完成 ✅")

            # ===== 現行契約一年結算結果 =====
            st.subheader("現行契約一年結算結果")
            csum = current_summary
            st.write(
                f"**客戶名稱：** {csum['客戶名稱']}  \n"
                f"**台電電號：** {display_meter_no}  \n"
                f"**用電地址：** {display_address}  \n"
                f"**供電別：** {csum['供電別']}  \n"
                f"**現行契約容量：** {csum['現行契約容量(kW)']:.1f} kW  \n"
                f"**起算年月：** {csum['起算年月']}  \n"
                f"**試算日期：** {calc_date.isoformat()}  \n"
            )

            col1, col2, col3 = st.columns(3)
            col1.metric("一年基本電費合計", f"{csum['一年基本電費合計']:,.0f} 元")
            col2.metric("一年超約附加費合計", f"{csum['一年超約附加費合計']:,.0f} 元")
            col3.metric("一年合計", f"{csum['一年合計']:,.0f} 元")

            # ===== 現行契約每月明細 =====
            st.markdown("#### 現行契約每月明細")
            df_curr = pd.DataFrame(current_detail)
            st.dataframe(df_curr, use_container_width=True)

            # ===== 契約容量掃描結果（最佳值上下各六格） =====
            st.markdown("#### 契約容量掃描結果（最佳值上下各六格）")
            st.markdown(
                f"12 個月最大需量平均值：約 **{avg_max_demand:.0f} kW**  \n"
                "以平均值為中心，**每 1 kW** 向上 / 向下掃描至 **±200 kW**，"
                "以下僅列出「最適契約容量」上下各六格。"
            )

            df_scan = pd.DataFrame(scan_table)

            if "平均每月" in df_scan.columns:
                df_scan = df_scan.drop(columns=["平均每月"])

            # 確保有「備註」欄，並標示最適契約
            if "備註" not in df_scan.columns:
                df_scan["備註"] = ""

            best_cap = best_row["契約容量(kW)"]
            df_scan.loc[df_scan["契約容量(kW)"] == best_cap, "備註"] = "最適契約"

            def highlight_best(row):
                color = "#fed7aa" if abs(row["契約容量(kW)"] - best_cap) < 1e-6 else ""
                return ["background-color: {}".format(color)] * len(row)

            st.dataframe(
                df_scan.style.apply(highlight_best, axis=1).format(
                    {
                        "契約容量(kW)": "{:.0f}",
                        "一年基本電費合計": "{:,.0f}",
                        "一年超約附加費合計": "{:,.0f}",
                        "一年合計": "{:,.0f}",
                    }
                ),
                use_container_width=True,
            )

            # ===== 現行契約與最適契約成本比較 =====
            st.markdown("#### 現行契約與最適契約成本比較")

            best_total = best_row["一年合計"]
            best_cap_kw = best_row["契約容量(kW)"]
            saving = csum["一年合計"] - best_total

            colL, colR = st.columns(2)

            with colL:
                st.metric(
                    f"現行契約一年總金額（{contract_kw_value} kW）",
                    f"{csum['一年合計']:,.0f} 元",
                )

            with colR:
                st.metric(
                    f"最適契約一年總金額（{best_cap_kw:.0f} kW）",
                    f"{best_total:,.0f} 元",
                    delta=f"{saving:,.0f} 元" if saving != 0 else None,
                )

            if saving > 0:
                st.success(
                    f"採用最適契約容量時，每年可節省約 **{saving:,.0f} 元**"
                    "（基本電費＋超約附加費合計）。"
                )
            elif saving < 0:
                st.warning(
                    f"採用最適契約容量時，每年將增加約 **{abs(saving):,.0f} 元**"
                    "（基本電費＋超約附加費合計）。"
                )
            else:
                st.info("最適契約容量與現行契約容量的一年總金額相同。")

            st.caption("※ 試算結果僅供參考，實際金額以台電帳單為準。")

            # ===== 產生 PDF 並提供下載 =====
            pdf_bytes = build_pdf_report(
                current_summary=csum,
                df_curr=df_curr,
                df_scan=df_scan,
                best_row=best_row,
                customer_name=display_customer_name,
                meter_no=display_meter_no,
                address=display_address,
                contract_kw_value=contract_kw_value,
                pdf_date=calc_date,
            )

            st.download_button(
                label="下載試算結果 PDF",
                data=pdf_bytes,
                file_name=f"契約容量試算_{display_customer_name}.pdf",
                mime="application/pdf",
            )

else:
    st.info("請先在左側輸入資料，再按下「開始試算」。")