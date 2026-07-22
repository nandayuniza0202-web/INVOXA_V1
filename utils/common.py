from __future__ import annotations

import re
from typing import Any

import pandas as pd


CATEGORIES = [
    "Belum Dikategorikan",
    "ATK",
    "APD",
    "Alat Kebersihan",
    "Alat Kelengkapan",
]

UNITS = [
    "pcs", "buah", "unit", "set", "pak", "pack", "box", "dos",
    "lusin", "rim", "roll", "botol", "liter", "kg", "gram", "meter",
]

REQUIRED_COLUMNS = [
    "Uraian",
    "Kuantitas",
    "Satuan",
    "Harga",
    "Jumlah",
    "Kategori",
    "Nama Nota",
    "Kunci",
]


def numeric_value(value: Any) -> float:
    if value is None:
        return 0.0

    try:
        if pd.isna(value):
            return 0.0
    except TypeError:
        pass

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return 0.0

    text = re.sub(r"(?i)\brp\b", "", text)
    text = re.sub(r"[^0-9,.\-]", "", text)

    if not text:
        return 0.0

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    elif text.count(",") > 1:
        text = text.replace(",", "")
    elif "," in text:
        right = text.split(",")[-1]
        text = text.replace(",", "." if len(right) <= 2 else "")
    elif "." in text and len(text.split(".")[-1]) == 3:
        text = text.replace(".", "")

    try:
        return float(text)
    except ValueError:
        return 0.0


def rupiah(value: Any) -> str:
    return f"Rp{numeric_value(value):,.0f}".replace(",", ".")


def prepare_dataframe(records_or_df: Any) -> pd.DataFrame:
    if isinstance(records_or_df, pd.DataFrame):
        dataframe = records_or_df.copy()
    else:
        dataframe = pd.DataFrame(records_or_df)

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

    for column in REQUIRED_COLUMNS:
        if column not in dataframe.columns:
            dataframe[column] = defaults[column]

    dataframe = dataframe[REQUIRED_COLUMNS].copy()

    dataframe["Uraian"] = dataframe["Uraian"].fillna("").astype(str).str.strip()
    dataframe["Satuan"] = dataframe["Satuan"].fillna("pcs").astype(str).str.strip()
    dataframe["Kategori"] = (
        dataframe["Kategori"]
        .fillna("Belum Dikategorikan")
        .astype(str)
        .str.strip()
    )
    dataframe["Nama Nota"] = dataframe["Nama Nota"].fillna("").astype(str).str.strip()
    dataframe["Kuantitas"] = dataframe["Kuantitas"].apply(numeric_value)
    dataframe["Harga"] = dataframe["Harga"].apply(numeric_value)
    dataframe["Jumlah"] = dataframe["Jumlah"].apply(numeric_value)
    dataframe["Kunci"] = dataframe["Kunci"].fillna(False).astype(bool)

    dataframe.loc[dataframe["Kuantitas"] <= 0, "Kuantitas"] = 1.0

    missing_price = (
        (dataframe["Harga"] <= 0)
        & (dataframe["Jumlah"] > 0)
        & (dataframe["Kuantitas"] > 0)
    )
    dataframe.loc[missing_price, "Harga"] = (
        dataframe.loc[missing_price, "Jumlah"]
        / dataframe.loc[missing_price, "Kuantitas"]
    )

    missing_total = (
        (dataframe["Jumlah"] <= 0)
        & (dataframe["Harga"] > 0)
    )
    dataframe.loc[missing_total, "Jumlah"] = (
        dataframe.loc[missing_total, "Kuantitas"]
        * dataframe.loc[missing_total, "Harga"]
    )

    return dataframe.reset_index(drop=True)


def recalculate(dataframe: pd.DataFrame) -> pd.DataFrame:
    result = prepare_dataframe(dataframe)
    result["Jumlah"] = result["Kuantitas"] * result["Harga"]
    return result
