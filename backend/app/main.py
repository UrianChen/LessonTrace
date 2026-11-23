from fastapi import FastAPI

from .api import admin, auth, lessons, reports, review

app = FastAPI(title="LessonTrace", docs_url="/api/docs", openapi_url="/api/openapi.json")

for module in (auth, lessons, review, reports, admin):
    app.include_router(module.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"ok": True}
