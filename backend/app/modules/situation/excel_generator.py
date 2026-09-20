from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

from decimal import Decimal, ROUND_HALF_UP

from app.config import BACKEND_DIR, settings
from app.modules.situation.calculations import add_months, build_situation_data
from app.modules.situation.mappings import (
    DATE_CHANGEMENT_TAUX,
    SELECTED_EXPORT_SHEETS,
    TARGET_BARRAGES_ORDER,
)
from app.modules.situation.repository import load_situation_raw_data


TEMPLATE_NAME = "Situation quotidienne des barrages_TEMPLATE.xlsx"


# ============================================================
# CHEMINS
# ============================================================

def resolve_template_path() -> Path:
    candidates = [
        BACKEND_DIR / "app" / "templates" / TEMPLATE_NAME,
        BACKEND_DIR / "templates" / TEMPLATE_NAME,
        BACKEND_DIR / "excel_templates" / TEMPLATE_NAME,
    ]

    try:
        candidates.append((BACKEND_DIR / settings.EXCEL_TEMPLATES_DIR / TEMPLATE_NAME).resolve())
    except Exception:
        pass

    for path in candidates:
        if path.exists():
            return path

    raise HTTPException(
        status_code=500,
        detail=(
            "Template Excel introuvable. Place le fichier ici : "
            f"{BACKEND_DIR / 'app' / 'templates' / TEMPLATE_NAME}"
        ),
    )


def resolve_exports_dir() -> Path:
    try:
        p = Path(settings.DATA_EXPORTS_DIR)
    except Exception:
        p = BACKEND_DIR / "exports"

    if not p.is_absolute():
        p = (BACKEND_DIR / p).resolve()

    p.mkdir(parents=True, exist_ok=True)
    return p


# ============================================================
# OUTILS EXCEL
# ============================================================

def get_writable_cell(ws, cell_ref: str):
    """
    Si cell_ref est une cellule fusionnée non modifiable,
    retourne la cellule principale en haut à gauche du bloc fusionné.
    """
    cell = ws[cell_ref]

    if not isinstance(cell, MergedCell):
        return cell

    for merged_range in ws.merged_cells.ranges:
        if cell_ref in merged_range:
            return ws.cell(
                row=merged_range.min_row,
                column=merged_range.min_col,
            )

    return cell


def write_cell(ws, cell_ref: str, value):
    """
    Écrit une valeur même si la cellule appartient à une zone fusionnée.
    """
    target_cell = get_writable_cell(ws, cell_ref)
    target_cell.value = value


def set_calc_mode(wb):
    try:
        wb.calculation.fullCalcOnLoad = True
        wb.calculation.forceFullCalc = True
        wb.calculation.calcMode = "auto"
    except Exception:
        pass


def remove_non_selected_sheets(wb):
    for sheet_name in list(wb.sheetnames):
        if sheet_name not in SELECTED_EXPORT_SHEETS:
            del wb[sheet_name]


def remove_external_links(wb):
    try:
        wb._external_links = []
    except Exception:
        pass


# ============================================================
# FORMAT DATES
# ============================================================

def fr_date_long(d: date) -> str:
    mois = [
        "",
        "JANVIER",
        "FÉVRIER",
        "MARS",
        "AVRIL",
        "MAI",
        "JUIN",
        "JUILLET",
        "AOÛT",
        "SEPTEMBRE",
        "OCTOBRE",
        "NOVEMBRE",
        "DÉCEMBRE",
    ]
    return f"{d.day:02d} {mois[d.month]} {d.year}"


def detail_date_text(d: date) -> str:
    return f" Au {d.day:02d} . {d.month:02d} . {d.year}"


# ============================================================
# DATES DANS LES FEUILLES
# ============================================================

def fill_dates(ws, date_situation: date, date_veille: date, date_annee_precedente: date):
    write_cell(ws, "F8", detail_date_text(date_situation))
    write_cell(ws, "C10", date_veille)
    write_cell(ws, "D10", date_situation)
    write_cell(ws, "G11", date_veille)
    write_cell(ws, "I11", date_situation)
    write_cell(ws, "M11", date_situation)
    write_cell(ws, "O11", date_annee_precedente)
    write_cell(ws, "U13", date_situation)
    write_cell(ws, "V13", date_annee_precedente)


def fill_dates_transfer(ws, date_situation: date, date_veille: date, date_annee_precedente: date):
    write_cell(ws, "D8", f"{detail_date_text(date_situation)} à 7 heures")
    write_cell(ws, "C10", date_veille)
    write_cell(ws, "D10", date_situation)
    write_cell(ws, "G11", date_veille)
    write_cell(ws, "J11", date_situation)
    write_cell(ws, "N11", date_situation)
    write_cell(ws, "P11", date_annee_precedente)


# ============================================================
# FEUILLE : SITUATION DÉTAILLÉE
# ============================================================

def fill_situation_detaillee(ws, data: dict):
    dates = data["dates"]

    fill_dates(
        ws,
        dates["date_situation"],
        dates["date_veille"],
        dates["date_annee_precedente"],
    )

    for code in TARGET_BARRAGES_ORDER:
        row_data = data["normal_rows"][code]
        cote_row = row_data["cote_row"]
        volume_row = row_data["volume_row"]

        write_cell(ws, f"A{cote_row}", row_data["label"])

        write_cell(ws, f"B{cote_row}", row_data["cote_normale"])
        write_cell(ws, f"C{cote_row}", row_data["cote_veille"])
        write_cell(ws, f"D{cote_row}", row_data["cote_jour"])
        write_cell(ws, f"E{cote_row}", row_data["variation_cote_cm"])

        write_cell(ws, f"B{volume_row}", row_data["volume_normal_current"])
        write_cell(ws, f"C{volume_row}", row_data["volume_veille"])
        write_cell(ws, f"D{volume_row}", row_data["volume_jour"])
        write_cell(ws, f"E{volume_row}", row_data["variation_volume"])

        for col in ["F", "G", "H", "I", "J", "K"]:
            write_cell(ws, f"{col}{cote_row}", row_data["lachers"].get(col, 0.0))

        # Correction spéciale Dar Khrofa :
        # Dans le template, les cellules de lâchers sont fusionnées,
        # donc la valeur Prise agricole peut être écrasée par les colonnes voisines.
        if code == "DAR_KHROFA":
            write_cell(ws, f"H{cote_row}", row_data["lachers"].get("H", 0.0))



        write_cell(ws, f"M{cote_row}", row_data["volume_jour"])
        write_cell(ws, f"N{cote_row}", row_data["taux_remplissage"])
        write_cell(ws, f"O{cote_row}", row_data["volume_annee_precedente"])
        write_cell(ws, f"P{cote_row}", row_data["taux_annee_precedente"])
        write_cell(ws, f"Q{cote_row}", row_data["pluie_mm"])

        write_cell(ws, f"T{cote_row}", row_data["cote_normale"])
        write_cell(ws, f"T{volume_row}", row_data["volume_normal_old"])
        write_cell(ws, f"U{volume_row}", row_data["volume_jour"])
        write_cell(ws, f"V{volume_row}", row_data["volume_annee_precedente"])

    totals = data["normal_totals"]
    total_row = 40

    write_cell(ws, f"A{total_row}", "Ensemble des barrages")

    for col in [
        "B", "C", "D", "E",
        "F", "G", "H", "I", "J", "K",
        "M", "N", "O", "P",
        "T", "U", "V",
    ]:
        write_cell(ws, f"{col}{total_row}", totals.get(col))


# ============================================================
# FEUILLE : SITUATION DÉTAILLÉE (T)
# ============================================================

def fill_situation_detaillee_transfer(ws, data: dict):
    dates = data["dates"]

    fill_dates_transfer(
        ws,
        dates["date_situation"],
        dates["date_veille"],
        dates["date_annee_precedente"],
    )

    for code in TARGET_BARRAGES_ORDER:
        row_data = data["transfer_rows"][code]
        cote_row = row_data["cote_row"]
        volume_row = row_data["volume_row"]

        write_cell(ws, f"A{cote_row}", row_data["label"])

        write_cell(ws, f"B{cote_row}", row_data["cote_normale"])
        write_cell(ws, f"C{cote_row}", row_data["cote_veille"])
        write_cell(ws, f"D{cote_row}", row_data["cote_jour"])
        write_cell(ws, f"E{cote_row}", row_data["variation_cote_cm"])

        write_cell(ws, f"B{volume_row}", row_data["volume_normal_old"])
        write_cell(ws, f"C{volume_row}", row_data["volume_veille"])
        write_cell(ws, f"D{volume_row}", row_data["volume_jour"])
        write_cell(ws, f"E{volume_row}", row_data["variation_volume"])

        for col in ["F", "G", "H", "I", "J", "K", "L"]:
            write_cell(ws, f"{col}{cote_row}", row_data["lachers"].get(col, 0.0))

        # Correction spéciale Dar Khrofa :
        # Dans la version transfert, la Prise agricole de Dar Khrofa
        # doit apparaître dans la colonne Irrigation.
        if code == "DAR_KHROFA":
            write_cell(ws, f"I{cote_row}", row_data["lachers"].get("I", 0.0))

        write_cell(ws, f"N{cote_row}", row_data["volume_jour"])
        write_cell(ws, f"O{cote_row}", row_data["taux_remplissage"])
        write_cell(ws, f"P{cote_row}", row_data["volume_annee_precedente"])
        write_cell(ws, f"Q{cote_row}", row_data["taux_annee_precedente"])
        write_cell(ws, f"R{cote_row}", row_data["pluie_mm"])

    totals = data["transfer_totals"]
    total_row = 40

    write_cell(ws, f"A{total_row}", "Ensemble des barrages")

    for col in [
        "B", "C", "D", "E",
        "F", "G", "H", "I", "J", "K", "L",
        "N", "O", "P", "Q",
    ]:
        write_cell(ws, f"{col}{total_row}", totals.get(col))


# ============================================================
# OUTILS POUR SITUATION FRA / AR
# ============================================================

# ============================================================
# OUTILS POUR SITUATION FRA / AR
# ============================================================

def excel_round(value, digits=0):
    """
    Arrondi proche d'Excel : 0.5 vers le haut.
    """
    if value is None:
        return None

    q = Decimal("1") if digits == 0 else Decimal("1." + ("0" * digits))
    result = Decimal(str(float(value))).quantize(q, rounding=ROUND_HALF_UP)

    if digits == 0:
        return int(result)

    return float(result)


def safe_number(value, default=0.0):
    if value is None:
        return default
    return float(value)


def safe_rate(volume, volume_normal):
    if volume is None or volume_normal in (None, 0):
        return None

    result = float(volume) / float(volume_normal) * 100

    if result > 100:
        return 100.0

    return result


def write_number_cell(ws, cell_ref: str, value, number_format: str):
    """
    Écrit une valeur numérique avec un format Excel.
    """
    target_cell = get_writable_cell(ws, cell_ref)
    target_cell.value = value
    target_cell.number_format = number_format


SUMMARY_ROWS = {
    "BOEM": 10,
    "DAR_KHROFA": 11,
    "LOUKKOS_TOTAL": 12,

    "BIB": 13,
    "9_AVRIL": 14,
    "KHARROUB": 15,
    "TANGER_MED": 16,
    "TANGER_TOTAL": 17,

    "NAKHLA": 18,
    "SMIR": 19,
    "MHB_MEHDI": 20,
    "CAI": 21,
    "TETOUAN_TOTAL": 22,

    "KHATTABI": 23,
    "JOUMOUA": 24,
    "AL_HOCEIMA_TOTAL": 25,

    "CHEFCHAOUEN": 26,
    "TOTAL": 27,
}


SUMMARY_INDIVIDUAL_CODES = [
    "BOEM",
    "DAR_KHROFA",
    "BIB",
    "9_AVRIL",
    "KHARROUB",
    "TANGER_MED",
    "NAKHLA",
    "SMIR",
    "MHB_MEHDI",
    "CAI",
    "KHATTABI",
    "JOUMOUA",
    "CHEFCHAOUEN",
]


FRA_BARRAGE_NAMES = {
    "BOEM": "Oued El Makhazine",
    "DAR_KHROFA": "Dar Khrofa",
    "BIB": "Ibn Batouta",
    "9_AVRIL": "9 Avril 1947",
    "KHARROUB": "khroub",
    "TANGER_MED": "Tanger Med",
    "NAKHLA": "Nakhla",
    "SMIR": "Smir",
    "MHB_MEHDI": "M.H.B. El Mehdi",
    "CAI": "Charif Al Idrissi",
    "KHATTABI": "M.B.A. El Khattabi",
    "JOUMOUA": "Joumoua",
    "CHEFCHAOUEN": "Chefchaouen",
}


SUMMARY_GROUPS = {
    "LOUKKOS_TOTAL": ["BOEM", "DAR_KHROFA"],
    "TANGER_TOTAL": ["BIB", "9_AVRIL", "KHARROUB", "TANGER_MED"],
    "TETOUAN_TOTAL": ["NAKHLA", "SMIR", "MHB_MEHDI", "CAI"],
    "AL_HOCEIMA_TOTAL": ["KHATTABI", "JOUMOUA"],
    "TOTAL": [
        "BOEM",
        "DAR_KHROFA",
        "BIB",
        "9_AVRIL",
        "KHARROUB",
        "TANGER_MED",
        "NAKHLA",
        "SMIR",
        "MHB_MEHDI",
        "CAI",
        "KHATTABI",
        "JOUMOUA",
        "CHEFCHAOUEN",
    ],
}


# Totaux visibles dans les tableaux AR/FRA.
# Ces valeurs servent seulement aux feuilles résumé AR/FRA.
# Elles ne touchent pas Situation Détaillée ni Situation Détaillée (T).
SUMMARY_CURRENT_NORMAL_TOTALS = {
    "LOUKKOS_TOTAL": 1170.6,
    "TANGER_TOTAL": 546.1,
    "TETOUAN_TOTAL": 212.2,
    "AL_HOCEIMA_TOTAL": 15.9,
    "TOTAL": 1956.6,
}


SUMMARY_OLD_NORMAL_TOTALS = {
    "LOUKKOS_TOTAL": 1153.1,
    "TANGER_TOTAL": 539.8,
    "TETOUAN_TOTAL": 188.2,
    "AL_HOCEIMA_TOTAL": 16.9,
    "TOTAL": 1910.3,
}


def get_row_summary_values(data: dict, code: str) -> dict:
    row_data = data["normal_rows"][code]

    volume_normal_current = safe_number(row_data.get("volume_normal_current"))
    volume_normal_old = safe_number(row_data.get("volume_normal_old"))
    volume_jour = safe_number(row_data.get("volume_jour"))
    volume_annee_precedente = safe_number(row_data.get("volume_annee_precedente"))

    return {
        "volume_normal_current": volume_normal_current,
        "volume_normal_old": volume_normal_old,
        "volume_jour": volume_jour,
        "taux_remplissage": safe_rate(volume_jour, volume_normal_current),
        "volume_annee_precedente": volume_annee_precedente,
        "taux_annee_precedente": safe_rate(volume_annee_precedente, volume_normal_old),
    }


def build_summary_values(data: dict, group_code: str, codes: list[str]) -> dict:
    volume_normal_current = SUMMARY_CURRENT_NORMAL_TOTALS.get(group_code)
    volume_normal_old = SUMMARY_OLD_NORMAL_TOTALS.get(group_code)

    if volume_normal_current is None:
        volume_normal_current = sum(
            safe_number(data["normal_rows"][code].get("volume_normal_current"))
            for code in codes
        )

    if volume_normal_old is None:
        volume_normal_old = sum(
            safe_number(data["normal_rows"][code].get("volume_normal_old"))
            for code in codes
        )

    volume_jour = sum(
        safe_number(data["normal_rows"][code].get("volume_jour"))
        for code in codes
    )

    volume_annee_precedente = sum(
        safe_number(data["normal_rows"][code].get("volume_annee_precedente"))
        for code in codes
    )

    return {
        "volume_normal_current": volume_normal_current,
        "volume_normal_old": volume_normal_old,
        "volume_jour": volume_jour,
        "taux_remplissage": safe_rate(volume_jour, volume_normal_current),
        "volume_annee_precedente": volume_annee_precedente,
        "taux_annee_precedente": safe_rate(volume_annee_precedente, volume_normal_old),
    }


def build_summary_values_fra(data: dict, group_code: str, codes: list[str]) -> dict:
    """
    Version spéciale Situation FRA.

    Dans la page FRA originale, les lignes Sous-Total et Total utilisent
    le volume normal actuel pour calculer le taux de l'année précédente.
    """
    values = build_summary_values(data, group_code, codes)

    values["taux_annee_precedente"] = safe_rate(
        values["volume_annee_precedente"],
        values["volume_normal_current"],
    )

    return values


def write_summary_fra_row(ws, excel_row: int, values: dict):
    """
    Situation FRA.

    Colonnes réelles :
    D : Barrage
    E : Capacité normale
    F : Volume 09/06/2026
    G : Taux 09/06/2026
    H : Volume 09/06/2025
    I : Taux 09/06/2025
    """

    write_number_cell(ws, f"E{excel_row}", excel_round(values["volume_normal_current"], 1), "0.0")
    write_number_cell(ws, f"F{excel_row}", excel_round(values["volume_jour"], 1), "0.0")
    write_number_cell(ws, f"G{excel_row}", excel_round(values["taux_remplissage"], 0), "0")
    write_number_cell(ws, f"H{excel_row}", excel_round(values["volume_annee_precedente"], 1), "0.0")
    write_number_cell(ws, f"I{excel_row}", excel_round(values["taux_annee_precedente"], 0), "0")


def write_summary_ar_row(ws, excel_row: int, values: dict):
    """
    Situation AR - tableau principal.

    C : نسبة الملء 2025
    D : الحجم 2025
    E : نسبة الملء 2026
    F : الحجم 2026
    G : الحجم العادي
    """

    write_number_cell(ws, f"C{excel_row}", excel_round(values["taux_annee_precedente"], 0), "0")
    write_number_cell(ws, f"D{excel_row}", excel_round(values["volume_annee_precedente"], 1), "0.0")

    write_number_cell(ws, f"E{excel_row}", excel_round(values["taux_remplissage"], 0), "0")
    write_number_cell(ws, f"F{excel_row}", excel_round(values["volume_jour"], 1), "0.0")

    write_number_cell(ws, f"G{excel_row}", excel_round(values["volume_normal_current"], 1), "0.0")


def write_summary_ar_right_table_row(ws, excel_row: int, values: dict):
    """
    Situation AR - tableau à droite.

    M : volume normal ancien
    N : volume année précédente
    O : volume date situation
    """

    write_number_cell(ws, f"M{excel_row}", excel_round(values["volume_normal_old"], 1), "0.0")
    write_number_cell(ws, f"N{excel_row}", excel_round(values["volume_annee_precedente"], 1), "0.0")
    write_number_cell(ws, f"O{excel_row}", excel_round(values["volume_jour"], 1), "0.0")


# ============================================================
# FEUILLE : SITUATION FRA
# ============================================================

def fill_situation_fra(ws, data: dict):
    d = data["dates"]["date_situation"]

    write_cell(ws, "A6", f" SITUATION DES BARRAGES AU {fr_date_long(d)}")

    # Lignes individuelles : nom du barrage + valeurs décalées à droite.
    for code in SUMMARY_INDIVIDUAL_CODES:
        excel_row = SUMMARY_ROWS[code]
        values = get_row_summary_values(data, code)

        write_cell(ws, f"D{excel_row}", FRA_BARRAGE_NAMES[code])
        write_summary_fra_row(ws, excel_row, values)

    # Lignes Sous-Total / Total.
    for group_code, codes in SUMMARY_GROUPS.items():
        excel_row = SUMMARY_ROWS[group_code]
        values = build_summary_values_fra(data, group_code, codes)

        if group_code == "TOTAL":
            write_cell(ws, f"C{excel_row}", "Total")
        else:
            write_cell(ws, f"C{excel_row}", "Sous-Total")

        write_summary_fra_row(ws, excel_row, values)


# ============================================================
# FEUILLE : SITUATION AR
# ============================================================

def fill_situation_ar(ws, data: dict):
    d = data["dates"]["date_situation"]

    mois_ar = [
        "",
        " يناير ",
        " فبراير ",
        " مارس ",
        " أبريل ",
        " ماي ",
        " يونيو ",
        " يوليوز ",
        " غشت ",
        " شتنبر ",
        " أكتوبر ",
        " نونبر ",
        " دجنبر ",
    ]

    write_cell(ws, "A6", f" حالة ملء السدود بتاريخ {d.day}{mois_ar[d.month]}{d.year}")

    for code in SUMMARY_INDIVIDUAL_CODES:
        excel_row = SUMMARY_ROWS[code]
        values = get_row_summary_values(data, code)

        write_summary_ar_row(ws, excel_row, values)
        write_summary_ar_right_table_row(ws, excel_row, values)

    for group_code, codes in SUMMARY_GROUPS.items():
        excel_row = SUMMARY_ROWS[group_code]
        values = build_summary_values(data, group_code, codes)

        write_summary_ar_row(ws, excel_row, values)
        write_summary_ar_right_table_row(ws, excel_row, values)

# ============================================================
# FEUILLE : ORMVAL NORMALE
# ============================================================

def fill_ormval(ws, data: dict):
    d = data["dates"]["date_situation"]

    write_cell(
        ws,
        "B10",
        f" SITUATION DES BARRAGES RELEVANT DE LA PROVINCE DE LARACHE AU {fr_date_long(d)}",
    )

    boem = data["normal_rows"]["BOEM"]
    dar = data["normal_rows"]["DAR_KHROFA"]

    write_cell(ws, "D16", boem["cote_jour"])
    write_cell(ws, "F16", boem["volume_jour"])
    write_cell(ws, "G16", boem["taux_remplissage"])
    write_cell(ws, "H16", boem["lachers"].get("F", 0.0))
    write_cell(ws, "I16", boem["lachers"].get("G", 0.0))
    write_cell(ws, "J16", boem["lachers"].get("H", 0.0))

    write_cell(ws, "D17", dar["cote_jour"])
    write_cell(ws, "F17", dar["volume_jour"])
    write_cell(ws, "G17", dar["taux_remplissage"])
    write_cell(ws, "J17", dar["lachers"].get("H", 0.0))

    write_cell(ws, "D19", data["specials"]["garde_loukkos_amont"])
    write_cell(ws, "E19", data["specials"]["garde_loukkos_aval"])


# ============================================================
# FEUILLE : ORMVAL VT
# ============================================================

def fill_ormval_vt(ws, data: dict):
    d = data["dates"]["date_situation"]

    write_cell(
        ws,
        "B10",
        f" SITUATION DES BARRAGES RELEVANT DE LA PROVINCE DE LARACHE AU {fr_date_long(d)}",
    )

    boem = data["transfer_rows"]["BOEM"]
    dar = data["transfer_rows"]["DAR_KHROFA"]

    write_cell(ws, "D16", boem["cote_jour"])
    write_cell(ws, "F16", boem["volume_jour"])
    write_cell(ws, "G16", boem["taux_remplissage"])
    write_cell(ws, "H16", boem["lachers"].get("F", 0.0))
    write_cell(ws, "I16", boem["lachers"].get("G", 0.0))
    write_cell(ws, "J16", boem["lachers"].get("H", 0.0))
    write_cell(ws, "K16", boem["lachers"].get("I", 0.0))

    write_cell(ws, "D17", dar["cote_jour"])
    write_cell(ws, "F17", dar["volume_jour"])
    write_cell(ws, "G17", dar["taux_remplissage"])
    write_cell(ws, "K17", dar["lachers"].get("I", 0.0))

    write_cell(ws, "D19", data["specials"]["garde_loukkos_amont"])
    write_cell(ws, "E19", data["specials"]["garde_loukkos_aval"])


# ============================================================
# GÉNÉRATION PRINCIPALE
# ============================================================

def generate_situation_excel(db, date_situation: date) -> Path:
    date_veille = date_situation - timedelta(days=1)
    date_annee_precedente = add_months(date_situation, -12)

    raw = load_situation_raw_data(
        db,
        [
            date_situation,
            date_veille,
            date_annee_precedente,
        ],
    )

    data = build_situation_data(raw, date_situation)

    if not data["check"]["can_generate"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Impossible de générer la situation : données manquantes.",
                "check": data["check"],
            },
        )

    template_path = resolve_template_path()
    exports_dir = resolve_exports_dir()

    output_name = (
        f"Situation quotidienne des barrages - "
        f"{date_situation.isoformat()} - {uuid4().hex[:8]}.xlsx"
    )
    output_path = exports_dir / output_name

    wb = load_workbook(template_path)

    remove_non_selected_sheets(wb)
    remove_external_links(wb)
    set_calc_mode(wb)

    required_sheets = [
        "Situation Détaillée",
        "Situation Détaillée (T)",
        "Situation FRA",
        "Situation AR",
        "Situation ORMVAL (Larache)",
        "Situation ORMVAL (Larache) (VT)",
    ]

    for sheet_name in required_sheets:
        if sheet_name not in wb.sheetnames:
            raise HTTPException(
                status_code=500,
                detail=f"Feuille manquante dans le template : {sheet_name}",
            )

    fill_situation_detaillee(wb["Situation Détaillée"], data)
    fill_situation_detaillee_transfer(wb["Situation Détaillée (T)"], data)
    fill_situation_fra(wb["Situation FRA"], data)
    fill_situation_ar(wb["Situation AR"], data)
    fill_ormval(wb["Situation ORMVAL (Larache)"], data)
    fill_ormval_vt(wb["Situation ORMVAL (Larache) (VT)"], data)

    wb.save(output_path)

    return output_path

# === ABHL SITUATION DYNAMIQUE V2 PATCH START ===
# Ce bloc rend les feuilles Situation Détaillée / Résumés compatibles avec les nouveaux barrages.

def _abhl_sq_codes(data: dict) -> list[str]:
    return data.get("situation_codes") or list(TARGET_BARRAGES_ORDER)


def _abhl_sq_dynamic_codes(data: dict) -> list[str]:
    return data.get("dynamic_codes") or [
        code for code in _abhl_sq_codes(data)
        if code not in TARGET_BARRAGES_ORDER
    ]


def _abhl_sq_num(value, default=0.0):
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def _abhl_sq_copy_row_style(ws, source_row: int, target_row: int, max_col: int):
    from copy import copy

    ws.row_dimensions[target_row].height = ws.row_dimensions[source_row].height

    for col in range(1, max_col + 1):
        source = ws.cell(row=source_row, column=col)
        target = ws.cell(row=target_row, column=col)

        if source.has_style:
            target._style = copy(source._style)
        target.font = copy(source.font)
        target.fill = copy(source.fill)
        target.border = copy(source.border)
        target.alignment = copy(source.alignment)
        target.number_format = source.number_format
        target.protection = copy(source.protection)


def _abhl_sq_prepare_detail_rows(ws, data: dict, max_col: int):
    codes = _abhl_sq_codes(data)
    extra_count = max(0, len(codes) - len(TARGET_BARRAGES_ORDER))

    if extra_count > 0:
        ws.insert_rows(40, amount=extra_count * 2)

        for idx in range(extra_count):
            cote_row = 40 + idx * 2
            volume_row = cote_row + 1
            _abhl_sq_copy_row_style(ws, 38, cote_row, max_col)
            _abhl_sq_copy_row_style(ws, 39, volume_row, max_col)

    return 14 + 2 * len(codes)


def _abhl_sq_row_pair(index: int) -> tuple[int, int]:
    cote_row = 14 + (index * 2)
    return cote_row, cote_row + 1


def fill_situation_detaillee(ws, data: dict):
    dates = data["dates"]
    codes = _abhl_sq_codes(data)

    total_row = _abhl_sq_prepare_detail_rows(ws, data, 22)

    fill_dates(
        ws,
        dates["date_situation"],
        dates["date_veille"],
        dates["date_annee_precedente"],
    )

    for index, code in enumerate(codes):
        row_data = data["normal_rows"][code]
        cote_row, volume_row = _abhl_sq_row_pair(index)

        write_cell(ws, f"A{cote_row}", row_data["label"])
        write_cell(ws, f"A{volume_row}", row_data.get("bathy_label") or "")

        write_cell(ws, f"B{cote_row}", row_data["cote_normale"])
        write_cell(ws, f"C{cote_row}", row_data["cote_veille"])
        write_cell(ws, f"D{cote_row}", row_data["cote_jour"])
        write_cell(ws, f"E{cote_row}", row_data["variation_cote_cm"])

        write_cell(ws, f"B{volume_row}", row_data["volume_normal_current"])
        write_cell(ws, f"C{volume_row}", row_data["volume_veille"])
        write_cell(ws, f"D{volume_row}", row_data["volume_jour"])
        write_cell(ws, f"E{volume_row}", row_data["variation_volume"])

        for col in ["F", "G", "H", "I", "J", "K"]:
            write_cell(ws, f"{col}{cote_row}", row_data["lachers"].get(col, 0.0))

        if code == "DAR_KHROFA":
            write_cell(ws, f"H{cote_row}", row_data["lachers"].get("H", 0.0))

        write_cell(ws, f"M{cote_row}", row_data["volume_jour"])
        write_cell(ws, f"N{cote_row}", row_data["taux_remplissage"])
        write_cell(ws, f"O{cote_row}", row_data["volume_annee_precedente"])
        write_cell(ws, f"P{cote_row}", row_data["taux_annee_precedente"])
        write_cell(ws, f"Q{cote_row}", row_data["pluie_mm"])

        write_cell(ws, f"T{cote_row}", row_data["cote_normale"])
        write_cell(ws, f"T{volume_row}", row_data["volume_normal_old"])
        write_cell(ws, f"U{volume_row}", row_data["volume_jour"])
        write_cell(ws, f"V{volume_row}", row_data["volume_annee_precedente"])

    totals = data["normal_totals"]

    write_cell(ws, f"A{total_row}", "Ensemble des barrages")

    for col in [
        "B", "C", "D", "E",
        "F", "G", "H", "I", "J", "K",
        "M", "N", "O", "P",
        "T", "U", "V",
    ]:
        write_cell(ws, f"{col}{total_row}", totals.get(col))

    try:
        ws.print_area = f"A1:V{total_row + 5}"
    except Exception:
        pass


def fill_situation_detaillee_transfer(ws, data: dict):
    dates = data["dates"]
    codes = _abhl_sq_codes(data)

    total_row = _abhl_sq_prepare_detail_rows(ws, data, 18)

    fill_dates_transfer(
        ws,
        dates["date_situation"],
        dates["date_veille"],
        dates["date_annee_precedente"],
    )

    for index, code in enumerate(codes):
        row_data = data["transfer_rows"][code]
        cote_row, volume_row = _abhl_sq_row_pair(index)

        write_cell(ws, f"A{cote_row}", row_data["label"])
        write_cell(ws, f"A{volume_row}", row_data.get("bathy_label") or "")

        write_cell(ws, f"B{cote_row}", row_data["cote_normale"])
        write_cell(ws, f"C{cote_row}", row_data["cote_veille"])
        write_cell(ws, f"D{cote_row}", row_data["cote_jour"])
        write_cell(ws, f"E{cote_row}", row_data["variation_cote_cm"])

        write_cell(ws, f"B{volume_row}", row_data["volume_normal_old"])
        write_cell(ws, f"C{volume_row}", row_data["volume_veille"])
        write_cell(ws, f"D{volume_row}", row_data["volume_jour"])
        write_cell(ws, f"E{volume_row}", row_data["variation_volume"])

        for col in ["F", "G", "H", "I", "J", "K", "L"]:
            write_cell(ws, f"{col}{cote_row}", row_data["lachers"].get(col, 0.0))

        if code == "DAR_KHROFA":
            write_cell(ws, f"I{cote_row}", row_data["lachers"].get("I", 0.0))

        write_cell(ws, f"N{cote_row}", row_data["volume_jour"])
        write_cell(ws, f"O{cote_row}", row_data["taux_remplissage"])
        write_cell(ws, f"P{cote_row}", row_data["volume_annee_precedente"])
        write_cell(ws, f"Q{cote_row}", row_data["taux_annee_precedente"])
        write_cell(ws, f"R{cote_row}", row_data["pluie_mm"])

    totals = data["transfer_totals"]

    write_cell(ws, f"A{total_row}", "Ensemble des barrages")

    for col in [
        "B", "C", "D", "E",
        "F", "G", "H", "I", "J", "K", "L",
        "N", "O", "P", "Q",
    ]:
        write_cell(ws, f"{col}{total_row}", totals.get(col))

    try:
        ws.print_area = f"A1:R{total_row + 5}"
    except Exception:
        pass


def _abhl_sq_summary_values_for_codes(data: dict, codes: list[str], group_code: str | None = None) -> dict:
    if group_code == "TOTAL":
        volume_normal_current = data["normal_totals"].get("B")
        volume_normal_old = data["normal_totals"].get("T")
        volume_jour = data["normal_totals"].get("D")
        volume_annee_precedente = data["normal_totals"].get("O")
    else:
        base_current = SUMMARY_CURRENT_NORMAL_TOTALS.get(group_code, 0.0) if group_code else 0.0
        base_old = SUMMARY_OLD_NORMAL_TOTALS.get(group_code, 0.0) if group_code else 0.0

        dynamic_codes = [
            code for code in codes
            if code not in TARGET_BARRAGES_ORDER
        ]

        volume_normal_current = base_current + sum(
            _abhl_sq_num(data["normal_rows"][code].get("volume_normal_current"))
            for code in dynamic_codes
        )

        volume_normal_old = base_old + sum(
            _abhl_sq_num(data["normal_rows"][code].get("volume_normal_old"))
            for code in dynamic_codes
        )

        volume_jour = sum(
            _abhl_sq_num(data["normal_rows"][code].get("volume_jour"))
            for code in codes
        )

        volume_annee_precedente = sum(
            _abhl_sq_num(data["normal_rows"][code].get("volume_annee_precedente"))
            for code in codes
        )

    return {
        "volume_normal_current": volume_normal_current,
        "volume_normal_old": volume_normal_old,
        "volume_jour": volume_jour,
        "taux_remplissage": safe_rate(volume_jour, volume_normal_current),
        "volume_annee_precedente": volume_annee_precedente,
        "taux_annee_precedente": safe_rate(volume_annee_precedente, volume_normal_old),
    }


def _abhl_sq_group_code_for_barrage(data: dict, code: str) -> str | None:
    if code in ["BOEM", "DAR_KHROFA"]:
        return "LOUKKOS_TOTAL"
    if code in ["BIB", "9_AVRIL", "KHARROUB", "TANGER_MED"]:
        return "TANGER_TOTAL"
    if code in ["NAKHLA", "SMIR", "MHB_MEHDI", "CAI"]:
        return "TETOUAN_TOTAL"
    if code in ["KHATTABI", "JOUMOUA"]:
        return "AL_HOCEIMA_TOTAL"
    if code == "CHEFCHAOUEN":
        return "CHEFCHAOUEN"

    agence = (data.get("barrages", {}).get(code, {}).get("agence_code") or "").upper()

    if agence == "LOUKKOS":
        return "LOUKKOS_TOTAL"
    if agence == "TANGER":
        return "TANGER_TOTAL"
    if agence == "TETOUAN":
        return "TETOUAN_TOTAL"
    if agence == "AL_HOCEIMA":
        return "AL_HOCEIMA_TOTAL"
    if agence == "CHEFCHAOUEN":
        return "CHEFCHAOUEN"

    return None


def _abhl_sq_codes_for_group(data: dict, group_code: str) -> list[str]:
    result = []

    if group_code in SUMMARY_GROUPS:
        result.extend([code for code in SUMMARY_GROUPS[group_code] if code in data["normal_rows"]])

    for code in _abhl_sq_dynamic_codes(data):
        if _abhl_sq_group_code_for_barrage(data, code) == group_code:
            result.append(code)

    return result


def _abhl_sq_barrage_name_fr(data: dict, code: str) -> str:
    if code in FRA_BARRAGE_NAMES:
        return FRA_BARRAGE_NAMES[code]

    barrage = data.get("barrages", {}).get(code, {})
    return barrage.get("nom_court") or barrage.get("nom") or code


def fill_situation_fra(ws, data: dict):
    d = data["dates"]["date_situation"]

    write_cell(ws, "A6", f" SITUATION DES BARRAGES AU {fr_date_long(d)}")

    for code in SUMMARY_INDIVIDUAL_CODES:
        excel_row = SUMMARY_ROWS[code]
        values = get_row_summary_values(data, code)

        write_cell(ws, f"D{excel_row}", FRA_BARRAGE_NAMES[code])
        write_summary_fra_row(ws, excel_row, values)

    for group_code, original_codes in SUMMARY_GROUPS.items():
        excel_row = SUMMARY_ROWS[group_code]
        codes = _abhl_sq_codes_for_group(data, group_code)
        values = _abhl_sq_summary_values_for_codes(data, codes, group_code)

        if group_code == "TOTAL":
            write_cell(ws, f"C{excel_row}", "Total")
        else:
            write_cell(ws, f"C{excel_row}", "Sous-Total")

        write_summary_fra_row(ws, excel_row, values)

    # Bloc visible des nouveaux barrages, après le tableau officiel.
    dynamic_codes = _abhl_sq_dynamic_codes(data)

    if dynamic_codes:
        start_row = 29
        ws.insert_rows(start_row, amount=len(dynamic_codes) + 1)

        write_cell(ws, f"C{start_row}", "Barrages ajoutés")
        write_cell(ws, f"D{start_row}", "Barrage")
        write_cell(ws, f"E{start_row}", "Capacité normale")
        write_cell(ws, f"F{start_row}", "Volume")
        write_cell(ws, f"G{start_row}", "Taux")
        write_cell(ws, f"H{start_row}", "Volume N-1")
        write_cell(ws, f"I{start_row}", "Taux N-1")

        for offset, code in enumerate(dynamic_codes, start=1):
            row = start_row + offset
            values = get_row_summary_values(data, code)
            write_cell(ws, f"C{row}", "Ajouté")
            write_cell(ws, f"D{row}", _abhl_sq_barrage_name_fr(data, code))
            write_summary_fra_row(ws, row, values)

        try:
            ws.print_area = f"A1:M{start_row + len(dynamic_codes) + 2}"
        except Exception:
            pass


def fill_situation_ar(ws, data: dict):
    d = data["dates"]["date_situation"]

    mois_ar = [
        "",
        " يناير ",
        " فبراير ",
        " مارس ",
        " أبريل ",
        " ماي ",
        " يونيو ",
        " يوليوز ",
        " غشت ",
        " شتنبر ",
        " أكتوبر ",
        " نونبر ",
        " دجنبر ",
    ]

    write_cell(ws, "A6", f" حالة ملء السدود بتاريخ {d.day}{mois_ar[d.month]}{d.year}")

    for code in SUMMARY_INDIVIDUAL_CODES:
        excel_row = SUMMARY_ROWS[code]
        values = get_row_summary_values(data, code)

        write_summary_ar_row(ws, excel_row, values)
        write_summary_ar_right_table_row(ws, excel_row, values)

    for group_code, original_codes in SUMMARY_GROUPS.items():
        excel_row = SUMMARY_ROWS[group_code]
        codes = _abhl_sq_codes_for_group(data, group_code)
        values = _abhl_sq_summary_values_for_codes(data, codes, group_code)

        write_summary_ar_row(ws, excel_row, values)
        write_summary_ar_right_table_row(ws, excel_row, values)

    dynamic_codes = _abhl_sq_dynamic_codes(data)

    if dynamic_codes:
        start_row = 29
        ws.insert_rows(start_row, amount=len(dynamic_codes) + 1)

        write_cell(ws, f"H{start_row}", "السدود المضافة")
        write_cell(ws, f"G{start_row}", "الحجم العادي")
        write_cell(ws, f"F{start_row}", "الحجم")
        write_cell(ws, f"E{start_row}", "نسبة الملء")

        for offset, code in enumerate(dynamic_codes, start=1):
            row = start_row + offset
            values = get_row_summary_values(data, code)
            write_cell(ws, f"H{row}", _abhl_sq_barrage_name_fr(data, code))
            write_summary_ar_row(ws, row, values)
            write_summary_ar_right_table_row(ws, row, values)

        try:
            ws.print_area = f"A1:O{start_row + len(dynamic_codes) + 2}"
        except Exception:
            pass


def _abhl_sq_loukkos_dynamic_codes(data: dict) -> list[str]:
    return [
        code for code in _abhl_sq_dynamic_codes(data)
        if _abhl_sq_group_code_for_barrage(data, code) == "LOUKKOS_TOTAL"
    ]


def fill_ormval(ws, data: dict):
    d = data["dates"]["date_situation"]

    write_cell(
        ws,
        "B10",
        f" SITUATION DES BARRAGES RELEVANT DE LA PROVINCE DE LARACHE AU {fr_date_long(d)}",
    )

    boem = data["normal_rows"]["BOEM"]
    dar = data["normal_rows"]["DAR_KHROFA"]

    write_cell(ws, "D16", boem["cote_jour"])
    write_cell(ws, "F16", boem["volume_jour"])
    write_cell(ws, "G16", boem["taux_remplissage"])
    write_cell(ws, "H16", boem["lachers"].get("F", 0.0))
    write_cell(ws, "I16", boem["lachers"].get("G", 0.0))
    write_cell(ws, "J16", boem["lachers"].get("H", 0.0))

    write_cell(ws, "D17", dar["cote_jour"])
    write_cell(ws, "F17", dar["volume_jour"])
    write_cell(ws, "G17", dar["taux_remplissage"])
    write_cell(ws, "J17", dar["lachers"].get("H", 0.0))

    loukkos_dynamic = _abhl_sq_loukkos_dynamic_codes(data)

    if loukkos_dynamic:
        ws.insert_rows(18, amount=len(loukkos_dynamic))

        for offset, code in enumerate(loukkos_dynamic):
            row = 18 + offset
            _abhl_sq_copy_row_style(ws, 17, row, 12)
            item = data["normal_rows"][code]

            write_cell(ws, f"C{row}", _abhl_sq_barrage_name_fr(data, code))
            write_cell(ws, f"D{row}", item["cote_jour"])
            write_cell(ws, f"F{row}", item["volume_jour"])
            write_cell(ws, f"G{row}", item["taux_remplissage"])
            write_cell(ws, f"J{row}", item["lachers"].get("H", 0.0))

    garde_row = 19 + len(loukkos_dynamic)
    write_cell(ws, f"D{garde_row}", data["specials"]["garde_loukkos_amont"])
    write_cell(ws, f"E{garde_row}", data["specials"]["garde_loukkos_aval"])


def fill_ormval_vt(ws, data: dict):
    d = data["dates"]["date_situation"]

    write_cell(
        ws,
        "B10",
        f" SITUATION DES BARRAGES RELEVANT DE LA PROVINCE DE LARACHE AU {fr_date_long(d)}",
    )

    boem = data["transfer_rows"]["BOEM"]
    dar = data["transfer_rows"]["DAR_KHROFA"]

    write_cell(ws, "D16", boem["cote_jour"])
    write_cell(ws, "F16", boem["volume_jour"])
    write_cell(ws, "G16", boem["taux_remplissage"])
    write_cell(ws, "H16", boem["lachers"].get("F", 0.0))
    write_cell(ws, "I16", boem["lachers"].get("G", 0.0))
    write_cell(ws, "J16", boem["lachers"].get("H", 0.0))
    write_cell(ws, "K16", boem["lachers"].get("I", 0.0))

    write_cell(ws, "D17", dar["cote_jour"])
    write_cell(ws, "F17", dar["volume_jour"])
    write_cell(ws, "G17", dar["taux_remplissage"])
    write_cell(ws, "K17", dar["lachers"].get("I", 0.0))

    loukkos_dynamic = _abhl_sq_loukkos_dynamic_codes(data)

    if loukkos_dynamic:
        ws.insert_rows(18, amount=len(loukkos_dynamic))

        for offset, code in enumerate(loukkos_dynamic):
            row = 18 + offset
            _abhl_sq_copy_row_style(ws, 17, row, 13)
            item = data["transfer_rows"][code]

            write_cell(ws, f"C{row}", _abhl_sq_barrage_name_fr(data, code))
            write_cell(ws, f"D{row}", item["cote_jour"])
            write_cell(ws, f"F{row}", item["volume_jour"])
            write_cell(ws, f"G{row}", item["taux_remplissage"])
            write_cell(ws, f"K{row}", item["lachers"].get("I", 0.0))

    garde_row = 19 + len(loukkos_dynamic)
    write_cell(ws, f"D{garde_row}", data["specials"]["garde_loukkos_amont"])
    write_cell(ws, f"E{garde_row}", data["specials"]["garde_loukkos_aval"])

# === ABHL SITUATION DYNAMIQUE V2 PATCH END ===

# === ABHL SITUATION DYNAMIC FIX CAPACITY V1 START ===
# Correction visuelle : élargir les colonnes sensibles pour éviter les ######
# après ajout de nouveaux barrages.

def _abhl_sq_adjust_situation_widths(output_path):
    try:
        from openpyxl import load_workbook
    except Exception:
        return

    wb = load_workbook(output_path)

    if "Situation Détaillée" in wb.sheetnames:
        ws = wb["Situation Détaillée"]

        widths = {
            "A": 22,
            "B": 10,
            "C": 10,
            "D": 10,
            "E": 10,
            "F": 12,
            "G": 10,
            "H": 12,
            "I": 12,
            "J": 10,
            "K": 12,
            "M": 12,
            "N": 10,
            "O": 12,
            "P": 10,
            "Q": 8,
            "T": 12,
            "U": 12,
            "V": 12,
        }

        for col, width in widths.items():
            ws.column_dimensions[col].width = width

    if "Situation Détaillée (T)" in wb.sheetnames:
        ws = wb["Situation Détaillée (T)"]

        widths = {
            "A": 22,
            "B": 10,
            "C": 10,
            "D": 10,
            "E": 10,
            "F": 12,
            "G": 10,
            "H": 10,
            "I": 12,
            "J": 12,
            "K": 10,
            "L": 12,
            "N": 12,
            "O": 10,
            "P": 12,
            "Q": 10,
            "R": 8,
        }

        for col, width in widths.items():
            ws.column_dimensions[col].width = width

    if "Situation FRA" in wb.sheetnames:
        ws = wb["Situation FRA"]
        for col, width in {
            "C": 18,
            "D": 22,
            "E": 14,
            "F": 14,
            "G": 12,
            "H": 14,
            "I": 12,
        }.items():
            ws.column_dimensions[col].width = width

    if "Situation AR" in wb.sheetnames:
        ws = wb["Situation AR"]
        for col, width in {
            "E": 12,
            "F": 14,
            "G": 14,
            "H": 22,
            "M": 14,
            "N": 14,
            "O": 14,
        }.items():
            ws.column_dimensions[col].width = width

    wb.save(output_path)


if "_abhl_sq_original_generate_situation_excel_capacity_fix" not in globals():
    _abhl_sq_original_generate_situation_excel_capacity_fix = generate_situation_excel


def generate_situation_excel(db, date_situation):
    output_path = _abhl_sq_original_generate_situation_excel_capacity_fix(db, date_situation)
    _abhl_sq_adjust_situation_widths(output_path)
    return output_path

# === ABHL SITUATION DYNAMIC FIX CAPACITY V1 END ===

# === ABHL SITUATION GROUPED ORDER + SUBTOTALS V1 START ===
# Correctif professionnel des feuilles FRA/AR :
# - intégration des nouveaux barrages dans leur système
# - suppression du bloc séparé "Barrages ajoutés"
# - sous-totaux recalculés par système
# - N-1 vide si le nouveau barrage n'a pas d'historique

_ABHL_SQ_EXCEL_GROUP_ORDER = [
    ("LOUKKOS_TOTAL", "Loukkos", "اللوكوس"),
    ("TANGER_TOTAL", "Tanger", "طنجة"),
    ("TETOUAN_TOTAL", "Tétouan", "تطوان"),
    ("AL_HOCEIMA_TOTAL", "Al Hoceima", "الحسيمة"),
    ("CHEFCHAOUEN", "Chefchaouen", "شفشاون"),
]

_ABHL_SQ_EXCEL_OFFICIAL_GROUPS = {
    "LOUKKOS_TOTAL": ["BOEM", "DAR_KHROFA"],
    "TANGER_TOTAL": ["BIB", "9_AVRIL", "KHARROUB", "TANGER_MED"],
    "TETOUAN_TOTAL": ["NAKHLA", "SMIR", "MHB_MEHDI", "CAI"],
    "AL_HOCEIMA_TOTAL": ["KHATTABI", "JOUMOUA"],
    "CHEFCHAOUEN": ["CHEFCHAOUEN"],
}


def _abhl_sq_group_for_code_from_data(data: dict, code: str):
    if "normal_rows" in data and code in data["normal_rows"]:
        group = data["normal_rows"][code].get("group_code")
        if group:
            return group

    for group, codes in _ABHL_SQ_EXCEL_OFFICIAL_GROUPS.items():
        if code in codes:
            return group

    agence = ((data.get("barrages") or {}).get(code) or {}).get("agence_code")
    agence = (agence or "").upper()

    if agence == "LOUKKOS":
        return "LOUKKOS_TOTAL"
    if agence == "TANGER":
        return "TANGER_TOTAL"
    if agence == "TETOUAN":
        return "TETOUAN_TOTAL"
    if agence == "AL_HOCEIMA":
        return "AL_HOCEIMA_TOTAL"
    if agence == "CHEFCHAOUEN":
        return "CHEFCHAOUEN"

    return None


def _abhl_sq_codes_for_excel_group(data: dict, group_code: str) -> list[str]:
    all_codes = data.get("situation_codes") or list((data.get("normal_rows") or {}).keys())
    result = [code for code in all_codes if _abhl_sq_group_for_code_from_data(data, code) == group_code]
    return result


def _abhl_sq_display_name(data: dict, code: str) -> str:
    if code in FRA_BARRAGE_NAMES:
        return FRA_BARRAGE_NAMES[code]

    barrage = (data.get("barrages") or {}).get(code) or {}
    return barrage.get("nom_court") or barrage.get("nom") or code


def _abhl_sq_has_n1(data: dict, code: str) -> bool:
    row = (data.get("normal_rows") or {}).get(code) or {}
    return row.get("volume_annee_precedente") is not None


def _abhl_sq_summary_group(data: dict, codes: list[str]) -> dict:
    current_capacity = 0.0
    current_volume = 0.0

    n1_capacity = 0.0
    n1_volume = 0.0
    has_any_n1 = False

    for code in codes:
        row = data["normal_rows"][code]

        current_capacity += _abhl_sq_num(row.get("volume_normal_current"))
        current_volume += _abhl_sq_num(row.get("volume_jour"))

        if row.get("volume_annee_precedente") is not None:
            has_any_n1 = True
            n1_capacity += _abhl_sq_num(row.get("volume_normal_old"))
            n1_volume += _abhl_sq_num(row.get("volume_annee_precedente"))

    return {
        "volume_normal_current": current_capacity,
        "volume_jour": current_volume,
        "taux_remplissage": safe_rate(current_volume, current_capacity),
        "volume_annee_precedente": n1_volume if has_any_n1 else None,
        "taux_annee_precedente": safe_rate(n1_volume, n1_capacity) if has_any_n1 else None,
    }


def _abhl_sq_summary_individual(data: dict, code: str) -> dict:
    row = data["normal_rows"][code]

    return {
        "volume_normal_current": row.get("volume_normal_current"),
        "volume_jour": row.get("volume_jour"),
        "taux_remplissage": row.get("taux_remplissage"),
        "volume_annee_precedente": row.get("volume_annee_precedente"),
        "taux_annee_precedente": row.get("taux_annee_precedente"),
    }


def _abhl_sq_summary_total(data: dict) -> dict:
    totals = data["normal_totals"]

    return {
        "volume_normal_current": totals.get("B"),
        "volume_jour": totals.get("D"),
        "taux_remplissage": totals.get("N"),
        "volume_annee_precedente": totals.get("O"),
        "taux_annee_precedente": totals.get("P"),
    }


def _abhl_sq_unmerge_range(ws, min_row: int, max_row: int, min_col: int, max_col: int):
    ranges_to_unmerge = []

    for merged_range in list(ws.merged_cells.ranges):
        if (
            merged_range.min_row <= max_row
            and merged_range.max_row >= min_row
            and merged_range.min_col <= max_col
            and merged_range.max_col >= min_col
        ):
            ranges_to_unmerge.append(str(merged_range))

    for range_string in ranges_to_unmerge:
        ws.unmerge_cells(range_string)


def _abhl_sq_clear_area(ws, min_row=1, max_row=80, min_col=1, max_col=12):
    _abhl_sq_unmerge_range(ws, min_row, max_row, min_col, max_col)

    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            cell = ws.cell(row=row, column=col)
            cell.value = None


def _abhl_sq_apply_border(ws, min_row, max_row, min_col, max_col, border):
    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            ws.cell(row=row, column=col).border = border


def _abhl_sq_style_range(ws, min_row, max_row, min_col, max_col, fill=None, font=None, alignment=None, border=None):
    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            cell = ws.cell(row=row, column=col)
            if fill is not None:
                cell.fill = fill
            if font is not None:
                cell.font = font
            if alignment is not None:
                cell.alignment = alignment
            if border is not None:
                cell.border = border


def _abhl_sq_write_num_or_dash(ws, row: int, col: int, value, number_format="#,##0.0"):
    cell = ws.cell(row=row, column=col)

    if value is None:
        cell.value = "-"
        return

    cell.value = value
    cell.number_format = number_format


def _abhl_sq_write_rate_or_dash(ws, row: int, col: int, value):
    cell = ws.cell(row=row, column=col)

    if value is None:
        cell.value = "-"
        return

    cell.value = value
    cell.number_format = "0"


def _abhl_sq_fra_write_values(ws, row: int, values: dict):
    _abhl_sq_write_num_or_dash(ws, row, 5, values.get("volume_normal_current"))
    _abhl_sq_write_num_or_dash(ws, row, 6, values.get("volume_jour"))
    _abhl_sq_write_rate_or_dash(ws, row, 7, values.get("taux_remplissage"))
    _abhl_sq_write_num_or_dash(ws, row, 8, values.get("volume_annee_precedente"))
    _abhl_sq_write_rate_or_dash(ws, row, 9, values.get("taux_annee_precedente"))


def _abhl_sq_ar_write_values(ws, row: int, values: dict):
    _abhl_sq_write_num_or_dash(ws, row, 5, values.get("volume_normal_current"))
    _abhl_sq_write_num_or_dash(ws, row, 6, values.get("volume_jour"))
    _abhl_sq_write_rate_or_dash(ws, row, 7, values.get("taux_remplissage"))
    _abhl_sq_write_num_or_dash(ws, row, 8, values.get("volume_annee_precedente"))
    _abhl_sq_write_rate_or_dash(ws, row, 9, values.get("taux_annee_precedente"))


def _abhl_sq_make_summary_styles():
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

    thin = Side(style="thin", color="000000")

    return {
        "title_font": Font(name="Calibri", size=16, bold=True),
        "header_font": Font(name="Calibri", size=10, bold=True),
        "normal_font": Font(name="Calibri", size=10),
        "bold_font": Font(name="Calibri", size=10, bold=True),
        "title_align": Alignment(horizontal="center", vertical="center"),
        "center": Alignment(horizontal="center", vertical="center", wrap_text=True),
        "left": Alignment(horizontal="left", vertical="center", wrap_text=True),
        "right": Alignment(horizontal="right", vertical="center", wrap_text=True),
        "gray": PatternFill("solid", fgColor="D9D9D9"),
        "light_gray": PatternFill("solid", fgColor="F2F2F2"),
        "white": PatternFill("solid", fgColor="FFFFFF"),
        "border": Border(left=thin, right=thin, top=thin, bottom=thin),
    }


def fill_situation_fra(ws, data: dict):
    styles = _abhl_sq_make_summary_styles()
    d = data["dates"]["date_situation"]

    _abhl_sq_clear_area(ws, 1, 90, 1, 12)

    ws.merge_cells(start_row=6, start_column=3, end_row=6, end_column=9)
    title_cell = ws.cell(row=6, column=3, value=f"SITUATION DES BARRAGES AU {fr_date_long(d)}")
    title_cell.font = styles["title_font"]
    title_cell.alignment = styles["title_align"]

    header_row = 8
    headers = [
        "Système",
        "Barrage",
        "Capacité normale\n(Mm³)",
        "Volume\n(Mm³)",
        "Taux de\nremplissage (%)",
        "Volume N-1\n(Mm³)",
        "Taux N-1\n(%)",
    ]

    for offset, header in enumerate(headers, start=3):
        cell = ws.cell(row=header_row, column=offset, value=header)
        cell.fill = styles["light_gray"]
        cell.font = styles["header_font"]
        cell.alignment = styles["center"]
        cell.border = styles["border"]

    row = header_row + 1

    for group_code, system_label, _ in _ABHL_SQ_EXCEL_GROUP_ORDER:
        codes = _abhl_sq_codes_for_excel_group(data, group_code)

        if not codes:
            continue

        group_start = row

        for code in codes:
            ws.cell(row=row, column=3, value=system_label if row == group_start else "")
            ws.cell(row=row, column=4, value=_abhl_sq_display_name(data, code))
            _abhl_sq_fra_write_values(ws, row, _abhl_sq_summary_individual(data, code))

            for col in range(3, 10):
                ws.cell(row=row, column=col).border = styles["border"]
                ws.cell(row=row, column=col).alignment = styles["center"]

            ws.cell(row=row, column=4).alignment = styles["left"]

            row += 1

        if len(codes) > 1:
            subtotal = _abhl_sq_summary_group(data, codes)

            ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=4)
            ws.cell(row=row, column=3, value="Sous-Total")
            _abhl_sq_fra_write_values(ws, row, subtotal)

            _abhl_sq_style_range(ws, row, row, 3, 9, fill=styles["gray"], font=styles["bold_font"], alignment=styles["center"], border=styles["border"])

            row += 1

    total = _abhl_sq_summary_total(data)

    ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=4)
    ws.cell(row=row, column=3, value="Total")
    _abhl_sq_fra_write_values(ws, row, total)

    _abhl_sq_style_range(ws, row, row, 3, 9, fill=styles["gray"], font=styles["bold_font"], alignment=styles["center"], border=styles["border"])

    for col, width in {
        "C": 16,
        "D": 26,
        "E": 14,
        "F": 14,
        "G": 14,
        "H": 14,
        "I": 14,
    }.items():
        ws.column_dimensions[col].width = width

    for r in range(header_row, row + 1):
        ws.row_dimensions[r].height = 25

    try:
        ws.print_area = f"C6:I{row}"
    except Exception:
        pass


def fill_situation_ar(ws, data: dict):
    styles = _abhl_sq_make_summary_styles()
    d = data["dates"]["date_situation"]

    mois_ar = [
        "",
        " يناير ",
        " فبراير ",
        " مارس ",
        " أبريل ",
        " ماي ",
        " يونيو ",
        " يوليوز ",
        " غشت ",
        " شتنبر ",
        " أكتوبر ",
        " نونبر ",
        " دجنبر ",
    ]

    _abhl_sq_clear_area(ws, 1, 90, 1, 12)

    ws.sheet_view.rightToLeft = True

    ws.merge_cells(start_row=6, start_column=3, end_row=6, end_column=9)
    title_cell = ws.cell(row=6, column=3, value=f"حالة ملء السدود بتاريخ {d.day}{mois_ar[d.month]}{d.year}")
    title_cell.font = styles["title_font"]
    title_cell.alignment = styles["title_align"]

    header_row = 8
    headers = [
        "المنظومة",
        "السد",
        "الحجم العادي\n(مليون م³)",
        "الحجم\n(مليون م³)",
        "نسبة الملء\n(%)",
        "الحجم ن-1\n(مليون م³)",
        "نسبة ن-1\n(%)",
    ]

    for offset, header in enumerate(headers, start=3):
        cell = ws.cell(row=header_row, column=offset, value=header)
        cell.fill = styles["light_gray"]
        cell.font = styles["header_font"]
        cell.alignment = styles["center"]
        cell.border = styles["border"]

    row = header_row + 1

    for group_code, _, system_label_ar in _ABHL_SQ_EXCEL_GROUP_ORDER:
        codes = _abhl_sq_codes_for_excel_group(data, group_code)

        if not codes:
            continue

        group_start = row

        for code in codes:
            ws.cell(row=row, column=3, value=system_label_ar if row == group_start else "")
            ws.cell(row=row, column=4, value=_abhl_sq_display_name(data, code))
            _abhl_sq_ar_write_values(ws, row, _abhl_sq_summary_individual(data, code))

            for col in range(3, 10):
                ws.cell(row=row, column=col).border = styles["border"]
                ws.cell(row=row, column=col).alignment = styles["center"]

            ws.cell(row=row, column=4).alignment = styles["right"]

            row += 1

        if len(codes) > 1:
            subtotal = _abhl_sq_summary_group(data, codes)

            ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=4)
            ws.cell(row=row, column=3, value="المجموع الجزئي")
            _abhl_sq_ar_write_values(ws, row, subtotal)

            _abhl_sq_style_range(ws, row, row, 3, 9, fill=styles["gray"], font=styles["bold_font"], alignment=styles["center"], border=styles["border"])

            row += 1

    total = _abhl_sq_summary_total(data)

    ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=4)
    ws.cell(row=row, column=3, value="المجموع")
    _abhl_sq_ar_write_values(ws, row, total)

    _abhl_sq_style_range(ws, row, row, 3, 9, fill=styles["gray"], font=styles["bold_font"], alignment=styles["center"], border=styles["border"])

    for col, width in {
        "C": 18,
        "D": 26,
        "E": 14,
        "F": 14,
        "G": 14,
        "H": 14,
        "I": 14,
    }.items():
        ws.column_dimensions[col].width = width

    for r in range(header_row, row + 1):
        ws.row_dimensions[r].height = 25

    try:
        ws.print_area = f"C6:I{row}"
    except Exception:
        pass

# === ABHL SITUATION GROUPED ORDER + SUBTOTALS V1 END ===

# === ABHL SITUATION DESIGN FIX FRA AR V1 START ===
# Correction design uniquement :
# - les lignes de barrages sont blanches
# - seules les lignes Sous-Total et Total sont grises
# - la colonne Système est fusionnée verticalement par groupe
# - les nouveaux barrages restent dans leur vrai système/agence

def _abhl_sq_make_summary_styles_v2():
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

    thin = Side(style="thin", color="000000")

    return {
        "title_font": Font(name="Calibri", size=16, bold=True),
        "header_font": Font(name="Calibri", size=10, bold=True),
        "normal_font": Font(name="Calibri", size=10),
        "bold_font": Font(name="Calibri", size=10, bold=True),
        "title_align": Alignment(horizontal="center", vertical="center"),
        "center": Alignment(horizontal="center", vertical="center", wrap_text=True),
        "left": Alignment(horizontal="left", vertical="center", wrap_text=True),
        "right": Alignment(horizontal="right", vertical="center", wrap_text=True),
        "gray": PatternFill("solid", fgColor="D9D9D9"),
        "light_gray": PatternFill("solid", fgColor="F2F2F2"),
        "white": PatternFill("solid", fgColor="FFFFFF"),
        "border": Border(left=thin, right=thin, top=thin, bottom=thin),
    }


def _abhl_sq_style_body_row(ws, row: int, min_col: int, max_col: int, styles: dict):
    for col in range(min_col, max_col + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = styles["white"]
        cell.font = styles["normal_font"]
        cell.alignment = styles["center"]
        cell.border = styles["border"]


def _abhl_sq_style_group_cell(ws, start_row: int, end_row: int, col: int, value: str, styles: dict, rtl: bool = False):
    if end_row > start_row:
        ws.merge_cells(start_row=start_row, start_column=col, end_row=end_row, end_column=col)

    cell = ws.cell(row=start_row, column=col)
    cell.value = value
    cell.fill = styles["white"]
    cell.font = styles["normal_font"]
    cell.alignment = styles["center"]
    cell.border = styles["border"]

    for row in range(start_row, end_row + 1):
        ws.cell(row=row, column=col).fill = styles["white"]
        ws.cell(row=row, column=col).font = styles["normal_font"]
        ws.cell(row=row, column=col).alignment = styles["center"]
        ws.cell(row=row, column=col).border = styles["border"]


def _abhl_sq_write_num_or_dash_v2(ws, row: int, col: int, value, number_format="#,##0.0"):
    cell = ws.cell(row=row, column=col)

    if value is None:
        cell.value = "-"
        return

    cell.value = value
    cell.number_format = number_format


def _abhl_sq_write_rate_or_dash_v2(ws, row: int, col: int, value):
    cell = ws.cell(row=row, column=col)

    if value is None:
        cell.value = "-"
        return

    cell.value = value
    cell.number_format = "0"


def _abhl_sq_fra_write_values_v2(ws, row: int, values: dict):
    _abhl_sq_write_num_or_dash_v2(ws, row, 5, values.get("volume_normal_current"))
    _abhl_sq_write_num_or_dash_v2(ws, row, 6, values.get("volume_jour"))
    _abhl_sq_write_rate_or_dash_v2(ws, row, 7, values.get("taux_remplissage"))
    _abhl_sq_write_num_or_dash_v2(ws, row, 8, values.get("volume_annee_precedente"))
    _abhl_sq_write_rate_or_dash_v2(ws, row, 9, values.get("taux_annee_precedente"))


def _abhl_sq_ar_write_values_v2(ws, row: int, values: dict):
    _abhl_sq_write_num_or_dash_v2(ws, row, 5, values.get("volume_normal_current"))
    _abhl_sq_write_num_or_dash_v2(ws, row, 6, values.get("volume_jour"))
    _abhl_sq_write_rate_or_dash_v2(ws, row, 7, values.get("taux_remplissage"))
    _abhl_sq_write_num_or_dash_v2(ws, row, 8, values.get("volume_annee_precedente"))
    _abhl_sq_write_rate_or_dash_v2(ws, row, 9, values.get("taux_annee_precedente"))


def _abhl_sq_style_subtotal_row(ws, row: int, label: str, styles: dict):
    ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=4)
    ws.cell(row=row, column=3, value=label)

    for col in range(3, 10):
        cell = ws.cell(row=row, column=col)
        cell.fill = styles["gray"]
        cell.font = styles["bold_font"]
        cell.alignment = styles["center"]
        cell.border = styles["border"]


def fill_situation_fra(ws, data: dict):
    styles = _abhl_sq_make_summary_styles_v2()
    d = data["dates"]["date_situation"]

    _abhl_sq_clear_area(ws, 1, 100, 1, 12)

    ws.merge_cells(start_row=6, start_column=3, end_row=6, end_column=9)
    title_cell = ws.cell(row=6, column=3, value=f"SITUATION DES BARRAGES AU {fr_date_long(d)}")
    title_cell.font = styles["title_font"]
    title_cell.alignment = styles["title_align"]

    header_row = 8
    headers = [
        "Système",
        "Barrage",
        "Capacité normale\n(Mm³)",
        "Volume\n(Mm³)",
        "Taux de\nremplissage (%)",
        "Volume N-1\n(Mm³)",
        "Taux N-1\n(%)",
    ]

    for offset, header in enumerate(headers, start=3):
        cell = ws.cell(row=header_row, column=offset, value=header)
        cell.fill = styles["light_gray"]
        cell.font = styles["header_font"]
        cell.alignment = styles["center"]
        cell.border = styles["border"]

    row = header_row + 1

    for group_code, system_label, _ in _ABHL_SQ_EXCEL_GROUP_ORDER:
        codes = _abhl_sq_codes_for_excel_group(data, group_code)

        if not codes:
            continue

        group_start = row

        for code in codes:
            _abhl_sq_style_body_row(ws, row, 3, 9, styles)

            ws.cell(row=row, column=4, value=_abhl_sq_display_name(data, code))
            ws.cell(row=row, column=4).alignment = styles["left"]

            _abhl_sq_fra_write_values_v2(ws, row, _abhl_sq_summary_individual(data, code))
            row += 1

        group_end = row - 1
        _abhl_sq_style_group_cell(ws, group_start, group_end, 3, system_label, styles)

        if len(codes) > 1:
            subtotal = _abhl_sq_summary_group(data, codes)
            _abhl_sq_style_subtotal_row(ws, row, "Sous-Total", styles)
            _abhl_sq_fra_write_values_v2(ws, row, subtotal)
            row += 1

    total = _abhl_sq_summary_total(data)
    _abhl_sq_style_subtotal_row(ws, row, "Total", styles)
    _abhl_sq_fra_write_values_v2(ws, row, total)

    for col, width in {
        "C": 16,
        "D": 26,
        "E": 14,
        "F": 14,
        "G": 14,
        "H": 14,
        "I": 14,
    }.items():
        ws.column_dimensions[col].width = width

    for r in range(header_row, row + 1):
        ws.row_dimensions[r].height = 25

    try:
        ws.print_area = f"C6:I{row}"
    except Exception:
        pass


def fill_situation_ar(ws, data: dict):
    styles = _abhl_sq_make_summary_styles_v2()
    d = data["dates"]["date_situation"]

    mois_ar = [
        "",
        " يناير ",
        " فبراير ",
        " مارس ",
        " أبريل ",
        " ماي ",
        " يونيو ",
        " يوليوز ",
        " غشت ",
        " شتنبر ",
        " أكتوبر ",
        " نونبر ",
        " دجنبر ",
    ]

    _abhl_sq_clear_area(ws, 1, 100, 1, 12)
    ws.sheet_view.rightToLeft = True

    ws.merge_cells(start_row=6, start_column=3, end_row=6, end_column=9)
    title_cell = ws.cell(row=6, column=3, value=f"حالة ملء السدود بتاريخ {d.day}{mois_ar[d.month]}{d.year}")
    title_cell.font = styles["title_font"]
    title_cell.alignment = styles["title_align"]

    header_row = 8
    headers = [
        "المنظومة",
        "السد",
        "الحجم العادي\n(مليون م³)",
        "الحجم\n(مليون م³)",
        "نسبة الملء\n(%)",
        "الحجم ن-1\n(مليون م³)",
        "نسبة ن-1\n(%)",
    ]

    for offset, header in enumerate(headers, start=3):
        cell = ws.cell(row=header_row, column=offset, value=header)
        cell.fill = styles["light_gray"]
        cell.font = styles["header_font"]
        cell.alignment = styles["center"]
        cell.border = styles["border"]

    row = header_row + 1

    for group_code, _, system_label_ar in _ABHL_SQ_EXCEL_GROUP_ORDER:
        codes = _abhl_sq_codes_for_excel_group(data, group_code)

        if not codes:
            continue

        group_start = row

        for code in codes:
            _abhl_sq_style_body_row(ws, row, 3, 9, styles)

            ws.cell(row=row, column=4, value=_abhl_sq_display_name(data, code))
            ws.cell(row=row, column=4).alignment = styles["right"]

            _abhl_sq_ar_write_values_v2(ws, row, _abhl_sq_summary_individual(data, code))
            row += 1

        group_end = row - 1
        _abhl_sq_style_group_cell(ws, group_start, group_end, 3, system_label_ar, styles, rtl=True)

        if len(codes) > 1:
            subtotal = _abhl_sq_summary_group(data, codes)
            _abhl_sq_style_subtotal_row(ws, row, "المجموع الجزئي", styles)
            _abhl_sq_ar_write_values_v2(ws, row, subtotal)
            row += 1

    total = _abhl_sq_summary_total(data)
    _abhl_sq_style_subtotal_row(ws, row, "المجموع", styles)
    _abhl_sq_ar_write_values_v2(ws, row, total)

    for col, width in {
        "C": 18,
        "D": 26,
        "E": 14,
        "F": 14,
        "G": 14,
        "H": 14,
        "I": 14,
    }.items():
        ws.column_dimensions[col].width = width

    for r in range(header_row, row + 1):
        ws.row_dimensions[r].height = 25

    try:
        ws.print_area = f"C6:I{row}"
    except Exception:
        pass

# === ABHL SITUATION DESIGN FIX FRA AR V1 END ===

# === ABHL SITUATION AR SECONDARY TABLE FINAL V1 START ===
# Correction finale de la feuille "Situation AR" :
# - reconstruit proprement la table arabe principale
# - reconstruit aussi la table secondaire des volumes
# - garde les nouveaux barrages dans leurs systèmes/agences
# - garde les N-1 des nouveaux barrages vides ("-") quand il n'y a pas d'historique
# - ne change pas les calculs, ne change pas la base de données

def _abhl_ar_final_month_name_ar(month: int) -> str:
    months = {
        1: "يناير",
        2: "فبراير",
        3: "مارس",
        4: "أبريل",
        5: "ماي",
        6: "يونيو",
        7: "يوليوز",
        8: "غشت",
        9: "شتنبر",
        10: "أكتوبر",
        11: "نونبر",
        12: "دجنبر",
    }
    return months.get(month, "")


def _abhl_ar_final_date_slash(d):
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def _abhl_ar_final_styles():
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

    thin = Side(style="thin", color="000000")

    return {
        "title_font": Font(name="Calibri", size=16, bold=True),
        "header_font": Font(name="Calibri", size=10, bold=True),
        "normal_font": Font(name="Calibri", size=10),
        "bold_font": Font(name="Calibri", size=10, bold=True),
        "title_align": Alignment(horizontal="center", vertical="center"),
        "center": Alignment(horizontal="center", vertical="center", wrap_text=True),
        "right": Alignment(horizontal="right", vertical="center", wrap_text=True),
        "left": Alignment(horizontal="left", vertical="center", wrap_text=True),
        "gray": PatternFill("solid", fgColor="D9D9D9"),
        "light_gray": PatternFill("solid", fgColor="F2F2F2"),
        "white": PatternFill("solid", fgColor="FFFFFF"),
        "border": Border(left=thin, right=thin, top=thin, bottom=thin),
    }


_ABHL_AR_FINAL_GROUP_ORDER = [
    ("LOUKKOS_TOTAL", "اللوكوس"),
    ("TANGER_TOTAL", "طنجة"),
    ("TETOUAN_TOTAL", "تطوان"),
    ("AL_HOCEIMA_TOTAL", "الحسيمة"),
    ("CHEFCHAOUEN", "شفشاون"),
]

_ABHL_AR_FINAL_OFFICIAL_GROUPS = {
    "LOUKKOS_TOTAL": ["BOEM", "DAR_KHROFA"],
    "TANGER_TOTAL": ["BIB", "9_AVRIL", "KHARROUB", "TANGER_MED"],
    "TETOUAN_TOTAL": ["NAKHLA", "SMIR", "MHB_MEHDI", "CAI"],
    "AL_HOCEIMA_TOTAL": ["KHATTABI", "JOUMOUA"],
    "CHEFCHAOUEN": ["CHEFCHAOUEN"],
}


def _abhl_ar_final_group_for_code(data: dict, code: str):
    row = (data.get("normal_rows") or {}).get(code) or {}
    if row.get("group_code"):
        return row.get("group_code")

    for group, codes in _ABHL_AR_FINAL_OFFICIAL_GROUPS.items():
        if code in codes:
            return group

    barrage = (data.get("barrages") or {}).get(code) or {}
    agence = (barrage.get("agence_code") or "").upper()

    if agence == "LOUKKOS":
        return "LOUKKOS_TOTAL"
    if agence == "TANGER":
        return "TANGER_TOTAL"
    if agence == "TETOUAN":
        return "TETOUAN_TOTAL"
    if agence == "AL_HOCEIMA":
        return "AL_HOCEIMA_TOTAL"
    if agence == "CHEFCHAOUEN":
        return "CHEFCHAOUEN"

    return None


def _abhl_ar_final_codes_for_group(data: dict, group_code: str) -> list[str]:
    codes = data.get("situation_codes") or list((data.get("normal_rows") or {}).keys())
    return [code for code in codes if _abhl_ar_final_group_for_code(data, code) == group_code]


def _abhl_ar_final_display_name(data: dict, code: str) -> str:
    try:
        if code in FRA_BARRAGE_NAMES:
            return FRA_BARRAGE_NAMES[code]
    except NameError:
        pass

    barrage = (data.get("barrages") or {}).get(code) or {}
    return barrage.get("nom_court") or barrage.get("nom") or code


def _abhl_ar_final_num(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except Exception:
        return 0.0


def _abhl_ar_final_rate(volume, capacity):
    v = _abhl_ar_final_num(volume)
    c = _abhl_ar_final_num(capacity)
    if c == 0:
        return None
    return min((v / c) * 100.0, 100.0)


def _abhl_ar_final_individual(data: dict, code: str) -> dict:
    row = (data.get("normal_rows") or {}).get(code) or {}

    return {
        "capacity": row.get("volume_normal_current"),
        "volume": row.get("volume_jour"),
        "rate": row.get("taux_remplissage"),
        "volume_n1": row.get("volume_annee_precedente"),
        "rate_n1": row.get("taux_annee_precedente"),
    }


def _abhl_ar_final_subtotal(data: dict, codes: list[str]) -> dict:
    capacity = 0.0
    volume = 0.0

    capacity_n1 = 0.0
    volume_n1 = 0.0
    has_n1 = False

    for code in codes:
        row = (data.get("normal_rows") or {}).get(code) or {}

        capacity += _abhl_ar_final_num(row.get("volume_normal_current"))
        volume += _abhl_ar_final_num(row.get("volume_jour"))

        if row.get("volume_annee_precedente") is not None:
            has_n1 = True
            capacity_n1 += _abhl_ar_final_num(row.get("volume_normal_old") or row.get("volume_normal_current"))
            volume_n1 += _abhl_ar_final_num(row.get("volume_annee_precedente"))

    return {
        "capacity": capacity,
        "volume": volume,
        "rate": _abhl_ar_final_rate(volume, capacity),
        "volume_n1": volume_n1 if has_n1 else None,
        "rate_n1": _abhl_ar_final_rate(volume_n1, capacity_n1) if has_n1 else None,
    }


def _abhl_ar_final_total(data: dict) -> dict:
    totals = data.get("normal_totals") or {}

    return {
        "capacity": totals.get("B"),
        "volume": totals.get("D"),
        "rate": totals.get("N"),
        "volume_n1": totals.get("O"),
        "rate_n1": totals.get("P"),
    }


def _abhl_ar_final_unmerge_area(ws, min_row: int, max_row: int, min_col: int, max_col: int):
    for merged_range in list(ws.merged_cells.ranges):
        if (
            merged_range.min_row <= max_row
            and merged_range.max_row >= min_row
            and merged_range.min_col <= max_col
            and merged_range.max_col >= min_col
        ):
            ws.unmerge_cells(str(merged_range))


def _abhl_ar_final_clear_area(ws, min_row=1, max_row=100, min_col=1, max_col=18):
    _abhl_ar_final_unmerge_area(ws, min_row, max_row, min_col, max_col)

    for r in range(min_row, max_row + 1):
        for c in range(min_col, max_col + 1):
            cell = ws.cell(row=r, column=c)
            cell.value = None
            cell.fill = _abhl_ar_final_styles()["white"]
            cell.border = _abhl_ar_final_styles()["border"]


def _abhl_ar_final_style_range(ws, min_row, max_row, min_col, max_col, fill, font, alignment, border):
    for r in range(min_row, max_row + 1):
        for c in range(min_col, max_col + 1):
            cell = ws.cell(row=r, column=c)
            cell.fill = fill
            cell.font = font
            cell.alignment = alignment
            cell.border = border


def _abhl_ar_final_write_number_or_dash(ws, row: int, col: int, value, number_format="#,##0.0"):
    cell = ws.cell(row=row, column=col)

    if value is None:
        cell.value = "-"
        return

    cell.value = value
    cell.number_format = number_format


def _abhl_ar_final_write_rate_or_dash(ws, row: int, col: int, value):
    cell = ws.cell(row=row, column=col)

    if value is None:
        cell.value = "-"
        return

    cell.value = value
    cell.number_format = "0"


def _abhl_ar_final_write_main_values(ws, row: int, values: dict):
    _abhl_ar_final_write_number_or_dash(ws, row, 5, values.get("capacity"))
    _abhl_ar_final_write_number_or_dash(ws, row, 6, values.get("volume"))
    _abhl_ar_final_write_rate_or_dash(ws, row, 7, values.get("rate"))
    _abhl_ar_final_write_number_or_dash(ws, row, 8, values.get("volume_n1"))
    _abhl_ar_final_write_rate_or_dash(ws, row, 9, values.get("rate_n1"))


def _abhl_ar_final_write_secondary_values(ws, row: int, values: dict):
    _abhl_ar_final_write_number_or_dash(ws, row, 12, values.get("capacity"))
    _abhl_ar_final_write_number_or_dash(ws, row, 13, values.get("volume"))
    _abhl_ar_final_write_number_or_dash(ws, row, 14, values.get("volume_n1"))


def _abhl_ar_final_style_body_row(ws, row: int, min_col: int, max_col: int, styles: dict):
    for c in range(min_col, max_col + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = styles["white"]
        cell.font = styles["normal_font"]
        cell.alignment = styles["center"]
        cell.border = styles["border"]


def _abhl_ar_final_style_subtotal_row(ws, row: int, min_col: int, max_col: int, styles: dict):
    for c in range(min_col, max_col + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = styles["gray"]
        cell.font = styles["bold_font"]
        cell.alignment = styles["center"]
        cell.border = styles["border"]


def _abhl_ar_final_merge_group_label(ws, start_row: int, end_row: int, col: int, label: str, styles: dict):
    if end_row > start_row:
        ws.merge_cells(start_row=start_row, start_column=col, end_row=end_row, end_column=col)

    cell = ws.cell(row=start_row, column=col)
    cell.value = label

    for r in range(start_row, end_row + 1):
        c = ws.cell(row=r, column=col)
        c.fill = styles["white"]
        c.font = styles["normal_font"]
        c.alignment = styles["center"]
        c.border = styles["border"]


def fill_situation_ar(ws, data: dict):
    styles = _abhl_ar_final_styles()
    d = data["dates"]["date_situation"]
    d_n1 = data["dates"]["date_annee_precedente"]

    ws.sheet_view.rightToLeft = True
    _abhl_ar_final_clear_area(ws, 1, 100, 1, 18)

    # Titre principal
    ws.merge_cells(start_row=6, start_column=3, end_row=6, end_column=9)
    title_cell = ws.cell(
        row=6,
        column=3,
        value=f"حالة ملء السدود بتاريخ {d.day} {_abhl_ar_final_month_name_ar(d.month)} {d.year}",
    )
    title_cell.font = styles["title_font"]
    title_cell.alignment = styles["title_align"]

    # Tableau principal
    header_row = 8
    main_headers = [
        "المنظومة",
        "السد",
        "الحجم العادي\n(مليون م³)",
        "الحجم\n(مليون م³)",
        "نسبة الملء\n(%)",
        "الحجم ن-1\n(مليون م³)",
        "نسبة ن-1\n(%)",
    ]

    for offset, header in enumerate(main_headers, start=3):
        cell = ws.cell(row=header_row, column=offset, value=header)
        cell.fill = styles["light_gray"]
        cell.font = styles["header_font"]
        cell.alignment = styles["center"]
        cell.border = styles["border"]

    # Tableau secondaire volumes
    secondary_start_col = 12
    ws.merge_cells(start_row=header_row, start_column=secondary_start_col, end_row=header_row, end_column=secondary_start_col)
    ws.cell(row=header_row, column=secondary_start_col, value="الحجم العادي\n(مليون م³)")

    ws.merge_cells(start_row=header_row, start_column=secondary_start_col + 1, end_row=header_row, end_column=secondary_start_col + 2)
    ws.cell(row=header_row, column=secondary_start_col + 1, value="الحجم (مليون م³)")

    ws.cell(row=header_row + 1, column=secondary_start_col, value="Volume normal\n(Mm3)")
    ws.cell(row=header_row + 1, column=secondary_start_col + 1, value=_abhl_ar_final_date_slash(d))
    ws.cell(row=header_row + 1, column=secondary_start_col + 2, value=_abhl_ar_final_date_slash(d_n1))

    _abhl_ar_final_style_range(
        ws,
        header_row,
        header_row + 1,
        secondary_start_col,
        secondary_start_col + 2,
        styles["light_gray"],
        styles["header_font"],
        styles["center"],
        styles["border"],
    )

    row = header_row + 1

    for group_code, group_label_ar in _ABHL_AR_FINAL_GROUP_ORDER:
        codes = _abhl_ar_final_codes_for_group(data, group_code)
        if not codes:
            continue

        group_start = row

        for code in codes:
            values = _abhl_ar_final_individual(data, code)

            _abhl_ar_final_style_body_row(ws, row, 3, 9, styles)
            ws.cell(row=row, column=4, value=_abhl_ar_final_display_name(data, code))
            ws.cell(row=row, column=4).alignment = styles["right"]
            _abhl_ar_final_write_main_values(ws, row, values)

            _abhl_ar_final_style_body_row(ws, row, secondary_start_col, secondary_start_col + 2, styles)
            _abhl_ar_final_write_secondary_values(ws, row, values)

            row += 1

        group_end = row - 1
        _abhl_ar_final_merge_group_label(ws, group_start, group_end, 3, group_label_ar, styles)

        if len(codes) > 1:
            subtotal = _abhl_ar_final_subtotal(data, codes)

            ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=4)
            ws.cell(row=row, column=3, value="المجموع الجزئي")
            _abhl_ar_final_style_subtotal_row(ws, row, 3, 9, styles)
            _abhl_ar_final_write_main_values(ws, row, subtotal)

            _abhl_ar_final_style_subtotal_row(ws, row, secondary_start_col, secondary_start_col + 2, styles)
            _abhl_ar_final_write_secondary_values(ws, row, subtotal)

            row += 1

    total = _abhl_ar_final_total(data)

    ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=4)
    ws.cell(row=row, column=3, value="المجموع")
    _abhl_ar_final_style_subtotal_row(ws, row, 3, 9, styles)
    _abhl_ar_final_write_main_values(ws, row, total)

    _abhl_ar_final_style_subtotal_row(ws, row, secondary_start_col, secondary_start_col + 2, styles)
    _abhl_ar_final_write_secondary_values(ws, row, total)

    # Dimensions et lisibilité
    for col, width in {
        "C": 18,
        "D": 26,
        "E": 14,
        "F": 14,
        "G": 14,
        "H": 14,
        "I": 14,
        "K": 3,
        "L": 16,
        "M": 16,
        "N": 16,
    }.items():
        ws.column_dimensions[col].width = width

    for r in range(6, row + 1):
        ws.row_dimensions[r].height = 25

    try:
        ws.print_area = f"C6:N{row}"
    except Exception:
        pass

# === ABHL SITUATION AR SECONDARY TABLE FINAL V1 END ===

# === ABHL SITUATION FINAL CLEAN EXPORT V1 START ===
# Post-traitement final des exports Situation quotidienne.
# Objectif :
# - ne modifie pas PostgreSQL
# - ne modifie pas les fichiers ABHL originaux
# - corrige uniquement le fichier Excel exporté
# - nettoie les cadres/bordures hors tableau
# - corrige les libellés Mm3 -> Mm³
# - corrige la colonne "Volume normal" de la table latérale à partir de Situation FRA

def _abhl_final_norm_text(value):
    import re
    if value is None:
        return ""
    text = str(value).strip()
    text = re.sub(r"^\s*\d+\.\s*", "", text)
    text = text.replace("é", "e").replace("è", "e").replace("ê", "e")
    text = text.replace("à", "a").replace("â", "a")
    text = text.replace("ï", "i").replace("î", "i")
    text = text.replace("ô", "o")
    text = re.sub(r"\s+", " ", text)
    return text.upper()


def _abhl_final_is_number(value):
    try:
        if value is None or value == "-":
            return False
        float(value)
        return True
    except Exception:
        return False


def _abhl_final_fix_m3_labels(wb):
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    value = cell.value
                    value = value.replace("Mm3", "Mm³")
                    value = value.replace("m3", "m³")
                    value = value.replace("M3", "M³")
                    value = value.replace("م3", "م³")
                    cell.value = value


def _abhl_final_build_fra_reference(wb):
    """
    Lit la page Situation FRA, qui contient la synthèse propre après nos corrections.
    Retourne :
    - capacities_by_order
    - total_capacity
    """
    if "Situation FRA" not in wb.sheetnames:
        return [], None

    ws = wb["Situation FRA"]

    capacities = []
    total_capacity = None

    for row in range(1, ws.max_row + 1):
        system = ws.cell(row=row, column=3).value
        barrage = ws.cell(row=row, column=4).value
        capacity = ws.cell(row=row, column=5).value

        barrage_norm = _abhl_final_norm_text(barrage)
        system_norm = _abhl_final_norm_text(system)

        if system_norm in {"SOUS-TOTAL", "TOTAL"}:
            if system_norm == "TOTAL" and _abhl_final_is_number(capacity):
                total_capacity = float(capacity)
            continue

        if barrage_norm and barrage_norm not in {"BARRAGE"} and _abhl_final_is_number(capacity):
            capacities.append(float(capacity))

    return capacities, total_capacity


def _abhl_final_clear_borders_outside_real_tables(ws):
    from openpyxl.styles import Border, PatternFill, Font, Alignment

    no_border = Border()
    no_fill = PatternFill(fill_type=None)
    normal_font = Font(name="Calibri", size=11)
    normal_align = Alignment(horizontal="general", vertical="bottom")

    # On enlève les cadres dans les zones vides uniquement.
    # On ne touche pas aux cellules qui contiennent des valeurs.
    for row in range(1, min(ws.max_row + 20, 120)):
        for col in range(1, min(ws.max_column + 10, 30)):
            cell = ws.cell(row=row, column=col)
            if cell.value is None:
                cell.border = no_border
                cell.fill = no_fill
                cell.font = normal_font
                cell.alignment = normal_align


def _abhl_final_patch_situation_ar(ws):
    """
    Nettoie la feuille Situation AR :
    - enlève les cadres hors tableau
    - corrige la table secondaire à droite
    - garde uniquement les cellules utiles encadrées
    """
    from openpyxl.styles import Border, Side, PatternFill, Font, Alignment

    thin = Side(style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    gray = PatternFill("solid", fgColor="D9D9D9")
    light_gray = PatternFill("solid", fgColor="F2F2F2")
    white = PatternFill("solid", fgColor="FFFFFF")
    header_font = Font(name="Calibri", size=10, bold=True)
    normal_font = Font(name="Calibri", size=10)
    bold_font = Font(name="Calibri", size=10, bold=True)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    _abhl_final_clear_borders_outside_real_tables(ws)

    # Trouver la ligne du total principal.
    total_row = None
    for row in range(1, ws.max_row + 1):
        if _abhl_final_norm_text(ws.cell(row=row, column=3).value) in {"المجموع", "TOTAL"}:
            total_row = row

    if not total_row:
        total_row = ws.max_row

    # Tableau principal : C:I
    for row in range(8, total_row + 1):
        for col in range(3, 10):
            cell = ws.cell(row=row, column=col)
            cell.border = border
            cell.alignment = center
            if row == 8:
                cell.fill = light_gray
                cell.font = header_font
            elif _abhl_final_norm_text(ws.cell(row=row, column=3).value) in {"المجموع الجزئي", "المجموع", "SOUS-TOTAL", "TOTAL"}:
                cell.fill = gray
                cell.font = bold_font
            else:
                cell.fill = white
                cell.font = normal_font

    # Table secondaire : on la garde proprement en L:N seulement.
    # L = volume normal, M = volume jour, N = volume année précédente
    start_col = 12
    end_col = 14

    for row in range(8, total_row + 1):
        for col in range(start_col, end_col + 1):
            cell = ws.cell(row=row, column=col)
            cell.border = border
            cell.alignment = center

            if row in (8, 9):
                cell.fill = light_gray
                cell.font = header_font
            elif _abhl_final_norm_text(ws.cell(row=row, column=3).value) in {"المجموع الجزئي", "المجموع", "SOUS-TOTAL", "TOTAL"}:
                cell.fill = gray
                cell.font = bold_font
            else:
                cell.fill = white
                cell.font = normal_font

    # Titres plus propres.
    try:
        ws.cell(row=8, column=12).value = "الحجم العادي\n(مليون م³)"
        ws.cell(row=8, column=13).value = "الحجم\n(مليون م³)"
        ws.cell(row=9, column=12).value = "Volume normal\n(Mm³)"

        # Les dates en M/N restent celles déjà générées si elles existent.
        if not ws.cell(row=9, column=13).value:
            ws.cell(row=9, column=13).value = ""
        if not ws.cell(row=9, column=14).value:
            ws.cell(row=9, column=14).value = ""
    except Exception:
        pass

    for col in ["C", "D", "E", "F", "G", "H", "I", "L", "M", "N"]:
        ws.column_dimensions[col].width = 16

    ws.column_dimensions["D"].width = 26
    ws.column_dimensions["K"].width = 3

    # Supprimer visuellement les cadres après la fin des tableaux.
    for row in range(total_row + 1, min(total_row + 20, 100)):
        for col in list(range(3, 10)) + list(range(12, 15)):
            cell = ws.cell(row=row, column=col)
            cell.value = None
            cell.border = Border()
            cell.fill = PatternFill(fill_type=None)


def _abhl_final_patch_detailed_volume_normal(ws, capacities_by_order, total_capacity):
    """
    Corrige les valeurs de Volume normal dans les feuilles détaillées.
    Le problème venait du fait que certaines lignes gardaient l'ancien volume normal.
    On prend comme référence la page Situation FRA, qui contient les capacités normales correctes.
    """
    from openpyxl.styles import Border, PatternFill

    if not capacities_by_order:
        return

    idx = 0

    # Lignes des barrages dans la table principale.
    for row in range(1, ws.max_row + 1):
        label = ws.cell(row=row, column=1).value
        label_norm = _abhl_final_norm_text(label)

        # Exemple : "1. Oued El Makhazine", "7. TEST 02", etc.
        if label_norm and label_norm[0:1].isdigit() and idx < len(capacities_by_order):
            capacity = capacities_by_order[idx]

            # Dans Situation Détaillée, le volume normal est généralement sur la ligne suivante en B.
            ws.cell(row=row + 1, column=2).value = capacity
            ws.cell(row=row + 1, column=2).number_format = "#,##0.0"

            # Table latérale à droite : même ligne de volume normal si elle existe.
            # Colonne T = 20 dans les exports existants.
            try:
                ws.cell(row=row + 1, column=20).value = capacity
                ws.cell(row=row + 1, column=20).number_format = "#,##0.0"
            except Exception:
                pass

            idx += 1

    # Total / Ensemble.
    if total_capacity is not None:
        for row in range(1, ws.max_row + 1):
            label = _abhl_final_norm_text(ws.cell(row=row, column=1).value)

            if "ENSEMBLE" in label or label == "TOTAL":
                ws.cell(row=row, column=2).value = total_capacity
                ws.cell(row=row, column=2).number_format = "#,##0.0"

                try:
                    ws.cell(row=row, column=20).value = total_capacity
                    ws.cell(row=row, column=20).number_format = "#,##0.0"
                except Exception:
                    pass

    # Corriger les libellés de la table latérale.
    for row in range(1, min(ws.max_row + 1, 60)):
        for col in range(18, min(ws.max_column + 1, 24)):
            cell = ws.cell(row=row, column=col)
            if isinstance(cell.value, str):
                cell.value = cell.value.replace("Mm3", "Mm³").replace("m3", "m³").replace("م3", "م³")

    # Enlever les cadres vides très loin à droite / en bas.
    no_border = Border()
    no_fill = PatternFill(fill_type=None)

    for row in range(1, min(ws.max_row + 20, 120)):
        for col in range(1, min(ws.max_column + 10, 35)):
            cell = ws.cell(row=row, column=col)

            if cell.value is None:
                # On évite de toucher la zone principale quand elle est réellement dans le tableau.
                if col > 22 or row > 55:
                    cell.border = no_border
                    cell.fill = no_fill

    for col in ["B", "C", "D", "M", "N", "O", "P", "T", "U", "V"]:
        ws.column_dimensions[col].width = max(ws.column_dimensions[col].width or 0, 12)


def _abhl_final_postprocess_xlsx_file(path):
    from pathlib import Path
    from openpyxl import load_workbook

    xlsx_path = Path(path)

    if not xlsx_path.exists() or xlsx_path.suffix.lower() != ".xlsx":
        return

    wb = load_workbook(xlsx_path)

    _abhl_final_fix_m3_labels(wb)

    capacities_by_order, total_capacity = _abhl_final_build_fra_reference(wb)

    if "Situation AR" in wb.sheetnames:
        _abhl_final_patch_situation_ar(wb["Situation AR"])

    if "Situation Détaillée" in wb.sheetnames:
        _abhl_final_patch_detailed_volume_normal(wb["Situation Détaillée"], capacities_by_order, total_capacity)

    # Attention : on ne force pas la feuille Situation Détaillée (T) avec les mêmes capacités,
    # car elle peut garder une logique de référence différente selon le modèle ABHL.
    # On corrige seulement les libellés Mm³ via _abhl_final_fix_m3_labels.

    wb.save(xlsx_path)


def _abhl_final_wrap_generation_functions():
    import inspect
    from pathlib import Path

    current_globals = globals()

    if current_globals.get("_ABHL_FINAL_SITUATION_WRAPPED"):
        return

    current_globals["_ABHL_FINAL_SITUATION_WRAPPED"] = True

    candidate_names = []

    for name, obj in list(current_globals.items()):
        if not callable(obj):
            continue

        if not name.startswith("generate"):
            continue

        # On évite de wrapper les fonctions internes de ce patch.
        if name.startswith("_abhl"):
            continue

        candidate_names.append(name)

    for name in candidate_names:
        original = current_globals[name]

        def _make_wrapper(fn):
            def wrapper(*args, **kwargs):
                result = fn(*args, **kwargs)

                try:
                    # Cas 1 : la fonction retourne directement le chemin.
                    if result is not None:
                        _abhl_final_postprocess_xlsx_file(result)

                    # Cas 2 : certains générateurs reçoivent output_path dans les arguments nommés.
                    output_path = kwargs.get("output_path") or kwargs.get("path")
                    if output_path:
                        _abhl_final_postprocess_xlsx_file(output_path)

                    # Cas 3 : output_path positionnel probable.
                    for arg in args:
                        if isinstance(arg, (str, Path)) and str(arg).lower().endswith(".xlsx"):
                            _abhl_final_postprocess_xlsx_file(arg)
                except Exception as exc:
                    # Ne jamais casser l'export à cause d'un post-traitement visuel.
                    print("[ABHL] Avertissement post-traitement Situation:", exc)

                return result

            try:
                wrapper.__name__ = fn.__name__
                wrapper.__doc__ = fn.__doc__
                wrapper.__signature__ = inspect.signature(fn)
            except Exception:
                pass

            return wrapper

        current_globals[name] = _make_wrapper(original)


_abhl_final_wrap_generation_functions()

# === ABHL SITUATION FINAL CLEAN EXPORT V1 END ===

# === ABHL SITUATION AR ORIGINAL ARCHITECTURE FINAL V2 START ===
# Correction finale de la feuille "Situation AR" selon l'architecture réelle du fichier ABHL :
# - header sur 2 lignes comme le fichier original
# - tableau principal C:I
# - table secondaire M:O, pas L:N
# - M = Volume normal (Mm³) de référence ancienne / comparaison
# - N = volume année précédente
# - O = volume jour
# - pas de cadres dessinés hors tableau
# - garde les nouveaux barrages dans leurs bons groupes
# - général pour tous les nouveaux barrages, pas seulement TEST 01 / TEST 02

def _abhl_ar_v2_styles():
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

    thin = Side(style="thin", color="000000")

    return {
        "title_font": Font(name="Calibri", size=16, bold=True),
        "header_font": Font(name="Calibri", size=10, bold=True),
        "normal_font": Font(name="Calibri", size=10),
        "bold_font": Font(name="Calibri", size=10, bold=True),
        "center": Alignment(horizontal="center", vertical="center", wrap_text=True),
        "right": Alignment(horizontal="right", vertical="center", wrap_text=True),
        "left": Alignment(horizontal="left", vertical="center", wrap_text=True),
        "gray": PatternFill("solid", fgColor="D9D9D9"),
        "light_gray": PatternFill("solid", fgColor="F2F2F2"),
        "white": PatternFill("solid", fgColor="FFFFFF"),
        "none_fill": PatternFill(fill_type=None),
        "border": Border(left=thin, right=thin, top=thin, bottom=thin),
        "no_border": Border(),
    }


_ABHL_AR_V2_GROUPS = [
    ("LOUKKOS_TOTAL", "اللكوس"),
    ("TANGER_TOTAL", "طنجة"),
    ("TETOUAN_TOTAL", "تطوان"),
    ("AL_HOCEIMA_TOTAL", "الحسيمة"),
    ("CHEFCHAOUEN", "شفشاون"),
]

_ABHL_AR_V2_OFFICIAL_GROUPS = {
    "LOUKKOS_TOTAL": ["BOEM", "DAR_KHROFA"],
    "TANGER_TOTAL": ["BIB", "9_AVRIL", "KHARROUB", "TANGER_MED"],
    "TETOUAN_TOTAL": ["NAKHLA", "SMIR", "MHB_MEHDI", "CAI"],
    "AL_HOCEIMA_TOTAL": ["KHATTABI", "JOUMOUA"],
    "CHEFCHAOUEN": ["CHEFCHAOUEN"],
}


def _abhl_ar_v2_clean_name(value):
    import re

    if value is None:
        return ""

    text = str(value)
    text = re.sub(r"^\s*\d+\.\s*", "", text)
    text = text.replace("\xa0", " ")
    text = " ".join(text.split())

    return text


def _abhl_ar_v2_norm(value):
    return _abhl_ar_v2_clean_name(value).upper()


def _abhl_ar_v2_month_ar(month: int) -> str:
    months = {
        1: "يناير",
        2: "فبراير",
        3: "مارس",
        4: "أبريل",
        5: "ماي",
        6: "يونيو",
        7: "يوليوز",
        8: "غشت",
        9: "شتنبر",
        10: "أكتوبر",
        11: "نونبر",
        12: "دجنبر",
    }
    return months.get(month, "")


def _abhl_ar_v2_date_slash(d):
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def _abhl_ar_v2_num(value):
    if value is None or value == "-":
        return None

    try:
        return float(value)
    except Exception:
        return None


def _abhl_ar_v2_zero(value) -> float:
    n = _abhl_ar_v2_num(value)
    return 0.0 if n is None else n


def _abhl_ar_v2_rate(volume, capacity):
    v = _abhl_ar_v2_num(volume)
    c = _abhl_ar_v2_num(capacity)

    if v is None or c is None or c == 0:
        return None

    return min(v / c * 100.0, 100.0)


def _abhl_ar_v2_group_for_code(data: dict, code: str):
    row = (data.get("normal_rows") or {}).get(code) or {}

    if row.get("group_code"):
        return row.get("group_code")

    for group_code, codes in _ABHL_AR_V2_OFFICIAL_GROUPS.items():
        if code in codes:
            return group_code

    barrage = (data.get("barrages") or {}).get(code) or {}
    agence = (barrage.get("agence_code") or "").upper()

    if agence == "LOUKKOS":
        return "LOUKKOS_TOTAL"
    if agence == "TANGER":
        return "TANGER_TOTAL"
    if agence == "TETOUAN":
        return "TETOUAN_TOTAL"
    if agence == "AL_HOCEIMA":
        return "AL_HOCEIMA_TOTAL"
    if agence == "CHEFCHAOUEN":
        return "CHEFCHAOUEN"

    return None


def _abhl_ar_v2_codes_for_group(data: dict, group_code: str) -> list[str]:
    codes = data.get("situation_codes") or list((data.get("normal_rows") or {}).keys())
    return [code for code in codes if _abhl_ar_v2_group_for_code(data, code) == group_code]


def _abhl_ar_v2_display_name(data: dict, code: str) -> str:
    try:
        if code in FRA_BARRAGE_NAMES:
            return FRA_BARRAGE_NAMES[code]
    except NameError:
        pass

    barrage = (data.get("barrages") or {}).get(code) or {}
    return barrage.get("nom_court") or barrage.get("nom") or code


def _abhl_ar_v2_row_values(data: dict, code: str) -> dict:
    row = (data.get("normal_rows") or {}).get(code) or {}

    current_capacity = row.get("volume_normal_current")
    old_capacity = row.get("volume_normal_old")

    if old_capacity is None:
        old_capacity = current_capacity

    current_volume = row.get("volume_jour")
    n1_volume = row.get("volume_annee_precedente")

    current_rate = row.get("taux_remplissage")
    if current_rate is None:
        current_rate = _abhl_ar_v2_rate(current_volume, current_capacity)

    n1_rate = row.get("taux_annee_precedente")
    if n1_rate is None:
        n1_rate = _abhl_ar_v2_rate(n1_volume, old_capacity)

    return {
        "current_capacity": current_capacity,
        "old_capacity": old_capacity,
        "current_volume": current_volume,
        "current_rate": current_rate,
        "n1_volume": n1_volume,
        "n1_rate": n1_rate,
    }


def _abhl_ar_v2_summary(data: dict, codes: list[str]) -> dict:
    current_capacity = 0.0
    old_capacity = 0.0
    current_volume = 0.0
    n1_volume = 0.0
    has_n1 = False

    for code in codes:
        values = _abhl_ar_v2_row_values(data, code)

        current_capacity += _abhl_ar_v2_zero(values.get("current_capacity"))
        old_capacity += _abhl_ar_v2_zero(values.get("old_capacity"))
        current_volume += _abhl_ar_v2_zero(values.get("current_volume"))

        if values.get("n1_volume") is not None:
            has_n1 = True
            n1_volume += _abhl_ar_v2_zero(values.get("n1_volume"))

    return {
        "current_capacity": current_capacity,
        "old_capacity": old_capacity,
        "current_volume": current_volume,
        "current_rate": _abhl_ar_v2_rate(current_volume, current_capacity),
        "n1_volume": n1_volume if has_n1 else None,
        "n1_rate": _abhl_ar_v2_rate(n1_volume, old_capacity) if has_n1 else None,
    }


def _abhl_ar_v2_total(data: dict) -> dict:
    all_codes = []

    for group_code, _ in _ABHL_AR_V2_GROUPS:
        all_codes.extend(_abhl_ar_v2_codes_for_group(data, group_code))

    return _abhl_ar_v2_summary(data, all_codes)


def _abhl_ar_v2_unmerge_area(ws, min_row: int, max_row: int, min_col: int, max_col: int):
    for merged_range in list(ws.merged_cells.ranges):
        if (
            merged_range.min_row <= max_row
            and merged_range.max_row >= min_row
            and merged_range.min_col <= max_col
            and merged_range.max_col >= min_col
        ):
            ws.unmerge_cells(str(merged_range))


def _abhl_ar_v2_clear_sheet_area(ws):
    styles = _abhl_ar_v2_styles()

    # On nettoie largement la zone utilisée par la feuille AR pour enlever les anciens cadres.
    _abhl_ar_v2_unmerge_area(ws, 1, 120, 1, 25)

    for r in range(1, 121):
        for c in range(1, 26):
            cell = ws.cell(row=r, column=c)
            cell.value = None
            cell.border = styles["no_border"]
            cell.fill = styles["none_fill"]
            cell.font = styles["normal_font"]
            cell.alignment = styles["center"]


def _abhl_ar_v2_style_range(ws, min_row, max_row, min_col, max_col, fill, font, alignment):
    styles = _abhl_ar_v2_styles()

    for r in range(min_row, max_row + 1):
        for c in range(min_col, max_col + 1):
            cell = ws.cell(row=r, column=c)
            cell.fill = fill
            cell.font = font
            cell.alignment = alignment
            cell.border = styles["border"]


def _abhl_ar_v2_write_num(ws, row: int, col: int, value, fmt="#,##0.0"):
    cell = ws.cell(row=row, column=col)

    if value is None:
        cell.value = "-"
        return

    cell.value = value
    cell.number_format = fmt


def _abhl_ar_v2_write_rate(ws, row: int, col: int, value):
    cell = ws.cell(row=row, column=col)

    if value is None:
        cell.value = "-"
        return

    cell.value = value
    cell.number_format = "0"


def _abhl_ar_v2_write_main_row(ws, row: int, values: dict):
    # Architecture officielle AR :
    # C = taux N-1
    # D = volume N-1
    # E = taux actuel
    # F = volume actuel
    # G = volume normal actuel
    _abhl_ar_v2_write_rate(ws, row, 3, values.get("n1_rate"))
    _abhl_ar_v2_write_num(ws, row, 4, values.get("n1_volume"))
    _abhl_ar_v2_write_rate(ws, row, 5, values.get("current_rate"))
    _abhl_ar_v2_write_num(ws, row, 6, values.get("current_volume"))
    _abhl_ar_v2_write_num(ws, row, 7, values.get("current_capacity"))


def _abhl_ar_v2_write_secondary_row(ws, row: int, values: dict):
    # Architecture officielle de la petite table :
    # M = Volume normal de référence ancienne
    # N = Volume N-1
    # O = Volume actuel
    _abhl_ar_v2_write_num(ws, row, 13, values.get("old_capacity"))
    _abhl_ar_v2_write_num(ws, row, 14, values.get("n1_volume"))
    _abhl_ar_v2_write_num(ws, row, 15, values.get("current_volume"))


def _abhl_ar_v2_style_data_row(ws, row: int):
    styles = _abhl_ar_v2_styles()

    for col in list(range(3, 10)) + [13, 14, 15]:
        cell = ws.cell(row=row, column=col)
        cell.fill = styles["white"]
        cell.font = styles["normal_font"]
        cell.alignment = styles["center"]
        cell.border = styles["border"]


def _abhl_ar_v2_style_total_row(ws, row: int):
    styles = _abhl_ar_v2_styles()

    for col in list(range(3, 10)) + [13, 14, 15]:
        cell = ws.cell(row=row, column=col)
        cell.fill = styles["gray"]
        cell.font = styles["bold_font"]
        cell.alignment = styles["center"]
        cell.border = styles["border"]


def _abhl_ar_v2_merge_group(ws, start_row: int, end_row: int, label: str):
    styles = _abhl_ar_v2_styles()

    if end_row > start_row:
        ws.merge_cells(start_row=start_row, start_column=9, end_row=end_row, end_column=9)

    cell = ws.cell(row=start_row, column=9)
    cell.value = label

    for r in range(start_row, end_row + 1):
        c = ws.cell(row=r, column=9)
        c.fill = styles["white"]
        c.font = styles["normal_font"]
        c.alignment = styles["center"]
        c.border = styles["border"]


def fill_situation_ar(ws, data: dict):
    styles = _abhl_ar_v2_styles()
    d = data["dates"]["date_situation"]
    d_n1 = data["dates"]["date_annee_precedente"]

    ws.sheet_view.rightToLeft = True
    _abhl_ar_v2_clear_sheet_area(ws)

    # Titre
    ws.merge_cells(start_row=6, start_column=1, end_row=6, end_column=11)
    title = f"حالة ملء السدود بتاريخ {d.day} {_abhl_ar_v2_month_ar(d.month)} {d.year}"
    ws.cell(row=6, column=1, value=title)
    ws.cell(row=6, column=1).font = styles["title_font"]
    ws.cell(row=6, column=1).alignment = styles["center"]

    # Header principal, exactement sur 2 lignes comme le fichier ABHL.
    ws.merge_cells(start_row=8, start_column=3, end_row=8, end_column=4)
    ws.cell(row=8, column=3, value=_abhl_ar_v2_date_slash(d_n1))
    ws.cell(row=9, column=3, value="نسبة الملء (%)")
    ws.cell(row=9, column=4, value="الحجم (مليون م³)")

    ws.merge_cells(start_row=8, start_column=5, end_row=8, end_column=6)
    ws.cell(row=8, column=5, value=_abhl_ar_v2_date_slash(d))
    ws.cell(row=9, column=5, value="نسبة الملء (%)")
    ws.cell(row=9, column=6, value="الحجم (مليون م³)")

    ws.merge_cells(start_row=8, start_column=7, end_row=9, end_column=7)
    ws.cell(row=8, column=7, value="الحجم العادي\n(مليون م³)")

    ws.merge_cells(start_row=8, start_column=8, end_row=9, end_column=8)
    ws.cell(row=8, column=8, value="السد")

    ws.merge_cells(start_row=8, start_column=9, end_row=9, end_column=9)
    ws.cell(row=8, column=9, value="المنظومة")

    _abhl_ar_v2_style_range(
        ws, 8, 9, 3, 9,
        styles["light_gray"],
        styles["header_font"],
        styles["center"],
    )

    # Petite table secondaire officielle M:O.
    ws.merge_cells(start_row=8, start_column=13, end_row=9, end_column=13)
    ws.cell(row=8, column=13, value="Volume normal\n(Mm³)")

    ws.merge_cells(start_row=8, start_column=14, end_row=8, end_column=15)
    ws.cell(row=8, column=14, value="الحجم (مليون م³)")
    ws.cell(row=9, column=14, value=_abhl_ar_v2_date_slash(d_n1))
    ws.cell(row=9, column=15, value=_abhl_ar_v2_date_slash(d))

    _abhl_ar_v2_style_range(
        ws, 8, 9, 13, 15,
        styles["light_gray"],
        styles["header_font"],
        styles["center"],
    )

    row = 10

    for group_code, group_label_ar in _ABHL_AR_V2_GROUPS:
        codes = _abhl_ar_v2_codes_for_group(data, group_code)

        if not codes:
            continue

        group_start = row

        for code in codes:
            values = _abhl_ar_v2_row_values(data, code)

            _abhl_ar_v2_style_data_row(ws, row)

            ws.cell(row=row, column=8, value=_abhl_ar_v2_display_name(data, code))
            ws.cell(row=row, column=8).alignment = styles["right"]

            _abhl_ar_v2_write_main_row(ws, row, values)
            _abhl_ar_v2_write_secondary_row(ws, row, values)

            row += 1

        group_end = row - 1
        _abhl_ar_v2_merge_group(ws, group_start, group_end, group_label_ar)

        if len(codes) > 1:
            subtotal = _abhl_ar_v2_summary(data, codes)

            ws.merge_cells(start_row=row, start_column=8, end_row=row, end_column=9)
            ws.cell(row=row, column=8, value="المجموع الجزئي")

            _abhl_ar_v2_style_total_row(ws, row)
            _abhl_ar_v2_write_main_row(ws, row, subtotal)
            _abhl_ar_v2_write_secondary_row(ws, row, subtotal)

            row += 1

    total = _abhl_ar_v2_total(data)

    ws.merge_cells(start_row=row, start_column=8, end_row=row, end_column=9)
    ws.cell(row=row, column=8, value="المجموع")

    _abhl_ar_v2_style_total_row(ws, row)
    _abhl_ar_v2_write_main_row(ws, row, total)
    _abhl_ar_v2_write_secondary_row(ws, row, total)

    # Dimensions
    widths = {
        "A": 4,
        "B": 4,
        "C": 14,
        "D": 16,
        "E": 14,
        "F": 16,
        "G": 16,
        "H": 26,
        "I": 16,
        "J": 3,
        "K": 3,
        "L": 3,
        "M": 18,
        "N": 16,
        "O": 16,
    }

    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    for r in range(6, row + 1):
        ws.row_dimensions[r].height = 24

    # Nettoyage : aucune bordure hors table.
    for r in range(1, 120):
        for c in range(1, 26):
            in_main = 8 <= r <= row and 3 <= c <= 9
            in_side = 8 <= r <= row and 13 <= c <= 15
            in_title = r == 6 and 1 <= c <= 11

            if not in_main and not in_side and not in_title:
                cell = ws.cell(row=r, column=c)
                if cell.value is None:
                    cell.border = styles["no_border"]
                    cell.fill = styles["none_fill"]

    try:
        ws.print_area = f"A6:O{row}"
    except Exception:
        pass


# Le vieux post-traitement ajouté par les patchs précédents ne doit plus réécrire
# la petite table AR avec les mauvaises valeurs. On le neutralise pour éviter
# de casser l'architecture finale construite ci-dessus.
def _abhl_final_postprocess_xlsx_file(path):
    try:
        from pathlib import Path
        from openpyxl import load_workbook

        xlsx_path = Path(path)

        if not xlsx_path.exists() or xlsx_path.suffix.lower() != ".xlsx":
            return

        wb = load_workbook(xlsx_path)

        # Correction simple des libellés d'unités uniquement.
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str):
                        cell.value = (
                            cell.value
                            .replace("Mm3", "Mm³")
                            .replace("m3", "m³")
                            .replace("M3", "M³")
                            .replace("م3", "م³")
                        )

        wb.save(xlsx_path)
    except Exception as exc:
        print("[ABHL] Avertissement post-traitement final Situation:", exc)

# === ABHL SITUATION AR ORIGINAL ARCHITECTURE FINAL V2 END ===

# === ABHL SITUATION AR N1 REFERENCE TOTALS FINAL V3 START ===
# Correction finale de Situation AR :
# - La petite table secondaire respecte l'architecture ABHL : M:O
#   M = Volume normal de référence N-1
#   N = Volume N-1
#   O = Volume actuel
# - Les nouveaux barrages sans historique N-1 affichent "-" dans les colonnes N-1.
# - Les nouveaux barrages ne changent pas les totaux historiques N-1.
# - Le total actuel de Situation AR reprend le même total que Situation FRA.
# - Correction générale pour tous les futurs barrages, pas seulement TEST 01 / TEST 02.

def _abhl_ar_v3_styles():
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

    thin = Side(style="thin", color="000000")
    return {
        "title_font": Font(name="Calibri", size=16, bold=True),
        "header_font": Font(name="Calibri", size=10, bold=True),
        "normal_font": Font(name="Calibri", size=10),
        "bold_font": Font(name="Calibri", size=10, bold=True),
        "center": Alignment(horizontal="center", vertical="center", wrap_text=True),
        "right": Alignment(horizontal="right", vertical="center", wrap_text=True),
        "gray": PatternFill("solid", fgColor="D9D9D9"),
        "light_gray": PatternFill("solid", fgColor="F2F2F2"),
        "white": PatternFill("solid", fgColor="FFFFFF"),
        "none_fill": PatternFill(fill_type=None),
        "border": Border(left=thin, right=thin, top=thin, bottom=thin),
        "no_border": Border(),
    }


_ABHL_AR_V3_GROUPS = [
    ("LOUKKOS_TOTAL", "اللكوس"),
    ("TANGER_TOTAL", "طنجة"),
    ("TETOUAN_TOTAL", "تطوان"),
    ("AL_HOCEIMA_TOTAL", "الحسيمة"),
    ("CHEFCHAOUEN", "شفشاون"),
]

_ABHL_AR_V3_OFFICIAL_GROUPS = {
    "LOUKKOS_TOTAL": ["BOEM", "DAR_KHROFA"],
    "TANGER_TOTAL": ["BIB", "9_AVRIL", "KHARROUB", "TANGER_MED"],
    "TETOUAN_TOTAL": ["NAKHLA", "SMIR", "MHB_MEHDI", "CAI"],
    "AL_HOCEIMA_TOTAL": ["KHATTABI", "JOUMOUA"],
    "CHEFCHAOUEN": ["CHEFCHAOUEN"],
}


def _abhl_ar_v3_month_ar(month: int) -> str:
    return {
        1: "يناير",
        2: "فبراير",
        3: "مارس",
        4: "أبريل",
        5: "ماي",
        6: "يونيو",
        7: "يوليوز",
        8: "غشت",
        9: "شتنبر",
        10: "أكتوبر",
        11: "نونبر",
        12: "دجنبر",
    }.get(month, "")


def _abhl_ar_v3_date_slash(d):
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def _abhl_ar_v3_num(value):
    if value is None or value == "-":
        return None
    try:
        return float(value)
    except Exception:
        return None


def _abhl_ar_v3_zero(value) -> float:
    value = _abhl_ar_v3_num(value)
    return 0.0 if value is None else value


def _abhl_ar_v3_rate(volume, capacity):
    volume = _abhl_ar_v3_num(volume)
    capacity = _abhl_ar_v3_num(capacity)

    if volume is None or capacity is None or capacity == 0:
        return None

    return min((volume / capacity) * 100.0, 100.0)


def _abhl_ar_v3_group_for_code(data: dict, code: str):
    row = (data.get("normal_rows") or {}).get(code) or {}

    if row.get("group_code"):
        return row.get("group_code")

    for group_code, codes in _ABHL_AR_V3_OFFICIAL_GROUPS.items():
        if code in codes:
            return group_code

    barrage = (data.get("barrages") or {}).get(code) or {}
    agence = (barrage.get("agence_code") or "").upper()

    if agence == "LOUKKOS":
        return "LOUKKOS_TOTAL"
    if agence == "TANGER":
        return "TANGER_TOTAL"
    if agence == "TETOUAN":
        return "TETOUAN_TOTAL"
    if agence == "AL_HOCEIMA":
        return "AL_HOCEIMA_TOTAL"
    if agence == "CHEFCHAOUEN":
        return "CHEFCHAOUEN"

    return None


def _abhl_ar_v3_codes_for_group(data: dict, group_code: str) -> list[str]:
    codes = data.get("situation_codes") or list((data.get("normal_rows") or {}).keys())
    return [code for code in codes if _abhl_ar_v3_group_for_code(data, code) == group_code]


def _abhl_ar_v3_display_name(data: dict, code: str) -> str:
    try:
        if code in FRA_BARRAGE_NAMES:
            return FRA_BARRAGE_NAMES[code]
    except NameError:
        pass

    barrage = (data.get("barrages") or {}).get(code) or {}
    return barrage.get("nom_court") or barrage.get("nom") or code


def _abhl_ar_v3_row_values(data: dict, code: str) -> dict:
    row = (data.get("normal_rows") or {}).get(code) or {}

    current_capacity = row.get("volume_normal_current")
    current_volume = row.get("volume_jour")
    current_rate = row.get("taux_remplissage")

    if current_rate is None:
        current_rate = _abhl_ar_v3_rate(current_volume, current_capacity)

    n1_volume = row.get("volume_annee_precedente")
    old_capacity = row.get("volume_normal_old")

    # Important :
    # si le barrage n'a pas de volume N-1, il ne doit PAS contribuer
    # aux calculs historiques. Donc old_capacity devient None.
    if n1_volume is None:
        old_capacity_for_n1 = None
        n1_rate = None
    else:
        old_capacity_for_n1 = old_capacity if old_capacity is not None else current_capacity
        n1_rate = row.get("taux_annee_precedente")
        if n1_rate is None:
            n1_rate = _abhl_ar_v3_rate(n1_volume, old_capacity_for_n1)

    return {
        "current_capacity": current_capacity,
        "current_volume": current_volume,
        "current_rate": current_rate,
        "old_capacity_for_n1": old_capacity_for_n1,
        "n1_volume": n1_volume,
        "n1_rate": n1_rate,
    }


def _abhl_ar_v3_summary(data: dict, codes: list[str]) -> dict:
    current_capacity = 0.0
    current_volume = 0.0

    old_capacity_for_n1 = 0.0
    n1_volume = 0.0
    has_n1 = False

    for code in codes:
        values = _abhl_ar_v3_row_values(data, code)

        current_capacity += _abhl_ar_v3_zero(values.get("current_capacity"))
        current_volume += _abhl_ar_v3_zero(values.get("current_volume"))

        if values.get("n1_volume") is not None:
            has_n1 = True
            old_capacity_for_n1 += _abhl_ar_v3_zero(values.get("old_capacity_for_n1"))
            n1_volume += _abhl_ar_v3_zero(values.get("n1_volume"))

    return {
        "current_capacity": current_capacity,
        "current_volume": current_volume,
        "current_rate": _abhl_ar_v3_rate(current_volume, current_capacity),
        "old_capacity_for_n1": old_capacity_for_n1 if has_n1 else None,
        "n1_volume": n1_volume if has_n1 else None,
        "n1_rate": _abhl_ar_v3_rate(n1_volume, old_capacity_for_n1) if has_n1 else None,
    }


def _abhl_ar_v3_total_from_fra_logic(data: dict) -> dict:
    """
    Pour le total général, on prend d'abord la même fonction que Situation FRA
    quand elle existe dans le fichier, pour avoir exactement la même valeur
    affichée dans FRA et AR.
    """
    try:
        fra_total = _abhl_sq_summary_total(data)

        return {
            "current_capacity": fra_total.get("volume_normal_current"),
            "current_volume": fra_total.get("volume_jour"),
            "current_rate": fra_total.get("taux_remplissage"),
            "n1_volume": fra_total.get("volume_annee_precedente"),
            "n1_rate": fra_total.get("taux_annee_precedente"),
            "old_capacity_for_n1": _abhl_ar_v3_total_old_capacity_for_n1(data),
        }
    except Exception:
        all_codes = []
        for group_code, _ in _ABHL_AR_V3_GROUPS:
            all_codes.extend(_abhl_ar_v3_codes_for_group(data, group_code))
        return _abhl_ar_v3_summary(data, all_codes)


def _abhl_ar_v3_total_old_capacity_for_n1(data: dict):
    total = 0.0
    found = False

    for group_code, _ in _ABHL_AR_V3_GROUPS:
        for code in _abhl_ar_v3_codes_for_group(data, group_code):
            values = _abhl_ar_v3_row_values(data, code)
            if values.get("n1_volume") is not None:
                found = True
                total += _abhl_ar_v3_zero(values.get("old_capacity_for_n1"))

    return total if found else None


def _abhl_ar_v3_unmerge_area(ws, min_row: int, max_row: int, min_col: int, max_col: int):
    for merged_range in list(ws.merged_cells.ranges):
        if (
            merged_range.min_row <= max_row
            and merged_range.max_row >= min_row
            and merged_range.min_col <= max_col
            and merged_range.max_col >= min_col
        ):
            ws.unmerge_cells(str(merged_range))


def _abhl_ar_v3_clear(ws):
    styles = _abhl_ar_v3_styles()
    _abhl_ar_v3_unmerge_area(ws, 1, 120, 1, 25)

    for r in range(1, 121):
        for c in range(1, 26):
            cell = ws.cell(row=r, column=c)
            cell.value = None
            cell.border = styles["no_border"]
            cell.fill = styles["none_fill"]
            cell.font = styles["normal_font"]
            cell.alignment = styles["center"]


def _abhl_ar_v3_style_range(ws, min_row, max_row, min_col, max_col, fill, font, alignment):
    styles = _abhl_ar_v3_styles()

    for r in range(min_row, max_row + 1):
        for c in range(min_col, max_col + 1):
            cell = ws.cell(row=r, column=c)
            cell.fill = fill
            cell.font = font
            cell.alignment = alignment
            cell.border = styles["border"]


def _abhl_ar_v3_write_num(ws, row: int, col: int, value, fmt="#,##0.0"):
    cell = ws.cell(row=row, column=col)

    if value is None:
        cell.value = "-"
        return

    cell.value = value
    cell.number_format = fmt


def _abhl_ar_v3_write_rate(ws, row: int, col: int, value):
    cell = ws.cell(row=row, column=col)

    if value is None:
        cell.value = "-"
        return

    cell.value = value
    cell.number_format = "0"


def _abhl_ar_v3_write_main_row(ws, row: int, values: dict):
    # Architecture AR principale :
    # C = taux N-1
    # D = volume N-1
    # E = taux actuel
    # F = volume actuel
    # G = volume normal actuel
    _abhl_ar_v3_write_rate(ws, row, 3, values.get("n1_rate"))
    _abhl_ar_v3_write_num(ws, row, 4, values.get("n1_volume"))
    _abhl_ar_v3_write_rate(ws, row, 5, values.get("current_rate"))
    _abhl_ar_v3_write_num(ws, row, 6, values.get("current_volume"))
    _abhl_ar_v3_write_num(ws, row, 7, values.get("current_capacity"))


def _abhl_ar_v3_write_secondary_row(ws, row: int, values: dict):
    # Petite table officielle M:O :
    # M = Volume normal de référence N-1
    # N = Volume N-1
    # O = Volume actuel
    _abhl_ar_v3_write_num(ws, row, 13, values.get("old_capacity_for_n1"))
    _abhl_ar_v3_write_num(ws, row, 14, values.get("n1_volume"))
    _abhl_ar_v3_write_num(ws, row, 15, values.get("current_volume"))


def _abhl_ar_v3_style_data_row(ws, row: int):
    styles = _abhl_ar_v3_styles()

    for col in list(range(3, 10)) + [13, 14, 15]:
        cell = ws.cell(row=row, column=col)
        cell.fill = styles["white"]
        cell.font = styles["normal_font"]
        cell.alignment = styles["center"]
        cell.border = styles["border"]


def _abhl_ar_v3_style_total_row(ws, row: int):
    styles = _abhl_ar_v3_styles()

    for col in list(range(3, 10)) + [13, 14, 15]:
        cell = ws.cell(row=row, column=col)
        cell.fill = styles["gray"]
        cell.font = styles["bold_font"]
        cell.alignment = styles["center"]
        cell.border = styles["border"]


def _abhl_ar_v3_merge_group(ws, start_row: int, end_row: int, label: str):
    styles = _abhl_ar_v3_styles()

    if end_row > start_row:
        ws.merge_cells(start_row=start_row, start_column=9, end_row=end_row, end_column=9)

    cell = ws.cell(row=start_row, column=9)
    cell.value = label

    for r in range(start_row, end_row + 1):
        c = ws.cell(row=r, column=9)
        c.fill = styles["white"]
        c.font = styles["normal_font"]
        c.alignment = styles["center"]
        c.border = styles["border"]


def fill_situation_ar(ws, data: dict):
    styles = _abhl_ar_v3_styles()
    d = data["dates"]["date_situation"]
    d_n1 = data["dates"]["date_annee_precedente"]

    ws.sheet_view.rightToLeft = True
    _abhl_ar_v3_clear(ws)

    # Titre
    ws.merge_cells(start_row=6, start_column=1, end_row=6, end_column=11)
    ws.cell(
        row=6,
        column=1,
        value=f"حالة ملء السدود بتاريخ {d.day} {_abhl_ar_v3_month_ar(d.month)} {d.year}",
    )
    ws.cell(row=6, column=1).font = styles["title_font"]
    ws.cell(row=6, column=1).alignment = styles["center"]

    # En-tête principal C:I
    ws.merge_cells(start_row=8, start_column=3, end_row=8, end_column=4)
    ws.cell(row=8, column=3, value=_abhl_ar_v3_date_slash(d_n1))
    ws.cell(row=9, column=3, value="نسبة الملء (%)")
    ws.cell(row=9, column=4, value="الحجم (مليون م³)")

    ws.merge_cells(start_row=8, start_column=5, end_row=8, end_column=6)
    ws.cell(row=8, column=5, value=_abhl_ar_v3_date_slash(d))
    ws.cell(row=9, column=5, value="نسبة الملء (%)")
    ws.cell(row=9, column=6, value="الحجم (مليون م³)")

    ws.merge_cells(start_row=8, start_column=7, end_row=9, end_column=7)
    ws.cell(row=8, column=7, value="الحجم العادي\n(مليون م³)")

    ws.merge_cells(start_row=8, start_column=8, end_row=9, end_column=8)
    ws.cell(row=8, column=8, value="السد")

    ws.merge_cells(start_row=8, start_column=9, end_row=9, end_column=9)
    ws.cell(row=8, column=9, value="المنظومة")

    _abhl_ar_v3_style_range(ws, 8, 9, 3, 9, styles["light_gray"], styles["header_font"], styles["center"])

    # Petite table secondaire M:O
    ws.merge_cells(start_row=8, start_column=13, end_row=9, end_column=13)
    ws.cell(row=8, column=13, value="Volume normal\n(Mm³)")

    ws.merge_cells(start_row=8, start_column=14, end_row=8, end_column=15)
    ws.cell(row=8, column=14, value="الحجم (مليون م³)")
    ws.cell(row=9, column=14, value=_abhl_ar_v3_date_slash(d_n1))
    ws.cell(row=9, column=15, value=_abhl_ar_v3_date_slash(d))

    _abhl_ar_v3_style_range(ws, 8, 9, 13, 15, styles["light_gray"], styles["header_font"], styles["center"])

    row = 10

    for group_code, group_label_ar in _ABHL_AR_V3_GROUPS:
        codes = _abhl_ar_v3_codes_for_group(data, group_code)

        if not codes:
            continue

        group_start = row

        for code in codes:
            values = _abhl_ar_v3_row_values(data, code)

            _abhl_ar_v3_style_data_row(ws, row)

            ws.cell(row=row, column=8, value=_abhl_ar_v3_display_name(data, code))
            ws.cell(row=row, column=8).alignment = styles["right"]

            _abhl_ar_v3_write_main_row(ws, row, values)
            _abhl_ar_v3_write_secondary_row(ws, row, values)

            row += 1

        group_end = row - 1
        _abhl_ar_v3_merge_group(ws, group_start, group_end, group_label_ar)

        if len(codes) > 1:
            subtotal = _abhl_ar_v3_summary(data, codes)

            ws.merge_cells(start_row=row, start_column=8, end_row=row, end_column=9)
            ws.cell(row=row, column=8, value="المجموع الجزئي")

            _abhl_ar_v3_style_total_row(ws, row)
            _abhl_ar_v3_write_main_row(ws, row, subtotal)
            _abhl_ar_v3_write_secondary_row(ws, row, subtotal)

            row += 1

    total = _abhl_ar_v3_total_from_fra_logic(data)

    ws.merge_cells(start_row=row, start_column=8, end_row=row, end_column=9)
    ws.cell(row=row, column=8, value="المجموع")

    _abhl_ar_v3_style_total_row(ws, row)
    _abhl_ar_v3_write_main_row(ws, row, total)
    _abhl_ar_v3_write_secondary_row(ws, row, total)

    # Dimensions
    for col, width in {
        "A": 4,
        "B": 4,
        "C": 14,
        "D": 16,
        "E": 14,
        "F": 16,
        "G": 16,
        "H": 26,
        "I": 16,
        "J": 3,
        "K": 3,
        "L": 3,
        "M": 18,
        "N": 16,
        "O": 16,
    }.items():
        ws.column_dimensions[col].width = width

    for r in range(6, row + 1):
        ws.row_dimensions[r].height = 24

    # Aucun cadre hors tableau.
    for r in range(1, 120):
        for c in range(1, 26):
            in_title = r == 6 and 1 <= c <= 11
            in_main = 8 <= r <= row and 3 <= c <= 9
            in_side = 8 <= r <= row and 13 <= c <= 15

            if not in_title and not in_main and not in_side:
                cell = ws.cell(row=r, column=c)
                if cell.value is None:
                    cell.border = styles["no_border"]
                    cell.fill = styles["none_fill"]

    try:
        ws.print_area = f"A6:O{row}"
    except Exception:
        pass


# Neutraliser les anciens post-traitements visuels qui pouvaient réécrire
# la table AR après génération.
def _abhl_final_postprocess_xlsx_file(path):
    try:
        from pathlib import Path
        from openpyxl import load_workbook

        xlsx_path = Path(path)

        if not xlsx_path.exists() or xlsx_path.suffix.lower() != ".xlsx":
            return

        wb = load_workbook(xlsx_path)

        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str):
                        cell.value = (
                            cell.value
                            .replace("Mm3", "Mm³")
                            .replace("m3", "m³")
                            .replace("M3", "M³")
                            .replace("م3", "م³")
                        )

        wb.save(xlsx_path)
    except Exception as exc:
        print("[ABHL] Avertissement post-traitement Situation:", exc)

# === ABHL SITUATION AR N1 REFERENCE TOTALS FINAL V3 END ===

# === ABHL V20 SUMMARY N-1 OFFICIAL FORMULA START ===
# Formule officielle observée dans le fichier agence :
# Sous-total taux N-1 = Volume N-1 / Capacité normale actuelle * 100.
# Exemple : =H12/E12*100.
# Cette surcharge corrige les sous-totaux FRA et AR sans toucher les lignes individuelles.

def build_summary_values(data: dict, group_code: str, codes: list[str]) -> dict:
    volume_normal_current = SUMMARY_CURRENT_NORMAL_TOTALS.get(group_code)
    volume_normal_old = SUMMARY_OLD_NORMAL_TOTALS.get(group_code)

    if volume_normal_current is None:
        volume_normal_current = sum(
            safe_number(data["normal_rows"][code].get("volume_normal_current"))
            for code in codes
            if code in data.get("normal_rows", {})
        )

    if volume_normal_old is None:
        volume_normal_old = sum(
            safe_number(data["normal_rows"][code].get("volume_normal_old"))
            for code in codes
            if code in data.get("normal_rows", {})
        )

    volume_jour = sum(
        safe_number(data["normal_rows"][code].get("volume_jour"))
        for code in codes
        if code in data.get("normal_rows", {})
    )

    volume_annee_precedente = sum(
        safe_number(data["normal_rows"][code].get("volume_annee_precedente"))
        for code in codes
        if code in data.get("normal_rows", {})
    )

    return {
        "volume_normal_current": volume_normal_current,
        "volume_normal_old": volume_normal_old,
        "volume_jour": volume_jour,
        "taux_remplissage": safe_rate(volume_jour, volume_normal_current),
        "volume_annee_precedente": volume_annee_precedente,

        # Correction officielle : taux N-1 avec capacité actuelle.
        "taux_annee_precedente": safe_rate(
            volume_annee_precedente,
            volume_normal_current,
        ),
    }


def build_summary_values_fra(data: dict, group_code: str, codes: list[str]) -> dict:
    # Même règle que le fichier Excel agence.
    return build_summary_values(data, group_code, codes)
# === ABHL V20 SUMMARY N-1 OFFICIAL FORMULA END ===

# === ABHL SITUATION FINAL SUMMARY FORMULAS V20 START ===
# Le fichier officiel calcule les taux N-1 des sous-totaux ainsi :
#     Volume N-1 du groupe / Capacité normale actuelle du groupe * 100
# Exemple Loukkos : H12 / E12 * 100.

def _abhl_v20_num(value) -> float:
    if value is None or value == "-":
        return 0.0
    try:
        return float(value)
    except Exception:
        return 0.0


def _abhl_v20_rate(volume, capacity):
    volume = _abhl_v20_num(volume)
    capacity = _abhl_v20_num(capacity)
    if capacity == 0:
        return None
    return min(volume / capacity * 100.0, 100.0)


def _abhl_sq_summary_group(data: dict, codes: list[str]) -> dict:
    current_capacity = 0.0
    current_volume = 0.0
    n1_volume = 0.0
    has_n1 = False

    for code in codes:
        row = data["normal_rows"][code]
        current_capacity += _abhl_v20_num(row.get("volume_normal_current"))
        current_volume += _abhl_v20_num(row.get("volume_jour"))
        if row.get("volume_annee_precedente") is not None:
            has_n1 = True
            n1_volume += _abhl_v20_num(row.get("volume_annee_precedente"))

    return {
        "volume_normal_current": current_capacity,
        "volume_jour": current_volume,
        "taux_remplissage": _abhl_v20_rate(current_volume, current_capacity),
        "volume_annee_precedente": n1_volume if has_n1 else None,
        "taux_annee_precedente": _abhl_v20_rate(n1_volume, current_capacity) if has_n1 else None,
    }


def _abhl_sq_summary_total(data: dict) -> dict:
    totals = data["normal_totals"]
    return {
        "volume_normal_current": totals.get("B"),
        "volume_jour": totals.get("D"),
        "taux_remplissage": totals.get("N"),
        "volume_annee_precedente": totals.get("O"),
        "taux_annee_precedente": totals.get("P"),
    }


def _abhl_ar_v3_summary(data: dict, codes: list[str]) -> dict:
    current_capacity = 0.0
    current_volume = 0.0
    old_capacity_for_side_table = 0.0
    n1_volume = 0.0
    has_n1 = False

    for code in codes:
        values = _abhl_ar_v3_row_values(data, code)
        current_capacity += _abhl_v20_num(values.get("current_capacity"))
        current_volume += _abhl_v20_num(values.get("current_volume"))
        if values.get("n1_volume") is not None:
            has_n1 = True
            old_capacity_for_side_table += _abhl_v20_num(values.get("old_capacity_for_n1"))
            n1_volume += _abhl_v20_num(values.get("n1_volume"))

    return {
        "current_capacity": current_capacity,
        "current_volume": current_volume,
        "current_rate": _abhl_v20_rate(current_volume, current_capacity),
        "old_capacity_for_n1": old_capacity_for_side_table if has_n1 else None,
        "n1_volume": n1_volume if has_n1 else None,
        "n1_rate": _abhl_v20_rate(n1_volume, current_capacity) if has_n1 else None,
    }


def _abhl_ar_v3_total_from_fra_logic(data: dict) -> dict:
    fra_total = _abhl_sq_summary_total(data)
    return {
        "current_capacity": fra_total.get("volume_normal_current"),
        "current_volume": fra_total.get("volume_jour"),
        "current_rate": fra_total.get("taux_remplissage"),
        "n1_volume": fra_total.get("volume_annee_precedente"),
        "n1_rate": fra_total.get("taux_annee_precedente"),
        "old_capacity_for_n1": _abhl_ar_v3_total_old_capacity_for_n1(data),
    }

# === ABHL SITUATION FINAL SUMMARY FORMULAS V20 END ===
# === ABHL V21 SITUATION FRA/AR OFFICIAL FORMULAS START ===
# Référence : fichier agence du 04/08/2026.
#
# REGLES IMPORTANTES :
# 1) Situation FRA - sous-totaux et TOTAL N-1 :
#       Volume N-1 / Capacité ACTUELLE * 100
#    (ex. agence : =H12/E12*100)
# 2) Situation AR - N-1 : capacité HISTORIQUE de référence.
# 3) Situation FRA - sous-total Al Hoceima :
#       =ROUND(E23+E24,0)
#    Le TOTAL FRA additionne ce sous-total arrondi, donc sa capacité interne
#    n'est pas strictement égale au total de Situation Détaillée.
# 4) Les valeurs précises restent dans les cellules ; le format Excel gère
#    l'affichage à 1 décimale. Ne pas arrondir la valeur avant le calcul.

_ABHL_V21_ARABIC_BARRAGE_NAMES = {
    "BOEM": "•\u00a0 وادي المخازن",
    "DAR_KHROFA": "•\u00a0 دار خروفة ",
    "BIB": "•\u00a0 ابن بطوطة",
    "9_AVRIL": "•\u00a0 9 أبريل 1947",
    "KHARROUB": "•\u00a0 الخروب",
    "TANGER_MED": "•\u00a0 طنجة المتوسط",
    "NAKHLA": "•\u00a0 النخلة",
    "SMIR": "•\u00a0 اسمير",
    "MHB_MEHDI": "•\u00a0 م ح بن المهدي",
    "CAI": "•\u00a0 الشريف الإدريسي",
    "CHEFCHAOUEN": "•\u00a0 شفشاون",
    "KHATTABI": "•\u00a0 م ب ع الخطابي",
    "JOUMOUA": "•\u00a0 الجمعة",
}


def _abhl_v21_fra_group_values(data: dict, group_code: str, codes: list[str]) -> dict:
    rows = data.get("normal_rows") or {}

    official_group_codes = set(_ABHL_SQ_EXCEL_OFFICIAL_GROUPS.get(group_code, []))
    official_present = [code for code in codes if code in official_group_codes and code in rows]
    dynamic_present = [code for code in codes if code not in official_group_codes and code in rows]

    official_capacity = sum(_abhl_v20_num(rows[code].get("volume_normal_current")) for code in official_present)
    dynamic_capacity = sum(_abhl_v20_num(rows[code].get("volume_normal_current")) for code in dynamic_present)

    # Reproduit exactement la formule Excel agence : =ROUND(E23+E24,0)
    # pour les deux barrages officiels Al Hoceima. Les barrages dynamiques
    # éventuels restent ajoutés ensuite avec leur précision propre.
    if group_code == "AL_HOCEIMA_TOTAL" and official_present:
        official_capacity = float(excel_round(official_capacity, 0))

    current_capacity = official_capacity + dynamic_capacity
    current_volume = sum(_abhl_v20_num(rows[code].get("volume_jour")) for code in codes if code in rows)

    n1_values = [
        rows[code].get("volume_annee_precedente")
        for code in codes
        if code in rows and rows[code].get("volume_annee_precedente") is not None
    ]
    has_n1 = bool(n1_values)
    n1_volume = sum(_abhl_v20_num(value) for value in n1_values) if has_n1 else None

    return {
        "volume_normal_current": current_capacity,
        "volume_jour": current_volume,
        "taux_remplissage": _abhl_v20_rate(current_volume, current_capacity),
        "volume_annee_precedente": n1_volume,
        "taux_annee_precedente": _abhl_v20_rate(n1_volume, current_capacity) if has_n1 else None,
    }


def _abhl_v21_fra_total_values(data: dict) -> dict:
    current_capacity = 0.0
    current_volume = 0.0
    n1_volume = 0.0
    has_n1 = False

    for group_code, _, _ in _ABHL_SQ_EXCEL_GROUP_ORDER:
        codes = _abhl_sq_codes_for_excel_group(data, group_code)
        if not codes:
            continue

        values = _abhl_v21_fra_group_values(data, group_code, codes)
        current_capacity += _abhl_v20_num(values.get("volume_normal_current"))
        current_volume += _abhl_v20_num(values.get("volume_jour"))

        if values.get("volume_annee_precedente") is not None:
            has_n1 = True
            n1_volume += _abhl_v20_num(values.get("volume_annee_precedente"))

    return {
        "volume_normal_current": current_capacity,
        "volume_jour": current_volume,
        "taux_remplissage": _abhl_v20_rate(current_volume, current_capacity),
        "volume_annee_precedente": n1_volume if has_n1 else None,
        "taux_annee_precedente": _abhl_v20_rate(n1_volume, current_capacity) if has_n1 else None,
    }


def fill_situation_fra(ws, data: dict):
    """Reconstruction de Situation FRA conforme à la structure agence."""
    styles = _abhl_sq_make_summary_styles_v2()
    d = data["dates"]["date_situation"]
    d_n1 = data["dates"]["date_annee_precedente"]

    _abhl_sq_clear_area(ws, 1, 100, 1, 12)

    # Titre comme le classeur agence.
    ws.merge_cells(start_row=6, start_column=1, end_row=6, end_column=11)
    title_cell = ws.cell(row=6, column=1, value=f"SITUATION DES BARRAGES AU {fr_date_long(d)}")
    title_cell.font = styles["title_font"]
    title_cell.alignment = styles["title_align"]

    # En-tête officiel sur deux lignes (8-9), ce qui remet les données à la
    # ligne 10 et le Total à la ligne 27 pour les 13 barrages officiels.
    ws.merge_cells("C8:C9")
    ws.merge_cells("D8:D9")
    ws.merge_cells("E8:E9")
    ws.merge_cells("F8:G8")
    ws.merge_cells("H8:I8")

    ws["C8"] = "Système"
    ws["D8"] = "Barrage"
    ws["E8"] = "Capacité normale (Mm³)"
    ws["F8"] = d
    ws["H8"] = d_n1
    ws["F9"] = "Volume (Mm³)"
    ws["G9"] = "Taux de remplissage (%)"
    ws["H9"] = "Volume (Mm³)"
    ws["I9"] = "Taux de remplissage (%)"
    ws["F8"].number_format = "dd/mm/yyyy"
    ws["H8"].number_format = "dd/mm/yyyy"

    for r in (8, 9):
        for c in range(3, 10):
            cell = ws.cell(row=r, column=c)
            cell.fill = styles["light_gray"]
            cell.font = styles["header_font"]
            cell.alignment = styles["center"]
            cell.border = styles["border"]

    row = 10

    for group_code, system_label, _ in _ABHL_SQ_EXCEL_GROUP_ORDER:
        codes = _abhl_sq_codes_for_excel_group(data, group_code)
        if not codes:
            continue

        group_start = row

        for code in codes:
            _abhl_sq_style_body_row(ws, row, 3, 9, styles)
            ws.cell(row=row, column=4, value=_abhl_sq_display_name(data, code))
            ws.cell(row=row, column=4).alignment = styles["left"]

            values = _abhl_sq_summary_individual(data, code)
            # Les 13 barrages officiels : un SUMIF sans donnée donne 0 dans
            # l'Excel agence. Les barrages dynamiques gardent la logique générique.
            if code in set(data.get("official_codes") or []):
                if values.get("volume_jour") is None:
                    values = dict(values)
                    values["volume_jour"] = 0.0
                    values["taux_remplissage"] = 0.0

            _abhl_sq_fra_write_values_v2(ws, row, values)
            row += 1

        group_end = row - 1
        _abhl_sq_style_group_cell(ws, group_start, group_end, 3, system_label, styles)

        if len(codes) > 1:
            subtotal = _abhl_v21_fra_group_values(data, group_code, codes)
            _abhl_sq_style_subtotal_row(ws, row, "Sous-Total", styles)
            _abhl_sq_fra_write_values_v2(ws, row, subtotal)
            row += 1

    total = _abhl_v21_fra_total_values(data)
    _abhl_sq_style_subtotal_row(ws, row, "Total", styles)
    _abhl_sq_fra_write_values_v2(ws, row, total)

    for col, width in {
        "C": 16,
        "D": 26,
        "E": 16,
        "F": 15,
        "G": 18,
        "H": 15,
        "I": 14,
    }.items():
        ws.column_dimensions[col].width = width

    for r in range(8, row + 1):
        ws.row_dimensions[r].height = 25

    try:
        ws.print_area = f"A6:K{row}"
    except Exception:
        pass


# Situation AR : la dernière surcharge V20 utilisait par erreur la capacité
# actuelle pour les sous-totaux N-1. L'Excel agence du 04/08/2026 utilise ici
# la capacité historique (contrairement à Situation FRA).
def _abhl_ar_v3_summary(data: dict, codes: list[str]) -> dict:
    current_capacity = 0.0
    current_volume = 0.0
    old_capacity_for_n1 = 0.0
    n1_volume = 0.0
    has_n1 = False

    for code in codes:
        values = _abhl_ar_v3_row_values(data, code)
        current_capacity += _abhl_ar_v3_zero(values.get("current_capacity"))
        current_volume += _abhl_ar_v3_zero(values.get("current_volume"))

        if values.get("n1_volume") is not None:
            has_n1 = True
            old_capacity_for_n1 += _abhl_ar_v3_zero(values.get("old_capacity_for_n1"))
            n1_volume += _abhl_ar_v3_zero(values.get("n1_volume"))

    return {
        "current_capacity": current_capacity,
        "current_volume": current_volume,
        "current_rate": _abhl_ar_v3_rate(current_volume, current_capacity),
        "old_capacity_for_n1": old_capacity_for_n1 if has_n1 else None,
        "n1_volume": n1_volume if has_n1 else None,
        "n1_rate": _abhl_ar_v3_rate(n1_volume, old_capacity_for_n1) if has_n1 else None,
    }


def _abhl_ar_v3_total_from_fra_logic(data: dict) -> dict:
    # Le nom historique de la fonction est conservé pour compatibilité,
    # mais AR ne doit pas reprendre le taux N-1 FRA.
    all_codes = []
    for group_code, _ in _ABHL_AR_V3_GROUPS:
        all_codes.extend(_abhl_ar_v3_codes_for_group(data, group_code))
    return _abhl_ar_v3_summary(data, all_codes)


if "_abhl_v21_original_ar_display_name" not in globals():
    _abhl_v21_original_ar_display_name = _abhl_ar_v3_display_name


def _abhl_ar_v3_display_name(data: dict, code: str) -> str:
    if code in _ABHL_V21_ARABIC_BARRAGE_NAMES:
        return _ABHL_V21_ARABIC_BARRAGE_NAMES[code]
    return _abhl_v21_original_ar_display_name(data, code)

# === ABHL V21 SITUATION FRA/AR OFFICIAL FORMULAS END ===
# === ABHL V22.1 GENERAL SIX SHEETS START ===
# Version générale : la date du 04/08/2026 n'intervient jamais dans les calculs.
# Les constantes ci-dessous décrivent uniquement des règles de mise en forme /
# calcul propres au modèle Excel agence. Elles ne contiennent aucune valeur de
# barrage, aucun volume, aucun taux et aucune valeur d'une date de test.

from app.modules.situation.mappings import (
    NORMAL_RESTITUTION_MAPPING as _ABHL_V221_NORMAL_RESTITUTION_MAPPING,
    TRANSFER_RESTITUTION_MAPPING as _ABHL_V221_TRANSFER_RESTITUTION_MAPPING,
)

_ABHL_V221_AR_SUBTOTAL_LABELS = {
    "LOUKKOS_TOTAL": "مجموع اللكوس",
    "TANGER_TOTAL": "مجموع طنجة ",
    "TETOUAN_TOTAL": "مجموع تطوان",
    "AL_HOCEIMA_TOTAL": "مجموع الحسيمة",
}

# REGLES, pas valeurs :
# Dans le fichier officiel, la capacité de Joumoua est présentée dans Situation
# AR avec une précision d'une décimale. La valeur source reste dynamique.
_ABHL_V221_AR_CAPACITY_ROUND_1_CODES = {"JOUMOUA"}

# Dans le fichier officiel, le sous-total capacité Al Hoceima est arrondi à
# une décimale. Le sous-total est recalculé à partir des capacités sources.
_ABHL_V221_AR_SUBTOTAL_CAPACITY_ROUND_1_GROUPS = {"AL_HOCEIMA_TOTAL"}


def _abhl_v221_excel_round(value, digits: int = 1):
    """Arrondi Excel ROUND_HALF_UP générique, sans valeur métier codée en dur."""
    if value is None:
        return None
    try:
        quantum = Decimal("1").scaleb(-int(digits))
        return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))
    except Exception:
        return value


def _abhl_v221_zero(value) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _abhl_v221_lacher_value(
    data: dict,
    code: str,
    col: str,
    lachers: dict,
    mapping: dict,
    total_col: str,
):
    """
    Règle générale de l'Excel agence :
      - colonne applicable + valeur absente/nulle => 0 ;
      - colonne non applicable au barrage => vide ;
      - total => numérique, 0 lorsqu'il n'y a aucune restitution.

    Les barrages dynamiques non présents dans le mapping officiel conservent
    le comportement générique existant.
    """
    official_codes = set(data.get("official_codes") or [])

    if code in official_codes and code in mapping:
        if col == total_col:
            return lachers.get(col, 0.0)
        if col not in (mapping.get(code) or {}):
            return None
        return lachers.get(col, 0.0)

    return lachers.get(col, 0.0)


def fill_situation_detaillee(ws, data: dict):
    """Remplit Situation Détaillée avec les données de LA DATE demandée."""
    dates = data["dates"]
    codes = _abhl_sq_codes(data)
    total_row = _abhl_sq_prepare_detail_rows(ws, data, 22)

    fill_dates(
        ws,
        dates["date_situation"],
        dates["date_veille"],
        dates["date_annee_precedente"],
    )

    for index, code in enumerate(codes):
        row_data = data["normal_rows"][code]
        cote_row, volume_row = _abhl_sq_row_pair(index)

        write_cell(ws, f"A{cote_row}", row_data["label"])
        write_cell(ws, f"A{volume_row}", row_data.get("bathy_label") or "")

        write_cell(ws, f"B{cote_row}", row_data["cote_normale"])
        write_cell(ws, f"C{cote_row}", row_data["cote_veille"])
        write_cell(ws, f"D{cote_row}", row_data["cote_jour"])
        write_cell(ws, f"E{cote_row}", row_data["variation_cote_cm"])

        write_cell(ws, f"B{volume_row}", row_data["volume_normal_current"])
        write_cell(ws, f"C{volume_row}", row_data["volume_veille"])
        write_cell(ws, f"D{volume_row}", row_data["volume_jour"])
        write_cell(ws, f"E{volume_row}", row_data["variation_volume"])

        lachers = row_data.get("lachers") or {}
        for col in ["F", "G", "H", "I", "J", "K"]:
            write_cell(
                ws,
                f"{col}{cote_row}",
                _abhl_v221_lacher_value(
                    data,
                    code,
                    col,
                    lachers,
                    _ABHL_V221_NORMAL_RESTITUTION_MAPPING,
                    "K",
                ),
            )

        write_cell(ws, f"M{cote_row}", row_data["volume_jour"])
        write_cell(ws, f"N{cote_row}", row_data["taux_remplissage"])
        write_cell(ws, f"O{cote_row}", row_data["volume_annee_precedente"])
        write_cell(ws, f"P{cote_row}", row_data["taux_annee_precedente"])
        write_cell(ws, f"Q{cote_row}", row_data["pluie_mm"])

        write_cell(ws, f"T{cote_row}", row_data["cote_normale"])
        write_cell(ws, f"T{volume_row}", row_data["volume_normal_old"])
        write_cell(ws, f"U{volume_row}", row_data["volume_jour"])
        write_cell(ws, f"V{volume_row}", row_data["volume_annee_precedente"])

    totals = data["normal_totals"]
    write_cell(ws, f"A{total_row}", "Ensemble des barrages")
    for col in [
        "B", "C", "D", "E", "F", "G", "H", "I", "J", "K",
        "M", "N", "O", "P", "T", "U", "V",
    ]:
        write_cell(ws, f"{col}{total_row}", totals.get(col))

    try:
        ws.print_area = f"A1:V{total_row + 5}"
    except Exception:
        pass


def fill_situation_detaillee_transfer(ws, data: dict):
    """Remplit Situation Détaillée (T) avec les données de LA DATE demandée."""
    dates = data["dates"]
    codes = _abhl_sq_codes(data)
    total_row = _abhl_sq_prepare_detail_rows(ws, data, 18)

    fill_dates_transfer(
        ws,
        dates["date_situation"],
        dates["date_veille"],
        dates["date_annee_precedente"],
    )

    for index, code in enumerate(codes):
        row_data = data["transfer_rows"][code]
        cote_row, volume_row = _abhl_sq_row_pair(index)

        write_cell(ws, f"A{cote_row}", row_data["label"])
        write_cell(ws, f"A{volume_row}", row_data.get("bathy_label") or "")

        write_cell(ws, f"B{cote_row}", row_data["cote_normale"])
        write_cell(ws, f"C{cote_row}", row_data["cote_veille"])
        write_cell(ws, f"D{cote_row}", row_data["cote_jour"])
        write_cell(ws, f"E{cote_row}", row_data["variation_cote_cm"])

        write_cell(ws, f"B{volume_row}", row_data["volume_normal_old"])
        write_cell(ws, f"C{volume_row}", row_data["volume_veille"])
        write_cell(ws, f"D{volume_row}", row_data["volume_jour"])
        write_cell(ws, f"E{volume_row}", row_data["variation_volume"])

        lachers = row_data.get("lachers") or {}
        for col in ["F", "G", "H", "I", "J", "K", "L"]:
            write_cell(
                ws,
                f"{col}{cote_row}",
                _abhl_v221_lacher_value(
                    data,
                    code,
                    col,
                    lachers,
                    _ABHL_V221_TRANSFER_RESTITUTION_MAPPING,
                    "L",
                ),
            )

        write_cell(ws, f"N{cote_row}", row_data["volume_jour"])
        write_cell(ws, f"O{cote_row}", row_data["taux_remplissage"])
        write_cell(ws, f"P{cote_row}", row_data["volume_annee_precedente"])
        write_cell(ws, f"Q{cote_row}", row_data["taux_annee_precedente"])
        write_cell(ws, f"R{cote_row}", row_data["pluie_mm"])

    totals = data["transfer_totals"]
    write_cell(ws, f"A{total_row}", "Ensemble des barrages")
    for col in [
        "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L",
        "N", "O", "P", "Q",
    ]:
        write_cell(ws, f"{col}{total_row}", totals.get(col))

    try:
        ws.print_area = f"A1:R{total_row + 5}"
    except Exception:
        pass


def _abhl_v221_ar_row_values(data: dict, code: str) -> dict:
    """
    Valeurs AR calculées depuis data. Aucune valeur fixe de barrage.

    Seule la REGLE du modèle Excel est codée : pour les codes déclarés dans
    _ABHL_V221_AR_CAPACITY_ROUND_1_CODES, on arrondit la capacité SOURCE à
    une décimale puis on recalcule le taux courant avec cette capacité.
    """
    values = dict(_abhl_ar_v3_row_values(data, code))

    if code in _ABHL_V221_AR_CAPACITY_ROUND_1_CODES:
        source_capacity = values.get("current_capacity")
        if source_capacity is not None:
            rounded_capacity = _abhl_v221_excel_round(source_capacity, 1)
            values["current_capacity"] = rounded_capacity
            values["current_rate"] = _abhl_ar_v3_rate(
                values.get("current_volume"),
                rounded_capacity,
            )

    return values


def _abhl_v221_ar_summary(data: dict, group_code: str, codes: list[str]) -> dict:
    """Sous-total AR entièrement recalculé à partir des barrages présents."""
    current_capacity = 0.0
    current_volume = 0.0
    old_capacity_for_n1 = 0.0
    n1_volume = 0.0
    has_n1 = False

    official_codes = set(_ABHL_AR_V3_OFFICIAL_GROUPS.get(group_code, []))
    official_current_capacity = 0.0
    dynamic_current_capacity = 0.0

    for code in codes:
        values = _abhl_v221_ar_row_values(data, code)
        capacity = _abhl_v221_zero(values.get("current_capacity"))

        if code in official_codes:
            official_current_capacity += capacity
        else:
            dynamic_current_capacity += capacity

        current_volume += _abhl_v221_zero(values.get("current_volume"))

        if values.get("n1_volume") is not None:
            has_n1 = True
            old_capacity_for_n1 += _abhl_v221_zero(values.get("old_capacity_for_n1"))
            n1_volume += _abhl_v221_zero(values.get("n1_volume"))

    # Règle du modèle Excel, calculée dynamiquement sur le sous-total courant.
    if (
        group_code in _ABHL_V221_AR_SUBTOTAL_CAPACITY_ROUND_1_GROUPS
        and official_codes.intersection(codes)
    ):
        official_current_capacity = _abhl_v221_excel_round(official_current_capacity, 1)

    current_capacity = official_current_capacity + dynamic_current_capacity

    return {
        "current_capacity": current_capacity,
        "current_volume": current_volume,
        "current_rate": _abhl_ar_v3_rate(current_volume, current_capacity),
        "old_capacity_for_n1": old_capacity_for_n1 if has_n1 else None,
        "n1_volume": n1_volume if has_n1 else None,
        # IMPORTANT : Situation AR garde la capacité HISTORIQUE pour N-1.
        "n1_rate": _abhl_ar_v3_rate(n1_volume, old_capacity_for_n1) if has_n1 else None,
    }


def _abhl_v221_ar_total(data: dict) -> dict:
    """Total AR = somme dynamique des groupes réellement présents."""
    current_capacity = 0.0
    current_volume = 0.0
    old_capacity_for_n1 = 0.0
    n1_volume = 0.0
    has_n1 = False

    for group_code, _ in _ABHL_AR_V3_GROUPS:
        codes = _abhl_ar_v3_codes_for_group(data, group_code)
        if not codes:
            continue

        values = _abhl_v221_ar_summary(data, group_code, codes)
        current_capacity += _abhl_v221_zero(values.get("current_capacity"))
        current_volume += _abhl_v221_zero(values.get("current_volume"))

        if values.get("n1_volume") is not None:
            has_n1 = True
            old_capacity_for_n1 += _abhl_v221_zero(values.get("old_capacity_for_n1"))
            n1_volume += _abhl_v221_zero(values.get("n1_volume"))

    return {
        "current_capacity": current_capacity,
        "current_volume": current_volume,
        "current_rate": _abhl_ar_v3_rate(current_volume, current_capacity),
        "old_capacity_for_n1": old_capacity_for_n1 if has_n1 else None,
        "n1_volume": n1_volume if has_n1 else None,
        "n1_rate": _abhl_ar_v3_rate(n1_volume, old_capacity_for_n1) if has_n1 else None,
    }


def fill_situation_ar(ws, data: dict):
    """Situation AR générale : toutes les valeurs viennent de data."""
    styles = _abhl_ar_v3_styles()
    d = data["dates"]["date_situation"]
    d_n1 = data["dates"]["date_annee_precedente"]

    ws.sheet_view.rightToLeft = True
    _abhl_ar_v3_clear(ws)

    ws.merge_cells(start_row=6, start_column=1, end_row=6, end_column=11)
    ws.cell(
        row=6,
        column=1,
        value=f"حالة ملء السدود بتاريخ {d.day} {_abhl_ar_v3_month_ar(d.month)} {d.year}",
    )
    ws.cell(row=6, column=1).font = styles["title_font"]
    ws.cell(row=6, column=1).alignment = styles["center"]

    ws.merge_cells(start_row=8, start_column=3, end_row=8, end_column=4)
    ws.cell(row=8, column=3, value=_abhl_ar_v3_date_slash(d_n1))
    ws.cell(row=9, column=3, value="نسبة الملء (%)")
    ws.cell(row=9, column=4, value="الحجم (مليون م³)")

    ws.merge_cells(start_row=8, start_column=5, end_row=8, end_column=6)
    ws.cell(row=8, column=5, value=_abhl_ar_v3_date_slash(d))
    ws.cell(row=9, column=5, value="نسبة الملء (%)")
    ws.cell(row=9, column=6, value="الحجم (مليون م³)")

    ws.merge_cells(start_row=8, start_column=7, end_row=9, end_column=7)
    ws.cell(row=8, column=7, value="الحجم العادي\n(مليون م³)")

    ws.merge_cells(start_row=8, start_column=8, end_row=9, end_column=8)
    ws.cell(row=8, column=8, value="السد")

    ws.merge_cells(start_row=8, start_column=9, end_row=9, end_column=9)
    ws.cell(row=8, column=9, value="المنظومة")

    _abhl_ar_v3_style_range(
        ws, 8, 9, 3, 9,
        styles["light_gray"], styles["header_font"], styles["center"],
    )

    ws.merge_cells(start_row=8, start_column=13, end_row=9, end_column=13)
    ws.cell(row=8, column=13, value="Volume normal\n(Mm³)")

    ws.merge_cells(start_row=8, start_column=14, end_row=8, end_column=15)
    ws.cell(row=8, column=14, value="الحجم (مليون م³)")
    ws.cell(row=9, column=14, value=_abhl_ar_v3_date_slash(d_n1))
    ws.cell(row=9, column=15, value=_abhl_ar_v3_date_slash(d))

    _abhl_ar_v3_style_range(
        ws, 8, 9, 13, 15,
        styles["light_gray"], styles["header_font"], styles["center"],
    )

    row = 10

    for group_code, group_label_ar in _ABHL_AR_V3_GROUPS:
        codes = _abhl_ar_v3_codes_for_group(data, group_code)
        if not codes:
            continue

        group_start = row

        for code in codes:
            values = _abhl_v221_ar_row_values(data, code)
            _abhl_ar_v3_style_data_row(ws, row)

            ws.cell(row=row, column=8, value=_abhl_ar_v3_display_name(data, code))
            ws.cell(row=row, column=8).alignment = styles["right"]

            _abhl_ar_v3_write_main_row(ws, row, values)
            _abhl_ar_v3_write_secondary_row(ws, row, values)

            # La cellule reste NUMERIQUE. Le format n'impose que l'affichage.
            if code in _ABHL_V221_AR_CAPACITY_ROUND_1_CODES:
                ws.cell(row=row, column=7, value=values.get("current_capacity"))
                ws.cell(row=row, column=7).number_format = "0.0"

            row += 1

        group_end = row - 1
        _abhl_ar_v3_merge_group(ws, group_start, group_end, group_label_ar)

        if len(codes) > 1:
            subtotal = _abhl_v221_ar_summary(data, group_code, codes)

            ws.merge_cells(start_row=row, start_column=8, end_row=row, end_column=9)
            ws.cell(
                row=row,
                column=8,
                value=_ABHL_V221_AR_SUBTOTAL_LABELS.get(group_code, "المجموع الجزئي"),
            )

            _abhl_ar_v3_style_total_row(ws, row)
            _abhl_ar_v3_write_main_row(ws, row, subtotal)
            _abhl_ar_v3_write_secondary_row(ws, row, subtotal)

            if group_code in _ABHL_V221_AR_SUBTOTAL_CAPACITY_ROUND_1_GROUPS:
                ws.cell(row=row, column=7, value=subtotal.get("current_capacity"))
                ws.cell(row=row, column=7).number_format = "0.0"

            row += 1

    total = _abhl_v221_ar_total(data)

    ws.merge_cells(start_row=row, start_column=8, end_row=row, end_column=9)
    ws.cell(row=row, column=8, value="المجموع")

    _abhl_ar_v3_style_total_row(ws, row)
    _abhl_ar_v3_write_main_row(ws, row, total)
    _abhl_ar_v3_write_secondary_row(ws, row, total)

    for col, width in {
        "A": 4, "B": 4, "C": 14, "D": 16, "E": 14, "F": 16,
        "G": 16, "H": 26, "I": 16, "J": 3, "K": 3, "L": 3,
        "M": 18, "N": 16, "O": 16,
    }.items():
        ws.column_dimensions[col].width = width

    for r in range(6, row + 1):
        ws.row_dimensions[r].height = 24

    for r in range(1, 120):
        for c in range(1, 26):
            in_title = r == 6 and 1 <= c <= 11
            in_main = 8 <= r <= row and 3 <= c <= 9
            in_side = 8 <= r <= row and 13 <= c <= 15
            if not in_title and not in_main and not in_side:
                cell = ws.cell(row=r, column=c)
                if cell.value is None:
                    cell.border = styles["no_border"]
                    cell.fill = styles["none_fill"]

    try:
        ws.print_area = f"A6:O{row}"
    except Exception:
        pass

# === ABHL V22.1 GENERAL SIX SHEETS END ===

# === ABHL V23 DAR KHROFA IRRIGATION DISPLAY START ===
# Correctif ciblé d'une régression d'affichage V22/V22.1.
#
# IMPORTANT :
# - aucune date n'est codée en dur ;
# - aucune valeur d'irrigation n'est codée en dur ;
# - le TOTAL existant n'est pas modifié ;
# - seules les cellules Irrigation de DAR_KHROFA sont sécurisées ;
# - toutes les autres règles V21/V22.1 restent inchangées.

if "_abhl_v23_original_lacher_value" not in globals():
    _abhl_v23_original_lacher_value = _abhl_v221_lacher_value


def _abhl_v23_num(value) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _abhl_v23_dar_irrigation_from_lachers(lachers: dict, total_col: str) -> float:
    """
    Retourne l'irrigation Dar Khrofa sans dépendre d'une date ou d'une valeur fixe.

    Le dictionnaire ``lachers`` est déjà construit depuis PostgreSQL pour
    l'intervalle correspondant à la date de situation demandée.

    total_col == "K" : Situation Détaillée
        H = Irrigation ; K = Total

    total_col == "L" : Situation Détaillée (T)
        I = Irrigation ; L = Total
    """
    lachers = lachers or {}

    if total_col == "K":
        irrigation_col = "H"
        other_cols = ("F", "G", "I", "J")
    elif total_col == "L":
        irrigation_col = "I"
        other_cols = ("F", "G", "H", "J", "K")
    else:
        return 0.0

    explicit = lachers.get(irrigation_col)
    explicit_num = _abhl_v23_num(explicit)

    # Si la composante explicite est réellement renseignée, on la conserve.
    # Une valeur 0 peut cependant être le symptôme de la régression : le TOTAL
    # contient alors l'irrigation alors que la composante visible vaut 0.
    if explicit is not None and abs(explicit_num) > 1e-12:
        return explicit_num

    total = _abhl_v23_num(lachers.get(total_col))
    others = sum(_abhl_v23_num(lachers.get(col)) for col in other_cols)
    residual = total - others

    # Evite uniquement les -0.0 / petites poussières numériques.
    if abs(residual) < 1e-9:
        return 0.0

    return residual


def _abhl_v221_lacher_value(
    data: dict,
    code: str,
    col: str,
    lachers: dict,
    mapping: dict,
    total_col: str,
):
    """
    Extension V23 de la fonction V22.1.

    Pour DAR_KHROFA seulement, sécurise la colonne Irrigation à partir du TOTAL
    déjà calculé pour la date demandée. Les autres barrages et les autres
    colonnes passent exactement par la logique V22.1 d'origine.
    """
    if code == "DAR_KHROFA":
        if total_col == "K" and col == "H":
            return _abhl_v23_dar_irrigation_from_lachers(lachers, "K")
        if total_col == "L" and col == "I":
            return _abhl_v23_dar_irrigation_from_lachers(lachers, "L")

    return _abhl_v23_original_lacher_value(
        data,
        code,
        col,
        lachers,
        mapping,
        total_col,
    )

# === ABHL V23 DAR KHROFA IRRIGATION DISPLAY END ===

# === ABHL V24 DAR KHROFA DETAIL POST-FILL START ===
#
# Correctif final ciblé sur l'affichage de l'irrigation Dar Khrofa.
#
# V24 ne remplace aucune donnée métier :
# - il utilise row_data["lachers"] déjà calculé depuis PostgreSQL ;
# - aucune date n'est codée en dur ;
# - aucune valeur (156772 ou autre) n'est codée en dur ;
# - le TOTAL n'est jamais recalculé/modifié ;
# - les autres barrages ne sont jamais touchés.

if "_abhl_v24_original_fill_situation_detaillee" not in globals():
    _abhl_v24_original_fill_situation_detaillee = fill_situation_detaillee

if "_abhl_v24_original_fill_situation_detaillee_transfer" not in globals():
    _abhl_v24_original_fill_situation_detaillee_transfer = fill_situation_detaillee_transfer


def _abhl_v24_float(value):
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _abhl_v24_visible_irrigation(lachers: dict, irrigation_col: str, total_col: str, other_cols):
    """
    Retourne la valeur d'irrigation réellement calculée pour la date demandée.

    Priorité :
    1) la composante Irrigation déjà calculée dans ``lachers`` ;
    2) si elle vaut 0/None alors que le total est non nul, résidu du total
       après retrait des autres composantes visibles.

    Le fallback est uniquement une protection contre la régression d'affichage.
    Il n'invente aucune donnée.
    """
    lachers = lachers or {}

    explicit_raw = lachers.get(irrigation_col)
    explicit = _abhl_v24_float(explicit_raw)

    if explicit_raw is not None and abs(explicit) > 1e-12:
        return explicit

    total = _abhl_v24_float(lachers.get(total_col))
    others = sum(_abhl_v24_float(lachers.get(col)) for col in other_cols)
    residual = total - others

    if abs(residual) < 1e-9:
        return 0.0

    return residual


def _abhl_v24_dar_cote_row(data: dict):
    """Trouve dynamiquement la ligne Dar Khrofa dans l'ordre réellement généré."""
    codes = list(_abhl_sq_codes(data))
    if "DAR_KHROFA" not in codes:
        return None

    index = codes.index("DAR_KHROFA")
    cote_row, _volume_row = _abhl_sq_row_pair(index)
    return cote_row


def fill_situation_detaillee(ws, data: dict):
    """
    Exécute toute la logique existante V22.1/V23, puis sécurise uniquement
    Dar Khrofa -> Irrigation dans Situation Détaillée.
    """
    _abhl_v24_original_fill_situation_detaillee(ws, data)

    row = _abhl_v24_dar_cote_row(data)
    if row is None:
        return

    row_data = (data.get("normal_rows") or {}).get("DAR_KHROFA") or {}
    lachers = row_data.get("lachers") or {}

    irrigation = _abhl_v24_visible_irrigation(
        lachers=lachers,
        irrigation_col="H",
        total_col="K",
        other_cols=("F", "G", "I", "J"),
    )

    # Ecriture APRES le masque V22.1 : il ne peut plus être retransformé en vide.
    write_cell(ws, f"H{row}", irrigation)


def fill_situation_detaillee_transfer(ws, data: dict):
    """
    Exécute toute la logique existante V22.1/V23, puis sécurise uniquement
    Dar Khrofa -> Irrigation dans Situation Détaillée (T).
    """
    _abhl_v24_original_fill_situation_detaillee_transfer(ws, data)

    row = _abhl_v24_dar_cote_row(data)
    if row is None:
        return

    row_data = (data.get("transfer_rows") or {}).get("DAR_KHROFA") or {}
    lachers = row_data.get("lachers") or {}

    irrigation = _abhl_v24_visible_irrigation(
        lachers=lachers,
        irrigation_col="I",
        total_col="L",
        other_cols=("F", "G", "H", "J", "K"),
    )

    # Ecriture APRES le masque V22.1 : il ne peut plus être retransformé en vide.
    write_cell(ws, f"I{row}", irrigation)

# === ABHL V24 DAR KHROFA DETAIL POST-FILL END ===
