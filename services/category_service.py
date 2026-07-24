import re
from typing import Any

from database.supabase_client import supabase


def normalize_text(text: str) -> str:
    """Membersihkan teks agar lebih mudah dicocokkan."""

    text = str(text or "").lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text


def get_categories() -> list[dict[str, Any]]:
    """Mengambil seluruh kategori dari Supabase."""

    response = (
        supabase.table("categories")
        .select("id, name, description")
        .order("name")
        .execute()
    )

    return response.data or []


def get_category_by_name(category_name: str) -> dict[str, Any] | None:
    """Mengambil satu kategori berdasarkan nama."""

    response = (
        supabase.table("categories")
        .select("id, name, description")
        .eq("name", category_name)
        .limit(1)
        .execute()
    )

    return response.data[0] if response.data else None


def get_uncategorized_category() -> dict[str, Any] | None:
    """Mengambil kategori cadangan Belum Dikategorikan."""

    return get_category_by_name("Belum Dikategorikan")
from typing import Any

from database.supabase_client import supabase


CATEGORY_RULES = {
    "APD": [
        "masker",
        "sarung tangan",
        "kaos tangan",
        "nitrile",
        "latex",
        "helm",
        "rompi",
        "sepatu safety",
        "penutup kepala",
        "hairnet",
    ],
    "Alat Kebersihan": [
        "sunlight",
        "mama lemon",
        "sabun",
        "detergen",
        "tissu",
        "tissue",
        "pembersih",
        "wipol",
        "bayclin",
        "sapu",
        "pel",
        "sikat",
        "disinfektan",
    ],
    "Alat Kelengkapan": [
        "plastik",
        "bento",
        "wrapping",
        "tali",
        "baterai",
        "balon",
        "amplop",
        "kertas",
        "galon",
        "gembok",
        "cling",
        "ember",
        "gayung",
        "rak",
        "wadah",
    ],
}


def predict_category(description: str) -> dict[str, Any] | None:
    """Menentukan kategori berdasarkan nama barang."""

    normalized_description = normalize_text(description)

    best_category_name = "Belum Dikategorikan"
    best_score = 0

    for category_name, keywords in CATEGORY_RULES.items():
        score = 0

        for keyword in keywords:
            normalized_keyword = normalize_text(keyword)

            if normalized_keyword in normalized_description:
                score += len(normalized_keyword.split())

        if score > best_score:
            best_score = score
            best_category_name = category_name

    category = get_category_by_name(best_category_name)

    if not category:
        return None

    return {
        "category_id": category["id"],
        "category_name": category["name"],
        "confidence": 0.9 if best_score > 0 else 0.0,
        "source": "keyword" if best_score > 0 else "automatic",
    }


def apply_predicted_categories(dataframe):
    """Mengisi kategori kosong pada DataFrame."""

    dataframe = dataframe.copy()

    for index, row in dataframe.iterrows():
        current_category = row.get("category")

        if current_category and str(current_category).strip():
            continue

        prediction = predict_category(
            row.get("raw_description", "")
        )

        if prediction:
            dataframe.at[index, "category"] = (
                prediction["category_name"]
            )

    return dataframe