import logging

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.schemas import (
    ErrorResponse,
    ProspectDiscoveryRequest,
    ProspectDiscoveryResponse,
)
from app.services.llm_service import LLMServiceError
from app.services.prospect_service import ProspectDiscoveryService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

app = FastAPI(
    title="AI Multi-Platform Prospect Discovery API",
    description="Discovers, validates, and consolidates public prospect profiles and contact details across platforms.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_discovery_service: ProspectDiscoveryService | None = None


def get_prospect_service(settings: Settings = Depends(get_settings)) -> ProspectDiscoveryService:
    global _discovery_service
    if _discovery_service is None:
        _discovery_service = ProspectDiscoveryService(settings=settings)
    else:
        _discovery_service.settings = settings
        _discovery_service.llm.settings = settings
    return _discovery_service


@app.exception_handler(LLMServiceError)
async def handle_llm_service_error(_: Request, exc: LLMServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content=ErrorResponse(
            error="Query understanding service unavailable",
            detail=str(exc),
        ).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    detail = "; ".join(err.get("msg", "Invalid input") for err in exc.errors())
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(error="Invalid search query", detail=detail).model_dump(),
    )


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "AI Multi-Platform Prospect Discovery API",
        "status": "running",
        "endpoint": "POST /prospect-discovery",
        "docs": "/docs",
    }


@app.get("/health")
async def health(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    return {
        "status": "ok",
        "llm_configured": bool(settings.gemini_api_key or settings.openai_api_key),
    }


@app.post(
    "/prospect-discovery",
    response_model=ProspectDiscoveryResponse,
    responses={
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def discover_prospects(
    payload: ProspectDiscoveryRequest,
    service: ProspectDiscoveryService = Depends(get_prospect_service),
) -> ProspectDiscoveryResponse:
    return await service.discover(payload.query)
