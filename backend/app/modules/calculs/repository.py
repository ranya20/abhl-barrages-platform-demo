from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any


from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.calculs.constants import BARRAGE_CALCUL_CONSTANTS

def to_float(value: Any):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def date_key(value: Any) -> str:
    if hasattr(value, "date"):
        value = value.date()
    return value.isoformat()


def read_table_columns(db: Session, table_name: str) -> list[str]:
    rows = db.execute(
        text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table_name
            ORDER BY ordinal_position;
        """),
        {"table_name": table_name},
    ).mappings().all()

    return [row["column_name"] for row in rows]


def table_exists(db: Session, table_name: str) -> bool:
    value = db.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = :table_name
            );
        """),
        {"table_name": table_name},
    ).scalar()

    return bool(value)


def fetch_active_barrages(db: Session) -> dict[str, dict]:
    rows = db.execute(
        text("""
            SELECT
                id,
                code,
                nom,
                nom_court,
                capacite_normale_mm3,
                cote_normale_ngm,
                ordre_affichage,
                actif,
                COALESCE(inclure_calculs, TRUE) AS inclure_calculs,
                COALESCE(inclure_annonce, TRUE) AS inclure_annonce,
                COALESCE(inclure_bilan, TRUE) AS inclure_bilan,
                COALESCE(inclure_situation, TRUE) AS inclure_situation,
                ordre_annonce,
                ordre_bilan,
                ordre_situation
            FROM public.barrages
            WHERE COALESCE(actif, TRUE) = TRUE
              AND COALESCE(inclure_calculs, TRUE) = TRUE
            ORDER BY ordre_affichage NULLS LAST, id;
        """)
    ).mappings().all()

    data = {}
    for row in rows:
        item = dict(row)
        item["capacite_normale_mm3"] = to_float(item.get("capacite_normale_mm3"))
        item["cote_normale_ngm"] = to_float(item.get("cote_normale_ngm"))

        code = item["code"]
        constants = BARRAGE_CALCUL_CONSTANTS.get(code, {})

        if item["capacite_normale_mm3"] is None:
            item["capacite_normale_mm3"] = constants.get("capacite_normale_mm3")

        if item["cote_normale_ngm"] is None:
            item["cote_normale_ngm"] = constants.get("cote_normale_ngm")

        data[code] = item

    return data


def fetch_restitution_types_by_barrage(db: Session) -> dict[str, list[dict]]:
    rows = db.execute(
        text("""
            SELECT
                b.code AS barrage_code,
                tr.id AS type_id,
                tr.code AS type_code,
                tr.libelle,
                tr.unite,
                btr.ordre_affichage,
                btr.obligatoire,
                btr.libelle_affichage
            FROM public.barrage_types_restitution btr
            JOIN public.barrages b
                ON b.id = btr.barrage_id
            JOIN public.types_restitution tr
                ON tr.id = btr.type_restitution_id
            WHERE COALESCE(b.actif, TRUE) = TRUE
              AND COALESCE(btr.actif, TRUE) = TRUE
              AND COALESCE(tr.actif, TRUE) = TRUE
            ORDER BY b.ordre_affichage NULLS LAST, b.id, btr.ordre_affichage, tr.id;
        """)
    ).mappings().all()

    data: dict[str, list[dict]] = {}

    for row in rows:
        item = dict(row)
        item["obligatoire"] = bool(item.get("obligatoire"))
        data.setdefault(item["barrage_code"], []).append(item)

    return data


def fetch_all_restitution_types(db: Session) -> dict[str, dict]:
    rows = db.execute(
        text("""
            SELECT
                id AS type_id,
                code AS type_code,
                libelle,
                unite
            FROM public.types_restitution
            WHERE COALESCE(actif, TRUE) = TRUE
            ORDER BY id;
        """)
    ).mappings().all()

    data = {}

    for row in rows:
        item = dict(row)
        data[item["type_code"]] = item

    return data


def fetch_bilans_by_dates(
    db: Session,
    dates: list[date],
    barrage_codes: list[str],
) -> dict[tuple[str, str], dict]:
    if not dates or not barrage_codes:
        return {}

    rows = db.execute(
        text("""
            SELECT
                bj.*,
                b.code AS barrage_code
            FROM public.bilans_journaliers bj
            JOIN public.barrages b
                ON b.id = bj.barrage_id
            WHERE bj.date_bilan = ANY(:dates)
              AND b.code = ANY(:codes)
            ORDER BY bj.date_bilan, b.ordre_affichage;
        """),
        {"dates": dates, "codes": barrage_codes},
    ).mappings().all()

    data = {}

    for row in rows:
        item = dict(row)
        key = (item["barrage_code"], date_key(item["date_bilan"]))

        for k, v in list(item.items()):
            if isinstance(v, Decimal):
                item[k] = float(v)

        data[key] = item

    return data


def fetch_restitutions_for_bilan_ids(
    db: Session,
    bilan_ids: list[int],
) -> dict[int, dict[str, float]]:
    if not bilan_ids:
        return {}

    rows = db.execute(
        text("""
            SELECT
                rj.bilan_journalier_id,
                tr.code AS type_code,
                rj.valeur_m3
            FROM public.restitutions_journalieres rj
            JOIN public.types_restitution tr
                ON tr.id = rj.type_restitution_id
            WHERE rj.bilan_journalier_id = ANY(:bilan_ids);
        """),
        {"bilan_ids": bilan_ids},
    ).mappings().all()

    data: dict[int, dict[str, float]] = {}

    for row in rows:
        bilan_id = int(row["bilan_journalier_id"])
        data.setdefault(bilan_id, {})[row["type_code"]] = to_float(row["valeur_m3"]) or 0.0

    return data


def lookup_bareme_exact(
    db: Session,
    barrage_id: int,
    cote_ngm: float | None,
) -> dict | None:
    if cote_ngm is None:
        return None

    row = db.execute(
        text("""
            WITH last_version AS (
                SELECT id
                FROM public.bareme_versions
                WHERE barrage_id = :barrage_id
                  AND actif = TRUE
                ORDER BY is_default DESC, id DESC
                LIMIT 1
            )
            SELECT
                bp.cote_ngm,
                bp.volume_mm3,
                bp.surface_km2
            FROM public.bareme_points bp
            JOIN last_version lv
                ON lv.id = bp.bareme_version_id
            WHERE ABS(bp.cote_ngm - :cote_ngm) <= 0.000001
            ORDER BY bp.cote_ngm
            LIMIT 1;
        """),
        {
            "barrage_id": barrage_id,
            "cote_ngm": cote_ngm,
        },
    ).mappings().first()

    if not row:
        return None

    item = dict(row)
    item["cote_ngm"] = to_float(item.get("cote_ngm"))
    item["volume_mm3"] = to_float(item.get("volume_mm3"))
    item["surface_km2"] = to_float(item.get("surface_km2"))

    return item


def fetch_special_value(
    db: Session,
    barrage_code: str,
    date_bilan: date,
    mesure_code: str,
) -> float:
    if not table_exists(db, "djbarrage_mesures_speciales"):
        return 0.0

    row = db.execute(
        text("""
            SELECT COALESCE(SUM(dms.valeur), 0) AS valeur
            FROM public.djbarrage_mesures_speciales dms
            JOIN public.bilans_journaliers bj
                ON bj.id = dms.bilan_journalier_id
            JOIN public.barrages b
                ON b.id = bj.barrage_id
            WHERE b.code = :barrage_code
              AND bj.date_bilan = :date_bilan
              AND dms.mesure_code = :mesure_code;
        """),
        {
            "barrage_code": barrage_code,
            "date_bilan": date_bilan,
            "mesure_code": mesure_code,
        },
    ).mappings().first()

    return float(row["valeur"] or 0.0)


def fetch_boem_transfert_from_db(db: Session, date_bilan: date) -> float:
    row = db.execute(
        text("""
            SELECT COALESCE(SUM(rj.valeur_m3), 0) AS valeur
            FROM public.restitutions_journalieres rj
            JOIN public.bilans_journaliers bj
                ON bj.id = rj.bilan_journalier_id
            JOIN public.barrages b
                ON b.id = bj.barrage_id
            JOIN public.types_restitution tr
                ON tr.id = rj.type_restitution_id
            WHERE b.code = 'BOEM'
              AND bj.date_bilan = :date_bilan
              AND tr.code = 'TRANSFERT';
        """),
        {"date_bilan": date_bilan},
    ).mappings().first()

    return float(row["valeur"] or 0.0)


def ensure_journee_situation(db: Session, date_situation: date) -> int:
    row = db.execute(
        text("""
            SELECT id
            FROM public.journees_situation
            WHERE date_situation = :date_situation
              AND heure_reference = '07:00'
            LIMIT 1;
        """),
        {"date_situation": date_situation},
    ).mappings().first()

    if row:
        return int(row["id"])

    row = db.execute(
        text("""
            INSERT INTO public.journees_situation (
                date_situation,
                heure_reference,
                statut_global
            )
            VALUES (
                :date_situation,
                '07:00',
                'PRETE'
            )
            RETURNING id;
        """),
        {"date_situation": date_situation},
    ).mappings().first()

    return int(row["id"])


def upsert_bilan(
    db: Session,
    barrage_id: int,
    date_bilan: date,
    values: dict,
) -> int:
    columns = read_table_columns(db, "bilans_journaliers")

    allowed = {
        key: value
        for key, value in values.items()
        if key in columns and key != "id"
    }

    existing = db.execute(
        text("""
            SELECT id
            FROM public.bilans_journaliers
            WHERE barrage_id = :barrage_id
              AND date_bilan = :date_bilan
              AND heure_reference = '07:00'
            LIMIT 1;
        """),
        {
            "barrage_id": barrage_id,
            "date_bilan": date_bilan,
        },
    ).mappings().first()

    if existing:
        bilan_id = int(existing["id"])

        update_keys = [
            key
            for key in allowed.keys()
            if key not in {"barrage_id", "date_bilan", "heure_reference"}
        ]

        if update_keys:
            set_sql = ", ".join([f"{key} = :{key}" for key in update_keys])
            params = {key: allowed[key] for key in update_keys}
            params["id"] = bilan_id

            db.execute(
                text(f"""
                    UPDATE public.bilans_journaliers
                    SET {set_sql}
                    WHERE id = :id;
                """),
                params,
            )

        return bilan_id

    insert_data = {
        "barrage_id": barrage_id,
        "date_bilan": date_bilan,
        "heure_reference": "07:00",
    }
    insert_data.update(allowed)

    insert_data = {
        key: value
        for key, value in insert_data.items()
        if key in columns
    }

    col_sql = ", ".join(insert_data.keys())
    val_sql = ", ".join([f":{key}" for key in insert_data.keys()])

    row = db.execute(
        text(f"""
            INSERT INTO public.bilans_journaliers ({col_sql})
            VALUES ({val_sql})
            RETURNING id;
        """),
        insert_data,
    ).mappings().first()

    return int(row["id"])


def get_type_restitution_id(db: Session, type_code: str) -> int | None:
    row = db.execute(
        text("""
            SELECT id
            FROM public.types_restitution
            WHERE code = :type_code
            LIMIT 1;
        """),
        {"type_code": type_code},
    ).mappings().first()

    return int(row["id"]) if row else None


def upsert_restitution(
    db: Session,
    bilan_id: int,
    type_code: str,
    valeur_m3: float,
    observation: str | None = None,
):
    type_id = get_type_restitution_id(db, type_code)

    if type_id is None:
        raise ValueError(f"Type de restitution introuvable : {type_code}")

    db.execute(
        text("""
            INSERT INTO public.restitutions_journalieres (
                bilan_journalier_id,
                type_restitution_id,
                valeur_m3,
                observation
            )
            VALUES (
                :bilan_id,
                :type_id,
                :valeur_m3,
                :observation
            )
            ON CONFLICT (bilan_journalier_id, type_restitution_id)
            DO UPDATE SET
                valeur_m3 = EXCLUDED.valeur_m3,
                observation = EXCLUDED.observation,
                updated_at = now();
        """),
        {
            "bilan_id": bilan_id,
            "type_id": type_id,
            "valeur_m3": valeur_m3,
            "observation": observation,
        },
    )


def upsert_bilan_variable(
    db: Session,
    bilan_id: int,
    code_variable: str,
    libelle_variable: str,
    valeur_numeric: float | None,
    unite: str | None = None,
    source_type: str | None = "CALCUL_BACKEND",
):
    if not table_exists(db, "bilan_variables_journalieres"):
        return

    db.execute(
        text("""
            INSERT INTO public.bilan_variables_journalieres (
                bilan_journalier_id,
                code_variable,
                libelle_variable,
                valeur_numeric,
                unite,
                source_type
            )
            VALUES (
                :bilan_id,
                :code_variable,
                :libelle_variable,
                :valeur_numeric,
                :unite,
                :source_type
            )
            ON CONFLICT (bilan_journalier_id, code_variable)
            DO UPDATE SET
                libelle_variable = EXCLUDED.libelle_variable,
                valeur_numeric = EXCLUDED.valeur_numeric,
                unite = EXCLUDED.unite,
                source_type = EXCLUDED.source_type,
                updated_at = now();
        """),
        {
            "bilan_id": bilan_id,
            "code_variable": code_variable,
            "libelle_variable": libelle_variable,
            "valeur_numeric": valeur_numeric,
            "unite": unite,
            "source_type": source_type,
        },
    )

# === ABHL BAREMES V27 DATE-AWARE LOOKUP START ===
_abhl_v27_lookup_bareme_exact_legacy = lookup_bareme_exact

def lookup_bareme_exact(db: Session, barrage_id: int, cote_ngm: float | None, date_reference=None) -> dict | None:
    if cote_ngm is None:
        return None
    from app.modules.baremes.service import BaremeResolutionError, lookup_bareme_exact_by_id
    try:
        return lookup_bareme_exact_by_id(db, barrage_id, cote_ngm, date_reference=date_reference)
    except BaremeResolutionError:
        # Pas de fallback silencieux vers un barème hors période : le calcul sera BLOQUANT.
        return None
# === ABHL BAREMES V27 DATE-AWARE LOOKUP END ===
