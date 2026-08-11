import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agentpit.auth.workos_client import WorkOsError
from agentpit.domain.exceptions import (
    AlreadyExistsError,
    BusinessRuleError,
    FeatureDisabledError,
    InsufficientGasError,
    InvalidCredentialsError,
    NotFoundError,
)

log = logging.getLogger(__name__)


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

    @app.exception_handler(WorkOsError)
    async def _workos_refused(_: Request, exc: WorkOsError) -> JSONResponse:
        """A failed sign-in, not a failed server.

        `WorkOsError` is deliberately one type for every WorkOS failure, so a
        mistyped code and a WorkOS outage arrive here together. 401 is right for
        the first and honest about the second -- either way no session exists --
        and without this handler the exception is a `RuntimeError` that falls
        through to a 500, turning a six-digit typo into "agentpit is broken".

        Handled here rather than by making `WorkOsError` a subclass of
        `InvalidCredentialsError`: the migration script catches it outside the
        API entirely, and its message must not become the response `detail`.
        That message names the WorkOS endpoint and quotes the (redacted)
        response body -- diagnostics for us, noise for whoever fat-fingered a
        digit -- so it is logged instead.
        """
        log.warning("WorkOS refused a request: %s", exc)
        return JSONResponse(
            status_code=401,
            content={"detail": "could not sign you in — request a new code"},
        )
