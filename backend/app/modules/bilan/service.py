from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.modules.bilan.mappings import (
    BILAN_CONFIGS,
    SUPPORTED_BARRAGE_CODES,
    get_bilan_config,
    input_field_by_code,
    normalize_barrage_code,
    total_restitution_codes,
)
from app.modules.bilan.repository import (
    existing_bilan_id,
    fetch_bilan_enabled_barrages,
    fetch_boem_transfers_by_dates,
    fetch_dynamic_bilan_input_fields,
    fetch_month_bilans,
    fetch_month_restitutions,
    fetch_supported_barrages,
)
from app.modules.bilan.schemas import (
    BilanComputeRequest,
    BilanDailyInput,
    BilanRestitutionInput,
    BilanSaveRequest,
)
from app.modules.calculs.repository import (
    ensure_journee_situation,
    lookup_bareme_exact,
    upsert_bilan,
    upsert_bilan_variable,
    upsert_restitution,
)
from app.services.hydraulic_calculator import HydraulicInputs, calculate_hydraulic_balance


ALLOWED_STATUSES = {"BROUILLON", "INCOMPLET", "CALCULE", "VALIDE"}


def zero(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def safe_rate(volume_mm3: float | None, capacity_mm3: float | None) -> float | None:
    if volume_mm3 is None or capacity_mm3 in (None, 0):
        return None
    return min(100.0, float(volume_mm3) / float(capacity_mm3) * 100.0)


def month_bounds(year: int, month: int) -> tuple[date, date, date]:
    if month < 1 or month > 12:
        raise ValueError("Le mois doit être compris entre 1 et 12.")
    start = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    next_day = last + timedelta(days=1)
    return start, last, next_day


def month_dates(year: int, month: int) -> list[date]:
    start, last, _ = month_bounds(year, month)
    count = (last - start).days + 1
    return [start + timedelta(days=index) for index in range(count)]


def add_check(checks: list[dict], level: str, code: str, field: str, message: str):
    checks.append(
        {
            "niveau": level,
            "code": code,
            "champ": field,
            "message": message,
        }
    )


def has_blocking(checks: list[dict]) -> bool:
    return any(item["niveau"] == "BLOQUANT" for item in checks)



def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _make_dynamic_bilan_config(barrage: dict, fields: list[dict]) -> dict:
    """
    Configuration BILAN générique pour un barrage ajouté depuis l'interface.
    Elle ne remplace pas les configurations officielles existantes.
    """
    restitution_count = len(fields)
    first_restitution_col = 6  # F
    total_col_index = first_restitution_col + restitution_count
    apports_col_index = total_col_index + 1
    debit_col_index = apports_col_index + 1
    pluie_col_index = debit_col_index + 1

    return {
        "template": "__DYNAMIC_BILAN__",
        "display_name": barrage.get("nom") or barrage.get("code"),
        "dynamic": True,
        "evaporation": {
            "sheet": "EVAPORATION",
            "month_cell": "C2",
            "year_cell": "C3",
            "start_row": 9,
            "row_count": 32,
            "columns": {
                "date": "A",
                "cote": "B",
                "surface": "C",
                "surface_moyenne": "D",
                "hauteur_bac": "E",
                "pluie": "F",
                "hauteur_evaporee": "G",
                "hauteur_corrigee": "H",
                "evaporation": "I",
            },
        },
        "apport": {
            "sheet": "APPORT",
            "start_row": 8,
            "row_count": 32,
            "columns": {
                "date": "A",
                "cote": "B",
                "volume": "C",
                "variation": "D",
                "evaporation": "E",
                "total_restitutions": _column_name(total_col_index),
                "apports": _column_name(apports_col_index),
                "debit": _column_name(debit_col_index),
                "pluie": _column_name(pluie_col_index),
            },
            "last_column": _column_name(pluie_col_index),
            "special_columns": {},
        },
        "input_fields": fields,
    }


def resolve_bilan_config(db: Session, barrage_code: str) -> tuple[str, dict, dict]:
    """Retourne code, barrage, config pour un barrage officiel ou dynamique."""
    return _require_supported_barrage(db, barrage_code)

def _require_supported_barrage(db: Session, barrage_code: str) -> tuple[str, dict, dict]:
    code = normalize_barrage_code(barrage_code)

    # 1) Barrages officiels : on garde exactement les mappings et templates existants.
    config = get_bilan_config(code)
    if config:
        barrages = fetch_supported_barrages(db, SUPPORTED_BARRAGE_CODES)
        barrage = barrages.get(code)
        if not barrage:
            raise ValueError(f"Le barrage {code} est introuvable ou inactif dans PostgreSQL.")
        return code, barrage, config

    # 2) Nouveaux barrages : configuration dynamique depuis PostgreSQL.
    dynamic_barrages = {item["code"]: item for item in fetch_bilan_enabled_barrages(db)}
    barrage = dynamic_barrages.get(code)
    if not barrage:
        raise ValueError(
            f"Le barrage {code or barrage_code} n'est pas configuré pour BILAN. "
            "Vérifie qu'il est actif et que l'option inclure_bilan est cochée."
        )

    fields = fetch_dynamic_bilan_input_fields(db, code)
    if not fields:
        raise ValueError(
            f"Le barrage {code} n'a aucune restitution associée. "
            "Ajoute les restitutions avant de générer le BILAN."
        )

    if not barrage.get("nb_points_bareme"):
        raise ValueError(
            f"Le barrage {code} n'a pas de barème actif. "
            "Importe le barème avant de générer le BILAN."
        )

    return code, barrage, _make_dynamic_bilan_config(barrage, fields)


def build_bilan_catalog(db: Session) -> dict:
    barrages = fetch_supported_barrages(db, SUPPORTED_BARRAGE_CODES)
    enabled_barrages = fetch_bilan_enabled_barrages(db)
    enabled_by_code = {item["code"]: item for item in enabled_barrages}
    items = []

    # Barrages officiels : ordre et templates historiques conservés.
    for code in SUPPORTED_BARRAGE_CODES:
        config = BILAN_CONFIGS[code]
        barrage = barrages.get(code)
        if not barrage:
            continue
        items.append(
            {
                "barrage_code": code,
                "barrage_nom": barrage.get("nom") or config["display_name"],
                "barrage_nom_court": barrage.get("nom_court"),
                "template": config["template"],
                "ordre_affichage": barrage.get("ordre_affichage"),
                "ordre_bilan": enabled_by_code.get(code, {}).get("ordre_bilan", barrage.get("ordre_affichage")),
                "input_count": len(config["input_fields"]),
                "is_dynamic": False,
            }
        )

    # Nouveaux barrages : ajout automatique au catalogue BILAN.
    for barrage in enabled_barrages:
        code = barrage["code"]
        if code in BILAN_CONFIGS:
            continue

        fields = fetch_dynamic_bilan_input_fields(db, code)
        items.append(
            {
                "barrage_code": code,
                "barrage_nom": barrage.get("nom") or code,
                "barrage_nom_court": barrage.get("nom_court"),
                "template": "BILAN dynamique",
                "ordre_affichage": barrage.get("ordre_affichage"),
                "ordre_bilan": barrage.get("ordre_bilan"),
                "input_count": len(fields),
                "is_dynamic": True,
                "nb_points_bareme": barrage.get("nb_points_bareme"),
            }
        )

    items.sort(key=lambda item: (item.get("ordre_bilan") or item.get("ordre_affichage") or 999999, item["barrage_code"]))
    return {"status": "ok", "count": len(items), "barrages": items}


def _stored_computed(bilan: dict | None) -> dict | None:
    if not bilan:
        return None
    return {
        "volume_mm3": maybe_float(bilan.get("volume_mm3")),
        "surface_km2": maybe_float(bilan.get("surface_km2")),
        "surface_moyenne_km2": maybe_float(bilan.get("surface_moyenne_km2")),
        "volume_jour_suivant_mm3": maybe_float(bilan.get("volume_jour_suivant_mm3")),
        "variation_reserve_mm3": maybe_float(bilan.get("variation_reserve_mm3")),
        "hauteur_evaporee_mm": maybe_float(bilan.get("hauteur_evaporee_mm")),
        "hauteur_corrigee_mm": maybe_float(bilan.get("hauteur_corrigee_mm")),
        "evaporation_m3": maybe_float(bilan.get("evaporation_m3")),
        "evaporation_1000m3": maybe_float(bilan.get("evaporation_1000m3")),
        "debit_evaporation_1000m3s": maybe_float(bilan.get("debit_evaporation_1000m3s")),
        "total_restitutions_m3": maybe_float(bilan.get("total_restitutions_m3")),
        "transfert_dar_khrofa_m3": maybe_float(bilan.get("transfert_dar_khrofa_m3")),
        "apports_raw_m3": maybe_float(bilan.get("apports_raw_m3")),
        "apports_m3": maybe_float(bilan.get("apports_m3")),
        "debit_m3s": maybe_float(bilan.get("debit_m3s")),
        "taux_remplissage": maybe_float(bilan.get("taux_remplissage")),
    }


def build_bilan_month_form(db: Session, barrage_code: str, year: int, month: int) -> dict:
    code, barrage, config = _require_supported_barrage(db, barrage_code)
    days = month_dates(year, month)
    _, _, next_day = month_bounds(year, month)
    all_dates = days + [next_day]

    bilans = fetch_month_bilans(db, barrage_code=code, dates=all_dates)
    restitutions = fetch_month_restitutions(db, bilans)
    boem_transfers = fetch_boem_transfers_by_dates(db, days) if code == "DAR_KHROFA" else {}

    rows = []
    fields = config["input_fields"]

    for day in days:
        next_date = day + timedelta(days=1)
        current = bilans.get(day.isoformat())
        following = bilans.get(next_date.isoformat())
        current_restitutions = dict(restitutions.get(day.isoformat(), {}))

        if code == "DAR_KHROFA":
            if "TRANSFERT_DAR_KHROFA" not in current_restitutions:
                current_restitutions["TRANSFERT_DAR_KHROFA"] = (
                    maybe_float(current.get("transfert_dar_khrofa_m3"))
                    if current and current.get("transfert_dar_khrofa_m3") is not None
                    else boem_transfers.get(day.isoformat(), 0.0)
                )

        input_values = {
            item["code"]: zero(current_restitutions.get(item["code"], 0.0))
            for item in fields
        }

        irrigation = None
        if code == "DAR_KHROFA":
            irrigation = (
                zero(input_values.get("PRISE_AGRICOLE_RD"))
                + zero(input_values.get("PRISE_AGRICOLE_RG"))
                - zero(input_values.get("AEPI_TANGER"))
            )

        rows.append(
            {
                "date_bilan": day.isoformat(),
                "date_suivante": next_date.isoformat(),
                "existing_bilan_id": int(current["id"]) if current and current.get("id") else None,
                "statut": current.get("statut") if current else "NON_SAISI",
                "inputs": {
                    "cote_7h_ngm": maybe_float(current.get("cote_7h_ngm")) if current else None,
                    "cote_suivante_ngm": maybe_float(following.get("cote_7h_ngm")) if following else None,
                    "hauteur_bac_mm": maybe_float(current.get("hauteur_bac_mm")) if current else None,
                    "pluie_mm": maybe_float(current.get("pluie_mm")) if current else None,
                    "restitutions": input_values,
                    "observation": current.get("observation") if current else None,
                },
                "derived": {"irrigation_m3": irrigation},
                "computed": _stored_computed(current),
            }
        )

    next_bilan = bilans.get(next_day.isoformat())

    return {
        "status": "ok",
        "barrage": {
            "barrage_code": code,
            "barrage_nom": barrage.get("nom") or config["display_name"],
            "barrage_nom_court": barrage.get("nom_court"),
            "capacite_normale_mm3": maybe_float(barrage.get("capacite_normale_mm3")),
            "template": config["template"],
        },
        "year": year,
        "month": month,
        "days_in_month": len(days),
        "date_start": days[0].isoformat(),
        "date_end": days[-1].isoformat(),
        "next_date": next_day.isoformat(),
        "next_day_cote_7h_ngm": maybe_float(next_bilan.get("cote_7h_ngm")) if next_bilan else None,
        "input_fields": config["input_fields"],
        "rows": rows,
    }


def _restitution_dict(row: BilanDailyInput) -> tuple[dict[str, float], set[str]]:
    values: dict[str, float] = {}
    provided: set[str] = set()
    for item in row.restitutions:
        code = str(item.type_code or "").strip().upper()
        if not code:
            continue
        values[code] = zero(item.valeur_m3)
        provided.add(code)
    return values, provided


def compute_bilan(db: Session, payload: BilanComputeRequest) -> dict:
    code, barrage, config = _require_supported_barrage(db, payload.barrage_code)
    valid_days = set(month_dates(payload.year, payload.month))
    start, last, next_month_day = month_bounds(payload.year, payload.month)
    all_dates = sorted(valid_days | {next_month_day})

    bilans = fetch_month_bilans(db, barrage_code=code, dates=all_dates)
    existing_restitutions = fetch_month_restitutions(db, bilans)
    boem_transfers = (
        fetch_boem_transfers_by_dates(db, sorted(valid_days))
        if code == "DAR_KHROFA"
        else {}
    )

    seen_dates: set[date] = set()
    results = []
    field_meta = {item["code"]: item for item in config["input_fields"]}
    total_codes = {
        item["code"]
        for item in config["input_fields"]
        if item.get("included_in_total", True)
    }
    barrage_id = int(barrage["id"])

    for row in sorted(payload.rows, key=lambda item: item.date_bilan):
        checks: list[dict] = []
        day = row.date_bilan
        next_day = day + timedelta(days=1)

        if day in seen_dates:
            add_check(checks, "BLOQUANT", "DATE_DUPLIQUEE", "date_bilan", f"La date {day} est répétée.")
        seen_dates.add(day)

        if day not in valid_days:
            add_check(
                checks,
                "BLOQUANT",
                "DATE_HORS_MOIS",
                "date_bilan",
                f"La date {day} n'appartient pas à {payload.month:02d}/{payload.year}.",
            )

        current_existing = bilans.get(day.isoformat())
        next_existing = bilans.get(next_day.isoformat())

        current_cote = (
            maybe_float(row.cote_7h_ngm)
            if row.cote_7h_ngm is not None
            else maybe_float(current_existing.get("cote_7h_ngm")) if current_existing else None
        )
        next_cote = (
            maybe_float(row.cote_suivante_ngm)
            if row.cote_suivante_ngm is not None
            else maybe_float(next_existing.get("cote_7h_ngm")) if next_existing else None
        )
        hauteur_bac = (
            maybe_float(row.hauteur_bac_mm)
            if row.hauteur_bac_mm is not None
            else maybe_float(current_existing.get("hauteur_bac_mm")) if current_existing else None
        )
        pluie = (
            maybe_float(row.pluie_mm)
            if row.pluie_mm is not None
            else maybe_float(current_existing.get("pluie_mm")) if current_existing else None
        )

        if current_cote is None:
            add_check(checks, "BLOQUANT", "COTE_MANQUANTE", "cote_7h_ngm", f"Cote manquante le {day}.")
        if next_cote is None:
            add_check(
                checks,
                "BLOQUANT",
                "COTE_SUIVANTE_MANQUANTE",
                "cote_suivante_ngm",
                f"Cote du {next_day} manquante pour calculer le {day}.",
            )
        if hauteur_bac is None:
            add_check(checks, "BLOQUANT", "HAUTEUR_BAC_MANQUANTE", "hauteur_bac_mm", f"Hauteur bac manquante le {day}.")
        elif hauteur_bac < 0:
            add_check(
                checks,
                "AVERTISSEMENT",
                "HAUTEUR_BAC_NEGATIVE",
                "hauteur_bac_mm",
                f"Hauteur bac négative le {day}; la valeur est conservée comme dans le fichier BILAN.",
            )
        if pluie is None:
            add_check(checks, "BLOQUANT", "PLUIE_MANQUANTE", "pluie_mm", f"Pluie manquante le {day}.")
        elif pluie < 0:
            add_check(checks, "BLOQUANT", "PLUIE_NEGATIVE", "pluie_mm", f"La pluie ne peut pas être négative le {day}.")

        existing_values = dict(existing_restitutions.get(day.isoformat(), {}))
        submitted_values, provided_codes = _restitution_dict(row)
        existing_values.update(submitted_values)

        input_values: dict[str, float] = {}
        for field_code, meta in field_meta.items():
            value = zero(existing_values.get(field_code, 0.0))
            if value < 0:
                add_check(
                    checks,
                    "BLOQUANT",
                    "RESTITUTION_NEGATIVE",
                    field_code,
                    f"La valeur {meta['label']} ne peut pas être négative le {day}.",
                )
            input_values[field_code] = value

        if code == "DAR_KHROFA" and "TRANSFERT_DAR_KHROFA" not in provided_codes:
            stored_transfer = (
                maybe_float(current_existing.get("transfert_dar_khrofa_m3"))
                if current_existing and current_existing.get("transfert_dar_khrofa_m3") is not None
                else None
            )
            input_values["TRANSFERT_DAR_KHROFA"] = (
                stored_transfer
                if stored_transfer is not None
                else zero(boem_transfers.get(day.isoformat(), 0.0))
            )

        total_restitutions = sum(zero(input_values.get(type_code)) for type_code in total_codes)
        transfert_received = (
            zero(input_values.get("TRANSFERT_DAR_KHROFA"))
            if code == "DAR_KHROFA"
            else 0.0
        )

        irrigation = None
        if code == "DAR_KHROFA":
            irrigation = (
                zero(input_values.get("PRISE_AGRICOLE_RD"))
                + zero(input_values.get("PRISE_AGRICOLE_RG"))
                - zero(input_values.get("AEPI_TANGER"))
            )

        bareme_current = lookup_bareme_exact(db, barrage_id, current_cote, date_reference=day) if current_cote is not None else None
        bareme_next = lookup_bareme_exact(db, barrage_id, next_cote, date_reference=next_day) if next_cote is not None else None

        if current_cote is not None and bareme_current is None:
            add_check(
                checks,
                "BLOQUANT",
                "COTE_HORS_BAREME",
                "cote_7h_ngm",
                f"La cote {current_cote} du {day} est introuvable dans le barème actif.",
            )
        if next_cote is not None and bareme_next is None:
            add_check(
                checks,
                "BLOQUANT",
                "COTE_SUIVANTE_HORS_BAREME",
                "cote_suivante_ngm",
                f"La cote {next_cote} du {next_day} est introuvable dans le barème actif.",
            )

        computed = None
        if not has_blocking(checks):
            hydraulic = calculate_hydraulic_balance(
                HydraulicInputs(
                    barrage_code=code,
                    volume_interval_mm3=bareme_current["volume_mm3"],
                    volume_next_mm3=bareme_next["volume_mm3"],
                    surface_interval_km2=bareme_current["surface_km2"],
                    surface_next_km2=bareme_next["surface_km2"],
                    hauteur_bac_mm=hauteur_bac,
                    pluie_mm=pluie,
                    total_restitutions_m3=total_restitutions,
                    capacite_normale_mm3=(bareme_next.get("volume_normal_mm3") if bareme_next else None) or barrage.get("capacite_normale_mm3"),
                    transfert_dar_khrofa_m3=transfert_received,
                )
            ).to_dict()

            computed = {
                **hydraulic,
                "date_bilan": day.isoformat(),
                "date_suivante": next_day.isoformat(),
                "cote_7h_ngm": current_cote,
                "cote_suivante_ngm": next_cote,
                "volume_mm3": hydraulic["volume_interval_mm3"],
                "surface_km2": hydraulic["surface_interval_km2"],
                "irrigation_m3": irrigation,
                "input_values": input_values,
            }

            if hydraulic.get("apports_raw_m3") is not None and hydraulic["apports_raw_m3"] < 0:
                add_check(
                    checks,
                    "AVERTISSEMENT",
                    "APPORTS_NEGATIFS_RAMENES_ZERO",
                    "apports_m3",
                    f"Apports bruts négatifs le {day}; BILAN affiche 0 m3.",
                )

        if has_blocking(checks):
            status = "BLOQUANT"
        elif checks:
            status = "AVERTISSEMENT"
        else:
            status = "OK"

        results.append(
            {
                "barrage_code": code,
                "date_bilan": day.isoformat(),
                "date_suivante": next_day.isoformat(),
                "status": status,
                "can_save": not has_blocking(checks),
                "checks": checks,
                "inputs": {
                    "cote_7h_ngm": current_cote,
                    "cote_suivante_ngm": next_cote,
                    "hauteur_bac_mm": hauteur_bac,
                    "pluie_mm": pluie,
                    "restitutions": input_values,
                    "observation": row.observation,
                },
                "computed": computed,
            }
        )

    can_save = bool(results) and all(item["can_save"] for item in results)
    return {
        "status": "ok" if can_save else "problem",
        "barrage_code": code,
        "year": payload.year,
        "month": payload.month,
        "date_start": start.isoformat(),
        "date_end": last.isoformat(),
        "next_date": next_month_day.isoformat(),
        "count": len(results),
        "ready_count": sum(1 for item in results if item["can_save"]),
        "can_save": can_save,
        "results": results,
    }


def save_bilan(db: Session, payload: BilanSaveRequest) -> dict:
    code, barrage, _ = _require_supported_barrage(db, payload.barrage_code)
    if payload.statut not in ALLOWED_STATUSES:
        return {
            "status": "problem",
            "message": f"Statut non autorisé : {payload.statut}",
        }

    computed_payload = compute_bilan(db, payload)
    if not computed_payload["can_save"]:
        return {
            "status": "problem",
            "message": "Impossible d'enregistrer : une ou plusieurs lignes sont incomplètes.",
            "computed": computed_payload,
        }

    barrage_id = int(barrage["id"])
    capacity = maybe_float(barrage.get("capacite_normale_mm3"))
    saved_rows = []

    try:
        for row in computed_payload["results"]:
            day = date.fromisoformat(row["date_bilan"])
            next_day = date.fromisoformat(row["date_suivante"])
            computed = row["computed"]
            inputs = row["inputs"]

            if not payload.overwrite and existing_bilan_id(db, barrage_id, day) is not None:
                raise ValueError(
                    f"Une ligne existe déjà pour {code} le {day}. Activez overwrite pour la remplacer."
                )

            journee_id = ensure_journee_situation(db, next_day)

            current_values = {
                "journee_situation_id": journee_id,
                "cote_7h_ngm": inputs["cote_7h_ngm"],
                "hauteur_bac_mm": inputs["hauteur_bac_mm"],
                "pluie_mm": inputs["pluie_mm"],
                "surface_km2": computed["surface_interval_km2"],
                "surface_moyenne_km2": computed["surface_moyenne_km2"],
                "volume_mm3": computed["volume_interval_mm3"],
                "volume_jour_suivant_mm3": computed["volume_next_mm3"],
                "variation_reserve_mm3": computed["variation_reserve_mm3"],
                "hauteur_evaporee_mm": computed["hauteur_evaporee_mm"],
                "hauteur_corrigee_mm": computed["hauteur_corrigee_mm"],
                "evaporation_m3": computed["evaporation_m3"],
                "evaporation_1000m3": computed["evaporation_1000m3"],
                "debit_evaporation_1000m3s": computed["debit_evaporation_1000m3s"],
                "total_restitutions_m3": computed["total_restitutions_m3"],
                "transfert_dar_khrofa_m3": computed["transfert_dar_khrofa_m3"],
                "apports_raw_m3": computed["apports_raw_m3"],
                "apports_m3": computed["apports_m3"],
                "debit_m3s": computed["debit_m3s"],
                "taux_remplissage": safe_rate(computed["volume_interval_mm3"], capacity),
                "statut": payload.statut,
                "observation": inputs.get("observation"),
                "is_from_import": False,
                "source_fichier": "PLATEFORME",
                "source_feuille": "BILAN_MENSUEL",
            }
            current_bilan_id = upsert_bilan(
                db,
                barrage_id=barrage_id,
                date_bilan=day,
                values=current_values,
            )

            next_values = {
                "journee_situation_id": journee_id,
                "cote_7h_ngm": inputs["cote_suivante_ngm"],
                "surface_km2": computed["surface_next_km2"],
                "volume_mm3": computed["volume_next_mm3"],
                "taux_remplissage": safe_rate(computed["volume_next_mm3"], capacity),
                "statut": payload.statut,
                "is_from_import": False,
                "source_fichier": "PLATEFORME",
                "source_feuille": "BILAN_MENSUEL",
            }
            next_bilan_id = upsert_bilan(
                db,
                barrage_id=barrage_id,
                date_bilan=next_day,
                values=next_values,
            )

            for type_code, value in computed["input_values"].items():
                upsert_restitution(
                    db,
                    bilan_id=current_bilan_id,
                    type_code=type_code,
                    valeur_m3=zero(value),
                    observation="Saisie plateforme BILAN",
                )

            if code == "DAR_KHROFA" and computed.get("irrigation_m3") is not None:
                upsert_restitution(
                    db,
                    bilan_id=current_bilan_id,
                    type_code="IRRIGATION",
                    valeur_m3=max(0.0, zero(computed["irrigation_m3"])),
                    observation="Calcul BILAN : prise RD + prise RG - AEPI Tanger",
                )

            variables = [
                ("HAUTEUR_EVAPOREE_MM", "Hauteur évaporée", computed["hauteur_evaporee_mm"], "mm"),
                ("HAUTEUR_CORRIGEE_MM", "Hauteur corrigée", computed["hauteur_corrigee_mm"], "mm"),
                ("EVAPORATION_1000M3", "Evaporation en milliers de m3", computed["evaporation_1000m3"], "1000 m3"),
                ("DEBIT_EVAPORATION_1000M3S", "Débit évaporation auxiliaire", computed["debit_evaporation_1000m3s"], "1000 m3/s"),
                ("APPORTS_RAW_M3", "Apports bruts avant max(0)", computed["apports_raw_m3"], "m3"),
                ("TRANSFERT_DAR_KHROFA_M3", "Transfert Dar Khrofa", computed["transfert_dar_khrofa_m3"], "m3"),
                ("IRRIGATION_CALCULEE_M3", "Irrigation calculée Dar Khrofa", computed.get("irrigation_m3"), "m3"),
            ]
            for variable_code, label, value, unit in variables:
                upsert_bilan_variable(
                    db,
                    bilan_id=current_bilan_id,
                    code_variable=variable_code,
                    libelle_variable=label,
                    valeur_numeric=value,
                    unite=unit,
                    source_type="BILAN_BACKEND",
                )

            saved_rows.append(
                {
                    "date_bilan": day.isoformat(),
                    "bilan_id": current_bilan_id,
                    "next_date": next_day.isoformat(),
                    "next_bilan_id": next_bilan_id,
                }
            )

        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "status": "ok",
        "message": "BILAN enregistré avec succès.",
        "barrage_code": code,
        "year": payload.year,
        "month": payload.month,
        "saved_count": len(saved_rows),
        "saved_rows": saved_rows,
        "computed": computed_payload,
    }


def _request_from_month_form(form: dict) -> BilanComputeRequest:
    rows = []
    for item in form["rows"]:
        inputs = item["inputs"]
        rows.append(
            BilanDailyInput(
                date_bilan=date.fromisoformat(item["date_bilan"]),
                cote_7h_ngm=inputs.get("cote_7h_ngm"),
                cote_suivante_ngm=inputs.get("cote_suivante_ngm"),
                hauteur_bac_mm=inputs.get("hauteur_bac_mm"),
                pluie_mm=inputs.get("pluie_mm"),
                restitutions=[
                    BilanRestitutionInput(type_code=code, valeur_m3=value)
                    for code, value in inputs.get("restitutions", {}).items()
                ],
                observation=inputs.get("observation"),
            )
        )
    return BilanComputeRequest(
        barrage_code=form["barrage"]["barrage_code"],
        year=form["year"],
        month=form["month"],
        rows=rows,
    )


def build_bilan_preview(db: Session, barrage_code: str, year: int, month: int) -> dict:
    form = build_bilan_month_form(db, barrage_code, year, month)
    computed = compute_bilan(db, _request_from_month_form(form))
    result_by_date = {item["date_bilan"]: item for item in computed["results"]}

    rows = []
    for item in form["rows"]:
        calculated = result_by_date.get(item["date_bilan"])
        rows.append({**item, "calculation": calculated})

    valid_results = [item for item in computed["results"] if item.get("computed")]
    totals = {
        "pluie_mm": sum(zero(item["inputs"].get("pluie_mm")) for item in valid_results),
        "evaporation_m3": sum(zero(item["computed"].get("evaporation_m3")) for item in valid_results),
        "total_restitutions_m3": sum(zero(item["computed"].get("total_restitutions_m3")) for item in valid_results),
        "apports_m3": sum(zero(item["computed"].get("apports_m3")) for item in valid_results),
    }

    return {
        **form,
        "status": computed["status"],
        "can_export_complete_month": computed["can_save"] and computed["count"] == form["days_in_month"],
        "ready_count": computed["ready_count"],
        "expected_count": form["days_in_month"],
        "rows": rows,
        "totals": totals,
        "compute_summary": computed,
    }


def build_bilan_check(db: Session, barrage_code: str, year: int, month: int) -> dict:
    preview = build_bilan_preview(db, barrage_code, year, month)
    missing = []
    for row in preview["rows"]:
        calculation = row.get("calculation") or {}
        if not calculation.get("can_save"):
            missing.append(
                {
                    "date_bilan": row["date_bilan"],
                    "checks": calculation.get("checks", []),
                }
            )

    return {
        "status": "ok",
        "barrage": preview["barrage"],
        "year": year,
        "month": month,
        "ready_count": preview["ready_count"],
        "expected_count": preview["expected_count"],
        "can_export_complete_month": preview["can_export_complete_month"],
        "missing_rows": missing,
    }

# === ABHL V20 BOEM BGE DE GARDE INPUTS START ===
# Objectif :
# Ajouter dans la saisie BOEM les trois colonnes spéciales du fichier officiel :
# - BGE_GARDE_AM
# - BGE_GARDE_AV
# - BGE_GARDE_PLUIE
#
# Elles ne sont PAS des restitutions et ne rentrent PAS dans le total.
# Elles sont stockées dans public.djbarrage_mesures_speciales pour être reprises
# dans l'export annonce/situation.

from sqlalchemy import text as _abhl_v20_text, bindparam as _abhl_v20_bindparam

_ABHL_V20_BOEM_SPECIAL_FIELDS = [
    {
        "code": "BGE_GARDE_AM",
        "label": "BGE de garde AM",
        "column": None,
        "included_in_total": False,
        "role": "special_measure",
        "editable": True,
        "unit": "NGM",
    },
    {
        "code": "BGE_GARDE_AV",
        "label": "BGE de garde AV",
        "column": None,
        "included_in_total": False,
        "role": "special_measure",
        "editable": True,
        "unit": "NGM",
    },
    {
        "code": "BGE_GARDE_PLUIE",
        "label": "BGE de garde Pluie",
        "column": None,
        "included_in_total": False,
        "role": "special_measure",
        "editable": True,
        "unit": "mm",
    },
]


def _abhl_v20_table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        _abhl_v20_text('''
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = :table_name
            ) AS ok
        '''),
        {"table_name": table_name},
    ).mappings().first()

    return bool(row and row["ok"])


def _abhl_v20_ensure_special_table(db: Session) -> None:
    db.execute(
        _abhl_v20_text('''
            CREATE TABLE IF NOT EXISTS public.djbarrage_mesures_speciales (
                id SERIAL PRIMARY KEY,
                bilan_journalier_id INTEGER NOT NULL,
                mesure_code VARCHAR(100) NOT NULL,
                mesure_nom VARCHAR(255),
                valeur NUMERIC,
                unite VARCHAR(30),
                source_fichier VARCHAR(255),
                source_feuille VARCHAR(255),
                ligne_source INTEGER,
                colonne_source VARCHAR(20),
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now(),
                CONSTRAINT uq_djbarrage_mesure
                    UNIQUE (bilan_journalier_id, mesure_code)
            );
        ''')
    )


def _abhl_v20_fetch_boem_specials(db: Session, date_values: list[str]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}

    if not date_values:
        return result

    if not _abhl_v20_table_exists(db, "djbarrage_mesures_speciales"):
        return result

    codes = [item["code"] for item in _ABHL_V20_BOEM_SPECIAL_FIELDS]

    query = _abhl_v20_text('''
        SELECT
            bj.date_bilan,
            dms.mesure_code,
            dms.valeur
        FROM public.djbarrage_mesures_speciales dms
        JOIN public.bilans_journaliers bj
          ON bj.id = dms.bilan_journalier_id
        JOIN public.barrages b
          ON b.id = bj.barrage_id
        WHERE b.code = 'BOEM'
          AND bj.date_bilan IN :date_values
          AND dms.mesure_code IN :codes
    ''').bindparams(
        _abhl_v20_bindparam("date_values", expanding=True),
        _abhl_v20_bindparam("codes", expanding=True),
    )

    rows = db.execute(
        query,
        {
            "date_values": date_values,
            "codes": codes,
        },
    ).mappings().all()

    for row in rows:
        day_key = row["date_bilan"].isoformat()
        result.setdefault(day_key, {})
        result[day_key][row["mesure_code"]] = zero(row["valeur"])

    return result


def _abhl_v20_upsert_boem_special(
    db: Session,
    *,
    bilan_id: int,
    mesure_code: str,
    valeur,
    unite: str,
    date_label: str,
) -> None:
    _abhl_v20_ensure_special_table(db)

    db.execute(
        _abhl_v20_text('''
            INSERT INTO public.djbarrage_mesures_speciales (
                bilan_journalier_id,
                mesure_code,
                mesure_nom,
                valeur,
                unite,
                source_fichier,
                source_feuille,
                ligne_source,
                colonne_source
            )
            VALUES (
                :bilan_id,
                :mesure_code,
                :mesure_nom,
                :valeur,
                :unite,
                'PLATEFORME',
                'BILAN_MENSUEL_BOEM',
                NULL,
                :colonne_source
            )
            ON CONFLICT (bilan_journalier_id, mesure_code)
            DO UPDATE SET
                valeur = EXCLUDED.valeur,
                unite = EXCLUDED.unite,
                source_fichier = EXCLUDED.source_fichier,
                source_feuille = EXCLUDED.source_feuille,
                colonne_source = EXCLUDED.colonne_source,
                updated_at = now()
        '''),
        {
            "bilan_id": bilan_id,
            "mesure_code": mesure_code,
            "mesure_nom": mesure_code.replace("_", " "),
            "valeur": zero(valeur),
            "unite": unite,
            "colonne_source": date_label,
        },
    )


_abhl_v20_original_build_bilan_month_form = build_bilan_month_form


def build_bilan_month_form(db: Session, barrage_code: str, year: int, month: int) -> dict:
    form = _abhl_v20_original_build_bilan_month_form(db, barrage_code, year, month)

    code = str(form.get("barrage", {}).get("barrage_code") or barrage_code or "").upper().strip()

    if code != "BOEM":
        return form

    existing_codes = {
        str(item.get("code") or "").upper().strip()
        for item in form.get("input_fields", [])
    }

    for item in _ABHL_V20_BOEM_SPECIAL_FIELDS:
        if item["code"] not in existing_codes:
            form.setdefault("input_fields", []).append(dict(item))

    date_values = [row.get("date_bilan") for row in form.get("rows", []) if row.get("date_bilan")]
    specials_by_date = _abhl_v20_fetch_boem_specials(db, date_values)

    for row in form.get("rows", []):
        date_key = row.get("date_bilan")
        inputs = row.setdefault("inputs", {})
        restitutions = inputs.setdefault("restitutions", {})
        values = specials_by_date.get(date_key, {})

        for item in _ABHL_V20_BOEM_SPECIAL_FIELDS:
            code_special = item["code"]
            restitutions[code_special] = values.get(code_special, 0.0)

    form["has_special_measure_inputs"] = True
    form["special_measure_message"] = (
        "BOEM : les champs BGE de garde AM, AV et Pluie sont stockés "
        "dans djbarrage_mesures_speciales et ne rentrent pas dans Total restitutions."
    )

    return form


_abhl_v20_original_save_bilan = save_bilan


def save_bilan(db: Session, payload: BilanSaveRequest) -> dict:
    result = _abhl_v20_original_save_bilan(db, payload)

    code = str(payload.barrage_code or "").upper().strip()
    if result.get("status") != "ok" or code != "BOEM":
        return result

    special_codes = {item["code"] for item in _ABHL_V20_BOEM_SPECIAL_FIELDS}
    values_by_date: dict[str, dict[str, float]] = {}

    for row in payload.rows:
        day_key = row.date_bilan.isoformat()
        values_by_date.setdefault(day_key, {})

        for restitution in row.restitutions:
            type_code = str(restitution.type_code or "").upper().strip()
            if type_code in special_codes:
                values_by_date[day_key][type_code] = zero(restitution.valeur_m3)

    saved_by_date = {
        item.get("date_bilan"): item
        for item in result.get("saved_rows", [])
        if item.get("date_bilan") and item.get("bilan_id")
    }

    saved_specials = 0

    for day_key, special_values in values_by_date.items():
        saved = saved_by_date.get(day_key)
        if not saved:
            continue

        bilan_id = int(saved["bilan_id"])

        for meta in _ABHL_V20_BOEM_SPECIAL_FIELDS:
            special_code = meta["code"]

            # Même si l'utilisateur laisse vide, le front envoie généralement 0.
            # On stocke 0 pour reproduire le fichier officiel.
            value = special_values.get(special_code, 0.0)

            _abhl_v20_upsert_boem_special(
                db,
                bilan_id=bilan_id,
                mesure_code=special_code,
                valeur=value,
                unite=meta["unit"],
                date_label=day_key,
            )
            saved_specials += 1

    if saved_specials:
        db.commit()

    result["boem_bge_specials_saved"] = saved_specials
    return result

# === ABHL V20 BOEM BGE DE GARDE INPUTS END ===

# === ABHL V26 ANNONCE BLANK INPUT FLAGS START ===
# Préserve pour les FUTURES saisies la différence entre "vide" et "0"
# uniquement pour la présentation/export Annonce. Les calculs BILAN restent inchangés.

if "_abhl_v26_original_save_bilan" not in globals():
    _abhl_v26_original_save_bilan = save_bilan


def _abhl_v26_flag_sql(db, bilan_id: int, flag_code: str, is_blank: bool):
    from sqlalchemy import text
    if is_blank:
        db.execute(
            text("""
                INSERT INTO public.djbarrage_mesures_speciales
                    (bilan_journalier_id, mesure_code, mesure_nom, valeur, unite,
                     source_fichier, source_feuille)
                VALUES (:bid, :code, :name, 1, NULL, 'PLATEFORME', 'ANNONCE_FLAGS')
                ON CONFLICT (bilan_journalier_id, mesure_code)
                DO UPDATE SET valeur=1, source_fichier='PLATEFORME',
                              source_feuille='ANNONCE_FLAGS', updated_at=now()
            """),
            {"bid": int(bilan_id), "code": flag_code, "name": flag_code.replace("_", " ")},
        )
    else:
        db.execute(
            text("""
                DELETE FROM public.djbarrage_mesures_speciales
                WHERE bilan_journalier_id=:bid AND mesure_code=:code
            """),
            {"bid": int(bilan_id), "code": flag_code},
        )


def _abhl_v26_payload_rest_map(row):
    result = {}
    for item in (getattr(row, "restitutions", None) or []):
        code = str(getattr(item, "type_code", "") or "").strip().upper()
        if code:
            result[code] = getattr(item, "valeur_m3", None)
    return result


def _abhl_v26_sync_visibility_flags(db, barrage_code: str, bilan_id: int, row):
    values = _abhl_v26_payload_rest_map(row)
    code = str(barrage_code or "").upper()

    # Champs directs : si un champ porte exactement le nom d'une colonne visible,
    # V25 saura lire ce flag directement.
    for type_code, value in values.items():
        _abhl_v26_flag_sql(
            db,
            bilan_id,
            f"ANNONCE_REST_BLANK__{type_code}",
            value is None,
        )

    # Alias historiques / colonnes visibles agrégées.
    if code == "BIB":
        if "AEPI_PRISES" in values:
            _abhl_v26_flag_sql(db, bilan_id, "ANNONCE_REST_BLANK__AEPI", values.get("AEPI_PRISES") is None)
        if "AEPI_JETS_CREUX" in values:
            _abhl_v26_flag_sql(db, bilan_id, "ANNONCE_REST_BLANK__JETS_CREUX", values.get("AEPI_JETS_CREUX") is None)

    if code == "DAR_KHROFA":
        if "PRISE_AGRICOLE_RD" in values or "PRISE_AGRICOLE_RG" in values:
            both_blank = values.get("PRISE_AGRICOLE_RD") is None and values.get("PRISE_AGRICOLE_RG") is None
            _abhl_v26_flag_sql(db, bilan_id, "ANNONCE_REST_BLANK__PRISE_AGRICOLE", both_blank)
        if "AEPI_TANGER" in values:
            blank = values.get("AEPI_TANGER") is None
            _abhl_v26_flag_sql(db, bilan_id, "ANNONCE_SPECIAL_BLANK__UTILISATION_AEPI_TANGER", blank)
            # L'irrigation dérivée doit être vide dès que l'AEPI Tanger est vide.
            _abhl_v26_flag_sql(db, bilan_id, "ANNONCE_SPECIAL_BLANK__UTILISATION_IRRIGATION", blank)

    if code == "BOEM":
        if "IRRIGATION_LOUKKOS_PRISE" in values:
            _abhl_v26_flag_sql(
                db, bilan_id,
                "ANNONCE_REST_BLANK__IRRIGATION_LOUKKOS_PRISE_AGRICOLE",
                values.get("IRRIGATION_LOUKKOS_PRISE") is None,
            )
        if "TRANSFERT_DAR_KHROFA" in values:
            _abhl_v26_flag_sql(
                db, bilan_id, "ANNONCE_REST_BLANK__TRANSFERT",
                values.get("TRANSFERT_DAR_KHROFA") is None,
            )
        if "VDF_RD" in values or "VDF_RG" in values:
            both_blank = values.get("VDF_RD") is None and values.get("VDF_RG") is None
            _abhl_v26_flag_sql(db, bilan_id, "ANNONCE_REST_BLANK__VDF", both_blank)

    if code == "KHATTABI":
        if "PRISE_AGRICOLE_RD" in values:
            _abhl_v26_flag_sql(
                db, bilan_id, "ANNONCE_REST_BLANK__PRISE_AGRICOLE_AM",
                values.get("PRISE_AGRICOLE_RD") is None,
            )
        if "PRISE_AGRICOLE_RG" in values:
            _abhl_v26_flag_sql(
                db, bilan_id, "ANNONCE_REST_BLANK__PRISE_AGRICOLE_AV",
                values.get("PRISE_AGRICOLE_RG") is None,
            )


def save_bilan(db: Session, payload: BilanSaveRequest) -> dict:
    result = _abhl_v26_original_save_bilan(db, payload)
    if not isinstance(result, dict) or result.get("status") != "ok":
        return result

    saved_by_date = {
        str(item.get("date_bilan")): int(item.get("bilan_id"))
        for item in (result.get("saved_rows") or [])
        if item.get("date_bilan") and item.get("bilan_id")
    }
    if not saved_by_date:
        return result

    try:
        for row in (getattr(payload, "rows", None) or []):
            day_key = row.date_bilan.isoformat()
            bilan_id = saved_by_date.get(day_key)
            if bilan_id is None:
                continue
            _abhl_v26_sync_visibility_flags(
                db, getattr(payload, "barrage_code", ""), bilan_id, row
            )
        db.commit()
    except Exception:
        # Les données hydrauliques viennent déjà d'être enregistrées par la logique
        # métier principale. Un problème de flag de présentation ne doit pas les annuler.
        db.rollback()

    return result

# === ABHL V26 ANNONCE BLANK INPUT FLAGS END ===
