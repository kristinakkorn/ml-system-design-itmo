FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Docker Desktop/corporate proxies can replace the PyPI TLS certificate with a
# self-signed one. Trust is scoped to the two official package hosts and can be
# overridden at build time. This is acceptable for the local PoC; for production
# install the corporate root CA in the image instead.
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org"

WORKDIR /app

COPY requirements.txt .
RUN PIP_INDEX_URL="${PIP_INDEX_URL}" \
    PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}" \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    python -m pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data
COPY tests ./tests
COPY pyproject.toml .
COPY ui.py ./ui.py

RUN mkdir -p /app/runtime

EXPOSE 8000 8501

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
