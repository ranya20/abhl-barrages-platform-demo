from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.modules.calculs.repository import (
    ensure_journee_situation,
    fetch_active_barrages,
    fetch_all_restitution_types,
    fetch_bilans_by_dates,
    fetch_boem_transfert_from_db,
    fetch_restitution_types_by_barrage,
    fetch_restitutions_for_bilan_ids,
    fetch_special_value,
    lookup_bareme_exact,
    upsert_bilan,
    upsert_bilan_variable,
    upsert_restitution,
)
from app.modules.calculs.schemas import CalculsComputeRequest, CalculsSaveRequest
from app.services.hydraulic_calculator import HydraulicInputs, calculate_hydraulic_balance


def dkey(d: date) -> str:
    return d.isoformat()


def zero(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def add_check(checks: list[dict], niveau: str, code: str, champ: str, message: str):
    checks.append(
        {
            "niveau": niveau,
            "code": code,
            "champ": champ,
            "message": message,
        }
    )


def has_blocking(checks: list[dict]) -> bool:
    return any(check["niveau"] == "BLOQUANT" for check in checks)


def build_calculs_form(db: Session, date_situation: date) -> dict:
    date_interval = date_situation - timedelta(days=1)

    barrages = fetch_active_barrages(db)
    restitution_types = fetch_restitution_types_by_barrage(db)
    all_restitution_types = fetch_all_restitution_types(db)

    codes = list(barrages.keys())
    bilans = fetch_bilans_by_dates(db, [date_interval, date_situation], codes)

    bilan_ids = [
        int(bilan["id"])
        for bilan in bilans.values()
        if bilan.get("id") is not None
    ]
    restitutions_existing = fetch_restitutions_for_bilan_ids(db, bilan_ids)

    items = []

    for code, barrage in barrages.items():
        bilan_interval = bilans.get((code, dkey(date_interval)))
        bilan_current = bilans.get((code, dkey(date_situation)))

        interval_restitutions = {}
        if bilan_interval:
            interval_restitutions = restitutions_existing.get(int(bilan_interval["id"]), {})

        types = []
        official_codes = set()

        # 1) Types officiels associés au barrage
        for item in restitution_types.get(code, []):
            type_code = item["type_code"]
            official_codes.add(type_code)

            types.append(
                {
                    "type_id": item["type_id"],
                    "type_code": type_code,
                    "libelle": item["libelle_affichage"] or item["libelle"],
                    "unite": item["unite"],
                    "obligatoire": item["obligatoire"],
                    "ordre_affichage": item["ordre_affichage"],
                    "existing_value_m3": interval_restitutions.get(type_code, 0.0),
                    "source": "MAPPING_OFFICIEL_BARRAGE",
                    "is_associated_to_barrage": True,
                }
            )

        # 2) Types existants en base mais absents du mapping officiel
        # Très important pour ne pas perdre les restitutions importées depuis DJBarrage.
        extra_order = 9000

        for type_code, existing_value in sorted(interval_restitutions.items()):
            if type_code in official_codes:
                continue

            meta = all_restitution_types.get(type_code, {})

            types.append(
                {
                    "type_id": meta.get("type_id"),
                    "type_code": type_code,
                    "libelle": meta.get("libelle") or f"{type_code} (valeur existante PostgreSQL)",
                    "unite": meta.get("unite") or "m3",
                    "obligatoire": False,
                    "ordre_affichage": extra_order,
                    "existing_value_m3": existing_value,
                    "source": "VALEUR_EXISTANTE_POSTGRESQL_HORS_MAPPING",
                    "is_associated_to_barrage": False,
                }
            )

            extra_order += 1

        items.append(
            {
                "barrage_code": code,
                "barrage_nom": barrage.get("nom"),
                "barrage_nom_court": barrage.get("nom_court"),
                "capacite_normale_mm3": barrage.get("capacite_normale_mm3"),
                "inclure_annonce": barrage.get("inclure_annonce", True),
                "inclure_bilan": barrage.get("inclure_bilan", True),
                "inclure_situation": barrage.get("inclure_situation", True),
                "ordre_annonce": barrage.get("ordre_annonce"),
                "ordre_bilan": barrage.get("ordre_bilan"),
                "ordre_situation": barrage.get("ordre_situation"),
                "date_interval": date_interval.isoformat(),
                "date_situation": date_situation.isoformat(),
                "previous_bilan": bilan_interval,
                "current_bilan": bilan_current,
                "default_inputs": {
                    "cote_7h_ngm": bilan_current.get("cote_7h_ngm") if bilan_current else None,
                    "hauteur_bac_mm": bilan_interval.get("hauteur_bac_mm") if bilan_interval else None,
                    "pluie_mm": bilan_interval.get("pluie_mm") if bilan_interval else None,
                },
                "restitution_types": types,
                "can_calculate": bool(
                    bilan_interval
                    and bilan_interval.get("cote_7h_ngm") is not None
                ),
            }
        )

    return {
        "status": "ok",
        "date_situation": date_situation.isoformat(),
        "date_interval": date_interval.isoformat(),
        "count": len(items),
        "barrages": items,
    }


def _input_restitutions_to_dict(item) -> dict[str, float]:
    data = {}

    for r in item.restitutions:
        code = r.type_code.upper().strip()
        data[code] = zero(r.valeur_m3)

    return data


def compute_calculs(db: Session, payload: CalculsComputeRequest) -> dict:
    date_situation = payload.date_situation
    date_interval = date_situation - timedelta(days=1)

    barrages = fetch_active_barrages(db)
    restitution_types = fetch_restitution_types_by_barrage(db)

    codes = list(barrages.keys())
    bilans = fetch_bilans_by_dates(db, [date_interval, date_situation], codes)

    inputs_by_code = {
        item.barrage_code.upper().strip(): item
        for item in payload.barrages
    }

    # Transfert BOEM saisi dans la même requête.
    boem_transfert_input = None
    if "BOEM" in inputs_by_code:
        boem_restitutions = _input_restitutions_to_dict(inputs_by_code["BOEM"])
        boem_transfert_input = boem_restitutions.get("TRANSFERT")

    if boem_transfert_input is None:
        boem_transfert_input = fetch_boem_transfert_from_db(db, date_interval)

    results = []

    for code, item in inputs_by_code.items():
        checks = []

        if code not in barrages:
            add_check(
                checks,
                "BLOQUANT",
                "BARRAGE_INTRouvable",
                "barrage_code",
                f"Barrage introuvable ou inactif : {code}",
            )
            results.append(
                {
                    "barrage_code": code,
                    "status": "BLOQUANT",
                    "can_save": False,
                    "checks": checks,
                    "computed": None,
                }
            )
            continue

        barrage = barrages[code]
        barrage_id = int(barrage["id"])

        bilan_interval = bilans.get((code, dkey(date_interval)))

        if not bilan_interval:
            add_check(
                checks,
                "BLOQUANT",
                "BILAN_INTERVAL_MANQUANT",
                "date_interval",
                f"Bilan manquant pour {code} à la date {date_interval}.",
            )

        cote_interval = None
        if bilan_interval:
            cote_interval = bilan_interval.get("cote_7h_ngm")

        if cote_interval is None:
            add_check(
                checks,
                "BLOQUANT",
                "COTE_INTERVAL_MANQUANTE",
                "cote_interval",
                f"Cote du jour précédent manquante pour {code}.",
            )

        if item.cote_7h_ngm is None:
            add_check(
                checks,
                "BLOQUANT",
                "COTE_JOUR_MANQUANTE",
                "cote_7h_ngm",
                f"Cote du jour manquante pour {code}.",
            )

        if item.hauteur_bac_mm is None:
            add_check(
                checks,
                "BLOQUANT",
                "HAUTEUR_BAC_MANQUANTE",
                "hauteur_bac_mm",
                f"Hauteur bac manquante pour {code}.",
            )

        if item.pluie_mm is None:
            add_check(
                checks,
                "BLOQUANT",
                "PLUIE_MANQUANTE",
                "pluie_mm",
                f"Pluie manquante pour {code}.",
            )

        if item.hauteur_bac_mm is not None and item.hauteur_bac_mm < 0:
            add_check(
                checks,
                "AVERTISSEMENT",
                "HAUTEUR_BAC_NEGATIVE",
                "hauteur_bac_mm",
                f"Hauteur bac négative pour {code}. À vérifier.",
            )

        if item.pluie_mm is not None and item.pluie_mm < 0:
            add_check(
                checks,
                "AVERTISSEMENT",
                "PLUIE_NEGATIVE",
                "pluie_mm",
                f"Pluie négative pour {code}. À vérifier.",
            )

        bareme_interval = None
        bareme_next = None

        if cote_interval is not None:
            bareme_interval = lookup_bareme_exact(db, barrage_id, float(cote_interval), date_reference=date_interval)

        if item.cote_7h_ngm is not None:
            bareme_next = lookup_bareme_exact(db, barrage_id, float(item.cote_7h_ngm), date_reference=date_situation)

        if cote_interval is not None and not bareme_interval:
            add_check(
                checks,
                "BLOQUANT",
                "COTE_INTERVAL_HORS_BAREME",
                "cote_interval",
                f"Cote {cote_interval} introuvable dans le barème de {code}.",
            )

        if item.cote_7h_ngm is not None and not bareme_next:
            add_check(
                checks,
                "BLOQUANT",
                "COTE_JOUR_HORS_BAREME",
                "cote_7h_ngm",
                f"Cote {item.cote_7h_ngm} introuvable dans le barème de {code}.",
            )

        restitution_values = _input_restitutions_to_dict(item)

        allowed_types = {
            t["type_code"]
            for t in restitution_types.get(code, [])
        }

        for type_code in restitution_values.keys():
            if type_code not in allowed_types:
                add_check(
                    checks,
                    "AVERTISSEMENT",
                    "TYPE_RESTITUTION_NON_ASSOCIE",
                    "restitutions",
                    f"Le type {type_code} n'est pas associé officiellement au barrage {code}.",
                )

        for t in restitution_types.get(code, []):
            if t["obligatoire"] and t["type_code"] not in restitution_values:
                add_check(
                    checks,
                    "BLOQUANT",
                    "RESTITUTION_OBLIGATOIRE_MANQUANTE",
                    "restitutions",
                    f"Restitution obligatoire manquante : {t['type_code']} pour {code}.",
                )

        total_restitutions = sum(restitution_values.values())

        transfert_dar_khrofa = 0.0

        if code == "DAR_KHROFA":
            if item.transfert_dar_khrofa_m3 is not None:
                transfert_dar_khrofa = float(item.transfert_dar_khrofa_m3)
            elif boem_transfert_input is not None:
                transfert_dar_khrofa = float(boem_transfert_input)
            else:
                transfert_dar_khrofa = fetch_special_value(
                    db,
                    "DAR_KHROFA",
                    date_interval,
                    "TRANSFERT_DAR_KHROFA",
                )

        computed = None

        if not has_blocking(checks):
            hydraulic_inputs = HydraulicInputs(
                barrage_code=code,

                volume_interval_mm3=bareme_interval["volume_mm3"],
                volume_next_mm3=bareme_next["volume_mm3"],

                surface_interval_km2=bareme_interval["surface_km2"],
                surface_next_km2=bareme_next["surface_km2"],

                hauteur_bac_mm=item.hauteur_bac_mm,
                pluie_mm=item.pluie_mm,

                total_restitutions_m3=total_restitutions,
                capacite_normale_mm3=(bareme_next.get("volume_normal_mm3") if bareme_next else None) or barrage.get("capacite_normale_mm3"),

                transfert_dar_khrofa_m3=transfert_dar_khrofa,
            )

            result = calculate_hydraulic_balance(hydraulic_inputs)
            computed = result.to_dict()

            if computed["apports_raw_m3"] is not None and computed["apports_raw_m3"] < 0:
                add_check(
                    checks,
                    "AVERTISSEMENT",
                    "APPORTS_NEGATIFS_RAMENES_ZERO",
                    "apports_m3",
                    f"Apports bruts négatifs pour {code}. La valeur finale est ramenée à 0.",
                )

            capacity = barrage.get("capacite_normale_mm3")
            variation = computed.get("variation_reserve_mm3")
            if capacity not in (None, 0) and variation is not None:
                if abs(float(variation)) > float(capacity) * 0.20:
                    add_check(
                        checks,
                        "AVERTISSEMENT",
                        "VARIATION_RESERVE_FORTE",
                        "variation_reserve_mm3",
                        f"Variation réserve forte pour {code}. À vérifier.",
                    )

        status = "BLOQUANT" if has_blocking(checks) else "OK"

        results.append(
            {
                "barrage_code": code,
                "barrage_nom": barrage.get("nom"),
                "date_interval": date_interval.isoformat(),
                "date_situation": date_situation.isoformat(),
                "status": status,
                "can_save": status != "BLOQUANT",
                "checks": checks,
                "inputs": {
                    "cote_interval": cote_interval,
                    "cote_7h_ngm": item.cote_7h_ngm,
                    "hauteur_bac_mm": item.hauteur_bac_mm,
                    "pluie_mm": item.pluie_mm,
                    "restitutions": restitution_values,
                    "transfert_dar_khrofa_m3": transfert_dar_khrofa,
                },
                "computed": computed,
            }
        )

    can_save_all = all(row["can_save"] for row in results)

    return {
        "status": "ok" if can_save_all else "problem",
        "date_situation": date_situation.isoformat(),
        "date_interval": date_interval.isoformat(),
        "can_save": can_save_all,
        "count": len(results),
        "results": results,
    }


def save_calculs(db: Session, payload: CalculsSaveRequest) -> dict:
    computed_payload = compute_calculs(db, payload)

    if not computed_payload["can_save"]:
        return {
            "status": "problem",
            "message": "Impossible d'enregistrer : certaines lignes contiennent des erreurs bloquantes.",
            "computed": computed_payload,
        }

    date_situation = payload.date_situation
    date_interval = date_situation - timedelta(days=1)

    journee_id = ensure_journee_situation(db, date_situation)

    barrages = fetch_active_barrages(db)
    inputs_by_code = {
        item.barrage_code.upper().strip(): item
        for item in payload.barrages
    }

    saved_rows = []

    try:
        for row in computed_payload["results"]:
            code = row["barrage_code"]
            item = inputs_by_code[code]
            barrage = barrages[code]
            barrage_id = int(barrage["id"])
            c = row["computed"]

            interval_bilan_values = {
                "journee_situation_id": journee_id,
                "hauteur_bac_mm": item.hauteur_bac_mm,
                "pluie_mm": item.pluie_mm,

                "surface_moyenne_km2": c["surface_moyenne_km2"],
                "volume_jour_suivant_mm3": c["volume_next_mm3"],
                "variation_reserve_mm3": c["variation_reserve_mm3"],

                "hauteur_evaporee_mm": c["hauteur_evaporee_mm"],
                "hauteur_corrigee_mm": c["hauteur_corrigee_mm"],

                "evaporation_m3": c["evaporation_m3"],
                "evaporation_1000m3": c["evaporation_1000m3"],
                "debit_evaporation_1000m3s": c["debit_evaporation_1000m3s"],

                "total_restitutions_m3": c["total_restitutions_m3"],
                "transfert_dar_khrofa_m3": c["transfert_dar_khrofa_m3"],
                "apports_raw_m3": c["apports_raw_m3"],
                "apports_m3": c["apports_m3"],
                "debit_m3s": c["debit_m3s"],

                "statut": payload.statut,
                "observation": item.observation,
                "is_from_import": False,
                "source_fichier": "PLATEFORME",
                "source_feuille": "CALCULS",
            }

            current_bilan_values = {
                "journee_situation_id": journee_id,
                "cote_7h_ngm": item.cote_7h_ngm,
                "volume_mm3": c["volume_next_mm3"],
                "surface_km2": c["surface_next_km2"],
                "taux_remplissage": c["taux_remplissage"],
                "statut": payload.statut,
                "observation": item.observation,
                "is_from_import": False,
                "source_fichier": "PLATEFORME",
                "source_feuille": "CALCULS",
            }

            interval_bilan_id = upsert_bilan(
                db,
                barrage_id=barrage_id,
                date_bilan=date_interval,
                values=interval_bilan_values,
            )

            current_bilan_id = upsert_bilan(
                db,
                barrage_id=barrage_id,
                date_bilan=date_situation,
                values=current_bilan_values,
            )

            for restitution in item.restitutions:
                upsert_restitution(
                    db,
                    bilan_id=interval_bilan_id,
                    type_code=restitution.type_code.upper().strip(),
                    valeur_m3=zero(restitution.valeur_m3),
                    observation="Saisie plateforme calculs",
                )

            variables = [
                ("HAUTEUR_EVAPOREE_MM", "Hauteur évaporée", c["hauteur_evaporee_mm"], "mm"),
                ("HAUTEUR_CORRIGEE_MM", "Hauteur corrigée", c["hauteur_corrigee_mm"], "mm"),
                ("EVAPORATION_1000M3", "Evaporation en milliers de m3", c["evaporation_1000m3"], "1000 m3"),
                ("DEBIT_EVAPORATION_1000M3S", "Débit évaporation auxiliaire", c["debit_evaporation_1000m3s"], "1000 m3/s"),
                ("APPORTS_RAW_M3", "Apports bruts avant max(0)", c["apports_raw_m3"], "m3"),
                ("TRANSFERT_DAR_KHROFA_M3", "Transfert Dar Khrofa", c["transfert_dar_khrofa_m3"], "m3"),
            ]

            for code_variable, libelle, valeur, unite in variables:
                upsert_bilan_variable(
                    db,
                    bilan_id=interval_bilan_id,
                    code_variable=code_variable,
                    libelle_variable=libelle,
                    valeur_numeric=valeur,
                    unite=unite,
                )

            saved_rows.append(
                {
                    "barrage_code": code,
                    "interval_bilan_id": interval_bilan_id,
                    "current_bilan_id": current_bilan_id,
                    "date_interval": date_interval.isoformat(),
                    "date_situation": date_situation.isoformat(),
                }
            )

        db.commit()

    except Exception:
        db.rollback()
        raise

    return {
        "status": "ok",
        "message": "Calculs enregistrés avec succès.",
        "date_situation": date_situation.isoformat(),
        "date_interval": date_interval.isoformat(),
        "journee_situation_id": journee_id,
        "saved_count": len(saved_rows),
        "saved_rows": saved_rows,
        "computed": computed_payload,
    }