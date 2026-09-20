from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.barrage_admin.schemas import (
    BarrageCreateRequest,
    BarrageUpdateRequest,
    BaremeImportRequest,
    InitialBilanRequest,
)


def _float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _row_to_dict(row) -> dict:
    item = dict(row)
    for key, value in list(item.items()):
        if isinstance(value, Decimal):
            item[key] = float(value)
        elif isinstance(value, (date, datetime)):
            item[key] = value.isoformat()
    return item


def normalize_code(value: str) -> str:
    code = value.strip().upper()
    code = code.replace(" ", "_").replace("-", "_")
    code = re.sub(r"[^A-Z0-9_]", "", code)
    code = re.sub(r"_+", "_", code).strip("_")
    if not code:
        raise ValueError("Code barrage invalide.")
    return code


def list_reference_data(db: Session) -> dict:
    agences = db.execute(text("""
        SELECT id, code, nom, actif
        FROM public.agences_territoriales
        WHERE COALESCE(actif, TRUE) = TRUE
        ORDER BY nom;
    """)).mappings().all()

    bassins = db.execute(text("""
        SELECT id, code, nom
        FROM public.bassins
        ORDER BY nom;
    """)).mappings().all()

    provinces = db.execute(text("""
        SELECT id, code, nom, region
        FROM public.provinces
        ORDER BY nom;
    """)).mappings().all()

    types = db.execute(text("""
        SELECT id, code, libelle, unite, actif
        FROM public.types_restitution
        WHERE COALESCE(actif, TRUE) = TRUE
        ORDER BY code;
    """)).mappings().all()

    max_order = db.execute(text("""
        SELECT COALESCE(MAX(ordre_affichage), 0) FROM public.barrages;
    """)).scalar() or 0

    return {
        "status": "ok",
        "agences": [_row_to_dict(row) for row in agences],
        "bassins": [_row_to_dict(row) for row in bassins],
        "provinces": [_row_to_dict(row) for row in provinces],
        "types_restitution": [_row_to_dict(row) for row in types],
        "suggested_next_order": int(max_order) + 1,
    }


def list_admin_barrages(db: Session) -> dict:
    rows = db.execute(text("""
        SELECT
            b.id,
            b.code,
            b.nom,
            b.nom_court,
            b.capacite_normale_mm3,
            b.cote_normale_ngm,
            b.cote_min_ngm,
            b.cote_max_ngm,
            b.ordre_affichage,
            b.actif,
            b.inclure_calculs,
            b.inclure_annonce,
            b.inclure_bilan,
            b.inclure_situation,
            b.ordre_annonce,
            b.ordre_bilan,
            b.ordre_situation,
            b.date_mise_service,
            b.statut_perimetre,
            b.observation,
            a.code AS agence_code,
            a.nom AS agence_nom,
            ba.nom AS bassin_nom,
            p.nom AS province_nom,
            COALESCE(rt.nb_restitutions, 0) AS nb_restitutions,
            COALESCE(bp.nb_points, 0) AS nb_points_bareme,
            last_bilan.dernier_bilan
        FROM public.barrages b
        LEFT JOIN public.agences_territoriales a ON a.id = b.agence_id
        LEFT JOIN public.bassins ba ON ba.id = b.bassin_id
        LEFT JOIN public.provinces p ON p.id = b.province_id
        LEFT JOIN (
            SELECT barrage_id, COUNT(*) AS nb_restitutions
            FROM public.barrage_types_restitution
            WHERE COALESCE(actif, TRUE) = TRUE
            GROUP BY barrage_id
        ) rt ON rt.barrage_id = b.id
        LEFT JOIN (
            SELECT bv.barrage_id, COUNT(bp.id) AS nb_points
            FROM public.bareme_versions bv
            LEFT JOIN public.bareme_points bp ON bp.bareme_version_id = bv.id
            WHERE COALESCE(bv.actif, TRUE) = TRUE
            GROUP BY bv.barrage_id
        ) bp ON bp.barrage_id = b.id
        LEFT JOIN (
            SELECT barrage_id, MAX(date_bilan) AS dernier_bilan
            FROM public.bilans_journaliers
            GROUP BY barrage_id
        ) last_bilan ON last_bilan.barrage_id = b.id
        ORDER BY b.ordre_affichage NULLS LAST, b.id;
    """)).mappings().all()

    return {"status": "ok", "count": len(rows), "data": [_row_to_dict(row) for row in rows]}


def get_barrage_id(db: Session, code: str) -> int | None:
    row = db.execute(
        text("SELECT id FROM public.barrages WHERE code = :code LIMIT 1"),
        {"code": normalize_code(code)},
    ).mappings().first()
    return int(row["id"]) if row else None


def get_admin_barrage(db: Session, code: str) -> dict | None:
    code = normalize_code(code)
    row = db.execute(text("""
        SELECT
            b.*,
            a.code AS agence_code,
            a.nom AS agence_nom,
            ba.nom AS bassin_nom,
            p.nom AS province_nom
        FROM public.barrages b
        LEFT JOIN public.agences_territoriales a ON a.id = b.agence_id
        LEFT JOIN public.bassins ba ON ba.id = b.bassin_id
        LEFT JOIN public.provinces p ON p.id = b.province_id
        WHERE b.code = :code
        LIMIT 1;
    """), {"code": code}).mappings().first()
    if not row:
        return None

    item = _row_to_dict(row)
    restitution_rows = db.execute(text("""
        SELECT tr.id, tr.code, tr.libelle, tr.unite, btr.ordre_affichage, btr.obligatoire, btr.actif
        FROM public.barrage_types_restitution btr
        JOIN public.types_restitution tr ON tr.id = btr.type_restitution_id
        WHERE btr.barrage_id = :barrage_id
        ORDER BY btr.ordre_affichage, tr.code;
    """), {"barrage_id": item["id"]}).mappings().all()
    item["restitutions"] = [_row_to_dict(row) for row in restitution_rows]
    return item


def create_barrage_full(db: Session, payload: BarrageCreateRequest) -> dict:
    code = normalize_code(payload.code)
    existing = get_barrage_id(db, code)
    if existing:
        raise ValueError(f"Un barrage avec le code {code} existe déjà.")

    order = payload.ordre_affichage
    if order is None:
        order = int(db.execute(text("SELECT COALESCE(MAX(ordre_affichage), 0) + 1 FROM public.barrages")).scalar() or 1)

    row = db.execute(text("""
        INSERT INTO public.barrages (
            code, nom, nom_court,
            agence_id, bassin_id, province_id,
            capacite_normale_mm3, cote_normale_ngm, cote_min_ngm, cote_max_ngm,
            feuille_annonce, feuille_djbarrage, fichier_bm,
            ordre_affichage, ordre_annonce, ordre_bilan, ordre_situation,
            date_mise_service,
            actif, inclure_calculs, inclure_annonce, inclure_bilan, inclure_situation,
            statut_perimetre, mode_creation, observation
        )
        VALUES (
            :code, :nom, :nom_court,
            :agence_id, :bassin_id, :province_id,
            :capacite_normale_mm3, :cote_normale_ngm, :cote_min_ngm, :cote_max_ngm,
            :feuille_annonce, :feuille_djbarrage, :fichier_bm,
            :ordre_affichage, :ordre_annonce, :ordre_bilan, :ordre_situation,
            :date_mise_service,
            :actif, :inclure_calculs, :inclure_annonce, :inclure_bilan, :inclure_situation,
            'ACTIF', 'SAISIE_PLATEFORME', :observation
        )
        RETURNING id;
    """), {
        **payload.model_dump(),
        "code": code,
        "ordre_affichage": order,
        "ordre_annonce": payload.ordre_annonce if payload.ordre_annonce is not None else order,
        "ordre_bilan": payload.ordre_bilan if payload.ordre_bilan is not None else order,
        "ordre_situation": payload.ordre_situation if payload.ordre_situation is not None else order,
    }).mappings().first()

    barrage_id = int(row["id"])
    sync_restitutions(db, barrage_id, payload.restitution_type_ids)
    db.commit()
    return {"status": "ok", "message": "Barrage créé avec succès.", "barrage": get_admin_barrage(db, code)}


def sync_restitutions(db: Session, barrage_id: int, type_ids: list[int]):
    clean_ids = [int(x) for x in dict.fromkeys(type_ids or [])]
    db.execute(
        text("UPDATE public.barrage_types_restitution SET actif = FALSE WHERE barrage_id = :barrage_id"),
        {"barrage_id": barrage_id},
    )
    for index, type_id in enumerate(clean_ids, start=1):
        db.execute(text("""
            INSERT INTO public.barrage_types_restitution (
                barrage_id, type_restitution_id, ordre_affichage, obligatoire, actif
            )
            VALUES (:barrage_id, :type_id, :ordre, FALSE, TRUE)
            ON CONFLICT (barrage_id, type_restitution_id)
            DO UPDATE SET
                ordre_affichage = EXCLUDED.ordre_affichage,
                actif = TRUE,
                updated_at = now();
        """), {"barrage_id": barrage_id, "type_id": type_id, "ordre": index})


def update_barrage_configuration(db: Session, code: str, payload: BarrageUpdateRequest) -> dict:
    code = normalize_code(code)
    barrage_id = get_barrage_id(db, code)
    if not barrage_id:
        raise ValueError(f"Barrage introuvable : {code}")

    values = payload.model_dump(exclude_unset=True)
    restitution_ids = values.pop("restitution_type_ids", None)
    if values:
        assignments = ", ".join(f"{key} = :{key}" for key in values.keys())
        db.execute(
            text(f"UPDATE public.barrages SET {assignments}, updated_at = now() WHERE id = :barrage_id"),
            {**values, "barrage_id": barrage_id},
        )
    if restitution_ids is not None:
        sync_restitutions(db, barrage_id, restitution_ids)

    db.commit()
    return {"status": "ok", "message": "Configuration du barrage mise à jour.", "barrage": get_admin_barrage(db, code)}


def import_bareme_points(db: Session, code: str, payload: BaremeImportRequest) -> dict:
    code = normalize_code(code)
    barrage_id = get_barrage_id(db, code)
    if not barrage_id:
        raise ValueError(f"Barrage introuvable : {code}")
    if not payload.points:
        raise ValueError("Aucun point de barème fourni.")

    db.execute(text("UPDATE public.bareme_versions SET is_default = FALSE WHERE barrage_id = :barrage_id"), {"barrage_id": barrage_id})
    row = db.execute(text("""
        INSERT INTO public.bareme_versions (
            barrage_id, nom, annee_bareme, date_debut_validite,
            source_fichier, source_feuille, actif, is_default, observation
        )
        VALUES (
            :barrage_id, :nom, :annee_bareme, :date_debut_validite,
            :source_fichier, :source_feuille, TRUE, TRUE, :observation
        )
        RETURNING id;
    """), {
        "barrage_id": barrage_id,
        "nom": payload.nom,
        "annee_bareme": payload.annee_bareme,
        "date_debut_validite": payload.date_debut_validite,
        "source_fichier": payload.source_fichier,
        "source_feuille": payload.source_feuille,
        "observation": payload.observation,
    }).mappings().first()
    version_id = int(row["id"])

    inserted = 0
    for index, point in enumerate(payload.points, start=1):
        db.execute(text("""
            INSERT INTO public.bareme_points (
                bareme_version_id, cote_ngm, volume_mm3, surface_km2, ligne_source
            )
            VALUES (:version_id, :cote_ngm, :volume_mm3, :surface_km2, :ligne_source)
            ON CONFLICT (bareme_version_id, cote_ngm)
            DO UPDATE SET
                volume_mm3 = EXCLUDED.volume_mm3,
                surface_km2 = EXCLUDED.surface_km2,
                ligne_source = EXCLUDED.ligne_source;
        """), {
            "version_id": version_id,
            "cote_ngm": point.cote_ngm,
            "volume_mm3": point.volume_mm3,
            "surface_km2": point.surface_km2,
            "ligne_source": index,
        })
        inserted += 1

    db.commit()
    return {"status": "ok", "message": "Barème importé.", "bareme_version_id": version_id, "points_count": inserted, "readiness": get_barrage_readiness(db, code)}


def _fetch_default_bareme_points(db: Session, barrage_id: int) -> list[dict]:
    rows = db.execute(text("""
        WITH selected_version AS (
            SELECT id
            FROM public.bareme_versions
            WHERE barrage_id = :barrage_id
              AND COALESCE(actif, TRUE) = TRUE
            ORDER BY COALESCE(is_default, FALSE) DESC,
                     date_debut_validite DESC NULLS LAST,
                     id DESC
            LIMIT 1
        )
        SELECT bp.cote_ngm, bp.volume_mm3, bp.surface_km2
        FROM public.bareme_points bp
        JOIN selected_version sv ON sv.id = bp.bareme_version_id
        ORDER BY bp.cote_ngm;
    """), {"barrage_id": barrage_id}).mappings().all()
    return [_row_to_dict(row) for row in rows]


def _interpolate_from_bareme(points: list[dict], cote: float) -> dict:
    if not points:
        raise ValueError("Aucun barème disponible pour ce barrage.")

    clean = []
    for p in points:
        c = _float(p.get("cote_ngm"))
        v = _float(p.get("volume_mm3"))
        s = _float(p.get("surface_km2"))
        if c is not None and v is not None and s is not None:
            clean.append({"cote_ngm": c, "volume_mm3": v, "surface_km2": s})

    if not clean:
        raise ValueError("Le barème ne contient pas de points complets cote/volume/surface.")

    clean.sort(key=lambda x: x["cote_ngm"])
    min_cote = clean[0]["cote_ngm"]
    max_cote = clean[-1]["cote_ngm"]

    if cote < min_cote or cote > max_cote:
        raise ValueError(
            f"Cote {cote} hors barème. Intervalle disponible : {min_cote} à {max_cote}."
        )

    for p in clean:
        if abs(p["cote_ngm"] - cote) < 1e-9:
            return {
                "cote_7h_ngm": cote,
                "volume_mm3": p["volume_mm3"],
                "surface_km2": p["surface_km2"],
                "method": "exact",
                "borne_inf": p,
                "borne_sup": p,
            }

    for lower, upper in zip(clean, clean[1:]):
        if lower["cote_ngm"] <= cote <= upper["cote_ngm"]:
            span = upper["cote_ngm"] - lower["cote_ngm"]
            if abs(span) < 1e-12:
                raise ValueError("Deux points de barème ont la même cote.")
            ratio = (cote - lower["cote_ngm"]) / span
            volume = lower["volume_mm3"] + ratio * (upper["volume_mm3"] - lower["volume_mm3"])
            surface = lower["surface_km2"] + ratio * (upper["surface_km2"] - lower["surface_km2"])
            return {
                "cote_7h_ngm": cote,
                "volume_mm3": volume,
                "surface_km2": surface,
                "method": "interpolation_lineaire",
                "borne_inf": lower,
                "borne_sup": upper,
            }

    raise ValueError("Impossible d'interpoler la cote dans le barème.")


def initialize_initial_bilan(db: Session, code: str, payload: InitialBilanRequest) -> dict:
    code = normalize_code(code)
    barrage = get_admin_barrage(db, code)
    if not barrage:
        raise ValueError(f"Barrage introuvable : {code}")

    barrage_id = int(barrage["id"])
    points = _fetch_default_bareme_points(db, barrage_id)
    lookup = _interpolate_from_bareme(points, float(payload.cote_7h_ngm))

    capacite = _float(barrage.get("capacite_normale_mm3"))
    taux = None
    if capacite and capacite > 0:
        taux = min((lookup["volume_mm3"] / capacite) * 100, 100)

    existing = db.execute(text("""
        SELECT id
        FROM public.bilans_journaliers
        WHERE barrage_id = :barrage_id
          AND date_bilan = :date_bilan
        ORDER BY id
        LIMIT 1;
    """), {"barrage_id": barrage_id, "date_bilan": payload.date_bilan}).mappings().first()

    params = {
        "barrage_id": barrage_id,
        "date_bilan": payload.date_bilan,
        "cote_7h_ngm": lookup["cote_7h_ngm"],
        "volume_mm3": lookup["volume_mm3"],
        "surface_km2": lookup["surface_km2"],
        "taux_remplissage": taux,
        "statut": payload.statut,
        "source_fichier": "PLATEFORME",
        "source_feuille": "INITIALISATION_NOUVEAU_BARRAGE",
        "observation": payload.observation,
    }

    if existing:
        db.execute(text("""
            UPDATE public.bilans_journaliers
            SET
                cote_7h_ngm = :cote_7h_ngm,
                volume_mm3 = :volume_mm3,
                surface_km2 = :surface_km2,
                taux_remplissage = :taux_remplissage,
                statut = :statut,
                source_fichier = :source_fichier,
                source_feuille = :source_feuille,
                observation = :observation
            WHERE id = :id;
        """), {**params, "id": int(existing["id"])})
        action = "updated"
        bilan_id = int(existing["id"])
    else:
        row = db.execute(text("""
            INSERT INTO public.bilans_journaliers (
                barrage_id,
                date_bilan,
                cote_7h_ngm,
                volume_mm3,
                surface_km2,
                taux_remplissage,
                statut,
                source_fichier,
                source_feuille,
                observation
            )
            VALUES (
                :barrage_id,
                :date_bilan,
                :cote_7h_ngm,
                :volume_mm3,
                :surface_km2,
                :taux_remplissage,
                :statut,
                :source_fichier,
                :source_feuille,
                :observation
            )
            RETURNING id;
        """), params).mappings().first()
        action = "created"
        bilan_id = int(row["id"])

    db.commit()

    return {
        "status": "ok",
        "message": "Premier bilan initialisé avec succès.",
        "action": action,
        "barrage_code": code,
        "bilan_id": bilan_id,
        "date_bilan": payload.date_bilan.isoformat(),
        "cote_7h_ngm": lookup["cote_7h_ngm"],
        "volume_mm3": lookup["volume_mm3"],
        "surface_km2": lookup["surface_km2"],
        "taux_remplissage": taux,
        "lookup_method": lookup["method"],
        "borne_inf": lookup["borne_inf"],
        "borne_sup": lookup["borne_sup"],
        "readiness": get_barrage_readiness(db, code),
    }


def get_barrage_readiness(db: Session, code: str) -> dict:
    code = normalize_code(code)
    barrage = get_admin_barrage(db, code)
    if not barrage:
        raise ValueError(f"Barrage introuvable : {code}")
    barrage_id = int(barrage["id"])

    nb_restitutions = int(db.execute(text("""
        SELECT COUNT(*)
        FROM public.barrage_types_restitution
        WHERE barrage_id = :barrage_id AND COALESCE(actif, TRUE) = TRUE;
    """), {"barrage_id": barrage_id}).scalar() or 0)

    nb_bareme_points = int(db.execute(text("""
        SELECT COUNT(bp.id)
        FROM public.bareme_versions bv
        JOIN public.bareme_points bp ON bp.bareme_version_id = bv.id
        WHERE bv.barrage_id = :barrage_id
          AND COALESCE(bv.actif, TRUE) = TRUE
          AND COALESCE(bv.is_default, FALSE) = TRUE;
    """), {"barrage_id": barrage_id}).scalar() or 0)

    bilan_row = db.execute(text("""
        SELECT COUNT(*) AS nb_bilans, MAX(date_bilan) AS dernier_bilan
        FROM public.bilans_journaliers
        WHERE barrage_id = :barrage_id;
    """), {"barrage_id": barrage_id}).mappings().first()

    nb_bilans = int(bilan_row["nb_bilans"] or 0)
    dernier_bilan = bilan_row["dernier_bilan"].isoformat() if bilan_row and bilan_row["dernier_bilan"] else None

    general_info_ok = bool(
        barrage.get("nom")
        and barrage.get("capacite_normale_mm3") is not None
        and barrage.get("cote_normale_ngm") is not None
    )
    restitutions_ok = nb_restitutions > 0
    bareme_ok = nb_bareme_points > 0
    initial_bilan_ok = nb_bilans > 0

    ready_calculs = general_info_ok and restitutions_ok and bareme_ok and bool(barrage.get("actif")) and bool(barrage.get("inclure_calculs"))
    ready_operationnel = ready_calculs and initial_bilan_ok

    return {
        "status": "ok",
        "barrage_code": code,
        "general_info_ok": general_info_ok,
        "restitutions_ok": restitutions_ok,
        "bareme_ok": bareme_ok,
        "initial_bilan_ok": initial_bilan_ok,
        "ready_calculs": ready_calculs,
        "ready_operationnel": ready_operationnel,
        "ready_annonce": ready_calculs and bool(barrage.get("inclure_annonce")),
        "ready_bilan": ready_calculs and bool(barrage.get("inclure_bilan")),
        "ready_situation": ready_calculs and bool(barrage.get("inclure_situation")),
        "nb_restitutions": nb_restitutions,
        "nb_bareme_points_default": nb_bareme_points,
        "nb_bilans": nb_bilans,
        "dernier_bilan": dernier_bilan,
        "notes": [
            *([] if general_info_ok else ["Informations hydrauliques incomplètes : capacité normale et cote normale sont nécessaires."]),
            *([] if restitutions_ok else ["Aucune restitution associée au barrage."]),
            *([] if bareme_ok else ["Aucun point de barème par défaut : importer cote/volume/surface."]),
            *([] if initial_bilan_ok else ["Aucun premier bilan journalier : initialiser une date et une cote de départ."]),
            "Pour calculer une journée, il faut une cote du jour précédent dans bilans_journaliers.",
            "Pour l'export BILAN Excel, un modèle/mapping dédié peut être nécessaire si le barrage est nouveau.",
        ],
    }
