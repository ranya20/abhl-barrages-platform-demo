from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.assistant_data.semantic_dictionary import compact_metric_catalog
from app.modules.assistant_data.utils import row_to_dict


SENSITIVE_TABLES = {
    "users",
    "roles",
    "auth_sessions",
    "auth_audit_log",
    "data_import_batches",
    "data_import_rows",
    "data_import_changes",
    "data_import_events",
    "import_batches",
    "import_errors",
}


IMPORTANT_TABLES = [
    "barrages",
    "agences_territoriales",
    "bassins",
    "provinces",
    "journees_situation",
    "bilans_journaliers",
    "restitutions_journalieres",
    "types_restitution",
    "transferts_journaliers",
    "bareme_versions",
    "bareme_points",
]


def table_exists(db: Session, table_name: str) -> bool:
    return bool(db.execute(text("SELECT to_regclass(:name)"), {"name": f"public.{table_name}"}).scalar())


def read_schema(db: Session) -> dict[str, list[dict[str, Any]]]:
    rows = db.execute(
        text(
            """
            SELECT table_name, column_name, data_type, is_nullable, ordinal_position
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
            """
        )
    ).mappings().all()

    schema: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        table_name = str(row["table_name"])

        if table_name in SENSITIVE_TABLES:
            continue

        # Garder tout le public non sensible, mais les tables métier passent en premier dans le prompt.
        schema.setdefault(table_name, []).append(
            {
                "column": row["column_name"],
                "type": row["data_type"],
                "nullable": row["is_nullable"],
                "ordinal": row["ordinal_position"],
            }
        )

    return schema


def read_foreign_keys(db: Session) -> list[dict[str, str]]:
    rows = db.execute(
        text(
            """
            SELECT
                tc.table_name AS source_table,
                kcu.column_name AS source_column,
                ccu.table_name AS target_table,
                ccu.column_name AS target_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
            ORDER BY tc.table_name, kcu.column_name
            """
        )
    ).mappings().all()

    relations = []

    for row in rows:
        if row["source_table"] in SENSITIVE_TABLES or row["target_table"] in SENSITIVE_TABLES:
            continue

        relations.append(
            {
                "source": f"public.{row['source_table']}.{row['source_column']}",
                "target": f"public.{row['target_table']}.{row['target_column']}",
            }
        )

    return relations


def read_barrages(db: Session) -> list[dict[str, Any]]:
    if not table_exists(db, "barrages"):
        return []

    has_agence = table_exists(db, "agences_territoriales")
    agence_join = "LEFT JOIN public.agences_territoriales a ON a.id = b.agence_id" if has_agence else ""
    agence_select = "a.code AS agence_code, a.nom AS agence_nom" if has_agence else "NULL::text AS agence_code, NULL::text AS agence_nom"

    rows = db.execute(
        text(
            f"""
            SELECT
                b.id,
                b.code,
                b.nom,
                COALESCE(b.nom_court, b.nom) AS nom_court,
                b.feuille_annonce,
                b.feuille_djbarrage,
                b.fichier_bm,
                b.capacite_normale_mm3,
                b.cote_normale_ngm,
                {agence_select}
            FROM public.barrages b
            {agence_join}
            WHERE COALESCE(b.actif, TRUE) = TRUE
            ORDER BY COALESCE(b.ordre_situation, b.ordre_affichage, 9999), b.code
            """
        )
    ).mappings().all()

    return [row_to_dict(row) for row in rows]


def read_agences(db: Session) -> list[dict[str, Any]]:
    if not table_exists(db, "agences_territoriales"):
        return []

    rows = db.execute(
        text(
            """
            SELECT code, nom, description
            FROM public.agences_territoriales
            WHERE COALESCE(actif, TRUE) = TRUE
            ORDER BY nom
            """
        )
    ).mappings().all()

    return [row_to_dict(row) for row in rows]


def read_types_restitution(db: Session) -> list[dict[str, Any]]:
    if not table_exists(db, "types_restitution"):
        return []

    rows = db.execute(
        text(
            """
            SELECT code, libelle, unite, description
            FROM public.types_restitution
            WHERE COALESCE(actif, TRUE) = TRUE
            ORDER BY code
            """
        )
    ).mappings().all()

    return [row_to_dict(row) for row in rows]


def read_available_dates(db: Session) -> dict[str, Any]:
    if not table_exists(db, "bilans_journaliers"):
        return {"min": None, "max": None, "count": 0}

    row = db.execute(
        text(
            """
            SELECT
                MIN(date_bilan) AS min_date,
                MAX(date_bilan) AS max_date,
                COUNT(DISTINCT date_bilan) AS count_dates
            FROM public.bilans_journaliers
            """
        )
    ).mappings().first()

    return {
        "min": row_to_dict(row).get("min_date") if row else None,
        "max": row_to_dict(row).get("max_date") if row else None,
        "count": row_to_dict(row).get("count_dates") if row else 0,
    }


def read_catalog(db: Session) -> dict[str, Any]:
    schema = read_schema(db)
    ordered_schema: dict[str, list[dict[str, Any]]] = {}

    for table in IMPORTANT_TABLES:
        if table in schema:
            ordered_schema[table] = schema[table]

    for table, columns in schema.items():
        if table not in ordered_schema:
            ordered_schema[table] = columns

    return {
        "schema": ordered_schema,
        "foreign_keys": read_foreign_keys(db),
        "barrages": read_barrages(db),
        "agences": read_agences(db),
        "types_restitution": read_types_restitution(db),
        "dates": read_available_dates(db),
        "metrics": compact_metric_catalog(),
        "sensitive_tables": sorted(SENSITIVE_TABLES),
    }


def catalog_for_prompt(catalog: dict[str, Any]) -> str:
    parts: list[str] = []

    parts.append("=== PÉRIODE DISPONIBLE ===")
    parts.append(str(catalog.get("dates", {})))

    parts.append("\n=== BARRAGES RÉELS DISPONIBLES ===")
    parts.append(
        "Règle absolue : pour filtrer un barrage, utilise b.code avec une valeur exacte de cette liste. "
        "Ne filtre jamais b.code avec le nom utilisateur brut."
    )
    for barrage in catalog.get("barrages", []):
        parts.append(
            f"- code={barrage.get('code')} | nom={barrage.get('nom')} | nom_court={barrage.get('nom_court')} | "
            f"feuille_annonce={barrage.get('feuille_annonce')} | feuille_djbarrage={barrage.get('feuille_djbarrage')} | "
            f"agence={barrage.get('agence_code')} {barrage.get('agence_nom')}"
        )

    parts.append("\n=== AGENCES ===")
    for agence in catalog.get("agences", []):
        parts.append(f"- code={agence.get('code')} | nom={agence.get('nom')}")

    parts.append("\n=== VARIABLES MÉTIER ===")
    for metric in catalog.get("metrics", []):
        parts.append(
            f"- metric_code={metric['metric_code']} | {metric['label']} | colonne={metric['table']}.{metric['column']} | "
            f"expression={metric['sql_expression']} | unité={metric['unit']} | synonymes={metric['synonyms']}"
        )

    parts.append("\n=== TYPES DE RESTITUTION ===")
    for item in catalog.get("types_restitution", []):
        parts.append(f"- code={item.get('code')} | libelle={item.get('libelle')} | unite={item.get('unite')}")

    parts.append("\n=== SCHÉMA POSTGRESQL PUBLIC AUTORISÉ ===")
    for table, columns in catalog.get("schema", {}).items():
        parts.append(f"TABLE public.{table}")
        for column in columns:
            parts.append(f"  - {column['column']} : {column['type']} nullable={column['nullable']}")

    parts.append("\n=== RELATIONS FOREIGN KEY ===")
    for relation in catalog.get("foreign_keys", []):
        parts.append(f"- {relation['source']} -> {relation['target']}")

    return "\n".join(parts)
