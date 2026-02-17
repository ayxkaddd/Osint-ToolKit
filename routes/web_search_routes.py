"""
FastAPI routes for OSINT Search Service
"""

import json
import os
from fastapi import APIRouter, HTTPException, Body
from typing import List
from dotenv import load_dotenv

from services.web_search_service import (
    OSINTSearchService,
    SearchEngine,
    InputType,
)
from models.web_search_models import (
    SearchRequest,
    CustomDorksRequest,
    GetDorksRequest,
    SearchResponse,
    DorksResponse,
)

load_dotenv()

osint_router = APIRouter(prefix="/web", tags=["OSINT Search"])

_osint_service = None


def get_osint_service() -> OSINTSearchService:
    """Get or create OSINT service instance"""
    global _osint_service

    if _osint_service is None:
        api_key = os.getenv("SERPAPI_KEY")
        if not api_key:
            raise HTTPException(
                status_code=500,
                detail="SERPAPI_KEY not configured in environment variables"
            )
        _osint_service = OSINTSearchService(api_key)

    return _osint_service


@osint_router.post("/search", response_model=SearchResponse)
async def search_osint(request: SearchRequest):
    try:
        service = get_osint_service()

        engines = [SearchEngine(engine.value) for engine in request.engines]
        input_type = InputType(request.input_type.value)
        results = await service.search(
            value=request.value,
            input_type=input_type,
            engines=engines,
            max_results_per_dork=request.max_results_per_dork,
            rate_limit_delay=request.rate_limit_delay
        )

        return results

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@osint_router.post("/search/custom", response_model=SearchResponse)
async def search_custom_dorks(request: CustomDorksRequest):
    try:
        service = get_osint_service()

        engines = [SearchEngine(engine.value) for engine in request.engines]

        results = await service.search_custom_dorks(
            dorks=request.dorks,
            engines=engines,
            max_results_per_dork=request.max_results_per_dork,
            rate_limit_delay=request.rate_limit_delay
        )

        return results

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Custom search failed: {str(e)}")


@osint_router.post("/dorks/preview", response_model=DorksResponse)
async def get_dorks_preview(request: GetDorksRequest):
    try:
        service = get_osint_service()

        engines = [SearchEngine(engine.value) for engine in request.engines]
        input_type = InputType(request.input_type.value)

        dorks = service.get_available_dorks(
            value=request.value,
            input_type=input_type,
            engines=engines
        )

        return {
            "value": request.value,
            "input_type": request.input_type.value,
            "dorks_by_engine": dorks
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dork generation failed: {str(e)}")
