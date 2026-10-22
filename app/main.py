import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from psycopg.conninfo import make_conninfo
from psycopg_pool import AsyncConnectionPool


@asynccontextmanager
async def lifespan(app: FastAPI):
    conninfo = make_conninfo(
        host="db",
        dbname="research",
        user="research",
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=10,
    )

    pool = AsyncConnectionPool(
        conninfo,
        min_size=1,
        max_size=5,
        open=False,
    )
    await pool.open()
    try:
        await pool.wait(timeout=30)
        app.state.pool = pool
        yield
    finally:
        await pool.close()


app = FastAPI(
    title="Research Explorer",
    lifespan=lifespan,
)


@app.get("/api/health")
async def health():
    try:
        async with app.state.pool.connection() as connection:
            await connection.execute("SELECT 1")
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        )

    return {"status": "ok", "database": "connected"}


from app.papers import router as papers_router
app.include_router(papers_router)


from pathlib import Path
from fastapi.responses import FileResponse

DASHBOARD_FILE = Path(__file__).parent / "static" / "index.html"


@app.get("/", include_in_schema=False)
@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    return FileResponse(DASHBOARD_FILE)


from app.reading import router as reading_router
app.include_router(reading_router)


from app.auth import router as auth_router
app.include_router(auth_router)
