FROM rclone/rclone:latest AS rclone-base

# Begin final image
FROM ubuntu:focal
ENV DEBIAN_FRONTEND="noninteractive" 

RUN echo "tzdata tzdata/Areas select Europe" | debconf-set-selections && \
  echo "tzdata tzdata/Zones/Europe select Paris" | debconf-set-selections && \
  echo "locales locales/locales_to_be_generated multiselect C.UTF-8 UTF-8" | debconf-set-selections && \
  echo "locales locales/default_environment_locale select C.UTF-8" | debconf-set-selections && \
  apt update && apt install -y ca-certificates tzdata fuse3 mysql-client && \
  echo "user_allow_other" >> /etc/fuse.conf && \
  apt-get clean && \ 
  rm -rf /var/lib/apt/lists/*

COPY --from=rclone-base /usr/local/bin/rclone /usr/local/bin/rclone
ADD backups_n_sync.sh /usr/local/bin/
ADD entrypoint.sh /

RUN chmod +x /usr/local/bin/backups_n_sync.sh
RUN chmod +x /entrypoint.sh

ENV XDG_CONFIG_HOME=/config

ENV HOSTID=""
ENV WAKEUPTIME=""
ENV SKIPFIRSTRUN=false
ENV SRC_VOL_BASE="/data"
ENV BKP_BASE_DIR="/backups"
ENV MAXBKP=7
ENV RCLONE_TARGET=""
ENV RCLONE_PREFIX="Backups"
ENV RCLONE_SUFFIX="dockervolumes"

WORKDIR /data
CMD /entrypoint.sh 