from __future__ import annotations

import random
from collections import Counter
from typing import Any

import pandas as pd

from database.supabase_client import supabase
from services.category_service import normalize_text


DEFAULT_RECOMMENDATION_LIMIT = 10
GALLON_LIMIT = 30
MEDICAL_GLOVE_REQUIRED = 20
HIJAB_MASK_REQUIRED = 10
NON_HIJAB_MASK_REQUIRED = 10
DEVICE_LIMIT = 1


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default

    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _name(value: Any) -> str:
    return normalize_text(str(value or ""))


def is_hijab_mask(name: str) -> bool:
    text = _name(name)
    return "masker" in text and any(
        token in text
        for token in ("hijab", "headloop", "head loop")
    )


def is_non_hijab_mask(name: str) -> bool:
    text = _name(name)
    if "masker" not in text or is_hijab_mask(text):
        return False

    return any(
        token in text
        for token in (
            "earloop",
            "ear loop",
            "non hijab",
            "medis",
            "surgical",
            "3 ply",
        )
    )


def is_plastic_glove(name: str) -> bool:
    text = _name(name)
    return "sarung tangan" in text and any(
        token in text
        for token in ("plastik", "pe glove", "polyethylene")
    )


def is_medical_glove(name: str) -> bool:
    text = _name(name)

    if is_plastic_glove(text):
        return False

    return "sarung tangan" in text and any(
        token in text
        for token in (
            "medis",
            "medical",
            "nitril",
            "nitrile",
            "latex",
            "karet",
            "rubber",
            "examination",
            "exam glove",
            "surgical glove",
        )
    )


def is_gallon_product(name: str) -> bool:
    text = _name(name)
    return "galon" in text or (
        "air" in text
        and any(token in text for token in ("bio oxy", "ro"))
    )


def is_device_product(name: str) -> bool:
    text = _name(name)

    consumable_tokens = (
        "tinta",
        "toner",
        "cartridge",
        "kabel",
        "baterai",
        "refill",
    )

    if any(token in text for token in consumable_tokens):
        return False

    return any(
        token in text
        for token in (
            "printer",
            "mouse",
            "keyboard",
            "monitor",
            "laptop",
            "komputer",
            "scanner",
            "proyektor",
            "router",
            "ups",
        )
    )


def get_product_family(name: str) -> str:
    if is_hijab_mask(name):
        return "masker_hijab"
    if is_non_hijab_mask(name):
        return "masker_non_hijab"
    if is_medical_glove(name):
        return "sarung_tangan_medis"
    if is_plastic_glove(name):
        return "sarung_tangan_plastik"
    if is_gallon_product(name):
        return "galon"
    if is_device_product(name):
        return "perangkat"
    return _name(name)


def get_recommendation_quantity_limit(name: str) -> int:
    family = get_product_family(name)

    if family == "galon":
        return GALLON_LIMIT
    if family == "sarung_tangan_medis":
        return MEDICAL_GLOVE_REQUIRED
    if family in {"masker_hijab", "masker_non_hijab"}:
        return 10
    if family == "perangkat":
        return DEVICE_LIMIT
    return DEFAULT_RECOMMENDATION_LIMIT


def get_special_reference_price(name: str) -> float | None:
    text = _name(name)

    if "bio oxy" in text:
        return 7_500.0
    if "air ro" in text or ("ro" in text and "galon" in text):
        return 5_000.0
    return None


def get_products_with_history() -> list[dict[str, Any]]:
    response = (
        supabase.table("products")
        .select(
            "id, product_name, normalized_name, default_unit, "
            "usage_count, category_id, categories(name), "
            "price_history(unit, unit_price, quantity, recorded_date)"
        )
        .eq("is_active", True)
        .execute()
    )

    return response.data or []


def get_invoice_items(invoice_id: str) -> list[dict[str, Any]]:
    response = (
        supabase.table("invoice_items")
        .select(
            "id, product_id, raw_description, quantity, unit, "
            "unit_price, total_price, category_id, is_recommended, "
            "categories(name)"
        )
        .eq("invoice_id", invoice_id)
        .execute()
    )

    return response.data or []


def get_invoice(invoice_id: str) -> dict[str, Any] | None:
    response = (
        supabase.table("invoices")
        .select("*")
        .eq("id", invoice_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def calculate_price_statistics(
    price_history: list[dict[str, Any]] | None,
) -> dict[str, float]:
    valid_history = []

    for item in price_history or []:
        unit_price = _safe_float(item.get("unit_price"))
        if unit_price <= 0:
            continue

        valid_history.append(
            {
                "unit_price": unit_price,
                "recorded_date": str(item.get("recorded_date") or ""),
            }
        )

    if not valid_history:
        return {
            "minimum_price": 0.0,
            "maximum_price": 0.0,
            "average_price": 0.0,
            "latest_price": 0.0,
        }

    valid_history.sort(key=lambda item: item["recorded_date"])
    prices = [item["unit_price"] for item in valid_history]

    return {
        "minimum_price": min(prices),
        "maximum_price": max(prices),
        "average_price": sum(prices) / len(prices),
        "latest_price": prices[-1],
    }


def get_existing_product_ids(
    invoice_items: list[dict[str, Any]],
) -> set[str]:
    return {
        str(item["product_id"])
        for item in invoice_items
        if item.get("product_id")
    }


def get_existing_descriptions(
    invoice_items: list[dict[str, Any]],
) -> set[str]:
    return {
        _name(item.get("raw_description"))
        for item in invoice_items
        if _name(item.get("raw_description"))
    }


def get_existing_family_quantities(
    invoice_items: list[dict[str, Any]],
) -> Counter:
    quantities: Counter = Counter()

    for item in invoice_items:
        family = get_product_family(item.get("raw_description") or "")
        quantities[family] += max(_safe_float(item.get("quantity")), 0)

    return quantities


def get_category_name(record: dict[str, Any]) -> str | None:
    category_data = record.get("categories")

    if isinstance(category_data, dict):
        category_name = category_data.get("name")
        if category_name:
            return str(category_name)

    return None


def get_category_frequencies(
    invoice_items: list[dict[str, Any]],
) -> Counter:
    categories = []

    for item in invoice_items:
        category_name = get_category_name(item)
        if category_name:
            categories.append(category_name)

    return Counter(categories)


def _required_quantity_for_family(
    family: str,
    existing_family_quantities: Counter,
) -> int:
    required_map = {
        "masker_hijab": HIJAB_MASK_REQUIRED,
        "masker_non_hijab": NON_HIJAB_MASK_REQUIRED,
        "sarung_tangan_medis": MEDICAL_GLOVE_REQUIRED,
    }

    required = required_map.get(family, 0)
    existing = int(existing_family_quantities.get(family, 0))
    return max(required - existing, 0)


def score_product(
    product: dict[str, Any],
    category_frequencies: Counter,
    budget_gap: float,
    existing_family_quantities: Counter | None = None,
) -> float:
    score = 0.0
    usage_count = int(product.get("usage_count") or 0)
    score += min(usage_count, 20) * 1.5

    category_name = get_category_name(product)
    if category_name:
        score += category_frequencies.get(category_name, 0) * 5

    product_name = (
        product.get("product_name")
        or product.get("normalized_name")
        or ""
    )
    family = get_product_family(product_name)

    missing_required = _required_quantity_for_family(
        family,
        existing_family_quantities or Counter(),
    )

    if missing_required > 0:
        score += 1_000 + missing_required

    price_stats = calculate_price_statistics(product.get("price_history"))
    reference_price = (
        get_special_reference_price(product_name)
        or price_stats["latest_price"]
        or price_stats["average_price"]
    )

    if reference_price > 0 and budget_gap > 0:
        if reference_price <= budget_gap:
            score += 10

        ratio = reference_price / budget_gap
        if 0.05 <= ratio <= 0.40:
            score += 8
        elif ratio <= 0.75:
            score += 4

    return score


def _randomize_recommendations(
    recommendations: list[dict[str, Any]],
    limit: int,
    random_seed: int | None = None,
) -> list[dict[str, Any]]:
    """
    Mengacak rekomendasi secara terkontrol.

    Untuk kebutuhan wajib berbasis product family, hanya satu produk terbaik
    dipilih per family. Contoh: sarung tangan latex S/M/L tetap dihitung sebagai
    satu family sarung tangan medis dengan total kebutuhan 20.
    """

    if not recommendations or limit <= 0:
        return []

    generator = random.Random(random_seed)

    mandatory_candidates = [
        item
        for item in recommendations
        if bool(item.get("is_mandatory"))
    ]
    regular = [
        item
        for item in recommendations
        if not bool(item.get("is_mandatory"))
    ]

    # Satu pilihan terbaik untuk setiap family wajib.
    mandatory_by_family: dict[str, dict[str, Any]] = {}

    for item in mandatory_candidates:
        family = str(
            item.get("product_family")
            or get_product_family(item.get("product_name") or "")
        )

        current = mandatory_by_family.get(family)

        if current is None:
            mandatory_by_family[family] = item
            continue

        current_key = (
            _safe_float(current.get("score")),
            int(current.get("usage_count") or 0),
            -_safe_float(current.get("suggested_unit_price")),
        )
        candidate_key = (
            _safe_float(item.get("score")),
            int(item.get("usage_count") or 0),
            -_safe_float(item.get("suggested_unit_price")),
        )

        if candidate_key > current_key:
            mandatory_by_family[family] = item

    mandatory = sorted(
        mandatory_by_family.values(),
        key=lambda item: (
            int(item.get("priority") or 0),
            _safe_float(item.get("score")),
        ),
        reverse=True,
    )

    selected_families = {
        str(item.get("product_family") or "")
        for item in mandatory
    }

    # Jangan masukkan varian lain dari family wajib yang sudah dipilih.
    regular = [
        item
        for item in regular
        if str(item.get("product_family") or "") not in selected_families
    ]

    remaining_limit = max(limit - len(mandatory), 0)

    ordered = sorted(
        regular,
        key=lambda item: (
            _safe_float(item.get("score")),
            int(item.get("usage_count") or 0),
        ),
        reverse=True,
    )

    pool_size = min(
        len(ordered),
        max(remaining_limit * 4, remaining_limit),
    )
    candidate_pool = ordered[:pool_size]
    weighted_candidates = []

    for index, item in enumerate(candidate_pool):
        base_score = max(_safe_float(item.get("score")), 0.0)
        rank_bonus = (pool_size - index) / max(pool_size, 1)
        random_bonus = generator.uniform(0.0, 8.0)

        weighted_candidates.append(
            (base_score + rank_bonus + random_bonus, item)
        )

    weighted_candidates.sort(
        key=lambda pair: pair[0],
        reverse=True,
    )

    selected = mandatory[:limit]
    selected.extend(
        item
        for _, item in weighted_candidates[:remaining_limit]
    )

    return selected[:limit]


def recommend_new_products(
    invoice_id: str,
    limit: int = 10,
    random_seed: int | None = None,
    exclude_product_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    invoice = get_invoice(invoice_id)

    if not invoice:
        raise ValueError("Invoice tidak ditemukan.")

    invoice_items = get_invoice_items(invoice_id)
    products = get_products_with_history()

    existing_product_ids = get_existing_product_ids(invoice_items)
    existing_product_ids.update(
        str(product_id)
        for product_id in (exclude_product_ids or set())
        if product_id
    )

    existing_descriptions = get_existing_descriptions(invoice_items)
    existing_families = get_existing_family_quantities(invoice_items)
    category_frequencies = get_category_frequencies(invoice_items)

    target_budget = _safe_float(invoice.get("target_budget"))
    current_total = _safe_float(
        invoice.get("final_total")
        or invoice.get("original_total")
    )
    budget_gap = max(target_budget - current_total, 0.0)

    recommendations: list[dict[str, Any]] = []

    for product in products:
        product_id = str(product.get("id") or "")
        product_name = (
            product.get("product_name")
            or product.get("normalized_name")
            or ""
        )
        normalized_name = _name(product_name)

        if not product_id or product_id in existing_product_ids:
            continue

        if normalized_name and normalized_name in existing_descriptions:
            continue

        family = get_product_family(product_name)

        # Produk satu family wajib boleh tetap masuk hanya bila kebutuhan
        # family tersebut belum terpenuhi.
        missing_required = _required_quantity_for_family(
            family,
            existing_families,
        )
        is_mandatory = missing_required > 0

        price_stats = calculate_price_statistics(product.get("price_history"))
        reference_price = (
            get_special_reference_price(product_name)
            or price_stats["latest_price"]
            or price_stats["average_price"]
        )

        if reference_price <= 0:
            continue

        quantity_limit = get_recommendation_quantity_limit(product_name)

        if is_mandatory:
            suggested_quantity = min(missing_required, quantity_limit)
        elif budget_gap > 0:
            suggested_quantity = max(
                1,
                min(
                    int(budget_gap // reference_price),
                    quantity_limit,
                ),
            )
        else:
            suggested_quantity = 1

        category_name = get_category_name(product)
        score = score_product(
            product=product,
            category_frequencies=category_frequencies,
            budget_gap=budget_gap,
            existing_family_quantities=existing_families,
        )

        reason_parts = ["Barang tersedia pada database INVOXA"]

        if is_mandatory:
            reason_parts.append("memenuhi aturan APD wajib")
        if category_name:
            reason_parts.append(f"kategori {category_name}")
        if int(product.get("usage_count") or 0) > 0:
            reason_parts.append("pernah digunakan sebelumnya")
        if budget_gap > 0 and reference_price <= budget_gap:
            reason_parts.append("harga sesuai sisa pagu")
        if get_special_reference_price(product_name):
            reason_parts.append("menggunakan harga acuan khusus")

        recommendations.append(
            {
                "product_id": product_id,
                "product_name": product_name,
                "product_family": family,
                "category": category_name or "Belum Dikategorikan",
                "unit": product.get("default_unit") or "pcs",
                "suggested_quantity": float(suggested_quantity),
                "quantity_limit": int(quantity_limit),
                "suggested_unit_price": float(reference_price),
                "estimated_total": float(
                    suggested_quantity * reference_price
                ),
                "average_price": float(price_stats["average_price"]),
                "minimum_price": float(price_stats["minimum_price"]),
                "maximum_price": float(price_stats["maximum_price"]),
                "latest_price": float(price_stats["latest_price"]),
                "usage_count": int(product.get("usage_count") or 0),
                "score": float(score),
                "priority": 100 if is_mandatory else 0,
                "is_mandatory": is_mandatory,
                "reason": "; ".join(reason_parts),
            }
        )

    return _randomize_recommendations(
        recommendations=recommendations,
        limit=max(int(limit), 0),
        random_seed=random_seed,
    )


def recommend_replacement_product(
    invoice_id: str,
    replaced_product_id: str,
    visible_product_ids: set[str] | None,
    old_product_name: str,
    old_category: str,
    old_total: float,
    random_seed: int | None = None,
) -> dict[str, Any] | None:
    """
    Mencari satu produk pengganti untuk satu baris rekomendasi.

    Ketentuan:
    - produk yang sudah ada pada invoice tidak boleh dipilih;
    - produk rekomendasi lain yang sedang tampil tidak boleh dipilih;
    - produk yang diganti juga dikecualikan;
    - family APD wajib harus tetap sama;
    - barang biasa memprioritaskan kategori yang sama;
    - nilai total kandidat dipilih sedekat mungkin dengan nilai barang lama.
    """

    invoice = get_invoice(invoice_id)

    if not invoice:
        raise ValueError("Invoice tidak ditemukan.")

    invoice_items = get_invoice_items(invoice_id)
    products = get_products_with_history()

    excluded_ids = get_existing_product_ids(invoice_items)
    excluded_ids.update(
        str(product_id)
        for product_id in (visible_product_ids or set())
        if product_id
    )

    if replaced_product_id:
        excluded_ids.add(str(replaced_product_id))

    old_family = get_product_family(old_product_name)
    protected_families = {
        "masker_hijab",
        "masker_non_hijab",
        "sarung_tangan_medis",
    }

    normalized_old_category = str(old_category or "").strip().lower()
    target_total = max(_safe_float(old_total), 0.0)
    generator = random.Random(random_seed)

    candidates: list[dict[str, Any]] = []

    for product in products:
        product_id = str(product.get("id") or "")

        if not product_id or product_id in excluded_ids:
            continue

        product_name = (
            product.get("product_name")
            or product.get("normalized_name")
            or ""
        )

        if not product_name:
            continue

        family = get_product_family(product_name)
        category_name = (
            get_category_name(product)
            or "Belum Dikategorikan"
        )

        # APD wajib hanya boleh diganti dengan family yang sama.
        if old_family in protected_families:
            if family != old_family:
                continue
        else:
            # Barang biasa jangan mengambil family APD wajib.
            if family in protected_families:
                continue

        price_stats = calculate_price_statistics(
            product.get("price_history")
        )

        reference_price = (
            get_special_reference_price(product_name)
            or price_stats["latest_price"]
            or price_stats["average_price"]
        )

        if reference_price <= 0:
            continue

        quantity_limit = get_recommendation_quantity_limit(
            product_name
        )

        if old_family in protected_families:
            if old_family == "sarung_tangan_medis":
                suggested_quantity = MEDICAL_GLOVE_REQUIRED
            else:
                suggested_quantity = 10
        elif target_total > 0:
            suggested_quantity = max(
                1,
                min(
                    int(round(target_total / reference_price)),
                    quantity_limit,
                ),
            )
        else:
            suggested_quantity = 1

        estimated_total = (
            suggested_quantity * reference_price
        )

        same_category = (
            str(category_name).strip().lower()
            == normalized_old_category
        )

        # Prioritas utama: family wajib, kategori sama, lalu total terdekat.
        category_penalty = 0.0 if same_category else max(
            target_total * 0.20,
            50_000.0,
        )

        distance = abs(estimated_total - target_total)
        random_tiebreaker = generator.uniform(0.0, 1.0)

        candidates.append(
            {
                "product_id": product_id,
                "product_name": product_name,
                "product_family": family,
                "category": category_name,
                "unit": product.get("default_unit") or "pcs",
                "suggested_quantity": float(suggested_quantity),
                "quantity_limit": int(quantity_limit),
                "suggested_unit_price": float(reference_price),
                "estimated_total": float(estimated_total),
                "average_price": float(
                    price_stats["average_price"]
                ),
                "minimum_price": float(
                    price_stats["minimum_price"]
                ),
                "maximum_price": float(
                    price_stats["maximum_price"]
                ),
                "latest_price": float(
                    price_stats["latest_price"]
                ),
                "usage_count": int(
                    product.get("usage_count") or 0
                ),
                "score": float(
                    int(product.get("usage_count") or 0)
                ),
                "priority": (
                    100
                    if old_family in protected_families
                    else 0
                ),
                "is_mandatory": (
                    old_family in protected_families
                ),
                "reason": (
                    "Pengganti satu item; "
                    + (
                        "family wajib dipertahankan; "
                        if old_family in protected_families
                        else ""
                    )
                    + (
                        "kategori sama; "
                        if same_category
                        else ""
                    )
                    + "nilai dipilih mendekati barang lama"
                ),
                "_selection_key": (
                    category_penalty + distance,
                    -int(product.get("usage_count") or 0),
                    random_tiebreaker,
                ),
            }
        )

    if not candidates:
        return None

    selected = min(
        candidates,
        key=lambda item: item["_selection_key"],
    ).copy()

    selected.pop("_selection_key", None)

    return selected


def recommend_price_and_quantity_changes(
    invoice_id: str,
) -> list[dict[str, Any]]:
    invoice = get_invoice(invoice_id)

    if not invoice:
        raise ValueError("Invoice tidak ditemukan.")

    invoice_items = get_invoice_items(invoice_id)
    products = get_products_with_history()
    product_map = {
        str(product["id"]): product
        for product in products
        if product.get("id")
    }

    target_budget = _safe_float(invoice.get("target_budget"))
    current_total = _safe_float(
        invoice.get("final_total")
        or invoice.get("original_total")
    )
    remaining_budget = max(target_budget - current_total, 0.0)

    recommendations: list[dict[str, Any]] = []

    for item in invoice_items:
        product_id = str(item.get("product_id") or "")
        if not product_id or product_id not in product_map:
            continue

        product = product_map[product_id]
        price_stats = calculate_price_statistics(product.get("price_history"))
        average_price = price_stats["average_price"]

        if average_price <= 0:
            continue

        current_quantity = max(_safe_float(item.get("quantity"), 1.0), 1.0)
        current_unit_price = max(_safe_float(item.get("unit_price")), 0.0)
        suggested_unit_price = current_unit_price
        suggested_quantity = current_quantity
        reason_parts = []

        if current_unit_price > average_price * 1.15:
            suggested_unit_price = average_price
            reason_parts.append(
                "harga saat ini lebih tinggi dari rata-rata database"
            )
        elif current_unit_price < average_price * 0.85:
            suggested_unit_price = average_price
            reason_parts.append(
                "harga saat ini lebih rendah dari rata-rata database"
            )

        # Batas rekomendasi hanya mengikat item hasil rekomendasi.
        is_recommended = bool(item.get("is_recommended"))
        quantity_limit = (
            get_recommendation_quantity_limit(
                item.get("raw_description") or ""
            )
            if is_recommended
            else None
        )

        if remaining_budget > 0 and suggested_unit_price > 0:
            affordable_addition = int(
                remaining_budget // suggested_unit_price
            )

            if affordable_addition > 0:
                proposed_quantity = current_quantity + affordable_addition

                if quantity_limit is not None:
                    proposed_quantity = min(
                        proposed_quantity,
                        quantity_limit,
                    )

                addition = max(
                    int(proposed_quantity - current_quantity),
                    0,
                )

                if addition > 0:
                    suggested_quantity = current_quantity + addition
                    remaining_budget -= addition * suggested_unit_price
                    reason_parts.append(
                        "kuantitas dapat ditambah untuk mendekati target pagu"
                    )

        if (
            suggested_unit_price != current_unit_price
            or suggested_quantity != current_quantity
        ):
            old_total = current_quantity * current_unit_price
            new_total = suggested_quantity * suggested_unit_price

            recommendations.append(
                {
                    "invoice_item_id": item.get("id"),
                    "product_id": product_id,
                    "product_name": item.get("raw_description"),
                    "old_quantity": current_quantity,
                    "suggested_quantity": suggested_quantity,
                    "old_unit_price": current_unit_price,
                    "suggested_unit_price": suggested_unit_price,
                    "old_total": old_total,
                    "suggested_total": new_total,
                    "estimated_difference": new_total - old_total,
                    "reason": "; ".join(reason_parts),
                }
            )

    return recommendations


def build_recommendation_summary(
    invoice_id: str,
    limit: int = 10,
    random_seed: int | None = None,
    exclude_product_ids: set[str] | None = None,
) -> dict[str, Any]:
    invoice = get_invoice(invoice_id)

    if not invoice:
        raise ValueError("Invoice tidak ditemukan.")

    target_budget = _safe_float(invoice.get("target_budget"))
    current_total = _safe_float(
        invoice.get("final_total")
        or invoice.get("original_total")
    )

    return {
        "invoice": invoice,
        "target_budget": target_budget,
        "current_total": current_total,
        "budget_gap": target_budget - current_total,
        "new_products": recommend_new_products(
            invoice_id=invoice_id,
            limit=limit,
            random_seed=random_seed,
            exclude_product_ids=exclude_product_ids,
        ),
        "adjustments": recommend_price_and_quantity_changes(
            invoice_id=invoice_id,
        ),
    }