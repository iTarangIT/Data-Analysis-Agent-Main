from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["ops"])
def health() -> dict:
    return {"status": "ok"}
