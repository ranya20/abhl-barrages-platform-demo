from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.restitutions.service import (
    get_all_types_restitution,
    get_restitutions_by_barrage_code,
)


router = APIRouter()


@router.get("/types")
def list_types_restitution(db: Session = Depends(get_db)):
    data = get_all_types_restitution(db)

    return {
        "status": "ok",
        "count": len(data),
        "data": data,
    }


@router.get("/by-barrage/{barrage_code}")
def list_restitutions_by_barrage(
    barrage_code: str,
    db: Session = Depends(get_db),
):
    data = get_restitutions_by_barrage_code(db, barrage_code)

    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"Aucune restitution trouvée pour le barrage : {barrage_code}"
        )

    return {
        "status": "ok",
        "barrage_code": barrage_code.upper(),
        "count": len(data),
        "data": data,
    }