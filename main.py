from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.routes import filter_routes

app = FastAPI(title="EasyFilters - Smart Flight Filter API")

# Browser access is limited to easemytrip.com and its subdomains. A regex
# rather than a list because CORS matches origins as exact strings: "www.",
# "m.", and each staging host are all distinct origins, and an allowlist would
# need updating every time one appears.
#
# localhost is included so the frontend team can develop against this without
# needing a proxy. Drop that alternative when they no longer need it.
#
# allow_credentials stays False deliberately: nothing here reads a cookie or an
# auth header, and with it True Starlette cannot send a literal "*" for any
# future wildcard. Narrow this regex before ever turning it on.
ALLOWED_ORIGIN_REGEX = (
    r"https://([a-z0-9-]+\.)*easemytrip\.com"
    r"|http://localhost(:\d+)?"
    r"|http://127\.0\.0\.1(:\d+)?"
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(filter_routes.router)
