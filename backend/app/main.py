from fastapi import FastAPI

app = FastAPI(title="SETU-Swasthya API")


@app.get("/health")
def health():
    return {"status": "ok"}