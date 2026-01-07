import json
import textwrap

from app.schemas.extract_webpage import FetchUrlResponse
from app.services.python import get_python_executor


async def extract_url(
    url: str,
    extract_text: bool = True,
    max_length: int = 200000,
) -> FetchUrlResponse:


    fetch_code = textwrap.dedent(f'''
    import requests
    from bs4 import BeautifulSoup
    import json

    url = {url!r}
    extract_text = {extract_text}
    max_length = {max_length}

    try:
        response = requests.get(url, timeout=120, headers={{"User-Agent": "Mozilla/5.0 (compatible; ResearchBot/1.0)"}})
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.string if soup.title else ""

        if extract_text:
            # Remove script and style elements
            for element in soup(["script", "style", "nav", "header", "footer"]):
                element.decompose()
            content = soup.get_text(separator="\\n", strip=True)
        else:
            content = response.text

        truncated = len(content) > max_length
        content = content[:max_length]

        result = {{
            "title": title,
            "content": content,
            "content_length": len(content),
            "truncated": truncated
        }}
        print(json.dumps(result))

    except Exception as e:
        print(json.dumps({{"error": str(e)}}))
    ''')
    executor = get_python_executor()

    result = await executor.execute_code(fetch_code, timeout=120)

    try:
        data = json.loads(result["output"])
    except (json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"Failed to parse tool output: {result.get('output', 'No output')} (Error: {e})") from e

    if "error" in data:
        raise RuntimeError(f"Fetch failed: {data['error']}")


    return FetchUrlResponse(
        url=url,
        title=data.get("title", ""),
        content=data.get("content", ""),
        content_length=data.get("content_length", 0),
        truncated=data.get("truncated", False),
    )
