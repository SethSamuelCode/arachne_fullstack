"""arXiv API client.

arXiv is a free, open-access preprint repository for physics, mathematics,
computer science, quantitative biology, quantitative finance, statistics,
electrical engineering and systems science, and economics.

API Documentation: https://info.arxiv.org/help/api/user-manual.html
Rate Limits: No explicit limit, but 3-second delay recommended between requests.
Max Results: 2000 per request, 30000 total per query.
"""

import asyncio
from typing import Any, Literal

import feedparser
import httpx

from app.core.exceptions import ArxivError

# Type aliases for arXiv parameters
ArxivSearchField = Literal[
    "all", "title", "abstract", "author", "category", "comment", "journal_ref"
]
ArxivSortBy = Literal["relevance", "lastUpdatedDate", "submittedDate"]
ArxivSortOrder = Literal["ascending", "descending"]

# arXiv category codes - comprehensive list
ARXIV_CATEGORIES: dict[str, dict[str, str]] = {
    # Computer Science
    "cs.AI": {"name": "Artificial Intelligence", "group": "Computer Science"},
    "cs.AR": {"name": "Hardware Architecture", "group": "Computer Science"},
    "cs.CC": {"name": "Computational Complexity", "group": "Computer Science"},
    "cs.CE": {
        "name": "Computational Engineering, Finance, and Science",
        "group": "Computer Science",
    },
    "cs.CG": {"name": "Computational Geometry", "group": "Computer Science"},
    "cs.CL": {"name": "Computation and Language (NLP)", "group": "Computer Science"},
    "cs.CR": {"name": "Cryptography and Security", "group": "Computer Science"},
    "cs.CV": {"name": "Computer Vision and Pattern Recognition", "group": "Computer Science"},
    "cs.CY": {"name": "Computers and Society", "group": "Computer Science"},
    "cs.DB": {"name": "Databases", "group": "Computer Science"},
    "cs.DC": {"name": "Distributed, Parallel, and Cluster Computing", "group": "Computer Science"},
    "cs.DL": {"name": "Digital Libraries", "group": "Computer Science"},
    "cs.DM": {"name": "Discrete Mathematics", "group": "Computer Science"},
    "cs.DS": {"name": "Data Structures and Algorithms", "group": "Computer Science"},
    "cs.ET": {"name": "Emerging Technologies", "group": "Computer Science"},
    "cs.FL": {"name": "Formal Languages and Automata Theory", "group": "Computer Science"},
    "cs.GL": {"name": "General Literature", "group": "Computer Science"},
    "cs.GR": {"name": "Graphics", "group": "Computer Science"},
    "cs.GT": {"name": "Computer Science and Game Theory", "group": "Computer Science"},
    "cs.HC": {"name": "Human-Computer Interaction", "group": "Computer Science"},
    "cs.IR": {"name": "Information Retrieval", "group": "Computer Science"},
    "cs.IT": {"name": "Information Theory", "group": "Computer Science"},
    "cs.LG": {"name": "Machine Learning", "group": "Computer Science"},
    "cs.LO": {"name": "Logic in Computer Science", "group": "Computer Science"},
    "cs.MA": {"name": "Multiagent Systems", "group": "Computer Science"},
    "cs.MM": {"name": "Multimedia", "group": "Computer Science"},
    "cs.MS": {"name": "Mathematical Software", "group": "Computer Science"},
    "cs.NA": {"name": "Numerical Analysis", "group": "Computer Science"},
    "cs.NE": {"name": "Neural and Evolutionary Computing", "group": "Computer Science"},
    "cs.NI": {"name": "Networking and Internet Architecture", "group": "Computer Science"},
    "cs.OH": {"name": "Other Computer Science", "group": "Computer Science"},
    "cs.OS": {"name": "Operating Systems", "group": "Computer Science"},
    "cs.PF": {"name": "Performance", "group": "Computer Science"},
    "cs.PL": {"name": "Programming Languages", "group": "Computer Science"},
    "cs.RO": {"name": "Robotics", "group": "Computer Science"},
    "cs.SC": {"name": "Symbolic Computation", "group": "Computer Science"},
    "cs.SD": {"name": "Sound", "group": "Computer Science"},
    "cs.SE": {"name": "Software Engineering", "group": "Computer Science"},
    "cs.SI": {"name": "Social and Information Networks", "group": "Computer Science"},
    "cs.SY": {"name": "Systems and Control", "group": "Computer Science"},
    # Statistics
    "stat.AP": {"name": "Applications", "group": "Statistics"},
    "stat.CO": {"name": "Computation", "group": "Statistics"},
    "stat.ME": {"name": "Methodology", "group": "Statistics"},
    "stat.ML": {"name": "Machine Learning", "group": "Statistics"},
    "stat.OT": {"name": "Other Statistics", "group": "Statistics"},
    "stat.TH": {"name": "Statistics Theory", "group": "Statistics"},
    # Mathematics
    "math.AC": {"name": "Commutative Algebra", "group": "Mathematics"},
    "math.AG": {"name": "Algebraic Geometry", "group": "Mathematics"},
    "math.AP": {"name": "Analysis of PDEs", "group": "Mathematics"},
    "math.AT": {"name": "Algebraic Topology", "group": "Mathematics"},
    "math.CA": {"name": "Classical Analysis and ODEs", "group": "Mathematics"},
    "math.CO": {"name": "Combinatorics", "group": "Mathematics"},
    "math.CT": {"name": "Category Theory", "group": "Mathematics"},
    "math.CV": {"name": "Complex Variables", "group": "Mathematics"},
    "math.DG": {"name": "Differential Geometry", "group": "Mathematics"},
    "math.DS": {"name": "Dynamical Systems", "group": "Mathematics"},
    "math.FA": {"name": "Functional Analysis", "group": "Mathematics"},
    "math.GM": {"name": "General Mathematics", "group": "Mathematics"},
    "math.GN": {"name": "General Topology", "group": "Mathematics"},
    "math.GR": {"name": "Group Theory", "group": "Mathematics"},
    "math.GT": {"name": "Geometric Topology", "group": "Mathematics"},
    "math.HO": {"name": "History and Overview", "group": "Mathematics"},
    "math.IT": {"name": "Information Theory", "group": "Mathematics"},
    "math.KT": {"name": "K-Theory and Homology", "group": "Mathematics"},
    "math.LO": {"name": "Logic", "group": "Mathematics"},
    "math.MG": {"name": "Metric Geometry", "group": "Mathematics"},
    "math.MP": {"name": "Mathematical Physics", "group": "Mathematics"},
    "math.NA": {"name": "Numerical Analysis", "group": "Mathematics"},
    "math.NT": {"name": "Number Theory", "group": "Mathematics"},
    "math.OA": {"name": "Operator Algebras", "group": "Mathematics"},
    "math.OC": {"name": "Optimization and Control", "group": "Mathematics"},
    "math.PR": {"name": "Probability", "group": "Mathematics"},
    "math.QA": {"name": "Quantum Algebra", "group": "Mathematics"},
    "math.RA": {"name": "Rings and Algebras", "group": "Mathematics"},
    "math.RT": {"name": "Representation Theory", "group": "Mathematics"},
    "math.SG": {"name": "Symplectic Geometry", "group": "Mathematics"},
    "math.SP": {"name": "Spectral Theory", "group": "Mathematics"},
    "math.ST": {"name": "Statistics Theory", "group": "Mathematics"},
    # Physics
    "astro-ph": {"name": "Astrophysics", "group": "Physics"},
    "astro-ph.CO": {"name": "Cosmology and Nongalactic Astrophysics", "group": "Physics"},
    "astro-ph.EP": {"name": "Earth and Planetary Astrophysics", "group": "Physics"},
    "astro-ph.GA": {"name": "Astrophysics of Galaxies", "group": "Physics"},
    "astro-ph.HE": {"name": "High Energy Astrophysical Phenomena", "group": "Physics"},
    "astro-ph.IM": {"name": "Instrumentation and Methods for Astrophysics", "group": "Physics"},
    "astro-ph.SR": {"name": "Solar and Stellar Astrophysics", "group": "Physics"},
    "cond-mat": {"name": "Condensed Matter", "group": "Physics"},
    "cond-mat.dis-nn": {"name": "Disordered Systems and Neural Networks", "group": "Physics"},
    "cond-mat.mes-hall": {"name": "Mesoscale and Nanoscale Physics", "group": "Physics"},
    "cond-mat.mtrl-sci": {"name": "Materials Science", "group": "Physics"},
    "cond-mat.other": {"name": "Other Condensed Matter", "group": "Physics"},
    "cond-mat.quant-gas": {"name": "Quantum Gases", "group": "Physics"},
    "cond-mat.soft": {"name": "Soft Condensed Matter", "group": "Physics"},
    "cond-mat.stat-mech": {"name": "Statistical Mechanics", "group": "Physics"},
    "cond-mat.str-el": {"name": "Strongly Correlated Electrons", "group": "Physics"},
    "cond-mat.supr-con": {"name": "Superconductivity", "group": "Physics"},
    "gr-qc": {"name": "General Relativity and Quantum Cosmology", "group": "Physics"},
    "hep-ex": {"name": "High Energy Physics - Experiment", "group": "Physics"},
    "hep-lat": {"name": "High Energy Physics - Lattice", "group": "Physics"},
    "hep-ph": {"name": "High Energy Physics - Phenomenology", "group": "Physics"},
    "hep-th": {"name": "High Energy Physics - Theory", "group": "Physics"},
    "math-ph": {"name": "Mathematical Physics", "group": "Physics"},
    "nlin": {"name": "Nonlinear Sciences", "group": "Physics"},
    "nlin.AO": {"name": "Adaptation and Self-Organizing Systems", "group": "Physics"},
    "nlin.CD": {"name": "Chaotic Dynamics", "group": "Physics"},
    "nlin.CG": {"name": "Cellular Automata and Lattice Gases", "group": "Physics"},
    "nlin.PS": {"name": "Pattern Formation and Solitons", "group": "Physics"},
    "nlin.SI": {"name": "Exactly Solvable and Integrable Systems", "group": "Physics"},
    "nucl-ex": {"name": "Nuclear Experiment", "group": "Physics"},
    "nucl-th": {"name": "Nuclear Theory", "group": "Physics"},
    "physics": {"name": "Physics", "group": "Physics"},
    "physics.acc-ph": {"name": "Accelerator Physics", "group": "Physics"},
    "physics.ao-ph": {"name": "Atmospheric and Oceanic Physics", "group": "Physics"},
    "physics.app-ph": {"name": "Applied Physics", "group": "Physics"},
    "physics.atm-clus": {"name": "Atomic and Molecular Clusters", "group": "Physics"},
    "physics.atom-ph": {"name": "Atomic Physics", "group": "Physics"},
    "physics.bio-ph": {"name": "Biological Physics", "group": "Physics"},
    "physics.chem-ph": {"name": "Chemical Physics", "group": "Physics"},
    "physics.class-ph": {"name": "Classical Physics", "group": "Physics"},
    "physics.comp-ph": {"name": "Computational Physics", "group": "Physics"},
    "physics.data-an": {"name": "Data Analysis, Statistics and Probability", "group": "Physics"},
    "physics.ed-ph": {"name": "Physics Education", "group": "Physics"},
    "physics.flu-dyn": {"name": "Fluid Dynamics", "group": "Physics"},
    "physics.gen-ph": {"name": "General Physics", "group": "Physics"},
    "physics.geo-ph": {"name": "Geophysics", "group": "Physics"},
    "physics.hist-ph": {"name": "History and Philosophy of Physics", "group": "Physics"},
    "physics.ins-det": {"name": "Instrumentation and Detectors", "group": "Physics"},
    "physics.med-ph": {"name": "Medical Physics", "group": "Physics"},
    "physics.optics": {"name": "Optics", "group": "Physics"},
    "physics.plasm-ph": {"name": "Plasma Physics", "group": "Physics"},
    "physics.pop-ph": {"name": "Popular Physics", "group": "Physics"},
    "physics.soc-ph": {"name": "Physics and Society", "group": "Physics"},
    "physics.space-ph": {"name": "Space Physics", "group": "Physics"},
    "quant-ph": {"name": "Quantum Physics", "group": "Physics"},
    # Quantitative Biology
    "q-bio.BM": {"name": "Biomolecules", "group": "Quantitative Biology"},
    "q-bio.CB": {"name": "Cell Behavior", "group": "Quantitative Biology"},
    "q-bio.GN": {"name": "Genomics", "group": "Quantitative Biology"},
    "q-bio.MN": {"name": "Molecular Networks", "group": "Quantitative Biology"},
    "q-bio.NC": {"name": "Neurons and Cognition", "group": "Quantitative Biology"},
    "q-bio.OT": {"name": "Other Quantitative Biology", "group": "Quantitative Biology"},
    "q-bio.PE": {"name": "Populations and Evolution", "group": "Quantitative Biology"},
    "q-bio.QM": {"name": "Quantitative Methods", "group": "Quantitative Biology"},
    "q-bio.SC": {"name": "Subcellular Processes", "group": "Quantitative Biology"},
    "q-bio.TO": {"name": "Tissues and Organs", "group": "Quantitative Biology"},
    # Quantitative Finance
    "q-fin.CP": {"name": "Computational Finance", "group": "Quantitative Finance"},
    "q-fin.EC": {"name": "Economics", "group": "Quantitative Finance"},
    "q-fin.GN": {"name": "General Finance", "group": "Quantitative Finance"},
    "q-fin.MF": {"name": "Mathematical Finance", "group": "Quantitative Finance"},
    "q-fin.PM": {"name": "Portfolio Management", "group": "Quantitative Finance"},
    "q-fin.PR": {"name": "Pricing of Securities", "group": "Quantitative Finance"},
    "q-fin.RM": {"name": "Risk Management", "group": "Quantitative Finance"},
    "q-fin.ST": {"name": "Statistical Finance", "group": "Quantitative Finance"},
    "q-fin.TR": {"name": "Trading and Market Microstructure", "group": "Quantitative Finance"},
    # Electrical Engineering and Systems Science
    "eess.AS": {"name": "Audio and Speech Processing", "group": "Electrical Engineering"},
    "eess.IV": {"name": "Image and Video Processing", "group": "Electrical Engineering"},
    "eess.SP": {"name": "Signal Processing", "group": "Electrical Engineering"},
    "eess.SY": {"name": "Systems and Control", "group": "Electrical Engineering"},
    # Economics
    "econ.EM": {"name": "Econometrics", "group": "Economics"},
    "econ.GN": {"name": "General Economics", "group": "Economics"},
    "econ.TH": {"name": "Theoretical Economics", "group": "Economics"},
}


class ArxivClient:
    """Async HTTP client for arXiv API.

    Implements rate limiting with a 3-second delay between requests as recommended.
    Parses Atom XML responses using feedparser.
    """

    BASE_URL = "http://export.arxiv.org/api"
    DEFAULT_TIMEOUT = 60.0  # arXiv can be slow
    DEFAULT_MAX_RESULTS = 20
    MAX_RESULTS_PER_REQUEST = 2000
    MAX_TOTAL_RESULTS = 30000
    RATE_LIMIT_DELAY = 3.0  # Seconds between requests

    def __init__(self) -> None:
        """Initialize the arXiv client."""
        self._client: httpx.AsyncClient | None = None
        self._last_request_time: float = 0

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client (lazy initialization)."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=self.DEFAULT_TIMEOUT,
                headers={
                    "Accept": "application/atom+xml",
                    "User-Agent": "Arachne/1.0",
                },
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _respect_rate_limit(self) -> None:
        """Wait if necessary to respect arXiv's rate limit."""
        import time

        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.RATE_LIMIT_DELAY and self._last_request_time > 0:
            await asyncio.sleep(self.RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.time()

    def _build_query(
        self,
        query: str | None = None,
        *,
        search_field: ArxivSearchField = "all",
        categories: list[str] | None = None,
        submitted_after: str | None = None,
        submitted_before: str | None = None,
    ) -> str:
        """Build arXiv search query string.

        Args:
            query: Search terms.
            search_field: Field to search in.
            categories: List of category codes to filter by.
            submitted_after: Start date (YYYYMMDD or YYYYMMDDHHMM).
            submitted_before: End date (YYYYMMDD or YYYYMMDDHHMM).

        Returns:
            URL-encoded query string.
        """
        parts: list[str] = []

        # Field prefix mapping
        field_map = {
            "all": "all",
            "title": "ti",
            "abstract": "abs",
            "author": "au",
            "category": "cat",
            "comment": "co",
            "journal_ref": "jr",
        }

        # Add main query
        if query:
            prefix = field_map.get(search_field, "all")
            # URL-encode spaces as + for arXiv
            encoded_query = query.replace(" ", "+")
            parts.append(f"{prefix}:{encoded_query}")

        # Add category filter
        if categories:
            cat_queries = [f"cat:{cat}" for cat in categories]
            if len(cat_queries) == 1:
                parts.append(cat_queries[0])
            else:
                parts.append(f"({'+OR+'.join(cat_queries)})")

        # Add date range filter
        if submitted_after or submitted_before:
            start = submitted_after or "190001010000"
            end = submitted_before or "299912312359"
            # Ensure proper format (pad to 12 digits)
            start = start.ljust(12, "0")[:12]
            end = end.ljust(12, "9")[:12]
            parts.append(f"submittedDate:[{start}+TO+{end}]")

        # Combine with AND
        if not parts:
            return ""

        return "+AND+".join(parts)

    def _parse_feed(self, content: str) -> dict[str, Any]:
        """Parse arXiv Atom feed into structured data.

        Args:
            content: Raw XML content from arXiv API.

        Returns:
            Dict with 'total_results', 'start_index', 'items_per_page', and 'entries'.
        """
        feed = feedparser.parse(content)

        # Extract OpenSearch metadata
        total_results = int(getattr(feed.feed, "opensearch_totalresults", 0))
        start_index = int(getattr(feed.feed, "opensearch_startindex", 0))
        items_per_page = int(getattr(feed.feed, "opensearch_itemsperpage", 0))

        entries: list[dict[str, Any]] = []

        for entry in feed.entries:
            # Extract arXiv ID from URL
            arxiv_id = entry.id.split("/abs/")[-1] if "/abs/" in entry.id else entry.id

            # Extract authors
            authors = []
            for author in getattr(entry, "authors", []):
                author_info: dict[str, Any] = {"name": author.name}
                # Check for affiliation (arXiv-specific field)
                if hasattr(author, "arxiv_affiliation"):
                    author_info["affiliation"] = author.arxiv_affiliation
                authors.append(author_info)

            # Extract categories
            categories = [tag.term for tag in getattr(entry, "tags", [])]
            primary_category = getattr(entry, "arxiv_primary_category", {})
            primary_cat = primary_category.get("term", categories[0] if categories else "")

            # Find PDF link
            pdf_url = None
            for link in getattr(entry, "links", []):
                if link.get("type") == "application/pdf":
                    pdf_url = link.get("href")
                    break
            # Fallback: construct PDF URL from ID
            if not pdf_url and arxiv_id:
                pdf_url = f"http://arxiv.org/pdf/{arxiv_id}"

            # Parse dates
            published = entry.get("published", "")
            updated = entry.get("updated", "")

            parsed_entry: dict[str, Any] = {
                "id": arxiv_id,
                "title": entry.title.replace("\n", " ").strip() if entry.title else "",
                "summary": entry.summary.replace("\n", " ").strip() if entry.summary else "",
                "authors": authors,
                "published": published,
                "updated": updated,
                "categories": categories,
                "primary_category": primary_cat,
                "pdf_url": pdf_url,
                "abs_url": f"http://arxiv.org/abs/{arxiv_id}",
            }

            # Optional fields
            if hasattr(entry, "arxiv_doi"):
                parsed_entry["doi"] = entry.arxiv_doi
            if hasattr(entry, "arxiv_journal_ref"):
                parsed_entry["journal_ref"] = entry.arxiv_journal_ref
            if hasattr(entry, "arxiv_comment"):
                parsed_entry["comment"] = entry.arxiv_comment

            entries.append(parsed_entry)

        return {
            "total_results": total_results,
            "start_index": start_index,
            "items_per_page": items_per_page,
            "entries": entries,
        }

    async def search(
        self,
        query: str | None = None,
        *,
        id_list: list[str] | None = None,
        search_field: ArxivSearchField = "all",
        categories: list[str] | None = None,
        submitted_after: str | None = None,
        submitted_before: str | None = None,
        sort_by: ArxivSortBy = "relevance",
        sort_order: ArxivSortOrder = "descending",
        start: int = 0,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> dict[str, Any]:
        """Search arXiv papers.

        Args:
            query: Search query. Supports field prefixes inline (e.g., "ti:quantum AND au:smith").
            id_list: List of specific arXiv IDs to retrieve (e.g., ["2301.00001", "cs/0001001"]).
            search_field: Field to search in (all, title, abstract, author, category).
            categories: Filter by category codes (e.g., ["cs.AI", "cs.LG", "stat.ML"]).
            submitted_after: Filter by submission date start (YYYYMMDD format).
            submitted_before: Filter by submission date end (YYYYMMDD format).
            sort_by: Sort field (relevance, lastUpdatedDate, submittedDate).
            sort_order: Sort direction (ascending, descending).
            start: Starting index for pagination (0-based).
            max_results: Number of results to return (max 2000 per request).

        Returns:
            Dict with 'total_results', 'start_index', 'items_per_page', and 'entries'.

        Raises:
            ArxivError: If API returns an error, request times out, or connection fails.
        """
        client = await self._get_client()

        # Validate inputs
        if not query and not id_list:
            raise ArxivError(
                message="Either query or id_list must be provided",
                details={"query": query, "id_list": id_list},
            )

        # Validate categories
        if categories:
            invalid_cats = [cat for cat in categories if cat not in ARXIV_CATEGORIES]
            if invalid_cats:
                raise ArxivError(
                    message=f"Invalid arXiv categories: {', '.join(invalid_cats)}",
                    details={"invalid_categories": invalid_cats},
                )

        # Clamp max_results
        max_results = max(1, min(max_results, self.MAX_RESULTS_PER_REQUEST))

        # Build query parameters
        params: dict[str, Any] = {
            "start": start,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }

        # Add search query or ID list
        if id_list:
            params["id_list"] = ",".join(id_list)
        if query or categories or submitted_after or submitted_before:
            search_query = self._build_query(
                query,
                search_field=search_field,
                categories=categories,
                submitted_after=submitted_after,
                submitted_before=submitted_before,
            )
            if search_query:
                params["search_query"] = search_query

        # Respect rate limit
        await self._respect_rate_limit()

        try:
            response = await client.get("/query", params=params)
            response.raise_for_status()

            # Parse the Atom feed
            result = self._parse_feed(response.text)
            return result

        except httpx.HTTPStatusError as e:
            error_body = e.response.text if e.response else "No response body"

            # arXiv returns 400 for results > 30000
            if e.response.status_code == 400:
                raise ArxivError(
                    message="arXiv query exceeds maximum result limit (30000). "
                    "Try adding more specific filters or reducing date range.",
                    api_status_code=400,
                    details={"response": error_body},
                ) from e

            raise ArxivError(
                message=f"arXiv API error: {e.response.status_code} - {error_body}",
                api_status_code=e.response.status_code,
                details={"url": str(e.request.url), "response": error_body},
            ) from e

        except httpx.TimeoutException as e:
            raise ArxivError(
                message="arXiv API request timed out. The service may be slow or overloaded.",
                details={"timeout": self.DEFAULT_TIMEOUT},
            ) from e

        except httpx.RequestError as e:
            raise ArxivError(
                message=f"arXiv API connection error: {e}",
                details={"error_type": type(e).__name__},
            ) from e

    async def get_paper(self, arxiv_id: str) -> dict[str, Any]:
        """Get a single paper by arXiv ID.

        Args:
            arxiv_id: arXiv identifier (e.g., "2301.00001", "cs/0001001").

        Returns:
            Paper metadata dict.

        Raises:
            ArxivError: If paper not found or API error.
        """
        result = await self.search(id_list=[arxiv_id], max_results=1)

        if not result["entries"]:
            raise ArxivError(
                message=f"Paper not found: {arxiv_id}",
                details={"arxiv_id": arxiv_id},
            )

        return result["entries"][0]


def get_categories() -> dict[str, dict[str, str]]:
    """Get all arXiv category codes with names and groups.

    Returns:
        Dict mapping category code to {"name": ..., "group": ...}.
    """
    return ARXIV_CATEGORIES.copy()


def get_categories_by_group() -> dict[str, list[dict[str, str]]]:
    """Get arXiv categories organized by group.

    Returns:
        Dict mapping group name to list of {"code": ..., "name": ...}.
    """
    by_group: dict[str, list[dict[str, str]]] = {}
    for code, info in ARXIV_CATEGORIES.items():
        group = info["group"]
        if group not in by_group:
            by_group[group] = []
        by_group[group].append({"code": code, "name": info["name"]})
    return by_group


# Singleton instance
_client_instance: ArxivClient | None = None


def get_arxiv_client() -> ArxivClient:
    """Get the singleton arXiv client instance.

    Returns:
        ArxivClient instance (creates one if not exists).
    """
    global _client_instance
    if _client_instance is None:
        _client_instance = ArxivClient()
    return _client_instance
