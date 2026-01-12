"""Academic search API clients.

Provides singleton HTTP clients for academic search APIs:
- OpenAlex: Open scholarly metadata (250M+ works)
- Semantic Scholar: AI-enhanced paper search with TLDR summaries
- arXiv: Preprint repository (physics, math, CS, etc.)
"""

from app.clients.academic.arxiv import ArxivClient, get_arxiv_client
from app.clients.academic.openalex import OpenAlexClient, get_openalex_client
from app.clients.academic.semantic_scholar import (
    SemanticScholarClient,
    get_semantic_scholar_client,
)

__all__ = [
    "ArxivClient",
    "OpenAlexClient",
    "SemanticScholarClient",
    "get_arxiv_client",
    "get_openalex_client",
    "get_semantic_scholar_client",
]
