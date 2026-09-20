import calendar
from datetime import date, timedelta
from typing import Any

from app.modules.situation.mappings import (
    DATE_CHANGEMENT_TAUX,
    NORMAL_RESTITUTION_MAPPING,
    OFFICIAL_TOTALS,
    SITUATION_ROWS,
    TARGET_BARRAGES_ORDER,
    TRANSFER_RESTITUTION_MAPPING,
)


def add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def dkey(d: date) -> str:
    return d.isoformat()


def num(value: Any, default=None):
    if value is None:
        return default
    return float(value)


def zero(value: Any) -> float:
    return 0.0 if value is None else float(value)


def rate(volume, volume_normal):
    if volume is None or volume_normal in (None, 0):
        return None

    result = float(volume) / float(volume_normal) * 100

    if result > 100:
        return 100.0

    return result


def diff(a, b):
    if a is None or b is None:
        return None
    return float(a) - float(b)


def cote_variation_cm(cote_jour, cote_veille):
    if cote_jour is None or cote_veille is None:
        return None
    return (float(cote_jour) - float(cote_veille)) * 100


def get_bilan(raw: dict, code: str, d: date) -> dict | None:
    return raw["bilans"].get((code, dkey(d)))


def get_restitution(raw: dict, code: str, d: date, type_codes: list[str]) -> float:
    total = 0.0
    for type_code in type_codes:
        total += raw["restitutions"].get((code, dkey(d), type_code), 0.0) or 0.0
    return total


def get_special(raw: dict, code: str, d: date, special_code: str) -> float:
    return raw["specials"].get((code, dkey(d), special_code), 0.0) or 0.0


def get_current_cote_normale(raw: dict, code: str):
    rows_info = SITUATION_ROWS.get(code, {})
    if rows_info.get("cote_normale_current") is not None:
        return rows_info["cote_normale_current"]

    barrage = raw["barrages"].get(code) or {}
    return barrage.get("cote_normale_ngm")


def get_current_normal_volume(raw: dict, code: str):
    rows_info = SITUATION_ROWS.get(code, {})
    if rows_info.get("volume_normal_current") is not None:
        return rows_info["volume_normal_current"]

    from_bareme = raw["normal_volumes"].get(code)
    if from_bareme is not None:
        return from_bareme

    barrage = raw["barrages"].get(code) or {}
    return barrage.get("capacite_normale_mm3")


def get_old_normal_volume(code: str):
    return SITUATION_ROWS[code]["old_volume_normal_mm3"]


def build_lachers_normal(raw: dict, code: str, d: date) -> dict[str, float]:
    mapping = NORMAL_RESTITUTION_MAPPING.get(code, {})
    result = {col: 0.0 for col in ["F", "G", "H", "I", "J"]}

    for col, types in mapping.items():
        result[col] = get_restitution(raw, code, d, types)

    result["K"] = sum(result[col] for col in ["F", "G", "H", "I", "J"])
    return result


def build_lachers_transfer(raw: dict, code: str, d: date) -> dict[str, float]:
    mapping = TRANSFER_RESTITUTION_MAPPING.get(code, {})
    result = {col: 0.0 for col in ["F", "G", "H", "I", "J", "K"]}

    for col, types in mapping.items():
        result[col] = get_restitution(raw, code, d, types)

    result["L"] = sum(result[col] for col in ["F", "G", "H", "I", "J", "K"])
    return result


def check_situation_data(raw: dict, date_situation: date) -> dict:
    date_veille = date_situation - timedelta(days=1)
    date_annee_precedente = add_months(date_situation, -12)

    missing_barrages = []
    missing_bilans = []
    missing_required_values = []

    for code in TARGET_BARRAGES_ORDER:
        if code not in raw["barrages"]:
            missing_barrages.append(code)
            continue

        for label, d in [
            ("date_situation", date_situation),
            ("date_veille", date_veille),
            ("date_annee_precedente", date_annee_precedente),
        ]:
            bilan = get_bilan(raw, code, d)

            if not bilan:
                missing_bilans.append(
                    {
                        "barrage_code": code,
                        "date_type": label,
                        "date": d.isoformat(),
                    }
                )
                continue

            for field in ["cote_7h_ngm", "volume_mm3"]:
                if bilan.get(field) is None:
                    missing_required_values.append(
                        {
                            "barrage_code": code,
                            "date_type": label,
                            "date": d.isoformat(),
                            "field": field,
                        }
                    )

    can_generate = (
        len(missing_barrages) == 0
        and len(missing_bilans) == 0
        and len(missing_required_values) == 0
    )

    return {
        "date_situation": date_situation.isoformat(),
        "date_veille": date_veille.isoformat(),
        "date_annee_precedente": date_annee_precedente.isoformat(),
        "can_generate": can_generate,
        "missing_barrages": missing_barrages,
        "missing_bilans": missing_bilans,
        "missing_required_values": missing_required_values,
    }


def build_situation_data(raw: dict, date_situation: date) -> dict:
    date_veille = date_situation - timedelta(days=1)
    date_annee_precedente = add_months(date_situation, -12)

    check = check_situation_data(raw, date_situation)

    normal_rows = {}
    transfer_rows = {}

    normal_totals = {
        "B": 0.0,
        "C": 0.0,
        "D": 0.0,
        "F": 0.0,
        "G": 0.0,
        "H": 0.0,
        "I": 0.0,
        "J": 0.0,
        "K": 0.0,
        "O": 0.0,
        "T": 0.0,
    }

    transfer_totals = {
        "B": 0.0,
        "C": 0.0,
        "D": 0.0,
        "F": 0.0,
        "G": 0.0,
        "H": 0.0,
        "I": 0.0,
        "J": 0.0,
        "K": 0.0,
        "L": 0.0,
        "P": 0.0,
    }

    for code in TARGET_BARRAGES_ORDER:
        rows_info = SITUATION_ROWS[code]

        bilan_jour = get_bilan(raw, code, date_situation) or {}
        bilan_veille = get_bilan(raw, code, date_veille) or {}
        bilan_annee_precedente = get_bilan(raw, code, date_annee_precedente) or {}

        cote_normale = get_current_cote_normale(raw, code)
        volume_normal_current = get_current_normal_volume(raw, code)
        volume_normal_old = get_old_normal_volume(code)

        cote_veille = num(bilan_veille.get("cote_7h_ngm"))
        cote_jour = num(bilan_jour.get("cote_7h_ngm"))

        volume_veille = num(bilan_veille.get("volume_mm3"))
        volume_jour = num(bilan_jour.get("volume_mm3"))
        volume_annee_precedente = num(bilan_annee_precedente.get("volume_mm3"))

        pluie_interval = zero(bilan_veille.get("pluie_mm"))

        l_normal = build_lachers_normal(raw, code, date_veille)
        l_transfer = build_lachers_transfer(raw, code, date_veille)

        previous_reference_normal = (
            volume_normal_current
            if date_annee_precedente > DATE_CHANGEMENT_TAUX
            else volume_normal_old
        )

        normal_current_rate = rate(volume_jour, volume_normal_current)
        normal_previous_rate = rate(volume_annee_precedente, previous_reference_normal)

        # Très important :
        # La page Situation Détaillée (T) utilise l'ancien volume normal.
        transfer_current_rate = rate(volume_jour, volume_normal_old)
        transfer_previous_rate = rate(volume_annee_precedente, volume_normal_old)

        normal_row = {
            "barrage_code": code,
            "label": rows_info["label"],
            "cote_row": rows_info["cote_row"],
            "volume_row": rows_info["volume_row"],
            "cote_normale": cote_normale,
            "volume_normal_current": volume_normal_current,
            "volume_normal_old": volume_normal_old,
            "cote_veille": cote_veille,
            "cote_jour": cote_jour,
            "variation_cote_cm": cote_variation_cm(cote_jour, cote_veille),
            "volume_veille": volume_veille,
            "volume_jour": volume_jour,
            "variation_volume": diff(volume_jour, volume_veille),
            "volume_annee_precedente": volume_annee_precedente,
            "taux_remplissage": normal_current_rate,
            "taux_annee_precedente": normal_previous_rate,
            "pluie_mm": pluie_interval,
            "lachers": l_normal,
        }

        transfer_row = {
            "barrage_code": code,
            "label": rows_info["label"],
            "cote_row": rows_info["cote_row"],
            "volume_row": rows_info["volume_row"],
            "cote_normale": cote_normale,
            "volume_normal_current": volume_normal_current,
            "volume_normal_old": volume_normal_old,
            "cote_veille": cote_veille,
            "cote_jour": cote_jour,
            "variation_cote_cm": cote_variation_cm(cote_jour, cote_veille),
            "volume_veille": volume_veille,
            "volume_jour": volume_jour,
            "variation_volume": diff(volume_jour, volume_veille),
            "volume_annee_precedente": volume_annee_precedente,
            "taux_remplissage": transfer_current_rate,
            "taux_annee_precedente": transfer_previous_rate,
            "pluie_mm": pluie_interval,
            "lachers": l_transfer,
        }

        normal_rows[code] = normal_row
        transfer_rows[code] = transfer_row

        # Page normale : volume normal actuel.
        normal_totals["B"] += zero(volume_normal_current)
        normal_totals["C"] += zero(volume_veille)
        normal_totals["D"] += zero(volume_jour)
        normal_totals["O"] += zero(volume_annee_precedente)
        normal_totals["T"] += zero(volume_normal_old)

        for col in ["F", "G", "H", "I", "J", "K"]:
            normal_totals[col] += zero(l_normal.get(col))

        # Page (T) : ancien volume normal.
        transfer_totals["B"] += zero(volume_normal_old)
        transfer_totals["C"] += zero(volume_veille)
        transfer_totals["D"] += zero(volume_jour)
        transfer_totals["P"] += zero(volume_annee_precedente)

        for col in ["F", "G", "H", "I", "J", "K", "L"]:
            transfer_totals[col] += zero(l_transfer.get(col))

    normal_totals["B"] = OFFICIAL_TOTALS["volume_normal_current"]
    normal_totals["T"] = OFFICIAL_TOTALS["volume_normal_old"]

    transfer_totals["B"] = OFFICIAL_TOTALS["volume_normal_old"]

    normal_previous_reference_total = (
        normal_totals["B"]
        if date_annee_precedente > DATE_CHANGEMENT_TAUX
        else normal_totals["T"]
    )

    normal_totals["E"] = normal_totals["D"] - normal_totals["C"]
    normal_totals["M"] = normal_totals["D"]
    normal_totals["N"] = rate(normal_totals["D"], normal_totals["B"])
    normal_totals["P"] = rate(normal_totals["O"], normal_previous_reference_total)
    normal_totals["U"] = normal_totals["D"]
    normal_totals["V"] = normal_totals["O"]

    transfer_previous_reference_total = OFFICIAL_TOTALS["volume_normal_old"]

    transfer_totals["E"] = transfer_totals["D"] - transfer_totals["C"]
    transfer_totals["N"] = transfer_totals["D"]
    transfer_totals["O"] = rate(transfer_totals["D"], transfer_totals["B"])
    transfer_totals["Q"] = rate(transfer_totals["P"], transfer_previous_reference_total)

    garde_am = get_special(raw, "BOEM", date_situation, "BGE_GARDE_AM")
    garde_av = get_special(raw, "BOEM", date_situation, "BGE_GARDE_AV")
    garde_pluie = get_special(raw, "BOEM", date_situation, "BGE_GARDE_PLUIE")

    return {
        "dates": {
            "date_situation": date_situation,
            "date_veille": date_veille,
            "date_annee_precedente": date_annee_precedente,
        },
        "check": check,
        "normal_rows": normal_rows,
        "normal_totals": normal_totals,
        "transfer_rows": transfer_rows,
        "transfer_totals": transfer_totals,
        "specials": {
            "garde_loukkos_amont": garde_am,
            "garde_loukkos_aval": garde_av,
            "garde_loukkos_pluie": garde_pluie,
        },
    }

# === ABHL SITUATION DYNAMIQUE V2 PATCH START ===
# Ce bloc surcharge les calculs pour inclure les nouveaux barrages dans la situation quotidienne.

def _abhl_sq_codes(raw: dict) -> list[str]:
    return raw.get("situation_codes") or list(TARGET_BARRAGES_ORDER)


def _abhl_sq_official_codes(raw: dict) -> list[str]:
    return raw.get("official_codes") or list(TARGET_BARRAGES_ORDER)


def _abhl_sq_dynamic_codes(raw: dict) -> list[str]:
    return raw.get("dynamic_codes") or [
        code for code in _abhl_sq_codes(raw)
        if code not in TARGET_BARRAGES_ORDER
    ]


def _abhl_sq_is_dynamic(raw: dict, code: str) -> bool:
    return code in set(_abhl_sq_dynamic_codes(raw))


def _abhl_sq_label(raw: dict, code: str, index: int) -> str:
    rows_info = SITUATION_ROWS.get(code)

    if rows_info and rows_info.get("label"):
        return rows_info["label"]

    barrage = raw.get("barrages", {}).get(code, {})
    nom = barrage.get("nom_court") or barrage.get("nom") or code
    return f"{index}. {nom}"


def _abhl_sq_bathy_label(raw: dict, code: str) -> str:
    if code in SITUATION_ROWS:
        return "    ( 2023 )"

    return "    ( plateforme )"


def _abhl_sq_current_cote_normale(raw: dict, code: str):
    rows_info = SITUATION_ROWS.get(code, {})
    if rows_info.get("cote_normale_current") is not None:
        return rows_info["cote_normale_current"]

    barrage = raw["barrages"].get(code) or {}
    return barrage.get("cote_normale_ngm")


def _abhl_sq_current_normal_volume(raw: dict, code: str):
    rows_info = SITUATION_ROWS.get(code, {})
    if rows_info.get("volume_normal_current") is not None:
        return rows_info["volume_normal_current"]

    from_bareme = raw.get("normal_volumes", {}).get(code)
    if from_bareme is not None:
        return from_bareme

    barrage = raw["barrages"].get(code) or {}
    return barrage.get("capacite_normale_mm3")


def _abhl_sq_old_normal_volume(raw: dict, code: str):
    rows_info = SITUATION_ROWS.get(code, {})
    if rows_info.get("old_volume_normal_mm3") is not None:
        return rows_info["old_volume_normal_mm3"]

    # Pour un nouveau barrage il n'y a pas encore de "ancien volume normal".
    # On utilise la capacité normale actuelle comme référence historique provisoire.
    return _abhl_sq_current_normal_volume(raw, code)


def get_current_cote_normale(raw: dict, code: str):
    return _abhl_sq_current_cote_normale(raw, code)


def get_current_normal_volume(raw: dict, code: str):
    return _abhl_sq_current_normal_volume(raw, code)


def get_old_normal_volume(code: str):
    # Compatibilité avec l'ancien code.
    return SITUATION_ROWS[code]["old_volume_normal_mm3"]


def _abhl_sq_group_type_normal(type_code: str) -> str:
    tc = (type_code or "").upper()

    if "TURBINAGE_EXCLUSIF" in tc or tc == "TURBINAGE_EXCLUSIF" or "EXCLUSIF" in tc:
        return "G"

    if "TURBINAGE" in tc:
        return "F"

    if "IRRIGATION" in tc or "PRISE" in tc or "SIPHON" in tc:
        return "H"

    if "AEPI" in tc or tc.startswith("AEP"):
        return "I"

    return "J"


def _abhl_sq_group_type_transfer(type_code: str) -> str:
    tc = (type_code or "").upper()

    if "TURBINAGE_EXCLUSIF" in tc or tc == "TURBINAGE_EXCLUSIF" or "EXCLUSIF" in tc:
        return "G"

    if "TURBINAGE" in tc:
        return "F"

    if "TRANSFERT" in tc:
        return "H"

    if "IRRIGATION" in tc or "PRISE" in tc or "SIPHON" in tc:
        return "I"

    if "AEPI" in tc or tc.startswith("AEP"):
        return "J"

    return "K"


def _abhl_sq_dynamic_restitution_type_codes(raw: dict, code: str, d: date) -> list[str]:
    configured = [
        item["type_code"]
        for item in raw.get("barrage_restitution_types", {}).get(code, [])
        if item.get("type_code")
    ]

    existing = [
        type_code
        for (barrage_code, date_key_value, type_code), value in raw.get("restitutions", {}).items()
        if barrage_code == code and date_key_value == dkey(d)
    ]

    result = []

    for type_code in configured + existing:
        if type_code not in result:
            result.append(type_code)

    return result


def build_lachers_normal(raw: dict, code: str, d: date) -> dict[str, float]:
    # Ancien comportement exact pour les barrages officiels.
    if code in NORMAL_RESTITUTION_MAPPING:
        mapping = NORMAL_RESTITUTION_MAPPING.get(code, {})
        result = {col: 0.0 for col in ["F", "G", "H", "I", "J"]}

        for col, types in mapping.items():
            result[col] = get_restitution(raw, code, d, types)

        result["K"] = sum(result[col] for col in ["F", "G", "H", "I", "J"])
        return result

    # Nouveau comportement dynamique pour les nouveaux barrages.
    result = {col: 0.0 for col in ["F", "G", "H", "I", "J"]}

    for type_code in _abhl_sq_dynamic_restitution_type_codes(raw, code, d):
        col = _abhl_sq_group_type_normal(type_code)
        result[col] += get_restitution(raw, code, d, [type_code])

    result["K"] = sum(result[col] for col in ["F", "G", "H", "I", "J"])
    return result


def build_lachers_transfer(raw: dict, code: str, d: date) -> dict[str, float]:
    # Ancien comportement exact pour les barrages officiels.
    if code in TRANSFER_RESTITUTION_MAPPING:
        mapping = TRANSFER_RESTITUTION_MAPPING.get(code, {})
        result = {col: 0.0 for col in ["F", "G", "H", "I", "J", "K"]}

        for col, types in mapping.items():
            result[col] = get_restitution(raw, code, d, types)

        result["L"] = sum(result[col] for col in ["F", "G", "H", "I", "J", "K"])
        return result

    # Nouveau comportement dynamique pour les nouveaux barrages.
    result = {col: 0.0 for col in ["F", "G", "H", "I", "J", "K"]}

    for type_code in _abhl_sq_dynamic_restitution_type_codes(raw, code, d):
        col = _abhl_sq_group_type_transfer(type_code)
        result[col] += get_restitution(raw, code, d, [type_code])

    result["L"] = sum(result[col] for col in ["F", "G", "H", "I", "J", "K"])
    return result


def check_situation_data(raw: dict, date_situation: date) -> dict:
    date_veille = date_situation - timedelta(days=1)
    date_annee_precedente = add_months(date_situation, -12)

    missing_barrages = []
    missing_bilans = []
    missing_required_values = []

    official_codes = set(_abhl_sq_official_codes(raw))

    for code in _abhl_sq_codes(raw):
        if code not in raw["barrages"]:
            missing_barrages.append(code)
            continue

        required_dates = [
            ("date_situation", date_situation),
            ("date_veille", date_veille),
        ]

        # Pour les barrages officiels, l'année précédente reste obligatoire.
        # Pour les nouveaux barrages, elle est facultative car ils n'existaient pas forcément l'année précédente.
        if code in official_codes:
            required_dates.append(("date_annee_precedente", date_annee_precedente))

        for label, d in required_dates:
            bilan = get_bilan(raw, code, d)

            if not bilan:
                missing_bilans.append(
                    {
                        "barrage_code": code,
                        "date_type": label,
                        "date": d.isoformat(),
                    }
                )
                continue

            for field in ["cote_7h_ngm", "volume_mm3"]:
                if bilan.get(field) is None:
                    missing_required_values.append(
                        {
                            "barrage_code": code,
                            "date_type": label,
                            "date": d.isoformat(),
                            "field": field,
                        }
                    )

    can_generate = (
        len(missing_barrages) == 0
        and len(missing_bilans) == 0
        and len(missing_required_values) == 0
    )

    return {
        "date_situation": date_situation.isoformat(),
        "date_veille": date_veille.isoformat(),
        "date_annee_precedente": date_annee_precedente.isoformat(),
        "can_generate": can_generate,
        "missing_barrages": missing_barrages,
        "missing_bilans": missing_bilans,
        "missing_required_values": missing_required_values,
        "dynamic_barrages": _abhl_sq_dynamic_codes(raw),
    }


def build_situation_data(raw: dict, date_situation: date) -> dict:
    date_veille = date_situation - timedelta(days=1)
    date_annee_precedente = add_months(date_situation, -12)

    check = check_situation_data(raw, date_situation)

    normal_rows = {}
    transfer_rows = {}

    normal_totals = {
        "B": 0.0, "C": 0.0, "D": 0.0, "F": 0.0, "G": 0.0,
        "H": 0.0, "I": 0.0, "J": 0.0, "K": 0.0,
        "O": 0.0, "T": 0.0,
    }

    transfer_totals = {
        "B": 0.0, "C": 0.0, "D": 0.0, "F": 0.0, "G": 0.0,
        "H": 0.0, "I": 0.0, "J": 0.0, "K": 0.0, "L": 0.0,
        "P": 0.0,
    }

    dynamic_current_total = 0.0
    dynamic_old_total = 0.0

    codes = _abhl_sq_codes(raw)

    for index, code in enumerate(codes, start=1):
        bilan_jour = get_bilan(raw, code, date_situation) or {}
        bilan_veille = get_bilan(raw, code, date_veille) or {}
        bilan_annee_precedente = get_bilan(raw, code, date_annee_precedente) or {}

        cote_normale = _abhl_sq_current_cote_normale(raw, code)
        volume_normal_current = _abhl_sq_current_normal_volume(raw, code)
        volume_normal_old = _abhl_sq_old_normal_volume(raw, code)

        if _abhl_sq_is_dynamic(raw, code):
            dynamic_current_total += zero(volume_normal_current)
            dynamic_old_total += zero(volume_normal_old)

        cote_veille = num(bilan_veille.get("cote_7h_ngm"))
        cote_jour = num(bilan_jour.get("cote_7h_ngm"))

        volume_veille = num(bilan_veille.get("volume_mm3"))
        volume_jour = num(bilan_jour.get("volume_mm3"))
        volume_annee_precedente = num(bilan_annee_precedente.get("volume_mm3"))

        pluie_interval = zero(bilan_veille.get("pluie_mm"))

        l_normal = build_lachers_normal(raw, code, date_veille)
        l_transfer = build_lachers_transfer(raw, code, date_veille)

        previous_reference_normal = (
            volume_normal_current
            if date_annee_precedente > DATE_CHANGEMENT_TAUX
            else volume_normal_old
        )

        normal_current_rate = rate(volume_jour, volume_normal_current)
        normal_previous_rate = rate(volume_annee_precedente, previous_reference_normal)

        transfer_current_rate = rate(volume_jour, volume_normal_old)
        transfer_previous_rate = rate(volume_annee_precedente, volume_normal_old)

        label = _abhl_sq_label(raw, code, index)

        normal_row = {
            "barrage_code": code,
            "label": label,
            "bathy_label": _abhl_sq_bathy_label(raw, code),
            "cote_row": None,
            "volume_row": None,
            "cote_normale": cote_normale,
            "volume_normal_current": volume_normal_current,
            "volume_normal_old": volume_normal_old,
            "cote_veille": cote_veille,
            "cote_jour": cote_jour,
            "variation_cote_cm": cote_variation_cm(cote_jour, cote_veille),
            "volume_veille": volume_veille,
            "volume_jour": volume_jour,
            "variation_volume": diff(volume_jour, volume_veille),
            "volume_annee_precedente": volume_annee_precedente,
            "taux_remplissage": normal_current_rate,
            "taux_annee_precedente": normal_previous_rate,
            "pluie_mm": pluie_interval,
            "lachers": l_normal,
        }

        transfer_row = {
            **normal_row,
            "taux_remplissage": transfer_current_rate,
            "taux_annee_precedente": transfer_previous_rate,
            "lachers": l_transfer,
        }

        normal_rows[code] = normal_row
        transfer_rows[code] = transfer_row

        normal_totals["C"] += zero(volume_veille)
        normal_totals["D"] += zero(volume_jour)
        normal_totals["O"] += zero(volume_annee_precedente)

        for col in ["F", "G", "H", "I", "J", "K"]:
            normal_totals[col] += zero(l_normal.get(col))

        transfer_totals["C"] += zero(volume_veille)
        transfer_totals["D"] += zero(volume_jour)
        transfer_totals["P"] += zero(volume_annee_precedente)

        for col in ["F", "G", "H", "I", "J", "K", "L"]:
            transfer_totals[col] += zero(l_transfer.get(col))

    # Les totaux officiels restent inchangés pour les 13 barrages historiques,
    # puis on ajoute les volumes normaux des nouveaux barrages.
    normal_totals["B"] = OFFICIAL_TOTALS["volume_normal_current"] + dynamic_current_total
    normal_totals["T"] = OFFICIAL_TOTALS["volume_normal_old"] + dynamic_old_total
    transfer_totals["B"] = OFFICIAL_TOTALS["volume_normal_old"] + dynamic_old_total

    normal_previous_reference_total = (
        normal_totals["B"]
        if date_annee_precedente > DATE_CHANGEMENT_TAUX
        else normal_totals["T"]
    )

    normal_totals["E"] = normal_totals["D"] - normal_totals["C"]
    normal_totals["M"] = normal_totals["D"]
    normal_totals["N"] = rate(normal_totals["D"], normal_totals["B"])
    normal_totals["P"] = rate(normal_totals["O"], normal_previous_reference_total)
    normal_totals["U"] = normal_totals["D"]
    normal_totals["V"] = normal_totals["O"]

    transfer_previous_reference_total = transfer_totals["B"]

    transfer_totals["E"] = transfer_totals["D"] - transfer_totals["C"]
    transfer_totals["N"] = transfer_totals["D"]
    transfer_totals["O"] = rate(transfer_totals["D"], transfer_totals["B"])
    transfer_totals["Q"] = rate(transfer_totals["P"], transfer_previous_reference_total)

    garde_am = get_special(raw, "BOEM", date_situation, "BGE_GARDE_AM")
    garde_av = get_special(raw, "BOEM", date_situation, "BGE_GARDE_AV")
    garde_pluie = get_special(raw, "BOEM", date_situation, "BGE_GARDE_PLUIE")

    return {
        "dates": {
            "date_situation": date_situation,
            "date_veille": date_veille,
            "date_annee_precedente": date_annee_precedente,
        },
        "check": check,
        "situation_codes": codes,
        "official_codes": _abhl_sq_official_codes(raw),
        "dynamic_codes": _abhl_sq_dynamic_codes(raw),
        "barrages": raw.get("barrages", {}),
        "normal_rows": normal_rows,
        "normal_totals": normal_totals,
        "transfer_rows": transfer_rows,
        "transfer_totals": transfer_totals,
        "specials": {
            "garde_loukkos_amont": garde_am,
            "garde_loukkos_aval": garde_av,
            "garde_loukkos_pluie": garde_pluie,
        },
    }

# === ABHL SITUATION DYNAMIQUE V2 PATCH END ===

# === ABHL SITUATION DYNAMIC FIX CAPACITY V1 START ===
# Correction cohérence : pour les nouveaux barrages,
# le volume normal = capacite_normale_mm3, pas volume du barème à la cote normale.

def _abhl_sq_current_normal_volume(raw: dict, code: str):
    rows_info = SITUATION_ROWS.get(code, {})

    # Barrages historiques : garder les valeurs officielles fixes.
    if rows_info.get("volume_normal_current") is not None:
        return rows_info["volume_normal_current"]

    barrage = raw.get("barrages", {}).get(code) or {}
    capacity = barrage.get("capacite_normale_mm3")

    if capacity is not None:
        return capacity

    from_lookup = raw.get("normal_volumes", {}).get(code)
    if from_lookup is not None:
        return from_lookup

    return None


def _abhl_sq_old_normal_volume(raw: dict, code: str):
    rows_info = SITUATION_ROWS.get(code, {})

    # Barrages historiques : garder les anciens volumes officiels.
    if rows_info.get("old_volume_normal_mm3") is not None:
        return rows_info["old_volume_normal_mm3"]

    # Nouveau barrage : pas d'ancien volume normal, donc on garde la capacité actuelle.
    return _abhl_sq_current_normal_volume(raw, code)


def get_current_normal_volume(raw: dict, code: str):
    return _abhl_sq_current_normal_volume(raw, code)

# === ABHL SITUATION DYNAMIC FIX CAPACITY V1 END ===

# === ABHL SITUATION GROUPED ORDER + SUBTOTALS V1 START ===
# Correctif professionnel :
# - les nouveaux barrages sont insérés dans leur système/agence
# - les totaux N-1 ne considèrent un nouveau barrage que s'il possède réellement une donnée N-1
# - les anciens barrages gardent leurs valeurs historiques déjà validées

_ABHL_SQ_GROUP_ORDER = [
    "LOUKKOS_TOTAL",
    "TANGER_TOTAL",
    "TETOUAN_TOTAL",
    "CHEFCHAOUEN",
    "AL_HOCEIMA_TOTAL",
]

_ABHL_SQ_OFFICIAL_GROUPS = {
    "LOUKKOS_TOTAL": ["BOEM", "DAR_KHROFA"],
    "TANGER_TOTAL": ["BIB", "9_AVRIL", "KHARROUB", "TANGER_MED"],
    "TETOUAN_TOTAL": ["NAKHLA", "SMIR", "MHB_MEHDI", "CAI"],
    "CHEFCHAOUEN": ["CHEFCHAOUEN"],
    "AL_HOCEIMA_TOTAL": ["KHATTABI", "JOUMOUA"],
}


def _abhl_sq_group_code_from_agence(agence_code):
    agence = (agence_code or "").upper()

    if agence == "LOUKKOS":
        return "LOUKKOS_TOTAL"
    if agence == "TANGER":
        return "TANGER_TOTAL"
    if agence == "TETOUAN":
        return "TETOUAN_TOTAL"
    if agence == "CHEFCHAOUEN":
        return "CHEFCHAOUEN"
    if agence == "AL_HOCEIMA":
        return "AL_HOCEIMA_TOTAL"

    return None


def _abhl_sq_group_code_for_barrage_raw(raw: dict, code: str):
    for group_code, official_codes in _ABHL_SQ_OFFICIAL_GROUPS.items():
        if code in official_codes:
            return group_code

    barrage = (raw.get("barrages") or {}).get(code) or {}
    return _abhl_sq_group_code_from_agence(barrage.get("agence_code"))


def _abhl_sq_dynamic_codes(raw: dict) -> list[str]:
    barrages = raw.get("barrages") or {}
    return [code for code in barrages.keys() if code not in TARGET_BARRAGES_ORDER]


def _abhl_sq_codes(raw: dict) -> list[str]:
    """
    Ordre métier pour la situation :
    - anciens barrages dans leur ordre officiel
    - nouveaux barrages ajoutés dans leur système/agence
    """
    barrages = raw.get("barrages") or {}
    all_codes = list(barrages.keys())

    result = []
    used = set()

    for group_code in _ABHL_SQ_GROUP_ORDER:
        for code in _ABHL_SQ_OFFICIAL_GROUPS.get(group_code, []):
            if code in barrages and code not in used:
                result.append(code)
                used.add(code)

        dynamic_for_group = [
            code for code in all_codes
            if code not in used
            and code not in TARGET_BARRAGES_ORDER
            and _abhl_sq_group_code_for_barrage_raw(raw, code) == group_code
        ]

        dynamic_for_group.sort(
            key=lambda code: (
                (barrages.get(code) or {}).get("ordre_situation")
                or (barrages.get(code) or {}).get("ordre_affichage")
                or 9999,
                code,
            )
        )

        for code in dynamic_for_group:
            result.append(code)
            used.add(code)

    # Sécurité : si une agence est inconnue, on ajoute quand même le barrage à la fin.
    rest = [
        code for code in all_codes
        if code not in used
        and code not in TARGET_BARRAGES_ORDER
    ]

    rest.sort(
        key=lambda code: (
            (barrages.get(code) or {}).get("ordre_situation")
            or (barrages.get(code) or {}).get("ordre_affichage")
            or 9999,
            code,
        )
    )

    result.extend(rest)

    return result


def _abhl_sq_official_codes(raw: dict) -> list[str]:
    barrages = raw.get("barrages") or {}
    return [code for code in TARGET_BARRAGES_ORDER if code in barrages]


def _abhl_sq_is_dynamic(raw: dict, code: str) -> bool:
    return code not in TARGET_BARRAGES_ORDER


def build_situation_data(raw: dict, date_situation: date) -> dict:
    """
    Version corrigée :
    - ordre par système/agence
    - totaux courants incluent les nouveaux barrages
    - N-1 pour les nouveaux barrages : inclus seulement si une donnée N-1 existe
    """
    date_veille = date_situation - timedelta(days=1)
    date_annee_precedente = add_months(date_situation, -12)

    check = check_situation_data(raw, date_situation)

    normal_rows = {}
    transfer_rows = {}

    normal_totals = {
        "B": 0.0, "C": 0.0, "D": 0.0, "F": 0.0, "G": 0.0,
        "H": 0.0, "I": 0.0, "J": 0.0, "K": 0.0,
        "O": 0.0, "T": 0.0,
    }

    transfer_totals = {
        "B": 0.0, "C": 0.0, "D": 0.0, "F": 0.0, "G": 0.0,
        "H": 0.0, "I": 0.0, "J": 0.0, "K": 0.0, "L": 0.0,
        "P": 0.0,
    }

    dynamic_current_total = 0.0
    dynamic_old_total_with_history = 0.0

    codes = _abhl_sq_codes(raw)

    for index, code in enumerate(codes, start=1):
        bilan_jour = get_bilan(raw, code, date_situation) or {}
        bilan_veille = get_bilan(raw, code, date_veille) or {}
        bilan_annee_precedente = get_bilan(raw, code, date_annee_precedente) or {}

        cote_normale = _abhl_sq_current_cote_normale(raw, code)
        volume_normal_current = _abhl_sq_current_normal_volume(raw, code)
        volume_normal_old = _abhl_sq_old_normal_volume(raw, code)

        cote_veille = num(bilan_veille.get("cote_7h_ngm"))
        cote_jour = num(bilan_jour.get("cote_7h_ngm"))

        volume_veille = num(bilan_veille.get("volume_mm3"))
        volume_jour = num(bilan_jour.get("volume_mm3"))
        volume_annee_precedente = num(bilan_annee_precedente.get("volume_mm3"))

        # Le nouveau barrage compte dans le total courant.
        if _abhl_sq_is_dynamic(raw, code):
            dynamic_current_total += zero(volume_normal_current)

            # Mais il ne compte dans le total N-1 que s'il a réellement une donnée N-1.
            if volume_annee_precedente is not None:
                dynamic_old_total_with_history += zero(volume_normal_old)

        pluie_interval = zero(bilan_veille.get("pluie_mm"))

        l_normal = build_lachers_normal(raw, code, date_veille)
        l_transfer = build_lachers_transfer(raw, code, date_veille)

        previous_reference_normal = (
            volume_normal_current
            if date_annee_precedente > DATE_CHANGEMENT_TAUX
            else volume_normal_old
        )

        normal_current_rate = rate(volume_jour, volume_normal_current)
        normal_previous_rate = rate(volume_annee_precedente, previous_reference_normal)

        transfer_current_rate = rate(volume_jour, volume_normal_old)
        transfer_previous_rate = rate(volume_annee_precedente, volume_normal_old)

        label = _abhl_sq_label(raw, code, index)

        normal_row = {
            "barrage_code": code,
            "label": label,
            "bathy_label": _abhl_sq_bathy_label(raw, code),
            "cote_row": None,
            "volume_row": None,
            "cote_normale": cote_normale,
            "volume_normal_current": volume_normal_current,
            "volume_normal_old": volume_normal_old,
            "cote_veille": cote_veille,
            "cote_jour": cote_jour,
            "variation_cote_cm": cote_variation_cm(cote_jour, cote_veille),
            "volume_veille": volume_veille,
            "volume_jour": volume_jour,
            "variation_volume": diff(volume_jour, volume_veille),
            "volume_annee_precedente": volume_annee_precedente,
            "taux_remplissage": normal_current_rate,
            "taux_annee_precedente": normal_previous_rate,
            "pluie_mm": pluie_interval,
            "lachers": l_normal,
            "group_code": _abhl_sq_group_code_for_barrage_raw(raw, code),
            "is_dynamic": _abhl_sq_is_dynamic(raw, code),
        }

        transfer_row = {
            **normal_row,
            "taux_remplissage": transfer_current_rate,
            "taux_annee_precedente": transfer_previous_rate,
            "lachers": l_transfer,
        }

        normal_rows[code] = normal_row
        transfer_rows[code] = transfer_row

        normal_totals["C"] += zero(volume_veille)
        normal_totals["D"] += zero(volume_jour)

        if volume_annee_precedente is not None:
            normal_totals["O"] += zero(volume_annee_precedente)

        for col in ["F", "G", "H", "I", "J", "K"]:
            normal_totals[col] += zero(l_normal.get(col))

        transfer_totals["C"] += zero(volume_veille)
        transfer_totals["D"] += zero(volume_jour)

        if volume_annee_precedente is not None:
            transfer_totals["P"] += zero(volume_annee_precedente)

        for col in ["F", "G", "H", "I", "J", "K", "L"]:
            transfer_totals[col] += zero(l_transfer.get(col))

    # Total courant = total officiel + nouveaux barrages.
    normal_totals["B"] = OFFICIAL_TOTALS["volume_normal_current"] + dynamic_current_total

    # Total N-1 = total officiel N-1 + nouveaux barrages uniquement s'ils possèdent un historique N-1.
    normal_totals["T"] = OFFICIAL_TOTALS["volume_normal_old"] + dynamic_old_total_with_history
    transfer_totals["B"] = OFFICIAL_TOTALS["volume_normal_old"] + dynamic_old_total_with_history

    normal_previous_reference_total = (
        normal_totals["B"]
        if date_annee_precedente > DATE_CHANGEMENT_TAUX
        else normal_totals["T"]
    )

    normal_totals["E"] = normal_totals["D"] - normal_totals["C"]
    normal_totals["M"] = normal_totals["D"]
    normal_totals["N"] = rate(normal_totals["D"], normal_totals["B"])
    normal_totals["P"] = rate(normal_totals["O"], normal_previous_reference_total)
    normal_totals["U"] = normal_totals["D"]
    normal_totals["V"] = normal_totals["O"]

    transfer_previous_reference_total = transfer_totals["B"]

    transfer_totals["E"] = transfer_totals["D"] - transfer_totals["C"]
    transfer_totals["N"] = transfer_totals["D"]
    transfer_totals["O"] = rate(transfer_totals["D"], transfer_totals["B"])
    transfer_totals["Q"] = rate(transfer_totals["P"], transfer_previous_reference_total)

    garde_am = get_special(raw, "BOEM", date_situation, "BGE_GARDE_AM")
    garde_av = get_special(raw, "BOEM", date_situation, "BGE_GARDE_AV")
    garde_pluie = get_special(raw, "BOEM", date_situation, "BGE_GARDE_PLUIE")

    return {
        "dates": {
            "date_situation": date_situation,
            "date_veille": date_veille,
            "date_annee_precedente": date_annee_precedente,
        },
        "check": check,
        "situation_codes": codes,
        "official_codes": _abhl_sq_official_codes(raw),
        "dynamic_codes": _abhl_sq_dynamic_codes(raw),
        "barrages": raw.get("barrages", {}),
        "normal_rows": normal_rows,
        "normal_totals": normal_totals,
        "transfer_rows": transfer_rows,
        "transfer_totals": transfer_totals,
        "specials": {
            "garde_loukkos_amont": garde_am,
            "garde_loukkos_aval": garde_av,
            "garde_loukkos_pluie": garde_pluie,
        },
    }

# === ABHL SITUATION GROUPED ORDER + SUBTOTALS V1 END ===

# === ABHL SITUATION DESIGN FIX LABELS V1 START ===
# Correction d'affichage : les numéros des barrages sont recalculés après insertion
# des nouveaux barrages dans leur groupe. Cela évite les doublons comme 7. TEST 02
# puis 7. Nakhla.

import re as _abhl_sq_re


def _abhl_sq_clean_label_name(label: str) -> str:
    if not label:
        return ""
    return _abhl_sq_re.sub(r"^\s*\d+\.\s*", "", str(label)).strip()


def _abhl_sq_label(raw: dict, code: str, index: int) -> str:
    rows_info = SITUATION_ROWS.get(code)

    if rows_info and rows_info.get("label"):
        name = _abhl_sq_clean_label_name(rows_info["label"])
    else:
        barrage = raw.get("barrages", {}).get(code, {})
        name = barrage.get("nom_court") or barrage.get("nom") or code

    return f"{index}. {name}"

# === ABHL SITUATION DESIGN FIX LABELS V1 END ===

# === ABHL V20 PARTIAL SITUATION + EXCEL MISSING VALUES START ===
# Objectif :
# - La situation quotidienne doit pouvoir se générer même si certains bilans sont manquants.
# - Pour les variations, on reproduit le comportement du fichier Excel officiel :
#   une cellule vide peut être traitée comme 0.
# Exemple : Kharroub le 04/08, si J est vide et J-1 = 83.85,
# variation cote = 0 - 83.85 = -8385 cm.

def _abhl_v20_codes(raw: dict) -> list[str]:
    try:
        return _abhl_sq_codes(raw)
    except Exception:
        return list(TARGET_BARRAGES_ORDER)


def _abhl_v20_official_codes(raw: dict) -> list[str]:
    try:
        return _abhl_sq_official_codes(raw)
    except Exception:
        return list(TARGET_BARRAGES_ORDER)


def _abhl_v20_dynamic_codes(raw: dict) -> list[str]:
    try:
        return _abhl_sq_dynamic_codes(raw)
    except Exception:
        return [
            code for code in _abhl_v20_codes(raw)
            if code not in set(TARGET_BARRAGES_ORDER)
        ]


def _abhl_v20_zero_excel(value):
    return 0.0 if value is None else float(value)


def diff(a, b):
    # Comportement Excel pour les variations : cellule vide = 0.
    return _abhl_v20_zero_excel(a) - _abhl_v20_zero_excel(b)


def cote_variation_cm(cote_jour, cote_veille):
    # Comportement Excel pour les variations de cote : cellule vide = 0.
    return (_abhl_v20_zero_excel(cote_jour) - _abhl_v20_zero_excel(cote_veille)) * 100


def rate(volume, volume_normal):
    # Pour les taux, si le volume du jour est vide mais la capacité existe,
    # le fichier officiel affiche généralement 0.
    if volume_normal in (None, 0):
        return None

    if volume is None:
        return 0.0

    result = float(volume) / float(volume_normal) * 100

    if result > 100:
        return 100.0

    return result


def check_situation_data(raw: dict, date_situation: date) -> dict:
    date_veille = date_situation - timedelta(days=1)
    date_annee_precedente = add_months(date_situation, -12)

    missing_barrages = []
    missing_bilans = []
    missing_required_values = []

    official_codes = set(_abhl_v20_official_codes(raw))

    for code in _abhl_v20_codes(raw):
        if code not in raw.get("barrages", {}):
            missing_barrages.append(code)
            continue

        required_dates = [
            ("date_situation", date_situation),
            ("date_veille", date_veille),
        ]

        if code in official_codes:
            required_dates.append(("date_annee_precedente", date_annee_precedente))

        for label, d in required_dates:
            bilan = get_bilan(raw, code, d)

            if not bilan:
                missing_bilans.append(
                    {
                        "barrage_code": code,
                        "date_type": label,
                        "date": d.isoformat(),
                    }
                )
                continue

            for field in ["cote_7h_ngm", "volume_mm3"]:
                if bilan.get(field) is None:
                    missing_required_values.append(
                        {
                            "barrage_code": code,
                            "date_type": label,
                            "date": d.isoformat(),
                            "field": field,
                        }
                    )

    strict_can_generate = (
        len(missing_barrages) == 0
        and len(missing_bilans) == 0
        and len(missing_required_values) == 0
    )

    # Mode officiel/agence :
    # on bloque seulement si un barrage configuré n'existe pas du tout.
    # Les bilans/jours manquants ne doivent pas bloquer l'export.
    can_generate = len(missing_barrages) == 0

    return {
        "date_situation": date_situation.isoformat(),
        "date_veille": date_veille.isoformat(),
        "date_annee_precedente": date_annee_precedente.isoformat(),
        "can_generate": can_generate,
        "strict_can_generate": strict_can_generate,
        "partial_generation": not strict_can_generate,
        "generation_mode": "partial_allowed_like_official_excel",
        "warning": (
            "Situation générée avec données manquantes. "
            "Les valeurs absentes sont traitées comme dans le fichier officiel."
            if not strict_can_generate else None
        ),
        "missing_barrages": missing_barrages,
        "missing_bilans": missing_bilans,
        "missing_required_values": missing_required_values,
        "dynamic_barrages": _abhl_v20_dynamic_codes(raw),
    }
# === ABHL V20 PARTIAL SITUATION + EXCEL MISSING VALUES END ===

# === ABHL SITUATION FINAL CALCULATIONS V20 START ===
# Dernière surcharge métier :
# - génération partielle autorisée comme le fichier Excel officiel
# - valeurs manquantes du jour J/J-1 traitées comme 0 pour les barrages officiels
# - Kharroub sans donnée au 04/08 => variation = 0 - valeur du 03/08
# - totaux avec capacités précises officielles
# - libellés de bathymétrie exacts

def _abhl_v20_num_or_zero_for_official(raw: dict, code: str, bilan: dict, field: str):
    official_codes = set(_abhl_sq_official_codes(raw))
    if code in official_codes:
        return zero(bilan.get(field))
    return num(bilan.get(field))


def _abhl_v20_n1_value(raw: dict, code: str, bilan: dict, field: str):
    official_codes = set(_abhl_sq_official_codes(raw))
    if code in official_codes:
        return zero(bilan.get(field))
    return num(bilan.get(field))


def _abhl_sq_bathy_label(raw: dict, code: str) -> str:
    rows_info = SITUATION_ROWS.get(code) or {}
    if rows_info.get("bathy_year") is not None:
        return f"    ( {rows_info['bathy_year']} )"
    if code in SITUATION_ROWS:
        return "    ( 2023 )"
    return "    ( plateforme )"


def check_situation_data(raw: dict, date_situation: date) -> dict:
    date_veille = date_situation - timedelta(days=1)
    date_annee_precedente = add_months(date_situation, -12)

    missing_barrages = []
    missing_bilans = []
    missing_required_values = []
    official_codes = set(_abhl_sq_official_codes(raw))

    for code in _abhl_sq_codes(raw):
        if code not in raw.get("barrages", {}):
            missing_barrages.append(code)
            continue

        required_dates = [("date_situation", date_situation), ("date_veille", date_veille)]
        if code in official_codes:
            required_dates.append(("date_annee_precedente", date_annee_precedente))

        for label, d in required_dates:
            bilan = get_bilan(raw, code, d)
            if not bilan:
                missing_bilans.append({"barrage_code": code, "date_type": label, "date": d.isoformat()})
                continue
            for field in ["cote_7h_ngm", "volume_mm3"]:
                if bilan.get(field) is None:
                    missing_required_values.append({"barrage_code": code, "date_type": label, "date": d.isoformat(), "field": field})

    strict_can_generate = len(missing_barrages) == 0 and len(missing_bilans) == 0 and len(missing_required_values) == 0
    can_generate = len(missing_barrages) == 0

    return {
        "date_situation": date_situation.isoformat(),
        "date_veille": date_veille.isoformat(),
        "date_annee_precedente": date_annee_precedente.isoformat(),
        "can_generate": can_generate,
        "strict_can_generate": strict_can_generate,
        "partial_generation": not strict_can_generate,
        "generation_mode": "official_excel_like_missing_values_as_zero",
        "warning": "Situation générée en mode officiel avec données manquantes remplacées par 0." if not strict_can_generate else None,
        "missing_barrages": missing_barrages,
        "missing_bilans": missing_bilans,
        "missing_required_values": missing_required_values,
        "dynamic_barrages": _abhl_sq_dynamic_codes(raw),
    }


def build_situation_data(raw: dict, date_situation: date) -> dict:
    date_veille = date_situation - timedelta(days=1)
    date_annee_precedente = add_months(date_situation, -12)
    check = check_situation_data(raw, date_situation)

    normal_rows = {}
    transfer_rows = {}
    normal_totals = {"B": 0.0, "C": 0.0, "D": 0.0, "F": 0.0, "G": 0.0, "H": 0.0, "I": 0.0, "J": 0.0, "K": 0.0, "O": 0.0, "T": 0.0}
    transfer_totals = {"B": 0.0, "C": 0.0, "D": 0.0, "F": 0.0, "G": 0.0, "H": 0.0, "I": 0.0, "J": 0.0, "K": 0.0, "L": 0.0, "P": 0.0}
    dynamic_current_total = 0.0
    dynamic_old_total_with_history = 0.0
    codes = _abhl_sq_codes(raw)

    for index, code in enumerate(codes, start=1):
        bilan_jour = get_bilan(raw, code, date_situation) or {}
        bilan_veille = get_bilan(raw, code, date_veille) or {}
        bilan_annee_precedente = get_bilan(raw, code, date_annee_precedente) or {}

        cote_normale = _abhl_sq_current_cote_normale(raw, code)
        volume_normal_current = _abhl_sq_current_normal_volume(raw, code)
        volume_normal_old = _abhl_sq_old_normal_volume(raw, code)

        cote_veille = _abhl_v20_num_or_zero_for_official(raw, code, bilan_veille, "cote_7h_ngm")
        cote_jour = _abhl_v20_num_or_zero_for_official(raw, code, bilan_jour, "cote_7h_ngm")
        volume_veille = _abhl_v20_num_or_zero_for_official(raw, code, bilan_veille, "volume_mm3")
        volume_jour = _abhl_v20_num_or_zero_for_official(raw, code, bilan_jour, "volume_mm3")
        volume_annee_precedente = _abhl_v20_n1_value(raw, code, bilan_annee_precedente, "volume_mm3")

        if _abhl_sq_is_dynamic(raw, code):
            dynamic_current_total += zero(volume_normal_current)
            if volume_annee_precedente is not None:
                dynamic_old_total_with_history += zero(volume_normal_old)

        pluie_interval = zero(bilan_veille.get("pluie_mm"))
        l_normal = build_lachers_normal(raw, code, date_veille)
        l_transfer = build_lachers_transfer(raw, code, date_veille)

        previous_reference_normal = volume_normal_current if date_annee_precedente > DATE_CHANGEMENT_TAUX else volume_normal_old
        normal_current_rate = rate(volume_jour, volume_normal_current)
        normal_previous_rate = rate(volume_annee_precedente, previous_reference_normal)
        transfer_current_rate = rate(volume_jour, volume_normal_old)
        transfer_previous_rate = rate(volume_annee_precedente, volume_normal_old)
        label = _abhl_sq_label(raw, code, index)

        normal_row = {
            "barrage_code": code,
            "label": label,
            "bathy_label": _abhl_sq_bathy_label(raw, code),
            "cote_row": None,
            "volume_row": None,
            "cote_normale": cote_normale,
            "volume_normal_current": volume_normal_current,
            "volume_normal_old": volume_normal_old,
            "cote_veille": cote_veille,
            "cote_jour": cote_jour,
            "variation_cote_cm": cote_variation_cm(cote_jour, cote_veille),
            "volume_veille": volume_veille,
            "volume_jour": volume_jour,
            "variation_volume": diff(volume_jour, volume_veille),
            "volume_annee_precedente": volume_annee_precedente,
            "taux_remplissage": normal_current_rate,
            "taux_annee_precedente": normal_previous_rate,
            "pluie_mm": pluie_interval,
            "lachers": l_normal,
            "group_code": _abhl_sq_group_code_for_barrage_raw(raw, code),
            "is_dynamic": _abhl_sq_is_dynamic(raw, code),
        }

        transfer_row = {**normal_row, "taux_remplissage": transfer_current_rate, "taux_annee_precedente": transfer_previous_rate, "lachers": l_transfer}
        normal_rows[code] = normal_row
        transfer_rows[code] = transfer_row

        normal_totals["C"] += zero(volume_veille)
        normal_totals["D"] += zero(volume_jour)
        normal_totals["O"] += zero(volume_annee_precedente)
        for col in ["F", "G", "H", "I", "J", "K"]:
            normal_totals[col] += zero(l_normal.get(col))

        transfer_totals["C"] += zero(volume_veille)
        transfer_totals["D"] += zero(volume_jour)
        transfer_totals["P"] += zero(volume_annee_precedente)
        for col in ["F", "G", "H", "I", "J", "K", "L"]:
            transfer_totals[col] += zero(l_transfer.get(col))

    normal_totals["B"] = OFFICIAL_TOTALS["volume_normal_current"] + dynamic_current_total
    normal_totals["T"] = OFFICIAL_TOTALS["volume_normal_old"] + dynamic_old_total_with_history
    transfer_totals["B"] = OFFICIAL_TOTALS["volume_normal_old"] + dynamic_old_total_with_history

    normal_previous_reference_total = normal_totals["B"] if date_annee_precedente > DATE_CHANGEMENT_TAUX else normal_totals["T"]
    normal_totals["E"] = normal_totals["D"] - normal_totals["C"]
    normal_totals["M"] = normal_totals["D"]
    normal_totals["N"] = rate(normal_totals["D"], normal_totals["B"])
    normal_totals["P"] = rate(normal_totals["O"], normal_previous_reference_total)
    normal_totals["U"] = normal_totals["D"]
    normal_totals["V"] = normal_totals["O"]

    transfer_totals["E"] = transfer_totals["D"] - transfer_totals["C"]
    transfer_totals["N"] = transfer_totals["D"]
    transfer_totals["O"] = rate(transfer_totals["D"], transfer_totals["B"])
    transfer_totals["Q"] = rate(transfer_totals["P"], transfer_totals["B"])

    return {
        "dates": {"date_situation": date_situation, "date_veille": date_veille, "date_annee_precedente": date_annee_precedente},
        "check": check,
        "situation_codes": codes,
        "official_codes": _abhl_sq_official_codes(raw),
        "dynamic_codes": _abhl_sq_dynamic_codes(raw),
        "barrages": raw.get("barrages", {}),
        "normal_rows": normal_rows,
        "normal_totals": normal_totals,
        "transfer_rows": transfer_rows,
        "transfer_totals": transfer_totals,
        "specials": {
            "garde_loukkos_amont": get_special(raw, "BOEM", date_situation, "BGE_GARDE_AM"),
            "garde_loukkos_aval": get_special(raw, "BOEM", date_situation, "BGE_GARDE_AV"),
            "garde_loukkos_pluie": get_special(raw, "BOEM", date_situation, "BGE_GARDE_PLUIE"),
        },
    }

# === ABHL SITUATION FINAL CALCULATIONS V20 END ===
# === ABHL V21 TRANSFER BATHYMETRY START ===
# La feuille "Situation Détaillée (T)" n'affiche pas les mêmes années de
# bathymétrie que "Situation Détaillée". On conserve donc deux métadonnées
# distinctes, sans modifier les calculs hydrauliques ni la base PostgreSQL.

if "_abhl_v21_original_build_situation_data" not in globals():
    _abhl_v21_original_build_situation_data = build_situation_data


def build_situation_data(raw: dict, date_situation: date) -> dict:
    data = _abhl_v21_original_build_situation_data(raw, date_situation)

    for code, row in (data.get("transfer_rows") or {}).items():
        meta = SITUATION_ROWS.get(code) or {}
        year = meta.get("transfer_bathy_year")
        if year is not None:
            row["bathy_label"] = f"    ( {year} )"

    # Défense supplémentaire pour les 13 barrages officiels : le classeur agence
    # traite les SUMIF sans résultat comme 0 dans les calculs du jour J/J-1.
    official_codes = set(data.get("official_codes") or [])
    zero_keys = ("cote_veille", "cote_jour", "volume_veille", "volume_jour")
    for section in ("normal_rows", "transfer_rows"):
        for code, row in (data.get(section) or {}).items():
            if code not in official_codes:
                continue
            for key in zero_keys:
                if row.get(key) is None:
                    row[key] = 0.0

    return data
# === ABHL V21 TRANSFER BATHYMETRY END ===
