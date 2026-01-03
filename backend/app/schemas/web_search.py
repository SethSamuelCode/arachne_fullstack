"""Research tool schemas for web search, URL fetching, and calculations."""


from pydantic import BaseModel, Field


class WebSearchRequest(BaseModel):
    """Search the web for current information."""

    query: str = Field(
        ...,
        description="The search query. Be specific and include key terms.",
        examples=[
            "latest AI developments 2024",
            "Python pandas dataframe merge examples",
        ],
    )
    max_results: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Number of results to return (1-10).",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"query": "OpenAI GPT-5 release date rumors", "max_results": 5}]
        }
    }


class WebSearchResult(BaseModel):
    """A single search result."""

    title: str
    url: str
    snippet: str


class WebSearchResponse(BaseModel):
    """Response from web search."""

    query: str = Field(..., description="The original search query")
    results: list[WebSearchResult] = Field(
        ..., description="List of search results with titles, URLs, and snippets"
    )
    result_count: int = Field(..., description="Number of results returned")


class FetchUrlRequest(BaseModel):
    """Fetch and extract content from a URL."""

    url: str = Field(
        ...,
        description="The URL to fetch. Must be a valid HTTP/HTTPS URL.",
        examples=["https://en.wikipedia.org/wiki/Python_(programming_language)"],
    )
    extract_text: bool = Field(
        default=True,
        description="If true, extract readable text content. If false, return raw HTML.",
    )
    max_length: int = Field(
        default=10000,
        ge=100,
        le=50000,
        description="Maximum characters to return. Content is truncated if longer.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "url": "https://docs.python.org/3/tutorial/",
                    "extract_text": True,
                    "max_length": 5000,
                }
            ]
        }
    }


class FetchUrlResponse(BaseModel):
    """Response from URL fetch."""

    url: str = Field(..., description="The fetched URL")
    title: str = Field(..., description="Page title if available")
    content: str = Field(..., description="Extracted text or HTML content")
    content_length: int = Field(..., description="Length of content in characters")
    truncated: bool = Field(..., description="Whether content was truncated to max_length")


class CalculateRequest(BaseModel):
    """Evaluate a mathematical expression."""

    expression: str = Field(
        ...,
        description="A mathematical expression to evaluate.",
        examples=["2 + 2", "sqrt(16) + 3**2", "(1 + 0.05)**10 * 1000", "sin(pi/4)"],
    )

    model_config = {
        "json_schema_extra": {"examples": [{"expression": "1000 * (1 + 0.07)**30"}]}
    }


class CalculateResponse(BaseModel):
    """Response from calculation."""

    expression: str = Field(..., description="The original expression")
    result: str = Field(..., description="The computed result as a string")
    result_type: str = Field(
        ..., description="Type of result (int, float, complex, etc.)"
    )
