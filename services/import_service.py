from datetime import date, datetime
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd

from database.supabase_client import supabase
from services.category_service import (
    apply_predicted_categories,
    get_category_by_name,
    normalize_text,
    predict_category,
)
from services.parsers.csv_parser import parse_csv_file
from services.parsers.excel_parser import parse_and_combine_excel


EXCEL_EXTENSIONS = {".xlsx", ".xls", ".xlsm"}
CSV_EXTENSIONS = {".csv"}


def get_file_extension(
    source: str | Path | BinaryIO,
    filename: str | None = None,
) -> str:
    if filename:
        return Path(filename).suffix.lower()

    if isinstance(source, (str, Path)):
        return Path(source).suffix.lower()

    return Path(getattr(source, "name", "")).suffix.lower()


def get_source_filename(
    source: str | Path | BinaryIO,
    filename: str | None = None,
) -> str:
    if filename:
        return Path(filename).name

    if isinstance(source, (str, Path)):
        return Path(source).name

    source_name = getattr(source, "name", "")
    return Path(source_name).name if source_name else "uploaded_file"


def import_tabular_file(
    source: str | Path | BinaryIO,
    filename: str | None = None,
) -> pd.DataFrame:
    extension = get_file_extension(source=source, filename=filename)
    source_filename = get_source_filename(source=source, filename=filename)

    if extension in EXCEL_EXTENSIONS:
        dataframe = parse_and_combine_excel(source)
        input_method = "excel"
    elif extension in CSV_EXTENSIONS:
        dataframe = parse_csv_file(source)
        input_method = "import"
    else:
        raise ValueError(
            f"Format file {extension or 'tidak diketahui'} belum didukung. "
            "Gunakan file Excel atau CSV."
        )

    if dataframe is None:
        dataframe = pd.DataFrame()

    if dataframe.empty:
        dataframe["source_filename"] = pd.Series(dtype="object")
        dataframe["input_method"] = pd.Series(dtype="object")
        return dataframe

    dataframe = apply_predicted_categories(
        dataframe,
        overwrite_existing=True,
    )
    dataframe["source_filename"] = source_filename
    dataframe["input_method"] = input_method

    return dataframe.reset_index(drop=True)


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True

    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass

    return not str(value).strip()


def _safe_number(value: Any, default: float = 0) -> float:
    if _is_empty_value(value):
        return default

    if isinstance(value, str):
        cleaned = (
            value.strip()
            .replace("Rp", "")
            .replace("rp", "")
            .replace(" ", "")
        )

        if "." in cleaned and "," in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        elif "." in cleaned:
            parts = cleaned.split(".")
            if (
                len(parts) > 1
                and all(part.isdigit() for part in parts)
                and len(parts[-1]) == 3
            ):
                cleaned = "".join(parts)

        value = cleaned

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_text(value: Any, default: str = "") -> str:
    if _is_empty_value(value):
        return default
    return str(value).strip()


def _normalize_invoice_date(value: date | str | None) -> str:
    if value is None:
        return date.today().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    text = str(value).strip()

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue

    raise ValueError(
        "Format tanggal invoice tidak dikenali. "
        "Gunakan YYYY-MM-DD atau DD/MM/YYYY."
    )


def _get_row_description(row: pd.Series) -> str:
    for column_name in (
        "raw_description",
        "description",
        "product_name",
        "name",
        "item_name",
    ):
        value = row.get(column_name)
        if not _is_empty_value(value):
            return str(value).strip()
    return ""


def _get_row_category(row: pd.Series) -> dict[str, Any]:
    description = _get_row_description(row)
    category_name = _safe_text(row.get("category"))
    category_source = _safe_text(row.get("category_source"))
    category_confidence = _safe_number(
        row.get("category_confidence"),
        default=0,
    )
    matched_keyword = _safe_text(
        row.get("category_matched_keyword")
    )

    if category_name:
        category = get_category_by_name(category_name)
        if category:
            if not category_source:
                category_source = "manual"
                category_confidence = 1.0

            return {
                "category_id": category["id"],
                "category_name": category["name"],
                "category_source": category_source,
                "category_confidence": category_confidence,
                "matched_keyword": matched_keyword,
            }

    prediction = predict_category(description)

    if prediction:
        return {
            "category_id": prediction["category_id"],
            "category_name": prediction["category_name"],
            "category_source": prediction["source"],
            "category_confidence": prediction["confidence"],
            "matched_keyword": prediction.get("matched_keyword") or "",
        }

    uncategorized = get_category_by_name("Belum Dikategorikan")

    if not uncategorized:
        raise RuntimeError(
            "Kategori 'Belum Dikategorikan' tidak ditemukan di Supabase."
        )

    return {
        "category_id": uncategorized["id"],
        "category_name": uncategorized["name"],
        "category_source": "automatic",
        "category_confidence": 0.0,
        "matched_keyword": "",
    }


def _get_or_create_product(
    description: str,
    category_name: str,
    unit: str | None,
) -> dict[str, Any]:
    normalized_name = normalize_text(description)

    if not normalized_name:
        raise ValueError("Nama produk tidak boleh kosong.")

    existing_response = (
        supabase.table("products")
        .select("*")
        .eq("normalized_name", normalized_name)
        .limit(1)
        .execute()
    )

    category = (
        get_category_by_name(category_name)
        or get_category_by_name("Belum Dikategorikan")
    )

    if not category:
        raise RuntimeError("Kategori produk tidak ditemukan di Supabase.")

    if existing_response.data:
        existing_product = existing_response.data[0]
        update_payload: dict[str, Any] = {}

        # Jangan mengganti kategori master yang sudah valid hanya karena
        # satu hasil prediksi impor berbeda.
        existing_category_id = existing_product.get("category_id")
        if not existing_category_id:
            update_payload["category_id"] = category["id"]

        if not existing_product.get("default_unit") and unit:
            update_payload["default_unit"] = unit

        if update_payload:
            updated_response = (
                supabase.table("products")
                .update(update_payload)
                .eq("id", existing_product["id"])
                .execute()
            )
            if updated_response.data:
                return updated_response.data[0]
            existing_product.update(update_payload)

        return existing_product

    product_payload = {
        "product_name": description.strip(),
        "normalized_name": normalized_name,
        "category_id": category["id"],
        "default_unit": unit,
        "usage_count": 0,
    }

    created_response = (
        supabase.table("products")
        .insert(product_payload)
        .execute()
    )

    if not created_response.data:
        raise RuntimeError(f"Produk gagal dibuat: {description}")

    return created_response.data[0]


def _cleanup_failed_invoice(invoice_id: str) -> None:
    """Rollback best-effort bila penyimpanan invoice gagal di tengah proses."""
    try:
        supabase.table("price_history").delete().eq(
            "invoice_id", invoice_id
        ).execute()
    except Exception:
        pass

    try:
        supabase.table("invoice_items").delete().eq(
            "invoice_id", invoice_id
        ).execute()
    except Exception:
        pass

    try:
        supabase.table("invoices").delete().eq(
            "id", invoice_id
        ).execute()
    except Exception:
        pass


def save_imported_invoice(
    dataframe: pd.DataFrame,
    invoice_number: str | None = None,
    invoice_date: date | str | None = None,
    vendor_name: str | None = None,
    customer_name: str | None = None,
    target_budget: float | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    if dataframe is None or dataframe.empty:
        raise ValueError("Tidak ada data yang dapat disimpan.")

    required_columns = {
        "raw_description",
        "quantity",
        "unit",
        "unit_price",
        "total_price",
    }

    missing_columns = required_columns - set(dataframe.columns)

    if missing_columns:
        raise ValueError(
            "Kolom wajib belum lengkap: "
            + ", ".join(sorted(missing_columns))
        )

    clean_dataframe = apply_predicted_categories(
        dataframe.copy(),
        overwrite_existing=False,
    )

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

    # Selalu hitung ulang total agar tidak bergantung pada total_price yang salah.
    clean_dataframe["_safe_quantity"] = clean_dataframe["quantity"].apply(
        lambda value: max(_safe_number(value, 1), 1)
    )
    clean_dataframe["_safe_unit_price"] = clean_dataframe["unit_price"].apply(
        lambda value: max(_safe_number(value, 0), 0)
    )
    original_total = float(
        (
            clean_dataframe["_safe_quantity"]
            * clean_dataframe["_safe_unit_price"]
        ).sum()
    )

    source_filename: str | None = None
    input_method = "manual"

    if "source_filename" in clean_dataframe.columns:
        values = (
            clean_dataframe["source_filename"]
            .dropna()
            .astype(str)
            .str.strip()
        )
        values = values[values.ne("")]
        if not values.empty:
            source_filename = values.iloc[0]

    if "input_method" in clean_dataframe.columns:
        values = (
            clean_dataframe["input_method"]
            .dropna()
            .astype(str)
            .str.strip()
        )
        values = values[values.ne("")]
        if not values.empty:
            input_method = values.iloc[0]

    saved_invoice_date = _normalize_invoice_date(invoice_date)

    invoice_payload = {
        "invoice_number": _safe_text(invoice_number) or None,
        "invoice_date": saved_invoice_date,
        "vendor_name": _safe_text(vendor_name) or None,
        "customer_name": _safe_text(customer_name) or None,
        "target_budget": (
            _safe_number(target_budget)
            if target_budget is not None
            else None
        ),
        "original_total": original_total,
        "final_total": original_total,
        "input_method": input_method,
        "source_filename": source_filename,
        "status": "processed",
        "notes": _safe_text(notes) or None,
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

    try:
        for _, row in clean_dataframe.iterrows():
            description = _get_row_description(row)
            if not description:
                continue

            unit = _safe_text(row.get("unit")) or None
            quantity = max(_safe_number(row.get("quantity"), 1), 1)
            unit_price = max(_safe_number(row.get("unit_price"), 0), 0)
            category_data = _get_row_category(row)

            product = _get_or_create_product(
                description=description,
                category_name=category_data["category_name"],
                unit=unit,
            )

            item_payload = {
                "invoice_id": invoice_id,
                "product_id": product["id"],
                "raw_description": description,
                "normalized_description": normalize_text(description),
                "category_id": category_data["category_id"],
                "quantity": quantity,
                "unit": unit,
                "unit_price": unit_price,
                "category_source": category_data["category_source"],
                "category_confidence": category_data["category_confidence"],
                "is_recommended": False,
            }

            item_response = (
                supabase.table("invoice_items")
                .insert(item_payload)
                .execute()
            )

            if not item_response.data:
                raise RuntimeError(f"Item gagal disimpan: {description}")

            invoice_item = item_response.data[0]

            price_payload = {
                "product_id": product["id"],
                "invoice_item_id": invoice_item["id"],
                "vendor_name": _safe_text(vendor_name) or None,
                "unit": unit,
                "quantity": quantity,
                "unit_price": unit_price,
                "recorded_date": saved_invoice_date,
            }

            price_response = (
                supabase.table("price_history")
                .insert(price_payload)
                .execute()
            )

            if not price_response.data:
                raise RuntimeError(
                    f"Riwayat harga gagal disimpan untuk {description}."
                )

            current_usage_count = int(product.get("usage_count") or 0)
            (
                supabase.table("products")
                .update({"usage_count": current_usage_count + 1})
                .eq("id", product["id"])
                .execute()
            )

            saved_items += 1

    except Exception:
        _cleanup_failed_invoice(invoice_id)
        raise

    return {
        "invoice_id": invoice_id,
        "saved_items": saved_items,
        "total": original_total,
    }