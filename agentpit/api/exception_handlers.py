from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agentpit.domain.exceptions import (
    AlreadyExistsError,
    BusinessRuleError,
    FeatureDisabledError,
    InsufficientGasError,
    InvalidCredentialsError,
    NotFoundError,
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(AlreadyExistsError)
    async def _already_exists(_: Request, exc: AlreadyExistsError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(InvalidCredentialsError)
    async def _invalid_creds(_: Request, exc: InvalidCredentialsError) -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": str(exc)})

    @app.exception_handler(FeatureDisabledError)
    async def _feature_disabled(_: Request, exc: FeatureDisabledError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    # Registered ahead of the generic BusinessRuleError handler below it, but
    # order doesn't actually matter to Starlette's lookup -- it walks the
    # raised exception's own MRO and matches the most specific registered
    # type first, so `InsufficientGasError` (a `BusinessRuleError` subclass)
    # always wins over the catch-all regardless of registration order.
    @app.exception_handler(InsufficientGasError)
    async def _insufficient_gas(
        _: Request, exc: InsufficientGasError
    ) -> JSONResponse:
        return JSONResponse(status_code=402, content={"detail": str(exc)})

    @app.exception_handler(BusinessRuleError)
    async def _business_rule(_: Request, exc: BusinessRuleError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
