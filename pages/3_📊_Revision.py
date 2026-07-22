from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from utils.common import CATEGORIES, UNITS, prepare_dataframe, recalculate, rupiah


st.set_page_config(page_title="Revision", page_icon="📊", layout="wide")


# =========================================================
# HELPER
# =========================================================

def round_to_step(value: float, step: int) -> float:
    if step <= 0:
        return round(float(value))
    return round(float(value) / step) * step


def recommended_target(
    original_total: float,
    percentage: float,
    rounding: int = 1000,
) -> float:
    """Membuat target otomatis berdasarkan persentase kenaikan."""
    if original_total <= 0:
        return 0.0

    raw_target = original_total * (1.0 + percentage / 100.0)
    return float(round_to_step(raw_target, rounding))


def optimize_to_target_band(
    result: pd.DataFrame,
    target: float,
    adjustment_method: str,
    rounding_step: int,
    unlocked_indices: list[int],
    tolerance: float = 10000.0,
) -> pd.DataFrame:
    """
    Cari hasil sedekat mungkin dengan target.

    Hasil dianggap valid bila berada dalam rentang:
    target - tolerance sampai target + tolerance.

    Untuk metode yang mengizinkan perubahan harga, program melakukan
    koreksi akhir pada satu item agar selisih maksimum Rp10.000.
    """
    result = result.copy()

    result["Jumlah Usulan"] = (
        result["Kuantitas Usulan"] * result["Harga Usulan"]
    )

    if not unlocked_indices:
        return result

    # Koreksi bertahap menggunakan langkah harga atau 1 unit kuantitas.
    for _ in range(100000):
        current_total = float(result["Jumlah Usulan"].sum())
        current_gap = abs(target - current_total)

        if current_gap <= tolerance:
            break

        best_move = None
        best_gap = current_gap

        for idx in unlocked_indices:
            qty = float(result.at[idx, "Kuantitas Usulan"])
            price = float(result.at[idx, "Harga Usulan"])

            if qty <= 0 or price < 0:
                continue

            # Coba naik/turun harga satu langkah.
            if adjustment_method in ["Harga saja", "Harga dan kuantitas"]:
                for direction in (-1, 1):
                    candidate_price = price + direction * rounding_step

                    if candidate_price < 0:
                        continue

                    candidate_total = (
                        current_total
                        + qty * (candidate_price - price)
                    )
                    candidate_gap = abs(target - candidate_total)

                    if candidate_gap < best_gap:
                        best_gap = candidate_gap
                        best_move = (
                            "price",
                            idx,
                            candidate_price,
                        )

            # Coba naik/turun kuantitas satu unit.
            if adjustment_method in ["Kuantitas saja", "Harga dan kuantitas"]:
                for direction in (-1, 1):
                    candidate_qty = qty + direction

                    if candidate_qty < 0:
                        continue

                    candidate_total = (
                        current_total
                        + price * (candidate_qty - qty)
                    )
                    candidate_gap = abs(target - candidate_total)

                    if candidate_gap < best_gap:
                        best_gap = candidate_gap
                        best_move = (
                            "qty",
                            idx,
                            candidate_qty,
                        )

        if best_move is None:
            break

        move_type, idx, new_value = best_move

        if move_type == "price":
            result.at[idx, "Harga Usulan"] = new_value
        else:
            result.at[idx, "Kuantitas Usulan"] = new_value

        result.at[idx, "Jumlah Usulan"] = (
            float(result.at[idx, "Kuantitas Usulan"])
            * float(result.at[idx, "Harga Usulan"])
        )

    # Koreksi akhir yang lebih presisi untuk metode yang mengizinkan harga.
    # Harga tetap dibulatkan ke kelipatan rounding_step.
    if adjustment_method in ["Harga saja", "Harga dan kuantitas"]:
        current_total = float(result["Jumlah Usulan"].sum())
        current_gap = abs(target - current_total)

        if current_gap > tolerance:
            best_choice = None
            best_gap = current_gap

            for idx in unlocked_indices:
                qty = float(result.at[idx, "Kuantitas Usulan"])

                if qty <= 0:
                    continue

                current_price = float(result.at[idx, "Harga Usulan"])
                other_total = current_total - (qty * current_price)

                ideal_price = (target - other_total) / qty

                candidates = {
                    max(0.0, round_to_step(ideal_price, rounding_step)),
                    max(
                        0.0,
                        round_to_step(
                            ideal_price - rounding_step,
                            rounding_step,
                        ),
                    ),
                    max(
                        0.0,
                        round_to_step(
                            ideal_price + rounding_step,
                            rounding_step,
                        ),
                    ),
                }

                for candidate_price in candidates:
                    candidate_total = (
                        other_total + qty * candidate_price
                    )
                    candidate_gap = abs(target - candidate_total)

                    if candidate_gap < best_gap:
                        best_gap = candidate_gap
                        best_choice = (
                            idx,
                            candidate_price,
                        )

            if best_choice is not None:
                idx, candidate_price = best_choice
                result.at[idx, "Harga Usulan"] = candidate_price
                result.at[idx, "Jumlah Usulan"] = (
                    float(result.at[idx, "Kuantitas Usulan"])
                    * candidate_price
                )

    return result


def _prepare_simulation_dataframe(source: pd.DataFrame) -> pd.DataFrame:
    result = prepare_dataframe(source).copy().reset_index(drop=True)

    result["Kuantitas"] = pd.to_numeric(
        result["Kuantitas"], errors="coerce"
    ).fillna(0.0)

    result["Harga"] = pd.to_numeric(
        result["Harga"], errors="coerce"
    ).fillna(0.0)

    result["Kunci"] = result["Kunci"].fillna(False).astype(bool)

    result["Kuantitas Asli"] = result["Kuantitas"].astype(float)
    result["Harga Asli"] = result["Harga"].astype(float)

    result["Kuantitas Usulan"] = result["Kuantitas Asli"].copy()
    result["Harga Usulan"] = result["Harga Asli"].copy()

    result["Jumlah Asli"] = (
        result["Kuantitas Asli"] * result["Harga Asli"]
    )

    return result


def create_budget_simulation(
    source: pd.DataFrame,
    target: float,
    adjustment_method: str,
    max_percent: float,
    rounding_step: int,
    tolerance: float,
) -> dict:
    """
    Membuat simulasi yang HARUS tepat ke total pagu target.

    Prinsip:
    - Seluruh item tidak terkunci disesuaikan secara proporsional.
    - Kuantitas/harga awal tidak langsung diubah.
    - Satu item dipakai sebagai item penyeimbang terakhir agar total
      persis sama dengan target.
    - Data baru diterapkan setelah tombol Terapkan ditekan.
    """
    result = _prepare_simulation_dataframe(source)

    target = float(round(target))
    rounding_step = max(int(rounding_step), 1)

    original_total = float(result["Jumlah Asli"].sum())

    unlocked_mask = (
        (~result["Kunci"])
        & (result["Kuantitas Asli"] > 0)
        & (result["Harga Asli"] > 0)
    )

    unlocked_indices = list(result.index[unlocked_mask])

    if original_total <= 0 or not unlocked_indices:
        result["Jumlah Usulan"] = result["Jumlah Asli"]
        result["Persentase Harga"] = 0.0
        result["Persentase Kuantitas"] = 0.0

        return {
            "dataframe": result,
            "original_total": original_total,
            "revised_total": original_total,
            "target": target,
            "difference": abs(target - original_total),
            "reached": False,
            "message": "Tidak ada item yang dapat disesuaikan.",
            "required_percent": 0.0,
        }

    locked_total = float(
        result.loc[~unlocked_mask, "Jumlah Asli"].sum()
    )

    unlocked_original_total = float(
        result.loc[unlocked_mask, "Jumlah Asli"].sum()
    )

    target_for_unlocked = target - locked_total

    if target_for_unlocked <= 0:
        result["Jumlah Usulan"] = result["Jumlah Asli"]
        result["Persentase Harga"] = 0.0
        result["Persentase Kuantitas"] = 0.0

        return {
            "dataframe": result,
            "original_total": original_total,
            "revised_total": original_total,
            "target": target,
            "difference": abs(target - original_total),
            "reached": False,
            "message": (
                "Total item terkunci sudah sama dengan atau melebihi pagu target. "
                "Buka kunci sebagian item agar program dapat menyesuaikan."
            ),
            "required_percent": 0.0,
        }

    factor = target_for_unlocked / unlocked_original_total
    required_percent = (factor - 1.0) * 100.0

    # -----------------------------------------------------
    # TAHAP 1: penyesuaian proporsional seluruh item
    # -----------------------------------------------------
    for idx in unlocked_indices:
        original_qty = float(result.at[idx, "Kuantitas Asli"])
        original_price = float(result.at[idx, "Harga Asli"])

        if adjustment_method == "Harga saja":
            proposed_qty = original_qty
            proposed_price = round_to_step(
                original_price * factor,
                rounding_step,
            )

        elif adjustment_method == "Kuantitas saja":
            proposed_qty = max(
                1.0,
                float(round(original_qty * factor)),
            )
            proposed_price = original_price

        else:
            split_factor = factor ** 0.5

            proposed_qty = max(
                1.0,
                float(round(original_qty * split_factor)),
            )

            proposed_price = round_to_step(
                original_price * split_factor,
                rounding_step,
            )

        if proposed_price <= 0:
            proposed_price = rounding_step

        result.at[idx, "Kuantitas Usulan"] = proposed_qty
        result.at[idx, "Harga Usulan"] = proposed_price

    result["Jumlah Usulan"] = (
        result["Kuantitas Usulan"]
        * result["Harga Usulan"]
    )

    # -----------------------------------------------------
    # TAHAP 2: pilih satu item penyeimbang agar total PERSIS
    # -----------------------------------------------------
    best_solution = None

    for idx in unlocked_indices:
        current_qty = int(
            max(
                1,
                round(float(result.at[idx, "Kuantitas Usulan"])),
            )
        )

        original_qty = max(
            1,
            int(round(float(result.at[idx, "Kuantitas Asli"]))),
        )

        original_price = max(
            1.0,
            float(result.at[idx, "Harga Asli"]),
        )

        other_total = float(
            result["Jumlah Usulan"].sum()
            - result.at[idx, "Jumlah Usulan"]
        )

        remainder = int(round(target - other_total))

        if remainder <= 0:
            continue

        qty_candidates = {1, current_qty, original_qty}

        # Cari kuantitas sekitar kuantitas asli/usulan yang memungkinkan
        # harga bulat rupiah dan total tepat ke pagu.
        max_search = max(
            200,
            current_qty + 100,
            original_qty + 100,
        )

        for qty in range(1, max_search + 1):
            qty_candidates.add(qty)

        for qty in qty_candidates:
            if qty <= 0:
                continue

            if remainder % qty != 0:
                continue

            price = remainder // qty

            if price <= 0:
                continue

            # Nilai skor digunakan agar perubahan item penyeimbang
            # tetap sedekat mungkin dengan data awal.
            qty_change = abs(qty - original_qty) / max(original_qty, 1)
            price_change = abs(price - original_price) / max(original_price, 1)
            score = qty_change + price_change

            if adjustment_method == "Harga saja" and qty != original_qty:
                continue

            if adjustment_method == "Kuantitas saja" and price != int(round(original_price)):
                continue

            candidate = {
                "idx": idx,
                "qty": float(qty),
                "price": float(price),
                "score": score,
            }

            if best_solution is None or score < best_solution["score"]:
                best_solution = candidate

    # Untuk menjamin tepat ke target, mode Harga dan kuantitas
    # boleh memakai qty 1 pada satu item penyeimbang.
    if best_solution is None and adjustment_method == "Harga dan kuantitas":
        for idx in unlocked_indices:
            other_total = float(
                result["Jumlah Usulan"].sum()
                - result.at[idx, "Jumlah Usulan"]
            )

            remainder = int(round(target - other_total))

            if remainder > 0:
                best_solution = {
                    "idx": idx,
                    "qty": 1.0,
                    "price": float(remainder),
                    "score": float("inf"),
                }
                break

    if best_solution is not None:
        idx = best_solution["idx"]

        result.at[idx, "Kuantitas Usulan"] = best_solution["qty"]
        result.at[idx, "Harga Usulan"] = best_solution["price"]
        result.at[idx, "Jumlah Usulan"] = (
            best_solution["qty"]
            * best_solution["price"]
        )

    result["Jumlah Usulan"] = (
        result["Kuantitas Usulan"]
        * result["Harga Usulan"]
    )

    result["Persentase Harga"] = 0.0
    harga_nonzero = result["Harga Asli"] > 0

    result.loc[
        harga_nonzero,
        "Persentase Harga",
    ] = (
        (
            result.loc[harga_nonzero, "Harga Usulan"]
            / result.loc[harga_nonzero, "Harga Asli"]
        )
        - 1.0
    ) * 100.0

    result["Persentase Kuantitas"] = 0.0
    qty_nonzero = result["Kuantitas Asli"] > 0

    result.loc[
        qty_nonzero,
        "Persentase Kuantitas",
    ] = (
        (
            result.loc[qty_nonzero, "Kuantitas Usulan"]
            / result.loc[qty_nonzero, "Kuantitas Asli"]
        )
        - 1.0
    ) * 100.0

    revised_total = float(result["Jumlah Usulan"].sum())
    difference = abs(target - revised_total)
    reached = difference == 0

    if reached:
        message = (
            "Simulasi berhasil tepat sama dengan total pagu target. "
            "Data asli belum berubah sampai hasil diterapkan."
        )
    else:
        message = (
            "Program belum dapat mencapai total pagu secara tepat dengan metode "
            "yang dipilih. Gunakan metode 'Harga dan kuantitas' agar program "
            "dapat membuat item penyeimbang."
        )

    return {
        "dataframe": result,
        "original_total": original_total,
        "revised_total": revised_total,
        "target": target,
        "difference": difference,
        "reached": reached,
        "message": message,
        "required_percent": required_percent,
    }


# =========================================================
# SESSION STATE
# =========================================================

if "invoice_items" not in st.session_state:
    st.session_state.invoice_items = []

if "budget_simulation" not in st.session_state:
    st.session_state.budget_simulation = None

if "global_budget_simulation" not in st.session_state:
    st.session_state.global_budget_simulation = None


# =========================================================
# JUDUL DAN VALIDASI
# =========================================================

st.title("📊 Revision — Budget Adjustment")

st.caption(
    "Pilih simulasi otomatis seluruh kategori atau revisi manual per kategori. "
    "Data asli tidak berubah sebelum hasil diterapkan."
)

st.divider()

if not st.session_state.invoice_items:
    st.warning("Belum ada data. Mulai dari halaman Input Nota.")
    st.stop()

all_items = prepare_dataframe(st.session_state.invoice_items)
grand_total = float(all_items["Jumlah"].sum())

backup_csv = all_items.to_csv(index=False).encode("utf-8-sig")

st.download_button(
    "⬇️ Download Backup Data Sebelum Revisi",
    data=backup_csv,
    file_name="backup_invoice_sebelum_revisi.csv",
    mime="text/csv",
    use_container_width=True,
)


# =========================================================
# PILIH MODE UTAMA — DITAMPILKAN PALING ATAS
# =========================================================

st.divider()
st.subheader("Pilih Cara Revisi")

revision_mode = st.radio(
    "Mau melakukan revisi bagaimana?",
    [
        "🚀 Otomatis — Simulasikan Semua Kategori",
        "✏️ Manual — Revisi Per Kategori",
    ],
    horizontal=True,
    index=0,
)

TOLERANCE = 10_000.0


# =========================================================
# MODE OTOMATIS SELURUH KATEGORI
# =========================================================

if revision_mode == "🚀 Otomatis — Simulasikan Semua Kategori":
    st.info(
        "Program akan menyesuaikan seluruh kategori sekaligus agar total akhir "
        "mendekati total pagu. Selisih maksimal yang diizinkan adalah Rp10.000."
    )

    st.subheader("1. Tentukan Total Pagu Keseluruhan")

    target_mode = st.radio(
        "Cara menentukan total pagu",
        [
            "Isi pagu manual",
            "Rekomendasi otomatis",
        ],
        horizontal=True,
        key="global_target_mode",
    )

    if target_mode == "Isi pagu manual":
        total_target = st.number_input(
            "Masukkan total pagu seluruh kategori",
            min_value=0.0,
            value=float(
                st.session_state.get(
                    "target_budget",
                    grand_total,
                )
                or grand_total
            ),
            step=100_000.0,
            key="global_total_target",
        )
    else:
        safe_target = recommended_target(grand_total, 10.0)
        ideal_target = recommended_target(grand_total, 20.0)
        maximum_target = recommended_target(grand_total, 30.0)

        recommendation = st.radio(
            "Pilih rekomendasi program",
            [
                "Aman · Naik 10%",
                "Ideal · Naik 20%",
                "Maksimal · Naik 30%",
            ],
            horizontal=True,
            index=1,
            key="global_recommendation",
        )

        if recommendation.startswith("Aman"):
            total_target = safe_target
        elif recommendation.startswith("Ideal"):
            total_target = ideal_target
        else:
            total_target = maximum_target

        r1, r2, r3 = st.columns(3)
        r1.metric("Aman · 10%", rupiah(safe_target))
        r2.metric("Ideal · 20%", rupiah(ideal_target))
        r3.metric("Maksimal · 30%", rupiah(maximum_target))

    st.subheader("2. Pengaturan Simulasi")

    c1, c2 = st.columns(2)

    with c1:
        adjustment_method = st.radio(
            "Yang boleh diubah oleh program",
            [
                "Harga saja",
                "Kuantitas saja",
                "Harga dan kuantitas",
            ],
            index=2,
            key="global_adjustment_method",
        )

    with c2:
        rounding_step = st.selectbox(
            "Pembulatan harga",
            [100, 500, 1000, 5000],
            index=1,
            disabled=adjustment_method == "Kuantitas saja",
            key="global_rounding_step",
        )


    if adjustment_method != "Harga dan kuantitas":
        st.warning(
            "Untuk menjamin total tepat sama dengan pagu, gunakan metode "
            "'Harga dan kuantitas'. Metode lain mungkin tidak memiliki kombinasi yang tepat."
        )
    else:
        st.info(
            "Program akan menyesuaikan semua item, lalu memakai satu item sebagai "
            "penyeimbang akhir agar total tepat sama dengan pagu."
        )

    max_percent = 500.0

    g1, g2, g3 = st.columns(3)
    g1.metric("Total Saat Ini", rupiah(grand_total))
    g2.metric("Total Pagu Target", rupiah(total_target))
    g3.metric(
        "Nominal yang Harus Disesuaikan",
        rupiah(abs(float(total_target) - grand_total)),
    )

    st.caption(
        "Tolak ukur simulasi adalah total pagu target, bukan persentase. "
        "Hasil hanya dapat diterapkan jika Total Usulan tepat sama dengan Total Pagu."
    )

    if st.button(
        "📊 Simulasikan Semua Kategori Sekaligus",
        type="primary",
        use_container_width=True,
        key="run_global_simulation",
    ):
        result = create_budget_simulation(
            source=all_items,
            target=float(total_target),
            adjustment_method=adjustment_method,
            max_percent=float(max_percent),
            rounding_step=int(rounding_step),
            tolerance=TOLERANCE,
        )

        st.session_state.global_budget_simulation = {
            "data": result["dataframe"].to_dict("records"),
            "original_total": result["original_total"],
            "revised_total": result["revised_total"],
            "target": result["target"],
            "difference": result["difference"],
            "reached": result["reached"],
            "message": result["message"],
            "required_percent": result["required_percent"],
            "adjustment_method": adjustment_method,
            "rounding_step": int(rounding_step),
        }

        st.rerun()

    simulation = st.session_state.get("global_budget_simulation")

    if simulation:
        st.divider()
        st.subheader("3. Hasil Simulasi Semua Kategori")

        simulation_df = pd.DataFrame(simulation["data"])

        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Total Asli", rupiah(simulation["original_total"]))
        s2.metric("Total Pagu", rupiah(simulation["target"]))
        s3.metric("Total Usulan", rupiah(simulation["revised_total"]))
        s4.metric("Selisih", rupiah(simulation["difference"]))

        if simulation["difference"] == 0:
            st.success(
                "Hasil sudah tepat sama dengan total pagu target."
            )
        else:
            st.error(
                f"Selisih masih {rupiah(simulation['difference'])}. "
                "Hasil belum dapat diterapkan karena harus tepat sama dengan pagu."
            )

        category_summary = (
            simulation_df.groupby("Kategori", dropna=False)
            .agg(
                Jumlah_Uraian=("Uraian", "count"),
                Total_Asli=("Jumlah Asli", "sum"),
                Total_Usulan=("Jumlah Usulan", "sum"),
            )
            .reset_index()
        )

        category_summary["Perubahan"] = (
            category_summary["Total_Usulan"]
            - category_summary["Total_Asli"]
        )

        st.markdown("#### Ringkasan Per Kategori")

        st.dataframe(
            category_summary,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Jumlah_Uraian": "Jumlah Uraian",
                "Total_Asli": st.column_config.NumberColumn(
                    "Total Asli",
                    format="Rp %.0f",
                ),
                "Total_Usulan": st.column_config.NumberColumn(
                    "Total Usulan",
                    format="Rp %.0f",
                ),
                "Perubahan": st.column_config.NumberColumn(
                    "Perubahan",
                    format="Rp %.0f",
                ),
            },
        )

        st.markdown("#### Detail Semua Barang")

        display_columns = [
            "Kategori",
            "Nama Nota",
            "Uraian",
            "Satuan",
            "Kuantitas Asli",
            "Kuantitas Usulan",
            "Harga Asli",
            "Harga Usulan",
            "Jumlah Asli",
            "Jumlah Usulan",
            "Kunci",
        ]

        selected_result = st.data_editor(
            simulation_df[display_columns],
            hide_index=True,
            use_container_width=True,
            key="global_simulation_editor",
            column_config={
                "Kategori": st.column_config.TextColumn(disabled=True),
                "Nama Nota": st.column_config.TextColumn(disabled=True),
                "Uraian": st.column_config.TextColumn(
                    disabled=True,
                    width="large",
                ),
                "Satuan": st.column_config.TextColumn(disabled=True),
                "Kuantitas Asli": st.column_config.NumberColumn(disabled=True),
                "Kuantitas Usulan": st.column_config.NumberColumn(
                    "Kuantitas Usulan",
                    min_value=0.0,
                    step=1.0,
                    disabled=simulation["adjustment_method"] == "Harga saja",
                ),
                "Harga Asli": st.column_config.NumberColumn(
                    disabled=True,
                    format="Rp %.0f",
                ),
                "Harga Usulan": st.column_config.NumberColumn(
                    "Harga Usulan",
                    min_value=0.0,
                    step=float(simulation["rounding_step"]),
                    format="Rp %.0f",
                    disabled=simulation["adjustment_method"] == "Kuantitas saja",
                ),
                "Jumlah Asli": st.column_config.NumberColumn(
                    disabled=True,
                    format="Rp %.0f",
                ),
                "Jumlah Usulan": st.column_config.NumberColumn(
                    disabled=True,
                    format="Rp %.0f",
                ),
                "Kunci": st.column_config.CheckboxColumn(disabled=True),
            },
        )

        preview_qty = pd.to_numeric(
            selected_result["Kuantitas Usulan"],
            errors="coerce",
        ).fillna(0.0)

        preview_price = pd.to_numeric(
            selected_result["Harga Usulan"],
            errors="coerce",
        ).fillna(0.0)

        preview_total = float((preview_qty * preview_price).sum())
        preview_difference = abs(float(simulation["target"]) - preview_total)
        preview_valid = preview_difference == 0

        p1, p2 = st.columns(2)
        p1.metric("Total Setelah Koreksi", rupiah(preview_total))
        p2.metric("Selisih dari Total Pagu", rupiah(preview_difference))

        if preview_valid:
            st.success(
                "Hasil tepat sama dengan total pagu dan dapat diterapkan."
            )
        else:
            st.error(
                "Hasil belum dapat diterapkan. Total Usulan harus tepat sama "
                "dengan Total Pagu."
            )

        apply_col, clear_col = st.columns(2)

        if apply_col.button(
            "✅ Terapkan ke Semua Kategori",
            type="primary",
            use_container_width=True,
            disabled=not preview_valid,
            key="apply_global_simulation",
        ):
            updated = simulation_df.copy()

            for idx in updated.index:
                proposed_qty = float(
                    selected_result.at[idx, "Kuantitas Usulan"]
                )
                proposed_price = float(
                    selected_result.at[idx, "Harga Usulan"]
                )

                updated.at[idx, "Kuantitas"] = proposed_qty
                updated.at[idx, "Harga"] = proposed_price
                updated.at[idx, "Jumlah"] = proposed_qty * proposed_price

            keep_columns = [
                "Uraian",
                "Kuantitas",
                "Satuan",
                "Harga",
                "Jumlah",
                "Kategori",
                "Nama Nota",
                "Kunci",
            ]

            updated = prepare_dataframe(updated[keep_columns])

            final_difference = abs(
                float(simulation["target"])
                - float(updated["Jumlah"].sum())
            )

            if final_difference != 0:
                st.error(
                    "Data tidak diterapkan karena total akhir belum "
                    "tepat sama dengan total pagu."
                )
                st.stop()

            st.session_state.invoice_items = updated.to_dict("records")
            st.session_state.global_budget_simulation = None

            st.success("Hasil berhasil diterapkan ke semua kategori.")
            st.rerun()

        if clear_col.button(
            "🗑️ Hapus Simulasi",
            use_container_width=True,
            key="clear_global_simulation",
        ):
            st.session_state.global_budget_simulation = None
            st.rerun()


# =========================================================
# MODE MANUAL PER KATEGORI
# =========================================================

else:
    st.info(
        "Pilih kategori yang ingin direvisi. Simulasi dan perubahan hanya "
        "berlaku untuk kategori tersebut."
    )

    available_categories = sorted(
        all_items["Kategori"].astype(str).unique().tolist()
    )

    selected_category = st.selectbox(
        "Pilih kategori",
        available_categories,
        key="manual_selected_category",
    )

    category_items = (
        all_items[
            all_items["Kategori"] == selected_category
        ]
        .copy()
        .reset_index(drop=True)
    )

    if category_items.empty:
        st.info("Kategori ini belum memiliki barang.")
        st.stop()

    st.subheader("Revisi Data Manual")

    edited_category = st.data_editor(
        category_items,
        hide_index=True,
        num_rows="dynamic",
        use_container_width=True,
        key=f"manual_editor_{selected_category}",
        column_config={
            "Uraian": st.column_config.TextColumn(
                "Uraian Barang",
                required=True,
                width="large",
            ),
            "Kuantitas": st.column_config.NumberColumn(
                "Kuantitas",
                min_value=0.0,
                step=1.0,
            ),
            "Satuan": st.column_config.SelectboxColumn(
                "Satuan",
                options=UNITS,
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
            ),
            "Nama Nota": st.column_config.TextColumn("Nama Nota"),
            "Kunci": st.column_config.CheckboxColumn(
                "Kunci",
                help="Item ini tidak diubah oleh simulasi otomatis.",
            ),
        },
    )

    edited_category = recalculate(edited_category)

    edited_category = edited_category[
        edited_category["Uraian"]
        .fillna("")
        .astype(str)
        .str.strip()
        != ""
    ].copy()

    category_total = float(edited_category["Jumlah"].sum())

    m1, m2, m3 = st.columns(3)
    m1.metric("Jumlah Uraian", len(edited_category))
    m2.metric(f"Total {selected_category}", rupiah(category_total))
    m3.metric("Item Terkunci", int(edited_category["Kunci"].sum()))

    if st.button(
        f"💾 Simpan Revisi Manual {selected_category}",
        use_container_width=True,
        key="save_manual_revision",
    ):
        others = all_items[
            all_items["Kategori"] != selected_category
        ].copy()

        combined = prepare_dataframe(
            pd.concat(
                [others, edited_category],
                ignore_index=True,
            )
        )

        st.session_state.invoice_items = combined.to_dict("records")
        st.session_state.budget_simulation = None
        st.session_state.global_budget_simulation = None

        st.success("Revisi manual berhasil disimpan.")
        st.rerun()


# =========================================================
# RINGKASAN AKHIR
# =========================================================

st.divider()
st.subheader("Ringkasan Akhir Tersimpan")

latest = prepare_dataframe(st.session_state.invoice_items)

summary = (
    latest.groupby("Kategori", dropna=False)
    .agg(
        Jumlah_Uraian=("Uraian", "count"),
        Total=("Jumlah", "sum"),
    )
    .reset_index()
)

st.dataframe(
    summary,
    hide_index=True,
    use_container_width=True,
    column_config={
        "Jumlah_Uraian": "Jumlah Uraian",
        "Total": st.column_config.NumberColumn(
            "Total",
            format="Rp %.0f",
        ),
    },
)

st.metric(
    "Total Seluruh Kategori",
    rupiah(latest["Jumlah"].sum()),
)

st.info("Setelah selesai, buka halaman Download.")