from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.routes import filter_routes

app = FastAPI(title="EasyFilters - Smart Flight Filter API")

# Open to every origin: the consuming teams call this from localhost, staging
# and production, and the endpoint carries no auth and returns no user data.
#
# allow_credentials stays False deliberately. With it True, Starlette cannot
# send a literal "*" and instead echoes back whatever Origin asked, which also
# permits credentialed cross-origin requests - strictly more permissive than
# this. If an auth header or cookie is ever added to this API, narrow
# allow_origins to a real list before turning credentials on.
ALLOWED_ORIGINS = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(filter_routes.router)
