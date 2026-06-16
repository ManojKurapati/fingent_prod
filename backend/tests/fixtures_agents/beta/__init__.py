"""beta group — exposes router via package __init__ (fallback)."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/agents/beta/ping")
async def ping() -> dict[str, str]:
    return {"group": "beta"}
