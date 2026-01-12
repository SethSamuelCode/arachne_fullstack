"""Semantic Scholar API client.

Semantic Scholar is a free, AI-powered research tool with 200M+ papers,
featuring TLDR summaries, citation context, and paper embeddings.

API Documentation: https://api.semanticscholar.org/api-docs/graph
Rate Limits:
  - Without API key: 1 request/second (shared limit)
  - With API key: 1 request/second (dedicated), can request increases
"""

import contextlib
from typing import Any, Literal

import httpx

from app.core.config import settings
from app.core.exceptions import SemanticScholarError

# Type aliases for Semantic Scholar parameters
S2SortField = Literal["paperId", "publicationDate", "citationCount"]
S2FieldOfStudy = Literal[
    "Computer Science",
    "Medicine",
    "Chemistry",
    "Biology",
    "Materials Science",
    "Physics",
    "Geology",
    "Psychology",
    "Art",
    "History",
    "Geography",
    "Sociology",
    "Business",
    "Political Science",
    "Economics",
    "Philosophy",
    "Mathematics",
    "Engineering",
    "Environmental Science",
    "Agricultural and Food Sciences",
    "Education",
    "Law",
    "Linguistics",
]
S2PublicationType = Literal[
    "Review",
    "JournalArticle",
    "CaseReport",
    "ClinicalTrial",
    "Conference",
    "Dataset",
    "Editorial",
    "LettersAndComments",
    "MetaAnalysis",
    "News",
    "Study",
    "Book",
    "BookSection",
]


class SemanticScholarClient:
    """Async HTTP client for Semantic Scholar API.

    Supports both relevance search (max 1000 results) and bulk search
    (max 10M results with boolean queries).
    """

    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    DEFAULT_TIMEOUT = 30.0
    DEFAULT_LIMIT = 20
    MAX_LIMIT_RELEVANCE = 100
    MAX_LIMIT_BULK = 1000

    def __init__(self) -> None:
        """Initialize the Semantic Scholar client."""
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client (lazy initialization)."""
        if self._client is None or self._client.is_closed:
            headers = {
                "Accept": "application/json",
                "User-Agent": "Arachne/1.0",
            }
            # Add API key if configured
            if settings.SEMANTIC_SCHOLAR_API_KEY:
                headers["x-api-key"] = settings.SEMANTIC_SCHOLAR_API_KEY

            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=self.DEFAULT_TIMEOUT,
                headers=headers,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _build_fields(
        self,
        *,
        include_abstract: bool = True,
        include_tldr: bool = True,
        include_authors: bool = True,
        include_venue: bool = True,
        include_citations: bool = True,
        include_references: bool = False,
        include_embedding: bool = False,
        include_external_ids: bool = True,
    ) -> str:
        """Build Semantic Scholar fields parameter.

        Returns:
            Comma-separated list of fields to request.
        """
        # Core fields (always included)
        fields = [
            "paperId",
            "title",
            "year",
            "isOpenAccess",
            "openAccessPdf",
            "publicationTypes",
            "publicationDate",
            "fieldsOfStudy",
            "s2FieldsOfStudy",
        ]

        if include_abstract:
            fields.append("abstract")
        if include_tldr:
            fields.append("tldr")
        if include_authors:
            fields.append("authors")
        if include_venue:
            fields.extend(["venue", "publicationVenue", "journal"])
        if include_citations:
            fields.extend(["citationCount", "influentialCitationCount", "referenceCount"])
        if include_references:
            fields.append("references")
        if include_embedding:
            fields.append("embedding.specter_v2")
        if include_external_ids:
            fields.append("externalIds")

        return ",".join(fields)

    async def search_relevance(
        self,
        query: str,
        *,
        year: str | None = None,
        publication_date_range: str | None = None,
        venue: str | None = None,
        fields_of_study: list[str] | None = None,
        publication_types: list[str] | None = None,
        open_access_only: bool = False,
        min_citation_count: int | None = None,
        offset: int = 0,
        limit: int = DEFAULT_LIMIT,
        include_abstract: bool = True,
        include_tldr: bool = True,
        include_authors: bool = True,
        include_venue: bool = True,
        include_citations: bool = True,
        include_embedding: bool = False,
    ) -> dict[str, Any]:
        """Search papers using relevance ranking (max 1000 results).

        This endpoint uses plain-text queries and returns results ranked by relevance.
        For boolean queries or more results, use search_bulk().

        Args:
            query: Plain-text search query. No special syntax supported.
            year: Year or range. Formats: "2020", "2016-2020", "2010-" (2010+), "-2015" (pre-2015).
            publication_date_range: Date range as "YYYY-MM-DD:YYYY-MM-DD".
            venue: Comma-separated venue names to filter by.
            fields_of_study: List of fields (e.g., ["Computer Science", "Medicine"]).
            publication_types: List of types (e.g., ["JournalArticle", "Conference"]).
            open_access_only: Only return papers with public PDFs.
            min_citation_count: Minimum citation count filter.
            offset: Starting index (0-based).
            limit: Results per page (1-100).
            include_abstract: Include paper abstracts.
            include_tldr: Include AI-generated TLDR summaries.
            include_authors: Include author information.
            include_venue: Include venue/journal information.
            include_citations: Include citation counts.
            include_embedding: Include SPECTER v2 embeddings.

        Returns:
            Dict with 'total', 'offset', 'next' (token), and 'data' (list of papers).

        Raises:
            SemanticScholarError: If API returns an error or is unreachable.
        """
        client = await self._get_client()

        # Clamp limit to valid range
        limit = max(1, min(limit, self.MAX_LIMIT_RELEVANCE))

        # Build fields parameter
        fields = self._build_fields(
            include_abstract=include_abstract,
            include_tldr=include_tldr,
            include_authors=include_authors,
            include_venue=include_venue,
            include_citations=include_citations,
            include_embedding=include_embedding,
        )

        # Build query parameters
        params: dict[str, Any] = {
            "query": query,
            "fields": fields,
            "offset": offset,
            "limit": limit,
        }

        # Add optional filters
        if year:
            params["year"] = year
        if publication_date_range:
            params["publicationDateOrYear"] = publication_date_range
        if venue:
            params["venue"] = venue
        if fields_of_study:
            params["fieldsOfStudy"] = ",".join(fields_of_study)
        if publication_types:
            params["publicationTypes"] = ",".join(publication_types)
        if open_access_only:
            params["openAccessPdf"] = ""  # Flag parameter (no value)
        if min_citation_count is not None:
            params["minCitationCount"] = min_citation_count

        try:
            response = await client.get("/paper/search", params=params)
            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            error_body = e.response.text if e.response else "No response body"
            retry_after = None

            # Handle rate limiting
            if e.response.status_code == 429:
                retry_after_header = e.response.headers.get("Retry-After")
                if retry_after_header:
                    with contextlib.suppress(ValueError):
                        retry_after = int(retry_after_header)
                raise SemanticScholarError(
                    message="Semantic Scholar rate limit exceeded. Please wait before retrying.",
                    api_status_code=429,
                    retry_after=retry_after,
                    details={"response": error_body},
                ) from e

            raise SemanticScholarError(
                message=f"Semantic Scholar API error: {e.response.status_code} - {error_body}",
                api_status_code=e.response.status_code,
                details={"url": str(e.request.url), "response": error_body},
            ) from e

        except httpx.TimeoutException as e:
            raise SemanticScholarError(
                message="Semantic Scholar API request timed out",
                details={"timeout": self.DEFAULT_TIMEOUT},
            ) from e

        except httpx.RequestError as e:
            raise SemanticScholarError(
                message=f"Semantic Scholar API connection error: {e}",
                details={"error_type": type(e).__name__},
            ) from e

    async def search_bulk(
        self,
        query: str,
        *,
        year: str | None = None,
        venue: str | None = None,
        fields_of_study: list[str] | None = None,
        publication_types: list[str] | None = None,
        open_access_only: bool = False,
        min_citation_count: int | None = None,
        sort_by: S2SortField = "paperId",
        sort_order: Literal["asc", "desc"] = "asc",
        token: str | None = None,
        include_abstract: bool = True,
        include_tldr: bool = False,
        include_authors: bool = True,
        include_venue: bool = True,
        include_citations: bool = True,
    ) -> dict[str, Any]:
        """Bulk search papers with boolean query support (max 10M results).

        This endpoint supports boolean query syntax and pagination via continuation tokens.
        Use for large result sets or when you need precise query control.

        Args:
            query: Boolean query string. Supports:
                - AND: "machine AND learning" or "machine learning" (implicit)
                - OR: "machine | learning"
                - NOT: "-excluded_term"
                - Phrase: '"exact phrase"'
                - Prefix: "neuro*"
                - Grouping: "(a | b) AND c"
                - Fuzzy: "word~2" (edit distance)
            year: Year or range (same as relevance search).
            venue: Comma-separated venue names.
            fields_of_study: List of fields to filter by.
            publication_types: List of publication types.
            open_access_only: Only papers with public PDFs.
            min_citation_count: Minimum citation count.
            sort_by: Sort field (paperId, publicationDate, citationCount).
            sort_order: Sort direction (asc, desc).
            token: Continuation token for pagination (from previous response).
            include_abstract: Include paper abstracts.
            include_tldr: Include TLDR (not recommended for bulk - adds latency).
            include_authors: Include author information.
            include_venue: Include venue information.
            include_citations: Include citation counts.

        Returns:
            Dict with 'total', 'token' (for next page), and 'data' (list of papers).
            When 'token' is None, there are no more results.

        Raises:
            SemanticScholarError: If API returns an error or is unreachable.
        """
        client = await self._get_client()

        # Build fields parameter (no embedding for bulk - not supported)
        fields = self._build_fields(
            include_abstract=include_abstract,
            include_tldr=include_tldr,
            include_authors=include_authors,
            include_venue=include_venue,
            include_citations=include_citations,
            include_embedding=False,  # Not supported in bulk
        )

        # Build query parameters
        params: dict[str, Any] = {
            "query": query,
            "fields": fields,
            "sort": f"{sort_by}:{sort_order}",
        }

        # Add continuation token or filters
        if token:
            params["token"] = token
        else:
            # Filters only work on first request (not with token)
            if year:
                params["year"] = year
            if venue:
                params["venue"] = venue
            if fields_of_study:
                params["fieldsOfStudy"] = ",".join(fields_of_study)
            if publication_types:
                params["publicationTypes"] = ",".join(publication_types)
            if open_access_only:
                params["openAccessPdf"] = ""
            if min_citation_count is not None:
                params["minCitationCount"] = min_citation_count

        try:
            response = await client.get("/paper/search/bulk", params=params)
            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            error_body = e.response.text if e.response else "No response body"
            retry_after = None

            if e.response.status_code == 429:
                retry_after_header = e.response.headers.get("Retry-After")
                if retry_after_header:
                    with contextlib.suppress(ValueError):
                        retry_after = int(retry_after_header)
                raise SemanticScholarError(
                    message="Semantic Scholar rate limit exceeded. Please wait before retrying.",
                    api_status_code=429,
                    retry_after=retry_after,
                    details={"response": error_body},
                ) from e

            raise SemanticScholarError(
                message=f"Semantic Scholar API error: {e.response.status_code} - {error_body}",
                api_status_code=e.response.status_code,
                details={"url": str(e.request.url), "response": error_body},
            ) from e

        except httpx.TimeoutException as e:
            raise SemanticScholarError(
                message="Semantic Scholar API request timed out",
                details={"timeout": self.DEFAULT_TIMEOUT},
            ) from e

        except httpx.RequestError as e:
            raise SemanticScholarError(
                message=f"Semantic Scholar API connection error: {e}",
                details={"error_type": type(e).__name__},
            ) from e

    async def get_paper(
        self,
        paper_id: str,
        *,
        include_abstract: bool = True,
        include_tldr: bool = True,
        include_authors: bool = True,
        include_citations: bool = True,
        include_references: bool = False,
    ) -> dict[str, Any]:
        """Get a single paper by ID.

        Args:
            paper_id: Paper identifier. Supports multiple formats:
                - Semantic Scholar ID: "649def34f8be52c8b66281af98ae884c09aef38b"
                - DOI: "DOI:10.1038/nature12373"
                - arXiv: "ARXIV:2301.00001"
                - PubMed: "PMID:12345678"
                - Corpus ID: "CorpusId:12345678"
            include_abstract: Include paper abstract.
            include_tldr: Include TLDR summary.
            include_authors: Include author details.
            include_citations: Include citation counts.
            include_references: Include reference list.

        Returns:
            Paper metadata dict.

        Raises:
            SemanticScholarError: If paper not found or API error.
        """
        client = await self._get_client()

        fields = self._build_fields(
            include_abstract=include_abstract,
            include_tldr=include_tldr,
            include_authors=include_authors,
            include_venue=True,
            include_citations=include_citations,
            include_references=include_references,
        )

        try:
            response = await client.get(f"/paper/{paper_id}", params={"fields": fields})
            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise SemanticScholarError(
                    message=f"Paper not found: {paper_id}",
                    api_status_code=404,
                    details={"paper_id": paper_id},
                ) from e
            raise SemanticScholarError(
                message=f"Semantic Scholar API error: {e.response.status_code}",
                api_status_code=e.response.status_code,
            ) from e

        except httpx.RequestError as e:
            raise SemanticScholarError(
                message=f"Semantic Scholar API connection error: {e}",
            ) from e


# Singleton instance
_client_instance: SemanticScholarClient | None = None


def get_semantic_scholar_client() -> SemanticScholarClient:
    """Get the singleton Semantic Scholar client instance.

    Returns:
        SemanticScholarClient instance (creates one if not exists).
    """
    global _client_instance
    if _client_instance is None:
        _client_instance = SemanticScholarClient()
    return _client_instance
