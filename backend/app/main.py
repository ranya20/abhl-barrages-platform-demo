from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.database import engine
from app.modules.annonce.routes import router as annonce_router
from app.modules.auth.dependencies import get_current_ready_user, require_roles
from app.modules.auth.routes import router as auth_router
from app.modules.assistant_data.routes import router as assistant_data_router
from app.modules.baremes.routes import router as baremes_router
from app.modules.barrage_admin.routes import router as barrage_admin_router
from app.modules.barrages.routes import router as barrages_router
from app.modules.bilan.routes import router as bilan_router
from app.modules.calculs.routes import router as calculs_router
from app.modules.dashboard.routes import router as dashboard_router
from app.modules.imports.routes import router as imports_router
from app.modules.restitutions.routes import router as restitutions_router
from app.modules.situation.routes import router as situation_router


app = FastAPI(
    title="ABHL Barrages Platform",
    description="Plateforme locale sécurisée de gestion quotidienne des barrages ABHL",
    version="0.2.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.get("/")
def root():
    return {
        "message": "ABHL Barrages Platform API",
        "status": "running",
        "version": "0.2.0",
    }


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "message": "Backend ABHL Barrages actif",
    }


@app.get("/api/health/db")
def check_database():
    with engine.connect() as conn:
        database_name = conn.execute(text("SELECT current_database()")).scalar()
        user_name = conn.execute(text("SELECT current_user")).scalar()
        barrages_count = conn.execute(text("SELECT COUNT(*) FROM public.barrages")).scalar()
        types_restitution_count = conn.execute(text("SELECT COUNT(*) FROM public.types_restitution")).scalar()
        barrage_types_count = conn.execute(text("SELECT COUNT(*) FROM public.barrage_types_restitution")).scalar()

    return {
        "database": database_name,
        "user": user_name,
        "barrages_count": barrages_count,
        "types_restitution_count": types_restitution_count,
        "barrage_types_restitution_count": barrage_types_count,
        "status": "ok",
    }


# Routes publiques d'authentification. Les routes /me, /logout et admin
# appliquent leurs propres dépendances de sécurité dans le module auth.
app.include_router(
    auth_router,
    prefix="/api/auth",
    tags=["Authentification"],
)


_authenticated = [Depends(get_current_ready_user)]
_data_entry = [Depends(require_roles("ADMIN", "SAISIE", "VALIDATEUR"))]
_admin_only = [Depends(require_roles("ADMIN"))]


app.include_router(
    barrages_router,
    prefix="/api/barrages",
    tags=["Barrages"],
    dependencies=_authenticated,
)

app.include_router(
    restitutions_router,
    prefix="/api/restitutions",
    tags=["Restitutions"],
    dependencies=_authenticated,
)

app.include_router(
    baremes_router,
    prefix="/api/baremes",
    tags=["Barèmes"],
    dependencies=_authenticated,
)

app.include_router(
    situation_router,
    prefix="/api/situation",
    tags=["Situation quotidienne"],
    dependencies=_authenticated,
)

app.include_router(
    calculs_router,
    prefix="/api/calculs",
    tags=["Calculs hydrauliques"],
    dependencies=_data_entry,
)

app.include_router(
    annonce_router,
    prefix="/api/annonce",
    tags=["Annonce mensuelle"],
    dependencies=_authenticated,
)

app.include_router(
    bilan_router,
    prefix="/api/bilan",
    tags=["BILAN mensuel"],
    dependencies=_authenticated,
)

app.include_router(
    barrage_admin_router,
    prefix="/api/barrage-admin",
    tags=["Gestion dynamique des barrages"],
    dependencies=_admin_only,
)

app.include_router(
    dashboard_router,
    prefix="/api/dashboard",
    tags=["Dashboard"],
    dependencies=_authenticated,
)


app.include_router(
    assistant_data_router,
    prefix="/api/assistant",
    tags=["Assistant données"],
    dependencies=_authenticated,
)

app.include_router(
    imports_router,
    prefix="/api/imports",
    tags=["Imports contrôlés"],
)

