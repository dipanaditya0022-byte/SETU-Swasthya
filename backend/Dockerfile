FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# --no-server-header: deployment-hardening task -- `Server: uvicorn`
# cannot be stripped by application-level ASGI middleware (confirmed
# live: uvicorn's HTTP protocol implementation adds it independently of
# whatever headers the ASGI app returns in its own http.response.start
# message) -- this uvicorn CLI flag is the actual place this is
# controlled. No X-Powered-By flag exists because this stack never sets
# that header in the first place (checked live -- nothing to disable).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --no-server-header"]
