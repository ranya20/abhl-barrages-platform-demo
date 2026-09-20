from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import os

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / '.env')

DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    raise Exception('DATABASE_URL introuvable dans backend/.env')

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

with engine.connect() as conn:
    print('Connexion réussie à Supabase.')
    nb_barrages = conn.execute(text('SELECT COUNT(*) FROM barrages')).scalar()
    print('Nombre de barrages :', nb_barrages)
    result = conn.execute(text('SELECT code, nom_court, nom FROM barrages ORDER BY ordre_affichage'))
    print()
    print('Liste des barrages :')
    for row in result:
        r = row._mapping
        print(f"{r['code']} - {r['nom_court']} - {r['nom']}")