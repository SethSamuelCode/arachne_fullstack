from pydantic import BaseModel, Field


class FetchUrlResponse(BaseModel):
    """Response from URL fetch."""

    url: str = Field(..., description="The fetched URL")
    title: str = Field(..., description="Page title if available")
    content: str = Field(..., description="Extracted text or HTML content")
    content_length: int = Field(..., description="Length of content in characters")
    truncated: bool = Field(..., description="Whether content was truncated to max_length")


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
