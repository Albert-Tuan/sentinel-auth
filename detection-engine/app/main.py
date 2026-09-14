from fastapi import FastAPI

app = FastAPI(
    title="Sentinel Auth Detection",
    version="0.1.0",
    description="Scaffold only. Consume event schemas and implement contracts before SOC endpoints.",
)


@app.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "detection-engine"}
