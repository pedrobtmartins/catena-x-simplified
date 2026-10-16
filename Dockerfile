# syntax=docker/dockerfile:1.7
# catena-x-simplified: backend (FastAPI) serving the built web UI, one image.
#
#   docker build -t catenax-simplified .
#   docker run -p 8000:8000 -e CXS_OWN_BPNL=BPNL000000000T1A catenax-simplified
#
# Behind a TLS-inspecting proxy, pass its CA certificate as a build secret:
#   docker build --secret id=ca,src=/path/to/ca.crt --build-arg HTTPS_PROXY=… .
#
# At runtime, a company's private root CA (for an EDC, DTR or IdP with internal certificates) is
# trusted by mounting it into /etc/catenax-simplified/ca-certificates:
#   docker run -v ./certs:/etc/catenax-simplified/ca-certificates:ro …

ARG PYTHON_VERSION=3.12
ARG NODE_VERSION=22

FROM node:${NODE_VERSION}-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca; fi; \
    npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:${PYTHON_VERSION}-slim AS backend
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca SSL_CERT_FILE=/run/secrets/ca; fi; \
    pip install --no-cache-dir --root-user-action=ignore uv==0.11.32 \
    && uv sync --locked --no-dev --extra postgres --no-install-project
COPY backend/src ./src
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
    uv sync --locked --no-dev --extra postgres --no-editable

FROM python:${PYTHON_VERSION}-slim
LABEL org.opencontainers.image.title="catena-x-simplified" \
      org.opencontainers.image.description="Lightweight Catena-X traceability app (Traceability KIT)" \
      org.opencontainers.image.source="https://github.com/pedrobtmartins/catena-x-simplified" \
      org.opencontainers.image.licenses="Apache-2.0"
RUN useradd --uid 10001 --create-home app && mkdir /data && chown app /data \
    && mkdir -p /etc/catenax-simplified/ca-certificates
WORKDIR /app
COPY --from=backend /app/.venv /app/.venv
COPY --from=web /web/dist /app/web
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    CXS_WEB_DIST_DIR=/app/web \
    CXS_DATABASE_URL=sqlite:////data/catenax-simplified.db \
    CXS_EXTRA_CA_DIR=/etc/catenax-simplified/ca-certificates
USER 10001
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["uvicorn", "catenax_simplified.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
