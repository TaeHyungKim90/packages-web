from app.config import settings
from app.routers import auth, ghes_inventory, package_request, packages, proxy_health
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="packages-web", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(packages.router, prefix="/api")
app.include_router(package_request.router, prefix="/api")
app.include_router(proxy_health.router, prefix="/api")
app.include_router(ghes_inventory.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
