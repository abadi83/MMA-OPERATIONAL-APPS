"""Finance Page - Laba Rugi + Cashflow"""
import streamlit as st
st.set_page_config(page_title="ðŸ’° Finance", page_icon="ðŸ’°", layout="wide")

import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); from modules.shared import *
import pandas as pd
from datetime import datetime, timedelta

inject_pwa()
init_session()

if not st.session_state.get("authenticated"):
    st.switch_page("pages/00_Login.py")
    st.stop()

db = st.session_state.db
user = st.session_state.user
auto_amortisasi_bulanan(db)
render_sidebar()

tab1, tab2 = st.tabs(["ðŸ“Š Laba Rugi Harian", "ðŸ’µ Cashflow"])

with tab1:
    st.subheader("ðŸ“Š Laba Rugi Harian")
    tgl = st.date_input("Tanggal", datetime.now(), key="laba_tgl")
    tgl_str = tgl.strftime("%d-%m-%Y")

    # Revenue (PACKED orders)
    packed = db.fetch_all("SELECT p.marketplace, p.total_harga, p.potongan_marketplace, s.kategori FROM scan_aktif s JOIN penjualan p ON s.resi=p.no_resi WHERE s.status='PACKED' AND s.tanggal=?",
                          (tgl_str,)) or []

    if packed:
        df = pd.DataFrame([dict(r) for r in packed])
        revenue = df["total_harga"].sum()
        fee = df["potongan_marketplace"].sum()
        hpp = revenue * 0.4  # estimate
        net = revenue - fee - hpp

        # OPEX hari ini
        opex_day = db.fetch_one("SELECT SUM(total_harga) as total FROM opex WHERE tanggal=? AND status_bayar='LUNAS'", (tgl_str,))
        opex_total = opex_day["total"] if opex_day else 0
        final_net = net - opex_total

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Pendapatan", f"Rp {revenue:,.0f}")
        c2.metric("Fee MP", f"Rp {fee:,.0f}")
        c3.metric("HPP (est)", f"Rp {hpp:,.0f}")
        c4.metric("OPEX", f"Rp {opex_total:,.0f}")
        c5.metric("Laba Bersih", f"Rp {final_net:,.0f}", delta=f"{'âœ…' if final_net > 0 else 'âŒ'}")

        # Per marketplace
        st.divider()
        st.caption("Per Marketplace")
        per_mp = df.groupby("marketplace").agg({"total_harga": "sum", "potongan_marketplace": "sum"}).reset_index()
        per_mp["net"] = per_mp["total_harga"] - per_mp["potongan_marketplace"]
        st.dataframe(per_mp, width="stretch", hide_index=True)
    else:
        st.info(f"ðŸ“­ Belum ada data PACKED untuk {tgl_str}")

with tab2:
    st.subheader("ðŸ’µ Cashflow 7 Hari")
    dates = [(datetime.now() - timedelta(days=i)).strftime("%d-%m-%Y") for i in range(7)]
    data = []
    for d in dates:
        rev = db.fetch_one("SELECT SUM(p.total_harga) as total FROM scan_aktif s JOIN penjualan p ON s.resi=p.no_resi WHERE s.status='PACKED' AND s.tanggal=?", (d,))
        opex = db.fetch_one("SELECT SUM(total_harga) as total FROM opex WHERE tanggal=? AND status_bayar='LUNAS'", (d,))
        data.append({"Tanggal": d, "Pendapatan": rev["total"] or 0 if rev else 0, "OPEX": opex["total"] or 0 if opex else 0})

    df_cf = pd.DataFrame(data)
    df_cf["Net"] = df_cf["Pendapatan"] - df_cf["OPEX"]
    st.dataframe(df_cf, width="stretch", hide_index=True)
    st.bar_chart(df_cf.set_index("Tanggal")[["Pendapatan", "OPEX"]])
