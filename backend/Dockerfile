# CarLens backend image (platform step 3, docs/platform/03-backend-container.md).
# Build context = repo root (see .dockerignore): docker compose build backend
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /carlens/backend

# Packages first: this layer is reused until requirements.txt changes.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Build check: fails here if a system library is missing (Q3).
# RapidOCR() also downloads its models (~31 MB) into its package folder now, while the
# build runs as root; the carlens user cannot write there at run time.
RUN python -c "import cv2, onnxruntime; from rapidocr import RapidOCR; RapidOCR()"

# Code and default config + prompts (config.yaml, prompts/ and runs/ are mounted over on the laptop).
COPY backend/ .
COPY config.yaml /carlens/config.yaml
COPY prompts/ /carlens/prompts/

# The image has no git: the commit is passed at build time and saved on every run.
ARG GIT_COMMIT=unknown
ENV CARLENS_GIT_COMMIT=$GIT_COMMIT

# Run as a normal user, not root.
RUN useradd --create-home carlens \
    && mkdir -p /carlens/runs \
    && chown carlens /carlens/runs
USER carlens

EXPOSE 8000
CMD ["sh", "docker-entrypoint.sh"]
