from __future__ import annotations

from copy import deepcopy


EVAPORATION_MAPPING = {
    "sheet": "EVAPORATION",
    "month_cell": "C2",
    "year_cell": "C3",
    "start_row": 9,
    "row_count": 32,
    "columns": {
        "date": "A",
        "cote": "B",
        "surface": "C",
        "surface_moyenne": "D",
        "hauteur_bac": "E",
        "pluie": "F",
        "hauteur_evaporee": "G",
        "hauteur_corrigee": "H",
        "evaporation": "I",
    },
}


def field(
    code: str,
    label: str,
    column: str,
    *,
    included_in_total: bool = True,
    role: str = "restitution",
    editable: bool = True,
) -> dict:
    return {
        "code": code,
        "label": label,
        "column": column,
        "included_in_total": included_in_total,
        "role": role,
        "editable": editable,
        "unit": "m3",
    }


def config(
    template: str,
    display_name: str,
    start_row: int,
    total_column: str,
    apports_column: str,
    debit_column: str,
    pluie_column: str,
    input_fields: list[dict],
    *,
    last_column: str | None = None,
    special_columns: dict[str, str] | None = None,
) -> dict:
    return {
        "template": template,
        "display_name": display_name,
        "evaporation": deepcopy(EVAPORATION_MAPPING),
        "apport": {
            "sheet": "APPORT",
            "start_row": start_row,
            "row_count": 32,
            "columns": {
                "date": "A",
                "cote": "B",
                "volume": "C",
                "variation": "D",
                "evaporation": "E",
                "total_restitutions": total_column,
                "apports": apports_column,
                "debit": debit_column,
                "pluie": pluie_column,
            },
            "last_column": last_column or pluie_column,
            "special_columns": special_columns or {},
        },
        "input_fields": input_fields,
    }


BILAN_CONFIGS: dict[str, dict] = {
    "NAKHLA": config(
        "BILAN B.Nakhla.xlsx",
        "Barrage Nakhla",
        7,
        "J",
        "K",
        "L",
        "M",
        [
            field("AEPI", "AEPI", "F"),
            field("VDF", "VDF", "G"),
            field("EVAC", "EVAC", "H"),
            field("FUITES", "Fuites", "I"),
        ],
    ),
    "SMIR": config(
        "BILAN B.smir.xlsx",
        "Barrage Smir",
        7,
        "K",
        "L",
        "M",
        "N",
        [
            field("AEPI", "AEPI", "F"),
            field("VDF", "VDF", "G"),
            field("BY_PASS", "By-Pass", "H"),
            field("EVAC", "EVAC", "I"),
            field("FUITES", "Fuites", "J"),
        ],
    ),
    "MHB_MEHDI": config(
        "BILAN B.MHB Mehdi.xlsx",
        "Barrage M.H.B El Mehdi",
        7,
        "K",
        "L",
        "M",
        "N",
        [
            field("AEPI", "AEPI", "F"),
            field("VDF", "VDF", "G"),
            field("BY_PASS", "By-Pass", "H"),
            field("EVAC", "EVAC", "I"),
            field("FUITES", "Fuites", "J"),
        ],
    ),
    "CAI": config(
        "BILAN B.CAI.xlsx",
        "Barrage Charif Al Idrissi",
        7,
        "M",
        "N",
        "O",
        "P",
        [
            field("AEPI", "AEPI", "F"),
            field("IRRIGATION", "Irrigation", "G"),
            field("VDF_RD", "VDF RD", "H"),
            field("VDF_RG", "VDF RG", "I"),
            field("BY_PASS", "By-Pass", "J"),
            field("EVAC", "EVAC", "K"),
            field("FUITES", "Fuites", "L"),
        ],
    ),
    "CHEFCHAOUEN": config(
        "BILAN B.Chefchaouen.xlsx",
        "Barrage Chefchaouen",
        7,
        "L",
        "M",
        "N",
        "O",
        [
            field("AEPI", "AEPI", "F"),
            field("IRRIGATION", "Irrigation", "G"),
            field("VDF", "VDF", "H"),
            field("BY_PASS", "By-Pass", "I"),
            field("EVAC", "EVAC", "J"),
            field("FUITES", "Fuites", "K"),
        ],
    ),
    "TANGER_MED": config(
        "BILAN B.T-Med.xlsx",
        "Barrage Tanger Méditerranée",
        7,
        "K",
        "L",
        "M",
        "N",
        [
            field("AEPI", "AEPI", "F"),
            field("VDF", "VDF", "G"),
            field("EVAC", "EVAC", "H"),
            field("TMSA", "TMSA", "I"),
            field("FUITES", "Fuites", "J"),
        ],
    ),
    "BIB": config(
        "BILAN B.Ibn Batouta.xlsx",
        "Barrage Ibn Batouta",
        8,
        "N",
        "O",
        "P",
        "Q",
        [
            field("AEPI_PRISES", "AEPI - Prises", "F"),
            field("AEPI_JETS_CREUX", "AEPI - Jets creux", "G"),
            field("JETS_CREUX", "Jets creux", "H"),
            field("VDF", "VDF", "I"),
            field("BY_PASS", "By-Pass", "J"),
            field("POMPES_DEVASAGE", "Pompes de dévasage", "K"),
            field("EVAC", "EVAC", "L"),
            field("FUITES", "Fuites", "M"),
        ],
    ),
    "9_AVRIL": config(
        "BILAN B.9 AVRIL.xlsx",
        "Barrage 9 Avril 1947",
        7,
        "K",
        "L",
        "M",
        "N",
        [
            field("AEPI", "AEPI", "F"),
            field("VDF", "VDF", "G"),
            field("BY_PASS", "By-Pass", "H"),
            field("EVAC", "EVAC", "I"),
            field("FUITES", "Fuites", "J"),
        ],
    ),
    "KHARROUB": config(
        "BILAN B.Kharoub.xlsx",
        "Barrage Kharroub",
        7,
        "K",
        "L",
        "M",
        "N",
        [
            field("AEPI", "AEPI", "F"),
            field("VDF", "VDF", "G"),
            field("BY_PASS", "By-Pass", "H"),
            field("EVAC", "EVAC", "I"),
            field("FUITES", "Fuites", "J"),
        ],
    ),
    "BOEM": config(
        "BILAN B.OEM.xlsx",
        "Barrage Oued El Makhazine",
        8,
        "P",
        "Q",
        "R",
        "S",
        [
            field("IRRIGATION_LOUKKOS_TURBINAGE", "Irrigation Loukkos - Turbinage", "F"),
            field("IRRIGATION_LOUKKOS_PRISE", "Irrigation Loukkos - Prise agricole", "G"),
            field("IRRIGATION_ASJEN_AMONT", "Irrigation Asjen - Amont", "H"),
            field("TURBINAGE_EXCLUSIF", "Turbinage exclusif", "I"),
            field("AEPI", "AEPI", "J"),
            field("TRANSFERT_DAR_KHROFA", "Transfert vers Dar Khrofa", "K"),
            field("VDF_RD", "VDF RD", "L"),
            field("VDF_RG", "VDF RG", "M"),
            field("EVAC", "EVAC", "N"),
            field("FUITES", "Fuites", "O"),
        ],
    ),
    "DAR_KHROFA": config(
        "BILAN B.Dar Khrofa.xlsx",
        "Barrage Dar Khrofa",
        7,
        "N",
        "R",
        "S",
        "T",
        [
            field("PRISE_AGRICOLE_RD", "Prise agricole RD", "F"),
            field("PRISE_AGRICOLE_RG", "Prise agricole RG", "G"),
            field("AEPI_PRISES", "AEPI - Prises", "H"),
            field("VDF_RD", "VDF RD", "I"),
            field("VDF_RG", "VDF RG", "J"),
            field("BY_PASS", "By-Pass", "K"),
            field("EVAC", "EVAC", "L"),
            field("FUITES", "Fuites", "M"),
            field(
                "AEPI_TANGER",
                "AEPI Tanger",
                "O",
                included_in_total=False,
                role="utilisation",
            ),
            field(
                "TRANSFERT_DAR_KHROFA",
                "Transfert reçu depuis BOEM",
                "Q",
                included_in_total=False,
                role="transfer_received",
            ),
        ],
        special_columns={"IRRIGATION_CALCULEE": "P"},
    ),
    "KHATTABI": config(
        "BILAN B.MBA Khattabi.xlsx",
        "Barrage MBA Khattabi",
        8,
        "L",
        "M",
        "N",
        "O",
        [
            field("AEPI", "AEPI", "F"),
            field("PRISE_AGRICOLE_RD", "Prise agricole RD - Digue B", "G"),
            field("PRISE_AGRICOLE_RG", "Prise agricole RG - Digue A", "H"),
            field("SIPHON", "Siphon - Digue F", "I"),
            field("EVAC", "EVAC", "J"),
            field("FUITES", "Fuites", "K"),
        ],
    ),
    "JOUMOUA": config(
        "BILAN B.Joumoua.xlsx",
        "Barrage Joumoua",
        7,
        "K",
        "L",
        "M",
        "N",
        [
            field("AEPI", "AEPI", "F"),
            field("VDF_RD", "VDF RD", "G"),
            field("VDF_RG", "VDF RG", "H"),
            field("EVAC", "EVAC", "I"),
            field("FUITES", "Fuites", "J"),
        ],
    ),
    "RHISS": config(
        "BILAN B.Rhiss.xlsx",
        "Barrage Rhiss",
        7,
        "L",
        "M",
        "N",
        "O",
        [
            field("AEPI", "AEPI", "F"),
            field("RESTITUTION", "Restitution", "G"),
            field("SEGUIA", "Seguia", "H"),
            field("VDF", "VDF", "I"),
            field("EVAC", "EVAC", "J"),
            field("FUITES", "Fuites", "K"),
        ],
    ),
}


SUPPORTED_BARRAGE_CODES = tuple(BILAN_CONFIGS.keys())


def normalize_barrage_code(code: str) -> str:
    return str(code or "").strip().upper()


def get_bilan_config(code: str) -> dict | None:
    return BILAN_CONFIGS.get(normalize_barrage_code(code))


def get_input_fields(code: str) -> list[dict]:
    cfg = get_bilan_config(code)
    return deepcopy(cfg["input_fields"]) if cfg else []


def editable_codes(code: str) -> set[str]:
    return {item["code"] for item in get_input_fields(code) if item.get("editable", True)}


def total_restitution_codes(code: str) -> set[str]:
    return {
        item["code"]
        for item in get_input_fields(code)
        if item.get("included_in_total", True)
    }


def input_field_by_code(code: str) -> dict[str, dict]:
    return {item["code"]: item for item in get_input_fields(code)}


def derived_or_hidden_codes(code: str) -> set[str]:
    result: set[str] = set()
    if normalize_barrage_code(code) == "DAR_KHROFA":
        result.add("IRRIGATION")
    if normalize_barrage_code(code) == "KHATTABI":
        result.add("IRRIGATION")
    return result
