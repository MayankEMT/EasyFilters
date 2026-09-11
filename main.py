from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.routes import filter_routes

app = FastAPI(title="EasyFilters - Smart Flight Filter API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(filter_routes.router)
