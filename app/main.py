import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.routes.auth import router as auth_router
from app.routes.bank import router as bank_router
from app.routes.circles import router as circles_router
from app.routes.contributions import router as contributions_router
from app.routes.payouts import router as payouts_router
from app.services.db import create_db_and_tables, seed_demo_users

# Register tables with SQLModel
import app.models  # noqa: F401

tags_metadata = [
    {
        "name": "Authentication",
            },
    {
        "name": "Circles",
            },
    {
        "name": "Contributions",
        },
    {
        "name": "Payouts",
           },
    {
        "name": "Bank",
          },
]

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    seed_demo_users()
    yield


app = FastAPI(
    title="Ajo — The Savings Circle",
    description=(
        "A weekly savings circle: members pay in, one person collects the pot by turn, "
        "and the bank's robot confirms transfers that have actually cleared."
    ),
    openapi_tags=tags_metadata,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


app.include_router(auth_router)
app.include_router(circles_router)
app.include_router(contributions_router)
app.include_router(payouts_router)
app.include_router(bank_router)
