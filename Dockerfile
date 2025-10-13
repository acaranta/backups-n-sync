FROM rclone/rclone:latest AS rclone-base

# Begin final image
FROM ubuntu:noble
ENV DEBIAN_FRONTEND="noninteractive"

RUN echo "tzdata tzdata/Areas select Europe" | debconf-set-selections && \
  echo "tzdata tzdata/Zones/Europe select Paris" | debconf-set-selections && \
  echo "locales locales/locales_to_be_generated multiselect C.UTF-8 UTF-8" | debconf-set-selections && \
  echo "locales locales/default_environment_locale select C.UTF-8" | debconf-set-selections && \
  apt update && apt install -y ca-certificates tzdata fuse3 mysql-client python3 python3-pip curl jq && \
  echo "user_allow_other" >> /etc/fuse.conf && \
  apt clean && \
  rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

COPY --from=rclone-base /usr/local/bin/rclone /usr/local/bin/rclone

# Copy Python application
COPY pyproject.toml /app/
COPY backups_n_sync.py /usr/local/bin/
COPY entrypoint.py /

RUN chmod +x /usr/local/bin/backups_n_sync.py
RUN chmod +x /entrypoint.py

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

WORKDIR /data
CMD ["/usr/bin/python3", "-u", "/entrypoint.py"] 