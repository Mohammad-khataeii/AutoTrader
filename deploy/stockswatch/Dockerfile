# Build from the verified deployed StocksWatch image, supplied by digest or ID.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG RELEASE_COMMIT=unbound
LABEL org.opencontainers.image.revision=${RELEASE_COMMIT}
USER root
COPY deploy/stockswatch/requirements.txt /tmp/stockswatch-requirements.txt
RUN python -m venv --system-site-packages /opt/stockswatch/venv \
    && /opt/stockswatch/venv/bin/pip install --no-cache-dir -r /tmp/stockswatch-requirements.txt \
    && rm /tmp/stockswatch-requirements.txt
COPY --chown=10001:10001 stockswatch/*.py stockswatch/research_evidence.json /opt/stockswatch/stockswatch/
WORKDIR /opt/stockswatch
USER paper
CMD ["/opt/stockswatch/venv/bin/python", "-m", "stockswatch"]
