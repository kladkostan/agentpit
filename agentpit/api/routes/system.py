from fastapi import APIRouter

router = APIRouter(tags=["system"])


@router.get("/")
def get_version() -> dict[str, str]:
    return {"version": "1.0"}
