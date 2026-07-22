from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from utils.common import prepare_dataframe, numeric_value


@dataclass
class AdjustmentResult:
    dataframe: pd.DataFrame
    original_total: float
    revised_total: float
    target: float
    difference: float
    reached: bool
    message: str


def round_to_step(value: float, step: int) -> float:
    if step <= 1:
        return round(value)
    return round(value / step) * step


def simulate_budget_adjustment(
    source: pd.DataFrame,
    target: float,
    max_percent: float,
    rounding_step: int,
    tolerance: float,
) -> AdjustmentResult:
    df = prepare_dataframe(source).copy()

    df["Harga Asli"] = df["Harga"]
    df["Jumlah Asli"] = df["Jumlah"]
    df["Persentase"] = 0.0
    df["Harga Usulan"] = df["Harga"]
    df["Jumlah Usulan"] = df["Jumlah"]

    original_total = float(df["Jumlah"].sum())

    if target <= original_total:
        difference = target - original_total
        return AdjustmentResult(
            dataframe=df,
            original_total=original_total,
            revised_total=original_total,
            target=target,
            difference=difference,
            reached=abs(difference) <= tolerance,
            message=(
                "Target tidak lebih besar dari total saat ini. "
                "Tidak ada kenaikan yang diterapkan."
            ),
        )

    adjustable = df.index[
        (~df["Kunci"])
        & (df["Kuantitas"] > 0)
        & (df["Harga"] > 0)
    ].tolist()

    if not adjustable:
        return AdjustmentResult(
            dataframe=df,
            original_total=original_total,
            revised_total=original_total,
            target=target,
            difference=target - original_total,
            reached=False,
            message="Tidak ada item yang dapat disesuaikan.",
        )

    # Barang mahal diberi batas lebih kecil agar perubahan lebih natural.
    caps = {}
    for idx in adjustable:
        price = numeric_value(df.at[idx, "Harga"])
        if price < 20_000:
            cap = max_percent
        elif price <= 100_000:
            cap = max_percent * 0.8
        elif price <= 500_000:
            cap = max_percent * 0.6
        else:
            cap = max_percent * 0.4
        caps[idx] = max(cap, 0.0)

    increment = 0.25
    max_iterations = max(200, len(adjustable) * 100)

    for _ in range(max_iterations):
        current_total = float(df["Jumlah Usulan"].sum())
        remaining = target - current_total

        if abs(remaining) <= tolerance:
            break

        candidates = []

        for idx in adjustable:
            current_pct = numeric_value(df.at[idx, "Persentase"])
            if current_pct + increment > caps[idx] + 1e-9:
                continue

            original_price = numeric_value(df.at[idx, "Harga Asli"])
            qty = numeric_value(df.at[idx, "Kuantitas"])
            trial_pct = current_pct + increment
            trial_price = round_to_step(
                original_price * (1 + trial_pct / 100),
                rounding_step,
            )
            trial_total = trial_price * qty
            delta = trial_total - numeric_value(df.at[idx, "Jumlah Usulan"])

            if delta <= 0:
                continue

            projected_difference = abs(remaining - delta)
            candidates.append((projected_difference, delta, idx, trial_pct, trial_price))

        if not candidates:
            break

        candidates.sort(key=lambda x: (x[0], x[1]))
        _, _, idx, new_pct, new_price = candidates[0]

        qty = numeric_value(df.at[idx, "Kuantitas"])
        prospective_total = (
            float(df["Jumlah Usulan"].sum())
            - numeric_value(df.at[idx, "Jumlah Usulan"])
            + new_price * qty
        )

        if prospective_total > target + tolerance:
            remaining_for_row = target - (
                float(df["Jumlah Usulan"].sum())
                - numeric_value(df.at[idx, "Jumlah Usulan"])
            )
            exact_price = round_to_step(remaining_for_row / qty, rounding_step)
            original_price = numeric_value(df.at[idx, "Harga Asli"])
            max_price = original_price * (1 + caps[idx] / 100)

            if original_price <= exact_price <= max_price:
                new_price = exact_price
                new_pct = ((new_price / original_price) - 1) * 100
            else:
                caps[idx] = numeric_value(df.at[idx, "Persentase"])
                continue

        df.at[idx, "Persentase"] = round(new_pct, 2)
        df.at[idx, "Harga Usulan"] = new_price
        df.at[idx, "Jumlah Usulan"] = new_price * qty

    revised_total = float(df["Jumlah Usulan"].sum())
    difference = target - revised_total
    reached = abs(difference) <= tolerance

    message = (
        "Simulasi berhasil mendekati target."
        if reached
        else "Target belum dapat dicapai dalam batas yang dipilih."
    )

    return AdjustmentResult(
        dataframe=df,
        original_total=original_total,
        revised_total=revised_total,
        target=target,
        difference=difference,
        reached=reached,
        message=message,
    )
