import os

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api", tags=["Papers"])


@router.get("/papers")
async def search_papers(
    q: str = Query(min_length=2, max_length=200),
    mode: str = Query(default="topic", pattern="^(topic|journal|conference)$"),
    source_id: str | None = Query(default=None, pattern=r"^S[0-9]+$"),
    topic_id: str | None = Query(default=None, pattern=r"^T[0-9]+$"),
):
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(400, "Enter at least two characters.")

    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if not key:
        raise HTTPException(503, "Research API key is not configured.")

    params = {"per_page": 10}
    if mode in ("journal", "conference"):
        if not source_id:
            raise HTTPException(400, "Choose a journal or conference from the suggestions.")
        params["filter"] = f"primary_location.source.id:{source_id}"
        params["sort"] = "publication_date:desc"
    elif topic_id:
        params["filter"] = f"topics.id:{topic_id}"
        params["sort"] = "publication_date:desc"
    else:
        params["search"] = query

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.get(
                "https://api.openalex.org/works",
                headers={"Authorization": f"Bearer {key}"},
                params=params,
            )
    except httpx.RequestError:
        raise HTTPException(
            502, "Research provider could not be reached. Try again."
        )

    if response.status_code in (401, 403):
        raise HTTPException(
            503, "Check your OpenAlex API key and email verification."
        )
    if response.status_code == 429:
        raise HTTPException(
            429, "Research provider limit reached. Please try later."
        )
    if response.status_code != 200:
        raise HTTPException(502, "Research provider returned an error.")

    try:
        data = response.json()
        papers = []

        for work in data.get("results", []):
            location = work.get("primary_location") or {}
            source = location.get("source") or {}
            authors = [
                item["author"]["display_name"]
                for item in work.get("authorships", [])
                if (item.get("author") or {}).get("display_name")
            ]
            topic = work.get("primary_topic") or {}

            papers.append({
                "id": work.get("id"),
                "title": work.get("display_name") or "Untitled",
                "authors": authors,
                "year": work.get("publication_year"),
                "publication_date": work.get("publication_date"),
                "journal": source.get("display_name"),
                "field": (topic.get("field") or {}).get("display_name"),
                "open_access": (
                    work.get("open_access") or {}
                ).get("is_oa", False),
                "url": (
                    work.get("doi")
                    or location.get("landing_page_url")
                    or work.get("id")
                ),
            })

        return {
            "query": query,
            "mode": mode,
            "order": "newest" if source_id or topic_id else "relevance",
            "total": (data.get("meta") or {}).get("count", 0),
            "papers": papers,
        }
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(502, "Research provider returned invalid data.")


@router.get("/suggestions")
async def suggestions(
    q: str = Query(min_length=3, max_length=200),
    mode: str = Query(default="topic", pattern="^(topic|journal|conference)$"),
):
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if not key:
        raise HTTPException(503, "Research API key is not configured.")

    endpoint = "sources" if mode in ("journal", "conference") else "topics"
    params = {"search": q.strip(), "per_page": 6}
    if mode in ("journal", "conference"):
        params["filter"] = f"type:{mode}"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"https://api.openalex.org/{endpoint}",
                headers={"Authorization": f"Bearer {key}"},
                params=params,
            )
        if response.status_code == 429:
            raise HTTPException(429, "Suggestion limit reached. Try later.")
        if response.status_code != 200:
            raise HTTPException(502, "Suggestions are temporarily unavailable.")

        data = response.json()
        return {"suggestions": [
            {
                "id": item["id"].rsplit("/", 1)[-1],
                "name": item["display_name"],
                "detail": (
                    item.get("host_organization_name")
                    or (item.get("field") or {}).get("display_name")
                    or ""
                ),
            }
            for item in data.get("results", [])
            if item.get("id") and item.get("display_name")
        ]}
    except httpx.RequestError:
        raise HTTPException(502, "Could not connect for suggestions.")
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(502, "Invalid suggestion response.")

