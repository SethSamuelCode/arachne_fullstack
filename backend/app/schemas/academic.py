"""Academic search response schemas.

Pydantic models for academic search API responses.
Provides type safety and consistent data structures across different APIs.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# OpenAlex Schemas
# =============================================================================


class OpenAlexAuthor(BaseModel):
    """Author information from OpenAlex."""

    id: str | None = Field(default=None, description="OpenAlex author ID")
    display_name: str = Field(description="Author's display name")
    orcid: str | None = Field(default=None, description="ORCID identifier")

    @classmethod
    def from_authorship(cls, authorship: dict[str, Any]) -> "OpenAlexAuthor":
        """Create from OpenAlex authorship object."""
        author = authorship.get("author", {})
        return cls(
            id=author.get("id"),
            display_name=author.get("display_name", "Unknown"),
            orcid=author.get("orcid"),
        )


class OpenAlexOpenAccess(BaseModel):
    """Open access information from OpenAlex."""

    is_oa: bool = Field(default=False, description="Whether work is open access")
    oa_status: str | None = Field(
        default=None, description="OA status: gold, green, hybrid, bronze, closed"
    )
    oa_url: str | None = Field(default=None, description="URL to open access version")


class OpenAlexWork(BaseModel):
    """A scholarly work from OpenAlex."""

    id: str = Field(description="OpenAlex work ID (e.g., W2125098916)")
    doi: str | None = Field(default=None, description="Digital Object Identifier")
    title: str = Field(description="Work title")
    publication_year: int | None = Field(default=None, description="Year of publication")
    publication_date: str | None = Field(default=None, description="Publication date (YYYY-MM-DD)")
    type: str | None = Field(default=None, description="Work type: article, book, dataset, etc.")
    cited_by_count: int = Field(default=0, description="Number of citations")
    is_oa: bool = Field(default=False, description="Whether work is open access")
    oa_status: str | None = Field(default=None, description="OA status")
    pdf_url: str | None = Field(default=None, description="URL to PDF if available")
    abstract: str | None = Field(default=None, description="Work abstract")
    authors: list[OpenAlexAuthor] = Field(default_factory=list, description="List of authors")
    source_name: str | None = Field(default=None, description="Journal or source name")
    language: str | None = Field(default=None, description="Language code (ISO 639-1)")

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "OpenAlexWork":
        """Create from OpenAlex API response."""
        # Decode inverted index abstract if present
        abstract = None
        if data.get("abstract_inverted_index"):
            abstract = cls._decode_inverted_index(data["abstract_inverted_index"])

        # Extract authors from authorships
        authors = []
        for authorship in data.get("authorships", []):
            authors.append(OpenAlexAuthor.from_authorship(authorship))

        # Extract open access info
        open_access = data.get("open_access", {})
        is_oa = open_access.get("is_oa", False) or data.get("is_oa", False)
        oa_status = open_access.get("oa_status")

        # Get PDF URL from primary location or best_oa_location
        pdf_url = None
        primary_location = data.get("primary_location", {})
        if primary_location:
            pdf_url = primary_location.get("pdf_url")
        if not pdf_url:
            best_oa = data.get("best_oa_location", {})
            if best_oa:
                pdf_url = best_oa.get("pdf_url")

        # Get source name
        source_name = None
        if primary_location and primary_location.get("source"):
            source_name = primary_location["source"].get("display_name")

        return cls(
            id=data.get("id", "").split("/")[-1],  # Extract ID from URL
            doi=data.get("doi", "").replace("https://doi.org/", "") if data.get("doi") else None,
            title=data.get("display_name") or data.get("title", ""),
            publication_year=data.get("publication_year"),
            publication_date=data.get("publication_date"),
            type=data.get("type"),
            cited_by_count=data.get("cited_by_count", 0),
            is_oa=is_oa,
            oa_status=oa_status,
            pdf_url=pdf_url,
            abstract=abstract,
            authors=authors,
            source_name=source_name,
            language=data.get("language"),
        )

    @staticmethod
    def _decode_inverted_index(inverted_index: dict[str, list[int]]) -> str:
        """Decode OpenAlex inverted index abstract format.

        OpenAlex stores abstracts as {word: [positions]} for compression.
        This reconstructs the original text.
        """
        if not inverted_index:
            return ""

        # Find max position
        max_pos = 0
        for positions in inverted_index.values():
            if positions:
                max_pos = max(max_pos, max(positions))

        # Build word array
        words: list[str] = [""] * (max_pos + 1)
        for word, positions in inverted_index.items():
            for pos in positions:
                words[pos] = word

        return " ".join(words)


class OpenAlexSearchResult(BaseModel):
    """Search results from OpenAlex API."""

    total_count: int = Field(description="Total number of matching results")
    page: int = Field(description="Current page number")
    per_page: int = Field(description="Results per page")
    results: list[OpenAlexWork] = Field(description="List of works")

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "OpenAlexSearchResult":
        """Create from OpenAlex API response."""
        meta = data.get("meta", {})
        results = [OpenAlexWork.from_api_response(work) for work in data.get("results", [])]

        return cls(
            total_count=meta.get("count", 0),
            page=meta.get("page", 1),
            per_page=meta.get("per_page", 25),
            results=results,
        )


# =============================================================================
# Semantic Scholar Schemas
# =============================================================================


class SemanticScholarAuthor(BaseModel):
    """Author information from Semantic Scholar."""

    model_config = ConfigDict(populate_by_name=True)

    author_id: str | None = Field(
        default=None, alias="authorId", description="Semantic Scholar author ID"
    )
    name: str = Field(description="Author name")


class SemanticScholarTLDR(BaseModel):
    """AI-generated summary (TL;DR) from Semantic Scholar."""

    model: str | None = Field(default=None, description="Model used to generate TLDR")
    text: str = Field(description="TLDR summary text")


class SemanticScholarOpenAccessPdf(BaseModel):
    """Open access PDF information."""

    url: str = Field(description="URL to PDF")
    status: str | None = Field(default=None, description="OA status: GOLD, GREEN, HYBRID, BRONZE")


class SemanticScholarExternalIds(BaseModel):
    """External identifiers for a paper."""

    model_config = ConfigDict(populate_by_name=True)

    doi: str | None = Field(default=None, alias="DOI")
    arxiv_id: str | None = Field(default=None, alias="ArXiv")
    pubmed_id: str | None = Field(default=None, alias="PubMed")
    pubmed_central_id: str | None = Field(default=None, alias="PubMedCentral")
    corpus_id: int | None = Field(default=None, alias="CorpusId")
    mag_id: str | None = Field(default=None, alias="MAG")
    dblp_id: str | None = Field(default=None, alias="DBLP")
    acl_id: str | None = Field(default=None, alias="ACL")


class SemanticScholarPaper(BaseModel):
    """A paper from Semantic Scholar."""

    model_config = ConfigDict(populate_by_name=True)

    paper_id: str = Field(alias="paperId", description="Semantic Scholar paper ID")
    title: str = Field(description="Paper title")
    abstract: str | None = Field(default=None, description="Paper abstract")
    year: int | None = Field(default=None, description="Publication year")
    publication_date: str | None = Field(
        default=None, alias="publicationDate", description="Publication date"
    )
    venue: str | None = Field(default=None, description="Publication venue")
    citation_count: int = Field(default=0, alias="citationCount", description="Number of citations")
    influential_citation_count: int | None = Field(
        default=None,
        alias="influentialCitationCount",
        description="Number of influential citations",
    )
    reference_count: int | None = Field(
        default=None, alias="referenceCount", description="Number of references"
    )
    is_open_access: bool = Field(
        default=False, alias="isOpenAccess", description="Whether paper is open access"
    )
    open_access_pdf: SemanticScholarOpenAccessPdf | None = Field(
        default=None, alias="openAccessPdf", description="Open access PDF info"
    )
    tldr: SemanticScholarTLDR | None = Field(default=None, description="AI-generated summary")
    authors: list[SemanticScholarAuthor] = Field(
        default_factory=list, description="List of authors"
    )
    fields_of_study: list[str] | None = Field(
        default=None, alias="fieldsOfStudy", description="Fields of study"
    )
    s2_fields_of_study: list[dict[str, Any]] | None = Field(
        default=None, alias="s2FieldsOfStudy", description="Detailed S2 fields of study"
    )
    publication_types: list[str] | None = Field(
        default=None, alias="publicationTypes", description="Publication types"
    )
    external_ids: SemanticScholarExternalIds | None = Field(
        default=None, alias="externalIds", description="External identifiers"
    )
    embedding: list[float] | None = Field(default=None, description="SPECTER paper embedding")

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "SemanticScholarPaper":
        """Create from Semantic Scholar API response."""
        # Handle TLDR
        tldr_data = data.get("tldr")
        tldr = SemanticScholarTLDR(**tldr_data) if tldr_data else None

        # Handle open access PDF
        oa_pdf_data = data.get("openAccessPdf")
        oa_pdf = SemanticScholarOpenAccessPdf(**oa_pdf_data) if oa_pdf_data else None

        # Handle authors
        authors = [SemanticScholarAuthor(**a) for a in data.get("authors", [])]

        # Handle external IDs
        ext_ids_data = data.get("externalIds")
        ext_ids = SemanticScholarExternalIds(**ext_ids_data) if ext_ids_data else None

        # Handle embedding (nested in embedding.specter_v2)
        embedding_data = data.get("embedding")
        embedding = None
        if isinstance(embedding_data, dict):
            embedding = embedding_data.get("specter_v2") or embedding_data.get("vector")
        elif isinstance(embedding_data, list):
            embedding = embedding_data

        return cls(
            paperId=data.get("paperId", ""),
            title=data.get("title", ""),
            abstract=data.get("abstract"),
            year=data.get("year"),
            publicationDate=data.get("publicationDate"),
            venue=data.get("venue"),
            citationCount=data.get("citationCount", 0),
            influentialCitationCount=data.get("influentialCitationCount"),
            referenceCount=data.get("referenceCount"),
            isOpenAccess=data.get("isOpenAccess", False),
            openAccessPdf=oa_pdf,
            tldr=tldr,
            authors=authors,
            fieldsOfStudy=data.get("fieldsOfStudy"),
            s2FieldsOfStudy=data.get("s2FieldsOfStudy"),
            publicationTypes=data.get("publicationTypes"),
            externalIds=ext_ids,
            embedding=embedding,
        )


class SemanticScholarSearchResult(BaseModel):
    """Search results from Semantic Scholar relevance search."""

    model_config = ConfigDict(populate_by_name=True)

    total: int = Field(description="Total number of matching results")
    offset: int = Field(description="Current offset")
    next_offset: int | None = Field(
        default=None, alias="next", description="Next offset for pagination"
    )
    data: list[SemanticScholarPaper] = Field(description="List of papers")

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "SemanticScholarSearchResult":
        """Create from Semantic Scholar API response."""
        papers = [SemanticScholarPaper.from_api_response(p) for p in data.get("data", [])]
        return cls(
            total=data.get("total", 0),
            offset=data.get("offset", 0),
            next=data.get("next"),
            data=papers,
        )


class SemanticScholarBulkResult(BaseModel):
    """Search results from Semantic Scholar bulk search."""

    total: int = Field(description="Total number of matching results")
    token: str | None = Field(default=None, description="Continuation token for next page")
    data: list[SemanticScholarPaper] = Field(description="List of papers")

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "SemanticScholarBulkResult":
        """Create from Semantic Scholar API response."""
        papers = [SemanticScholarPaper.from_api_response(p) for p in data.get("data", [])]
        return cls(
            total=data.get("total", 0),
            token=data.get("token"),
            data=papers,
        )


# =============================================================================
# arXiv Schemas
# =============================================================================


class ArxivAuthor(BaseModel):
    """Author information from arXiv."""

    name: str = Field(description="Author name")
    affiliation: str | None = Field(default=None, description="Author affiliation")


class ArxivPaper(BaseModel):
    """A paper from arXiv."""

    id: str = Field(description="arXiv ID (e.g., 2301.00001)")
    title: str = Field(description="Paper title")
    summary: str = Field(description="Paper abstract/summary")
    authors: list[ArxivAuthor] = Field(description="List of authors")
    published: str = Field(description="Original publication date (ISO format)")
    updated: str = Field(description="Last update date (ISO format)")
    categories: list[str] = Field(description="All category codes")
    primary_category: str = Field(description="Primary category code")
    pdf_url: str = Field(description="Direct link to PDF")
    abs_url: str = Field(description="Link to abstract page")
    doi: str | None = Field(default=None, description="DOI if published")
    journal_ref: str | None = Field(default=None, description="Journal reference if published")
    comment: str | None = Field(default=None, description="Author comment (e.g., page count)")

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "ArxivPaper":
        """Create from parsed arXiv feed entry."""
        authors = [ArxivAuthor(**a) for a in data.get("authors", [])]
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            summary=data.get("summary", ""),
            authors=authors,
            published=data.get("published", ""),
            updated=data.get("updated", ""),
            categories=data.get("categories", []),
            primary_category=data.get("primary_category", ""),
            pdf_url=data.get("pdf_url", ""),
            abs_url=data.get("abs_url", ""),
            doi=data.get("doi"),
            journal_ref=data.get("journal_ref"),
            comment=data.get("comment"),
        )


class ArxivSearchResult(BaseModel):
    """Search results from arXiv API."""

    total_results: int = Field(description="Total number of matching results")
    start_index: int = Field(description="Starting index (0-based)")
    items_per_page: int = Field(description="Number of items returned")
    entries: list[ArxivPaper] = Field(description="List of papers")

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "ArxivSearchResult":
        """Create from parsed arXiv feed."""
        papers = [ArxivPaper.from_api_response(e) for e in data.get("entries", [])]
        return cls(
            total_results=data.get("total_results", 0),
            start_index=data.get("start_index", 0),
            items_per_page=data.get("items_per_page", 0),
            entries=papers,
        )


class ArxivCategory(BaseModel):
    """arXiv category information."""

    code: str = Field(description="Category code (e.g., cs.AI)")
    name: str = Field(description="Category full name")
    group: str = Field(description="Category group (e.g., Computer Science)")
