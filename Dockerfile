# Stage 1: Build Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

# Stage 2: Runtime
FROM ghcr.io/linuxserver/baseimage-alpine:3.20

# set version label
LABEL maintainer="PaperAgent"

# Install python/pip/uv and system dependencies
# git is often needed for installing dependencies from git
RUN apk add --no-cache \
    python3 \
    py3-pip \
    git \
    && pip3 install --break-system-packages uv

# Copy local files
COPY docker/root/ /

# Set workdir
WORKDIR /app

# Copy application code
COPY pyproject.toml uv.lock README.md .env.example ./
COPY src/ ./src/
# Copy built frontend
COPY --from=frontend-builder /web/dist ./frontend/dist

# Install dependencies into a virtual environment
# We use --system for uv in docker usually, but here we can just use .venv or system.
# LinuxServer base suggests not messing with system python too much, 
# but we are in a container.
# Let's verify standard uv usage.
RUN uv sync --frozen

# Expose port
EXPOSE 8000

# Volume for data
VOLUME /config
