import re
from typing import Optional

import pandas as pd


# Kolom standar yang digunakan di seluruh INVOXA
STANDARD_COLUMNS = [
    "raw_description",
    "quantity",
    "unit",
    "unit_price",
    "total_price",
    "category",
]


# Berbagai kemungkinan nama kolom dari file Excel/CSV
COLUMN_ALIASES = {
    "raw_description": [
        "uraian",
        "nama barang",
        "nama_barang",
        "barang",
        "deskripsi",
        "description",
        "item",
        "item name",
        "produk",
        "product",
        "jenis barang",
        "rincian",
    ],
    "quantity": [
        "qty",
        "quantity",
        "jumlah barang",
        "banyak",
        "banyaknya",
        "volume",
        "vol",
        "kuantitas",
    ],
    "unit": [
        "satuan",
        "unit",
        "uom",
        "jenis satuan",
    ],
    "unit_price": [
        "harga",
        "harga satuan",
        "harga_satuan",
        "unit price",
        "unit_price",
        "harga unit",
        "harga per unit",
    ],
    "total_price": [
        "jumlah",
        "total",
        "total harga",
        "total_harga",
        "subtotal",
        "nilai",
        "amount",
    ],
    "category": [
        "kategori",
        "category",
        "jenis kategori",
        "kelompok",
        "klasifikasi",
    ],
}


def normalize_column_name(column_name: object) -> str:
    """Membersihkan nama kolom agar lebih mudah dicocokkan."""

    text = str(column_name or "").lower().strip()
    text = re.sub(r"[_\-./]+", " ", text)
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def detect_standard_column(column_name: object) -> Optional[str]:
    """Mendeteksi nama kolom standar dari nama kolom file asal."""

    normalized = normalize_column_name(column_name)

    if not normalized:
        return None

    for standard_name, aliases in COLUMN_ALIASES.items():
        normalized_aliases = {
            normalize_column_name(alias)
            for alias in aliases
        }

        if normalized in normalized_aliases:
            return standard_name

    return None


def build_column_mapping(columns: list[object]) -> dict[object, str]:
    """Membuat pemetaan kolom asli ke kolom standar INVOXA."""

    mapping: dict[object, str] = {}
    used_standard_columns: set[str] = set()

    for original_column in columns:
        standard_column = detect_standard_column(original_column)

        if (
            standard_column
            and standard_column not in used_standard_columns
        ):
            mapping[original_column] = standard_column
            used_standard_columns.add(standard_column)

    return mapping


def clean_numeric_value(value: object) -> float | None:
    """
    Membersihkan angka dari format rupiah atau pemisah ribuan.

    Contoh:
    Rp15.000   -> 15000
    15,000     -> 15000
    15000      -> 15000
    """

    if value is None or pd.isna(value):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()

    if not text:
        return None

    text = re.sub(r"(?i)rp", "", text)
    text = re.sub(r"\s+", "", text)

    # Jika terdapat titik dan koma, anggap pemisah terakhir sebagai desimal
    if "." in text and "," in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "")
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")

    # Format Indonesia: 15.000
    elif "." in text:
        parts = text.split(".")

        if all(part.isdigit() for part in parts) and len(parts[-1]) == 3:
            text = "".join(parts)

    # Format 15,000 atau angka desimal dengan koma
    elif "," in text:
        parts = text.split(",")

        if all(part.isdigit() for part in parts) and len(parts[-1]) == 3:
            text = "".join(parts)
        else:
            text = text.replace(",", ".")

    text = re.sub(r"[^0-9.\-]", "", text)

    if not text:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def standardize_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    """
    Mengubah data dari Excel/CSV ke format standar INVOXA.

    Total harga otomatis dihitung dari quantity × unit_price
    jika total_price belum tersedia.
    """

    if dataframe is None or dataframe.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    dataframe = dataframe.copy()

    # Samakan nama kolom
    mapping = build_column_mapping(list(dataframe.columns))
    dataframe = dataframe.rename(columns=mapping)

    # Tambahkan kolom standar yang belum tersedia
    for column in STANDARD_COLUMNS:
        if column not in dataframe.columns:
            dataframe[column] = None

    # Hapus baris yang seluruh isinya kosong
    dataframe = dataframe.dropna(how="all")

    # Bersihkan uraian barang
    dataframe["raw_description"] = (
        dataframe["raw_description"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    # Hapus baris tanpa nama atau uraian barang
    dataframe = dataframe[
        dataframe["raw_description"].ne("")
    ].copy()

    # Bersihkan nilai numerik
    for column in ["quantity", "unit_price", "total_price"]:
        dataframe[column] = dataframe[column].apply(
            clean_numeric_value
        )

    # Quantity default 1 jika kosong
    dataframe["quantity"] = dataframe["quantity"].fillna(1)

    # Hitung total otomatis jika total kosong
    missing_total = dataframe["total_price"].isna()

    dataframe.loc[missing_total, "total_price"] = (
        dataframe.loc[missing_total, "quantity"]
        * dataframe.loc[missing_total, "unit_price"]
    )

    # Susun kolom standar di bagian depan
    ordered_columns = STANDARD_COLUMNS + [
        column
        for column in dataframe.columns
        if column not in STANDARD_COLUMNS
    ]

    return dataframe[ordered_columns].reset_index(drop=True)