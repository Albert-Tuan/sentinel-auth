from fastapi import FastAPI

app = FastAPI(
    title="Sentinel Auth Core",
    version="0.1.0",
    description="Scaffold only. Implement endpoints from docs/api-contract.yml.",
)


@app.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "core-app"}
