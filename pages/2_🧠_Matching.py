from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.common import CATEGORIES, UNITS, prepare_dataframe, recalculate, rupiah


st.set_page_config(page_title="Matching", page_icon="🧠", layout="wide")

if "invoice_items" not in st.session_state:
    st.session_state.invoice_items = []

st.title("🧠 Matching dan Kategorisasi")
st.caption("Periksa uraian, kategori, kuantitas, dan harga sebelum revisi.")
st.divider()

if not st.session_state.invoice_items:
    st.warning("Belum ada data nota. Buka halaman Input Nota terlebih dahulu.")
    st.stop()

items = prepare_dataframe(st.session_state.invoice_items)

edited = st.data_editor(
    items,
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
    key="matching_editor",
    column_config={
        "Uraian": st.column_config.TextColumn("Uraian Barang", required=True, width="large"),
        "Kuantitas": st.column_config.NumberColumn("Kuantitas", min_value=0.0, step=1.0),
        "Satuan": st.column_config.SelectboxColumn("Satuan", options=UNITS),
        "Harga": st.column_config.NumberColumn("Harga Satuan", min_value=0.0, step=1000.0, format="Rp %.0f"),
        "Jumlah": st.column_config.NumberColumn("Jumlah", disabled=True, format="Rp %.0f"),
        "Kategori": st.column_config.SelectboxColumn("Kategori", options=CATEGORIES, required=True),
        "Nama Nota": st.column_config.TextColumn("Nama Nota"),
        "Kunci": st.column_config.CheckboxColumn("Kunci"),
    },
)

edited = recalculate(edited)
valid = edited[edited["Uraian"].str.strip() != ""].copy()

st.divider()
st.subheader("Ringkasan Anggaran")

grand_total = float(valid["Jumlah"].sum())
target_budget = st.number_input(
    "Target anggaran keseluruhan, opsional",
    min_value=0.0,
    value=float(st.session_state.get("target_budget", 0.0) or 0.0),
    step=100_000.0,
)
st.session_state.target_budget = float(target_budget)

difference = target_budget - grand_total

m1, m2, m3 = st.columns(3)
m1.metric("Total Barang", rupiah(grand_total))
m2.metric("Target Anggaran", rupiah(target_budget))
m3.metric("Selisih", rupiah(difference))

if target_budget > 0:
    if difference < 0:
        st.error(f"Total melebihi target sebesar {rupiah(abs(difference))}.")
    elif difference > 0:
        st.warning(f"Masih ada selisih sebesar {rupiah(difference)}.")
    else:
        st.success("Total sudah sama dengan target.")

st.subheader("Ringkasan Kategori")

summary = (
    valid.groupby("Kategori", dropna=False)
    .agg(Jumlah_Uraian=("Uraian", "count"), Total=("Jumlah", "sum"))
    .reset_index()
)

st.dataframe(
    summary,
    hide_index=True,
    use_container_width=True,
    column_config={
        "Jumlah_Uraian": "Jumlah Uraian",
        "Total": st.column_config.NumberColumn("Total", format="Rp %.0f"),
    },
)

uncategorized = int((valid["Kategori"] == "Belum Dikategorikan").sum())
if uncategorized:
    st.warning(f"Masih ada {uncategorized} uraian yang belum dikategorikan.")

if st.button("💾 Simpan Hasil Matching", type="primary", use_container_width=True):
    if valid.empty:
        st.error("Tidak ada data yang dapat disimpan.")
    else:
        st.session_state.invoice_items = valid.to_dict("records")
        st.success("Matching berhasil disimpan. Buka halaman Revision.")
