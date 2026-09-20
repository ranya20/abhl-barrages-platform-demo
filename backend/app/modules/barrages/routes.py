from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.barrages.service import get_all_barrages, get_barrage_by_code


router = APIRouter()


@router.get("")
def list_barrages(db: Session = Depends(get_db)):
    data = get_all_barrages(db)

    return {
        "status": "ok",
        "count": len(data),
        "data": data,
    }


@router.get("/{code}")
def get_barrage(code: str, db: Session = Depends(get_db)):
    barrage = get_barrage_by_code(db, code)

    if barrage is None:
        raise HTTPException(
            status_code=404,
            detail=f"Barrage introuvable : {code}"
        )

    return {
        "status": "ok",
        "data": barrage,
    }