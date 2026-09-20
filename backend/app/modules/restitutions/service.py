from sqlalchemy import text


def get_all_types_restitution(db):
    query = text("""
        SELECT
            id,
            code,
            libelle,
            unite,
            description,
            actif
        FROM public.types_restitution
        ORDER BY id;
    """)

    rows = db.execute(query).mappings().all()
    return [dict(row) for row in rows]


def get_restitutions_by_barrage_code(db, barrage_code: str):
    query = text("""
        SELECT
            barrage_code,
            barrage_nom_court,
            type_restitution_code,
            type_restitution_libelle,
            ordre_affichage,
            obligatoire,
            actif
        FROM public.v_barrages_restitutions
        WHERE barrage_code = :barrage_code
        ORDER BY ordre_affichage;
    """)

    rows = db.execute(query, {"barrage_code": barrage_code.upper()}).mappings().all()
    return [dict(row) for row in rows]