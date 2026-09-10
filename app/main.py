from fastapi import FastAPI

from services.db import create_db_and_tables

# Import models so SQLModel registers the tables
from models import user, circles, contribution, membership, payout

app = FastAPI(
    title="Ajo Savings Circle API",
    description="API for managing savings circles, contributions, and payouts.",
)


@app.on_event("startup")
def on_startup():
    create_db_and_tables()


@app.get("/")
def root():
    return {"message": "Welcome to Ajo Savings Circle API"}