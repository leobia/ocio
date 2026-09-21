FROM pgvector/pgvector:0.8.6-pg17-bookworm

ARG TARGETARCH
ARG PG_TEXTSEARCH_VERSION=1.4.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && curl --fail --location --silent --show-error \
        --output /tmp/pg-textsearch.zip \
        "https://github.com/timescale/pg_textsearch/releases/download/v${PG_TEXTSEARCH_VERSION}/pg-textsearch-v${PG_TEXTSEARCH_VERSION}-pg17-${TARGETARCH}.zip" \
    && unzip -j /tmp/pg-textsearch.zip '*.deb' -d /tmp \
    && apt-get install -y --no-install-recommends /tmp/pg-textsearch-postgresql-17_*.deb \
    && rm -rf /var/lib/apt/lists/* /tmp/pg-textsearch.zip /tmp/pg-textsearch-postgresql-17_*.deb
