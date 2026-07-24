from pathlib import Path
from typing import BinaryIO

import pandas as pd

from services.parsers.column_mapper import standardize_dataframe


def detect_csv_separator(
    source: str | Path | BinaryIO,
) -> str:
    """
    Mendeteksi pemisah CSV:
    koma, titik koma, tab, atau garis vertikal.
    """

    separators = [",", ";", "\t", "|"]
    best_separator = ","
    best_column_count = 0

    for separator in separators:
        try:
            preview = pd.read_csv(
                source,
                sep=separator,
                nrows=10,
                dtype=object,
                engine="python",
            )

            column_count = len(preview.columns)

            if column_count > best_column_count:
                best_column_count = column_count
                best_separator = separator

            if hasattr(source, "seek"):
                source.seek(0)

        except Exception:
            if hasattr(source, "seek"):
                source.seek(0)

    return best_separator


def parse_csv_file(
    source: str | Path | BinaryIO,
) -> pd.DataFrame:
    """
    Membaca CSV dan mengubahnya ke format standar INVOXA.
    """

    separator = detect_csv_separator(source)

    if hasattr(source, "seek"):
        source.seek(0)

    encodings = [
        "utf-8-sig",
        "utf-8",
        "latin-1",
        "cp1252",
    ]

    last_error: Exception | None = None

    for encoding in encodings:
        try:
            if hasattr(source, "seek"):
                source.seek(0)

            dataframe = pd.read_csv(
                source,
                sep=separator,
                dtype=object,
                encoding=encoding,
                engine="python",
            )

            return standardize_dataframe(dataframe)

        except Exception as error:
            last_error = error

    raise ValueError(
        "File CSV tidak berhasil dibaca. "
        f"Kesalahan terakhir: {last_error}"
    )