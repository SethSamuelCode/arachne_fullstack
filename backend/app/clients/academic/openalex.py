"""OpenAlex API client.

OpenAlex is a free, open catalog of the world's scholarly works, authors,
institutions, and concepts. It has 250M+ works with rich metadata.

API Documentation: https://docs.openalex.org/
Rate Limits: 100,000 requests/day, 10 requests/second (polite pool with email)
"""

from typing import Any, Literal

import httpx

from app.core.config import settings
from app.core.exceptions import OpenAlexError

# Type aliases for OpenAlex-specific parameters
OpenAlexSearchField = Literal["all", "title", "abstract", "fulltext", "title_and_abstract"]
OpenAlexSortField = Literal["relevance", "cited_by_count", "publication_date", "display_name"]
OpenAlexOAStatus = Literal["gold", "green", "hybrid", "bronze", "closed"]


class OpenAlexClient:
    """Async HTTP client for OpenAlex API.

    Uses httpx.AsyncClient with connection pooling for efficient requests.
    Implements the "polite pool" pattern with email header for higher rate limits.
    """

    BASE_URL = "https://api.openalex.org"
    DEFAULT_TIMEOUT = 30.0
    DEFAULT_PER_PAGE = 25
    MAX_PER_PAGE = 200

    def __init__(self) -> None:
        """Initialize the OpenAlex client."""
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client (lazy initialization)."""
        if self._client is None or self._client.is_closed:
            headers = {
                "Accept": "application/json",
                "User-Agent": "Arachne/1.0",
            }
            # Add email for polite pool if configured
            if settings.OPENALEX_EMAIL:
                headers["User-Agent"] = f"Arachne/1.0 (mailto:{settings.OPENALEX_EMAIL})"

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

    def _build_auth_params(self) -> dict[str, str]:
        """Build authentication parameters for API requests.

        API key takes precedence over email for premium rate limits.
        Falls back to email-based "polite pool" if no API key configured.

        Returns:
            Dict with 'api_key' or 'mailto' param, or empty dict.
        """
        if settings.OPENALEX_API_KEY:
            return {"api_key": settings.OPENALEX_API_KEY}
        if settings.OPENALEX_EMAIL:
            return {"mailto": settings.OPENALEX_EMAIL}
        return {}

    def _build_filter(
        self,
        *,
        search_field: OpenAlexSearchField = "all",
        query: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        min_citations: int | None = None,
        open_access_only: bool = False,
        oa_status: OpenAlexOAStatus | None = None,
        publication_type: str | None = None,
        institution_id: str | None = None,
        author_id: str | None = None,
        concept_id: str | None = None,
        language: str | None = None,
        has_doi: bool | None = None,
        has_abstract: bool | None = None,
    ) -> str:
        """Build OpenAlex filter string from parameters.

        Returns:
            Comma-separated filter string for the API.
        """
        filters: list[str] = []

        # Text search filters
        if query:
            field_map = {
                "all": "default.search",
                "title": "title.search",
                "abstract": "abstract.search",
                "fulltext": "fulltext.search",
                "title_and_abstract": "title_and_abstract.search",
            }
            search_key = field_map.get(search_field, "default.search")
            filters.append(f"{search_key}:{query}")

        # Date filters
        if year_from is not None and year_to is not None and year_from == year_to:
            filters.append(f"publication_year:{year_from}")
        else:
            if year_from is not None:
                filters.append(f"from_publication_date:{year_from}-01-01")
            if year_to is not None:
                filters.append(f"to_publication_date:{year_to}-12-31")

        # Citation filter
        if min_citations is not None:
            filters.append(f"cited_by_count:>={min_citations}")

        # Open access filters
        if open_access_only:
            filters.append("is_oa:true")
        if oa_status is not None:
            filters.append(f"oa_status:{oa_status}")

        # Entity filters
        if publication_type is not None:
            filters.append(f"type:{publication_type}")
        if institution_id is not None:
            filters.append(f"institutions.id:{institution_id}")
        if author_id is not None:
            filters.append(f"author.id:{author_id}")
        if concept_id is not None:
            filters.append(f"concepts.id:{concept_id}")
        if language is not None:
            filters.append(f"language:{language}")

        # Boolean filters
        if has_doi is not None:
            filters.append(f"has_doi:{'true' if has_doi else 'false'}")
        if has_abstract is not None:
            filters.append(f"has_abstract:{'true' if has_abstract else 'false'}")

        return ",".join(filters)

    def _build_select(
        self,
        *,
        include_abstract: bool = True,
        include_authors: bool = True,
        include_citations: bool = True,
        include_concepts: bool = False,
        include_topics: bool = False,
        include_referenced_works: bool = False,
    ) -> str:
        """Build OpenAlex select string for field selection.

        Returns:
            Comma-separated list of fields to return.
        """
        # Always include core fields
        fields = [
            "id",
            "doi",
            "display_name",
            "title",
            "publication_year",
            "publication_date",
            "type",
            "open_access",
            "primary_location",
            "language",
        ]

        if include_abstract:
            fields.append("abstract_inverted_index")
        if include_authors:
            fields.append("authorships")
        if include_citations:
            fields.extend(["cited_by_count", "cited_by_api_url"])
        if include_concepts:
            fields.append("concepts")
        if include_topics:
            fields.extend(["primary_topic", "topics"])
        if include_referenced_works:
            fields.append("referenced_works")

        return ",".join(fields)

    async def search_works(
        self,
        query: str,
        *,
        search_field: OpenAlexSearchField = "all",
        sample: int | None = None,
        seed: int | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        min_citations: int | None = None,
        open_access_only: bool = False,
        oa_status: OpenAlexOAStatus | None = None,
        publication_type: str | None = None,
        institution_id: str | None = None,
        author_id: str | None = None,
        concept_id: str | None = None,
        language: str | None = None,
        sort_by: OpenAlexSortField = "relevance",
        sort_order: Literal["asc", "desc"] = "desc",
        page: int = 1,
        per_page: int = DEFAULT_PER_PAGE,
        include_abstract: bool = True,
        include_authors: bool = True,
        include_citations: bool = True,
    ) -> dict[str, Any]:
        """Search OpenAlex works (scholarly publications).

        Args:
            query: Search query string.
            search_field: Which fields to search (all, title, abstract, fulltext).
            sample: Number of random records to return. Disables pagination.
            seed: Random seed for reproducible sampling (used with 'sample').
            year_from: Minimum publication year (inclusive).
            year_to: Maximum publication year (inclusive).
            min_citations: Minimum citation count.
            open_access_only: Only return open access works.
            oa_status: Specific OA status filter (gold, green, hybrid, bronze, closed).
            publication_type: Work type filter (article, book, dataset, etc.).
            institution_id: Filter by institution OpenAlex ID.
            author_id: Filter by author OpenAlex ID.
            concept_id: Filter by concept OpenAlex ID.
            language: Filter by ISO 639-1 language code.
            sort_by: Sort field (relevance, cited_by_count, publication_date, display_name).
            sort_order: Sort direction (asc, desc).
            page: Page number (1-indexed).
            per_page: Results per page (1-200).
            include_abstract: Include abstract in results.
            include_authors: Include author information.
            include_citations: Include citation count.

        Returns:
            Dict with 'meta' (pagination info) and 'results' (list of works).

        Raises:
            OpenAlexError: If API returns an error or is unreachable.
        """
        client = await self._get_client()

        # Clamp per_page to valid range
        per_page = max(1, min(per_page, self.MAX_PER_PAGE))

        # Build filter string
        filter_str = self._build_filter(
            search_field=search_field,
            query=query,
            year_from=year_from,
            year_to=year_to,
            min_citations=min_citations,
            open_access_only=open_access_only,
            oa_status=oa_status,
            publication_type=publication_type,
            institution_id=institution_id,
            author_id=author_id,
            concept_id=concept_id,
            language=language,
        )

        # Build select string
        select_str = self._build_select(
            include_abstract=include_abstract,
            include_authors=include_authors,
            include_citations=include_citations,
        )

        # Build query parameters
        params: dict[str, Any] = {
            "filter": filter_str,
            "select": select_str,
            "page": page,
            "per-page": per_page,
        }

        # Add random sampling if requested
        if sample is not None:
            params["sample"] = sample
            if seed is not None:
                params["seed"] = seed

        # Add sorting (relevance requires a search filter)
        if sort_by == "relevance" and query:
            params["sort"] = f"relevance_score:{sort_order}"
        elif sort_by != "relevance":
            params["sort"] = f"{sort_by}:{sort_order}"

        # Add authentication (API key or polite pool email)
        params.update(self._build_auth_params())

        try:
            response = await client.get("/works", params=params)
            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            error_body = e.response.text if e.response else "No response body"
            raise OpenAlexError(
                message=f"OpenAlex API error: {e.response.status_code} - {error_body}",
                api_status_code=e.response.status_code,
                details={"url": str(e.request.url), "response": error_body},
            ) from e

        except httpx.TimeoutException as e:
            raise OpenAlexError(
                message="OpenAlex API request timed out",
                details={"timeout": self.DEFAULT_TIMEOUT},
            ) from e

        except httpx.RequestError as e:
            raise OpenAlexError(
                message=f"OpenAlex API connection error: {e}",
                details={"error_type": type(e).__name__},
            ) from e

    async def get_work(self, work_id: str) -> dict[str, Any]:
        """Get a single work by OpenAlex ID or DOI.

        Args:
            work_id: OpenAlex ID (e.g., 'W2125098916') or DOI (e.g., '10.1038/nature12373').

        Returns:
            Work metadata dict.

        Raises:
            OpenAlexError: If work not found or API error.
        """
        client = await self._get_client()

        # Handle DOI format
        if work_id.startswith("10."):
            work_id = f"doi:{work_id}"
        elif not work_id.startswith("W") and not work_id.startswith("https://"):
            work_id = f"W{work_id}"

        # Add authentication (API key or polite pool email)
        params = self._build_auth_params()

        try:
            response = await client.get(f"/works/{work_id}", params=params)
            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise OpenAlexError(
                    message=f"Work not found: {work_id}",
                    api_status_code=404,
                    details={"work_id": work_id},
                ) from e
            raise OpenAlexError(
                message=f"OpenAlex API error: {e.response.status_code}",
                api_status_code=e.response.status_code,
            ) from e

        except httpx.RequestError as e:
            raise OpenAlexError(
                message=f"OpenAlex API connection error: {e}",
            ) from e


# Singleton instance
_client_instance: OpenAlexClient | None = None


def get_openalex_client() -> OpenAlexClient:
    """Get the singleton OpenAlex client instance.

    Returns:
        OpenAlexClient instance (creates one if not exists).
    """
    global _client_instance
    if _client_instance is None:
        _client_instance = OpenAlexClient()
    return _client_instance
