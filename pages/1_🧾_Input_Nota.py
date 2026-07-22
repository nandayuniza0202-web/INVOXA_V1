from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Any

import pandas as pd
import pytesseract
import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


# =========================================================
# KONFIGURASI HALAMAN
# =========================================================

st.set_page_config(
    page_title="Input Nota",
    page_icon="🧾",
    layout="wide",
)


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

    # Jika ada titik dan koma, tentukan pemisah desimal dari posisi terakhir.
    if "." in text and "," in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        # Format Indonesia: 10.000,50 atau 10000,50
        parts = text.split(",")
        if len(parts[-1]) in (1, 2):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "." in text:
        # Titik biasanya pemisah ribuan.
        parts = text.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            text = text.replace(".", "")

    text = re.sub(r"[^0-9.\-]", "", text)

    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def rupiah(value: Any) -> str:
    number = numeric_value(value)
    return f"Rp{number:,.0f}".replace(",", ".")


def empty_dataframe(rows: int = 1) -> pd.DataFrame:
    data = []
    for _ in range(max(rows, 0)):
        data.append(
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
        )
    return pd.DataFrame(data, columns=COLUMNS)


def prepare_dataframe(data: Any) -> pd.DataFrame:
    """Menormalkan data agar selalu mempunyai kolom yang dibutuhkan."""
    if data is None:
        return empty_dataframe()

    if isinstance(data, pd.DataFrame):
        df = data.copy()
    else:
        try:
            df = pd.DataFrame(data)
        except Exception:
            df = empty_dataframe()

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

    df["Uraian"] = df["Uraian"].fillna("").astype(str)
    df["Satuan"] = df["Satuan"].fillna("pcs").astype(str)
    df["Kategori"] = (
        df["Kategori"]
        .fillna("Belum Dikategorikan")
        .astype(str)
    )
    df["Nama Nota"] = df["Nama Nota"].fillna("").astype(str)
    df["Kunci"] = df["Kunci"].fillna(False).astype(bool)

    df["Kuantitas"] = df["Kuantitas"].apply(numeric_value)
    df["Harga"] = df["Harga"].apply(numeric_value)
    df["Jumlah"] = df["Jumlah"].apply(numeric_value)

    df.loc[df["Kuantitas"] <= 0, "Kuantitas"] = 1.0
    df.loc[~df["Satuan"].isin(UNITS), "Satuan"] = "pcs"
    df.loc[~df["Kategori"].isin(CATEGORIES), "Kategori"] = (
        "Belum Dikategorikan"
    )

    return df.reset_index(drop=True)


def dataframe_changed(old: pd.DataFrame, new: pd.DataFrame) -> bool:
    old_norm = prepare_dataframe(old)
    new_norm = prepare_dataframe(new)

    if old_norm.shape != new_norm.shape:
        return True

    try:
        return not old_norm.equals(new_norm)
    except Exception:
        return True


def changed_number(old: Any, new: Any, tolerance: float = 0.01) -> bool:
    return abs(numeric_value(old) - numeric_value(new)) > tolerance


def synchronize_dataframe(
    previous: pd.DataFrame,
    edited: pd.DataFrame,
) -> pd.DataFrame:
    """
    Sinkronisasi dua arah:
    - Kuantitas + Harga => Jumlah
    - Kuantitas + Jumlah => Harga
    - Jika Harga diubah, Jumlah menjadi prioritas hasil perhitungan.
    - Jika Jumlah diubah, Harga menjadi prioritas hasil perhitungan.
    - Jika Kuantitas diubah, Jumlah dihitung dari Harga bila Harga tersedia.
    """
    old_df = prepare_dataframe(previous)
    new_df = prepare_dataframe(edited)

    for index in new_df.index:
        qty = numeric_value(new_df.at[index, "Kuantitas"])
        price = numeric_value(new_df.at[index, "Harga"])
        total = numeric_value(new_df.at[index, "Jumlah"])

        if qty <= 0:
            qty = 1.0
            new_df.at[index, "Kuantitas"] = qty

        if index < len(old_df):
            old_qty = numeric_value(old_df.at[index, "Kuantitas"])
            old_price = numeric_value(old_df.at[index, "Harga"])
            old_total = numeric_value(old_df.at[index, "Jumlah"])

            qty_changed = changed_number(old_qty, qty)
            price_changed = changed_number(old_price, price)
            total_changed = changed_number(old_total, total)
        else:
            qty_changed = True
            price_changed = price > 0
            total_changed = total > 0

        # Harga diubah: hitung Jumlah.
        if price_changed and not total_changed:
            new_df.at[index, "Jumlah"] = qty * price

        # Jumlah diubah: hitung Harga.
        elif total_changed and not price_changed:
            new_df.at[index, "Harga"] = total / qty if qty > 0 else 0.0

        # Keduanya berubah: prioritaskan Jumlah yang diketik pengguna.
        elif price_changed and total_changed:
            if total > 0 and qty > 0:
                new_df.at[index, "Harga"] = total / qty
            elif price > 0:
                new_df.at[index, "Jumlah"] = qty * price

        # Hanya kuantitas berubah.
        elif qty_changed:
            if price > 0:
                new_df.at[index, "Jumlah"] = qty * price
            elif total > 0 and qty > 0:
                new_df.at[index, "Harga"] = total / qty

        # Lengkapi data awal hasil OCR/Excel.
        else:
            if price <= 0 and total > 0 and qty > 0:
                new_df.at[index, "Harga"] = total / qty
            elif total <= 0 and price > 0:
                new_df.at[index, "Jumlah"] = qty * price

    new_df["Harga"] = new_df["Harga"].apply(numeric_value).round(0)
    new_df["Jumlah"] = new_df["Jumlah"].apply(numeric_value).round(0)
    new_df["Kuantitas"] = new_df["Kuantitas"].apply(numeric_value)

    return prepare_dataframe(new_df)


def append_rows(rows: pd.DataFrame) -> None:
    rows = prepare_dataframe(rows)
    current = prepare_dataframe(st.session_state.input_table)

    # Hapus baris kosong bawaan bila belum pernah diisi.
    if (
        len(current) == 1
        and not current.at[0, "Uraian"].strip()
        and numeric_value(current.at[0, "Harga"]) == 0
        and numeric_value(current.at[0, "Jumlah"]) == 0
    ):
        current = current.iloc[0:0]

    combined = pd.concat([current, rows], ignore_index=True)
    st.session_state.input_table = prepare_dataframe(combined)
    st.session_state.input_editor_version += 1


def replace_rows(rows: pd.DataFrame) -> None:
    st.session_state.input_table = prepare_dataframe(rows)
    st.session_state.input_editor_version += 1


# =========================================================
# EXCEL
# =========================================================

def normalize_column_name(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def find_matching_column(
    columns: list[str],
    candidates: list[str],
) -> str | None:
    normalized = {normalize_column_name(column): column for column in columns}

    for candidate in candidates:
        key = normalize_column_name(candidate)
        if key in normalized:
            return normalized[key]

    for normalized_name, original_name in normalized.items():
        for candidate in candidates:
            key = normalize_column_name(candidate)
            if key and key in normalized_name:
                return original_name

    return None


def map_excel_dataframe(raw_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df is None or raw_df.empty:
        return empty_dataframe(0)

    raw_df = raw_df.dropna(how="all").copy()
    columns = list(raw_df.columns)

    mapping_candidates = {
        "Uraian": [
            "uraian",
            "nama barang",
            "barang",
            "deskripsi",
            "item",
            "produk",
            "keterangan",
        ],
        "Kuantitas": [
            "kuantitas",
            "qty",
            "jumlah barang",
            "volume",
            "banyak",
        ],
        "Satuan": ["satuan", "unit"],
        "Harga": [
            "harga satuan",
            "harga",
            "unit price",
            "harga unit",
        ],
        "Jumlah": [
            "jumlah",
            "total",
            "subtotal",
            "nilai",
            "pengeluaran",
        ],
        "Kategori": ["kategori", "jenis"],
        "Nama Nota": [
            "nama nota",
            "nota",
            "invoice",
            "no nota",
            "nomor nota",
        ],
    }

    result = empty_dataframe(0)

    for target, candidates in mapping_candidates.items():
        source = find_matching_column(columns, candidates)
        if source:
            result[target] = raw_df[source]

    if "Uraian" not in result.columns or result["Uraian"].empty:
        # Gunakan kolom teks pertama sebagai uraian.
        text_columns = [
            column
            for column in columns
            if raw_df[column].dtype == "object"
        ]
        if text_columns:
            result["Uraian"] = raw_df[text_columns[0]]
        else:
            result["Uraian"] = ""

    result = prepare_dataframe(result)

    # Lengkapi Harga/Jumlah.
    for index in result.index:
        qty = numeric_value(result.at[index, "Kuantitas"])
        price = numeric_value(result.at[index, "Harga"])
        total = numeric_value(result.at[index, "Jumlah"])

        if qty <= 0:
            qty = 1
            result.at[index, "Kuantitas"] = qty

        if price <= 0 and total > 0:
            result.at[index, "Harga"] = total / qty
        elif total <= 0 and price > 0:
            result.at[index, "Jumlah"] = qty * price

    # Buang baris yang benar-benar kosong.
    mask = (
        result["Uraian"].str.strip().ne("")
        | result["Harga"].gt(0)
        | result["Jumlah"].gt(0)
    )
    return prepare_dataframe(result.loc[mask].reset_index(drop=True))


# =========================================================
# OCR FOTO
# =========================================================

def file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def preprocess_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    image = image.convert("L")
    image = ImageOps.autocontrast(image)
    image = ImageEnhance.Contrast(image).enhance(1.8)
    image = image.filter(ImageFilter.SHARPEN)

    width, height = image.size
    if width < 1600:
        ratio = 1600 / max(width, 1)
        image = image.resize(
            (int(width * ratio), int(height * ratio))
        )

    return image


def clean_ocr_text(text: str) -> str:
    replacements = {
        "O": "0",
        "o": "0",
        "I": "1",
        "l": "1",
    }

    # Penggantian hanya pada token yang sebagian besar berupa angka.
    tokens = []
    for token in text.split():
        digit_count = sum(character.isdigit() for character in token)
        if digit_count >= max(1, len(token) // 2):
            for old, new in replacements.items():
                token = token.replace(old, new)
        tokens.append(token)

    return " ".join(tokens)


def extract_money_values(line: str) -> list[float]:
    patterns = re.findall(
        r"(?:Rp\s*)?\d{1,3}(?:[.\s]\d{3})+(?:,\d{1,2})?"
        r"|(?:Rp\s*)?\d{4,}(?:,\d{1,2})?",
        line,
        flags=re.IGNORECASE,
    )

    values = []
    for pattern in patterns:
        value = numeric_value(pattern)
        if value > 0:
            values.append(value)

    return values


def detect_quantity_and_unit(line: str) -> tuple[float, str]:
    unit_pattern = "|".join(re.escape(unit) for unit in UNITS)

    patterns = [
        rf"\b(\d+(?:[.,]\d+)?)\s*({unit_pattern})\b",
        rf"\b({unit_pattern})\s*(\d+(?:[.,]\d+)?)\b",
    ]

    match = re.search(patterns[0], line, flags=re.IGNORECASE)
    if match:
        return numeric_value(match.group(1)), match.group(2).lower()

    match = re.search(patterns[1], line, flags=re.IGNORECASE)
    if match:
        return numeric_value(match.group(2)), match.group(1).lower()

    # Angka kecil di awal baris sering merupakan qty.
    match = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s+", line)
    if match:
        qty = numeric_value(match.group(1))
        if 0 < qty <= 10000:
            return qty, "pcs"

    return 1.0, "pcs"


def remove_price_and_quantity_from_description(
    line: str,
    quantity: float,
    unit: str,
) -> str:
    description = line

    description = re.sub(
        r"(?:Rp\s*)?\d{1,3}(?:[.\s]\d{3})+(?:,\d{1,2})?"
        r"|(?:Rp\s*)?\d{4,}(?:,\d{1,2})?",
        " ",
        description,
        flags=re.IGNORECASE,
    )

    if quantity > 0:
        quantity_strings = {
            str(int(quantity)) if quantity.is_integer() else str(quantity),
            str(quantity).replace(".", ","),
        }
        for quantity_string in quantity_strings:
            description = re.sub(
                rf"^\s*{re.escape(quantity_string)}\s*",
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

    description = re.sub(r"\s+", " ", description).strip(" -:|")
    return description


def should_skip_ocr_line(line: str) -> bool:
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
        "pemasukan",
        "pengeluaran",
        "debit",
        "kredit",
    ]

    return any(word in normalized for word in skip_words)


def parse_ocr_text(
    text: str,
    category: str,
    note_name: str,
) -> pd.DataFrame:
    rows = []

    for raw_line in text.splitlines():
        line = clean_ocr_text(raw_line).strip()

        if should_skip_ocr_line(line):
            continue

        money_values = extract_money_values(line)

        # Baris tanpa nilai uang biasanya bukan baris item.
        if not money_values:
            continue

        quantity, unit = detect_quantity_and_unit(line)

        if quantity <= 0:
            quantity = 1.0

        if len(money_values) >= 2:
            price = money_values[-2]
            total = money_values[-1]

            # Koreksi jika angka terakhir tampaknya bukan hasil qty x harga.
            expected = quantity * price
            if quantity > 0 and expected > 0:
                difference_ratio = abs(total - expected) / expected
                if difference_ratio > 0.25:
                    # Prioritaskan angka terakhir sebagai jumlah.
                    price = total / quantity
        else:
            total = money_values[-1]
            price = total / quantity if quantity > 0 else total

        description = remove_price_and_quantity_from_description(
            line,
            float(quantity),
            unit,
        )

        if not description:
            description = "Perlu dikoreksi"

        rows.append(
            {
                "Uraian": description,
                "Kuantitas": quantity,
                "Satuan": unit if unit in UNITS else "pcs",
                "Harga": price,
                "Jumlah": total,
                "Kategori": category,
                "Nama Nota": note_name,
                "Kunci": False,
            }
        )

    return prepare_dataframe(rows) if rows else empty_dataframe(0)


def run_ocr(image: Image.Image) -> str:
    processed = preprocess_image(image)

    configurations = [
        "--oem 3 --psm 6",
        "--oem 3 --psm 4",
    ]

    outputs = []
    for config in configurations:
        try:
            text = pytesseract.image_to_string(
                processed,
                lang="eng",
                config=config,
            )
            outputs.append(text)
        except pytesseract.TesseractNotFoundError:
            raise
        except Exception:
            continue

    if not outputs:
        return ""

    # Pilih hasil yang memiliki paling banyak karakter bermakna.
    return max(outputs, key=lambda value: len(value.strip()))


# =========================================================
# SESSION STATE
# =========================================================

if "invoice_items" not in st.session_state:
    st.session_state.invoice_items = []

if "input_table" not in st.session_state:
    st.session_state.input_table = empty_dataframe()

if "customer_name" not in st.session_state:
    st.session_state.customer_name = ""

if "customer_address" not in st.session_state:
    st.session_state.customer_address = ""

if "invoice_period" not in st.session_state:
    st.session_state.invoice_period = ""

if "selected_template" not in st.session_state:
    st.session_state.selected_template = ""

if "ocr_cache" not in st.session_state:
    st.session_state.ocr_cache = {}

if "input_editor_version" not in st.session_state:
    st.session_state.input_editor_version = 0


# =========================================================
# TAMPILAN UTAMA
# =========================================================

st.title("🧾 Input Nota")

st.caption(
    "Masukkan data dari foto, Excel, atau secara manual. "
    "Semua hasil dapat diperbaiki pada Tabel Koreksi."
)

st.divider()


# =========================================================
# DATA PELANGGAN
# =========================================================

st.subheader("1. Data Pelanggan")

customer_col, address_col = st.columns(2)

customer_col, address_col, period_col = st.columns(3)

with customer_col:
    st.session_state.customer_name = st.text_input(
        "Nama Pelanggan",
        value=st.session_state.customer_name,
        placeholder="Contoh: PT Raharja Abadi Futura",
    )

with address_col:
    st.session_state.customer_address = st.text_input(
        "Alamat Pelanggan",
        value=st.session_state.customer_address,
        placeholder="Contoh: Jl. Perumnas Raya",
    )

with period_col:
    st.session_state.invoice_period = st.text_input(
        "Periode",
        value=st.session_state.invoice_period,
        placeholder="Contoh: Juli 2026",
    )


# =========================================================
# TEMPLATE WORD
# =========================================================

st.divider()
st.subheader("2. Template Invoice")

project_root = Path(__file__).resolve().parents[1]
template_folder = project_root / "templates"
template_folder.mkdir(parents=True, exist_ok=True)

template_files = sorted(template_folder.glob("*.docx"))

if template_files:
    template_names = [template.name for template in template_files]

    previous_name = ""
    if st.session_state.selected_template:
        previous_name = Path(
            st.session_state.selected_template
        ).name

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

    selected_template_path = (
        template_folder / selected_template_name
    )

    st.session_state.selected_template = str(
        selected_template_path
    )

    st.success(
        f"Template aktif: {selected_template_name}"
    )
else:
    st.warning(
        "Belum ada template Word. Masukkan file .docx ke folder "
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
        "📷 Foto OCR",
        "📊 Excel",
        "⌨️ Manual",
    ],
    horizontal=True,
)


# =========================================================
# INPUT FOTO OCR
# =========================================================

if method == "📷 Foto OCR":
    st.markdown("#### Unggah Foto Nota")

    uploaded_images = st.file_uploader(
        "Pilih satu atau beberapa foto",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        help=(
            "Untuk hasil terbaik, gunakan foto lurus, terang, "
            "dan tulisan tidak buram."
        ),
    )

    if uploaded_images:
        all_ocr_rows = []

        for image_number, uploaded_image in enumerate(
            uploaded_images,
            start=1,
        ):
            image_bytes = uploaded_image.getvalue()
            image = Image.open(io.BytesIO(image_bytes))
            digest = file_hash(image_bytes)

            st.markdown(
                f"##### Foto {image_number}: {uploaded_image.name}"
            )

            preview_col, setting_col = st.columns([1.15, 1])

            with preview_col:
                st.image(
                    image,
                    caption=uploaded_image.name,
                    use_container_width=True,
                )

            with setting_col:
                category = st.selectbox(
                    "Kategori",
                    options=CATEGORIES,
                    key=f"ocr_category_{digest}",
                )

                default_note_name = Path(
                    uploaded_image.name
                ).stem

                note_name = st.text_input(
                    "Nama Nota",
                    value=default_note_name,
                    key=f"ocr_note_name_{digest}",
                )

                force_ocr = st.checkbox(
                    "Baca ulang OCR",
                    value=False,
                    key=f"force_ocr_{digest}",
                )

                ocr_button = st.button(
                    "🔍 Baca Foto",
                    key=f"ocr_button_{digest}",
                    use_container_width=True,
                )

            if ocr_button:
                try:
                    with st.spinner(
                        f"Membaca {uploaded_image.name}..."
                    ):
                        if (
                            digest not in st.session_state.ocr_cache
                            or force_ocr
                        ):
                            raw_text = run_ocr(image)
                            st.session_state.ocr_cache[digest] = raw_text
                        else:
                            raw_text = (
                                st.session_state.ocr_cache[digest]
                            )

                    parsed_rows = parse_ocr_text(
                        raw_text,
                        category,
                        note_name,
                    )

                    st.session_state.ocr_cache[
                        f"{digest}_rows"
                    ] = parsed_rows.to_dict("records")

                    if parsed_rows.empty:
                        st.warning(
                            "Tidak ada baris item yang dapat dibaca. "
                            "Coba foto yang lebih jelas atau koreksi "
                            "secara manual."
                        )
                    else:
                        st.success(
                            f"{len(parsed_rows)} baris terdeteksi."
                        )

                except pytesseract.TesseractNotFoundError:
                    st.error(
                        "Tesseract belum terpasang. Jalankan di Terminal:\n\n"
                        "`brew install tesseract`"
                    )
                except Exception as error:
                    st.error(f"OCR gagal: {error}")

            cached_rows = st.session_state.ocr_cache.get(
                f"{digest}_rows",
                [],
            )

            if cached_rows:
                parsed_rows = prepare_dataframe(cached_rows)

                # Terapkan perubahan kategori/nama nota terbaru.
                parsed_rows["Kategori"] = category
                parsed_rows["Nama Nota"] = note_name

                st.dataframe(
                    parsed_rows,
                    hide_index=True,
                    use_container_width=True,
                )

                all_ocr_rows.append(parsed_rows)

            st.divider()

        if all_ocr_rows:
            combined_ocr_rows = pd.concat(
                all_ocr_rows,
                ignore_index=True,
            )

            action_col_1, action_col_2 = st.columns(2)

            with action_col_1:
                if st.button(
                    "➕ Tambahkan Hasil OCR ke Tabel",
                    type="primary",
                    use_container_width=True,
                ):
                    append_rows(combined_ocr_rows)
                    st.success(
                        "Hasil OCR ditambahkan ke Tabel Koreksi."
                    )
                    st.rerun()

            with action_col_2:
                if st.button(
                    "♻️ Ganti Tabel dengan Hasil OCR",
                    use_container_width=True,
                ):
                    replace_rows(combined_ocr_rows)
                    st.success(
                        "Tabel diganti dengan hasil OCR."
                    )
                    st.rerun()


# =========================================================
# INPUT EXCEL
# =========================================================

elif method == "📊 Excel":
    st.markdown("#### Unggah Excel")

    excel_file = st.file_uploader(
        "Pilih file Excel",
        type=["xlsx", "xls"],
        accept_multiple_files=False,
    )

    if excel_file is not None:
        try:
            excel_engine = (
                "openpyxl"
                if excel_file.name.lower().endswith(".xlsx")
                else None
            )

            raw_excel = pd.read_excel(
                excel_file,
                engine=excel_engine,
            )

            mapped_excel = map_excel_dataframe(raw_excel)

            st.caption("Preview data asli")
            st.dataframe(
                raw_excel,
                hide_index=True,
                use_container_width=True,
            )

            st.caption("Preview setelah pemetaan")
            st.dataframe(
                mapped_excel,
                hide_index=True,
                use_container_width=True,
            )

            if mapped_excel.empty:
                st.warning(
                    "Tidak ada baris yang dapat dipetakan. "
                    "Pastikan Excel memiliki kolom Uraian, Qty, "
                    "Harga, atau Jumlah."
                )
            else:
                excel_action_1, excel_action_2 = st.columns(2)

                with excel_action_1:
                    if st.button(
                        "➕ Tambahkan Excel ke Tabel",
                        type="primary",
                        use_container_width=True,
                    ):
                        append_rows(mapped_excel)
                        st.success(
                            "Data Excel ditambahkan."
                        )
                        st.rerun()

                with excel_action_2:
                    if st.button(
                        "♻️ Ganti Tabel dengan Excel",
                        use_container_width=True,
                    ):
                        replace_rows(mapped_excel)
                        st.success(
                            "Tabel diganti dengan data Excel."
                        )
                        st.rerun()

        except ImportError:
            st.error(
                "Pustaka pembaca Excel belum lengkap. Jalankan:\n\n"
                "`pip install openpyxl`"
            )
        except Exception as error:
            st.error(f"Excel gagal dibaca: {error}")


# =========================================================
# INPUT MANUAL
# =========================================================

elif method == "⌨️ Manual":
    st.markdown("#### Tambah Barang Manual")

    with st.form(
        "manual_input_form",
        clear_on_submit=True,
    ):
        manual_col_1, manual_col_2 = st.columns(2)

        with manual_col_1:
            manual_description = st.text_input(
                "Uraian Barang",
                placeholder="Contoh: Kertas A4 80 gsm",
            )

            manual_quantity = st.number_input(
                "Kuantitas",
                min_value=0.01,
                value=1.0,
                step=1.0,
            )

            manual_unit = st.selectbox(
                "Satuan",
                options=UNITS,
            )

            manual_category = st.selectbox(
                "Kategori",
                options=CATEGORIES,
            )

        with manual_col_2:
            manual_price = st.number_input(
                "Harga Satuan",
                min_value=0.0,
                value=0.0,
                step=1000.0,
            )

            manual_total = st.number_input(
                "Jumlah",
                min_value=0.0,
                value=0.0,
                step=1000.0,
                help=(
                    "Isi Harga Satuan atau Jumlah. "
                    "Nilai lainnya akan dihitung otomatis."
                ),
            )

            manual_note_name = st.text_input(
                "Nama Nota",
                placeholder="Contoh: Nota Toko ABC",
            )

            manual_lock = st.checkbox(
                "Kunci Harga",
                value=False,
            )

        manual_submit = st.form_submit_button(
            "➕ Tambahkan ke Tabel",
            type="primary",
            use_container_width=True,
        )

        if manual_submit:
            if not manual_description.strip():
                st.error("Uraian barang wajib diisi.")
            elif manual_price <= 0 and manual_total <= 0:
                st.error(
                    "Isi Harga Satuan atau Jumlah."
                )
            else:
                quantity = max(
                    numeric_value(manual_quantity),
                    1,
                )
                price = numeric_value(manual_price)
                total = numeric_value(manual_total)

                if price > 0:
                    total = quantity * price
                elif total > 0:
                    price = total / quantity

                manual_row = pd.DataFrame(
                    [
                        {
                            "Uraian": manual_description.strip(),
                            "Kuantitas": quantity,
                            "Satuan": manual_unit,
                            "Harga": price,
                            "Jumlah": total,
                            "Kategori": manual_category,
                            "Nama Nota": manual_note_name.strip(),
                            "Kunci": manual_lock,
                        }
                    ]
                )

                append_rows(manual_row)
                st.success(
                    "Barang ditambahkan ke Tabel Koreksi."
                )
                st.rerun()


# =========================================================
# TABEL KOREKSI
# =========================================================

st.divider()
st.subheader("4. Tabel Koreksi")

st.caption(
    "Semua kolom dapat diedit. Isi Kuantitas bersama Harga Satuan "
    "atau Jumlah. Setelah nilai selesai diketik dan sel berpindah, "
    "kolom pasangannya akan dihitung otomatis."
)

current_table = prepare_dataframe(
    st.session_state.input_table
)

editor_key = (
    f"input_nota_editor_"
    f"{st.session_state.input_editor_version}"
)

edited_table = st.data_editor(
    current_table,
    hide_index=True,
    num_rows="dynamic",
    use_container_width=True,
    key=editor_key,
    column_config={
        "Uraian": st.column_config.TextColumn(
            "Uraian",
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
            min_value=0.0,
            step=1000.0,
            format="Rp %.0f",
        ),
        "Kategori": st.column_config.SelectboxColumn(
            "Kategori",
            options=CATEGORIES,
            required=True,
        ),
        "Nama Nota": st.column_config.TextColumn(
            "Nama Nota",
            width="medium",
        ),
        "Kunci": st.column_config.CheckboxColumn(
            "Kunci Harga",
        ),
    },
)

if dataframe_changed(current_table, edited_table):
    synchronized_table = synchronize_dataframe(
        current_table,
        edited_table,
    )

    st.session_state.input_table = synchronized_table
    st.session_state.input_editor_version += 1
    st.rerun()


# =========================================================
# AKSI TABEL
# =========================================================

button_col_1, button_col_2, button_col_3 = st.columns(3)

with button_col_1:
    if st.button(
        "➕ Tambah Baris Kosong",
        use_container_width=True,
    ):
        append_rows(empty_dataframe())
        st.rerun()

with button_col_2:
    if st.button(
        "🧮 Hitung Ulang Semua",
        use_container_width=True,
    ):
        table = prepare_dataframe(
            st.session_state.input_table
        )

        for index in table.index:
            qty = numeric_value(
                table.at[index, "Kuantitas"]
            )
            price = numeric_value(
                table.at[index, "Harga"]
            )
            total = numeric_value(
                table.at[index, "Jumlah"]
            )

            if qty <= 0:
                qty = 1
                table.at[index, "Kuantitas"] = qty

            if price > 0:
                table.at[index, "Jumlah"] = qty * price
            elif total > 0:
                table.at[index, "Harga"] = total / qty

        replace_rows(table)
        st.rerun()

with button_col_3:
    if st.button(
        "🗑️ Kosongkan Tabel",
        use_container_width=True,
    ):
        st.session_state.input_table = empty_dataframe()
        st.session_state.input_editor_version += 1
        st.rerun()


# =========================================================
# RINGKASAN
# =========================================================

st.divider()
st.subheader("5. Ringkasan")

summary_table = prepare_dataframe(
    st.session_state.input_table
)

valid_rows = summary_table[
    summary_table["Uraian"].str.strip().ne("")
].copy()

item_count = len(valid_rows)
total_quantity = valid_rows["Kuantitas"].apply(
    numeric_value
).sum()
grand_total = valid_rows["Jumlah"].apply(
    numeric_value
).sum()

metric_col_1, metric_col_2, metric_col_3 = st.columns(3)

with metric_col_1:
    st.metric("Jumlah Baris", item_count)

with metric_col_2:
    st.metric(
        "Total Kuantitas",
        f"{total_quantity:,.2f}".replace(",", "."),
    )

with metric_col_3:
    st.metric("Total Invoice", rupiah(grand_total))


# =========================================================
# VALIDASI DAN SIMPAN KE MATCHING
# =========================================================

st.divider()
st.subheader("6. Simpan dan Lanjutkan")

validation_errors = []

if not st.session_state.customer_name.strip():
    validation_errors.append("Nama pelanggan belum diisi.")

if not st.session_state.invoice_period.strip():
    validation_errors.append("Periode belum diisi.")

if valid_rows.empty:
    validation_errors.append("Belum ada barang yang dapat disimpan.")

if not st.session_state.selected_template:
    validation_errors.append("Template invoice belum dipilih.")

invalid_description = valid_rows[
    valid_rows["Uraian"].str.strip().eq("")
]
if not invalid_description.empty:
    validation_errors.append(
        "Masih ada baris tanpa uraian."
    )

invalid_quantity = valid_rows[
    valid_rows["Kuantitas"].apply(numeric_value) <= 0
]
if not invalid_quantity.empty:
    validation_errors.append(
        "Masih ada kuantitas nol atau negatif."
    )

invalid_total = valid_rows[
    valid_rows["Jumlah"].apply(numeric_value) <= 0
]
if not invalid_total.empty:
    validation_errors.append(
        "Masih ada baris dengan Jumlah nol."
    )

if validation_errors:
    for validation_error in validation_errors:
        st.warning(validation_error)

save_button = st.button(
    "💾 Simpan Data untuk Matching",
    type="primary",
    use_container_width=True,
    disabled=bool(validation_errors),
)

if save_button:
    final_table = prepare_dataframe(valid_rows)

    st.session_state.invoice_items = final_table.to_dict(
        orient="records"
    )

    st.session_state.invoice_metadata = {
        "customer_name": st.session_state.customer_name,
        "customer_address": st.session_state.customer_address,
        "period": st.session_state.invoice_period,
        "selected_template": st.session_state.selected_template,
    }

    # Nama-nama ini disediakan agar kompatibel
    # dengan halaman Matching, Revision, dan Download.
    st.session_state.final_items = (
        st.session_state.invoice_items
    )

    st.session_state.matched_items = (
        st.session_state.invoice_items
    )

    st.success(
        f"{len(final_table)} baris berhasil disimpan. "
        "Silakan buka halaman Matching."
    )

    try:
        st.switch_page("pages/2_🔗_Matching.py")
    except Exception:
        st.info(
            "Data sudah tersimpan. Buka halaman Matching "
            "melalui menu di sebelah kiri."
        )