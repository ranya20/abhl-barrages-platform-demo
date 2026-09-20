from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.baremes.excel_io import validate_points


STATUS_DRAFT = "BROUILLON"
STATUS_PUBLISHED = "PUBLIE"
STATUS_ARCHIVED = "ARCHIVE"

SOURCE_LEGACY_TEMPLATE = "LEGACY_TEMPLATE"
SOURCE_DATABASE_VERSIONED = "DATABASE_VERSIONED"


class BaremeResolutionError(ValueError):
    pass


def _float(value):
    if value is None:
        return None
    return float(value)


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _row(row) -> dict | None:
    if not row:
        return None
    item = dict(row)
    for key in (
        "cote_normale_ngm",
        "volume_normal_mm3",
        "surface_normale_km2",
        "cote_ngm",
        "volume_mm3",
        "surface_km2",
    ):
        if key in item:
            item[key] = _float(item.get(key))
    for key in (
        "date_debut_validite",
        "date_fin_validite",
        "created_at",
        "updated_at",
        "published_at",
        "archived_at",
    ):
        if key in item:
            item[key] = _iso(item.get(key))
    return item


def _barrage_id(db: Session, barrage_code: str) -> int:
    value = db.execute(
        text(
            """
            SELECT id
            FROM public.barrages
            WHERE UPPER(code) = UPPER(:code)
            LIMIT 1
            """
        ),
        {"code": str(barrage_code).strip()},
    ).scalar()
    if value is None:
        raise ValueError(f"Barrage introuvable : {barrage_code}")
    return int(value)


def _version_raw(db: Session, version_id: int):
    return db.execute(
        text(
            """
            SELECT
                bv.*,
                b.code AS barrage_code,
                b.nom AS barrage_nom,
                b.nom_court AS barrage_nom_court,
                COUNT(bp.id) OVER (PARTITION BY bv.id) AS points_count
            FROM public.bareme_versions bv
            JOIN public.barrages b ON b.id = bv.barrage_id
            LEFT JOIN public.bareme_points bp ON bp.bareme_version_id = bv.id
            WHERE bv.id = :version_id
            LIMIT 1
            """
        ),
        {"version_id": int(version_id)},
    ).mappings().first()


def _version_or_raise(db: Session, version_id: int) -> dict:
    row = _version_raw(db, version_id)
    if not row:
        raise ValueError(f"Version de barème introuvable : {version_id}")
    return dict(row)


def _audit(
    db: Session,
    *,
    version_id: int | None,
    barrage_id: int | None,
    action: str,
    user_id: int | None,
    details: dict | None = None,
    old_values: dict | None = None,
    new_values: dict | None = None,
):
    db.execute(
        text(
            """
            INSERT INTO public.bareme_audit_log (
                bareme_version_id,
                barrage_id,
                action,
                user_id,
                details,
                old_values,
                new_values
            )
            VALUES (
                :version_id,
                :barrage_id,
                :action,
                :user_id,
                CAST(:details AS jsonb),
                CAST(:old_values AS jsonb),
                CAST(:new_values AS jsonb)
            )
            """
        ),
        {
            "version_id": version_id,
            "barrage_id": barrage_id,
            "action": action,
            "user_id": user_id,
            "details": json.dumps(details or {}, ensure_ascii=False, default=str),
            "old_values": json.dumps(old_values or {}, ensure_ascii=False, default=str),
            "new_values": json.dumps(new_values or {}, ensure_ascii=False, default=str),
        },
    )


def _canonical_points_hash(points: list[dict]) -> str:
    canonical = "\n".join(
        f"{p['cote_ngm']}|{p['volume_mm3']}|{p['surface_km2']}"
        for p in sorted(points, key=lambda x: Decimal(str(x["cote_ngm"])))
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_points(points: Iterable[Any]) -> dict:
    normalized = []
    for index, p in enumerate(points, start=1):
        if hasattr(p, "model_dump"):
            p = p.model_dump()
        elif not isinstance(p, dict):
            p = dict(p)
        normalized.append(
            {
                "cote_ngm": Decimal(str(p["cote_ngm"])),
                "volume_mm3": Decimal(str(p["volume_mm3"])),
                "surface_km2": Decimal(str(p["surface_km2"])),
                "ligne_source": p.get("ligne_source") or index,
            }
        )
    return validate_points(normalized)


def _insert_points(db: Session, version_id: int, points: list[dict]):
    if not points:
        return
    params = [
        {
            "version_id": version_id,
            "cote_ngm": p["cote_ngm"],
            "volume_mm3": p["volume_mm3"],
            "surface_km2": p["surface_km2"],
            "ligne_source": p.get("ligne_source"),
        }
        for p in points
    ]
    db.execute(
        text(
            """
            INSERT INTO public.bareme_points (
                bareme_version_id,
                cote_ngm,
                volume_mm3,
                surface_km2,
                ligne_source
            )
            VALUES (
                :version_id,
                :cote_ngm,
                :volume_mm3,
                :surface_km2,
                :ligne_source
            )
            """
        ),
        params,
    )


def list_management_barrages(db: Session) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT
                b.id,
                b.code,
                b.nom,
                b.nom_court,
                COALESCE(b.actif, TRUE) AS actif,
                COUNT(DISTINCT bv.id) AS versions_count,
                COUNT(DISTINCT bp.id) AS points_count,
                COUNT(DISTINCT bv.id) FILTER (
                    WHERE bv.status = 'BROUILLON'
                ) AS drafts_count,
                COUNT(DISTINCT bv.id) FILTER (
                    WHERE bv.status = 'PUBLIE' AND COALESCE(bv.actif, TRUE)
                ) AS published_count,
                MAX(bv.updated_at) AS last_bareme_update
            FROM public.barrages b
            LEFT JOIN public.bareme_versions bv ON bv.barrage_id = b.id
            LEFT JOIN public.bareme_points bp ON bp.bareme_version_id = bv.id
            WHERE COALESCE(b.actif, TRUE) = TRUE
            GROUP BY b.id, b.code, b.nom, b.nom_court, b.actif, b.ordre_affichage
            ORDER BY COALESCE(b.ordre_affichage, b.id), b.code
            """
        )
    ).mappings().all()
    return [_row(row) for row in rows]


def list_versions(db: Session, barrage_code: str | None = None) -> list[dict]:
    params = {}
    where = ""
    if barrage_code:
        where = "WHERE UPPER(b.code) = UPPER(:code)"
        params["code"] = barrage_code
    rows = db.execute(
        text(
            f"""
            SELECT
                bv.id,
                bv.barrage_id,
                b.code AS barrage_code,
                b.nom AS barrage_nom,
                bv.nom,
                bv.annee_bareme,
                bv.date_debut_validite,
                bv.date_fin_validite,
                bv.status,
                bv.actif,
                bv.is_default,
                bv.locked_points,
                bv.source_type,
                bv.calculation_source,
                bv.source_fichier,
                bv.source_feuille,
                bv.source_sha256,
                bv.points_sha256,
                bv.cote_normale_ngm,
                bv.volume_normal_mm3,
                bv.surface_normale_km2,
                bv.observation,
                bv.created_at,
                bv.updated_at,
                bv.published_at,
                bv.archived_at,
                COUNT(bp.id) AS points_count
            FROM public.bareme_versions bv
            JOIN public.barrages b ON b.id = bv.barrage_id
            LEFT JOIN public.bareme_points bp ON bp.bareme_version_id = bv.id
            {where}
            GROUP BY bv.id, b.code, b.nom
            ORDER BY
                b.code,
                COALESCE(bv.date_debut_validite, DATE '0001-01-01') DESC,
                bv.id DESC
            """
        ),
        params,
    ).mappings().all()
    return [_row(row) for row in rows]


def get_version_points(db: Session, version_id: int) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT id, cote_ngm, volume_mm3, surface_km2, ligne_source, created_at, updated_at
            FROM public.bareme_points
            WHERE bareme_version_id = :version_id
            ORDER BY cote_ngm, id
            """
        ),
        {"version_id": int(version_id)},
    ).mappings().all()
    result = []
    for row in rows:
        item = dict(row)
        # Chaînes décimales : l'interface peut rééditer un BROUILLON sans
        # faire transiter les valeurs par un float JavaScript destructeur.
        for key in ("cote_ngm", "volume_mm3", "surface_km2"):
            value = item.get(key)
            item[key] = None if value is None else format(value, "f")
        item["created_at"] = _iso(item.get("created_at"))
        item["updated_at"] = _iso(item.get("updated_at"))
        result.append(item)
    return result


def get_version(db: Session, version_id: int) -> dict:
    version = _row(_version_or_raise(db, version_id))
    version["points"] = get_version_points(db, version_id)
    return version


def _published_versions_for_barrage(db: Session, *, barrage_id: int | None = None, barrage_code: str | None = None):
    if barrage_id is None:
        barrage_id = _barrage_id(db, barrage_code or "")
    rows = db.execute(
        text(
            """
            SELECT
                bv.id,
                bv.barrage_id,
                bv.nom,
                bv.annee_bareme,
                bv.date_debut_validite,
                bv.date_fin_validite,
                bv.status,
                bv.actif,
                bv.is_default,
                bv.locked_points,
                bv.source_type,
                bv.calculation_source,
                bv.cote_normale_ngm,
                bv.volume_normal_mm3,
                bv.surface_normale_km2,
                bv.points_sha256,
                bv.source_sha256,
                b.code AS barrage_code,
                b.nom AS barrage_nom,
                b.capacite_normale_mm3 AS barrage_capacite_normale_mm3,
                b.cote_normale_ngm AS barrage_cote_normale_ngm
            FROM public.bareme_versions bv
            JOIN public.barrages b ON b.id = bv.barrage_id
            WHERE bv.barrage_id = :barrage_id
              AND (
                    (bv.status = 'PUBLIE' AND COALESCE(bv.actif, TRUE) = TRUE)
                 OR (bv.status = 'ARCHIVE' AND bv.published_at IS NOT NULL
                     AND bv.date_debut_validite IS NOT NULL)
              )
            ORDER BY
                COALESCE(bv.date_debut_validite, DATE '0001-01-01') DESC,
                COALESCE(bv.is_default, FALSE) DESC,
                bv.id DESC
            """
        ),
        {"barrage_id": int(barrage_id)},
    ).mappings().all()
    return [dict(row) for row in rows]


def resolve_bareme_version(
    db: Session,
    *,
    date_reference: date,
    barrage_code: str | None = None,
    barrage_id: int | None = None,
    strict: bool = True,
) -> dict | None:
    if barrage_id is None and not barrage_code:
        raise ValueError("barrage_code ou barrage_id est obligatoire.")

    versions = _published_versions_for_barrage(
        db, barrage_id=barrage_id, barrage_code=barrage_code
    )
    if not versions:
        if strict:
            raise BaremeResolutionError("Aucune version de barème publiée pour ce barrage.")
        return None

    scheduled = [v for v in versions if v.get("date_debut_validite") is not None]

    if scheduled:
        matches = [
            v
            for v in scheduled
            if v["date_debut_validite"] <= date_reference
            and (
                v.get("date_fin_validite") is None
                or date_reference <= v["date_fin_validite"]
            )
        ]
        if len(matches) > 1:
            raise BaremeResolutionError(
                f"Plusieurs versions de barème couvrent la date {date_reference}. "
                "Corrigez les périodes avant de poursuivre."
            )
        if not matches:
            if strict:
                code = scheduled[0].get("barrage_code") or barrage_code or barrage_id
                raise BaremeResolutionError(
                    f"Aucun barème publié n'est valide pour {code} au {date_reference.isoformat()}."
                )
            return None
        result = matches[0]
    else:
        # Compatibilité sûre avec les imports historiques tant que la chronologie
        # n'a pas encore été configurée pour ce barrage.
        fallback_versions = [
            v for v in versions
            if v.get("status") == STATUS_PUBLISHED and bool(v.get("actif"))
        ]
        if not fallback_versions:
            if strict:
                raise BaremeResolutionError(
                    "Aucun barème publié actif n'est disponible pour ce barrage."
                )
            return None
        result = sorted(
            fallback_versions,
            key=lambda v: (
                bool(v.get("is_default")),
                int(v.get("id") or 0),
            ),
            reverse=True,
        )[0]

    item = _row(result)
    item["resolution_date"] = date_reference.isoformat()
    item["legacy_fallback"] = not bool(scheduled)
    item["effective_volume_normal_mm3"] = (
        item.get("volume_normal_mm3")
        if item.get("volume_normal_mm3") is not None
        else _float(result.get("barrage_capacite_normale_mm3"))
    )
    item["effective_cote_normale_ngm"] = (
        item.get("cote_normale_ngm")
        if item.get("cote_normale_ngm") is not None
        else _float(result.get("barrage_cote_normale_ngm"))
    )
    return item


def resolve_bareme_versions_for_dates(
    db: Session,
    barrage_codes: list[str],
    dates: list[date],
    *,
    strict: bool = True,
) -> dict[tuple[str, str], dict | None]:
    if not barrage_codes or not dates:
        return {}

    rows = db.execute(
        text(
            """
            SELECT
                bv.id,
                bv.barrage_id,
                bv.nom,
                bv.annee_bareme,
                bv.date_debut_validite,
                bv.date_fin_validite,
                bv.status,
                bv.actif,
                bv.is_default,
                bv.locked_points,
                bv.source_type,
                bv.calculation_source,
                bv.cote_normale_ngm,
                bv.volume_normal_mm3,
                bv.surface_normale_km2,
                bv.points_sha256,
                bv.source_sha256,
                b.code AS barrage_code,
                b.nom AS barrage_nom,
                b.capacite_normale_mm3 AS barrage_capacite_normale_mm3,
                b.cote_normale_ngm AS barrage_cote_normale_ngm
            FROM public.bareme_versions bv
            JOIN public.barrages b ON b.id = bv.barrage_id
            WHERE b.code = ANY(:codes)
              AND (
                    (bv.status = 'PUBLIE' AND COALESCE(bv.actif, TRUE) = TRUE)
                 OR (bv.status = 'ARCHIVE' AND bv.published_at IS NOT NULL
                     AND bv.date_debut_validite IS NOT NULL)
              )
            ORDER BY b.code, COALESCE(bv.date_debut_validite, DATE '0001-01-01') DESC, bv.id DESC
            """
        ),
        {"codes": barrage_codes},
    ).mappings().all()

    grouped: dict[str, list[dict]] = {code: [] for code in barrage_codes}
    for row in rows:
        grouped.setdefault(row["barrage_code"], []).append(dict(row))

    result: dict[tuple[str, str], dict | None] = {}
    for code in barrage_codes:
        versions = grouped.get(code, [])
        scheduled = [v for v in versions if v.get("date_debut_validite") is not None]
        for d in dates:
            selected = None
            if scheduled:
                matches = [
                    v
                    for v in scheduled
                    if v["date_debut_validite"] <= d
                    and (v.get("date_fin_validite") is None or d <= v["date_fin_validite"])
                ]
                if len(matches) > 1:
                    raise BaremeResolutionError(
                        f"Plusieurs barèmes couvrent {code} au {d.isoformat()}."
                    )
                if matches:
                    selected = matches[0]
                elif strict:
                    raise BaremeResolutionError(
                        f"Aucun barème publié n'est valide pour {code} au {d.isoformat()}."
                    )
            elif versions:
                fallback_versions = [
                    v for v in versions
                    if v.get("status") == STATUS_PUBLISHED and bool(v.get("actif"))
                ]
                if fallback_versions:
                    selected = sorted(
                        fallback_versions,
                        key=lambda v: (bool(v.get("is_default")), int(v.get("id") or 0)),
                        reverse=True,
                    )[0]
                elif strict:
                    raise BaremeResolutionError(
                        f"Aucun barème publié actif n'est disponible pour {code}."
                    )
            elif strict:
                raise BaremeResolutionError(
                    f"Aucune version de barème publiée pour {code}."
                )

            if selected:
                item = _row(selected)
                item["resolution_date"] = d.isoformat()
                item["legacy_fallback"] = not bool(scheduled)
                item["effective_volume_normal_mm3"] = (
                    item.get("volume_normal_mm3")
                    if item.get("volume_normal_mm3") is not None
                    else _float(selected.get("barrage_capacite_normale_mm3"))
                )
                item["effective_cote_normale_ngm"] = (
                    item.get("cote_normale_ngm")
                    if item.get("cote_normale_ngm") is not None
                    else _float(selected.get("barrage_cote_normale_ngm"))
                )
                result[(code, d.isoformat())] = item
            else:
                result[(code, d.isoformat())] = None
    return result


def fetch_points_by_versions(db: Session, version_ids: Iterable[int]) -> dict[int, list[dict]]:
    ids = sorted({int(v) for v in version_ids if v is not None})
    if not ids:
        return {}
    rows = db.execute(
        text(
            """
            SELECT bareme_version_id, cote_ngm, volume_mm3, surface_km2, ligne_source
            FROM public.bareme_points
            WHERE bareme_version_id = ANY(:ids)
            ORDER BY bareme_version_id, cote_ngm
            """
        ),
        {"ids": ids},
    ).mappings().all()
    result = {version_id: [] for version_id in ids}
    for row in rows:
        result.setdefault(int(row["bareme_version_id"]), []).append(_row(row))
    return result


def lookup_bareme_exact_by_id(
    db: Session,
    barrage_id: int,
    cote_ngm: float | Decimal | None,
    date_reference: date | None = None,
) -> dict | None:
    if cote_ngm is None:
        return None
    date_reference = date_reference or date.today()
    version = resolve_bareme_version(
        db,
        barrage_id=int(barrage_id),
        date_reference=date_reference,
        strict=True,
    )
    row = db.execute(
        text(
            """
            SELECT cote_ngm, volume_mm3, surface_km2
            FROM public.bareme_points
            WHERE bareme_version_id = :version_id
              AND ABS(cote_ngm - :cote_ngm) <= 0.0000005
            ORDER BY ABS(cote_ngm - :cote_ngm), id
            LIMIT 1
            """
        ),
        {
            "version_id": int(version["id"]),
            "cote_ngm": Decimal(str(cote_ngm)),
        },
    ).mappings().first()
    if not row:
        return None
    item = _row(row)
    item.update(
        {
            "method": "exact",
            "bareme_version_id": int(version["id"]),
            "bareme_nom": version["nom"],
            "bareme_status": version["status"],
            "date_debut_validite": version.get("date_debut_validite"),
            "date_fin_validite": version.get("date_fin_validite"),
            "calculation_source": version.get("calculation_source"),
            "volume_normal_mm3": version.get("effective_volume_normal_mm3"),
            "cote_normale_ngm": version.get("effective_cote_normale_ngm"),
            "surface_normale_km2": version.get("surface_normale_km2"),
        }
    )
    return item


def get_bareme_status(db: Session):
    rows = db.execute(
        text(
            """
            SELECT
                b.code AS barrage_code,
                b.nom_court,
                COUNT(DISTINCT bv.id) AS nb_versions,
                COUNT(bp.id) AS nb_points,
                COUNT(DISTINCT bv.id) FILTER (WHERE bv.status='PUBLIE') AS nb_publiees,
                COUNT(DISTINCT bv.id) FILTER (WHERE bv.status='BROUILLON') AS nb_brouillons
            FROM public.barrages b
            LEFT JOIN public.bareme_versions bv ON bv.barrage_id = b.id
            LEFT JOIN public.bareme_points bp ON bp.bareme_version_id = bv.id
            GROUP BY b.code, b.nom_court, b.ordre_affichage
            ORDER BY b.ordre_affichage
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def get_bareme_by_barrage_code(
    db: Session,
    barrage_code: str,
    date_reference: date | None = None,
):
    version = resolve_bareme_version(
        db,
        barrage_code=barrage_code,
        date_reference=date_reference or date.today(),
        strict=True,
    )
    points = get_version_points(db, int(version["id"]))
    for p in points:
        p.update(
            {
                "barrage_code": barrage_code.upper(),
                "bareme_version_id": int(version["id"]),
                "bareme_nom": version["nom"],
                "annee_bareme": version.get("annee_bareme"),
            }
        )
    return points


def get_volume_surface_by_cote(
    db: Session,
    barrage_code: str,
    cote_ngm: float,
    date_reference: date | None = None,
):
    barrage_id = _barrage_id(db, barrage_code)
    return lookup_bareme_exact_by_id(
        db,
        barrage_id,
        cote_ngm,
        date_reference=date_reference or date.today(),
    )



def _lock_barrage_for_versioning(db: Session, barrage_id: int) -> None:
    """Sérialise publication/changement de période pour éviter deux publications concurrentes."""
    db.execute(
        text("SELECT id FROM public.barrages WHERE id=:id FOR UPDATE"),
        {"id": int(barrage_id)},
    ).scalar()



def _conflicts(
    db: Session,
    barrage_id: int,
    start: date,
    end: date | None,
    *,
    exclude_id: int | None = None,
) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT id, nom, date_debut_validite, date_fin_validite, status
            FROM public.bareme_versions
            WHERE barrage_id = :barrage_id
              AND (
                    (status = 'PUBLIE' AND COALESCE(actif, TRUE) = TRUE)
                 OR (status = 'ARCHIVE' AND published_at IS NOT NULL)
              )
              AND date_debut_validite IS NOT NULL
              AND (:exclude_id IS NULL OR id <> :exclude_id)
              AND date_debut_validite <= COALESCE(:end_date, DATE '9999-12-31')
              AND :start_date <= COALESCE(date_fin_validite, DATE '9999-12-31')
            ORDER BY date_debut_validite, id
            """
        ),
        {
            "barrage_id": int(barrage_id),
            "start_date": start,
            "end_date": end,
            "exclude_id": exclude_id,
        },
    ).mappings().all()
    return [_row(row) for row in rows]


def preview_period_change(
    db: Session,
    version_id: int,
    start: date,
    end: date | None,
) -> dict:
    version = _version_or_raise(db, version_id)
    if end and end < start:
        raise ValueError("La date de fin ne peut pas précéder la date de début.")
    conflicts = _conflicts(
        db,
        int(version["barrage_id"]),
        start,
        end,
        exclude_id=version_id,
    )

    old_start = version.get("date_debut_validite")
    old_end = version.get("date_fin_validite")
    dates = [d for d in (old_start, old_end, start, end) if d is not None]
    impacted_bilans = 0
    if dates:
        low = min(dates)
        high = max(dates)
        impacted_bilans = int(
            db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM public.bilans_journaliers
                    WHERE barrage_id = :barrage_id
                      AND date_bilan BETWEEN :low AND :high
                    """
                ),
                {"barrage_id": int(version["barrage_id"]), "low": low, "high": high},
            ).scalar()
            or 0
        )

    return {
        "version_id": int(version_id),
        "current": {
            "date_debut_validite": _iso(old_start),
            "date_fin_validite": _iso(old_end),
        },
        "proposed": {
            "date_debut_validite": start.isoformat(),
            "date_fin_validite": _iso(end),
        },
        "conflicts": conflicts,
        "can_apply": not conflicts,
        "existing_bilans_in_impacted_window": impacted_bilans,
        "historical_bilans_recalculated_automatically": False,
    }


def create_draft_version(db: Session, payload, user_id: int | None = None) -> dict:
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    barrage_id = _barrage_id(db, data["barrage_code"])
    points_report = _normalize_points(data.get("points") or [])

    row = db.execute(
        text(
            """
            INSERT INTO public.bareme_versions (
                barrage_id,
                nom,
                annee_bareme,
                date_debut_validite,
                date_fin_validite,
                source_fichier,
                source_feuille,
                source_sha256,
                source_type,
                calculation_source,
                status,
                actif,
                is_default,
                locked_points,
                cote_normale_ngm,
                volume_normal_mm3,
                surface_normale_km2,
                points_sha256,
                observation,
                created_by
            )
            VALUES (
                :barrage_id,
                :nom,
                :annee_bareme,
                :date_debut_validite,
                :date_fin_validite,
                :source_fichier,
                :source_feuille,
                :source_sha256,
                :source_type,
                'DATABASE_VERSIONED',
                'BROUILLON',
                FALSE,
                FALSE,
                FALSE,
                :cote_normale_ngm,
                :volume_normal_mm3,
                :surface_normale_km2,
                :points_sha256,
                :observation,
                :created_by
            )
            RETURNING id
            """
        ),
        {
            "barrage_id": barrage_id,
            "nom": data["nom"],
            "annee_bareme": data.get("annee_bareme"),
            "date_debut_validite": data.get("date_debut_validite"),
            "date_fin_validite": data.get("date_fin_validite"),
            "source_fichier": data.get("source_fichier"),
            "source_feuille": data.get("source_feuille"),
            "source_sha256": data.get("source_sha256"),
            "source_type": data.get("source_type") or "MANUEL",
            "cote_normale_ngm": data.get("cote_normale_ngm"),
            "volume_normal_mm3": data.get("volume_normal_mm3"),
            "surface_normale_km2": data.get("surface_normale_km2"),
            "points_sha256": points_report["points_sha256"],
            "observation": data.get("observation"),
            "created_by": user_id,
        },
    ).mappings().first()
    version_id = int(row["id"])
    _insert_points(db, version_id, points_report["points"])

    _audit(
        db,
        version_id=version_id,
        barrage_id=barrage_id,
        action="CREATE_DRAFT",
        user_id=user_id,
        details={
            "points_count": len(points_report["points"]),
            "warnings": points_report["warnings"],
            "source_type": data.get("source_type") or "MANUEL",
        },
        new_values=data,
    )
    db.commit()
    return {
        "status": "ok",
        "message": "Brouillon de barème créé.",
        "warnings": points_report["warnings"],
        "data": get_version(db, version_id),
    }


def update_draft_version(db: Session, version_id: int, payload, user_id: int | None = None) -> dict:
    current = _version_or_raise(db, version_id)
    if current["status"] != STATUS_DRAFT:
        raise ValueError(
            "Les points d'une version publiée sont verrouillés. "
            "Dupliquez-la en brouillon pour modifier ses points."
        )

    values = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload)
    points = values.pop("points", None)

    allowed = {
        "nom",
        "annee_bareme",
        "date_debut_validite",
        "date_fin_validite",
        "cote_normale_ngm",
        "volume_normal_mm3",
        "surface_normale_km2",
        "observation",
    }
    values = {k: v for k, v in values.items() if k in allowed}

    if values:
        assignments = ", ".join(f"{key}=:{key}" for key in values)
        db.execute(
            text(
                f"""
                UPDATE public.bareme_versions
                SET {assignments}, updated_at=now()
                WHERE id=:version_id
                """
            ),
            {**values, "version_id": int(version_id)},
        )

    warnings = []
    if points is not None:
        report = _normalize_points(points)
        db.execute(
            text("DELETE FROM public.bareme_points WHERE bareme_version_id=:version_id"),
            {"version_id": int(version_id)},
        )
        _insert_points(db, version_id, report["points"])
        db.execute(
            text(
                """
                UPDATE public.bareme_versions
                SET points_sha256=:hash, updated_at=now()
                WHERE id=:version_id
                """
            ),
            {"hash": report["points_sha256"], "version_id": int(version_id)},
        )
        warnings = report["warnings"]

    _audit(
        db,
        version_id=int(version_id),
        barrage_id=int(current["barrage_id"]),
        action="UPDATE_DRAFT",
        user_id=user_id,
        old_values=_row(current),
        new_values=values,
        details={"points_replaced": points is not None, "warnings": warnings},
    )
    db.commit()
    return {
        "status": "ok",
        "message": "Brouillon mis à jour.",
        "warnings": warnings,
        "data": get_version(db, version_id),
    }


def clone_version(db: Session, version_id: int, payload, user_id: int | None = None) -> dict:
    source = get_version(db, version_id)
    values = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload)
    create_payload = {
        "barrage_code": source["barrage_code"],
        "nom": values.get("nom") or f"{source['nom']} - nouvelle version",
        "annee_bareme": values.get("annee_bareme", source.get("annee_bareme")),
        "date_debut_validite": values.get("date_debut_validite"),
        "date_fin_validite": values.get("date_fin_validite"),
        "cote_normale_ngm": source.get("cote_normale_ngm"),
        "volume_normal_mm3": source.get("volume_normal_mm3"),
        "surface_normale_km2": source.get("surface_normale_km2"),
        "observation": f"Copie de la version {version_id}.",
        "source_type": "COPIE",
        "source_fichier": source.get("source_fichier"),
        "source_feuille": source.get("source_feuille"),
        "source_sha256": source.get("source_sha256"),
        "points": [
            {
                "cote_ngm": p["cote_ngm"],
                "volume_mm3": p["volume_mm3"],
                "surface_km2": p["surface_km2"],
            }
            for p in source["points"]
        ],
    }

    class _Payload:
        def model_dump(self):
            return create_payload

    result = create_draft_version(db, _Payload(), user_id=user_id)
    _audit(
        db,
        version_id=int(result["data"]["id"]),
        barrage_id=int(result["data"]["barrage_id"]),
        action="CLONE_VERSION",
        user_id=user_id,
        details={"source_version_id": int(version_id)},
    )
    db.commit()
    return result


def delete_draft_version(db: Session, version_id: int, user_id: int | None = None) -> dict:
    current = _version_or_raise(db, version_id)
    if current["status"] != STATUS_DRAFT:
        raise ValueError("Seul un brouillon peut être supprimé.")
    _audit(
        db,
        version_id=int(version_id),
        barrage_id=int(current["barrage_id"]),
        action="DELETE_DRAFT",
        user_id=user_id,
        old_values=_row(current),
    )
    db.execute(
        text("DELETE FROM public.bareme_versions WHERE id=:version_id"),
        {"version_id": int(version_id)},
    )
    db.commit()
    return {"status": "ok", "message": "Brouillon supprimé."}


def publish_version(
    db: Session,
    version_id: int,
    *,
    user_id: int | None,
    close_previous: bool = True,
    commentaire: str | None = None,
) -> dict:
    version = _version_or_raise(db, version_id)
    if version["status"] != STATUS_DRAFT:
        raise ValueError("Seul un brouillon peut être publié.")
    start = version.get("date_debut_validite")
    end = version.get("date_fin_validite")
    if start is None:
        raise ValueError("La date de début d'application est obligatoire avant publication.")
    if end is not None and end < start:
        raise ValueError("La date de fin ne peut pas précéder la date de début.")

    point_count = int(
        db.execute(
            text("SELECT COUNT(*) FROM public.bareme_points WHERE bareme_version_id=:id"),
            {"id": int(version_id)},
        ).scalar()
        or 0
    )
    if point_count < 2:
        raise ValueError("Le barème doit contenir au moins deux points avant publication.")

    barrage_id = int(version["barrage_id"])
    _lock_barrage_for_versioning(db, barrage_id)

    # Une version historique sans date doit d'abord recevoir sa date officielle.
    legacy_open = db.execute(
        text(
            """
            SELECT id, nom
            FROM public.bareme_versions
            WHERE barrage_id=:barrage_id
              AND id<>:version_id
              AND status='PUBLIE'
              AND COALESCE(actif, TRUE)=TRUE
              AND date_debut_validite IS NULL
            ORDER BY COALESCE(is_default,FALSE) DESC, id DESC
            LIMIT 1
            """
        ),
        {"barrage_id": barrage_id, "version_id": int(version_id)},
    ).mappings().first()
    if legacy_open:
        raise ValueError(
            f"La version publiée '{legacy_open['nom']}' n'a pas encore de date de début. "
            "Renseignez d'abord sa date officielle avant de publier une nouvelle version."
        )

    previous = None
    if close_previous:
        previous = db.execute(
            text(
                """
                SELECT *
                FROM public.bareme_versions
                WHERE barrage_id=:barrage_id
                  AND id<>:version_id
                  AND status='PUBLIE'
                  AND COALESCE(actif, TRUE)=TRUE
                  AND date_debut_validite IS NOT NULL
                  AND date_debut_validite < :start_date
                  AND COALESCE(date_fin_validite, DATE '9999-12-31') >= :start_date
                ORDER BY date_debut_validite DESC, id DESC
                LIMIT 1
                FOR UPDATE
                """
            ),
            {
                "barrage_id": barrage_id,
                "version_id": int(version_id),
                "start_date": start,
            },
        ).mappings().first()
        if previous:
            old_previous = _row(previous)
            new_end = start - timedelta(days=1)
            db.execute(
                text(
                    """
                    UPDATE public.bareme_versions
                    SET date_fin_validite=:new_end, updated_at=now()
                    WHERE id=:id
                    """
                ),
                {"new_end": new_end, "id": int(previous["id"])},
            )
            _audit(
                db,
                version_id=int(previous["id"]),
                barrage_id=barrage_id,
                action="AUTO_CLOSE_PERIOD",
                user_id=user_id,
                old_values=old_previous,
                new_values={"date_fin_validite": new_end.isoformat()},
                details={"new_version_id": int(version_id)},
            )

    conflicts = _conflicts(
        db,
        barrage_id,
        start,
        end,
        exclude_id=version_id,
    )
    if conflicts:
        names = ", ".join(c["nom"] for c in conflicts[:5])
        raise ValueError(
            "Publication impossible : la période chevauche une version publiée "
            f"({names})."
        )

    db.execute(
        text(
            """
            UPDATE public.bareme_versions
            SET is_default=FALSE, updated_at=now()
            WHERE barrage_id=:barrage_id
            """
        ),
        {"barrage_id": barrage_id},
    )
    db.execute(
        text(
            """
            UPDATE public.bareme_versions
            SET
                status='PUBLIE',
                actif=TRUE,
                is_default=TRUE,
                locked_points=TRUE,
                published_at=now(),
                published_by=:user_id,
                publication_comment=:comment,
                updated_at=now()
            WHERE id=:version_id
            """
        ),
        {
            "version_id": int(version_id),
            "user_id": user_id,
            "comment": commentaire,
        },
    )
    _audit(
        db,
        version_id=int(version_id),
        barrage_id=barrage_id,
        action="PUBLISH",
        user_id=user_id,
        old_values=_row(version),
        new_values={
            "status": "PUBLIE",
            "date_debut_validite": _iso(start),
            "date_fin_validite": _iso(end),
            "locked_points": True,
        },
        details={
            "points_count": point_count,
            "auto_closed_previous_version_id": int(previous["id"]) if previous else None,
            "commentaire": commentaire,
        },
    )
    db.commit()
    return {
        "status": "ok",
        "message": "Version publiée. Elle sera sélectionnée automatiquement selon sa période.",
        "data": get_version(db, version_id),
    }


def update_published_period(
    db: Session,
    version_id: int,
    *,
    start: date,
    end: date | None,
    user_id: int | None,
    commentaire: str | None = None,
) -> dict:
    current = _version_or_raise(db, version_id)
    if current["status"] != STATUS_PUBLISHED:
        raise ValueError("Cette opération est réservée aux versions publiées.")
    _lock_barrage_for_versioning(db, int(current["barrage_id"]))
    preview = preview_period_change(db, version_id, start, end)
    if preview["conflicts"]:
        names = ", ".join(c["nom"] for c in preview["conflicts"][:5])
        raise ValueError(f"Période refusée : chevauchement avec {names}.")

    old = _row(current)
    db.execute(
        text(
            """
            UPDATE public.bareme_versions
            SET date_debut_validite=:start_date,
                date_fin_validite=:end_date,
                updated_at=now()
            WHERE id=:version_id
            """
        ),
        {
            "start_date": start,
            "end_date": end,
            "version_id": int(version_id),
        },
    )
    _audit(
        db,
        version_id=int(version_id),
        barrage_id=int(current["barrage_id"]),
        action="UPDATE_PERIOD",
        user_id=user_id,
        old_values=old,
        new_values={
            "date_debut_validite": start.isoformat(),
            "date_fin_validite": _iso(end),
        },
        details={
            "commentaire": commentaire,
            "existing_bilans_in_impacted_window": preview[
                "existing_bilans_in_impacted_window"
            ],
            "historical_bilans_recalculated_automatically": False,
        },
    )
    db.commit()
    return {
        "status": "ok",
        "message": "Période mise à jour. Aucun bilan historique n'a été recalculé.",
        "impact": preview,
        "data": get_version(db, version_id),
    }


def archive_version(
    db: Session,
    version_id: int,
    *,
    user_id: int | None,
    confirm: bool,
    commentaire: str | None = None,
) -> dict:
    if not confirm:
        raise ValueError("Confirmation obligatoire pour archiver une version.")

    current = _version_or_raise(db, version_id)
    if current["status"] == STATUS_ARCHIVED:
        return {
            "status": "ok",
            "message": "Version déjà archivée.",
            "data": get_version(db, version_id),
        }
    if current["status"] != STATUS_PUBLISHED:
        raise ValueError("Seule une version publiée peut être archivée.")

    # Une version ouverte ne doit jamais être retirée silencieusement du moteur.
    # Fermez d'abord sa période ou publiez sa remplaçante.
    if current.get("date_fin_validite") is None:
        raise ValueError(
            "Cette version n'a pas de date de fin. "
            "Publiez d'abord sa remplaçante (fermeture automatique possible) "
            "ou renseignez sa date de fin avant de l'archiver."
        )
    if current.get("date_debut_validite") is None:
        raise ValueError(
            "La version ne peut pas être archivée de façon traçable sans date de début."
        )

    barrage_id = int(current["barrage_id"])
    _lock_barrage_for_versioning(db, barrage_id)

    # ARCHIVE signifie : verrouillée / retirée des choix administratifs courants,
    # mais elle reste résoluble pour les dates de sa période historique.
    db.execute(
        text(
            """
            UPDATE public.bareme_versions
            SET status='ARCHIVE',
                actif=FALSE,
                is_default=FALSE,
                locked_points=TRUE,
                archived_at=now(),
                archived_by=:user_id,
                updated_at=now()
            WHERE id=:version_id
            """
        ),
        {"version_id": int(version_id), "user_id": user_id},
    )
    _audit(
        db,
        version_id=int(version_id),
        barrage_id=barrage_id,
        action="ARCHIVE",
        user_id=user_id,
        old_values=_row(current),
        new_values={
            "status": "ARCHIVE",
            "actif": False,
            "historical_resolution_preserved": True,
        },
        details={
            "commentaire": commentaire,
            "date_debut_validite": _iso(current.get("date_debut_validite")),
            "date_fin_validite": _iso(current.get("date_fin_validite")),
        },
    )
    db.commit()
    return {
        "status": "ok",
        "message": (
            "Version archivée. Sa période historique reste résoluble et "
            "aucun bilan historique n'a été recalculé."
        ),
        "data": get_version(db, version_id),
    }


def list_audit(db: Session, version_id: int | None = None, limit: int = 200) -> list[dict]:
    where = ""
    params = {"limit": max(1, min(int(limit), 500))}
    if version_id is not None:
        where = "WHERE bal.bareme_version_id=:version_id"
        params["version_id"] = int(version_id)
    rows = db.execute(
        text(
            f"""
            SELECT
                bal.id,
                bal.bareme_version_id,
                bal.barrage_id,
                b.code AS barrage_code,
                bv.nom AS bareme_nom,
                bal.action,
                bal.user_id,
                u.username,
                u.full_name,
                bal.details,
                bal.old_values,
                bal.new_values,
                bal.created_at
            FROM public.bareme_audit_log bal
            LEFT JOIN public.bareme_versions bv ON bv.id=bal.bareme_version_id
            LEFT JOIN public.barrages b ON b.id=bal.barrage_id
            LEFT JOIN public.users u ON u.id=bal.user_id
            {where}
            ORDER BY bal.created_at DESC, bal.id DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    result = []
    for row in rows:
        item = dict(row)
        item["created_at"] = _iso(item.get("created_at"))
        result.append(item)
    return result

# === ABHL V28 AUTO NORMAL REFERENCES START ===
#
# V28 - Références normales dérivées automatiquement du barème.
# L'utilisateur saisit seulement la cote normale. Volume normal et surface
# normale sont calculés depuis le point EXACT du barème. Aucune interpolation.
#
# Les versions 2023 déjà publiées ne sont pas modifiées ici. La règle s'applique
# aux nouveaux brouillons / mises à jour / publications DATABASE_VERSIONED.

if "_abhl_v28_original_create_draft_version" not in globals():
    _abhl_v28_original_create_draft_version = create_draft_version
if "_abhl_v28_original_update_draft_version" not in globals():
    _abhl_v28_original_update_draft_version = update_draft_version
if "_abhl_v28_original_publish_version" not in globals():
    _abhl_v28_original_publish_version = publish_version


class _ABHLV28Payload:
    def __init__(self, data: dict, exclude_unset_keys: set[str] | None = None):
        self._data = data
        self._exclude_unset_keys = exclude_unset_keys

    def model_dump(self, *args, **kwargs):
        data = dict(self._data)
        if kwargs.get("exclude_unset") and self._exclude_unset_keys is not None:
            return {k: data[k] for k in self._exclude_unset_keys if k in data}
        return data


def _abhl_v28_decimal_or_none(value):
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _abhl_v28_exact_normal_point(points, cote_normale):
    target = _abhl_v28_decimal_or_none(cote_normale)
    if target is None:
        return None

    match = None
    for point in points or []:
        if hasattr(point, "model_dump"):
            point = point.model_dump()
        elif not isinstance(point, dict):
            point = dict(point)

        cote = _abhl_v28_decimal_or_none(point.get("cote_ngm"))
        if cote is None or cote != target:
            continue

        if match is not None:
            raise ValueError(
                f"Plusieurs points correspondent à la cote normale {target}. "
                "Le barème doit contenir une seule ligne par cote."
            )

        match = {
            "cote_ngm": target,
            "volume_mm3": _abhl_v28_decimal_or_none(point.get("volume_mm3")),
            "surface_km2": _abhl_v28_decimal_or_none(point.get("surface_km2")),
        }

    return match


def _abhl_v28_apply_normal_reference(data: dict, points, *, strict: bool):
    data = dict(data)
    cote = data.get("cote_normale_ngm")

    # Les valeurs fournies par l'interface ne sont jamais prises comme source.
    # Elles sont toujours recalculées côté serveur.
    data["volume_normal_mm3"] = None
    data["surface_normale_km2"] = None

    if cote in (None, ""):
        if strict:
            raise ValueError(
                "La cote normale NGM est obligatoire avant publication. "
                "Le volume normal et la surface normale seront calculés automatiquement."
            )
        return data, (
            "Cote normale non renseignée : volume normal et surface normale "
            "restent vides dans le brouillon."
        )

    point = _abhl_v28_exact_normal_point(points, cote)
    if point is None:
        if strict:
            raise ValueError(
                f"La cote normale {cote} n'existe pas exactement dans les points du barème. "
                "Ajoutez/corrigez ce point. Aucune interpolation n'est autorisée."
            )
        return data, (
            f"Cote normale {cote} absente des points : le brouillon est conservé, "
            "mais il ne pourra pas être publié tant que la cote exacte n'existe pas."
        )

    if point["volume_mm3"] is None or point["surface_km2"] is None:
        raise ValueError(
            f"Le point de cote normale {cote} doit contenir volume et surface."
        )

    data["volume_normal_mm3"] = point["volume_mm3"]
    data["surface_normale_km2"] = point["surface_km2"]
    return data, None


def _abhl_v28_current_points(db: Session, version_id: int) -> list[dict]:
    return [
        {
            "cote_ngm": row["cote_ngm"],
            "volume_mm3": row["volume_mm3"],
            "surface_km2": row["surface_km2"],
        }
        for row in db.execute(
            text(
                """
                SELECT cote_ngm, volume_mm3, surface_km2
                FROM public.bareme_points
                WHERE bareme_version_id=:version_id
                ORDER BY cote_ngm, id
                """
            ),
            {"version_id": int(version_id)},
        ).mappings().all()
    ]


def create_draft_version(db: Session, payload, user_id: int | None = None) -> dict:
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    points = data.get("points") or []
    data, warning = _abhl_v28_apply_normal_reference(data, points, strict=False)

    result = _abhl_v28_original_create_draft_version(
        db,
        _ABHLV28Payload(data),
        user_id=user_id,
    )
    if warning:
        warnings = list(result.get("warnings") or [])
        if warning not in warnings:
            warnings.append(warning)
        result["warnings"] = warnings
    return result


def update_draft_version(db: Session, version_id: int, payload, user_id: int | None = None) -> dict:
    current = _version_or_raise(db, version_id)
    if current["status"] != STATUS_DRAFT:
        return _abhl_v28_original_update_draft_version(
            db, version_id, payload, user_id=user_id
        )

    values = (
        payload.model_dump(exclude_unset=True)
        if hasattr(payload, "model_dump")
        else dict(payload)
    )
    supplied_keys = set(values.keys())

    points = values.get("points")
    if points is None:
        points = _abhl_v28_current_points(db, version_id)

    cote = (
        values.get("cote_normale_ngm")
        if "cote_normale_ngm" in values
        else current.get("cote_normale_ngm")
    )

    # Recalcule aussi si seuls les points ont changé.
    values["cote_normale_ngm"] = cote
    values, warning = _abhl_v28_apply_normal_reference(values, points, strict=False)

    # L'original ne doit recevoir que les champs réellement modifiés, plus les
    # références normales que V28 recalcule de façon autoritaire.
    allowed_keys = set(supplied_keys)
    allowed_keys.update(
        {"cote_normale_ngm", "volume_normal_mm3", "surface_normale_km2"}
    )
    if "points" in supplied_keys:
        allowed_keys.add("points")

    result = _abhl_v28_original_update_draft_version(
        db,
        version_id,
        _ABHLV28Payload(values, allowed_keys),
        user_id=user_id,
    )
    if warning:
        warnings = list(result.get("warnings") or [])
        if warning not in warnings:
            warnings.append(warning)
        result["warnings"] = warnings
    return result


def publish_version(
    db: Session,
    version_id: int,
    *,
    user_id: int | None,
    close_previous: bool = True,
    commentaire: str | None = None,
) -> dict:
    current = _version_or_raise(db, version_id)

    # Les versions legacy déjà publiées ne passent pas ici : publish_version
    # ne publie que des brouillons. Pour toute nouvelle version, la référence
    # normale doit être complète et cohérente avec le point exact du barème.
    points = _abhl_v28_current_points(db, version_id)
    check_data = {
        "cote_normale_ngm": current.get("cote_normale_ngm"),
    }
    check_data, _ = _abhl_v28_apply_normal_reference(
        check_data,
        points,
        strict=True,
    )

    old_values = {
        "cote_normale_ngm": current.get("cote_normale_ngm"),
        "volume_normal_mm3": current.get("volume_normal_mm3"),
        "surface_normale_km2": current.get("surface_normale_km2"),
    }
    new_values = {
        "cote_normale_ngm": check_data.get("cote_normale_ngm"),
        "volume_normal_mm3": check_data.get("volume_normal_mm3"),
        "surface_normale_km2": check_data.get("surface_normale_km2"),
    }

    db.execute(
        text(
            """
            UPDATE public.bareme_versions
            SET volume_normal_mm3=:volume_normal_mm3,
                surface_normale_km2=:surface_normale_km2,
                updated_at=now()
            WHERE id=:version_id
            """
        ),
        {
            "volume_normal_mm3": check_data["volume_normal_mm3"],
            "surface_normale_km2": check_data["surface_normale_km2"],
            "version_id": int(version_id),
        },
    )

    if old_values != new_values:
        _audit(
            db,
            version_id=int(version_id),
            barrage_id=int(current["barrage_id"]),
            action="AUTO_NORMAL_REFERENCE",
            user_id=user_id,
            details={
                "rule": "EXACT_POINT_ONLY",
                "interpolation": False,
            },
            old_values=old_values,
            new_values=new_values,
        )

    return _abhl_v28_original_publish_version(
        db,
        version_id,
        user_id=user_id,
        close_previous=close_previous,
        commentaire=commentaire,
    )

# === ABHL V28 AUTO NORMAL REFERENCES END ===
