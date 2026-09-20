from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


SECONDS_PER_DAY = 24 * 3600


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def zero(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def safe_rate(volume_mm3: float | None, capacite_mm3: float | None) -> float | None:
    if volume_mm3 is None or capacite_mm3 in (None, 0):
        return None

    value = float(volume_mm3) / float(capacite_mm3) * 100

    if value > 100:
        return 100.0

    return value


@dataclass
class HydraulicInputs:
    barrage_code: str

    volume_interval_mm3: float | None
    volume_next_mm3: float | None

    surface_interval_km2: float | None
    surface_next_km2: float | None

    hauteur_bac_mm: float | None
    pluie_mm: float | None

    total_restitutions_m3: float
    capacite_normale_mm3: float | None

    transfert_dar_khrofa_m3: float = 0.0


@dataclass
class HydraulicResult:
    barrage_code: str

    volume_interval_mm3: float | None
    volume_next_mm3: float | None

    surface_interval_km2: float | None
    surface_next_km2: float | None
    surface_moyenne_km2: float | None

    hauteur_bac_mm: float | None
    pluie_mm: float | None
    hauteur_evaporee_mm: float | None
    hauteur_corrigee_mm: float | None

    evaporation_m3: float | None
    evaporation_1000m3: float | None
    debit_evaporation_1000m3s: float | None

    variation_reserve_mm3: float | None

    total_restitutions_m3: float
    transfert_dar_khrofa_m3: float

    apports_raw_m3: float | None
    apports_m3: float | None
    debit_m3s: float | None

    taux_remplissage: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def calculate_hydraulic_balance(inputs: HydraulicInputs) -> HydraulicResult:
    surface_moyenne = None
    if inputs.surface_interval_km2 is not None and inputs.surface_next_km2 is not None:
        surface_moyenne = (
            float(inputs.surface_interval_km2) + float(inputs.surface_next_km2)
        ) / 2

    hauteur_evaporee = None
    hauteur_corrigee = None
    evaporation_m3 = None
    evaporation_1000m3 = None
    debit_evaporation_1000m3s = None

    if (
        inputs.hauteur_bac_mm is not None
        and inputs.pluie_mm is not None
        and surface_moyenne is not None
    ):
        hauteur_evaporee = float(inputs.hauteur_bac_mm) + float(inputs.pluie_mm)
        hauteur_corrigee = hauteur_evaporee * 0.8
        evaporation_m3 = hauteur_corrigee * surface_moyenne * 1000

        # Formule trouvée dans BILAN B.9 AVRIL / EVAPORATION / L10 :
        # L10 = surface_moyenne * hauteur_corrigee
        # donc evaporation_1000m3 = evaporation_m3 / 1000
        evaporation_1000m3 = evaporation_m3 / 1000
        debit_evaporation_1000m3s = evaporation_1000m3 / SECONDS_PER_DAY

    variation_reserve = None
    if inputs.volume_interval_mm3 is not None and inputs.volume_next_mm3 is not None:
        variation_reserve = float(inputs.volume_next_mm3) - float(inputs.volume_interval_mm3)

    apports_raw = None
    apports_m3 = None
    debit_m3s = None

    if variation_reserve is not None and evaporation_m3 is not None:
        apports_raw = (
            variation_reserve * 1_000_000
            + float(inputs.total_restitutions_m3)
            + evaporation_m3
            - zero(inputs.transfert_dar_khrofa_m3)
        )

        apports_m3 = max(0.0, apports_raw)
        debit_m3s = apports_m3 / SECONDS_PER_DAY

    taux = safe_rate(inputs.volume_next_mm3, inputs.capacite_normale_mm3)

    return HydraulicResult(
        barrage_code=inputs.barrage_code,

        volume_interval_mm3=inputs.volume_interval_mm3,
        volume_next_mm3=inputs.volume_next_mm3,

        surface_interval_km2=inputs.surface_interval_km2,
        surface_next_km2=inputs.surface_next_km2,
        surface_moyenne_km2=surface_moyenne,

        hauteur_bac_mm=inputs.hauteur_bac_mm,
        pluie_mm=inputs.pluie_mm,
        hauteur_evaporee_mm=hauteur_evaporee,
        hauteur_corrigee_mm=hauteur_corrigee,

        evaporation_m3=evaporation_m3,
        evaporation_1000m3=evaporation_1000m3,
        debit_evaporation_1000m3s=debit_evaporation_1000m3s,

        variation_reserve_mm3=variation_reserve,

        total_restitutions_m3=float(inputs.total_restitutions_m3),
        transfert_dar_khrofa_m3=zero(inputs.transfert_dar_khrofa_m3),

        apports_raw_m3=apports_raw,
        apports_m3=apports_m3,
        debit_m3s=debit_m3s,

        taux_remplissage=taux,
    )