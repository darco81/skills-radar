# skill-radar - production Dockerfile
#
# Multi-stage build. Stage 1 installs deps and pre-bakes the embedding model
# so the container starts in <2s (vs 30-60s first-run model download).
# Stage 2 is a slim runtime that boots directly to the HTTP MCP server.

# -----------------------------------------------------------------------------
# Stage 1 - builder
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# uv: faster than pip, deterministic resolutions
RUN pip install --no-cache-dir uv

WORKDIR /build

# Copy only what's needed for `pip install -e .` so the layer caches
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install the package + runtime deps into a clean prefix we can copy to runtime
RUN uv pip install --system --no-cache .

# Pre-bake the default embedding model (~90 MB) so production starts instant
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# -----------------------------------------------------------------------------
# Stage 2 - runtime
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="skill-radar"
LABEL org.opencontainers.image.description="Lazy-loading skill discovery for Claude Code via MCP"
LABEL org.opencontainers.image.source="https://github.com/dar-kow/skill-radar"
LABEL org.opencontainers.image.licenses="MIT"

# Non-root user for security
RUN groupadd -r skillradar && useradd -r -g skillradar -u 1000 -m -d /home/skillradar skillradar

# Copy installed Python packages + binary
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/skill-radar /usr/local/bin/skill-radar

# Copy pre-baked model cache
COPY --from=builder /root/.cache/huggingface /home/skillradar/.cache/huggingface
RUN chown -R skillradar:skillradar /home/skillradar/.cache

# Default config - paths set to bind-mount targets
RUN mkdir -p /home/skillradar/.config/skill-radar /home/skillradar/.local/share/skill-radar && \
    printf 'paths:\n  - /skills\nembedder:\n  backend: sentence-transformers\n  model: all-MiniLM-L6-v2\nstore:\n  backend: chromadb\n  path: /home/skillradar/.local/share/skill-radar/store\ntransport:\n  mode: http\n  http_host: 0.0.0.0\n  http_port: 6580\n  http_path: /mcp\n  stateless_http: true\n  json_response: true\nretrieval:\n  hybrid_weight_semantic: 0.7\n  hybrid_weight_lexical: 0.3\n  default_top_k: 5\ntrust:\n  default_tier: untrusted\n  trusted_paths: []\nsanitization:\n  max_skill_size_kb: 64\n  strip_xml_tags: true\n  strip_live_exec: true\n' \
    > /home/skillradar/.config/skill-radar/config.yaml && \
    mkdir -p /skills && \
    chown -R skillradar:skillradar /home/skillradar /skills

USER skillradar
WORKDIR /home/skillradar

# Disable HF Hub network probes at runtime - we already have the model
ENV TRANSFORMERS_OFFLINE=1
ENV HF_HUB_OFFLINE=1

EXPOSE 6580

# Health: POST a real MCP initialize handshake - GET returns 406 by design,
# so we must speak proper Streamable HTTP to confirm the server is healthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import json,urllib.request,sys; \
        d=json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'hc','version':'0'}}}).encode(); \
        req=urllib.request.Request('http://127.0.0.1:6580/mcp',data=d,headers={'Content-Type':'application/json','Accept':'application/json,text/event-stream'}); \
        r=urllib.request.urlopen(req,timeout=3); \
        sys.exit(0 if r.status==200 else 1)" || exit 1

CMD ["skill-radar", "serve", "--transport", "http", "--host", "0.0.0.0", "--port", "6580"]
