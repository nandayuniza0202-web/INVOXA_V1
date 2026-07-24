from pathlib import Path
from typing import BinaryIO

import pandas as pd

from services.parsers.column_mapper import (
    build_column_mapping,
    standardize_dataframe,
)


MAX_HEADER_SCAN_ROWS = 20


def _read_excel_raw(
    source: str | Path | BinaryIO,
    sheet_name: str | int,
) -> pd.DataFrame:
    """Membaca Excel tanpa menganggap baris pertama sebagai header."""

    return pd.read_excel(
        source,
        sheet_name=sheet_name,
        header=None,
        dtype=object,
    )


def detect_header_row(
    raw_dataframe: pd.DataFrame,
    max_scan_rows: int = MAX_HEADER_SCAN_ROWS,
) -> int | None:
    """
    Mencari baris yang paling mungkin menjadi header tabel.

    Baris dengan minimal dua kolom yang dikenali akan dipilih.
    """

    if raw_dataframe is None or raw_dataframe.empty:
        return None

    best_row: int | None = None
    best_score = 0

    scan_limit = min(max_scan_rows, len(raw_dataframe))

    for row_index in range(scan_limit):
        row_values = raw_dataframe.iloc[row_index].tolist()
        mapping = build_column_mapping(row_values)
        score = len(mapping)

        if score > best_score:
            best_score = score
            best_row = row_index

    return best_row if best_score >= 2 else None


def dataframe_from_detected_header(
    raw_dataframe: pd.DataFrame,
    header_row: int,
) -> pd.DataFrame:
    """Membentuk DataFrame menggunakan baris header yang terdeteksi."""

    headers = raw_dataframe.iloc[header_row].tolist()

    dataframe = raw_dataframe.iloc[header_row + 1 :].copy()
    dataframe.columns = headers
    dataframe = dataframe.dropna(how="all").reset_index(drop=True)

    return dataframe


def parse_excel_sheet(
    source: str | Path | BinaryIO,
    sheet_name: str | int = 0,
) -> pd.DataFrame:
    """
    Membaca satu sheet Excel dan mengubahnya ke format standar INVOXA.
    """

    raw_dataframe = _read_excel_raw(source, sheet_name)
    header_row = detect_header_row(raw_dataframe)

    if header_row is None:
        raise ValueError(
            f"Header tabel tidak ditemukan pada sheet {sheet_name!r}. "
            "Pastikan terdapat minimal kolom uraian dan salah satu kolom "
            "quantity, satuan, harga, total, atau kategori."
        )

    dataframe = dataframe_from_detected_header(
        raw_dataframe,
        header_row,
    )

    return standardize_dataframe(dataframe)


def parse_excel_file(
    source: str | Path | BinaryIO,
) -> dict[str, pd.DataFrame]:
    """
    Membaca seluruh sheet Excel.

    Hanya sheet yang memiliki tabel valid yang dikembalikan.
    """

    excel_file = pd.ExcelFile(source)
    parsed_sheets: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}

    for sheet_name in excel_file.sheet_names:
        try:
            dataframe = parse_excel_sheet(
                excel_file,
                sheet_name=sheet_name,
            )

            if not dataframe.empty:
                parsed_sheets[sheet_name] = dataframe

        except Exception as error:
            errors[sheet_name] = str(error)

    if not parsed_sheets:
        error_details = "; ".join(
            f"{sheet}: {message}"
            for sheet, message in errors.items()
        )

        raise ValueError(
            "Tidak ada tabel barang yang berhasil dibaca dari Excel."
            + (f" Detail: {error_details}" if error_details else "")
        )

    return parsed_sheets


def combine_excel_sheets(
    parsed_sheets: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Menggabungkan hasil seluruh sheet menjadi satu tabel."""

    combined_frames: list[pd.DataFrame] = []

    for sheet_name, dataframe in parsed_sheets.items():
        sheet_dataframe = dataframe.copy()
        sheet_dataframe["source_sheet"] = sheet_name
        combined_frames.append(sheet_dataframe)

    if not combined_frames:
        return pd.DataFrame()

    return pd.concat(
        combined_frames,
        ignore_index=True,
        sort=False,
    )


def parse_and_combine_excel(
    source: str | Path | BinaryIO,
) -> pd.DataFrame:
    """Membaca seluruh sheet lalu menggabungkannya."""

    parsed_sheets = parse_excel_file(source)
    return combine_excel_sheets(parsed_sheets)