from __future__ import annotations

# Les feuilles réellement présentes dans annonce.xlsx.
# RHISS n'est pas présent dans ce classeur et ne doit donc pas être exporté ici.
TARGET_BARRAGE_CODES = [
    "NAKHLA",
    "SMIR",
    "MHB_MEHDI",
    "CAI",
    "CHEFCHAOUEN",
    "TANGER_MED",
    "BIB",
    "9_AVRIL",
    "KHARROUB",
    "BOEM",
    "DAR_KHROFA",
    "KHATTABI",
    "JOUMOUA",
]

MONTH_NAMES_FR_UPPER = {
    1: "JANVIER",
    2: "FÉVRIER",
    3: "MARS",
    4: "AVRIL",
    5: "MAI",
    6: "JUIN",
    7: "JUILLET",
    8: "AOÛT",
    9: "SEPTEMBRE",
    10: "OCTOBRE",
    11: "NOVEMBRE",
    12: "DÉCEMBRE",
}

# Le modèle possède 32 lignes journalières :
# 31 jours possibles + la cote du premier jour du mois suivant.
DATA_ROW_COUNT = 32

SHEET_CONFIGS = {
    "NAKHLA": {
        "sheet_name": "NAKHLA",
        "data_start_row": 8,
        "total_row": 41,
        "last_column": "L",
        "restitutions": {"AEPI": "G", "VDF": "H", "EVAC": "I", "FUITES": "J"},
        "total_restitutions": "K",
        "apports": "L",
        "specials": {},
    },
    "SMIR": {
        "sheet_name": "SMIR",
        "data_start_row": 8,
        "total_row": 41,
        "last_column": "M",
        "restitutions": {
            "AEPI": "G", "VDF": "H", "BY_PASS": "I", "EVAC": "J", "FUITES": "K"
        },
        "total_restitutions": "L",
        "apports": "M",
        "specials": {},
    },
    "MHB_MEHDI": {
        "sheet_name": "M.H.B.EL MEHDI",
        "data_start_row": 8,
        "total_row": 41,
        "last_column": "M",
        "restitutions": {
            "AEPI": "G", "VDF": "H", "BY_PASS": "I", "EVAC": "J", "FUITES": "K"
        },
        "total_restitutions": "L",
        "apports": "M",
        "specials": {},
    },
    "CAI": {
        "sheet_name": "CHARIF AL IDRISSI",
        "data_start_row": 8,
        "total_row": 41,
        "last_column": "N",
        "restitutions": {
            "AEPI": "G", "IRRIGATION": "H", "VDF": "I", "BY_PASS": "J",
            "EVAC": "K", "FUITES": "L"
        },
        "total_restitutions": "M",
        "apports": "N",
        "specials": {},
    },
    "CHEFCHAOUEN": {
        "sheet_name": "CHEFCHAOUN",
        "data_start_row": 8,
        "total_row": 41,
        "last_column": "N",
        "restitutions": {
            "AEPI": "G", "IRRIGATION": "H", "VDF": "I", "BY_PASS": "J",
            "EVAC": "K", "FUITES": "L"
        },
        "total_restitutions": "M",
        "apports": "N",
        "specials": {},
    },
    "TANGER_MED": {
        "sheet_name": "TANGER-MED",
        "data_start_row": 8,
        "total_row": 41,
        "last_column": "M",
        "restitutions": {
            "AEPI": "G", "VDF": "H", "EVAC": "I", "TMSA": "J", "FUITES": "K"
        },
        "total_restitutions": "L",
        "apports": "M",
        "specials": {},
    },
    "BIB": {
        "sheet_name": "BIB",
        "data_start_row": 8,
        "total_row": 41,
        "last_column": "O",
        "restitutions": {
            "AEPI": "G", "JETS_CREUX": "H", "VDF": "I", "BY_PASS": "J",
            "POMPES_DEVASAGE": "K", "EVAC": "L", "FUITES": "M"
        },
        "total_restitutions": "N",
        "apports": "O",
        "specials": {},
    },
    "9_AVRIL": {
        "sheet_name": "9 AVRIL",
        "data_start_row": 8,
        "total_row": 41,
        "last_column": "M",
        "restitutions": {
            "AEPI": "G", "VDF": "H", "BY_PASS": "I", "EVAC": "J", "FUITES": "K"
        },
        "total_restitutions": "L",
        "apports": "M",
        "specials": {},
    },
    "KHARROUB": {
        "sheet_name": "KHARROUB",
        "data_start_row": 8,
        "total_row": 41,
        "last_column": "M",
        "restitutions": {
            "AEPI": "G", "VDF": "H", "BY_PASS": "I", "EVAC": "J", "FUITES": "K"
        },
        "total_restitutions": "L",
        "apports": "M",
        "specials": {},
    },
    "BOEM": {
        "sheet_name": "BOEM",
        "data_start_row": 9,
        "total_row": 42,
        "last_column": "T",
        "restitutions": {
            "IRRIGATION_LOUKKOS_TURBINAGE": "G",
            "IRRIGATION_LOUKKOS_PRISE_AGRICOLE": "H",
            "IRRIGATION_ASJEN_AMONT": "I",
            "TURBINAGE_EXCLUSIF": "J",
            "AEPI": "K",
            "TRANSFERT": "L",
            "VDF": "M",
            "EVAC": "N",
            "FUITES": "O",
        },
        "total_restitutions": "P",
        "apports": "Q",
        "specials": {
            "BGE_GARDE_AM": "R",
            "BGE_GARDE_AV": "S",
            "BGE_GARDE_PLUIE": "T",
        },
    },
    "DAR_KHROFA": {
        "sheet_name": "DAR KHROFA",
        "data_start_row": 8,
        "total_row": 41,
        "last_column": "Q",
        "restitutions": {
            "PRISE_AGRICOLE": "G", "AEPI_PRISES": "H", "VDF": "I",
            "BY_PASS": "J", "EVAC": "K", "FUITES": "L"
        },
        "total_restitutions": "M",
        "apports": "Q",
        "specials": {
            "UTILISATION_AEPI_TANGER": "N",
            "UTILISATION_IRRIGATION": "O",
            "TRANSFERT_DAR_KHROFA": "P",
        },
    },
    "KHATTABI": {
        "sheet_name": "KHATTABI",
        "data_start_row": 9,
        "total_row": 42,
        "last_column": "N",
        "restitutions": {
            "AEPI": "G", "PRISE_AGRICOLE_AM": "H", "PRISE_AGRICOLE_AV": "I",
            "SIPHON_DIGUE": "J", "EVAC": "K", "FUITES": "L"
        },
        "total_restitutions": "M",
        "apports": "N",
        "specials": {},
    },
    "JOUMOUA": {
        "sheet_name": "JOUMOUA",
        "data_start_row": 8,
        "total_row": 41,
        "last_column": "L",
        "restitutions": {"AEPI": "G", "VDF": "H", "EVAC": "I", "FUITES": "J"},
        "total_restitutions": "K",
        "apports": "L",
        "specials": {},
    },
}

# Lignes correspondant aux barrages dans la feuille "ANNONCE DE CRUES".
CRUES_BARRAGE_ROWS = {
    "NAKHLA": 9,
    "CAI": 10,
    "MHB_MEHDI": 11,
    "SMIR": 16,
    "CHEFCHAOUEN": 17,
    "BIB": 27,
    "9_AVRIL": 29,
    "TANGER_MED": 34,
    "KHARROUB": 35,
    "BOEM": 44,
    "DAR_KHROFA": 46,
    "KHATTABI": 57,
    "JOUMOUA": 58,
}
