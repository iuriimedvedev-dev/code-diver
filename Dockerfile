FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    CODE_DIVER_CONFIG=/app/configs/container.yml

WORKDIR /app

RUN apk add --no-cache \
    bash \
    ca-certificates \
    curl \
    git \
    nodejs \
    npm \
    ripgrep \
    tini

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md package.json ./
COPY src ./src
COPY configs ./configs
COPY datasets ./datasets
COPY .pi ./.pi
COPY docker/entrypoint.sh /usr/local/bin/code-diver-entrypoint

RUN chmod +x /usr/local/bin/code-diver-entrypoint \
    && uv sync --frozen --no-dev

VOLUME ["/workspace", "/artifacts"]

ENTRYPOINT ["/sbin/tini", "--", "code-diver-entrypoint"]
CMD ["--help"]
