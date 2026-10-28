"""
FastAPI routes for OSINT Search Service
"""

import os
from fastapi import APIRouter, HTTPException
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
from utils.investigation_decorator import save_investigation

load_dotenv()

# Initialize router
osint_router = APIRouter(prefix="/web", tags=["OSINT Search"])

# Initialize service (will be lazy-loaded)
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
@save_investigation(service_name="web_search", method_name="search_osint")
async def search_osint(request: SearchRequest):
    """
    Perform OSINT search using predefined dork templates

    This endpoint generates appropriate dork queries based on the input type
    (username, email, phone, full name) and searches across specified engines.

    **Cost**: Depends on SerpAPI pricing (typically ~0.01-0.05 USD per search)

    **Example**:
    ```json
    {
        "value": "john_doe",
        "input_type": "username",
        "engines": ["google", "yandex"],
        "max_results_per_dork": 10,
        "rate_limit_delay": 1.0
    }
    ```
    """
    try:
        service = get_osint_service()

        # Convert enum values to service enums
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

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@osint_router.post("/search/custom", response_model=SearchResponse)
@save_investigation(service_name="web_search", method_name="search_custom_dorks")
async def search_custom_dorks(request: CustomDorksRequest):
    """
    Perform OSINT search using custom user-provided dork queries

    This endpoint allows you to provide your own custom dork queries for more
    targeted searches. Each dork will be executed on all specified engines.

    **Cost**: Depends on SerpAPI pricing (typically ~0.01-0.05 USD per search)

    **Example**:
    ```json
    {
        "dorks": [
            "\\"john_doe\\" site:github.com",
            "\\"john_doe\\" inurl:profile",
            "intitle:\\"john doe\\" filetype:pdf"
        ],
        "engines": ["google"],
        "max_results_per_dork": 10,
        "rate_limit_delay": 1.0
    }
    ```

    **Dork Tips**:
    - Use quotes for exact matches: `"exact phrase"`
    - Site operator: `site:example.com`
    - File type: `filetype:pdf`
    - URL contains: `inurl:keyword`
    - Title contains: `intitle:keyword`
    - Combine operators: `"name" site:linkedin.com filetype:pdf`
    """
    try:
        service = get_osint_service()

        # Convert enum values to service enums
        engines = [SearchEngine(engine.value) for engine in request.engines]

        results = await service.search_custom_dorks(
            dorks=request.dorks,
            engines=engines,
            max_results_per_dork=request.max_results_per_dork,
            rate_limit_delay=request.rate_limit_delay
        )

        return results

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Custom search failed: {str(e)}")


@osint_router.post("/dorks/preview", response_model=DorksResponse)
async def get_dorks_preview(request: GetDorksRequest):
    """
    Preview dork queries that would be generated without executing searches

    This endpoint is useful for:
    - Understanding what dorks will be used for a search
    - Testing dork generation logic
    - Creating custom dork templates

    **This endpoint is FREE** - it doesn't execute any searches

    **Example**:
    ```json
    {
        "value": "john_doe",
        "input_type": "username",
        "engines": ["google", "yandex"]
    }
    ```

    **Response** shows all dorks that would be generated for each engine.
    You can then modify these and use the `/search/custom` endpoint.
    """
    try:
        service = get_osint_service()

        # Convert enum values to service enums
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

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dork generation failed: {str(e)}")


@osint_router.get("/health")
async def health_check():
    """
    Check if OSINT service is configured and ready

    Returns service configuration status and API key presence
    """
    api_key = os.getenv("SERPAPI_KEY")

    return {
        "status": "healthy" if api_key else "misconfigured",
        "api_key_configured": bool(api_key),
        "message": "OSINT service is ready" if api_key else "SERPAPI_KEY not configured"
    }


@osint_router.get("/info")
async def get_service_info():
    """
    Get information about available search options and input types

    Returns details about:
    - Supported input types
    - Available search engines
    - Example dork patterns
    """
    return {
        "supported_input_types": [
            {
                "value": "username",
                "description": "Search for social media profiles and online presence",
                "example": "john_doe"
            },
            {
                "value": "full_name",
                "description": "Search for people by their full name",
                "example": "John Doe"
            },
            {
                "value": "email",
                "description": "Search for email addresses across the web",
                "example": "john@example.com"
            },
            {
                "value": "phone",
                "description": "Search for phone numbers",
                "example": "+1-555-123-4567"
            },
            {
                "value": "custom",
                "description": "Use your own custom dork queries",
                "example": "Use /search/custom endpoint"
            }
        ],
        "supported_engines": [
            {
                "value": "google",
                "description": "Google Search - Best for global results"
            },
            {
                "value": "yandex",
                "description": "Yandex Search - Best for Russian/CIS content"
            }
        ],
        "dork_operators": [
            {"operator": "\"exact phrase\"", "description": "Search for exact phrase"},
            {"operator": "site:domain.com", "description": "Limit to specific site"},
            {"operator": "inurl:keyword", "description": "URL must contain keyword"},
            {"operator": "intitle:keyword", "description": "Title must contain keyword"},
            {"operator": "filetype:pdf", "description": "Limit to specific file type"},
            {"operator": "OR", "description": "Combine multiple search terms"},
            {"operator": "AND", "description": "All terms must be present"},
            {"operator": "-keyword", "description": "Exclude keyword from results"}
        ],
        "rate_limiting": {
            "default_delay": 1.0,
            "recommended_delay": 1.5,
            "note": "Higher delays reduce risk of rate limiting"
        },
        "cost_info": {
            "note": "Costs depend on SerpAPI pricing",
            "typical_cost_per_search": "$0.01 - $0.05 USD",
            "free_preview": "Use /dorks/preview to see queries before searching"
        }
    }