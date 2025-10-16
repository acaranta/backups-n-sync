# Quick Start Example

This directory contains a complete Docker Compose setup to showcase the backup-n-sync container.

## Quick Start

1. **Setup configuration files:**
   ```bash
   chmod +x setup-config.sh
   ./setup-config.sh
   ```

2. **Configure rclone:**
   Edit `config/rclone/rclone.conf` with your cloud storage credentials.

3. **Configure volumes to backup:**
   Edit `config/bns/backup_vols.txt` with your Docker volume names.

4. **Start the backup service:**
   ```bash
   docker-compose up -d
   ```

5. **Optional: Start with monitoring:**
   ```bash
   docker-compose --profile monitoring up -d
   ```

## Key Features Demonstrated

- **Scheduled backups** at 2:00 AM daily
- **Health checks** with Docker Compose healthcheck
- **Monitoring endpoints** exposed on port 8080
- **Volume mounting** for configuration and data
- **Resource limits** for production use
- **Optional monitoring stack** (Prometheus + Grafana)

## Monitoring

- **Health endpoint:** http://localhost:8080/health
- **Metrics endpoint:** http://localhost:8080/metrics  
- **Readiness endpoint:** http://localhost:8080/ready
- **Prometheus:** http://localhost:9090 (with monitoring profile)
- **Grafana:** http://localhost:3000 (admin/admin, with monitoring profile)

## Configuration Files

- `config/bns/backup_vols.txt` - List of volumes to backup
- `config/bns/backup_pre_script.sh` - Global pre-backup script
- `config/bns/backup_post_script.sh` - Global post-backup script
- `config/rclone/rclone.conf` - Rclone cloud storage configuration
- `cache/` - Persistent cache directory for metrics state (survives container restarts)

## Environment Variables

The docker-compose.yml includes examples of all key environment variables:

- `WAKEUPTIME=02:00` - Daily backup time
- `HOSTID=my-docker-host` - Host identifier
- `MAXBKP=7` - Keep 7 backups
- `RCL_TARGET=MyCloudStorage` - Rclone remote name
- `LOG_LEVEL=INFO` - Logging level

## Volume Examples

The compose file shows different ways to mount volumes:

```yaml
# Configuration and cache directories
- ./config/bns:/config/bns:ro
- ./config/rclone:/config/rclone
- ./backups:/backups
- ./cache:/var/cache/bkpnsync  # Persistent metrics state

# All Docker volumes (read-only)
- /var/lib/docker/volumes:/data:ro

# Specific named volumes
- myapp_data:/data/myapp_data:ro
- database_data:/data/database_data:ro
```

## Production Considerations

- Set appropriate resource limits
- Use read-only mounts for source data
- Configure proper rclone credentials
- Set up monitoring and alerting
- Test backup and restore procedures