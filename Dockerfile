# Multi-stage build: wheel built with uv, installed into a slim runtime
# image that runs as a non-root user.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /build

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src

# No .git in the build context: uv-dynamic-versioning uses fallback-version.
RUN uv build --wheel --out-dir /dist \
    && uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python /dist/*.whl

FROM python:3.12-slim-bookworm AS runtime

# curl is kept for container-internal health/acceptance checks
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 mcp

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

USER mcp
WORKDIR /home/mcp
EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["mcp-google-sheets", "--transport", "streamable-http"]
