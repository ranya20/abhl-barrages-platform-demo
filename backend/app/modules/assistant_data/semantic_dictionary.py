from __future__ import annotations

from typing import Any


# Dictionnaire métier central.
# Le LLM peut comprendre les synonymes, mais le SQL doit utiliser ces codes officiels.
METRICS: dict[str, dict[str, Any]] = {
    "volume": {
        "label": "Volume / réserve",
        "unit": "Mm³",
        "digits": 3,
        "expression": "bj.volume_mm3",
        "table": "bilans_journaliers",
        "column": "volume_mm3",
        "default_aggregation": "avg",
        "synonyms": ["volume", "reserve", "réserve", "stock", "retenue", "eau stockee", "eau stockée"],
        "description": "Volume d'eau stocké dans la retenue, exprimé en Mm³.",
    },
    "taux_remplissage": {
        "label": "Taux de remplissage",
        "unit": "%",
        "digits": 1,
        "expression": "bj.taux_remplissage",
        "table": "bilans_journaliers",
        "column": "taux_remplissage",
        "default_aggregation": "avg",
        "synonyms": ["taux", "taux remplissage", "remplissage", "pourcentage", "%"],
        "description": "Taux de remplissage du barrage en pourcentage.",
    },
    "cote_7h": {
        "label": "Cote à 7h",
        "unit": "mNGM",
        "digits": 2,
        "expression": "bj.cote_7h_ngm",
        "table": "bilans_journaliers",
        "column": "cote_7h_ngm",
        "default_aggregation": "avg",
        "synonyms": ["cote", "côte", "niveau", "niveau eau", "niveau d eau", "ngm", "cote 7h"],
        "description": "Cote ou niveau du plan d'eau à 7h, exprimé en mNGM.",
    },
    "hauteur_bac": {
        "label": "Hauteur Bac",
        "unit": "mm",
        "digits": 2,
        "expression": "bj.hauteur_bac_mm",
        "table": "bilans_journaliers",
        "column": "hauteur_bac_mm",
        "default_aggregation": "avg",
        "synonyms": ["hauteur bac", "hateur bac", "hauter bac", "hauteur du bac", "bac", "hauteur evaporation", "hauteur évaporation"],
        "description": "Hauteur Bac mesurée, exprimée en millimètres.",
    },
    "pluie": {
        "label": "Pluie",
        "unit": "mm",
        "digits": 1,
        "expression": "bj.pluie_mm",
        "table": "bilans_journaliers",
        "column": "pluie_mm",
        "default_aggregation": "avg",
        "synonyms": ["pluie", "pluviometrie", "pluviométrie", "precipitation", "précipitation", "averse"],
        "description": "Pluie du jour, exprimée en millimètres.",
    },
    "surface": {
        "label": "Surface",
        "unit": "km²",
        "digits": 3,
        "expression": "bj.surface_km2",
        "table": "bilans_journaliers",
        "column": "surface_km2",
        "default_aggregation": "avg",
        "synonyms": ["surface", "surface eau", "surface plan eau", "plan d eau", "plan d'eau"],
        "description": "Surface du plan d'eau du barrage, exprimée en km².",
    },
    "surface_moyenne": {
        "label": "Surface moyenne",
        "unit": "km²",
        "digits": 3,
        "expression": "bj.surface_moyenne_km2",
        "table": "bilans_journaliers",
        "column": "surface_moyenne_km2",
        "default_aggregation": "avg",
        "synonyms": ["surface moyenne", "surface moyenne eau"],
        "description": "Surface moyenne utilisée dans certains calculs.",
    },
    "volume_jour_suivant": {
        "label": "Volume jour suivant",
        "unit": "Mm³",
        "digits": 3,
        "expression": "bj.volume_jour_suivant_mm3",
        "table": "bilans_journaliers",
        "column": "volume_jour_suivant_mm3",
        "default_aggregation": "avg",
        "synonyms": ["volume jour suivant", "volume suivant", "reserve suivante", "réserve suivante"],
        "description": "Volume du jour suivant, utilisé pour les calculs hydrauliques.",
    },
    "variation_reserve": {
        "label": "Variation de réserve",
        "unit": "Mm³",
        "digits": 3,
        "expression": "bj.variation_reserve_mm3",
        "table": "bilans_journaliers",
        "column": "variation_reserve_mm3",
        "default_aggregation": "sum",
        "synonyms": ["variation", "variation reserve", "variation réserve", "difference reserve", "différence réserve"],
        "description": "Variation de la réserve entre deux jours.",
    },
    "evaporation": {
        "label": "Évaporation",
        "unit": "m³",
        "digits": 0,
        "expression": "bj.evaporation_m3",
        "table": "bilans_journaliers",
        "column": "evaporation_m3",
        "default_aggregation": "sum",
        "synonyms": ["evaporation", "évaporation", "evapore", "évaporé", "perte evaporation"],
        "description": "Volume évaporé, exprimé en m³.",
    },
    "restitutions": {
        "label": "Restitutions",
        "unit": "m³",
        "digits": 0,
        "expression": "bj.total_restitutions_m3",
        "table": "bilans_journaliers",
        "column": "total_restitutions_m3",
        "default_aggregation": "sum",
        "synonyms": ["restitution", "restitutions", "lacher", "lâcher", "lachers", "lâchers", "sorties", "eau sortie"],
        "description": "Total des restitutions/lâchers/sorties, exprimé en m³.",
    },
    "apports": {
        "label": "Apports",
        "unit": "m³",
        "digits": 0,
        "expression": "bj.apports_m3",
        "table": "bilans_journaliers",
        "column": "apports_m3",
        "default_aggregation": "sum",
        "synonyms": ["apport", "apports", "entree", "entrée", "entrees", "entrées", "eau entrante"],
        "description": "Apports/entrées d'eau, exprimés en m³.",
    },
    "debit": {
        "label": "Débit moyen",
        "unit": "m³/s",
        "digits": 3,
        "expression": "bj.debit_m3s",
        "table": "bilans_journaliers",
        "column": "debit_m3s",
        "default_aggregation": "avg",
        "synonyms": ["debit", "débit", "debit moyen", "débit moyen", "m3/s"],
        "description": "Débit moyen calculé, exprimé en m³/s.",
    },
    "capacite": {
        "label": "Capacité normale",
        "unit": "Mm³",
        "digits": 3,
        "expression": "b.capacite_normale_mm3",
        "table": "barrages",
        "column": "capacite_normale_mm3",
        "default_aggregation": "avg",
        "synonyms": ["capacite", "capacité", "capacite normale", "capacité normale", "volume normal"],
        "description": "Capacité normale du barrage, exprimée en Mm³.",
    },
    "cote_normale": {
        "label": "Cote normale",
        "unit": "mNGM",
        "digits": 2,
        "expression": "b.cote_normale_ngm",
        "table": "barrages",
        "column": "cote_normale_ngm",
        "default_aggregation": "avg",
        "synonyms": ["cote normale", "côte normale", "niveau normal"],
        "description": "Cote normale du barrage.",
    },
    "transfert": {
        "label": "Transfert",
        "unit": "m³",
        "digits": 0,
        "expression": "tj.valeur_m3",
        "table": "transferts_journaliers",
        "column": "valeur_m3",
        "default_aggregation": "sum",
        "synonyms": ["transfert", "transferts", "transfert dar khrofa", "transfert dar khroufa"],
        "description": "Volumes transférés entre barrages, exprimés en m³.",
    },
}


AGGREGATIONS = {
    "none": "valeur brute sans agrégation",
    "sum": "somme / total / cumul",
    "avg": "moyenne",
    "min": "minimum",
    "max": "maximum",
    "count": "nombre de lignes",
}


INTENTS = {
    "point": "valeur simple pour une date ou une ligne précise",
    "series": "évolution temporelle sur une période",
    "aggregate": "moyenne, somme, minimum, maximum, cumul",
    "compare": "comparaison entre deux dates, deux périodes, deux barrages ou deux variables",
    "ranking": "classement top/bottom",
    "threshold": "filtre selon un seuil, ex: taux inférieur à 50%",
    "table": "tableau détaillé",
    "explain": "explication basée sur les données existantes",
}


def compact_metric_catalog() -> list[dict[str, Any]]:
    return [
        {
            "metric_code": code,
            "label": meta["label"],
            "unit": meta["unit"],
            "table": meta["table"],
            "column": meta["column"],
            "sql_expression": meta["expression"],
            "default_aggregation": meta["default_aggregation"],
            "synonyms": meta["synonyms"],
            "description": meta["description"],
        }
        for code, meta in METRICS.items()
    ]


def metric_columns() -> set[str]:
    return {str(meta["column"]) for meta in METRICS.values()}
