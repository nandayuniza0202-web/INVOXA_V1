from __future__ import annotations

import hashlib
import io
import re
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytesseract
import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from services.category_service import apply_predicted_categories
from services.import_service import (
    import_tabular_file,
    save_imported_invoice,
)


# =========================================================
# KONFIGURASI HALAMAN
# =========================================================

st.set_page_config(
    page_title="Input Nota",
    page_icon="🧾",
    layout="wide",
)


# =========================================================
# DATA PELANGGAN
# =========================================================

CUSTOMERS: dict[str, str] = {
    "SPPG Enrekang-Enrekang Juppandang": (
        "Jl. Emmy Saelan No. 29, Kelurahan Juppandang, "
        "Kecamatan Enrekang, Kabupaten Enrekang, "
        "Sulawesi Selatan"
    ),
    "SPPG Bubun Lamba Anggeraja": (
        "Jl. Negara No. 8, Desa Bubun Lamba, "
        "Kecamatan Anggeraja, Kabupaten Enrekang, "
        "Sulawesi Selatan"
    ),
    "SPPG Bangkala Maiwa 002": (
        "Jl. Dr. Ratulangi No. 56, Kelurahan Maroangin, "
        "Kecamatan Maiwa, Kabupaten Enrekang, "
        "Sulawesi Selatan"
    ),
    "SPPG BIRING ROMANG, MANGGALA #001": (
        "Jalan Geologi No. D1, Kelurahan Biring Romang, "
        "Kecamatan Manggala, Kota Makassar, "
        "Provinsi Sulawesi Selatan"
    ),
    "SPPG BIRING ROMANG, MANGGALA #002": (
        "Jalan Sipil Raya No. D2-D3, Kelurahan Biring Romang, "
        "Kecamatan Manggala, Kota Makassar, "
        "Provinsi Sulawesi Selatan"
    ),
    "SPPG KAMBIOLANGI, ALLA 001": (
        "Jl. Belajen Utara, Kelurahan Kambiolangi, "
        "Kecamatan Alla, Kabupaten Enrekang, "
        "Provinsi Sulawesi Selatan"
    ),
    "SPPG KATANGKA, SOMBA OPU #001": (
        "Jalan Syekh Yusuf No. 54 B, Kelurahan Katangka, "
        "Kecamatan Somba Opu, Kabupaten Gowa, "
        "Provinsi Sulawesi Selatan"
    ),
    "SPPG KATANGKA, SOMBA OPU #002": (
        "Jalan Syekh Yusuf No. 54 C, Kelurahan Katangka, "
        "Kecamatan Somba Opu, Kabupaten Gowa, "
        "Provinsi Sulawesi Selatan"
    ),
}

MANUAL_CUSTOMER_OPTION = "✍️ Isi Manual"


# =========================================================
# KONSTANTA
# =========================================================

CATEGORIES = [
    "Belum Dikategorikan",
    "ATK",
    "APD",
    "Alat Kebersihan",
    "Alat Kelengkapan",
]

UNITS = [
    "pcs",
    "buah",
    "unit",
    "set",
    "pak",
    "pack",
    "box",
    "dos",
    "lusin",
    "rim",
    "roll",
    "botol",
    "liter",
    "ml",
    "kg",
    "gram",
    "meter",
    "cm",
    "lembar",
    "pasang",
    "bungkus",
    "bal",
]

COLUMNS = [
    "Uraian",
    "Kuantitas",
    "Satuan",
    "Harga",
    "Jumlah",
    "Kategori",
    "Nama Nota",
    "Kunci",
]


# =========================================================
# FUNGSI UMUM
# =========================================================

def numeric_value(value: Any) -> float:
    """Mengubah berbagai format angka Indonesia menjadi float."""

    if value is None:
        return 0.0

    if isinstance(value, bool):
        return float(value)

    if isinstance(value, (int, float)):
        if pd.isna(value):
            return 0.0

        return float(value)

    text = str(value).strip()

    if not text:
        return 0.0

    text = (
        text.replace("Rp", "")
        .replace("rp", "")
        .replace("IDR", "")
        .replace("idr", "")
        .replace(" ", "")
    )

    if "." in text and "," in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")

    elif "," in text:
        parts = text.split(",")

        if len(parts[-1]) in (1, 2):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")

    elif "." in text:
        parts = text.split(".")

        if (
            len(parts) > 1
            and all(len(part) == 3 for part in parts[1:])
        ):
            text = text.replace(".", "")

    text = re.sub(r"[^0-9.\-]", "", text)

    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def rupiah(value: Any) -> str:
    """Mengubah angka menjadi format rupiah."""

    return f"Rp{numeric_value(value):,.0f}".replace(",", ".")


def empty_dataframe(rows: int = 1) -> pd.DataFrame:
    """Membuat DataFrame kosong dengan struktur tabel INVOXA."""

    return pd.DataFrame(
        [
            {
                "Uraian": "",
                "Kuantitas": 1.0,
                "Satuan": "pcs",
                "Harga": 0.0,
                "Jumlah": 0.0,
                "Kategori": "Belum Dikategorikan",
                "Nama Nota": "",
                "Kunci": False,
            }
            for _ in range(max(rows, 0))
        ],
        columns=COLUMNS,
    )


def prepare_dataframe(data: Any) -> pd.DataFrame:
    """Menormalkan data agar selalu mempunyai kolom INVOXA."""

    if data is None:
        return empty_dataframe()

    try:
        if isinstance(data, pd.DataFrame):
            df = data.copy()
        else:
            df = pd.DataFrame(data)

    except Exception:
        return empty_dataframe()

    defaults = {
        "Uraian": "",
        "Kuantitas": 1.0,
        "Satuan": "pcs",
        "Harga": 0.0,
        "Jumlah": 0.0,
        "Kategori": "Belum Dikategorikan",
        "Nama Nota": "",
        "Kunci": False,
    }

    for column, default in defaults.items():
        if column not in df.columns:
            df[column] = default

    df = df[COLUMNS].copy()

    df["Uraian"] = (
        df["Uraian"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    df["Satuan"] = (
        df["Satuan"]
        .fillna("pcs")
        .astype(str)
        .str.lower()
        .str.strip()
    )

    df["Kategori"] = (
        df["Kategori"]
        .fillna("Belum Dikategorikan")
        .astype(str)
        .str.strip()
    )

    df["Nama Nota"] = (
        df["Nama Nota"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    df["Kunci"] = (
        df["Kunci"]
        .fillna(False)
        .astype(bool)
    )

    for column in ["Kuantitas", "Harga", "Jumlah"]:
        df[column] = df[column].apply(numeric_value)

    df.loc[
        df["Kuantitas"] <= 0,
        "Kuantitas",
    ] = 1.0

    df.loc[
        ~df["Satuan"].isin(UNITS),
        "Satuan",
    ] = "pcs"

    df.loc[
        ~df["Kategori"].isin(CATEGORIES),
        "Kategori",
    ] = "Belum Dikategorikan"

    return df.reset_index(drop=True)


def dataframe_changed(
    old: pd.DataFrame,
    new: pd.DataFrame,
) -> bool:
    """Memeriksa apakah tabel editor mengalami perubahan."""

    old_normalized = prepare_dataframe(old)
    new_normalized = prepare_dataframe(new)

    return (
        old_normalized.shape != new_normalized.shape
        or not old_normalized.equals(new_normalized)
    )


def changed_number(
    old: Any,
    new: Any,
    tolerance: float = 0.01,
) -> bool:
    """Memeriksa perubahan nilai angka."""

    return (
        abs(
            numeric_value(old)
            - numeric_value(new)
        )
        > tolerance
    )


def synchronize_dataframe(
    previous: pd.DataFrame,
    edited: pd.DataFrame,
) -> pd.DataFrame:
    """Sinkronisasi Kuantitas, Harga, dan Jumlah dua arah."""

    old_df = prepare_dataframe(previous)
    new_df = prepare_dataframe(edited)

    for index in new_df.index:
        quantity = max(
            numeric_value(
                new_df.at[index, "Kuantitas"]
            ),
            1.0,
        )

        price = numeric_value(
            new_df.at[index, "Harga"]
        )

        total = numeric_value(
            new_df.at[index, "Jumlah"]
        )

        new_df.at[index, "Kuantitas"] = quantity

        if index < len(old_df):
            quantity_changed = changed_number(
                old_df.at[index, "Kuantitas"],
                quantity,
            )

            price_changed = changed_number(
                old_df.at[index, "Harga"],
                price,
            )

            total_changed = changed_number(
                old_df.at[index, "Jumlah"],
                total,
            )

        else:
            quantity_changed = True
            price_changed = price > 0
            total_changed = total > 0

        if price_changed and not total_changed:
            new_df.at[index, "Jumlah"] = (
                quantity * price
            )

        elif total_changed and not price_changed:
            new_df.at[index, "Harga"] = (
                total / quantity
            )

        elif price_changed and total_changed:
            if total > 0:
                new_df.at[index, "Harga"] = (
                    total / quantity
                )

            elif price > 0:
                new_df.at[index, "Jumlah"] = (
                    quantity * price
                )

        elif quantity_changed:
            if price > 0:
                new_df.at[index, "Jumlah"] = (
                    quantity * price
                )

            elif total > 0:
                new_df.at[index, "Harga"] = (
                    total / quantity
                )

        else:
            if price <= 0 and total > 0:
                new_df.at[index, "Harga"] = (
                    total / quantity
                )

            elif total <= 0 and price > 0:
                new_df.at[index, "Jumlah"] = (
                    quantity * price
                )

    new_df["Harga"] = (
        new_df["Harga"]
        .apply(numeric_value)
        .round(0)
    )

    new_df["Jumlah"] = (
        new_df["Jumlah"]
        .apply(numeric_value)
        .round(0)
    )

    return prepare_dataframe(new_df)


def append_rows(rows: pd.DataFrame) -> None:
    """Menambahkan baris ke tabel koreksi."""

    rows = prepare_dataframe(rows)
    current = prepare_dataframe(
        st.session_state.input_table
    )

    if (
        len(current) == 1
        and not current.at[0, "Uraian"].strip()
        and numeric_value(
            current.at[0, "Harga"]
        ) == 0
        and numeric_value(
            current.at[0, "Jumlah"]
        ) == 0
    ):
        current = current.iloc[0:0]

    st.session_state.input_table = prepare_dataframe(
        pd.concat(
            [current, rows],
            ignore_index=True,
        )
    )

    st.session_state.input_editor_version += 1


def replace_rows(rows: pd.DataFrame) -> None:
    """Mengganti seluruh tabel koreksi."""

    st.session_state.input_table = (
        prepare_dataframe(rows)
    )

    st.session_state.input_editor_version += 1


def service_dataframe_to_ui(
    dataframe: pd.DataFrame,
    note_name: str = "",
) -> pd.DataFrame:
    """Mengubah DataFrame service ke tabel halaman Input Nota."""

    if dataframe is None or dataframe.empty:
        return empty_dataframe(0)

    source = dataframe.copy()

    result = pd.DataFrame(
        {
            "Uraian": source.get(
                "raw_description",
                "",
            ),
            "Kuantitas": source.get(
                "quantity",
                1,
            ),
            "Satuan": source.get(
                "unit",
                "pcs",
            ),
            "Harga": source.get(
                "unit_price",
                0,
            ),
            "Jumlah": source.get(
                "total_price",
                0,
            ),
            "Kategori": source.get(
                "category",
                "Belum Dikategorikan",
            ),
            "Nama Nota": note_name,
            "Kunci": False,
        }
    )

    if "source_filename" in source.columns:
        source_names = (
            source["source_filename"]
            .fillna("")
            .astype(str)
        )

        result["Nama Nota"] = source_names.apply(
            lambda value: (
                Path(value).stem
                if value
                else note_name
            )
        )

    return prepare_dataframe(result)


def ui_dataframe_to_service(
    dataframe: pd.DataFrame,
    input_method: str,
) -> pd.DataFrame:
    """Mengubah tabel editor ke format import_service."""

    df = prepare_dataframe(dataframe)

    return pd.DataFrame(
        {
            "raw_description": df["Uraian"],
            "quantity": df["Kuantitas"],
            "unit": df["Satuan"],
            "unit_price": df["Harga"],
            "total_price": df["Jumlah"],
            "category": df["Kategori"],
            "source_filename": df["Nama Nota"],
            "input_method": input_method,
        }
    )


# =========================================================
# OCR FOTO DAN PDF
# =========================================================

def file_hash(file_bytes: bytes) -> str:
    """Menghasilkan hash file."""

    return hashlib.sha256(file_bytes).hexdigest()


def preprocess_image(
    image: Image.Image,
) -> Image.Image:
    """Menyiapkan gambar agar lebih mudah dibaca OCR."""

    image = ImageOps.exif_transpose(
        image
    ).convert("L")

    image = ImageOps.autocontrast(image)

    image = ImageEnhance.Contrast(
        image
    ).enhance(1.8)

    image = image.filter(
        ImageFilter.SHARPEN
    )

    width, height = image.size

    if width < 1600:
        ratio = 1600 / max(width, 1)

        image = image.resize(
            (
                int(width * ratio),
                int(height * ratio),
            )
        )

    return image


def clean_ocr_text(text: str) -> str:
    """Membersihkan kesalahan umum hasil OCR."""

    replacements = {
        "O": "0",
        "o": "0",
        "I": "1",
        "l": "1",
    }

    tokens = []

    for token in text.split():
        digit_count = sum(
            character.isdigit()
            for character in token
        )

        if digit_count >= max(
            1,
            len(token) // 2,
        ):
            for old, new in replacements.items():
                token = token.replace(
                    old,
                    new,
                )

        tokens.append(token)

    return " ".join(tokens)


def extract_money_values(
    line: str,
) -> list[float]:
    """Mengambil angka harga dari satu baris OCR."""

    patterns = re.findall(
        r"(?:Rp\s*)?\d{1,3}"
        r"(?:[.\s]\d{3})+"
        r"(?:,\d{1,2})?"
        r"|(?:Rp\s*)?\d{4,}"
        r"(?:,\d{1,2})?",
        line,
        flags=re.IGNORECASE,
    )

    return [
        numeric_value(value)
        for value in patterns
        if numeric_value(value) > 0
    ]


def detect_quantity_and_unit(
    line: str,
) -> tuple[float, str]:
    """Mendeteksi kuantitas dan satuan pada baris OCR."""

    unit_pattern = "|".join(
        re.escape(unit)
        for unit in UNITS
    )

    first = re.search(
        rf"\b(\d+(?:[.,]\d+)?)"
        rf"\s*({unit_pattern})\b",
        line,
        flags=re.IGNORECASE,
    )

    if first:
        return (
            numeric_value(first.group(1)),
            first.group(2).lower(),
        )

    second = re.search(
        rf"\b({unit_pattern})"
        rf"\s*(\d+(?:[.,]\d+)?)\b",
        line,
        flags=re.IGNORECASE,
    )

    if second:
        return (
            numeric_value(second.group(2)),
            second.group(1).lower(),
        )

    beginning = re.match(
        r"^\s*(\d+(?:[.,]\d+)?)\s+",
        line,
    )

    if beginning:
        quantity = numeric_value(
            beginning.group(1)
        )

        if 0 < quantity <= 10000:
            return quantity, "pcs"

    return 1.0, "pcs"


def remove_price_and_quantity_from_description(
    line: str,
    quantity: float,
    unit: str,
) -> str:
    """Membersihkan angka dan satuan dari uraian OCR."""

    description = re.sub(
        r"(?:Rp\s*)?\d{1,3}"
        r"(?:[.\s]\d{3})+"
        r"(?:,\d{1,2})?"
        r"|(?:Rp\s*)?\d{4,}"
        r"(?:,\d{1,2})?",
        " ",
        line,
        flags=re.IGNORECASE,
    )

    quantity_text = (
        str(int(quantity))
        if float(quantity).is_integer()
        else str(quantity)
    )

    description = re.sub(
        rf"^\s*{re.escape(quantity_text)}\s*",
        " ",
        description,
        count=1,
    )

    if unit:
        description = re.sub(
            rf"\b{re.escape(unit)}\b",
            " ",
            description,
            flags=re.IGNORECASE,
        )

    return re.sub(
        r"\s+",
        " ",
        description,
    ).strip(" -:|")


def should_skip_ocr_line(line: str) -> bool:
    """Memeriksa apakah baris OCR harus diabaikan."""

    normalized = line.lower().strip()

    if len(normalized) < 3:
        return True

    skip_words = [
        "total",
        "subtotal",
        "grand total",
        "tunai",
        "cash",
        "kembali",
        "change",
        "terima kasih",
        "thank you",
        "ppn",
        "pajak",
        "kasir",
        "tanggal",
        "no bukti",
        "saldo",
        "debit",
        "kredit",
    ]

    return any(
        word in normalized
        for word in skip_words
    )


def parse_ocr_text(
    text: str,
    note_name: str,
) -> pd.DataFrame:
    """Mengubah teks OCR menjadi tabel INVOXA."""

    rows = []

    for raw_line in text.splitlines():
        line = clean_ocr_text(
            raw_line
        ).strip()

        if should_skip_ocr_line(line):
            continue

        money_values = extract_money_values(
            line
        )

        if not money_values:
            continue

        quantity, unit = (
            detect_quantity_and_unit(line)
        )

        quantity = max(
            quantity,
            1.0,
        )

        if len(money_values) >= 2:
            price = money_values[-2]
            total = money_values[-1]
            expected = quantity * price

            if (
                expected > 0
                and abs(total - expected)
                / expected
                > 0.25
            ):
                price = total / quantity

        else:
            total = money_values[-1]
            price = total / quantity

        description = (
            remove_price_and_quantity_from_description(
                line,
                float(quantity),
                unit,
            )
            or "Perlu dikoreksi"
        )

        rows.append(
            {
                "Uraian": description,
                "Kuantitas": quantity,
                "Satuan": (
                    unit
                    if unit in UNITS
                    else "pcs"
                ),
                "Harga": price,
                "Jumlah": total,
                "Kategori": "Belum Dikategorikan",
                "Nama Nota": note_name,
                "Kunci": False,
            }
        )

    if not rows:
        return empty_dataframe(0)

    ui_dataframe = prepare_dataframe(rows)

    predicted = apply_predicted_categories(
        ui_dataframe_to_service(
            ui_dataframe,
            "ocr",
        ),
        overwrite_existing=True,
    )

    return service_dataframe_to_ui(
        predicted,
        note_name=note_name,
    )


def run_ocr(image: Image.Image) -> str:
    """Menjalankan OCR terhadap gambar."""

    processed = preprocess_image(image)
    outputs = []

    for config in [
        "--oem 3 --psm 6",
        "--oem 3 --psm 4",
    ]:
        try:
            outputs.append(
                pytesseract.image_to_string(
                    processed,
                    lang="eng",
                    config=config,
                )
            )

        except pytesseract.TesseractNotFoundError:
            raise

        except Exception:
            continue

    if not outputs:
        return ""

    return max(
        outputs,
        key=lambda value: len(
            value.strip()
        ),
    )


def pdf_pages_to_images(
    file_bytes: bytes,
) -> list[Image.Image]:
    """Mengubah halaman PDF menjadi gambar."""

    try:
        import fitz  # type: ignore

    except ImportError as error:
        raise RuntimeError(
            "Pembaca PDF belum terpasang. "
            "Jalankan: pip install pymupdf"
        ) from error

    document = fitz.open(
        stream=file_bytes,
        filetype="pdf",
    )

    images: list[Image.Image] = []

    for page in document:
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(2, 2),
            alpha=False,
        )

        image = Image.open(
            io.BytesIO(
                pixmap.tobytes("png")
            )
        )

        images.append(image)

    document.close()

    return images


# =========================================================
# SESSION STATE
# =========================================================

SESSION_DEFAULTS = {
    "invoice_items": [],
    "input_table": empty_dataframe(),
    "customer_choice": (
        list(CUSTOMERS.keys())[0]
    ),
    "customer_name": (
        list(CUSTOMERS.keys())[0]
    ),
    "customer_address": (
        list(CUSTOMERS.values())[0]
    ),
    "manual_customer_name": "",
    "manual_customer_address": "",
    "invoice_period": "",
    "invoice_number": "",
    "vendor_name": "",
    "selected_template": "",
    "ocr_cache": {},
    "input_editor_version": 0,
    "last_input_method": "manual",
    "current_invoice_id": None,
    "invoice_id": None,
    "saved_invoice_id": None,
}

for key, default in SESSION_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default


# =========================================================
# TAMPILAN UTAMA
# =========================================================

st.title("🧾 Input Nota")

st.caption(
    "Masukkan data dari Excel, CSV, PDF, foto, "
    "atau secara manual. Semua hasil dapat diperbaiki "
    "sebelum disimpan."
)

st.divider()
st.subheader("1. Data Invoice")


# =========================================================
# PILIH PELANGGAN DAN ALAMAT
# =========================================================

customer_options = [
    *CUSTOMERS.keys(),
    MANUAL_CUSTOMER_OPTION,
]

current_choice = (
    st.session_state.customer_choice
)

if current_choice not in customer_options:
    current_choice = customer_options[0]

customer_choice = st.selectbox(
    "Pilih Pelanggan",
    options=customer_options,
    index=customer_options.index(
        current_choice
    ),
)

st.session_state.customer_choice = (
    customer_choice
)

if customer_choice == MANUAL_CUSTOMER_OPTION:
    customer_col, address_col = st.columns(2)

    with customer_col:
        manual_customer_name = st.text_input(
            "Nama Pelanggan",
            value=(
                st.session_state
                .manual_customer_name
            ),
            placeholder=(
                "Masukkan nama pelanggan"
            ),
        )

    with address_col:
        manual_customer_address = st.text_area(
            "Alamat Pelanggan",
            value=(
                st.session_state
                .manual_customer_address
            ),
            placeholder=(
                "Masukkan alamat lengkap pelanggan"
            ),
            height=100,
        )

    st.session_state.manual_customer_name = (
        manual_customer_name
    )

    st.session_state.manual_customer_address = (
        manual_customer_address
    )

    st.session_state.customer_name = (
        manual_customer_name.strip()
    )

    st.session_state.customer_address = (
        manual_customer_address.strip()
    )

else:
    selected_address = CUSTOMERS[
        customer_choice
    ]

    st.session_state.customer_name = (
        customer_choice
    )

    st.session_state.customer_address = (
        selected_address
    )

    st.text_input(
        "Nama Pelanggan",
        value=customer_choice,
        disabled=True,
    )

    st.text_area(
        "Alamat Pelanggan",
        value=selected_address,
        disabled=True,
        height=100,
    )


period_col, number_col, vendor_col = (
    st.columns(3)
)

with period_col:
    st.session_state.invoice_period = (
        st.text_input(
            "Periode",
            value=(
                st.session_state
                .invoice_period
            ),
            placeholder="Contoh: Juli 2026",
        )
    )

with number_col:
    st.session_state.invoice_number = (
        st.text_input(
            "Nomor Invoice",
            value=(
                st.session_state
                .invoice_number
            ),
            placeholder="Boleh dikosongkan",
        )
    )

with vendor_col:
    st.session_state.vendor_name = (
        st.text_input(
            "Nama Vendor/Toko",
            value=(
                st.session_state
                .vendor_name
            ),
            placeholder="Boleh dikosongkan",
        )
    )


# =========================================================
# TEMPLATE WORD
# =========================================================

st.divider()
st.subheader("2. Template Invoice")

project_root = (
    Path(__file__)
    .resolve()
    .parents[1]
)

template_folder = (
    project_root
    / "templates"
)

template_folder.mkdir(
    parents=True,
    exist_ok=True,
)

template_files = sorted(
    template_folder.glob("*.docx")
)

if template_files:
    template_names = [
        template.name
        for template in template_files
    ]

    previous_name = (
        Path(
            st.session_state
            .selected_template
        ).name
        if st.session_state
        .selected_template
        else ""
    )

    selected_index = (
        template_names.index(previous_name)
        if previous_name in template_names
        else 0
    )

    selected_template_name = st.selectbox(
        "Pilih Template Word",
        options=template_names,
        index=selected_index,
    )

    st.session_state.selected_template = str(
        template_folder
        / selected_template_name
    )

    st.success(
        f"Template aktif: "
        f"{selected_template_name}"
    )

else:
    st.warning(
        "Belum ada template Word di folder "
        f"`{template_folder}`."
    )


# =========================================================
# PILIH METODE INPUT
# =========================================================

st.divider()
st.subheader("3. Masukkan Data")

method = st.radio(
    "Metode Input",
    options=[
        "📊 Excel / CSV",
        "📄 PDF",
        "📷 Foto OCR",
        "⌨️ Manual",
    ],
    horizontal=True,
)


# =========================================================
# EXCEL / CSV
# =========================================================

if method == "📊 Excel / CSV":
    uploaded_file = st.file_uploader(
        "Pilih file Excel atau CSV",
        type=[
            "xlsx",
            "xls",
            "xlsm",
            "csv",
        ],
    )

    if uploaded_file is not None:
        try:
            with st.spinner(
                "Membaca dan menyesuaikan data..."
            ):
                parsed = import_tabular_file(
                    uploaded_file,
                    filename=uploaded_file.name,
                )

                mapped = (
                    service_dataframe_to_ui(
                        parsed,
                        note_name=Path(
                            uploaded_file.name
                        ).stem,
                    )
                )

            st.dataframe(
                mapped,
                hide_index=True,
                use_container_width=True,
            )

            action_1, action_2 = (
                st.columns(2)
            )

            with action_1:
                if st.button(
                    "➕ Tambahkan ke Tabel Koreksi",
                    type="primary",
                    use_container_width=True,
                ):
                    append_rows(mapped)

                    st.session_state.last_input_method = (
                        "excel"
                        if uploaded_file.name
                        .lower()
                        .endswith(
                            (
                                ".xlsx",
                                ".xls",
                                ".xlsm",
                            )
                        )
                        else "import"
                    )

                    st.rerun()

            with action_2:
                if st.button(
                    "♻️ Ganti Tabel",
                    use_container_width=True,
                ):
                    replace_rows(mapped)

                    st.session_state.last_input_method = (
                        "excel"
                        if uploaded_file.name
                        .lower()
                        .endswith(
                            (
                                ".xlsx",
                                ".xls",
                                ".xlsm",
                            )
                        )
                        else "import"
                    )

                    st.rerun()

        except Exception as error:
            st.error(
                f"File gagal dibaca: {error}"
            )


# =========================================================
# PDF
# =========================================================

elif method == "📄 PDF":
    uploaded_pdf = st.file_uploader(
        "Pilih file PDF",
        type=["pdf"],
    )

    if uploaded_pdf is not None:
        pdf_bytes = uploaded_pdf.getvalue()
        digest = file_hash(pdf_bytes)

        if st.button(
            "🔍 Baca PDF",
            type="primary",
            use_container_width=True,
        ):
            try:
                all_rows = []

                with st.spinner(
                    "Membaca halaman PDF..."
                ):
                    pages = pdf_pages_to_images(
                        pdf_bytes
                    )

                    for (
                        page_number,
                        image,
                    ) in enumerate(
                        pages,
                        start=1,
                    ):
                        raw_text = run_ocr(
                            image
                        )

                        rows = parse_ocr_text(
                            raw_text,
                            (
                                f"{Path(uploaded_pdf.name).stem} "
                                f"- Halaman {page_number}"
                            ),
                        )

                        if not rows.empty:
                            all_rows.append(
                                rows
                            )

                combined = (
                    pd.concat(
                        all_rows,
                        ignore_index=True,
                    )
                    if all_rows
                    else empty_dataframe(0)
                )

                st.session_state.ocr_cache[
                    f"pdf_{digest}"
                ] = combined.to_dict(
                    "records"
                )

            except Exception as error:
                st.error(
                    f"PDF gagal dibaca: {error}"
                )

        cached_pdf_rows = (
            st.session_state.ocr_cache.get(
                f"pdf_{digest}",
                [],
            )
        )

        if cached_pdf_rows:
            pdf_rows = prepare_dataframe(
                cached_pdf_rows
            )

            st.dataframe(
                pdf_rows,
                hide_index=True,
                use_container_width=True,
            )

            pdf_action_1, pdf_action_2 = (
                st.columns(2)
            )

            with pdf_action_1:
                if st.button(
                    "➕ Tambahkan PDF ke Tabel",
                    type="primary",
                    use_container_width=True,
                ):
                    append_rows(pdf_rows)

                    st.session_state.last_input_method = (
                        "pdf"
                    )

                    st.rerun()

            with pdf_action_2:
                if st.button(
                    "♻️ Ganti Tabel dengan PDF",
                    use_container_width=True,
                ):
                    replace_rows(pdf_rows)

                    st.session_state.last_input_method = (
                        "pdf"
                    )

                    st.rerun()


# =========================================================
# FOTO OCR
# =========================================================

elif method == "📷 Foto OCR":
    uploaded_images = st.file_uploader(
        "Pilih satu atau beberapa foto",
        type=[
            "png",
            "jpg",
            "jpeg",
            "webp",
        ],
        accept_multiple_files=True,
    )

    if uploaded_images:
        all_ocr_rows = []

        for (
            image_number,
            uploaded_image,
        ) in enumerate(
            uploaded_images,
            start=1,
        ):
            image_bytes = (
                uploaded_image.getvalue()
            )

            image = Image.open(
                io.BytesIO(image_bytes)
            )

            digest = file_hash(
                image_bytes
            )

            note_name = st.text_input(
                f"Nama Nota Foto "
                f"{image_number}",
                value=Path(
                    uploaded_image.name
                ).stem,
                key=f"ocr_note_{digest}",
            )

            st.image(
                image,
                caption=uploaded_image.name,
                use_container_width=True,
            )

            if st.button(
                f"🔍 Baca Foto "
                f"{image_number}",
                key=f"ocr_button_{digest}",
                use_container_width=True,
            ):
                try:
                    with st.spinner(
                        f"Membaca "
                        f"{uploaded_image.name}..."
                    ):
                        raw_text = run_ocr(
                            image
                        )

                        parsed_rows = (
                            parse_ocr_text(
                                raw_text,
                                note_name,
                            )
                        )

                        st.session_state.ocr_cache[
                            f"{digest}_rows"
                        ] = parsed_rows.to_dict(
                            "records"
                        )

                except (
                    pytesseract
                    .TesseractNotFoundError
                ):
                    st.error(
                        "Tesseract belum terpasang. "
                        "Jalankan: "
                        "brew install tesseract"
                    )

                except Exception as error:
                    st.error(
                        f"OCR gagal: {error}"
                    )

            cached_rows = (
                st.session_state
                .ocr_cache
                .get(
                    f"{digest}_rows",
                    [],
                )
            )

            if cached_rows:
                parsed_rows = (
                    prepare_dataframe(
                        cached_rows
                    )
                )

                parsed_rows[
                    "Nama Nota"
                ] = note_name

                st.dataframe(
                    parsed_rows,
                    hide_index=True,
                    use_container_width=True,
                )

                all_ocr_rows.append(
                    parsed_rows
                )

            st.divider()

        if all_ocr_rows:
            combined_ocr_rows = pd.concat(
                all_ocr_rows,
                ignore_index=True,
            )

            action_1, action_2 = (
                st.columns(2)
            )

            with action_1:
                if st.button(
                    "➕ Tambahkan Hasil OCR",
                    type="primary",
                    use_container_width=True,
                ):
                    append_rows(
                        combined_ocr_rows
                    )

                    st.session_state.last_input_method = (
                        "ocr"
                    )

                    st.rerun()

            with action_2:
                if st.button(
                    "♻️ Ganti Tabel dengan OCR",
                    use_container_width=True,
                ):
                    replace_rows(
                        combined_ocr_rows
                    )

                    st.session_state.last_input_method = (
                        "ocr"
                    )

                    st.rerun()


# =========================================================
# MANUAL
# =========================================================

elif method == "⌨️ Manual":
    with st.form(
        "manual_input_form",
        clear_on_submit=True,
    ):
        left, right = st.columns(2)

        with left:
            manual_description = (
                st.text_input(
                    "Uraian Barang"
                )
            )

            manual_quantity = (
                st.number_input(
                    "Kuantitas",
                    min_value=0.01,
                    value=1.0,
                    step=1.0,
                )
            )

            manual_unit = st.selectbox(
                "Satuan",
                options=UNITS,
            )

            manual_category = (
                st.selectbox(
                    "Kategori",
                    options=CATEGORIES,
                )
            )

        with right:
            manual_price = (
                st.number_input(
                    "Harga Satuan",
                    min_value=0.0,
                    value=0.0,
                    step=1000.0,
                )
            )

            manual_total = (
                st.number_input(
                    "Jumlah",
                    min_value=0.0,
                    value=0.0,
                    step=1000.0,
                )
            )

            manual_note_name = (
                st.text_input(
                    "Nama Nota"
                )
            )

            manual_lock = st.checkbox(
                "Kunci Harga",
                value=False,
            )

        submitted = (
            st.form_submit_button(
                "➕ Tambahkan ke Tabel",
                type="primary",
                use_container_width=True,
            )
        )

        if submitted:
            if not manual_description.strip():
                st.error(
                    "Uraian barang wajib diisi."
                )

            elif (
                manual_price <= 0
                and manual_total <= 0
            ):
                st.error(
                    "Isi Harga Satuan atau Jumlah."
                )

            else:
                quantity = max(
                    numeric_value(
                        manual_quantity
                    ),
                    1,
                )

                price = numeric_value(
                    manual_price
                )

                total = numeric_value(
                    manual_total
                )

                if price > 0:
                    total = (
                        quantity * price
                    )

                else:
                    price = (
                        total / quantity
                    )

                manual_row = pd.DataFrame(
                    [
                        {
                            "Uraian": (
                                manual_description
                                .strip()
                            ),
                            "Kuantitas": quantity,
                            "Satuan": manual_unit,
                            "Harga": price,
                            "Jumlah": total,
                            "Kategori": (
                                manual_category
                            ),
                            "Nama Nota": (
                                manual_note_name
                                .strip()
                            ),
                            "Kunci": manual_lock,
                        }
                    ]
                )

                if (
                    manual_category
                    == "Belum Dikategorikan"
                ):
                    predicted = (
                        apply_predicted_categories(
                            ui_dataframe_to_service(
                                manual_row,
                                "manual",
                            ),
                            overwrite_existing=True,
                        )
                    )

                    manual_row = (
                        service_dataframe_to_ui(
                            predicted,
                            note_name=(
                                manual_note_name
                                .strip()
                            ),
                        )
                    )

                append_rows(
                    manual_row
                )

                st.session_state.last_input_method = (
                    "manual"
                )

                st.rerun()


# =========================================================
# TABEL KOREKSI
# =========================================================

st.divider()
st.subheader("4. Tabel Koreksi")

st.caption(
    "Semua kolom dapat diedit. "
    "Kategori otomatis tetap bisa diganti manual."
)

current_table = prepare_dataframe(
    st.session_state.input_table
)

editor_key = (
    "input_nota_editor_"
    f"{st.session_state.input_editor_version}"
)

edited_table = st.data_editor(
    current_table,
    hide_index=True,
    num_rows="dynamic",
    use_container_width=True,
    key=editor_key,
    column_config={
        "Uraian": (
            st.column_config.TextColumn(
                "Uraian",
                required=True,
                width="large",
            )
        ),
        "Kuantitas": (
            st.column_config.NumberColumn(
                "Kuantitas",
                min_value=0.01,
                step=1.0,
                format="%.2f",
            )
        ),
        "Satuan": (
            st.column_config.SelectboxColumn(
                "Satuan",
                options=UNITS,
                required=True,
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
                min_value=0.0,
                step=1000.0,
                format="Rp %.0f",
            )
        ),
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
                width="medium",
            )
        ),
        "Kunci": (
            st.column_config.CheckboxColumn(
                "Kunci Harga"
            )
        ),
    },
)

if dataframe_changed(
    current_table,
    edited_table,
):
    st.session_state.input_table = (
        synchronize_dataframe(
            current_table,
            edited_table,
        )
    )

    st.session_state.input_editor_version += 1

    st.rerun()


# =========================================================
# AKSI TABEL
# =========================================================

button_1, button_2, button_3, button_4 = (
    st.columns(4)
)

with button_1:
    if st.button(
        "➕ Tambah Baris",
        use_container_width=True,
    ):
        append_rows(
            empty_dataframe()
        )

        st.rerun()

with button_2:
    if st.button(
        "🏷️ Isi Kategori Otomatis",
        use_container_width=True,
    ):
        predicted = apply_predicted_categories(
            ui_dataframe_to_service(
                st.session_state.input_table,
                st.session_state.last_input_method,
            ),
            overwrite_existing=True,
        )

        replace_rows(
            service_dataframe_to_ui(
                predicted
            )
        )

        st.rerun()

with button_3:
    if st.button(
        "🧮 Hitung Ulang",
        use_container_width=True,
    ):
        table = prepare_dataframe(
            st.session_state.input_table
        )

        for index in table.index:
            quantity = max(
                numeric_value(
                    table.at[
                        index,
                        "Kuantitas",
                    ]
                ),
                1,
            )

            price = numeric_value(
                table.at[
                    index,
                    "Harga",
                ]
            )

            total = numeric_value(
                table.at[
                    index,
                    "Jumlah",
                ]
            )

            table.at[
                index,
                "Kuantitas",
            ] = quantity

            if price > 0:
                table.at[
                    index,
                    "Jumlah",
                ] = quantity * price

            elif total > 0:
                table.at[
                    index,
                    "Harga",
                ] = total / quantity

        replace_rows(table)

        st.rerun()

with button_4:
    if st.button(
        "🗑️ Kosongkan",
        use_container_width=True,
    ):
        st.session_state.input_table = (
            empty_dataframe()
        )

        st.session_state.input_editor_version += 1

        st.rerun()


# =========================================================
# RINGKASAN DAN VALIDASI
# =========================================================

st.divider()
st.subheader("5. Ringkasan")

summary_table = prepare_dataframe(
    st.session_state.input_table
)

valid_rows = summary_table[
    summary_table[
        "Uraian"
    ].str.strip().ne("")
].copy()

item_count = len(valid_rows)

total_quantity = (
    valid_rows["Kuantitas"]
    .apply(numeric_value)
    .sum()
)

grand_total = (
    valid_rows["Jumlah"]
    .apply(numeric_value)
    .sum()
)

metric_1, metric_2, metric_3 = (
    st.columns(3)
)

metric_1.metric(
    "Jumlah Baris",
    item_count,
)

metric_2.metric(
    "Total Kuantitas",
    f"{total_quantity:,.2f}".replace(
        ",",
        ".",
    ),
)

metric_3.metric(
    "Total Invoice",
    rupiah(grand_total),
)


# =========================================================
# SIMPAN
# =========================================================

st.divider()
st.subheader("6. Simpan dan Lanjutkan")

validation_errors = []

if not st.session_state.customer_name.strip():
    validation_errors.append(
        "Nama pelanggan belum diisi."
    )

if not st.session_state.customer_address.strip():
    validation_errors.append(
        "Alamat pelanggan belum diisi."
    )

if not st.session_state.invoice_period.strip():
    validation_errors.append(
        "Periode belum diisi."
    )

if valid_rows.empty:
    validation_errors.append(
        "Belum ada barang yang dapat disimpan."
    )

if not st.session_state.selected_template:
    validation_errors.append(
        "Template invoice belum dipilih."
    )

if (
    not valid_rows.empty
    and (
        valid_rows["Kuantitas"]
        .apply(numeric_value)
        <= 0
    ).any()
):
    validation_errors.append(
        "Masih ada kuantitas nol atau negatif."
    )

if (
    not valid_rows.empty
    and (
        valid_rows["Jumlah"]
        .apply(numeric_value)
        <= 0
    ).any()
):
    validation_errors.append(
        "Masih ada baris dengan Jumlah nol."
    )

for error in validation_errors:
    st.warning(error)

save_button = st.button(
    "💾 Simpan ke Database dan Lanjutkan ke Matching",
    type="primary",
    use_container_width=True,
    disabled=bool(validation_errors),
)

if save_button:
    try:
        final_table = prepare_dataframe(
            valid_rows
        )

        database_table = (
            ui_dataframe_to_service(
                final_table,
                st.session_state.last_input_method,
            )
        )

        with st.spinner(
            "Menyimpan invoice ke Supabase..."
        ):
            save_result = (
                save_imported_invoice(
                    database_table,
                    invoice_number=(
                        st.session_state
                        .invoice_number
                        .strip()
                        or None
                    ),
                    invoice_date=date.today(),
                    vendor_name=(
                        st.session_state
                        .vendor_name
                        .strip()
                        or None
                    ),
                    customer_name=(
                        st.session_state
                        .customer_name
                        .strip()
                    ),
                    notes=(
                        f"Periode: "
                        f"{st.session_state.invoice_period}; "
                        f"Alamat: "
                        f"{st.session_state.customer_address}"
                    ),
                )
            )

        saved_invoice_id = str(
            save_result["invoice_id"]
        )

        st.session_state.current_invoice_id = (
            saved_invoice_id
        )

        st.session_state.invoice_id = (
            saved_invoice_id
        )

        st.session_state.saved_invoice_id = (
            saved_invoice_id
        )

        st.session_state.invoice_items = (
            final_table.to_dict(
                orient="records"
            )
        )

        st.session_state.invoice_metadata = {
            "invoice_id": saved_invoice_id,
            "invoice_number": (
                st.session_state
                .invoice_number
            ),
            "customer_name": (
                st.session_state
                .customer_name
            ),
            "customer_address": (
                st.session_state
                .customer_address
            ),
            "vendor_name": (
                st.session_state
                .vendor_name
            ),
            "period": (
                st.session_state
                .invoice_period
            ),
            "selected_template": (
                st.session_state
                .selected_template
            ),
        }

        st.session_state.final_items = (
            st.session_state.invoice_items
        )

        st.session_state.matched_items = (
            st.session_state.invoice_items
        )

        st.success(
            f"{save_result['saved_items']} "
            f"item tersimpan ke database. "
            f"Total "
            f"{rupiah(save_result['total'])}."
        )

        try:
            st.switch_page(
                "pages/2_🧠_Matching.py"
            )

        except Exception:
            st.info(
                "Data sudah tersimpan. "
                "Buka halaman Matching "
                "dari menu kiri."
            )

    except Exception as error:
        st.error(
            "Gagal menyimpan ke Supabase: "
            f"{error}"
        )