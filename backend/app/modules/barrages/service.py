from sqlalchemy import text


def get_all_barrages(db):
    query = text("""
        SELECT
            id,
            code,
            nom,
            nom_court,
            bassin_id,
            province_id,
            capacite_normale_mm3,
            cote_normale_ngm,
            cote_min_ngm,
            cote_max_ngm,
            feuille_annonce,
            feuille_djbarrage,
            fichier_bm,
            ordre_affichage,
            actif,
            statut_perimetre,
            observation
        FROM public.barrages
        ORDER BY ordre_affichage;
    """)

    rows = db.execute(query).mappings().all()
    return [dict(row) for row in rows]


def get_barrage_by_code(db, code: str):
    query = text("""
        SELECT
            id,
            code,
            nom,
            nom_court,
            bassin_id,
            province_id,
            capacite_normale_mm3,
            cote_normale_ngm,
            cote_min_ngm,
            cote_max_ngm,
            feuille_annonce,
            feuille_djbarrage,
            fichier_bm,
            ordre_affichage,
            actif,
            statut_perimetre,
            observation
        FROM public.barrages
        WHERE code = :code;
    """)

    row = db.execute(query, {"code": code.upper()}).mappings().first()
    return dict(row) if row else None