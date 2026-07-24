from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from database.supabase_client import supabase
from utils.common import (
    CATEGORIES,
    UNITS,
    prepare_dataframe,
    recalculate,
    rupiah,
)


# =========================================================
# KONFIGURASI HALAMAN
# =========================================================

st.set_page_config(
    page_title="Matching",
    page_icon="🧠",
    layout="wide",
)




# =========================================================
# FUNGSI BANTUAN
# =========================================================

def safe_float(value: Any, default: float = 0.0) -> float:
    """Mengubah nilai menjadi float dengan aman."""

    if value is None:
        return default

    try:
        if pd.isna(value):
            return default
    except Exception:
        pass

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_current_invoice_id() -> str | None:
    """
    Mengambil ID invoice yang sebelumnya dibuat
    di halaman Input Nota.
    """

    possible_keys = [
        "current_invoice_id",
        "invoice_id",
        "saved_invoice_id",
    ]

    for key in possible_keys:
        value = st.session_state.get(key)

        if value:
            return str(value)

    return None


def update_invoice_budget(
    invoice_id: str,
    target_budget: float,
    final_total: float,
) -> None:
    """
    Menyimpan target pagu dan total terbaru
    ke invoice yang sama di Supabase.
    """

    response = (
        supabase.table("invoices")
        .update(
            {
                "target_budget": float(target_budget),
                "final_total": float(final_total),
                "status": "processed",
            }
        )
        .eq("id", invoice_id)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "Invoice tidak berhasil diperbarui di Supabase."
        )


# =========================================================
# SESSION STATE
# =========================================================

if "invoice_items" not in st.session_state:
    st.session_state.invoice_items = []

if "target_budget" not in st.session_state:
    st.session_state.target_budget = 0.0


# =========================================================
# TAMPILAN UTAMA
# =========================================================

st.title("🧠 Matching dan Kategorisasi")

st.caption(
    "Periksa uraian, kategori, kuantitas, dan harga "
    "sebelum masuk ke tahap revisi."
)

st.divider()


# =========================================================
# VALIDASI DATA INPUT
# =========================================================

if not st.session_state.invoice_items:
    st.warning(
        "Belum ada data nota. "
        "Buka halaman Input Nota terlebih dahulu."
    )
    st.stop()


# =========================================================
# TABEL MATCHING
# =========================================================

items = prepare_dataframe(
    st.session_state.invoice_items
)

# Pastikan hanya kategori INVOXA yang digunakan.
items.loc[
    ~items["Kategori"].isin(CATEGORIES),
    "Kategori",
] = "Belum Dikategorikan"

edited = st.data_editor(
    items,
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
    key="matching_editor",
    column_config={
        "Uraian": st.column_config.TextColumn(
            "Uraian Barang",
            required=True,
            width="large",
        ),
        "Kuantitas": st.column_config.NumberColumn(
            "Kuantitas",
            min_value=0.01,
            step=1.0,
            format="%.2f",
        ),
        "Satuan": st.column_config.SelectboxColumn(
            "Satuan",
            options=UNITS,
            required=True,
        ),
        "Harga": st.column_config.NumberColumn(
            "Harga Satuan",
            min_value=0.0,
            step=1000.0,
            format="Rp %.0f",
        ),
        "Jumlah": st.column_config.NumberColumn(
            "Jumlah",
            disabled=True,
            format="Rp %.0f",
        ),
        "Kategori": st.column_config.SelectboxColumn(
            "Kategori",
            options=CATEGORIES,
            required=True,
        ),
        "Nama Nota": st.column_config.TextColumn(
            "Nama Nota",
        ),
        "Kunci": st.column_config.CheckboxColumn(
            "Kunci",
        ),
    },
)

edited = recalculate(edited)

valid = edited[
    edited["Uraian"]
    .fillna("")
    .astype(str)
    .str.strip()
    .ne("")
].copy()


# =========================================================
# RINGKASAN ANGGARAN
# =========================================================

st.divider()
st.subheader("Ringkasan Anggaran")

grand_total = float(
    valid["Jumlah"]
    .apply(safe_float)
    .sum()
)

target_budget = st.number_input(
    "Target anggaran keseluruhan",
    min_value=0.0,
    value=float(
        st.session_state.get(
            "target_budget",
            0.0,
        )
        or 0.0
    ),
    step=100_000.0,
    help=(
        "Target ini akan disimpan ke database dan digunakan "
        "oleh sistem rekomendasi pada halaman Revision."
    ),
)

st.session_state.target_budget = float(target_budget)

difference = float(target_budget) - grand_total

metric_col_1, metric_col_2, metric_col_3 = st.columns(3)

with metric_col_1:
    st.metric(
        "Total Barang",
        rupiah(grand_total),
    )

with metric_col_2:
    st.metric(
        "Target Anggaran",
        rupiah(target_budget),
    )

with metric_col_3:
    st.metric(
        "Selisih",
        rupiah(difference),
    )

if target_budget > 0:
    if difference < 0:
        st.error(
            "Total melebihi target sebesar "
            f"{rupiah(abs(difference))}."
        )

    elif difference > 0:
        st.warning(
            "Masih ada selisih sebesar "
            f"{rupiah(difference)}."
        )

    else:
        st.success(
            "Total sudah sama dengan target anggaran."
        )
else:
    st.info(
        "Isi target anggaran agar sistem Recommendation "
        "dapat menghitung sisa pagu."
    )


# =========================================================
# RINGKASAN KATEGORI
# =========================================================

st.divider()
st.subheader("Ringkasan Kategori")

if valid.empty:
    summary = pd.DataFrame(
        columns=[
            "Kategori",
            "Jumlah_Uraian",
            "Total",
        ]
    )
else:
    summary = (
        valid.groupby(
            "Kategori",
            dropna=False,
        )
        .agg(
            Jumlah_Uraian=(
                "Uraian",
                "count",
            ),
            Total=(
                "Jumlah",
                "sum",
            ),
        )
        .reset_index()
    )

st.dataframe(
    summary,
    hide_index=True,
    use_container_width=True,
    column_config={
        "Kategori": st.column_config.TextColumn(
            "Kategori",
        ),
        "Jumlah_Uraian": st.column_config.NumberColumn(
            "Jumlah Uraian",
            format="%d",
        ),
        "Total": st.column_config.NumberColumn(
            "Total",
            format="Rp %.0f",
        ),
    },
)

uncategorized = int(
    (
        valid["Kategori"]
        == "Belum Dikategorikan"
    ).sum()
)

if uncategorized:
    st.warning(
        f"Masih ada {uncategorized} uraian "
        "yang belum dikategorikan."
    )


# =========================================================
# VALIDASI
# =========================================================

validation_errors: list[str] = []

if valid.empty:
    validation_errors.append(
        "Tidak ada data yang dapat disimpan."
    )

invalid_quantity = valid[
    valid["Kuantitas"].apply(safe_float) <= 0
]

if not invalid_quantity.empty:
    validation_errors.append(
        "Masih ada kuantitas nol atau negatif."
    )

invalid_price = valid[
    valid["Harga"].apply(safe_float) <= 0
]

if not invalid_price.empty:
    validation_errors.append(
        "Masih ada harga satuan nol."
    )

invalid_total = valid[
    valid["Jumlah"].apply(safe_float) <= 0
]

if not invalid_total.empty:
    validation_errors.append(
        "Masih ada jumlah harga nol."
    )

if target_budget <= 0:
    validation_errors.append(
        "Target anggaran belum diisi."
    )

if uncategorized > 0:
    validation_errors.append(
        "Masih ada uraian yang belum dikategorikan."
    )

for error_message in validation_errors:
    st.warning(error_message)


# =========================================================
# SIMPAN MATCHING
# =========================================================

st.divider()

save_button = st.button(
    "💾 Simpan Hasil Matching dan Lanjutkan",
    type="primary",
    use_container_width=True,
    disabled=bool(validation_errors),
)

if save_button:
    invoice_id = get_current_invoice_id()

    if not invoice_id:
        st.error(
            "ID invoice tidak ditemukan. "
            "Kembali ke halaman Input Nota, lalu simpan ulang datanya."
        )

    else:
        try:
            final_items = prepare_dataframe(valid)

            # Simpan hasil Matching untuk halaman berikutnya.
            st.session_state.invoice_items = (
                final_items.to_dict("records")
            )

            st.session_state.matched_items = (
                st.session_state.invoice_items
            )

            st.session_state.final_items = (
                st.session_state.invoice_items
            )

            st.session_state.target_budget = float(
                target_budget
            )

            st.session_state.current_invoice_id = (
                invoice_id
            )

            # Simpan target pagu dan total terbaru ke Supabase.
            update_invoice_budget(
                invoice_id=invoice_id,
                target_budget=float(target_budget),
                final_total=grand_total,
            )

            st.success(
                "Matching dan target anggaran berhasil "
                "disimpan ke Supabase."
            )

            try:
                st.switch_page(
                    "pages/3_📊_Revision.py"
                )
            except Exception:
                st.info(
                    "Data sudah tersimpan. "
                    "Buka halaman Revision melalui menu kiri."
                )

        except Exception as error:
            st.error(
                f"Hasil Matching gagal disimpan: {error}"
            )