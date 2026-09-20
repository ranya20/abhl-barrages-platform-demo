
from __future__ import annotations

import datetime as dt
import difflib
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.assistant_data.answer_generator import build_chart, build_columns, deterministic_answer
from app.modules.assistant_data.utils import normalize, row_to_dict, jsonable


def _parse_date(question: str) -> dt.date | None:
    q = question or ""
    # format JJ/MM/AAAA, JJ-MM-AAAA, JJ.MM.AAAA
    for day, month, year in re.findall(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b", q):
        try:
            return dt.date(int(year), int(month), int(day))
        except ValueError:
            pass

    # format AAAA-MM-JJ
    for year, month, day in re.findall(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", q):
        try:
            return dt.date(int(year), int(month), int(day))
        except ValueError:
            pass

    return None


def _read_barrages(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT id, code, nom, COALESCE(nom_court, nom) AS nom_court
            FROM public.barrages
            WHERE COALESCE(actif, TRUE) = TRUE
            ORDER BY COALESCE(ordre_situation, ordre_affichage, 9999), code
            """
        )
    ).mappings().all()
    return [row_to_dict(row) for row in rows]


def _resolve_one_barrage(db: Session, text_value: str) -> dict[str, Any] | None:
    target = normalize(text_value)
    if not target:
        return None

    best: tuple[float, dict[str, Any] | None] = (0.0, None)

    for barrage in _read_barrages(db):
        aliases = [
            str(barrage.get("code") or ""),
            str(barrage.get("nom") or ""),
            str(barrage.get("nom_court") or ""),
        ]
        aliases += [alias.replace("Barrage", "").replace("barrage", "").strip() for alias in aliases]

        for alias in aliases:
            alias_norm = normalize(alias)
            if not alias_norm:
                continue

            score = 0.0
            if alias_norm in target or target in alias_norm:
                score = 100 + min(len(alias_norm), len(target))
            else:
                alias_tokens = [tok for tok in alias_norm.split() if len(tok) >= 2]
                if alias_tokens and all(tok in target for tok in alias_tokens):
                    score = 80 + len(alias_tokens)
                else:
                    score = difflib.SequenceMatcher(None, alias_norm, target).ratio() * 60

            if score > best[0]:
                best = (score, barrage)

    return best[1] if best[0] >= 45 else None


def _resolve_barrage_from_question(db: Session, question: str) -> dict[str, Any] | None:
    q_norm = normalize(question)
    best: tuple[float, dict[str, Any] | None] = (0.0, None)

    for barrage in _read_barrages(db):
        aliases = [
            str(barrage.get("code") or ""),
            str(barrage.get("nom") or ""),
            str(barrage.get("nom_court") or ""),
        ]
        aliases += [alias.replace("Barrage", "").replace("barrage", "").strip() for alias in aliases]

        for alias in aliases:
            alias_norm = normalize(alias)
            if not alias_norm:
                continue

            score = 0.0
            if alias_norm in q_norm:
                score = 100 + len(alias_norm)
            else:
                alias_tokens = [tok for tok in alias_norm.split() if len(tok) >= 2]
                if alias_tokens and all(tok in q_norm for tok in alias_tokens):
                    score = 80 + len(alias_tokens)
                else:
                    score = difflib.SequenceMatcher(None, alias_norm, q_norm).ratio() * 50

            if score > best[0]:
                best = (score, barrage)

    return best[1] if best[0] >= 45 else None


def _answer_payload(
    *,
    answer: str,
    explanation: str,
    rows: list[dict[str, Any]],
    sql: str,
    params: dict[str, Any] | None = None,
    chart_type: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": "business_shortcut_readonly",
        "llm": {"attempted": False, "used": False, "error": None},
        "answer": answer,
        "explanation": explanation,
        "columns": build_columns(rows),
        "rows": rows,
        "chart": build_chart(rows, preferred_type=chart_type),
        "sql_used": sql,
        "sql_params": {key: jsonable(value) for key, value in (params or {}).items()},
        "safety": {
            "read_only": True,
            "select_only": True,
            "business_shortcut": True,
            "reason": "irrigation/transfert métier fiabilisé sans appel LLM",
        },
    }


def _format_number(value: Any, digits: int = 3) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    return str(value)


def _try_irrigation(db: Session, question: str) -> dict[str, Any] | None:
    q_norm = normalize(question)
    if "irrig" not in q_norm:
        return None

    date_value = _parse_date(question)
    barrage = _resolve_barrage_from_question(db, question)

    if not date_value or not barrage:
        return None

    # ------------------------------------------------------------------
    # RÈGLE MÉTIER SPÉCIALE DAR KHROFA
    # ------------------------------------------------------------------
    # Dans le fichier Excel Dar Khrofa, la colonne Utilisation / Irrigation
    # n'est pas une ligne de restitution à additionner avec les prises agricoles.
    # Sa formule est : Irrigation = Prise Agricole RD + Prise Agricole RG - AEPI Tanger.
    # Exemple : 09/03/2026 => 0 + 52 541 - 0 = 52 541 m³.
    # L'ancien fallback comptait parfois 52 541 deux fois, ce qui donnait 105 082.
    # ------------------------------------------------------------------
    if str(barrage.get("code")) == "DAR_KHROFA":
        sql = """
WITH bj0 AS (
    SELECT
        bj.id AS bilan_id,
        bj.date_bilan,
        b.code AS barrage_code,
        COALESCE(b.nom_court, b.nom) AS barrage
    FROM public.bilans_journaliers bj
    JOIN public.barrages b ON b.id = bj.barrage_id
    WHERE b.code = 'DAR_KHROFA'
      AND bj.date_bilan = :date_bilan
), details AS (
    SELECT
        bj0.date_bilan,
        bj0.barrage_code,
        bj0.barrage,
        UPPER(COALESCE(tr.code, '')) AS tr_code,
        LOWER(COALESCE(tr.libelle, '')) AS tr_libelle,
        COALESCE(rj.valeur_m3, 0) AS valeur_m3
    FROM bj0
    LEFT JOIN public.restitutions_journalieres rj ON rj.bilan_journalier_id = bj0.bilan_id
    LEFT JOIN public.types_restitution tr ON tr.id = rj.type_restitution_id
)
SELECT
    date_bilan AS date,
    barrage_code,
    barrage,
    COALESCE(SUM(CASE
        WHEN tr_code IN ('PRISE_AGRICOLE_RD', 'PRISE_AGRICOLE_RD_M3', 'PRISE_AGRI_RD')
          OR (tr_libelle LIKE '%prise%' AND tr_libelle LIKE '%agricole%' AND tr_libelle LIKE '%rd%')
          OR (tr_libelle LIKE '%prise%' AND tr_libelle LIKE '%agricole%' AND tr_libelle LIKE '%droite%')
        THEN valeur_m3
        ELSE 0
    END), 0) AS prise_agricole_rd_m3,
    COALESCE(SUM(CASE
        WHEN tr_code IN ('PRISE_AGRICOLE_RG', 'PRISE_AGRICOLE_RG_M3', 'PRISE_AGRI_RG')
          OR (tr_libelle LIKE '%prise%' AND tr_libelle LIKE '%agricole%' AND tr_libelle LIKE '%rg%')
          OR (tr_libelle LIKE '%prise%' AND tr_libelle LIKE '%agricole%' AND tr_libelle LIKE '%gauche%')
        THEN valeur_m3
        ELSE 0
    END), 0) AS prise_agricole_rg_m3,
    COALESCE(SUM(CASE
        WHEN tr_code IN ('AEPI_TANGER', 'AEPI_TANGER_M3', 'AEPI_TNG')
          OR (tr_libelle LIKE '%aepi%' AND tr_libelle LIKE '%tanger%')
        THEN valeur_m3
        ELSE 0
    END), 0) AS aepi_tanger_m3,
    (
        COALESCE(SUM(CASE
            WHEN tr_code IN ('PRISE_AGRICOLE_RD', 'PRISE_AGRICOLE_RD_M3', 'PRISE_AGRI_RD')
              OR (tr_libelle LIKE '%prise%' AND tr_libelle LIKE '%agricole%' AND tr_libelle LIKE '%rd%')
              OR (tr_libelle LIKE '%prise%' AND tr_libelle LIKE '%agricole%' AND tr_libelle LIKE '%droite%')
            THEN valeur_m3
            ELSE 0
        END), 0)
        +
        COALESCE(SUM(CASE
            WHEN tr_code IN ('PRISE_AGRICOLE_RG', 'PRISE_AGRICOLE_RG_M3', 'PRISE_AGRI_RG')
              OR (tr_libelle LIKE '%prise%' AND tr_libelle LIKE '%agricole%' AND tr_libelle LIKE '%rg%')
              OR (tr_libelle LIKE '%prise%' AND tr_libelle LIKE '%agricole%' AND tr_libelle LIKE '%gauche%')
            THEN valeur_m3
            ELSE 0
        END), 0)
        -
        COALESCE(SUM(CASE
            WHEN tr_code IN ('AEPI_TANGER', 'AEPI_TANGER_M3', 'AEPI_TNG')
              OR (tr_libelle LIKE '%aepi%' AND tr_libelle LIKE '%tanger%')
            THEN valeur_m3
            ELSE 0
        END), 0)
    ) AS irrigation_m3
FROM details
GROUP BY date_bilan, barrage_code, barrage
LIMIT 500
"""
        params = {"date_bilan": date_value}
        rows = [row_to_dict(row) for row in db.execute(text(sql), params).mappings().all()]
        db.rollback()

        if not rows:
            return _answer_payload(
                answer="Aucune donnée d'irrigation n’a été trouvée pour Dar Khrofa à cette date.",
                explanation="Règle métier Dar Khrofa : irrigation = Prise Agricole RD + Prise Agricole RG - AEPI Tanger.",
                rows=[],
                sql=sql,
                params=params,
            )

        value = rows[0].get("irrigation_m3")
        answer = (
            f"L’irrigation de {rows[0].get('barrage')} le {rows[0].get('date')} est de "
            f"{_format_number(value, 3)} m³. Source : PostgreSQL."
        )
        explanation = (
            "Règle métier spéciale Dar Khrofa appliquée : irrigation = "
            "Prise Agricole RD + Prise Agricole RG - AEPI Tanger. "
            "Cette règle évite le double comptage entre les prises agricoles et la colonne Utilisation/Irrigation."
        )
        return _answer_payload(answer=answer, explanation=explanation, rows=rows, sql=sql, params=params, chart_type="bar")

    # ------------------------------------------------------------------
    # AUTRES BARRAGES : on conserve l'ancien comportement.
    # L'irrigation est lue dans les types de restitution/utilisation stockés.
    # ------------------------------------------------------------------
    sql = """
WITH bj0 AS (
    SELECT
        bj.id AS bilan_id,
        bj.date_bilan,
        b.code AS barrage_code,
        COALESCE(b.nom_court, b.nom) AS barrage
    FROM public.bilans_journaliers bj
    JOIN public.barrages b ON b.id = bj.barrage_id
    WHERE b.code = :barrage_code
      AND bj.date_bilan = :date_bilan
)
SELECT
    bj0.date_bilan AS date,
    bj0.barrage_code,
    bj0.barrage,
    COALESCE(SUM(CASE
        WHEN UPPER(COALESCE(tr.code, '')) LIKE '%IRRIG%'
          OR LOWER(COALESCE(tr.libelle, '')) LIKE '%irrig%'
          OR UPPER(COALESCE(tr.code, '')) IN ('PRISE_AGRICOLE_RD', 'PRISE_AGRICOLE_RG')
          OR LOWER(COALESCE(tr.libelle, '')) LIKE '%agricole%'
        THEN rj.valeur_m3
        ELSE 0
    END), 0) AS irrigation_m3
FROM bj0
LEFT JOIN public.restitutions_journalieres rj ON rj.bilan_journalier_id = bj0.bilan_id
LEFT JOIN public.types_restitution tr ON tr.id = rj.type_restitution_id
GROUP BY bj0.date_bilan, bj0.barrage_code, bj0.barrage
LIMIT 500
"""
    params = {"barrage_code": barrage["code"], "date_bilan": date_value}
    rows = [row_to_dict(row) for row in db.execute(text(sql), params).mappings().all()]
    db.rollback()

    if not rows:
        return _answer_payload(
            answer="Aucune donnée d'irrigation n’a été trouvée pour cette date et ce barrage.",
            explanation="Recherche métier irrigation dans les types de restitution/utilisation stockés.",
            rows=[],
            sql=sql,
            params=params,
        )

    value = rows[0].get("irrigation_m3")
    answer = (
        f"L’irrigation de {rows[0].get('barrage')} le {rows[0].get('date')} est de "
        f"{_format_number(value, 3)} m³. Source : PostgreSQL."
    )
    explanation = "Règle métier appliquée : irrigation lue depuis les types de restitution/utilisation stockés pour ce barrage."

    return _answer_payload(answer=answer, explanation=explanation, rows=rows, sql=sql, params=params, chart_type="bar")


def _extract_transfer_direction(db: Session, question: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    q_norm = normalize(question)

    source = None
    dest = None

    # Cas explicite : depuis X vers Y
    match = re.search(r"depuis\s+(.+?)\s+vers\s+(.+?)(?:\s+le\s+|\s+en\s+|\s+du\s+|\?|$)", question, flags=re.IGNORECASE)
    if match:
        source = _resolve_one_barrage(db, match.group(1))
        dest = _resolve_one_barrage(db, match.group(2))
        return source, dest

    # Cas : de X vers Y
    match = re.search(r"\bde\s+(.+?)\s+vers\s+(.+?)(?:\s+le\s+|\s+en\s+|\s+du\s+|\?|$)", question, flags=re.IGNORECASE)
    if match:
        source = _resolve_one_barrage(db, match.group(1))
        dest = _resolve_one_barrage(db, match.group(2))
        return source, dest

    # Si l'utilisateur demande juste transfert de/vers Dar Khrofa, prendre le barrage détecté comme concerné.
    detected = _resolve_barrage_from_question(db, question)
    if detected:
        if " vers " in q_norm or " a " in q_norm or " à " in question.lower():
            dest = detected
        else:
            dest = detected

    return source, dest


def _try_transfer(db: Session, question: str) -> dict[str, Any] | None:
    q_norm = normalize(question)
    if "transfert" not in q_norm:
        return None

    date_value = _parse_date(question)
    if not date_value:
        return None

    source, dest = _extract_transfer_direction(db, question)

    # Si la destination n'est pas explicite, tenter le barrage dans la question.
    if not dest:
        dest = _resolve_barrage_from_question(db, question)

    if not source and not dest:
        return None

    # 1) Essai table transferts_journaliers si elle contient le transfert directionnel.
    sql_direct = """
SELECT
    tj.date_bilan AS date,
    s.code AS source_code,
    COALESCE(s.nom_court, s.nom) AS source_barrage,
    d.code AS destination_code,
    COALESCE(d.nom_court, d.nom) AS destination_barrage,
    tj.valeur_m3 AS transfert_m3,
    'transferts_journaliers' AS source_table
FROM public.transferts_journaliers tj
JOIN public.barrages s ON s.id = tj.barrage_source_id
JOIN public.barrages d ON d.id = tj.barrage_destination_id
WHERE tj.date_bilan = :date_bilan
  AND (:source_code IS NULL OR s.code = :source_code)
  AND (:dest_code IS NULL OR d.code = :dest_code)
ORDER BY tj.valeur_m3 DESC NULLS LAST
LIMIT 500
"""
    params_direct = {
        "date_bilan": date_value,
        "source_code": source["code"] if source else None,
        "dest_code": dest["code"] if dest else None,
    }

    rows = []
    try:
        rows = [row_to_dict(row) for row in db.execute(text(sql_direct), params_direct).mappings().all()]
        db.rollback()
    except Exception:
        db.rollback()
        rows = []

    if rows:
        value = sum(float(row.get("transfert_m3") or 0) for row in rows)
        if source and dest:
            answer = (
                f"Le transfert depuis {source.get('nom_court') or source.get('nom')} vers {dest.get('nom_court') or dest.get('nom')} "
                f"le {date_value.isoformat()} est de {_format_number(value, 3)} m³. Source : PostgreSQL."
            )
        else:
            answer = f"Le transfert trouvé le {date_value.isoformat()} est de {_format_number(value, 3)} m³. Source : PostgreSQL."

        return _answer_payload(
            answer=answer,
            explanation="Recherche d'abord dans transferts_journaliers avec source/destination.",
            rows=rows,
            sql=sql_direct,
            params=params_direct,
            chart_type="bar",
        )

    # 2) Fallback métier Dar Khrofa : dans les fichiers, le transfert depuis Oued El Makhazine est stocké comme type restitution TRANSFERT_DAR_KHROFA.
    if dest and str(dest.get("code")) == "DAR_KHROFA":
        sql_fallback = """
WITH bj0 AS (
    SELECT
        bj.id AS bilan_id,
        bj.date_bilan,
        b.code AS destination_code,
        COALESCE(b.nom_court, b.nom) AS destination_barrage
    FROM public.bilans_journaliers bj
    JOIN public.barrages b ON b.id = bj.barrage_id
    WHERE b.code = 'DAR_KHROFA'
      AND bj.date_bilan = :date_bilan
)
SELECT
    bj0.date_bilan AS date,
    'BOEM' AS source_code,
    'Oued El Makhazine' AS source_barrage,
    bj0.destination_code,
    bj0.destination_barrage,
    COALESCE(SUM(CASE
        WHEN UPPER(COALESCE(tr.code, '')) IN ('TRANSFERT_DAR_KHROFA', 'TRANSFERT_DAR_KHROFA_M3')
          OR LOWER(COALESCE(tr.libelle, '')) LIKE '%transfert%dar khrofa%'
        THEN rj.valeur_m3
        ELSE 0
    END), 0) AS transfert_m3,
    'restitutions_journalieres/types_restitution' AS source_table
FROM bj0
LEFT JOIN public.restitutions_journalieres rj ON rj.bilan_journalier_id = bj0.bilan_id
LEFT JOIN public.types_restitution tr ON tr.id = rj.type_restitution_id
GROUP BY bj0.date_bilan, bj0.destination_code, bj0.destination_barrage
LIMIT 500
"""
        params_fb = {"date_bilan": date_value}
        rows = [row_to_dict(row) for row in db.execute(text(sql_fallback), params_fb).mappings().all()]
        db.rollback()

        if rows:
            value = rows[0].get("transfert_m3")
            answer = (
                f"Le transfert depuis Oued El Makhazine vers Dar Khrofa le {rows[0].get('date')} est de "
                f"{_format_number(value, 3)} m³. Source : PostgreSQL."
            )
            explanation = (
                "Aucun transfert direct n'a été trouvé dans transferts_journaliers. "
                "Fallback métier utilisé : type de restitution TRANSFERT_DAR_KHROFA lié au bilan journalier de Dar Khrofa."
            )
            return _answer_payload(answer=answer, explanation=explanation, rows=rows, sql=sql_fallback, params=params_fb, chart_type="bar")

    # 3) Rien trouvé : répondre proprement, sans réparer via LLM.
    answer = "Aucune donnée de transfert n’a été trouvée dans PostgreSQL pour cette question."
    explanation = (
        "Recherche effectuée dans transferts_journaliers avec source/destination. "
        "Pour Dar Khrofa, le fallback TRANSFERT_DAR_KHROFA est utilisé seulement si la destination Dar Khrofa est détectée."
    )
    return _answer_payload(answer=answer, explanation=explanation, rows=[], sql=sql_direct, params=params_direct)


def try_business_shortcut(db: Session, question: str) -> dict[str, Any] | None:
    """Traite les cas métier connus où le LLM confond souvent les notions.

    Cette fonction est appelée AVANT OpenRouter. Elle permet aussi de répondre si le quota LLM est atteint.
    """
    q_norm = normalize(question)

    if "irrig" in q_norm:
        return _try_irrigation(db, question)

    if "transfert" in q_norm:
        return _try_transfer(db, question)

    return None
