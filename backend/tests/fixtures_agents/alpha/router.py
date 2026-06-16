from fastapi import APIRouter

router = APIRouter()


@router.get("/agents/alpha/ping")
async def ping() -> dict[str, str]:
    return {"group": "alpha"}
