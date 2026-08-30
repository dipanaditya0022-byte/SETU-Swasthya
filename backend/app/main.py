from fastapi import FastAPI

from app.api.routes.patients import router as patients_router

app = FastAPI(title="SETU-Swasthya API")


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(patients_router)

from app.api.routes.triage import router as triage_router

app.include_router(triage_router)

from app.api.routes.referrals import router as referrals_router

app.include_router(referrals_router)

from app.api.routes.sync import router as sync_router

app.include_router(sync_router)

from app.api.routes.auth import router as auth_router

app.include_router(auth_router)

from app.api.routes.users import router as users_router

app.include_router(users_router)

from app.api.routes.governance import router as governance_router

app.include_router(governance_router)
