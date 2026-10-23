import json
import secrets

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/reading-list", tags=["Reading list"])


class Paper(BaseModel):
    id: str = Field(
        pattern=r"^https://openalex\.org/W[0-9]+$",
        max_length=100,
    )
    title: str = Field(min_length=1, max_length=2000)
    authors: list[str] = Field(default_factory=list, max_length=100)
    year: int | None = None
    publication_date: str | None = Field(default=None, max_length=30)
    journal: str | None = Field(default=None, max_length=1000)
    field: str | None = Field(default=None, max_length=500)
    open_access: bool = False
    url: str | None = Field(default=None, max_length=4000)


async def browser_identity(request: Request, response: Response) -> str:
    from app.auth import current_user, check_origin

    if request.method not in ("GET", "HEAD"):
        check_origin(request)
    user = await current_user(request)
    response.headers["Cache-Control"] = "no-store"
    return f"user:{user['id']}"


@router.get("")
async def list_papers(request: Request, response: Response):
    reader = await browser_identity(request, response)
    response.headers["Cache-Control"] = "no-store"

    async with request.app.state.pool.connection() as connection:
        cursor = await connection.execute(
            """
            SELECT paper, saved_at
            FROM reading_list
            WHERE browser_id = %s
            ORDER BY saved_at DESC
            LIMIT 200
            """,
            (reader,),
        )
        rows = await cursor.fetchall()

    return {
        "papers": [
            {**paper, "saved_at": saved_at.isoformat()}
            for paper, saved_at in rows
        ]
    }


@router.post("")
async def save_paper(
    paper: Paper,
    request: Request,
    response: Response,
):
    reader = await browser_identity(request, response)

    async with request.app.state.pool.connection() as connection:
        await connection.execute(
            """
            INSERT INTO reading_list (browser_id, paper_id, paper)
            VALUES (%s, %s, %s::jsonb)
            ON CONFLICT (browser_id, paper_id)
            DO UPDATE SET paper = EXCLUDED.paper
            """,
            (reader, paper.id, json.dumps(paper.model_dump())),
        )

    return {"status": "saved", "id": paper.id}


@router.delete("/{work_id}")
async def remove_paper(
    work_id: str,
    request: Request,
    response: Response,
):
    reader = await browser_identity(request, response)

    async with request.app.state.pool.connection() as connection:
        await connection.execute(
            """
            DELETE FROM reading_list
            WHERE browser_id = %s AND paper_id = %s
            """,
            (reader, f"https://openalex.org/{work_id}"),
        )

    return {"status": "removed"}

