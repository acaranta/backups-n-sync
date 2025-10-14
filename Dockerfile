# Multi-stage build for minimal image size
# Stage 1: Get rclone binary
FROM alpine:3.20 AS rclone-downloader
ARG RCLONE_VERSION=v1.68.1
RUN apk add --no-cache curl unzip && \
    curl -O https://downloads.rclone.org/${RCLONE_VERSION}/rclone-${RCLONE_VERSION}-linux-amd64.zip && \
    unzip rclone-${RCLONE_VERSION}-linux-amd64.zip && \
    mv rclone-${RCLONE_VERSION}-linux-amd64/rclone /usr/local/bin/ && \
    chmod +x /usr/local/bin/rclone && \
    rm -rf rclone-*

# Stage 2: Final minimal image
FROM ubuntu:noble
ENV DEBIAN_FRONTEND="noninteractive"

# Install minimal dependencies and clean up in single layer to reduce size
RUN echo "tzdata tzdata/Areas select Europe" | debconf-set-selections && \
  echo "tzdata tzdata/Zones/Europe select Paris" | debconf-set-selections && \
  echo "locales locales/locales_to_be_generated multiselect C.UTF-8 UTF-8" | debconf-set-selections && \
  echo "locales locales/default_environment_locale select C.UTF-8" | debconf-set-selections && \
  apt-get update && \
  apt-get install -y --no-install-recommends \
    ca-certificates \
    tzdata \
    fuse3 \
    python3 \
    python3-pip \
    curl \
    && \
  echo "user_allow_other" >> /etc/fuse.conf && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Install uv for faster Python package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
  rm -rf /tmp/* /var/tmp/*
ENV PATH="/root/.local/bin:${PATH}"

# Copy rclone binary from downloader stage
COPY --from=rclone-downloader /usr/local/bin/rclone /usr/local/bin/rclone

# Create non-root user for running the application
RUN (getent group 1000 || groupadd -r -g 1000 backup) && \
    (getent passwd 1000 || useradd -r -u 1000 -g backup -m -d /home/backup -s /bin/bash backup) && \
    mkdir -p /data /backups /config /tmp && \
    chown -R backup:backup /data /backups /config /tmp

# Copy Python application
COPY --chown=backup:backup pyproject.toml /app/
COPY --chown=backup:backup backups_n_sync.py /usr/local/bin/
COPY --chown=backup:backup health_server.py /usr/local/bin/
COPY --chown=backup:backup entrypoint.py /

RUN chmod +x /usr/local/bin/backups_n_sync.py && \
    chmod +x /usr/local/bin/health_server.py && \
    chmod +x /entrypoint.py

ENV XDG_CONFIG_HOME=/config

# Force Python to run in unbuffered mode for real-time Docker logs
ENV PYTHONUNBUFFERED=1

ENV HOSTID=""
ENV WAKEUPTIME=""
ENV SKIPFIRSTRUN=false
ENV SRC_VOL_BASE="/data"
ENV BKP_BASE_DIR="/backups"
ENV MAXBKP=7
ENV RCL_TARGET=""
ENV RCL_PREFIX="Backups"
ENV RCL_SUFFIX="dockervolumes"
ENV LOG_LEVEL="INFO"
ENV ENABLE_HEALTH_SERVER="true"
ENV HEALTH_PORT="8080"

# Switch to non-root user
USER backup

WORKDIR /data

EXPOSE 8080

# Use specific user and set labels for better image metadata
LABEL maintainer="acaranta" \
      version="2.0" \
      description="Docker container for automated backups with rclone synchronization" \
      org.opencontainers.image.source="https://github.com/acaranta/backups-n-sync"

CMD ["/usr/bin/python3", "-u", "/entrypoint.py"] 