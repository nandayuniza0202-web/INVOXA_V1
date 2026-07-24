from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from database.supabase_client import supabase
from services.category_service import normalize_text


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default

    try:
        if pd.isna(value):
            return default
    except Exception:
        pass

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_products_with_history() -> list[dict[str, Any]]:
    """
    Mengambil master barang beserta kategori dan riwayat harga.
    """

    response = (
        supabase.table("products")
        .select(
            "id, product_name, normalized_name, default_unit, "
            "usage_count, category_id, "
            "categories(name), "
            "price_history(unit, unit_price, quantity, recorded_date)"
        )
        .eq("is_active", True)
        .execute()
    )

    return response.data or []


def get_invoice_items(invoice_id: str) -> list[dict[str, Any]]:
    """
    Mengambil item yang sudah ada pada invoice tertentu.
    """

    response = (
        supabase.table("invoice_items")
        .select(
            "id, product_id, raw_description, quantity, unit, "
            "unit_price, total_price, category_id, categories(name)"
        )
        .eq("invoice_id", invoice_id)
        .execute()
    )

    return response.data or []


def get_invoice(invoice_id: str) -> dict[str, Any] | None:
    """
    Mengambil metadata invoice.
    """

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
    """
    Menghitung statistik harga dari riwayat produk.
    """

    prices = [
        _safe_float(item.get("unit_price"))
        for item in (price_history or [])
        if _safe_float(item.get("unit_price")) > 0
    ]

    if not prices:
        return {
            "minimum_price": 0.0,
            "maximum_price": 0.0,
            "average_price": 0.0,
            "latest_price": 0.0,
        }

    latest_price = prices[-1]

    return {
        "minimum_price": min(prices),
        "maximum_price": max(prices),
        "average_price": sum(prices) / len(prices),
        "latest_price": latest_price,
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
        normalize_text(item.get("raw_description", ""))
        for item in invoice_items
        if normalize_text(item.get("raw_description", ""))
    }


def get_category_frequencies(
    invoice_items: list[dict[str, Any]],
) -> Counter:
    """
    Menghitung kategori yang dominan pada invoice aktif.
    """

    categories = []

    for item in invoice_items:
        category_data = item.get("categories")
        category_name = None

        if isinstance(category_data, dict):
            category_name = category_data.get("name")

        if category_name:
            categories.append(category_name)

    return Counter(categories)


def score_product(
    product: dict[str, Any],
    category_frequencies: Counter,
    budget_gap: float,
) -> float:
    """
    Memberi skor awal untuk rekomendasi produk.
    """

    score = 0.0

    usage_count = int(product.get("usage_count") or 0)
    score += min(usage_count, 20) * 1.5

    category_data = product.get("categories")
    category_name = None

    if isinstance(category_data, dict):
        category_name = category_data.get("name")

    if category_name:
        score += category_frequencies.get(category_name, 0) * 5

    price_stats = calculate_price_statistics(
        product.get("price_history")
    )

    reference_price = (
        price_stats["latest_price"]
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


def recommend_new_products(
    invoice_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Merekomendasikan barang baru yang belum ada pada invoice aktif.
    """

    invoice = get_invoice(invoice_id)

    if not invoice:
        raise ValueError("Invoice tidak ditemukan.")

    invoice_items = get_invoice_items(invoice_id)
    products = get_products_with_history()

    existing_product_ids = get_existing_product_ids(invoice_items)
    existing_descriptions = get_existing_descriptions(invoice_items)
    category_frequencies = get_category_frequencies(invoice_items)

    target_budget = _safe_float(invoice.get("target_budget"))
    current_total = _safe_float(
        invoice.get("final_total")
        or invoice.get("original_total")
    )

    budget_gap = max(target_budget - current_total, 0)

    recommendations = []

    for product in products:
        product_id = str(product.get("id") or "")
        normalized_name = normalize_text(
            product.get("normalized_name")
            or product.get("product_name")
            or ""
        )

        if not product_id or product_id in existing_product_ids:
            continue

        if normalized_name in existing_descriptions:
            continue

        price_stats = calculate_price_statistics(
            product.get("price_history")
        )

        reference_price = (
            price_stats["latest_price"]
            or price_stats["average_price"]
        )

        if reference_price <= 0:
            continue

        category_data = product.get("categories")
        category_name = None

        if isinstance(category_data, dict):
            category_name = category_data.get("name")

        score = score_product(
            product=product,
            category_frequencies=category_frequencies,
            budget_gap=budget_gap,
        )

        suggested_quantity = 1.0

        if budget_gap > 0 and reference_price > 0:
            suggested_quantity = max(
                1,
                min(
                    int(budget_gap // reference_price),
                    10,
                ),
            )

        estimated_total = (
            suggested_quantity * reference_price
        )

        recommendations.append(
            {
                "product_id": product_id,
                "product_name": product.get("product_name"),
                "category": (
                    category_name
                    or "Belum Dikategorikan"
                ),
                "unit": product.get("default_unit") or "pcs",
                "suggested_quantity": float(
                    suggested_quantity
                ),
                "suggested_unit_price": float(
                    reference_price
                ),
                "estimated_total": float(
                    estimated_total
                ),
                "average_price": float(
                    price_stats["average_price"]
                ),
                "minimum_price": float(
                    price_stats["minimum_price"]
                ),
                "maximum_price": float(
                    price_stats["maximum_price"]
                ),
                "usage_count": int(
                    product.get("usage_count") or 0
                ),
                "score": float(score),
                "reason": (
                    "Barang pernah digunakan pada invoice sebelumnya"
                    + (
                        f" dan sesuai kategori {category_name}"
                        if category_name
                        else ""
                    )
                ),
            }
        )

    recommendations.sort(
        key=lambda item: (
            item["score"],
            item["usage_count"],
        ),
        reverse=True,
    )

    return recommendations[:limit]


def recommend_price_and_quantity_changes(
    invoice_id: str,
) -> list[dict[str, Any]]:
    """
    Membuat rekomendasi perubahan harga dan kuantitas
    untuk barang yang sudah ada.
    """

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

    budget_gap = target_budget - current_total

    recommendations = []

    for item in invoice_items:
        product_id = str(item.get("product_id") or "")

        if not product_id or product_id not in product_map:
            continue

        product = product_map[product_id]

        price_stats = calculate_price_statistics(
            product.get("price_history")
        )

        average_price = price_stats["average_price"]

        if average_price <= 0:
            continue

        current_quantity = _safe_float(
            item.get("quantity"),
            1,
        )
        current_unit_price = _safe_float(
            item.get("unit_price")
        )

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

        if budget_gap > 0 and suggested_unit_price > 0:
            additional_quantity = int(
                budget_gap // suggested_unit_price
            )

            if additional_quantity > 0:
                suggested_quantity = (
                    current_quantity
                    + min(additional_quantity, 10)
                )
                reason_parts.append(
                    "kuantitas dapat ditambah untuk mendekati target pagu"
                )

        if (
            suggested_unit_price != current_unit_price
            or suggested_quantity != current_quantity
        ):
            old_total = current_quantity * current_unit_price
            new_total = (
                suggested_quantity
                * suggested_unit_price
            )

            recommendations.append(
                {
                    "invoice_item_id": item.get("id"),
                    "product_id": product_id,
                    "product_name": item.get(
                        "raw_description"
                    ),
                    "old_quantity": current_quantity,
                    "suggested_quantity": (
                        suggested_quantity
                    ),
                    "old_unit_price": current_unit_price,
                    "suggested_unit_price": (
                        suggested_unit_price
                    ),
                    "old_total": old_total,
                    "suggested_total": new_total,
                    "estimated_difference": (
                        new_total - old_total
                    ),
                    "reason": "; ".join(reason_parts),
                }
            )

    return recommendations


def build_recommendation_summary(
    invoice_id: str,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Menghasilkan seluruh paket rekomendasi invoice.
    """

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
        ),
        "adjustments": (
            recommend_price_and_quantity_changes(
                invoice_id=invoice_id,
            )
        ),
    }