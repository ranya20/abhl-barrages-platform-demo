from datetime import date


DATE_CHANGEMENT_TAUX = date(2026, 3, 1)
DATE_CHANGEMENT_VOLUME = date(2026, 3, 12)


TARGET_BARRAGES_ORDER = [
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
    "CHEFCHAOUEN",
    "KHATTABI",
    "JOUMOUA",
]


OFFICIAL_TOTALS = {
    "volume_normal_current": 1956.6,
    "volume_normal_old": 1910.3,
}


SITUATION_ROWS = {
    "BOEM": {
        "label": "1. Oued El Makhazine",
        "cote_row": 14,
        "volume_row": 15,
        "cote_normale_current": 61.50,
        "volume_normal_current": 695.8,
        "old_volume_normal_mm3": 672.859,
    },
    "DAR_KHROFA": {
        "label": "2. Dar Khrofa",
        "cote_row": 16,
        "volume_row": 17,
        "cote_normale_current": 165.0,
        "volume_normal_current": 474.7,
        "old_volume_normal_mm3": 480.2653,
    },
    "BIB": {
        "label": "3. Ibn Batouta",
        "cote_row": 18,
        "volume_row": 19,
        "cote_normale_current": 48.00,
        "volume_normal_current": 29.2,
        "old_volume_normal_mm3": 29.126,
    },
    "9_AVRIL": {
        "label": "4. 9 Avril 1947",
        "cote_row": 20,
        "volume_row": 21,
        "cote_normale_current": 46.00,
        "volume_normal_current": 305.6,
        "old_volume_normal_mm3": 299.961,
    },
    "KHARROUB": {
        "label": "5.Kharroub",
        "cote_row": 22,
        "volume_row": 23,
        "cote_normale_current": 85.00,
        "volume_normal_current": 188.7,
        "old_volume_normal_mm3": 188.7,
    },
    "TANGER_MED": {
        "label": "6.Tanger-Méditerrannée",
        "cote_row": 24,
        "volume_row": 25,
        "cote_normale_current": 76.5,
        "volume_normal_current": 22.6,
        "old_volume_normal_mm3": 22.023,
    },
    "NAKHLA": {
        "label": "7. Nakhla       ",
        "cote_row": 26,
        "volume_row": 27,
        "cote_normale_current": 190.65,
        "volume_normal_current": 4.209826352083337,
        "old_volume_normal_mm3": 4.209826352083337,
    },
    "SMIR": {
        "label": "8. Smir",
        "cote_row": 28,
        "volume_row": 29,
        "cote_normale_current": 43.65,
        "volume_normal_current": 45.0,
        "old_volume_normal_mm3": 38.95126621568627,
    },
    "MHB_MEHDI": {
        "label": "9. M.H.B. El Mehdi",
        "cote_row": 30,
        "volume_row": 31,
        "cote_normale_current": 120.0,
        "volume_normal_current": 29.6,
        "old_volume_normal_mm3": 23.423616666666668,
    },
    "CAI": {
        "label": "10. Charif Al Idrissi",
        "cote_row": 32,
        "volume_row": 33,
        "cote_normale_current": 131.0,
        "volume_normal_current": 133.4,
        "old_volume_normal_mm3": 121.647,
    },
    "CHEFCHAOUEN": {
        "label": "11. Chefchaouen",
        "cote_row": 34,
        "volume_row": 35,
        "cote_normale_current": 372.00,
        "volume_normal_current": 11.68398062083334,
        "old_volume_normal_mm3": 12.140242829600002,
    },
    "KHATTABI": {
        "label": "12. M.B.A. El Khattabi",
        "cote_row": 36,
        "volume_row": 37,
        "cote_normale_current": 140.00,
        "volume_normal_current": 10.5,
        "old_volume_normal_mm3": 11.790580177780273,
    },
    "JOUMOUA": {
        "label": "13. Joumoua",
        "cote_row": 38,
        "volume_row": 39,
        "cote_normale_current": 977.50,
        "volume_normal_current": 5.4,
        "old_volume_normal_mm3": 5.158,
    },
}


NORMAL_RESTITUTION_MAPPING = {
    "BOEM": {
        "F": ["IRRIGATION_LOUKKOS_TURBINAGE"],
        "G": ["TURBINAGE_EXCLUSIF"],
        "H": ["IRRIGATION_LOUKKOS_PRISE_AGRICOLE"],
        "I": ["AEPI"],
        "J": ["VDF", "EVAC"],
    },
    "DAR_KHROFA": {
        "H": ["PRISE_AGRICOLE"],
        "J": ["VDF", "BY_PASS", "EVAC"],
    },
    "BIB": {
        "I": ["AEPI"],
        "J": ["JETS_CREUX", "VDF", "EVAC"],
    },
    "9_AVRIL": {
        "I": ["AEPI"],
        "J": ["VDF", "BY_PASS", "EVAC"],
    },
    "KHARROUB": {
        "I": ["AEPI"],
        "J": ["VDF", "BY_PASS", "EVAC"],
    },
    "TANGER_MED": {
        "I": ["AEPI"],
        "J": ["VDF", "EVAC"],
    },
    "NAKHLA": {
        "I": ["AEPI"],
        "J": ["VDF", "EVAC"],
    },
    "SMIR": {
        "I": ["AEPI"],
        "J": ["VDF", "BY_PASS", "EVAC"],
    },
    "MHB_MEHDI": {
        "I": ["AEPI"],
        "J": ["VDF", "BY_PASS", "EVAC"],
    },
    "CAI": {
        "H": ["IRRIGATION"],
        "I": ["AEPI"],
        "J": ["VDF", "BY_PASS", "EVAC"],
    },
    "CHEFCHAOUEN": {
        "H": ["IRRIGATION"],
        "I": ["AEPI"],
        "J": ["VDF", "BY_PASS", "EVAC"],
    },
    "KHATTABI": {
        "H": ["PRISE_AGRICOLE_AM", "PRISE_AGRICOLE_AV", "SIPHON_DIGUE"],
        "I": ["AEPI"],
        "J": ["EVAC"],
    },
    "JOUMOUA": {
        "I": ["AEPI"],
        "J": ["VDF", "EVAC"],
    },
}


TRANSFER_RESTITUTION_MAPPING = {
    "BOEM": {
        "F": ["IRRIGATION_LOUKKOS_TURBINAGE"],
        "G": ["TURBINAGE_EXCLUSIF"],
        "H": ["TRANSFERT"],
        "I": ["IRRIGATION_LOUKKOS_PRISE_AGRICOLE"],
        "J": ["AEPI"],
        "K": ["VDF", "EVAC"],
    },
    "DAR_KHROFA": {
        "I": ["PRISE_AGRICOLE"],
        "K": ["VDF", "BY_PASS", "EVAC"],
    },
    "BIB": {
        "J": ["AEPI"],
        "K": ["JETS_CREUX", "VDF", "EVAC"],
    },
    "9_AVRIL": {
        "J": ["AEPI"],
        "K": ["VDF", "BY_PASS", "EVAC"],
    },
    "KHARROUB": {
        "J": ["AEPI"],
        "K": ["VDF", "BY_PASS", "EVAC"],
    },
    "TANGER_MED": {
        "J": ["AEPI"],
        "K": ["VDF", "EVAC"],
    },
    "NAKHLA": {
        "J": ["AEPI"],
        "K": ["VDF", "EVAC"],
    },
    "SMIR": {
        "J": ["AEPI"],
        "K": ["VDF", "BY_PASS", "EVAC"],
    },
    "MHB_MEHDI": {
        "J": ["AEPI"],
        "K": ["VDF", "BY_PASS", "EVAC"],
    },
    "CAI": {
        "I": ["IRRIGATION"],
        "J": ["AEPI"],
        "K": ["VDF", "BY_PASS", "EVAC"],
    },
    "CHEFCHAOUEN": {
        "I": ["IRRIGATION"],
        "J": ["AEPI"],
        "K": ["VDF", "BY_PASS", "EVAC"],
    },
    "KHATTABI": {
        "I": ["PRISE_AGRICOLE_AM", "PRISE_AGRICOLE_AV", "SIPHON_DIGUE"],
        "J": ["AEPI"],
        "K": ["EVAC"],
    },
    "JOUMOUA": {
        "J": ["AEPI"],
        "K": ["VDF", "EVAC"],
    },
}


SELECTED_EXPORT_SHEETS = [
    "Situation Détaillée",
    "Situation Détaillée (T)",
    "Situation FRA",
    "Situation AR",
    "Situation ORMVAL (Larache)",
    "Situation ORMVAL (Larache) (VT)",
]

# === ABHL SITUATION FINAL OFFICIAL VALUES V20 START ===
# Valeurs précises lues dans le fichier officiel "Situation quotidienne des barrages"
# du 04/08/2026. Ces valeurs sont parfois affichées avec 1 décimale dans Excel,
# mais les formules utilisent la valeur complète.

OFFICIAL_TOTALS.update({
    "volume_normal_current": 1956.555858858118,
    "volume_normal_old": 1910.2550058897334,
})

_ABHL_FINAL_OFFICIAL_ROWS_V20 = {
    "BOEM": {"volume_normal_current": 695.8143040166669, "old_volume_normal_mm3": 672.859, "bathy_year": 2023, "label": "1. Oued El Makhazine"},
    "DAR_KHROFA": {"volume_normal_current": 474.74761259486723, "old_volume_normal_mm3": 480.2653, "bathy_year": 2023, "label": "2. Dar Khrofa"},
    "BIB": {"volume_normal_current": 29.162767841999994, "old_volume_normal_mm3": 29.126, "bathy_year": 2023, "label": "3. Ibn Batouta"},
    "9_AVRIL": {"volume_normal_current": 305.63804704250015, "old_volume_normal_mm3": 299.961, "bathy_year": 2023, "label": "4. 9 Avril 1947"},
    "KHARROUB": {"volume_normal_current": 188.73200740583354, "old_volume_normal_mm3": 188.7, "bathy_year": 2023, "label": "5.Kharroub"},
    "TANGER_MED": {"volume_normal_current": 22.614807962499995, "old_volume_normal_mm3": 22.023, "bathy_year": 2023, "label": "6.Tanger-Mediterrannée"},
    "NAKHLA": {"volume_normal_current": 4.209826352083337, "old_volume_normal_mm3": 4.21, "bathy_year": 2014, "label": "7. Nakhla       "},
    "SMIR": {"volume_normal_current": 45.047829433333334, "old_volume_normal_mm3": 38.95126621568627, "bathy_year": 2023, "label": "8. Smir"},
    "MHB_MEHDI": {"volume_normal_current": 29.553286014166684, "old_volume_normal_mm3": 23.423616666666668, "bathy_year": 2023, "label": "9. M.H.B. El Mehdi"},
    "CAI": {"volume_normal_current": 133.43655689249988, "old_volume_normal_mm3": 121.647, "bathy_year": 2023, "label": "10. Charif Al Idrissi"},
    "CHEFCHAOUEN": {"volume_normal_current": 11.68398062083334, "old_volume_normal_mm3": 12.140242829600002, "bathy_year": 2023, "label": "11. Chefchoauen"},
    "KHATTABI": {"volume_normal_current": 10.515411685833339, "old_volume_normal_mm3": 11.790580177780273, "bathy_year": 2023, "label": "12. M.B.A. El Khattabi"},
    "JOUMOUA": {"volume_normal_current": 5.399420995000014, "old_volume_normal_mm3": 5.158, "bathy_year": 2020, "label": "13. Joumoua"},
}

for _abhl_code_v20, _abhl_values_v20 in _ABHL_FINAL_OFFICIAL_ROWS_V20.items():
    if _abhl_code_v20 in SITUATION_ROWS:
        SITUATION_ROWS[_abhl_code_v20].update(_abhl_values_v20)

try:
    NORMAL_RESTITUTION_MAPPING["BOEM"]["H"] = ["IRRIGATION_LOUKKOS_PRISE_AGRICOLE", "IRRIGATION_LOUKKOS_PRISE"]
    TRANSFER_RESTITUTION_MAPPING["BOEM"]["H"] = ["TRANSFERT", "TRANSFERT_DAR_KHROFA"]
    TRANSFER_RESTITUTION_MAPPING["BOEM"]["I"] = ["IRRIGATION_LOUKKOS_PRISE_AGRICOLE", "IRRIGATION_LOUKKOS_PRISE"]
    NORMAL_RESTITUTION_MAPPING["KHATTABI"]["H"] = ["PRISE_AGRICOLE_AM", "PRISE_AGRICOLE_AV", "SIPHON_DIGUE", "SIPHON"]
    TRANSFER_RESTITUTION_MAPPING["KHATTABI"]["I"] = ["PRISE_AGRICOLE_AM", "PRISE_AGRICOLE_AV", "SIPHON_DIGUE", "SIPHON"]
except Exception:
    pass

# === ABHL SITUATION FINAL OFFICIAL VALUES V20 END ===
# === ABHL V21 OFFICIAL SITUATION REFERENCES START ===
# Référence validée par comparaison directe avec le fichier agence du 04/08/2026.
# IMPORTANT :
# - bathy_year = année affichée dans "Situation Détaillée" (barème actuel)
# - transfer_bathy_year = année affichée dans "Situation Détaillée (T)"
# Les capacités sont conservées avec leur précision interne Excel ;
# l'arrondi à l'affichage est géré par le format de cellule, pas par la donnée.

_ABHL_V21_OFFICIAL_SITUATION_ROWS = {
    "BOEM": {
        "volume_normal_current": 695.8143040166669,
        "old_volume_normal_mm3": 672.859,
        "bathy_year": 2023,
        "transfer_bathy_year": 2013,
    },
    "DAR_KHROFA": {
        "volume_normal_current": 474.74761259486723,
        "old_volume_normal_mm3": 480.2653,
        "bathy_year": 2023,
        "transfer_bathy_year": 2018,
    },
    "BIB": {
        "volume_normal_current": 29.162767841999994,
        "old_volume_normal_mm3": 29.126,
        "bathy_year": 2023,
        "transfer_bathy_year": 2013,
    },
    "9_AVRIL": {
        "volume_normal_current": 305.63804704250015,
        "old_volume_normal_mm3": 299.961,
        "bathy_year": 2023,
        "transfer_bathy_year": 2009,
    },
    "KHARROUB": {
        "volume_normal_current": 188.73200740583354,
        "old_volume_normal_mm3": 188.7,
        "bathy_year": 2023,
        "transfer_bathy_year": 2022,
    },
    "TANGER_MED": {
        "volume_normal_current": 22.614807962499995,
        "old_volume_normal_mm3": 22.023,
        "bathy_year": 2023,
        "transfer_bathy_year": 2012,
    },
    "NAKHLA": {
        "volume_normal_current": 4.209826352083337,
        "old_volume_normal_mm3": 4.21,
        "bathy_year": 2014,
        "transfer_bathy_year": 2014,
    },
    "SMIR": {
        "volume_normal_current": 45.047829433333334,
        "old_volume_normal_mm3": 38.95126621568627,
        "bathy_year": 2023,
        "transfer_bathy_year": 2014,
    },
    "MHB_MEHDI": {
        "volume_normal_current": 29.553286014166684,
        "old_volume_normal_mm3": 23.423616666666668,
        "bathy_year": 2023,
        "transfer_bathy_year": 2014,
    },
    "CAI": {
        "volume_normal_current": 133.43655689249988,
        "old_volume_normal_mm3": 121.647,
        "bathy_year": 2023,
        "transfer_bathy_year": 2012,
    },
    "CHEFCHAOUEN": {
        "volume_normal_current": 11.68398062083334,
        "old_volume_normal_mm3": 12.140242829600002,
        "bathy_year": 2023,
        "transfer_bathy_year": 2014,
    },
    "KHATTABI": {
        "volume_normal_current": 10.515411685833339,
        "old_volume_normal_mm3": 11.790580177780273,
        "bathy_year": 2023,
        "transfer_bathy_year": 2016,
    },
    "JOUMOUA": {
        "volume_normal_current": 5.399420995000014,
        "old_volume_normal_mm3": 5.158,
        "bathy_year": 2020,
        "transfer_bathy_year": 2016,
    },
}

for _abhl_v21_code, _abhl_v21_values in _ABHL_V21_OFFICIAL_SITUATION_ROWS.items():
    if _abhl_v21_code in SITUATION_ROWS:
        SITUATION_ROWS[_abhl_v21_code].update(_abhl_v21_values)

OFFICIAL_TOTALS.update({
    "volume_normal_current": 1956.555858858118,
    "volume_normal_old": 1910.2550058897334,
})
# === ABHL V21 OFFICIAL SITUATION REFERENCES END ===
