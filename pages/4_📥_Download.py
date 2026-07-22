from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from docxtpl import DocxTemplate

from utils.common import prepare_dataframe, rupiah


st.set_page_config(page_title="Download", page_icon="📥", layout="wide")


# =========================================================
# KONFIGURASI
# =========================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = PROJECT_ROOT / "templates"


# =========================================================
# HELPER
# =========================================================

def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value).strip())
    return cleaned.strip("_") or "invoice"


def get_metadata() -> tuple[str, str, str]:
    metadata = st.session_state.get("invoice_metadata", {}) or {}

    customer_name = (
        metadata.get("customer_name")
        or st.session_state.get("customer_name", "")
        or ""
    )

    customer_address = (
        metadata.get("customer_address")
        or st.session_state.get("customer_address", "")
        or ""
    )

    period = (
        metadata.get("period")
        or st.session_state.get("invoice_period", "")
        or st.session_state.get("period", "")
        or ""
    )

    return (
        str(customer_name),
        str(customer_address),
        str(period),
    )


def get_templates() -> list[Path]:
    if not TEMPLATE_DIR.exists():
        return []

    return sorted(
        [
            path
            for path in TEMPLATE_DIR.iterdir()
            if path.is_file()
            and path.suffix.lower() == ".docx"
            and not path.name.startswith("~$")
        ],
        key=lambda path: path.name.lower(),
    )


def build_invoice_from_template(
    template_path: Path,
    customer_name: str,
    customer_address: str,
    period: str,
    category: str,
    items: pd.DataFrame,
    invoice_date: date,
) -> bytes:
    """
    Render template Word menggunakan docxtpl.

    Template dapat memakai:
    {{ nama_pelanggan }}
    {{ alamat }}
    {{ periode }}
    {{ tanggal }}
    {{ kategori }}
    {{ total }}

    Loop tabel:
    {%tr for item in items %}
    {{ loop.index }}
    {{ item.uraian }}
    {{ item.qty_satuan }}
    {{ item.harga }}
    {{ item.jumlah }}
    {%tr endfor %}
    """
    doc = DocxTemplate(str(template_path))

    item_rows = []

    for _, item in items.iterrows():
        qty = float(item.get("Kuantitas", 0))
        satuan = str(item.get("Satuan", "")).strip()

        item_rows.append(
            {
                "uraian": str(item.get("Uraian", "")),
                "qty": f"{qty:g}",
                "satuan": satuan,
                "qty_satuan": f"{qty:g} {satuan}".strip(),
                "harga": rupiah(item.get("Harga", 0)),
                "jumlah": rupiah(item.get("Jumlah", 0)),
                "nama_nota": str(item.get("Nama Nota", "")),
            }
        )

    context = {
        "nama_pelanggan": customer_name or "-",
        "pelanggan": customer_name or "-",
        "alamat": customer_address or "-",
        "periode": period or invoice_date.strftime("%d-%m-%Y"),
        "tanggal": invoice_date.strftime("%d-%m-%Y"),
        "kategori": category,
        "items": item_rows,
        "total": rupiah(items["Jumlah"].sum()).replace("Rp", "").strip(),
        "total_rupiah": rupiah(items["Jumlah"].sum()),
    }

    doc.render(context)

    output = io.BytesIO()
    doc.save(output)

    return output.getvalue()


# =========================================================
# HALAMAN
# =========================================================

if "invoice_items" not in st.session_state:
    st.session_state.invoice_items = []

st.title("📥 Download Invoice")

st.caption(
    "Invoice dibuat langsung dari template Word menggunakan docxtpl, "
    "sehingga desain, logo, border, header, footer, dan format tabel tetap mengikuti template."
)

st.divider()

if not st.session_state.invoice_items:
    st.warning("Belum ada data invoice.")
    st.stop()

customer_name, customer_address, period = get_metadata()

invoice_date = st.date_input(
    "Tanggal invoice",
    value=date.today(),
)

info_1, info_2, info_3 = st.columns(3)

info_1.write(f"**Pelanggan:** {customer_name or '-'}")
info_2.write(f"**Alamat:** {customer_address or '-'}")
info_3.write(f"**Periode:** {period or '-'}")

all_items = prepare_dataframe(
    st.session_state.invoice_items
)

all_items["Kuantitas"] = pd.to_numeric(
    all_items["Kuantitas"],
    errors="coerce",
).fillna(0.0)

all_items["Harga"] = pd.to_numeric(
    all_items["Harga"],
    errors="coerce",
).fillna(0.0)

all_items["Jumlah"] = (
    all_items["Kuantitas"]
    * all_items["Harga"]
)

valid_categories = [
    category
    for category in all_items["Kategori"].dropna().unique()
    if str(category).strip()
    and category != "Belum Dikategorikan"
]

if not valid_categories:
    st.error(
        "Semua barang masih belum dikategorikan. "
        "Kembali ke halaman Matching."
    )
    st.stop()

grand_total = float(
    all_items[
        all_items["Kategori"].isin(valid_categories)
    ]["Jumlah"].sum()
)

st.metric(
    "Total Keseluruhan",
    rupiah(grand_total),
)

templates = get_templates()

if not templates:
    st.error(
        f"Tidak ditemukan file template .docx di folder:\n\n"
        f"`{TEMPLATE_DIR}`"
    )
    st.stop()

st.divider()
st.subheader("Pilih Template")

template_mode = st.radio(
    "Penggunaan template",
    [
        "Gunakan satu template untuk semua kategori",
        "Pilih template berbeda per kategori",
    ],
    horizontal=True,
)

global_template: Path | None = None

if template_mode == "Gunakan satu template untuk semua kategori":
    global_template_name = st.selectbox(
        "Template Word",
        [path.name for path in templates],
    )

    global_template = next(
        path
        for path in templates
        if path.name == global_template_name
    )

st.info(
    "Template ANPER Anda sudah cocok untuk docxtpl. "
    "Jangan hapus tag {%tr for item in items %} dan {%tr endfor %}."
)

st.divider()

for category in valid_categories:
    category_items = (
        all_items[
            all_items["Kategori"] == category
        ]
        .copy()
        .reset_index(drop=True)
    )

    st.subheader(str(category))

    if template_mode == "Pilih template berbeda per kategori":
        selected_template_name = st.selectbox(
            f"Template untuk {category}",
            [path.name for path in templates],
            key=f"template_{safe_filename(category)}",
        )

        template_path = next(
            path
            for path in templates
            if path.name == selected_template_name
        )
    else:
        template_path = global_template

    st.caption(
        f"Template digunakan: **{template_path.name}**"
    )

    st.dataframe(
        category_items[
            [
                "Uraian",
                "Kuantitas",
                "Satuan",
                "Harga",
                "Jumlah",
                "Nama Nota",
            ]
        ],
        hide_index=True,
        use_container_width=True,
        column_config={
            "Harga": st.column_config.NumberColumn(
                "Harga",
                format="Rp %.0f",
            ),
            "Jumlah": st.column_config.NumberColumn(
                "Jumlah",
                format="Rp %.0f",
            ),
        },
    )

    st.metric(
        f"Total {category}",
        rupiah(category_items["Jumlah"].sum()),
    )

    try:
        word_bytes = build_invoice_from_template(
            template_path=template_path,
            customer_name=customer_name,
            customer_address=customer_address,
            period=period,
            category=str(category),
            items=category_items,
            invoice_date=invoice_date,
        )

    except Exception as error:
        st.error(
            f"Template tidak dapat diproses: {error}"
        )
        st.divider()
        continue

    filename = (
        f"invoice_{safe_filename(category)}_"
        f"{invoice_date.strftime('%d_%m_%Y')}.docx"
    )

    st.download_button(
        label=f"📥 Download Word {category}",
        data=word_bytes,
        file_name=filename,
        mime=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        use_container_width=True,
        key=f"download_{safe_filename(category)}",
    )

    st.divider()