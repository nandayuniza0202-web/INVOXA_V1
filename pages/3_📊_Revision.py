from __future__ import annotations

import math
from typing import Any

import pandas as pd
import streamlit as st

from services.recommendation_service import (
    get_product_family,
    get_recommendation_quantity_limit,
    recommend_new_products,
    recommend_replacement_product,
)
from utils.common import CATEGORIES, UNITS, prepare_dataframe, recalculate, rupiah


st.set_page_config(
    page_title="Revision",
    page_icon="📊",
    layout="wide",
)


# =========================================================
# KONSTANTA
# =========================================================

DEFAULT_MAX_PRICE_INCREASE = 12.0
DEFAULT_MAX_QUANTITY_INCREASE = 50.0
DEFAULT_NEW_PRODUCT_SHARE = 55.0
DEFAULT_TOLERANCE = 10_000.0

DISPLAY_COLUMNS = [
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
    "Sumber",
    "Kunci",
]


# =========================================================
# HELPER UMUM
# =========================================================

def safe_float(value: Any, default: float = 0.0) -> float:
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


def round_to_step(value: float, step: int) -> float:
    step = max(int(step), 1)
    return float(round(float(value) / step) * step)


def get_current_invoice_id() -> str | None:
    for key in (
        "current_invoice_id",
        "invoice_id",
        "saved_invoice_id",
    ):
        value = st.session_state.get(key)

        if value:
            return str(value)

    metadata = st.session_state.get("invoice_metadata", {})

    if isinstance(metadata, dict) and metadata.get("invoice_id"):
        return str(metadata["invoice_id"])

    return None


def apply_absolute_quantity_rules(
    dataframe: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Menerapkan batas absolut untuk barang dengan aturan khusus.

    Aturan ini berlaku juga pada barang hasil impor/manual:
    - masker hijab maksimal 10;
    - masker non-hijab maksimal 10.

    Barang lain tetap mengikuti aturan sumber masing-masing.
    """

    result = dataframe.copy()
    messages: list[str] = []

    if "Uraian" not in result.columns:
        return result, messages

    quantity_column = (
        "Kuantitas Usulan"
        if "Kuantitas Usulan" in result.columns
        else "Kuantitas"
    )

    changed_items = 0

    for idx in result.index:
        description = str(result.at[idx, "Uraian"] or "")
        family = get_product_family(description)

        if family not in {"masker_hijab", "masker_non_hijab"}:
            continue

        current_quantity = safe_float(
            result.at[idx, quantity_column]
        )
        maximum_quantity = float(
            get_recommendation_quantity_limit(description)
        )

        if current_quantity <= maximum_quantity:
            continue

        result.at[idx, quantity_column] = maximum_quantity

        if "Kuantitas" in result.columns:
            result.at[idx, "Kuantitas"] = maximum_quantity

        if (
            "Jumlah Usulan" in result.columns
            and "Harga Usulan" in result.columns
        ):
            result.at[idx, "Jumlah Usulan"] = (
                maximum_quantity
                * safe_float(result.at[idx, "Harga Usulan"])
            )

        if "Jumlah" in result.columns and "Harga" in result.columns:
            result.at[idx, "Jumlah"] = (
                maximum_quantity
                * safe_float(result.at[idx, "Harga"])
            )

        changed_items += 1

    if changed_items:
        messages.append(
            f"{changed_items} item masker dibatasi maksimal 10."
        )

    return result, messages


def prepare_simulation_source(source: pd.DataFrame) -> pd.DataFrame:
    result = prepare_dataframe(source).copy().reset_index(drop=True)

    result["Kuantitas"] = pd.to_numeric(
        result["Kuantitas"],
        errors="coerce",
    ).fillna(0.0)

    result["Harga"] = pd.to_numeric(
        result["Harga"],
        errors="coerce",
    ).fillna(0.0)

    result["Kunci"] = (
        result["Kunci"]
        .fillna(False)
        .astype(bool)
    )

    result["Kuantitas Asli"] = result["Kuantitas"].astype(float)
    result["Harga Asli"] = result["Harga"].astype(float)
    result["Kuantitas Usulan"] = result["Kuantitas Asli"].copy()
    result["Harga Usulan"] = result["Harga Asli"].copy()

    result["Jumlah Asli"] = (
        result["Kuantitas Asli"]
        * result["Harga Asli"]
    )

    result["Jumlah Usulan"] = result["Jumlah Asli"].copy()
    result["Sumber"] = "Barang Asli"

    return result


def recommendation_rows(
    recommendations: list[dict[str, Any]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for item in recommendations:
        price = safe_float(
            item.get("suggested_unit_price")
            or item.get("average_price")
        )

        if price <= 0:
            continue

        quantity = max(
            1.0,
            safe_float(item.get("suggested_quantity"), 1.0),
        )

        rows.append(
            {
                "Uraian": str(
                    item.get("product_name")
                    or "Barang Database"
                ),
                "Kuantitas": quantity,
                "Satuan": str(item.get("unit") or "pcs"),
                "Harga": price,
                "Jumlah": quantity * price,
                "Kategori": str(
                    item.get("category")
                    or "Belum Dikategorikan"
                ),
                "Nama Nota": "Rekomendasi Database",
                "Kunci": False,
                "Kuantitas Asli": 0.0,
                "Harga Asli": price,
                "Kuantitas Usulan": quantity,
                "Harga Usulan": price,
                "Jumlah Asli": 0.0,
                "Jumlah Usulan": quantity * price,
                "Sumber": "Barang Baru Database",
                "Product ID": item.get("product_id"),
                "Product Family": str(
                    item.get("product_family")
                    or get_product_family(
                        item.get("product_name") or ""
                    )
                ),
                "Skor Rekomendasi": safe_float(item.get("score")),
                "Alasan": str(item.get("reason") or ""),
                "Batas Rekomendasi": int(item.get("quantity_limit") or 10),
                "Wajib APD": bool(item.get("is_mandatory")),
            }
        )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


def add_database_products(
    result: pd.DataFrame,
    recommendations: list[dict[str, Any]],
    gap: float,
    share_percent: float,
    max_new_products: int,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Prioritas pertama:
    masukkan barang lain dari database sampai porsi tertentu dari selisih.
    """

    messages: list[str] = []

    if gap <= 0 or not recommendations:
        return result, messages

    target_for_new_products = gap * max(
        0.0,
        min(float(share_percent), 100.0),
    ) / 100.0

    candidates = recommendation_rows(recommendations)

    if candidates.empty:
        return result, messages

    used_names = {
        str(value).strip().lower()
        for value in result["Uraian"].tolist()
    }

    selected_rows: list[dict[str, Any]] = []
    added_total = 0.0

    candidates = candidates.sort_values(
        by=[
            "Wajib APD",
            "Skor Rekomendasi",
            "Jumlah Usulan",
        ],
        ascending=[
            False,
            False,
            True,
        ],
    )

    for _, candidate in candidates.iterrows():
        if len(selected_rows) >= max_new_products:
            break

        name = str(candidate["Uraian"]).strip()
        normalized_name = name.lower()

        if not name or normalized_name in used_names:
            continue

        unit_price = safe_float(candidate["Harga Usulan"])

        if unit_price <= 0:
            continue

        remaining = max(target_for_new_products - added_total, 0.0)

        if remaining <= 0:
            break

        quantity_limit = max(
            int(safe_float(candidate.get("Batas Rekomendasi"), 10)),
            1,
        )

        suggested_quantity = max(
            1,
            min(
                int(math.floor(remaining / unit_price)),
                int(max(safe_float(candidate["Kuantitas Usulan"]), 1)),
                quantity_limit,
            ),
        )

        candidate = candidate.copy()
        candidate["Kuantitas"] = float(suggested_quantity)
        candidate["Kuantitas Usulan"] = float(suggested_quantity)
        candidate["Jumlah"] = (
            float(suggested_quantity)
            * unit_price
        )
        candidate["Jumlah Usulan"] = candidate["Jumlah"]

        if candidate["Jumlah Usulan"] > gap:
            continue

        selected_rows.append(candidate.to_dict())
        used_names.add(normalized_name)
        added_total += safe_float(candidate["Jumlah Usulan"])

    if selected_rows:
        result = pd.concat(
            [
                result,
                pd.DataFrame(selected_rows),
            ],
            ignore_index=True,
            sort=False,
        )

        messages.append(
            f"{len(selected_rows)} barang baru dari database "
            f"ditambahkan dengan nilai {rupiah(added_total)}."
        )

    return result, messages


def increase_quantities(
    result: pd.DataFrame,
    target: float,
    max_quantity_increase: float,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Prioritas kedua:
    naikkan kuantitas barang lama secara terbatas.
    """

    messages: list[str] = []

    current_total = float(result["Jumlah Usulan"].sum())
    gap = target - current_total

    if gap <= 0:
        return result, messages

    eligible = result[
        (~result["Kunci"])
        & (result["Harga Usulan"] > 0)
        & (result["Kuantitas Usulan"] > 0)
    ].copy()

    if eligible.empty:
        return result, messages

    eligible["Harga Prioritas"] = eligible["Harga Usulan"]
    eligible = eligible.sort_values(
        by=[
            "Sumber",
            "Harga Prioritas",
        ],
        ascending=[
            True,
            True,
        ],
    )

    total_added = 0.0
    changed_items = 0

    for idx in eligible.index:
        if gap <= 0:
            break

        current_qty = safe_float(
            result.at[idx, "Kuantitas Usulan"]
        )
        original_qty = safe_float(
            result.at[idx, "Kuantitas Asli"]
        )
        unit_price = safe_float(
            result.at[idx, "Harga Usulan"]
        )

        if current_qty <= 0 or unit_price <= 0:
            continue

        baseline_qty = max(original_qty, current_qty, 1.0)
        product_family = get_product_family(
            str(result.at[idx, "Uraian"] or "")
        )

        if product_family in {
            "masker_hijab",
            "masker_non_hijab",
        }:
            # Batas masker bersifat absolut, termasuk barang impor/manual.
            max_qty = float(
                get_recommendation_quantity_limit(
                    str(result.at[idx, "Uraian"] or "")
                )
            )

        elif str(result.at[idx, "Sumber"]) == "Barang Baru Database":
            recommendation_limit = int(
                safe_float(
                    result.at[idx, "Batas Rekomendasi"]
                    if "Batas Rekomendasi" in result.columns
                    else 10,
                    10,
                )
            )
            max_qty = max(current_qty, recommendation_limit)

        else:
            max_qty = max(
                current_qty,
                math.floor(
                    baseline_qty
                    * (
                        1.0
                        + max_quantity_increase / 100.0
                    )
                ),
            )

        possible_addition = int(
            max_qty - current_qty
        )

        affordable_addition = int(
            gap // unit_price
        )

        addition = min(
            possible_addition,
            affordable_addition,
        )

        if addition <= 0:
            continue

        new_qty = current_qty + addition
        result.at[idx, "Kuantitas Usulan"] = new_qty
        result.at[idx, "Jumlah Usulan"] = (
            new_qty * unit_price
        )

        nominal = addition * unit_price
        total_added += nominal
        gap -= nominal
        changed_items += 1

    if changed_items:
        messages.append(
            f"Kuantitas {changed_items} barang dinaikkan "
            f"dengan tambahan {rupiah(total_added)}."
        )

    return result, messages


def increase_prices(
    result: pd.DataFrame,
    target: float,
    max_price_increase: float,
    rounding_step: int,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Prioritas ketiga:
    naikkan harga secara terbatas, bukan proporsional tanpa batas.
    """

    messages: list[str] = []

    current_total = float(result["Jumlah Usulan"].sum())
    gap = target - current_total

    if gap <= 0:
        return result, messages

    eligible = result[
        (~result["Kunci"])
        & (result["Harga Usulan"] > 0)
        & (result["Kuantitas Usulan"] > 0)
    ].copy()

    if eligible.empty:
        return result, messages

    eligible["Potensi Maksimal"] = (
        eligible["Kuantitas Usulan"]
        * eligible["Harga Usulan"]
        * max_price_increase
        / 100.0
    )

    eligible = eligible.sort_values(
        by="Potensi Maksimal",
        ascending=False,
    )

    total_added = 0.0
    changed_items = 0

    for idx in eligible.index:
        if gap <= 0:
            break

        qty = safe_float(
            result.at[idx, "Kuantitas Usulan"]
        )
        original_price = safe_float(
            result.at[idx, "Harga Asli"]
        )
        current_price = safe_float(
            result.at[idx, "Harga Usulan"]
        )

        if qty <= 0 or current_price <= 0:
            continue

        reference_price = max(
            original_price,
            current_price,
        )

        max_allowed_price = round_to_step(
            reference_price
            * (
                1.0
                + max_price_increase / 100.0
            ),
            rounding_step,
        )

        max_allowed_price = max(
            max_allowed_price,
            current_price,
        )

        ideal_increment = gap / qty

        candidate_price = round_to_step(
            min(
                current_price + ideal_increment,
                max_allowed_price,
            ),
            rounding_step,
        )

        candidate_price = max(
            current_price,
            min(candidate_price, max_allowed_price),
        )

        nominal = (
            candidate_price - current_price
        ) * qty

        if nominal <= 0:
            continue

        result.at[idx, "Harga Usulan"] = candidate_price
        result.at[idx, "Jumlah Usulan"] = (
            qty * candidate_price
        )

        total_added += nominal
        gap -= nominal
        changed_items += 1

    if changed_items:
        messages.append(
            f"Harga {changed_items} barang dinaikkan secara terbatas "
            f"dengan tambahan {rupiah(total_added)}."
        )

    return result, messages


def precise_balance(
    result: pd.DataFrame,
    target: float,
    max_price_increase: float,
    max_quantity_increase: float,
    rounding_step: int,
    tolerance: float,
) -> tuple[pd.DataFrame, str]:
    """
    Koreksi akhir tanpa melampaui batas harga/kuantitas.

    Program mencoba:
    1. Tambah satuan barang yang harganya paling dekat dengan sisa.
    2. Koreksi harga terbatas pada satu item.
    """

    current_total = float(result["Jumlah Usulan"].sum())
    gap = target - current_total

    if abs(gap) <= tolerance:
        return result, (
            "Sisa sudah berada dalam batas toleransi."
        )

    if gap <= 0:
        return result, (
            "Total sudah mencapai atau melebihi target."
        )

    best_move: dict[str, Any] | None = None
    best_gap = abs(gap)

    for idx in result.index:
        if bool(result.at[idx, "Kunci"]):
            continue

        qty = safe_float(
            result.at[idx, "Kuantitas Usulan"]
        )
        price = safe_float(
            result.at[idx, "Harga Usulan"]
        )
        original_qty = safe_float(
            result.at[idx, "Kuantitas Asli"]
        )
        original_price = safe_float(
            result.at[idx, "Harga Asli"]
        )

        if qty <= 0 or price <= 0:
            continue

        # Kandidat penambahan kuantitas.
        baseline_qty = max(
            original_qty,
            qty,
            1.0,
        )

        product_family = get_product_family(
            str(result.at[idx, "Uraian"] or "")
        )

        if product_family in {
            "masker_hijab",
            "masker_non_hijab",
        }:
            max_qty = int(
                get_recommendation_quantity_limit(
                    str(result.at[idx, "Uraian"] or "")
                )
            )

        elif str(result.at[idx, "Sumber"]) == "Barang Baru Database":
            max_qty = int(
                safe_float(
                    result.at[idx, "Batas Rekomendasi"]
                    if "Batas Rekomendasi" in result.columns
                    else 10,
                    10,
                )
            )

        else:
            max_qty = math.floor(
                baseline_qty
                * (
                    1.0
                    + max_quantity_increase / 100.0
                )
            )

        if qty + 1 <= max_qty:
            candidate_total = current_total + price
            candidate_gap = abs(target - candidate_total)

            if candidate_gap < best_gap:
                best_gap = candidate_gap
                best_move = {
                    "type": "quantity",
                    "idx": idx,
                    "value": qty + 1,
                }

        # Kandidat koreksi harga.
        reference_price = max(
            original_price,
            price,
        )

        max_price = round_to_step(
            reference_price
            * (
                1.0
                + max_price_increase / 100.0
            ),
            rounding_step,
        )

        ideal_price = (
            price + gap / qty
        )

        for candidate_price in {
            round_to_step(
                ideal_price,
                rounding_step,
            ),
            round_to_step(
                ideal_price - rounding_step,
                rounding_step,
            ),
            round_to_step(
                ideal_price + rounding_step,
                rounding_step,
            ),
        }:
            if (
                candidate_price < price
                or candidate_price > max_price
            ):
                continue

            candidate_total = (
                current_total
                + qty
                * (
                    candidate_price - price
                )
            )

            candidate_gap = abs(
                target - candidate_total
            )

            if candidate_gap < best_gap:
                best_gap = candidate_gap
                best_move = {
                    "type": "price",
                    "idx": idx,
                    "value": candidate_price,
                }

    if best_move:
        idx = best_move["idx"]

        if best_move["type"] == "quantity":
            result.at[idx, "Kuantitas Usulan"] = (
                best_move["value"]
            )
        else:
            result.at[idx, "Harga Usulan"] = (
                best_move["value"]
            )

        result.at[idx, "Jumlah Usulan"] = (
            safe_float(
                result.at[idx, "Kuantitas Usulan"]
            )
            * safe_float(
                result.at[idx, "Harga Usulan"]
            )
        )

        return result, (
            "Penyesuaian akhir diterapkan tanpa melampaui batas."
        )

    return result, (
        "Tidak ada penyesuaian tambahan yang masih berada "
        "dalam batas harga dan kuantitas."
    )


def replace_single_recommendation_row(
    simulation_df: pd.DataFrame,
    row_index: int,
    replacement: dict[str, Any],
    target: float,
    max_price_increase: float,
    max_quantity_increase: float,
    rounding_step: int,
    tolerance: float,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Mengganti satu baris rekomendasi dan menyeimbangkan kembali total.
    """

    result = simulation_df.copy()
    messages: list[str] = []

    if row_index not in result.index:
        raise ValueError("Baris rekomendasi tidak ditemukan.")

    old_name = str(result.at[row_index, "Uraian"])
    old_total = safe_float(
        result.at[row_index, "Jumlah Usulan"]
    )

    price = safe_float(
        replacement.get("suggested_unit_price")
        or replacement.get("average_price")
    )

    if price <= 0:
        raise ValueError(
            "Harga barang pengganti tidak valid."
        )

    quantity_limit = max(
        int(replacement.get("quantity_limit") or 10),
        1,
    )

    quantity = max(
        1,
        min(
            int(
                replacement.get("suggested_quantity")
                or round(old_total / price)
                or 1
            ),
            quantity_limit,
        ),
    )

    result.at[row_index, "Uraian"] = str(
        replacement.get("product_name")
        or "Barang Database"
    )
    result.at[row_index, "Kategori"] = str(
        replacement.get("category")
        or "Belum Dikategorikan"
    )
    result.at[row_index, "Satuan"] = str(
        replacement.get("unit") or "pcs"
    )
    result.at[row_index, "Kuantitas"] = float(quantity)
    result.at[row_index, "Kuantitas Asli"] = 0.0
    result.at[row_index, "Kuantitas Usulan"] = float(quantity)
    result.at[row_index, "Harga"] = float(price)
    result.at[row_index, "Harga Asli"] = float(price)
    result.at[row_index, "Harga Usulan"] = float(price)
    result.at[row_index, "Jumlah"] = float(quantity * price)
    result.at[row_index, "Jumlah Asli"] = 0.0
    result.at[row_index, "Jumlah Usulan"] = float(
        quantity * price
    )
    result.at[row_index, "Nama Nota"] = "Rekomendasi Database"
    result.at[row_index, "Sumber"] = "Barang Baru Database"
    result.at[row_index, "Product ID"] = replacement.get(
        "product_id"
    )
    result.at[row_index, "Product Family"] = str(
        replacement.get("product_family")
        or get_product_family(
            replacement.get("product_name") or ""
        )
    )
    result.at[row_index, "Skor Rekomendasi"] = safe_float(
        replacement.get("score")
    )
    result.at[row_index, "Alasan"] = str(
        replacement.get("reason") or ""
    )
    result.at[row_index, "Batas Rekomendasi"] = int(
        replacement.get("quantity_limit") or 10
    )
    result.at[row_index, "Wajib APD"] = bool(
        replacement.get("is_mandatory")
    )

    result, rule_messages = apply_absolute_quantity_rules(
        result
    )
    messages.extend(rule_messages)

    current_total = float(
        result["Jumlah Usulan"].sum()
    )

    # Bila pengganti membuat total melewati target, kurangi kuantitas
    # baris pengganti selama masih memperbaiki jarak.
    while (
        current_total > target
        and safe_float(
            result.at[row_index, "Kuantitas Usulan"]
        ) > 1
    ):
        current_quantity = safe_float(
            result.at[row_index, "Kuantitas Usulan"]
        )
        current_gap = abs(target - current_total)
        candidate_total = current_total - price
        candidate_gap = abs(target - candidate_total)

        if candidate_gap > current_gap:
            break

        new_quantity = current_quantity - 1
        result.at[row_index, "Kuantitas"] = new_quantity
        result.at[row_index, "Kuantitas Usulan"] = new_quantity
        result.at[row_index, "Jumlah"] = (
            new_quantity * price
        )
        result.at[row_index, "Jumlah Usulan"] = (
            new_quantity * price
        )
        current_total = candidate_total

    if current_total < target:
        result, quantity_messages = increase_quantities(
            result=result,
            target=target,
            max_quantity_increase=max_quantity_increase,
        )
        messages.extend(quantity_messages)

        result, price_messages = increase_prices(
            result=result,
            target=target,
            max_price_increase=max_price_increase,
            rounding_step=rounding_step,
        )
        messages.extend(price_messages)

        for _ in range(100):
            current_total = float(
                result["Jumlah Usulan"].sum()
            )

            if abs(target - current_total) <= tolerance:
                break

            previous_total = current_total

            result, balance_message = precise_balance(
                result=result,
                target=target,
                max_price_increase=max_price_increase,
                max_quantity_increase=max_quantity_increase,
                rounding_step=rounding_step,
                tolerance=tolerance,
            )

            current_total = float(
                result["Jumlah Usulan"].sum()
            )

            if current_total == previous_total:
                messages.append(balance_message)
                break

    messages.insert(
        0,
        f"{old_name} diganti dengan "
        f"{replacement.get('product_name')}.",
    )

    return result, messages


def build_automatic_database_simulation(
    source: pd.DataFrame,
    invoice_id: str,
    target: float,
    max_price_increase: float,
    max_quantity_increase: float,
    new_product_share: float,
    max_new_products: int,
    rounding_step: int,
    tolerance: float,
    random_seed: int | None = None,
    exclude_product_ids: set[str] | None = None,
) -> dict[str, Any]:
    """
    Urutan otomatis:
    1. Tambah barang baru dari database.
    2. Naikkan kuantitas secara terbatas.
    3. Naikkan harga secara terbatas.
    4. Koreksi akhir.
    """

    result = prepare_simulation_source(source)

    result, absolute_rule_messages = apply_absolute_quantity_rules(
        result
    )

    original_total = float(
        result["Jumlah Asli"].sum()
    )

    target = float(round(target))

    messages: list[str] = []
    messages.extend(absolute_rule_messages)

    try:
        recommendations = recommend_new_products(
            invoice_id=invoice_id,
            limit=max(max_new_products * 5, 30),
            random_seed=random_seed,
            exclude_product_ids=exclude_product_ids,
        )
    except Exception as error:
        recommendations = []
        messages.append(
            f"Rekomendasi database belum dapat dibaca: {error}"
        )

    gap = target - float(
        result["Jumlah Usulan"].sum()
    )

    result, addition_messages = add_database_products(
        result=result,
        recommendations=recommendations,
        gap=gap,
        share_percent=new_product_share,
        max_new_products=max_new_products,
    )
    messages.extend(addition_messages)

    result, quantity_messages = increase_quantities(
        result=result,
        target=target,
        max_quantity_increase=max_quantity_increase,
    )
    messages.extend(quantity_messages)

    result, price_messages = increase_prices(
        result=result,
        target=target,
        max_price_increase=max_price_increase,
        rounding_step=rounding_step,
    )
    messages.extend(price_messages)

    # Safety pass: enforce absolute rules before the final tolerance check.
    # If a prior operation changed a protected item, the balancing loop below
    # works from the corrected total instead of showing a false Rp206 result.
    result, final_rule_messages = apply_absolute_quantity_rules(
        result
    )
    messages.extend(final_rule_messages)

    for _ in range(100):
        current_total = float(
            result["Jumlah Usulan"].sum()
        )

        if abs(target - current_total) <= tolerance:
            break

        previous_total = current_total

        result, balance_message = precise_balance(
            result=result,
            target=target,
            max_price_increase=max_price_increase,
            max_quantity_increase=max_quantity_increase,
            rounding_step=rounding_step,
            tolerance=tolerance,
        )

        current_total = float(
            result["Jumlah Usulan"].sum()
        )

        if current_total == previous_total:
            messages.append(balance_message)
            break

    revised_total = float(
        result["Jumlah Usulan"].sum()
    )

    difference = target - revised_total

    result["Persentase Harga"] = 0.0

    original_price_mask = result["Harga Asli"] > 0

    result.loc[
        original_price_mask,
        "Persentase Harga",
    ] = (
        (
            result.loc[
                original_price_mask,
                "Harga Usulan",
            ]
            / result.loc[
                original_price_mask,
                "Harga Asli",
            ]
        )
        - 1.0
    ) * 100.0

    result["Persentase Kuantitas"] = 0.0

    original_qty_mask = result["Kuantitas Asli"] > 0

    result.loc[
        original_qty_mask,
        "Persentase Kuantitas",
    ] = (
        (
            result.loc[
                original_qty_mask,
                "Kuantitas Usulan",
            ]
            / result.loc[
                original_qty_mask,
                "Kuantitas Asli",
            ]
        )
        - 1.0
    ) * 100.0

    reached = abs(difference) <= tolerance

    recommended_product_ids = {
        str(value)
        for value in result.loc[
            result["Sumber"] == "Barang Baru Database",
            "Product ID",
        ].dropna().tolist()
        if str(value).strip()
    }

    return {
        "dataframe": result,
        "original_total": original_total,
        "revised_total": revised_total,
        "target": target,
        "difference": difference,
        "reached": reached,
        "recommendation_count": len(recommendations),
        "messages": messages,
        "max_price_increase": max_price_increase,
        "max_quantity_increase": max_quantity_increase,
        "new_product_share": new_product_share,
        "rounding_step": rounding_step,
        "tolerance": tolerance,
        "recommended_product_ids": sorted(
            recommended_product_ids
        ),
    }


# =========================================================
# SESSION STATE
# =========================================================

if "invoice_items" not in st.session_state:
    st.session_state.invoice_items = []

if "global_budget_simulation" not in st.session_state:
    st.session_state.global_budget_simulation = None

if "budget_simulation" not in st.session_state:
    st.session_state.budget_simulation = None

if "recommendation_refresh_seed" not in st.session_state:
    st.session_state.recommendation_refresh_seed = 0

if "recommendation_excluded_ids" not in st.session_state:
    st.session_state.recommendation_excluded_ids = []


if "single_replace_seed" not in st.session_state:
    st.session_state.single_replace_seed = 0


# =========================================================
# JUDUL DAN VALIDASI
# =========================================================

st.title("📊 Revision — Smart Budget Adjustment")

st.caption(
    "INVOXA memprioritaskan barang baru dari database, "
    "kemudian menaikkan kuantitas, dan terakhir menaikkan "
    "harga secara terbatas agar target pagu tercapai."
)

st.divider()

if not st.session_state.invoice_items:
    st.warning(
        "Belum ada data. Mulai dari halaman Input Nota."
    )
    st.stop()

invoice_id = get_current_invoice_id()

if not invoice_id:
    st.error(
        "ID invoice tidak ditemukan. Kembali ke Input Nota, "
        "simpan ulang data, lalu lanjutkan melalui Matching."
    )
    st.stop()

all_items = prepare_dataframe(
    st.session_state.invoice_items
)

grand_total = float(
    all_items["Jumlah"].sum()
)

target_budget = safe_float(
    st.session_state.get("target_budget"),
    grand_total,
)

backup_csv = all_items.to_csv(
    index=False,
).encode("utf-8-sig")

st.download_button(
    "⬇️ Download Backup Data Sebelum Revisi",
    data=backup_csv,
    file_name="backup_invoice_sebelum_revisi.csv",
    mime="text/csv",
    use_container_width=True,
)


# =========================================================
# PILIH MODE
# =========================================================

st.divider()
st.subheader("Pilih Cara Revisi")

revision_mode = st.radio(
    "Mau melakukan revisi bagaimana?",
    [
        "🚀 Otomatis Cerdas dari Database",
        "✏️ Manual Per Kategori",
    ],
    horizontal=True,
    index=0,
)


# =========================================================
# MODE OTOMATIS
# =========================================================

if revision_mode == "🚀 Otomatis Cerdas dari Database":
    st.info(
        "Urutan penyesuaian: barang baru dari database → "
        "kuantitas → harga. Harga tidak akan dinaikkan "
        "melewati batas yang kamu tentukan."
    )

    st.subheader("1. Target Pagu")

    total_target = st.number_input(
        "Total pagu keseluruhan",
        min_value=0.0,
        value=float(
            target_budget
            or grand_total
        ),
        step=100_000.0,
    )

    st.subheader("2. Batas Penyesuaian")

    setting_1, setting_2 = st.columns(2)

    with setting_1:
        max_price_increase = st.slider(
            "Maksimal kenaikan harga per barang",
            min_value=0,
            max_value=30,
            value=int(
                DEFAULT_MAX_PRICE_INCREASE
            ),
            step=1,
            format="%d%%",
            help=(
                "Harga satuan tidak boleh melewati "
                "persentase ini dari harga awal."
            ),
        )

        new_product_share = st.slider(
            "Porsi selisih untuk barang baru",
            min_value=0,
            max_value=100,
            value=int(
                DEFAULT_NEW_PRODUCT_SHARE
            ),
            step=5,
            format="%d%%",
            help=(
                "Semakin besar nilainya, semakin banyak "
                "selisih ditutup dengan barang baru."
            ),
        )

    with setting_2:
        max_quantity_increase = st.slider(
            "Maksimal kenaikan kuantitas",
            min_value=0,
            max_value=200,
            value=int(
                DEFAULT_MAX_QUANTITY_INCREASE
            ),
            step=10,
            format="%d%%",
        )

        max_new_products = st.number_input(
            "Maksimal jenis barang baru",
            min_value=0,
            max_value=30,
            value=8,
            step=1,
        )

    rounding_step = st.selectbox(
        "Pembulatan harga",
        options=[
            100,
            500,
            1000,
            5000,
        ],
        index=1,
    )

    tolerance = st.number_input(
        "Toleransi selisih akhir",
        min_value=0.0,
        value=float(DEFAULT_TOLERANCE),
        step=1000.0,
        help=(
            "Hasil dianggap tercapai bila selisih berada "
            "dalam nilai toleransi ini."
        ),
    )

    metric_1, metric_2, metric_3 = st.columns(3)

    metric_1.metric(
        "Total Saat Ini",
        rupiah(grand_total),
    )

    metric_2.metric(
        "Target Pagu",
        rupiah(total_target),
    )

    metric_3.metric(
        "Selisih Awal",
        rupiah(
            float(total_target) - grand_total
        ),
    )

    run_button = st.button(
        "🤖 Buat Simulasi Otomatis dari Database",
        type="primary",
        use_container_width=True,
    )

    if run_button:
        if total_target <= 0:
            st.error(
                "Target pagu harus lebih dari nol."
            )

        elif total_target < grand_total:
            st.error(
                "Target pagu lebih kecil dari total saat ini. "
                "Fitur otomatis ini dirancang untuk menambah "
                "barang, kuantitas, atau harga."
            )

        else:
            st.session_state.recommendation_refresh_seed += 1
            st.session_state.recommendation_excluded_ids = []

            with st.spinner(
                "Mengambil rekomendasi database dan "
                "menyusun simulasi..."
            ):
                simulation = (
                    build_automatic_database_simulation(
                        source=all_items,
                        invoice_id=invoice_id,
                        target=float(total_target),
                        max_price_increase=float(
                            max_price_increase
                        ),
                        max_quantity_increase=float(
                            max_quantity_increase
                        ),
                        new_product_share=float(
                            new_product_share
                        ),
                        max_new_products=int(
                            max_new_products
                        ),
                        rounding_step=int(
                            rounding_step
                        ),
                        tolerance=float(
                            tolerance
                        ),
                        random_seed=int(
                            st.session_state.recommendation_refresh_seed
                        ),
                        exclude_product_ids=set(),
                    )
                )

            st.session_state.global_budget_simulation = {
                "data": simulation[
                    "dataframe"
                ].to_dict("records"),
                "original_total": simulation[
                    "original_total"
                ],
                "revised_total": simulation[
                    "revised_total"
                ],
                "target": simulation["target"],
                "difference": simulation[
                    "difference"
                ],
                "reached": simulation["reached"],
                "recommendation_count": simulation[
                    "recommendation_count"
                ],
                "messages": simulation[
                    "messages"
                ],
                "max_price_increase": simulation[
                    "max_price_increase"
                ],
                "max_quantity_increase": simulation[
                    "max_quantity_increase"
                ],
                "new_product_share": simulation[
                    "new_product_share"
                ],
                "rounding_step": simulation[
                    "rounding_step"
                ],
                "tolerance": simulation[
                    "tolerance"
                ],
                "recommended_product_ids": simulation[
                    "recommended_product_ids"
                ],
            }

            st.rerun()

    simulation = st.session_state.get(
        "global_budget_simulation"
    )

    if simulation:
        st.divider()
        st.subheader("3. Hasil Simulasi Otomatis")

        simulation_df = pd.DataFrame(
            simulation["data"]
        )

        result_1, result_2, result_3, result_4 = (
            st.columns(4)
        )

        result_1.metric(
            "Total Asli",
            rupiah(
                simulation["original_total"]
            ),
        )

        result_2.metric(
            "Target Pagu",
            rupiah(simulation["target"]),
        )

        result_3.metric(
            "Total Usulan",
            rupiah(
                simulation["revised_total"]
            ),
        )

        result_4.metric(
            "Selisih",
            rupiah(
                abs(simulation["difference"])
            ),
        )

        new_product_count = int(
            (
                simulation_df["Sumber"]
                == "Barang Baru Database"
            ).sum()
        )

        info_1, info_2, info_3 = st.columns(3)

        info_1.metric(
            "Barang Baru Ditambahkan",
            new_product_count,
        )

        info_2.metric(
            "Batas Kenaikan Harga",
            f"{simulation['max_price_increase']:.0f}%",
        )

        info_3.metric(
            "Batas Kenaikan Kuantitas",
            f"{simulation['max_quantity_increase']:.0f}%",
        )

        if simulation["reached"]:
            st.success(
                "Simulasi sudah mencapai target dalam "
                "batas toleransi."
            )
        else:
            st.warning(
                "Simulasi sudah menggunakan barang baru, "
                "kenaikan kuantitas, dan kenaikan harga "
                "sesuai batas, tetapi masih memiliki selisih "
                f"{rupiah(abs(simulation['difference']))}."
            )

        for message in simulation.get(
            "messages",
            [],
        ):
            st.caption(f"• {message}")

        mandatory_count = int(
            simulation_df.get("Wajib APD", pd.Series(dtype=bool))
            .fillna(False)
            .astype(bool)
            .sum()
        )
        if mandatory_count:
            st.info(
                f"{mandatory_count} rekomendasi diprioritaskan untuk "
                "memenuhi aturan minimum APD."
            )

        if st.button(
            "🔄 Refresh dengan Barang Berbeda",
            use_container_width=True,
            help=(
                "Barang rekomendasi yang sedang tampil akan dikecualikan, "
                "lalu sistem mengambil barang lain dari database."
            ),
        ):
            current_product_ids = {
                str(product_id)
                for product_id in simulation.get(
                    "recommended_product_ids",
                    [],
                )
                if product_id
            }

            excluded_ids = {
                str(product_id)
                for product_id in st.session_state.get(
                    "recommendation_excluded_ids",
                    [],
                )
                if product_id
            }

            excluded_ids.update(current_product_ids)

            st.session_state.recommendation_refresh_seed += 1

            with st.spinner(
                "Mengambil kombinasi barang yang berbeda..."
            ):
                refreshed = build_automatic_database_simulation(
                    source=all_items,
                    invoice_id=invoice_id,
                    target=float(simulation["target"]),
                    max_price_increase=float(
                        simulation["max_price_increase"]
                    ),
                    max_quantity_increase=float(
                        simulation["max_quantity_increase"]
                    ),
                    new_product_share=float(
                        simulation["new_product_share"]
                    ),
                    max_new_products=int(
                        max_new_products
                    ),
                    rounding_step=int(
                        simulation["rounding_step"]
                    ),
                    tolerance=float(
                        simulation["tolerance"]
                    ),
                    random_seed=int(
                        st.session_state.recommendation_refresh_seed
                    ),
                    exclude_product_ids=excluded_ids,
                )

            # Jika seluruh kandidat sudah pernah dipakai, mulai siklus baru
            # tetapi tetap kecualikan barang yang sedang tampil.
            if not refreshed["recommended_product_ids"]:
                excluded_ids = current_product_ids

                refreshed = build_automatic_database_simulation(
                    source=all_items,
                    invoice_id=invoice_id,
                    target=float(simulation["target"]),
                    max_price_increase=float(
                        simulation["max_price_increase"]
                    ),
                    max_quantity_increase=float(
                        simulation["max_quantity_increase"]
                    ),
                    new_product_share=float(
                        simulation["new_product_share"]
                    ),
                    max_new_products=int(
                        max_new_products
                    ),
                    rounding_step=int(
                        simulation["rounding_step"]
                    ),
                    tolerance=float(
                        simulation["tolerance"]
                    ),
                    random_seed=int(
                        st.session_state.recommendation_refresh_seed
                    ),
                    exclude_product_ids=excluded_ids,
                )

            st.session_state.recommendation_excluded_ids = sorted(
                excluded_ids
            )

            st.session_state.global_budget_simulation = {
                "data": refreshed["dataframe"].to_dict("records"),
                "original_total": refreshed["original_total"],
                "revised_total": refreshed["revised_total"],
                "target": refreshed["target"],
                "difference": refreshed["difference"],
                "reached": refreshed["reached"],
                "recommendation_count": refreshed[
                    "recommendation_count"
                ],
                "messages": refreshed["messages"],
                "max_price_increase": refreshed[
                    "max_price_increase"
                ],
                "max_quantity_increase": refreshed[
                    "max_quantity_increase"
                ],
                "new_product_share": refreshed[
                    "new_product_share"
                ],
                "rounding_step": refreshed["rounding_step"],
                "tolerance": refreshed["tolerance"],
                "recommended_product_ids": refreshed[
                    "recommended_product_ids"
                ],
            }

            st.rerun()

        st.markdown("#### Ganti Satu Barang Rekomendasi")

        recommendation_rows_df = simulation_df[
            simulation_df["Sumber"]
            == "Barang Baru Database"
        ].copy()

        if recommendation_rows_df.empty:
            st.caption(
                "Belum ada barang rekomendasi yang dapat diganti."
            )
        else:
            replacement_options = {
                (
                    f"{row['Uraian']} | "
                    f"{rupiah(safe_float(row['Jumlah Usulan']))}"
                ): int(idx)
                for idx, row in recommendation_rows_df.iterrows()
            }

            selected_replacement_label = st.selectbox(
                "Pilih barang rekomendasi yang ingin diganti",
                options=list(replacement_options.keys()),
                key="single_replacement_selector",
            )

            if st.button(
                "🔁 Ganti Item Terpilih",
                use_container_width=True,
                help=(
                    "Hanya item yang dipilih yang diganti. "
                    "Rekomendasi lain tetap dipertahankan."
                ),
            ):
                selected_row_index = replacement_options[
                    selected_replacement_label
                ]

                selected_row = simulation_df.loc[
                    selected_row_index
                ]

                visible_product_ids = {
                    str(value)
                    for value in recommendation_rows_df[
                        "Product ID"
                    ].dropna().tolist()
                    if str(value).strip()
                }

                old_product_id = str(
                    selected_row.get("Product ID") or ""
                )

                # Produk yang dipilih harus boleh diganti,
                # jadi keluarkan ID-nya dari daftar visible.
                visible_product_ids.discard(
                    old_product_id
                )

                st.session_state.single_replace_seed += 1

                try:
                    with st.spinner(
                        "Mencari satu barang pengganti..."
                    ):
                        replacement = (
                            recommend_replacement_product(
                                invoice_id=invoice_id,
                                replaced_product_id=old_product_id,
                                visible_product_ids=visible_product_ids,
                                old_product_name=str(
                                    selected_row.get("Uraian")
                                    or ""
                                ),
                                old_category=str(
                                    selected_row.get("Kategori")
                                    or ""
                                ),
                                old_total=safe_float(
                                    selected_row.get(
                                        "Jumlah Usulan"
                                    )
                                ),
                                random_seed=int(
                                    st.session_state.single_replace_seed
                                ),
                            )
                        )

                    if not replacement:
                        st.warning(
                            "Belum ditemukan barang pengganti "
                            "yang memenuhi aturan."
                        )
                    else:
                        replaced_df, replace_messages = (
                            replace_single_recommendation_row(
                                simulation_df=simulation_df,
                                row_index=selected_row_index,
                                replacement=replacement,
                                target=float(
                                    simulation["target"]
                                ),
                                max_price_increase=float(
                                    simulation[
                                        "max_price_increase"
                                    ]
                                ),
                                max_quantity_increase=float(
                                    simulation[
                                        "max_quantity_increase"
                                    ]
                                ),
                                rounding_step=int(
                                    simulation["rounding_step"]
                                ),
                                tolerance=float(
                                    simulation["tolerance"]
                                ),
                            )
                        )

                        revised_total = float(
                            replaced_df[
                                "Jumlah Usulan"
                            ].sum()
                        )
                        difference = (
                            float(simulation["target"])
                            - revised_total
                        )

                        recommended_product_ids = sorted({
                            str(value)
                            for value in replaced_df.loc[
                                replaced_df["Sumber"]
                                == "Barang Baru Database",
                                "Product ID",
                            ].dropna().tolist()
                            if str(value).strip()
                        })

                        st.session_state.global_budget_simulation = {
                            **simulation,
                            "data": replaced_df.to_dict(
                                "records"
                            ),
                            "revised_total": revised_total,
                            "difference": difference,
                            "reached": (
                                abs(difference)
                                <= float(
                                    simulation["tolerance"]
                                )
                            ),
                            "messages": (
                                list(
                                    simulation.get(
                                        "messages",
                                        [],
                                    )
                                )
                                + replace_messages
                            ),
                            "recommended_product_ids": (
                                recommended_product_ids
                            ),
                        }

                        st.rerun()

                except Exception as error:
                    st.error(
                        "Barang belum dapat diganti: "
                        f"{error}"
                    )

        category_summary = (
            simulation_df.groupby(
                "Kategori",
                dropna=False,
            )
            .agg(
                Jumlah_Uraian=(
                    "Uraian",
                    "count",
                ),
                Total_Asli=(
                    "Jumlah Asli",
                    "sum",
                ),
                Total_Usulan=(
                    "Jumlah Usulan",
                    "sum",
                ),
                Barang_Baru=(
                    "Sumber",
                    lambda values: int(
                        (
                            values
                            == "Barang Baru Database"
                        ).sum()
                    ),
                ),
            )
            .reset_index()
        )

        category_summary["Perubahan"] = (
            category_summary[
                "Total_Usulan"
            ]
            - category_summary[
                "Total_Asli"
            ]
        )

        st.markdown(
            "#### Ringkasan Per Kategori"
        )

        st.dataframe(
            category_summary,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Jumlah_Uraian": (
                    "Jumlah Uraian"
                ),
                "Barang_Baru": (
                    "Barang Baru"
                ),
                "Total_Asli": (
                    st.column_config.NumberColumn(
                        "Total Asli",
                        format="Rp %.0f",
                    )
                ),
                "Total_Usulan": (
                    st.column_config.NumberColumn(
                        "Total Usulan",
                        format="Rp %.0f",
                    )
                ),
                "Perubahan": (
                    st.column_config.NumberColumn(
                        "Perubahan",
                        format="Rp %.0f",
                    )
                ),
            },
        )

        st.markdown(
            "#### Detail Semua Barang"
        )

        for column in DISPLAY_COLUMNS:
            if column not in simulation_df.columns:
                simulation_df[column] = None

        editor_columns = DISPLAY_COLUMNS.copy()

        edited_simulation = st.data_editor(
            simulation_df[editor_columns],
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            key="smart_database_simulation_editor",
            column_config={
                "Kategori": (
                    st.column_config.SelectboxColumn(
                        "Kategori",
                        options=CATEGORIES,
                        required=True,
                    )
                ),
                "Nama Nota": (
                    st.column_config.TextColumn(
                        "Nama Nota",
                    )
                ),
                "Uraian": (
                    st.column_config.TextColumn(
                        "Uraian",
                        width="large",
                        required=True,
                    )
                ),
                "Satuan": (
                    st.column_config.SelectboxColumn(
                        "Satuan",
                        options=UNITS,
                        required=True,
                    )
                ),
                "Kuantitas Asli": (
                    st.column_config.NumberColumn(
                        "Kuantitas Asli",
                        disabled=True,
                    )
                ),
                "Kuantitas Usulan": (
                    st.column_config.NumberColumn(
                        "Kuantitas Usulan",
                        min_value=0.0,
                        step=1.0,
                    )
                ),
                "Harga Asli": (
                    st.column_config.NumberColumn(
                        "Harga Asli",
                        format="Rp %.0f",
                        disabled=True,
                    )
                ),
                "Harga Usulan": (
                    st.column_config.NumberColumn(
                        "Harga Usulan",
                        min_value=0.0,
                        step=float(
                            simulation[
                                "rounding_step"
                            ]
                        ),
                        format="Rp %.0f",
                    )
                ),
                "Jumlah Asli": (
                    st.column_config.NumberColumn(
                        "Jumlah Asli",
                        format="Rp %.0f",
                        disabled=True,
                    )
                ),
                "Jumlah Usulan": (
                    st.column_config.NumberColumn(
                        "Jumlah Usulan",
                        format="Rp %.0f",
                        disabled=True,
                    )
                ),
                "Sumber": (
                    st.column_config.TextColumn(
                        "Sumber",
                        disabled=True,
                    )
                ),
                "Kunci": (
                    st.column_config.CheckboxColumn(
                        "Kunci",
                    )
                ),
            },
        )

        edited_simulation[
            "Kuantitas Usulan"
        ] = pd.to_numeric(
            edited_simulation[
                "Kuantitas Usulan"
            ],
            errors="coerce",
        ).fillna(0.0)

        edited_simulation[
            "Harga Usulan"
        ] = pd.to_numeric(
            edited_simulation[
                "Harga Usulan"
            ],
            errors="coerce",
        ).fillna(0.0)

        # Validasi ulang hanya untuk perubahan manual pengguna.
        # Simulasi otomatis V3 sudah menerapkan batas sebelum balancing.
        edited_simulation, editor_rule_messages = (
            apply_absolute_quantity_rules(
                edited_simulation
            )
        )

        edited_simulation[
            "Jumlah Usulan"
        ] = (
            edited_simulation[
                "Kuantitas Usulan"
            ]
            * edited_simulation[
                "Harga Usulan"
            ]
        )

        for rule_message in editor_rule_messages:
            st.caption(f"• {rule_message}")

        preview_total = float(
            edited_simulation[
                "Jumlah Usulan"
            ].sum()
        )

        preview_difference = (
            float(simulation["target"])
            - preview_total
        )

        preview_valid = (
            abs(preview_difference)
            <= float(
                simulation["tolerance"]
            )
        )

        preview_1, preview_2 = st.columns(2)

        preview_1.metric(
            "Total Setelah Koreksi Manual",
            rupiah(preview_total),
        )

        preview_2.metric(
            "Selisih dari Target",
            rupiah(
                abs(preview_difference)
            ),
        )

        if preview_valid:
            st.success(
                "Hasil dapat diterapkan."
            )
        else:
            st.warning(
                "Hasil masih di luar toleransi. "
                "Kamu tetap dapat mengubah kuantitas "
                "atau harga usulan."
            )

        apply_col, clear_col = st.columns(2)

        if apply_col.button(
            "✅ Terapkan Simulasi",
            type="primary",
            use_container_width=True,
            disabled=not preview_valid,
        ):
            updated = edited_simulation.copy()

            updated["Kuantitas"] = updated[
                "Kuantitas Usulan"
            ]

            updated["Harga"] = updated[
                "Harga Usulan"
            ]

            updated["Jumlah"] = updated[
                "Jumlah Usulan"
            ]

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

            updated = prepare_dataframe(
                updated[keep_columns]
            )

            st.session_state.invoice_items = (
                updated.to_dict("records")
            )

            st.session_state.final_items = (
                st.session_state.invoice_items
            )

            st.session_state.matched_items = (
                st.session_state.invoice_items
            )

            st.session_state.global_budget_simulation = (
                None
            )

            st.success(
                "Barang baru, perubahan kuantitas, "
                "dan perubahan harga berhasil diterapkan."
            )

            st.rerun()

        if clear_col.button(
            "🗑️ Hapus Simulasi",
            use_container_width=True,
        ):
            st.session_state.global_budget_simulation = (
                None
            )
            st.rerun()


# =========================================================
# MODE MANUAL
# =========================================================

else:
    st.info(
        "Pilih kategori yang ingin direvisi secara manual."
    )

    available_categories = sorted(
        all_items[
            "Kategori"
        ].astype(str).unique().tolist()
    )

    selected_category = st.selectbox(
        "Pilih kategori",
        available_categories,
    )

    category_items = (
        all_items[
            all_items["Kategori"]
            == selected_category
        ]
        .copy()
        .reset_index(drop=True)
    )

    edited_category = st.data_editor(
        category_items,
        hide_index=True,
        num_rows="dynamic",
        use_container_width=True,
        key=f"manual_editor_{selected_category}",
        column_config={
            "Uraian": (
                st.column_config.TextColumn(
                    "Uraian Barang",
                    required=True,
                    width="large",
                )
            ),
            "Kuantitas": (
                st.column_config.NumberColumn(
                    "Kuantitas",
                    min_value=0.0,
                    step=1.0,
                )
            ),
            "Satuan": (
                st.column_config.SelectboxColumn(
                    "Satuan",
                    options=UNITS,
                )
            ),
            "Harga": (
                st.column_config.NumberColumn(
                    "Harga Satuan",
                    min_value=0.0,
                    step=1000.0,
                    format="Rp %.0f",
                )
            ),
            "Jumlah": (
                st.column_config.NumberColumn(
                    "Jumlah",
                    disabled=True,
                    format="Rp %.0f",
                )
            ),
            "Kategori": (
                st.column_config.SelectboxColumn(
                    "Kategori",
                    options=CATEGORIES,
                )
            ),
            "Nama Nota": (
                st.column_config.TextColumn(
                    "Nama Nota",
                )
            ),
            "Kunci": (
                st.column_config.CheckboxColumn(
                    "Kunci",
                )
            ),
        },
    )

    edited_category = recalculate(
        edited_category
    )

    edited_category, manual_rule_messages = (
        apply_absolute_quantity_rules(
            edited_category
        )
    )

    for rule_message in manual_rule_messages:
        st.caption(f"• {rule_message}")

    edited_category = edited_category[
        edited_category[
            "Uraian"
        ]
        .fillna("")
        .astype(str)
        .str.strip()
        .ne("")
    ].copy()

    category_total = float(
        edited_category[
            "Jumlah"
        ].sum()
    )

    manual_1, manual_2, manual_3 = st.columns(3)

    manual_1.metric(
        "Jumlah Uraian",
        len(edited_category),
    )

    manual_2.metric(
        f"Total {selected_category}",
        rupiah(category_total),
    )

    manual_3.metric(
        "Item Terkunci",
        int(
            edited_category[
                "Kunci"
            ].sum()
        ),
    )

    if st.button(
        f"💾 Simpan Revisi Manual {selected_category}",
        use_container_width=True,
    ):
        others = all_items[
            all_items["Kategori"]
            != selected_category
        ].copy()

        combined = prepare_dataframe(
            pd.concat(
                [
                    others,
                    edited_category,
                ],
                ignore_index=True,
            )
        )

        st.session_state.invoice_items = (
            combined.to_dict("records")
        )

        st.session_state.final_items = (
            st.session_state.invoice_items
        )

        st.session_state.matched_items = (
            st.session_state.invoice_items
        )

        st.session_state.global_budget_simulation = (
            None
        )

        st.success(
            "Revisi manual berhasil disimpan."
        )

        st.rerun()


# =========================================================
# RINGKASAN AKHIR
# =========================================================

st.divider()
st.subheader("Ringkasan Akhir Tersimpan")

latest = prepare_dataframe(
    st.session_state.invoice_items
)

summary = (
    latest.groupby(
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
        "Jumlah_Uraian": (
            "Jumlah Uraian"
        ),
        "Total": (
            st.column_config.NumberColumn(
                "Total",
                format="Rp %.0f",
            )
        ),
    },
)

st.metric(
    "Total Seluruh Kategori",
    rupiah(
        latest["Jumlah"].sum()
    ),
)

st.info(
    "Setelah selesai, buka halaman Download."
)