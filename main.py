from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.routes import filter_routes

app = FastAPI(title="EasyFilters - Smart Flight Filter API")

# The only site allowed to call this API from a browser. Anything else gets no
# CORS headers back and is blocked by the browser. Add an origin here to widen it.
ALLOWED_ORIGINS = ["https://www.easemytrip.com"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # Nothing here reads cookies or an auth header, so credentialed cross-origin
    # requests are refused rather than permitted by default.
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)

app.include_router(filter_routes.router)
