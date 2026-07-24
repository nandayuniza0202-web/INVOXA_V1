from pathlib import Path
from typing import BinaryIO

import pandas as pd

from services.category_service import apply_predicted_categories
from services.parsers.csv_parser import parse_csv_file
from services.parsers.excel_parser import parse_and_combine_excel


EXCEL_EXTENSIONS = {".xlsx", ".xls", ".xlsm"}
CSV_EXTENSIONS = {".csv"}


def get_file_extension(
    source: str | Path | BinaryIO,
    filename: str | None = None,
) -> str:
    """
    Mengambil ekstensi file dari path lokal
    atau nama file hasil upload Streamlit.
    """

    if filename:
        return Path(filename).suffix.lower()

    if isinstance(source, (str, Path)):
        return Path(source).suffix.lower()

    source_name = getattr(source, "name", "")
    return Path(source_name).suffix.lower()


def get_source_filename(
    source: str | Path | BinaryIO,
    filename: str | None = None,
) -> str:
    """Mengambil nama file sumber."""

    if filename:
        return Path(filename).name

    if isinstance(source, (str, Path)):
        return Path(source).name

    source_name = getattr(source, "name", "")

    if source_name:
        return Path(source_name).name

    return "uploaded_file"


def import_tabular_file(
    source: str | Path | BinaryIO,
    filename: str | None = None,
) -> pd.DataFrame:
    """
    Membaca Excel atau CSV ke format standar INVOXA.

    Proses:
    1. Mendeteksi jenis file.
    2. Memilih parser Excel atau CSV.
    3. Menyamakan struktur kolom.
    4. Mengisi kategori yang kosong secara otomatis.
    5. Menambahkan informasi sumber file.
    """

    extension = get_file_extension(
        source=source,
        filename=filename,
    )

    source_filename = get_source_filename(
        source=source,
        filename=filename,
    )

    if extension in EXCEL_EXTENSIONS:
        dataframe = parse_and_combine_excel(source)
        input_method = "excel"

    elif extension in CSV_EXTENSIONS:
        dataframe = parse_csv_file(source)
        input_method = "import"

    else:
        raise ValueError(
            f"Format file {extension or 'tidak diketahui'} "
            "belum didukung. Gunakan file Excel atau CSV."
        )

    dataframe = apply_predicted_categories(dataframe)

    dataframe["source_filename"] = source_filename
    dataframe["input_method"] = input_method

    return dataframe.reset_index(drop=True)
from datetime import date
from typing import Any

from database.supabase_client import supabase
from services.category_service import (
    get_category_by_name,
    normalize_text,
)


def _safe_number(value: Any, default: float = 0) -> float:
    """Mengubah nilai kosong/NaN menjadi angka aman."""

    if value is None or pd.isna(value):
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get_or_create_product(
    description: str,
    category_name: str,
    unit: str | None,
) -> dict[str, Any]:
    """
    Mengambil produk yang sudah ada berdasarkan normalized_name.
    Jika belum ada, membuat produk baru.
    """

    normalized_name = normalize_text(description)

    existing = (
        supabase.table("products")
        .select("*")
        .eq("normalized_name", normalized_name)
        .limit(1)
        .execute()
    )

    if existing.data:
        return existing.data[0]

    category = get_category_by_name(category_name)

    payload = {
        "product_name": description.strip(),
        "normalized_name": normalized_name,
        "category_id": category["id"] if category else None,
        "default_unit": unit,
        "usage_count": 0,
    }

    created = (
        supabase.table("products")
        .insert(payload)
        .execute()
    )

    if not created.data:
        raise RuntimeError(
            f"Produk gagal dibuat: {description}"
        )

    return created.data[0]


def save_imported_invoice(
    dataframe: pd.DataFrame,
    invoice_number: str | None = None,
    invoice_date: date | str | None = None,
    vendor_name: str | None = None,
    customer_name: str | None = None,
    target_budget: float | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """
    Menyimpan hasil preview ke Supabase.

    DataFrame sebaiknya sudah direvisi manual sebelum fungsi ini dipanggil.
    """

    if dataframe is None or dataframe.empty:
        raise ValueError("Tidak ada data yang dapat disimpan.")

    required_columns = {
        "raw_description",
        "quantity",
        "unit",
        "unit_price",
        "total_price",
        "category",
    }

    missing_columns = required_columns - set(dataframe.columns)

    if missing_columns:
        raise ValueError(
            "Kolom wajib belum lengkap: "
            + ", ".join(sorted(missing_columns))
        )

    clean_dataframe = dataframe.copy()

    clean_dataframe["raw_description"] = (
        clean_dataframe["raw_description"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    clean_dataframe = clean_dataframe[
        clean_dataframe["raw_description"].ne("")
    ].copy()

    if clean_dataframe.empty:
        raise ValueError("Semua uraian barang kosong.")

    original_total = float(
        clean_dataframe["total_price"]
        .apply(lambda value: _safe_number(value, 0))
        .sum()
    )

    source_filename = None
    input_method = "manual"

    if "source_filename" in clean_dataframe.columns:
        source_values = (
            clean_dataframe["source_filename"]
            .dropna()
            .astype(str)
        )

        if not source_values.empty:
            source_filename = source_values.iloc[0]

    if "input_method" in clean_dataframe.columns:
        method_values = (
            clean_dataframe["input_method"]
            .dropna()
            .astype(str)
        )

        if not method_values.empty:
            input_method = method_values.iloc[0]

    invoice_payload = {
        "invoice_number": invoice_number,
        "invoice_date": (
            str(invoice_date)
            if invoice_date
            else str(date.today())
        ),
        "vendor_name": vendor_name,
        "customer_name": customer_name,
        "target_budget": target_budget,
        "original_total": original_total,
        "final_total": original_total,
        "input_method": input_method,
        "source_filename": source_filename,
        "status": "processed",
        "notes": notes,
    }

    invoice_response = (
        supabase.table("invoices")
        .insert(invoice_payload)
        .execute()
    )

    if not invoice_response.data:
        raise RuntimeError("Invoice gagal dibuat di Supabase.")

    invoice = invoice_response.data[0]
    invoice_id = invoice["id"]

    saved_items = 0

    for _, row in clean_dataframe.iterrows():
        description = str(row["raw_description"]).strip()
        category_name = str(
            row.get("category") or "Belum Dikategorikan"
        ).strip()
        unit = (
            str(row.get("unit")).strip()
            if row.get("unit") is not None
            and not pd.isna(row.get("unit"))
            else None
        )

        quantity = _safe_number(row.get("quantity"), 1)
        unit_price = _safe_number(row.get("unit_price"), 0)

        category = get_category_by_name(category_name)

        if not category:
            category = get_category_by_name(
                "Belum Dikategorikan"
            )

        product = _get_or_create_product(
            description=description,
            category_name=category["name"],
            unit=unit,
        )

        item_payload = {
            "invoice_id": invoice_id,
            "product_id": product["id"],
            "raw_description": description,
            "normalized_description": normalize_text(description),
            "category_id": category["id"],
            "quantity": quantity,
            "unit": unit,
            "unit_price": unit_price,
            "category_source": "manual",
            "category_confidence": 1,
            "is_recommended": False,
        }

        item_response = (
            supabase.table("invoice_items")
            .insert(item_payload)
            .execute()
        )

        if not item_response.data:
            raise RuntimeError(
                f"Item gagal disimpan: {description}"
            )

        invoice_item = item_response.data[0]

        price_payload = {
            "product_id": product["id"],
            "invoice_item_id": invoice_item["id"],
            "vendor_name": vendor_name,
            "unit": unit,
            "quantity": quantity,
            "unit_price": unit_price,
            "recorded_date": (
                str(invoice_date)
                if invoice_date
                else str(date.today())
            ),
        }

        (
            supabase.table("price_history")
            .insert(price_payload)
            .execute()
        )

        (
            supabase.table("products")
            .update({
                "usage_count": int(
                    product.get("usage_count") or 0
                ) + 1,
            })
            .eq("id", product["id"])
            .execute()
        )

        saved_items += 1

    return {
        "invoice_id": invoice_id,
        "saved_items": saved_items,
        "total": original_total,
    }