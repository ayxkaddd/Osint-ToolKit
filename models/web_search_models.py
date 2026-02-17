"""
Pydantic models for OSINT Search Service
"""

from pydantic import BaseModel, Field, validator
from typing import List, Optional
from enum import Enum


class SearchEngineEnum(str, Enum):
    """Search engine options"""
    GOOGLE = "google"
    YANDEX = "yandex"


class InputTypeEnum(str, Enum):
    """Input type options"""
    USERNAME = "username"
    FULL_NAME = "full_name"
    PHONE = "phone"
    EMAIL = "email"
    CUSTOM = "custom"


class SearchRequest(BaseModel):
    """Request model for OSINT search"""
    value: str = Field(..., description="Value to search for")
    input_type: InputTypeEnum = Field(..., description="Type of input data")
    engines: List[SearchEngineEnum] = Field(
        default=[SearchEngineEnum.GOOGLE],
        description="Search engines to use"
    )
    max_results_per_dork: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum results per dork query"
    )
    rate_limit_delay: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="Delay between requests in seconds"
    )

    @validator('value')
    def value_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Value cannot be empty')
        return v.strip()


class CustomDorksRequest(BaseModel):
    """Request model for custom dorks search"""
    dorks: List[str] = Field(..., description="List of custom dork queries", min_items=1)
    engines: List[SearchEngineEnum] = Field(
        default=[SearchEngineEnum.GOOGLE],
        description="Search engines to use"
    )
    max_results_per_dork: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum results per dork query"
    )
    rate_limit_delay: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="Delay between requests in seconds"
    )

    @validator('dorks')
    def dorks_not_empty(cls, v):
        if not v:
            raise ValueError('Dorks list cannot be empty')
        cleaned = [d.strip() for d in v if d.strip()]
        if not cleaned:
            raise ValueError('All dorks are empty')
        return cleaned


class GetDorksRequest(BaseModel):
    """Request model for getting available dorks without searching"""
    value: str = Field(..., description="Value to generate dorks for")
    input_type: InputTypeEnum = Field(..., description="Type of input data")
    engines: List[SearchEngineEnum] = Field(
        default=[SearchEngineEnum.GOOGLE],
        description="Search engines to generate dorks for"
    )

    @validator('value')
    def value_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Value cannot be empty')
        return v.strip()


class SearchResultItem(BaseModel):
    """Individual search result"""
    dork: str = Field(..., description="Dork query that found this result")
    engine: str = Field(..., description="Search engine used")
    title: str = Field(..., description="Result title")
    url: str = Field(..., description="Result URL")
    snippet: str = Field(..., description="Result snippet/description")
    position: int = Field(..., description="Position in search results")


class SearchQuery(BaseModel):
    """Query information"""
    value: Optional[str] = Field(None, description="Search value (if not custom dorks)")
    custom_dorks: Optional[List[str]] = Field(None, description="Custom dorks (if provided)")
    type: str = Field(..., description="Type of search performed")
    engines: List[str] = Field(..., description="Engines used")


class SearchResponse(BaseModel):
    """Response model for search results"""
    query: SearchQuery = Field(..., description="Query information")
    total_results: int = Field(..., description="Total number of unique results")
    results: List[SearchResultItem] = Field(..., description="Search results")


class DorksResponse(BaseModel):
    """Response model for getting available dorks"""
    value: str = Field(..., description="Input value")
    input_type: str = Field(..., description="Input type")
    dorks_by_engine: dict = Field(..., description="Dorks organized by engine")