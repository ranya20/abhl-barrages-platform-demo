from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.modules.situation.mappings import TARGET_BARRAGES_ORDER


def to_float(value: Any):
    if value is None:
        return None

    if isinstance(value, Decimal):
        return float(value)

    return value


def date_key(value):
    if value is None:
        return None

    if hasattr(value, "date"):
        value = value.date()

    return value.isoformat()


def read_table_columns(db, table_name: str) -> list[str]:
    query = text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = :table_name
        ORDER BY ordinal_position;
    """)

    rows = db.execute(query, {"table_name": table_name}).mappings().all()
    return [row["column_name"] for row in rows]


def pick_column(columns: list[str], candidates: list[str], required: bool = True):
    for candidate in candidates:
        if candidate in columns:
            return candidate

    if required:
        raise RuntimeError(
            f"Aucune colonne trouvée parmi {candidates}. Colonnes disponibles : {columns}"
        )

    return None


def fetch_barrages(db) -> dict[str, dict]:
    query = text("""
        SELECT
            id,
            code,
            nom,
            nom_court,
            cote_normale_ngm,
            capacite_normale_mm3,
            ordre_affichage,
            actif
        FROM public.barrages
        WHERE code = ANY(:codes)
        ORDER BY ordre_affichage;
    """)

    rows = db.execute(query, {"codes": TARGET_BARRAGES_ORDER}).mappings().all()

    data = {}
    for row in rows:
        item = dict(row)
        for key in ["cote_normale_ngm", "capacite_normale_mm3"]:
            item[key] = to_float(item.get(key))
        data[item["code"]] = item

    return data


def fetch_bilans(db, dates: list[date]) -> dict[tuple[str, str], dict]:
    query = text("""
        SELECT
            b.code AS barrage_code,
            bj.date_bilan,
            bj.cote_7h_ngm,
            bj.volume_mm3,
            bj.hauteur_bac_mm,
            bj.pluie_mm,
            bj.evaporation_m3,
            bj.apports_m3,
            bj.total_restitutions_m3,
            bj.source_fichier,
            bj.source_feuille
        FROM public.bilans_journaliers bj
        JOIN public.barrages b
            ON b.id = bj.barrage_id
        WHERE b.code = ANY(:codes)
          AND bj.date_bilan = ANY(:dates)
        ORDER BY bj.date_bilan, b.ordre_affichage;
    """)

    rows = db.execute(
        query,
        {
            "codes": TARGET_BARRAGES_ORDER,
            "dates": dates,
        },
    ).mappings().all()

    data = {}

    numeric_fields = [
        "cote_7h_ngm",
        "volume_mm3",
        "hauteur_bac_mm",
        "pluie_mm",
        "evaporation_m3",
        "apports_m3",
        "total_restitutions_m3",
    ]

    for row in rows:
        item = dict(row)
        d_key = date_key(item["date_bilan"])

        for field in numeric_fields:
            item[field] = to_float(item.get(field))

        data[(item["barrage_code"], d_key)] = item

    return data


def fetch_restitutions(db, dates: list[date]) -> dict[tuple[str, str, str], float]:
    columns = read_table_columns(db, "restitutions_journalieres")
    value_col = pick_column(columns, ["volume_m3", "valeur_m3", "valeur", "quantite_m3"])

    query = text(f"""
        SELECT
            b.code AS barrage_code,
            bj.date_bilan,
            tr.code AS type_code,
            rj.{value_col} AS valeur_m3
        FROM public.restitutions_journalieres rj
        JOIN public.bilans_journaliers bj
            ON bj.id = rj.bilan_journalier_id
        JOIN public.barrages b
            ON b.id = bj.barrage_id
        JOIN public.types_restitution tr
            ON tr.id = rj.type_restitution_id
        WHERE b.code = ANY(:codes)
          AND bj.date_bilan = ANY(:dates);
    """)

    rows = db.execute(
        query,
        {
            "codes": TARGET_BARRAGES_ORDER,
            "dates": dates,
        },
    ).mappings().all()

    data = {}

    for row in rows:
        key = (
            row["barrage_code"],
            date_key(row["date_bilan"]),
            row["type_code"],
        )
        data[key] = to_float(row["valeur_m3"]) or 0.0

    return data


def fetch_specials(db, dates: list[date]) -> dict[tuple[str, str, str], float]:
    columns = read_table_columns(db, "djbarrage_mesures_speciales")

    bilan_fk_col = pick_column(columns, ["bilan_journalier_id", "bilan_id"])
    code_col = pick_column(columns, ["mesure_code", "code"])
    value_col = pick_column(columns, ["valeur_m3", "volume_m3", "valeur"])

    query = text(f"""
        SELECT
            b.code AS barrage_code,
            bj.date_bilan,
            dms.{code_col} AS mesure_code,
            dms.{value_col} AS valeur
        FROM public.djbarrage_mesures_speciales dms
        JOIN public.bilans_journaliers bj
            ON bj.id = dms.{bilan_fk_col}
        JOIN public.barrages b
            ON b.id = bj.barrage_id
        WHERE b.code = ANY(:codes)
          AND bj.date_bilan = ANY(:dates);
    """)

    rows = db.execute(
        query,
        {
            "codes": TARGET_BARRAGES_ORDER,
            "dates": dates,
        },
    ).mappings().all()

    data = {}

    for row in rows:
        key = (
            row["barrage_code"],
            date_key(row["date_bilan"]),
            row["mesure_code"],
        )
        data[key] = to_float(row["valeur"]) or 0.0

    return data


def fetch_normal_volumes_from_baremes(db) -> dict[str, float]:
    """
    Volume normal actuel depuis les barèmes :
    on cherche le point de barème le plus proche de cote_normale_ngm.
    """
    query = text("""
        SELECT
            b.code AS barrage_code,
            b.cote_normale_ngm,
            x.cote_ngm AS bareme_cote_ngm,
            x.volume_mm3 AS volume_normal_mm3,
            x.surface_km2 AS surface_km2
        FROM public.barrages b
        LEFT JOIN LATERAL (
            SELECT
                bp.cote_ngm,
                bp.volume_mm3,
                bp.surface_km2
            FROM public.bareme_versions bv
            JOIN public.bareme_points bp
                ON bp.bareme_version_id = bv.id
            WHERE bv.barrage_id = b.id
              AND bv.actif = TRUE
              AND b.cote_normale_ngm IS NOT NULL
            ORDER BY
                ABS(bp.cote_ngm - b.cote_normale_ngm) ASC,
                bv.is_default DESC,
                bv.id DESC
            LIMIT 1
        ) x ON TRUE
        WHERE b.code = ANY(:codes)
        ORDER BY b.ordre_affichage;
    """)

    rows = db.execute(query, {"codes": TARGET_BARRAGES_ORDER}).mappings().all()

    data = {}
    for row in rows:
        data[row["barrage_code"]] = to_float(row["volume_normal_mm3"])

    return data


def load_situation_raw_data(db, dates: list[date]) -> dict:
    return {
        "barrages": fetch_barrages(db),
        "bilans": fetch_bilans(db, dates),
        "restitutions": fetch_restitutions(db, dates),
        "specials": fetch_specials(db, dates),
        "normal_volumes": fetch_normal_volumes_from_baremes(db),
    }

# === ABHL SITUATION DYNAMIQUE V2 PATCH START ===
# Ce bloc rend la lecture des données Situation compatible avec les nouveaux barrages.
# Il surcharge les fonctions précédentes sans supprimer l'ancien code.

def _abhl_sq_official_order_index(code: str) -> int:
    try:
        return TARGET_BARRAGES_ORDER.index(code)
    except ValueError:
        return 9999


def fetch_situation_barrages(db) -> dict[str, dict]:
    """
    Charge les barrages à inclure dans la situation quotidienne.

    - Les barrages officiels gardent leur ordre historique.
    - Les nouveaux barrages sont ajoutés après, si inclure_situation = true.
    """
    query = text("""
        SELECT
            b.id,
            b.code,
            b.nom,
            b.nom_court,
            b.cote_normale_ngm,
            b.capacite_normale_mm3,
            b.ordre_affichage,
            b.ordre_situation,
            b.actif,
            COALESCE(b.inclure_situation, TRUE) AS inclure_situation,
            a.code AS agence_code,
            a.nom AS agence_nom
        FROM public.barrages b
        LEFT JOIN public.agences_territoriales a
            ON a.id = b.agence_id
        WHERE COALESCE(b.actif, TRUE) = TRUE
          AND COALESCE(b.inclure_situation, TRUE) = TRUE
        ORDER BY
            COALESCE(b.ordre_situation, b.ordre_affichage, b.id),
            b.id;
    """)

    rows = db.execute(query).mappings().all()

    official = []
    dynamic = []

    for row in rows:
        item = dict(row)

        for key in ["cote_normale_ngm", "capacite_normale_mm3"]:
            item[key] = to_float(item.get(key))

        if item["code"] in TARGET_BARRAGES_ORDER:
            official.append(item)
        else:
            dynamic.append(item)

    official.sort(key=lambda item: _abhl_sq_official_order_index(item["code"]))
    dynamic.sort(key=lambda item: (item.get("ordre_situation") or item.get("ordre_affichage") or 9999, item["code"]))

    data = {}
    for item in official + dynamic:
        data[item["code"]] = item

    return data


def fetch_situation_codes(db) -> dict:
    barrages = fetch_situation_barrages(db)
    codes = list(barrages.keys())
    official_codes = [code for code in TARGET_BARRAGES_ORDER if code in barrages]
    dynamic_codes = [code for code in codes if code not in TARGET_BARRAGES_ORDER]

    return {
        "barrages": barrages,
        "codes": codes,
        "official_codes": official_codes,
        "dynamic_codes": dynamic_codes,
    }


def fetch_bilans_for_codes(db, codes: list[str], dates: list[date]) -> dict[tuple[str, str], dict]:
    if not codes:
        return {}

    query = text("""
        SELECT
            b.code AS barrage_code,
            bj.date_bilan,
            bj.cote_7h_ngm,
            bj.volume_mm3,
            bj.surface_km2,
            bj.hauteur_bac_mm,
            bj.pluie_mm,
            bj.evaporation_m3,
            bj.apports_m3,
            bj.total_restitutions_m3,
            bj.taux_remplissage,
            bj.source_fichier,
            bj.source_feuille
        FROM public.bilans_journaliers bj
        JOIN public.barrages b
            ON b.id = bj.barrage_id
        WHERE b.code = ANY(:codes)
          AND bj.date_bilan = ANY(:dates)
        ORDER BY bj.date_bilan, b.ordre_affichage;
    """)

    rows = db.execute(
        query,
        {
            "codes": codes,
            "dates": dates,
        },
    ).mappings().all()

    data = {}

    numeric_fields = [
        "cote_7h_ngm",
        "volume_mm3",
        "surface_km2",
        "hauteur_bac_mm",
        "pluie_mm",
        "evaporation_m3",
        "apports_m3",
        "total_restitutions_m3",
        "taux_remplissage",
    ]

    for row in rows:
        item = dict(row)
        d_key = date_key(item["date_bilan"])

        for field in numeric_fields:
            item[field] = to_float(item.get(field))

        data[(item["barrage_code"], d_key)] = item

    return data


def fetch_restitutions_for_codes(db, codes: list[str], dates: list[date]) -> dict[tuple[str, str, str], float]:
    if not codes:
        return {}

    columns = read_table_columns(db, "restitutions_journalieres")
    value_col = pick_column(columns, ["volume_m3", "valeur_m3", "valeur", "quantite_m3"])

    query = text(f"""
        SELECT
            b.code AS barrage_code,
            bj.date_bilan,
            tr.code AS type_code,
            rj.{value_col} AS valeur_m3
        FROM public.restitutions_journalieres rj
        JOIN public.bilans_journaliers bj
            ON bj.id = rj.bilan_journalier_id
        JOIN public.barrages b
            ON b.id = bj.barrage_id
        JOIN public.types_restitution tr
            ON tr.id = rj.type_restitution_id
        WHERE b.code = ANY(:codes)
          AND bj.date_bilan = ANY(:dates);
    """)

    rows = db.execute(
        query,
        {
            "codes": codes,
            "dates": dates,
        },
    ).mappings().all()

    data = {}

    for row in rows:
        key = (
            row["barrage_code"],
            date_key(row["date_bilan"]),
            row["type_code"],
        )
        data[key] = to_float(row["valeur_m3"]) or 0.0

    return data


def fetch_specials_for_codes(db, codes: list[str], dates: list[date]) -> dict[tuple[str, str, str], float]:
    if not codes:
        return {}

    columns = read_table_columns(db, "djbarrage_mesures_speciales")

    bilan_fk_col = pick_column(columns, ["bilan_journalier_id", "bilan_id"])
    code_col = pick_column(columns, ["mesure_code", "code"])
    value_col = pick_column(columns, ["valeur_m3", "volume_m3", "valeur"])

    query = text(f"""
        SELECT
            b.code AS barrage_code,
            bj.date_bilan,
            dms.{code_col} AS mesure_code,
            dms.{value_col} AS valeur
        FROM public.djbarrage_mesures_speciales dms
        JOIN public.bilans_journaliers bj
            ON bj.id = dms.{bilan_fk_col}
        JOIN public.barrages b
            ON b.id = bj.barrage_id
        WHERE b.code = ANY(:codes)
          AND bj.date_bilan = ANY(:dates);
    """)

    rows = db.execute(
        query,
        {
            "codes": codes,
            "dates": dates,
        },
    ).mappings().all()

    data = {}

    for row in rows:
        key = (
            row["barrage_code"],
            date_key(row["date_bilan"]),
            row["mesure_code"],
        )
        data[key] = to_float(row["valeur"]) or 0.0

    return data


def fetch_normal_volumes_from_baremes_for_codes(db, codes: list[str]) -> dict[str, float]:
    if not codes:
        return {}

    query = text("""
        SELECT
            b.code AS barrage_code,
            b.cote_normale_ngm,
            x.cote_ngm AS bareme_cote_ngm,
            x.volume_mm3 AS volume_normal_mm3,
            x.surface_km2 AS surface_km2
        FROM public.barrages b
        LEFT JOIN LATERAL (
            SELECT
                bp.cote_ngm,
                bp.volume_mm3,
                bp.surface_km2
            FROM public.bareme_versions bv
            JOIN public.bareme_points bp
                ON bp.bareme_version_id = bv.id
            WHERE bv.barrage_id = b.id
              AND COALESCE(bv.actif, TRUE) = TRUE
              AND b.cote_normale_ngm IS NOT NULL
            ORDER BY
                ABS(bp.cote_ngm - b.cote_normale_ngm) ASC,
                COALESCE(bv.is_default, FALSE) DESC,
                bv.id DESC
            LIMIT 1
        ) x ON TRUE
        WHERE b.code = ANY(:codes)
        ORDER BY b.ordre_affichage;
    """)

    rows = db.execute(query, {"codes": codes}).mappings().all()

    data = {}
    for row in rows:
        data[row["barrage_code"]] = to_float(row["volume_normal_mm3"])

    return data


def fetch_barrage_restitution_types_for_codes(db, codes: list[str]) -> dict[str, list[dict]]:
    if not codes:
        return {}

    query = text("""
        SELECT
            b.code AS barrage_code,
            tr.code AS type_code,
            tr.libelle,
            tr.unite,
            COALESCE(btr.ordre_affichage, tr.id) AS ordre_affichage
        FROM public.barrage_types_restitution btr
        JOIN public.barrages b
            ON b.id = btr.barrage_id
        JOIN public.types_restitution tr
            ON tr.id = btr.type_restitution_id
        WHERE b.code = ANY(:codes)
          AND COALESCE(btr.actif, TRUE) = TRUE
          AND COALESCE(tr.actif, TRUE) = TRUE
        ORDER BY b.code, COALESCE(btr.ordre_affichage, tr.id), tr.code;
    """)

    rows = db.execute(query, {"codes": codes}).mappings().all()

    data = {code: [] for code in codes}

    for row in rows:
        data.setdefault(row["barrage_code"], []).append(
            {
                "type_code": row["type_code"],
                "libelle": row["libelle"],
                "unite": row["unite"],
                "ordre_affichage": row["ordre_affichage"],
            }
        )

    return data


def load_situation_raw_data(db, dates: list[date]) -> dict:
    meta = fetch_situation_codes(db)
    codes = meta["codes"]

    return {
        "barrages": meta["barrages"],
        "situation_codes": codes,
        "official_codes": meta["official_codes"],
        "dynamic_codes": meta["dynamic_codes"],
        "bilans": fetch_bilans_for_codes(db, codes, dates),
        "restitutions": fetch_restitutions_for_codes(db, codes, dates),
        "specials": fetch_specials_for_codes(db, meta["official_codes"], dates),
        "normal_volumes": fetch_normal_volumes_from_baremes_for_codes(db, codes),
        "barrage_restitution_types": fetch_barrage_restitution_types_for_codes(db, codes),
    }

# === ABHL SITUATION DYNAMIQUE V2 PATCH END ===

# === ABHL SITUATION DYNAMIC FIX CAPACITY V1 START ===
# Correction : pour les nouveaux barrages, le volume normal doit utiliser
# b.capacite_normale_mm3 si elle existe. Le barème sert seulement de fallback.

def fetch_normal_volumes_from_baremes_for_codes(db, codes: list[str]) -> dict[str, float]:
    if not codes:
        return {}

    query = text("""
        SELECT
            b.code AS barrage_code,
            b.capacite_normale_mm3,
            b.cote_normale_ngm,
            x.cote_ngm AS bareme_cote_ngm,
            x.volume_mm3 AS bareme_volume_normal_mm3
        FROM public.barrages b
        LEFT JOIN LATERAL (
            SELECT
                bp.cote_ngm,
                bp.volume_mm3
            FROM public.bareme_versions bv
            JOIN public.bareme_points bp
                ON bp.bareme_version_id = bv.id
            WHERE bv.barrage_id = b.id
              AND COALESCE(bv.actif, TRUE) = TRUE
              AND b.cote_normale_ngm IS NOT NULL
            ORDER BY
                COALESCE(bv.is_default, FALSE) DESC,
                ABS(bp.cote_ngm - b.cote_normale_ngm) ASC,
                bv.id DESC
            LIMIT 1
        ) x ON TRUE
        WHERE b.code = ANY(:codes)
        ORDER BY b.ordre_affichage;
    """)

    rows = db.execute(query, {"codes": codes}).mappings().all()

    data = {}

    for row in rows:
        capacity = to_float(row.get("capacite_normale_mm3"))
        bareme_volume = to_float(row.get("bareme_volume_normal_mm3"))

        # Priorité au champ métier "Capacité normale Mm³".
        # Le barème est seulement une solution de secours.
        data[row["barrage_code"]] = capacity if capacity is not None else bareme_volume

    return data

# === ABHL SITUATION DYNAMIC FIX CAPACITY V1 END ===

# === ABHL BAREMES V27 SITUATION NORMAL CAPACITY START ===
_abhl_v27_load_situation_raw_data_legacy = load_situation_raw_data

def load_situation_raw_data(db, dates: list[date]) -> dict:
    raw = _abhl_v27_load_situation_raw_data_legacy(db, dates)
    if not dates:
        return raw
    from app.modules.baremes.service import resolve_bareme_versions_for_dates
    reference_date = max(dates)
    codes = list(raw.get("situation_codes") or [])
    resolutions = resolve_bareme_versions_for_dates(db, codes, [reference_date], strict=False)
    for code in codes:
        version = resolutions.get((code, reference_date.isoformat()))
        if version and version.get("calculation_source") == "DATABASE_VERSIONED":
            normal = version.get("effective_volume_normal_mm3")
            if normal is not None:
                raw.setdefault("normal_volumes", {})[code] = float(normal)
    return raw
# === ABHL BAREMES V27 SITUATION NORMAL CAPACITY END ===
