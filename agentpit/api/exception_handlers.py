from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agentpit.domain.exceptions import (
    AlreadyExistsError,
    BusinessRuleError,
    NotFoundError,
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(AlreadyExistsError)
    async def _already_exists(_: Request, exc: AlreadyExistsError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(BusinessRuleError)
    async def _business_rule(_: Request, exc: BusinessRuleError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
