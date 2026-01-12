"""Academic search tools for the AI agent.

Provides tools for searching academic literature across multiple platforms:
- OpenAlex: 250M+ scholarly works with rich metadata
- Semantic Scholar: AI-enhanced search with TLDR summaries
- arXiv: Preprints in physics, math, CS, and more

Each tool is optimized for its platform's unique strengths and parameters.
"""

from typing import Any, Literal

from app.clients.academic import (
    get_arxiv_client,
    get_openalex_client,
    get_semantic_scholar_client,
)
from app.clients.academic.arxiv import ARXIV_CATEGORIES, get_categories_by_group
from app.core.exceptions import ArxivError, OpenAlexError, SemanticScholarError
from app.schemas.academic import (
    ArxivSearchResult,
    OpenAlexSearchResult,
    SemanticScholarBulkResult,
    SemanticScholarSearchResult,
)

# Type aliases for tool parameters
OpenAlexSearchField = Literal["all", "title", "abstract", "fulltext", "title_and_abstract"]
OpenAlexSortField = Literal["relevance", "cited_by_count", "publication_date", "display_name"]
OpenAlexOAStatus = Literal["gold", "green", "hybrid", "bronze", "closed"]

SemanticScholarSortField = Literal["paperId", "publicationDate", "citationCount"]

ArxivSearchField = Literal[
    "all", "title", "abstract", "author", "category", "comment", "journal_ref"
]
ArxivSortBy = Literal["relevance", "lastUpdatedDate", "submittedDate"]


async def search_openalex_impl(
    query: str,
    *,
    search_field: OpenAlexSearchField = "all",
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
    per_page: int = 25,
    include_abstract: bool = True,
    include_authors: bool = True,
) -> dict[str, Any]:
    """Search OpenAlex academic database for scholarly works.

    OpenAlex is an open catalog of 250M+ scholarly works, authors, venues, and
    institutions. It provides comprehensive metadata including citations, open
    access status, and institutional affiliations.

    WHEN TO USE:
    - Large-scale academic searches across all disciplines
    - Need citation metrics and open access information
    - Want to filter by institution, author, or concept
    - Need structured metadata (DOIs, ORCIDs, publication dates)
    - Looking for open access versions of papers
    - Searching by specific journal, conference, or publisher

    WHEN NOT TO USE:
    - Need AI-generated paper summaries (use Semantic Scholar instead)
    - Looking for preprints not yet indexed (use arXiv instead)
    - Need paper embeddings for similarity search

    SEARCH FIELD OPTIONS:
    - "all": Search title, abstract, and fulltext (default, broadest)
    - "title": Search only paper titles (precise)
    - "abstract": Search only abstracts
    - "fulltext": Search full paper text (subset of works with fulltext)
    - "title_and_abstract": Search both title and abstract

    OPEN ACCESS STATUS:
    - "gold": Published in an OA journal
    - "green": Free copy in a repository
    - "hybrid": OA in a subscription journal
    - "bronze": Free to read on publisher site
    - "closed": No free version available

    SORTING OPTIONS:
    - "relevance": Best match for search terms (default when searching)
    - "cited_by_count": Most cited papers first
    - "publication_date": Newest or oldest papers
    - "display_name": Alphabetical by title

    ARGS:
        query: Search terms. Natural language queries work well.
        search_field: Which fields to search (default: "all").
        year_from: Minimum publication year (inclusive), e.g., 2020.
        year_to: Maximum publication year (inclusive), e.g., 2024.
        min_citations: Only return papers with at least this many citations.
        open_access_only: If True, only return papers with free full text.
        oa_status: Filter by specific OA status (gold, green, hybrid, bronze, closed).
        publication_type: Filter by type - "article", "book", "dataset",
            "book-chapter", "dissertation", "preprint", etc.
        institution_id: Filter by institution OpenAlex ID (e.g., "I27837315" for MIT).
        author_id: Filter by author OpenAlex ID (e.g., "A5023888391").
        concept_id: Filter by research concept ID (e.g., "C41008148" for AI).
        language: Filter by ISO 639-1 language code (e.g., "en", "zh", "de").
        sort_by: How to sort results (relevance, cited_by_count, publication_date).
        sort_order: "desc" for descending, "asc" for ascending.
        page: Page number (1-indexed). First page = 1.
        per_page: Results per page, 1-200 (default: 25).
        include_abstract: Include paper abstracts in results (default: True).
        include_authors: Include author information (default: True).

    RETURNS:
        Dictionary with:
        - total_count: Total matching papers
        - page: Current page number
        - per_page: Results per page
        - results: List of papers with:
            - id: OpenAlex ID
            - doi: DOI if available
            - title: Paper title
            - publication_year: Year published
            - cited_by_count: Number of citations
            - is_oa: Whether open access
            - oa_status: OA type (gold, green, etc.)
            - pdf_url: Direct PDF link if available
            - abstract: Paper abstract
            - authors: List of author names and IDs
            - source_name: Journal/venue name

    ERRORS:
        - API timeout: OpenAlex may be slow during peak times
        - Invalid filter: Check parameter values match allowed options
        - Rate limit: Very rare, but slow down if you hit it

    EXAMPLES:
        # Basic search
        search_openalex("transformer neural networks")

        # Recent ML papers with high citations
        search_openalex("machine learning", year_from=2022, min_citations=100)

        # Open access papers only
        search_openalex("climate change", open_access_only=True)

        # Papers from a specific institution
        search_openalex("quantum computing", institution_id="I27837315")
    """
    client = get_openalex_client()

    try:
        response = await client.search_works(
            query,
            search_field=search_field,
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
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            per_page=per_page,
            include_abstract=include_abstract,
            include_authors=include_authors,
            include_citations=True,
        )

        result = OpenAlexSearchResult.from_api_response(response)
        return result.model_dump()

    except OpenAlexError as e:
        return {
            "error": True,
            "message": e.message,
            "code": e.code,
            "api_status_code": e.api_status_code,
            "details": e.details,
        }


async def search_semantic_scholar_impl(
    query: str,
    *,
    year: str | None = None,
    venue: str | None = None,
    fields_of_study: list[str] | None = None,
    publication_types: list[str] | None = None,
    open_access_only: bool = False,
    min_citation_count: int | None = None,
    offset: int = 0,
    limit: int = 20,
    include_abstract: bool = True,
    include_tldr: bool = True,
    include_authors: bool = True,
    include_venue: bool = True,
    include_embedding: bool = False,
) -> dict[str, Any]:
    """Search Semantic Scholar for academic papers with AI-enhanced features.

    Semantic Scholar provides AI-powered paper search with unique features like
    TLDR summaries (AI-generated paper summaries), influential citation tracking,
    and paper embeddings for similarity search.

    WHEN TO USE:
    - Need AI-generated paper summaries (TLDR) for quick understanding
    - Want to identify influential citations (not just citation count)
    - Looking for CS/AI papers (excellent coverage)
    - Need paper embeddings for building similarity features
    - Want to filter by specific publication types or venues

    WHEN NOT TO USE:
    - Need boolean query syntax (use search_semantic_scholar_bulk instead)
    - Want more than 1000 results (use bulk search)
    - Need institution/affiliation filtering (use OpenAlex)
    - Looking for very recent preprints (arXiv may be faster)

    YEAR FILTER FORMATS:
    - Single year: "2020"
    - Range: "2016-2020"
    - From year onwards: "2010-" (2010 to present)
    - Up to year: "-2015" (papers before 2015)

    FIELDS OF STUDY (common values):
    - "Computer Science", "Medicine", "Physics", "Biology", "Chemistry"
    - "Mathematics", "Engineering", "Psychology", "Economics"
    - "Materials Science", "Environmental Science", "Business"

    PUBLICATION TYPES:
    - "JournalArticle": Peer-reviewed journal papers
    - "Conference": Conference proceedings
    - "Review": Review articles
    - "Book": Books and book chapters
    - "Dataset": Published datasets
    - "ClinicalTrial": Clinical trial reports

    ARGS:
        query: Plain-text search query. No special syntax supported in relevance search.
        year: Year or range filter. Examples: "2020", "2016-2020", "2010-", "-2015".
        venue: Comma-separated venue names (e.g., "Nature,Science,ICML").
        fields_of_study: List of fields like ["Computer Science", "Medicine"].
        publication_types: List of types like ["JournalArticle", "Conference"].
        open_access_only: If True, only return papers with free PDFs.
        min_citation_count: Minimum number of citations required.
        offset: Starting index (0-based) for pagination.
        limit: Number of results (1-100, default: 20).
        include_abstract: Include full paper abstracts (default: True).
        include_tldr: Include AI-generated TLDR summaries (default: True, RECOMMENDED).
        include_authors: Include author names and IDs (default: True).
        include_venue: Include publication venue info (default: True).
        include_embedding: Include SPECTER v2 paper embeddings (default: False).
            Note: Embeddings are useful for similarity search but increase response size.

    RETURNS:
        Dictionary with:
        - total: Total matching papers (max 1000 accessible)
        - offset: Current offset
        - next_offset: Offset for next page (None if no more results)
        - data: List of papers with:
            - paper_id: Semantic Scholar ID
            - title: Paper title
            - abstract: Full abstract (if requested)
            - year: Publication year
            - citation_count: Total citations
            - influential_citation_count: Highly relevant citations
            - is_open_access: Whether open access
            - open_access_pdf: URL to free PDF if available
            - tldr: AI-generated summary (if requested)
            - authors: List of author names
            - venue: Publication venue
            - fields_of_study: Research areas
            - publication_types: Paper types
            - external_ids: DOI, arXiv ID, PubMed ID, etc.

    ERRORS:
        - Rate limit (429): Wait and retry. Consider adding API key.
        - No results: Try broader search terms or fewer filters.

    EXAMPLES:
        # Basic search with TLDR
        search_semantic_scholar("attention is all you need")

        # Recent ML papers with high citations
        search_semantic_scholar("deep learning", year="2022-", min_citation_count=50)

        # Open access papers in a specific field
        search_semantic_scholar("drug discovery", fields_of_study=["Medicine", "Chemistry"], open_access_only=True)

        # Conference papers only
        search_semantic_scholar("reinforcement learning", publication_types=["Conference"])
    """
    client = get_semantic_scholar_client()

    try:
        response = await client.search_relevance(
            query,
            year=year,
            venue=venue,
            fields_of_study=fields_of_study,
            publication_types=publication_types,
            open_access_only=open_access_only,
            min_citation_count=min_citation_count,
            offset=offset,
            limit=limit,
            include_abstract=include_abstract,
            include_tldr=include_tldr,
            include_authors=include_authors,
            include_venue=include_venue,
            include_citations=True,
            include_embedding=include_embedding,
        )

        result = SemanticScholarSearchResult.from_api_response(response)
        return result.model_dump(by_alias=True)

    except SemanticScholarError as e:
        return {
            "error": True,
            "message": e.message,
            "code": e.code,
            "api_status_code": e.api_status_code,
            "retry_after": e.retry_after,
            "details": e.details,
        }


async def search_semantic_scholar_bulk_impl(
    query: str,
    *,
    year: str | None = None,
    venue: str | None = None,
    fields_of_study: list[str] | None = None,
    publication_types: list[str] | None = None,
    open_access_only: bool = False,
    min_citation_count: int | None = None,
    sort_by: SemanticScholarSortField = "paperId",
    sort_order: Literal["asc", "desc"] = "asc",
    token: str | None = None,
    include_abstract: bool = True,
    include_tldr: bool = False,
) -> dict[str, Any]:
    """Bulk search Semantic Scholar with boolean query support and pagination.

    This endpoint supports boolean query syntax and can access up to 10 million
    results through pagination tokens. Use this for systematic reviews, dataset
    building, or when you need precise query control.

    WHEN TO USE:
    - Need boolean query operators (AND, OR, NOT)
    - Want to retrieve more than 1000 results
    - Building datasets or doing systematic literature reviews
    - Need exact phrase matching or prefix search
    - Want to sort by citation count or publication date

    WHEN NOT TO USE:
    - Simple searches (use regular search_semantic_scholar)
    - Need quick results with TLDR summaries (bulk is slower)
    - Need paper embeddings (not available in bulk)

    BOOLEAN QUERY SYNTAX:
    - AND: "machine AND learning" or "machine learning" (implicit AND)
    - OR: "machine | learning" (either term)
    - NOT: "-excluded_term" (prefix with minus)
    - Phrase: '"exact phrase"' (wrap in double quotes)
    - Prefix: "neuro*" (matches neuroscience, neural, etc.)
    - Grouping: "(neural | deep) AND learning"
    - Fuzzy: "word~2" (edit distance of 2)

    SORTING OPTIONS:
    - "paperId": Default, stable ordering for pagination
    - "publicationDate": Newest or oldest first
    - "citationCount": Most or least cited first

    ARGS:
        query: Boolean query string. Supports AND, OR, NOT, phrases, wildcards.
        year: Year or range filter (same as relevance search).
        venue: Comma-separated venue names.
        fields_of_study: List of fields to filter by.
        publication_types: List of publication types.
        open_access_only: Only papers with free PDFs.
        min_citation_count: Minimum citation count.
        sort_by: Sort field - "paperId", "publicationDate", or "citationCount".
        sort_order: "asc" or "desc" (default: "asc").
        token: Continuation token from previous response for pagination.
            Pass the token from the last response to get the next page.
        include_abstract: Include paper abstracts (default: True).
        include_tldr: Include TLDR summaries (default: False, adds latency).

    RETURNS:
        Dictionary with:
        - total: Total matching papers (up to 10M)
        - token: Continuation token for next page (None if done)
        - data: List of papers (up to 1000 per call)

    PAGINATION:
        1. First call: Don't pass token
        2. Check response for token field
        3. If token is not None, call again with that token
        4. Repeat until token is None

    ERRORS:
        - Rate limit (429): Wait and retry
        - Invalid query: Check boolean syntax

    EXAMPLES:
        # Boolean AND query
        search_semantic_scholar_bulk("transformer AND attention AND nlp")

        # OR query with exclusion
        search_semantic_scholar_bulk('"graph neural network" | GNN -survey')

        # Phrase search
        search_semantic_scholar_bulk('"attention is all you need"')

        # Prefix matching
        search_semantic_scholar_bulk("neuro* AND imaging")

        # Paginated retrieval
        result = search_semantic_scholar_bulk("deep learning")
        while result.get("token"):
            result = search_semantic_scholar_bulk("deep learning", token=result["token"])
    """
    client = get_semantic_scholar_client()

    try:
        response = await client.search_bulk(
            query,
            year=year,
            venue=venue,
            fields_of_study=fields_of_study,
            publication_types=publication_types,
            open_access_only=open_access_only,
            min_citation_count=min_citation_count,
            sort_by=sort_by,
            sort_order=sort_order,
            token=token,
            include_abstract=include_abstract,
            include_tldr=include_tldr,
            include_authors=True,
            include_venue=True,
            include_citations=True,
        )

        result = SemanticScholarBulkResult.from_api_response(response)
        return result.model_dump(by_alias=True)

    except SemanticScholarError as e:
        return {
            "error": True,
            "message": e.message,
            "code": e.code,
            "api_status_code": e.api_status_code,
            "retry_after": e.retry_after,
            "details": e.details,
        }


async def search_arxiv_impl(
    query: str | None = None,
    *,
    id_list: list[str] | None = None,
    search_field: ArxivSearchField = "all",
    categories: list[str] | None = None,
    submitted_after: str | None = None,
    submitted_before: str | None = None,
    sort_by: ArxivSortBy = "relevance",
    sort_order: Literal["ascending", "descending"] = "descending",
    start: int = 0,
    max_results: int = 20,
) -> dict[str, Any]:
    """Search arXiv preprint repository for scientific papers.

    arXiv is a free, open-access repository of preprints in physics, mathematics,
    computer science, quantitative biology, quantitative finance, statistics,
    electrical engineering, and economics. Papers are available immediately upon
    submission, often months before peer-reviewed publication.

    WHEN TO USE:
    - Finding cutting-edge research before peer review
    - Physics, mathematics, CS, statistics, or quantitative papers
    - Need immediate access to full PDFs (always free)
    - Looking for specific arXiv IDs
    - Want to track recent submissions in a field
    - Need papers by exact arXiv category

    WHEN NOT TO USE:
    - Need AI summaries (use Semantic Scholar)
    - Need citation counts (use OpenAlex or Semantic Scholar)
    - Looking for biology, medicine, or social science (limited coverage)
    - Need institution or author affiliation filters

    SEARCH FIELD OPTIONS:
    - "all": Search all fields (default)
    - "title": Paper titles only
    - "abstract": Abstracts only
    - "author": Author names
    - "category": Category codes
    - "comment": Author comments (often contains page count)
    - "journal_ref": Journal references for published papers

    COMMON CATEGORY CODES:
    Computer Science:
      cs.AI (Artificial Intelligence), cs.CL (Computation & Language/NLP),
      cs.CV (Computer Vision), cs.LG (Machine Learning), cs.NE (Neural/Evolutionary),
      cs.RO (Robotics), cs.SE (Software Engineering), cs.CR (Cryptography)

    Statistics:
      stat.ML (Machine Learning), stat.TH (Theory), stat.ME (Methodology)

    Mathematics:
      math.OC (Optimization), math.PR (Probability), math.ST (Statistics)

    Physics:
      quant-ph (Quantum Physics), hep-th (High Energy Theory),
      cond-mat.* (Condensed Matter), astro-ph.* (Astrophysics)

    DATE FORMAT:
    Use YYYYMMDD (e.g., "20230101") or YYYYMMDDHHMM (e.g., "202301010600")
    Dates are in GMT timezone.

    ARGS:
        query: Search terms. Can use inline field prefixes like "ti:quantum AND au:smith".
            Supports AND, OR, ANDNOT operators.
        id_list: List of specific arXiv IDs to retrieve (e.g., ["2301.00001", "cs/0001001"]).
            Use this to fetch known papers directly.
        search_field: Limit search to specific field (default: "all").
        categories: Filter by arXiv category codes (e.g., ["cs.AI", "cs.LG", "stat.ML"]).
            Use list_arxiv_categories tool to see all available codes.
        submitted_after: Only papers submitted after this date (YYYYMMDD format).
        submitted_before: Only papers submitted before this date (YYYYMMDD format).
        sort_by: Sort results by "relevance", "lastUpdatedDate", or "submittedDate".
        sort_order: "ascending" or "descending" (default: descending).
        start: Starting index for pagination (0-based).
        max_results: Number of results (max 2000 per request, default: 20).

    RETURNS:
        Dictionary with:
        - total_results: Total matching papers (max 30000 per query)
        - start_index: Current starting position
        - items_per_page: Number of results returned
        - entries: List of papers with:
            - id: arXiv ID (e.g., "2301.00001")
            - title: Paper title
            - summary: Full abstract
            - authors: List of author names and affiliations
            - published: Original submission date
            - updated: Last update date
            - categories: All category codes
            - primary_category: Main category
            - pdf_url: Direct link to PDF
            - abs_url: Link to abstract page
            - doi: DOI if published in a journal
            - journal_ref: Journal reference if published
            - comment: Author comment (e.g., "15 pages, 3 figures")

    RATE LIMITING:
        arXiv requires a 3-second delay between requests. This is automatically
        handled by the client. Avoid rapid successive calls.

    ERRORS:
        - Query too broad: arXiv limits to 30000 results. Add filters.
        - Invalid category: Use list_arxiv_categories to check valid codes.
        - Timeout: arXiv can be slow. Results will be retried automatically.

    EXAMPLES:
        # Basic search
        search_arxiv("transformer attention mechanism")

        # Search in specific categories
        search_arxiv("reinforcement learning", categories=["cs.LG", "cs.AI", "stat.ML"])

        # Recent papers in a field
        search_arxiv("large language model", submitted_after="20240101", sort_by="submittedDate")

        # Fetch specific papers by ID
        search_arxiv(id_list=["2301.00234", "2312.12456"])

        # Author search
        search_arxiv("", search_field="author", query="Bengio")

        # Papers with inline field prefixes
        search_arxiv("ti:quantum AND au:preskill AND cat:quant-ph")
    """
    client = get_arxiv_client()

    try:
        response = await client.search(
            query,
            id_list=id_list,
            search_field=search_field,
            categories=categories,
            submitted_after=submitted_after,
            submitted_before=submitted_before,
            sort_by=sort_by,
            sort_order=sort_order,
            start=start,
            max_results=max_results,
        )

        result = ArxivSearchResult.from_api_response(response)
        return result.model_dump()

    except ArxivError as e:
        return {
            "error": True,
            "message": e.message,
            "code": e.code,
            "api_status_code": e.api_status_code,
            "details": e.details,
        }


def list_arxiv_categories_impl() -> dict[str, Any]:
    """List all arXiv category codes with their names and groups.

    Use this tool to discover valid arXiv category codes for filtering searches.
    arXiv uses a hierarchical category system organized by research discipline.

    WHEN TO USE:
    - Need to find the correct category code for a research area
    - Want to see all categories in a discipline (e.g., all CS categories)
    - Unsure which category code to use in search_arxiv

    RETURNS:
        Dictionary with:
        - categories: Dict mapping code to {"name": ..., "group": ...}
        - by_group: Dict mapping group name to list of {"code": ..., "name": ...}

    CATEGORY GROUPS:
    - Computer Science (cs.*): 40+ categories including AI, ML, NLP, CV
    - Statistics (stat.*): ML, methodology, theory, applications
    - Mathematics (math.*): 30+ categories including optimization, probability
    - Physics: Multiple archives (physics.*, quant-ph, hep-*, cond-mat.*, etc.)
    - Quantitative Biology (q-bio.*): Genomics, neuroscience, etc.
    - Quantitative Finance (q-fin.*): Pricing, risk management, etc.
    - Electrical Engineering (eess.*): Signal processing, image/video, audio
    - Economics (econ.*): Econometrics, general economics, theory

    EXAMPLES:
        # Get all categories
        categories = list_arxiv_categories()

        # Find ML-related categories
        cs_categories = categories["by_group"]["Computer Science"]
        ml_cats = [c for c in cs_categories if "learning" in c["name"].lower()]

        # Use in search
        search_arxiv("neural network", categories=["cs.LG", "cs.NE", "stat.ML"])
    """
    return {
        "categories": ARXIV_CATEGORIES,
        "by_group": get_categories_by_group(),
    }
