from datetime import date
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
    4. Memprediksi ulang kategori seluruh barang.
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

    if dataframe is None:
        dataframe = pd.DataFrame()

    if dataframe.empty:
        dataframe["source_filename"] = pd.Series(dtype="object")
        dataframe["input_method"] = pd.Series(dtype="object")

        return dataframe

    # Kategori dari file lama diprediksi ulang.
    # Contoh:
    # kertas dan amplop menjadi ATK,
    # penutup kepala menjadi APD.
    dataframe = apply_predicted_categories(
        dataframe,
        overwrite_existing=True,
    )

    dataframe["source_filename"] = source_filename
    dataframe["input_method"] = input_method

    return dataframe.reset_index(drop=True)


def _is_empty_value(value: Any) -> bool:
    """Memeriksa apakah nilai kosong, None, NaN, atau hanya spasi."""

    if value is None:
        return True

    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass

    return not str(value).strip()


def _safe_number(
    value: Any,
    default: float = 0,
) -> float:
    """
    Mengubah nilai kosong atau tidak valid menjadi angka aman.

    Mendukung format:
    - 1250000
    - 1.250.000
    - Rp1.250.000
    - 1.250.000,50
    """

    if _is_empty_value(value):
        return default

    if isinstance(value, str):
        cleaned_value = value.strip()

        cleaned_value = (
            cleaned_value
            .replace("Rp", "")
            .replace("rp", "")
            .replace(" ", "")
        )

        if "." in cleaned_value and "," in cleaned_value:
            cleaned_value = (
                cleaned_value
                .replace(".", "")
                .replace(",", ".")
            )

        elif "," in cleaned_value:
            cleaned_value = cleaned_value.replace(",", ".")

        elif "." in cleaned_value:
            parts = cleaned_value.split(".")

            if (
                len(parts) > 1
                and all(part.isdigit() for part in parts)
                and len(parts[-1]) == 3
            ):
                cleaned_value = "".join(parts)

        value = cleaned_value

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_text(
    value: Any,
    default: str = "",
) -> str:
    """Mengubah nilai menjadi teks yang aman."""

    if _is_empty_value(value):
        return default

    return str(value).strip()


def _get_row_description(row: pd.Series) -> str:
    """
    Mengambil uraian barang dari beberapa kemungkinan nama kolom.

    Prioritas:
    1. raw_description
    2. description
    3. product_name
    4. name
    5. item_name
    """

    description_columns = [
        "raw_description",
        "description",
        "product_name",
        "name",
        "item_name",
    ]

    for column_name in description_columns:
        value = row.get(column_name)

        if not _is_empty_value(value):
            return str(value).strip()

    return ""


def _get_row_category(
    row: pd.Series,
) -> dict[str, Any]:
    """
    Menentukan kategori final untuk satu baris barang.

    Prioritas:
    1. Kategori yang sudah ada pada tabel koreksi.
    2. Prediksi otomatis dari uraian barang.
    3. Belum Dikategorikan.
    """

    description = _get_row_description(row)

    category_name = _safe_text(
        row.get("category")
    )

    category_source = _safe_text(
        row.get("category_source")
    )

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
            "matched_keyword": (
                prediction.get("matched_keyword") or ""
            ),
        }

    uncategorized = get_category_by_name(
        "Belum Dikategorikan"
    )

    if not uncategorized:
        raise RuntimeError(
            "Kategori 'Belum Dikategorikan' "
            "tidak ditemukan di Supabase."
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
    """
    Mengambil produk berdasarkan normalized_name.

    Jika produk belum ada, produk baru dibuat.
    Jika produk sudah ada tetapi kategorinya berubah,
    kategori produk akan diperbarui.
    """

    normalized_name = normalize_text(description)

    if not normalized_name:
        raise ValueError(
            "Nama produk tidak boleh kosong."
        )

    existing_response = (
        supabase.table("products")
        .select("*")
        .eq("normalized_name", normalized_name)
        .limit(1)
        .execute()
    )

    category = get_category_by_name(category_name)

    if not category:
        category = get_category_by_name(
            "Belum Dikategorikan"
        )

    if not category:
        raise RuntimeError(
            "Kategori produk tidak ditemukan di Supabase."
        )

    if existing_response.data:
        existing_product = existing_response.data[0]

        update_payload: dict[str, Any] = {}

        if existing_product.get("category_id") != category["id"]:
            update_payload["category_id"] = category["id"]

        if (
            not existing_product.get("default_unit")
            and unit
        ):
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
        raise RuntimeError(
            f"Produk gagal dibuat: {description}"
        )

    return created_response.data[0]


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
    Menyimpan hasil tabel koreksi ke Supabase.

    Kategori yang sudah dikoreksi manual tidak akan ditimpa.
    Barang yang kategorinya masih kosong akan diprediksi otomatis.
    """

    if dataframe is None or dataframe.empty:
        raise ValueError(
            "Tidak ada data yang dapat disimpan."
        )

    required_columns = {
        "raw_description",
        "quantity",
        "unit",
        "unit_price",
        "total_price",
    }

    missing_columns = (
        required_columns - set(dataframe.columns)
    )

    if missing_columns:
        raise ValueError(
            "Kolom wajib belum lengkap: "
            + ", ".join(sorted(missing_columns))
        )

    clean_dataframe = dataframe.copy()

    # Jangan menimpa hasil koreksi manual pengguna.
    clean_dataframe = apply_predicted_categories(
        clean_dataframe,
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
        raise ValueError(
            "Semua uraian barang kosong."
        )

    original_total = float(
        clean_dataframe["total_price"]
        .apply(
            lambda value: _safe_number(
                value,
                default=0,
            )
        )
        .sum()
    )

    source_filename: str | None = None
    input_method = "manual"

    if "source_filename" in clean_dataframe.columns:
        source_values = (
            clean_dataframe["source_filename"]
            .dropna()
            .astype(str)
            .str.strip()
        )

        source_values = source_values[
            source_values.ne("")
        ]

        if not source_values.empty:
            source_filename = source_values.iloc[0]

    if "input_method" in clean_dataframe.columns:
        input_method_values = (
            clean_dataframe["input_method"]
            .dropna()
            .astype(str)
            .str.strip()
        )

        input_method_values = input_method_values[
            input_method_values.ne("")
        ]

        if not input_method_values.empty:
            input_method = input_method_values.iloc[0]

    saved_invoice_date = (
        str(invoice_date)
        if invoice_date
        else str(date.today())
    )

    invoice_payload = {
        "invoice_number": (
            _safe_text(invoice_number) or None
        ),
        "invoice_date": saved_invoice_date,
        "vendor_name": (
            _safe_text(vendor_name) or None
        ),
        "customer_name": (
            _safe_text(customer_name) or None
        ),
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
        raise RuntimeError(
            "Invoice gagal dibuat di Supabase."
        )

    invoice = invoice_response.data[0]
    invoice_id = invoice["id"]

    saved_items = 0

    for _, row in clean_dataframe.iterrows():
        description = _get_row_description(row)

        if not description:
            continue

        unit_text = _safe_text(
            row.get("unit")
        )
        unit = unit_text or None

        quantity = _safe_number(
            row.get("quantity"),
            default=1,
        )

        if quantity <= 0:
            quantity = 1

        unit_price = _safe_number(
            row.get("unit_price"),
            default=0,
        )

        category_data = _get_row_category(row)

        product = _get_or_create_product(
            description=description,
            category_name=category_data[
                "category_name"
            ],
            unit=unit,
        )

        item_payload = {
            "invoice_id": invoice_id,
            "product_id": product["id"],
            "raw_description": description,
            "normalized_description": normalize_text(
                description
            ),
            "category_id": category_data[
                "category_id"
            ],
            "quantity": quantity,
            "unit": unit,
            "unit_price": unit_price,
            "category_source": category_data[
                "category_source"
            ],
            "category_confidence": category_data[
                "category_confidence"
            ],
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
            "vendor_name": (
                _safe_text(vendor_name) or None
            ),
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
                "Riwayat harga gagal disimpan untuk "
                f"{description}."
            )

        current_usage_count = int(
            product.get("usage_count") or 0
        )

        (
            supabase.table("products")
            .update({
                "usage_count": current_usage_count + 1,
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