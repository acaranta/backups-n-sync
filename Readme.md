# Backup & Sync

A Docker container for automated backups with rclone synchronization.

## Features

* **Scheduled backups**: Runs at a specific time every day (`$WAKEUPTIME`)
* **Volume-based backups**: Creates daily tar.gz archives of directories listed in `/config/bns/backup_vols.txt` (one per line)
* **Efficient storage**: Backups are uploaded to rclone target and removed from local storage immediately
* **Remote retention**: Retention policy (`MAXBKP`) is applied directly on the rclone target, not locally
* **Global pre/post scripts**: Optional bash scripts executed before and after the entire backup cycle
* **Volume-specific pre/post scripts**: Optional per-volume scripts executed before and after each individual volume backup
* **Flexible configuration**: Uses rclone for any cloud storage backend
* **Health checks & monitoring**: Built-in HTTP endpoints for container orchestration and Prometheus metrics
* **Error handling**: Retry logic with exponential backoff for transient failures
* **Structured logging**: Configurable log levels with contextual information
* **Backup verification & integrity checks**: Each backup is verified with SHA256 checksum, MD5 checksum comparison (remote/local consistency), and archive integrity test (without extraction). Results are logged and surfaced in health state/metrics.

## Architecture (v2.0)

**Important change from v1.x**: This version uses a copy-based architecture instead of sync-based:

1. **Create**: Backup is created locally in `/backups` (temporary)
2. **Upload**: Backup is uploaded to rclone target using `rclone copy`
3. **Delete local**: Local backup is deleted immediately after successful upload
4. **Remote retention**: Old backups are deleted directly from the rclone target based on `MAXBKP`
5. **Verify**: Each backup is verified for integrity (SHA256, MD5 checksum comparison, archive integrity test)

**Benefits**: Local storage only needs space for one backup at a time, while the rclone target stores all retained backups.
## Backup Verification & Integrity Checks

After each backup, the following integrity checks are performed:

* **SHA256 checksum**: Calculated for each backup archive and logged.
* **MD5 checksum verification**: Compares MD5 checksum of the uploaded file on the remote with the local file using `rclone md5sum`. This avoids the read-only filesystem issues that `rclone check` can have.
* **Archive integrity test**: The backup archive is tested using `tar -tzf` to verify it can be read and decompressed without actually extracting data (lightweight, fast, minimal storage overhead).
* **Logging**: All verification results (checksum, MD5 verification, archive integrity, backup size) are logged and included in the backup summary.
* **Health state**: Verification results are surfaced in the health server state and metrics.

If any verification step fails, it is logged as an error, but the backup cycle continues for other volumes.

## Security Features

* **Non-root user**: Container runs as unprivileged user (UID 1000) for better security
* **Pinned versions**: Uses specific dated base images and rclone version for reproducibility
* **Minimal dependencies**: Only installs required packages to reduce attack surface
* **Multi-stage build**: Efficiently builds rclone from official source
* **Graceful shutdown**: Handles SIGTERM/SIGINT signals properly without data corruption

## Configuration

Configure rclone outside of this container and mount its configuration file.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `HOSTID` | Optional | hostname | Identifier for this host (used in backup paths) |
| `WAKEUPTIME` | Optional | - | Daily backup time in HH:MM format (e.g., "09:20"). If not set, runs once and exits |
| `SKIPFIRSTRUN` | Optional | false | Skip first run if current time is past WAKEUPTIME |
| `SRC_VOL_BASE` | Optional | /data | Base directory containing volumes to backup |
| `BKP_BASE_DIR` | Optional | /backups | Temporary local directory for backups (only used during upload) |
| `MAXBKP` | Optional | 7 | Maximum number of backups to retain on rclone target |
| `PRESCRIPT` | Optional | /config/bns/backup_pre_script.sh | Path to global pre-backup script |
| `POSTSCRIPT` | Optional | /config/bns/backup_post_script.sh | Path to global post-backup script |
| `RCL_TARGET` | **Required** | - | Rclone remote name |
| `RCL_PREFIX` | **Required** | - | Prefix path on rclone target |
| `RCL_SUFFIX` | Optional | dockervolumes | Suffix path on rclone target |
| `LOG_LEVEL` | Optional | INFO | Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL) |
| `ENABLE_HEALTH_SERVER` | Optional | true | Enable health check HTTP server |
| `HEALTH_PORT` | Optional | 8080 | Port for health check server |

**Final backup path**: `$RCL_TARGET:$RCL_PREFIX/$HOSTID/$RCL_SUFFIX/{volume_name}/`

## Health Checks & Monitoring

The container exposes HTTP endpoints for health monitoring and metrics collection:

### Endpoints

* **`/health`** - Basic health check (returns 200 if healthy, 503 if unhealthy)
* **`/ready`** - Readiness check for Kubernetes/orchestration (returns 200 when ready)
* **`/metrics`** - Prometheus-compatible metrics endpoint

### Metrics Exposed

* `backup_total_count` - Total number of backup cycles completed
* `backup_failure_count` - Total number of backup failures
* `backup_volumes_success` - Number of volumes successfully backed up in last cycle
* `backup_volumes_failed` - Number of volumes that failed in last cycle
* `backup_last_duration_seconds` - Duration of last backup cycle in seconds
* `backup_last_success_timestamp` - Unix timestamp of last successful backup
* `backup_uptime_seconds` - Service uptime in seconds

### Docker Compose with Health Checks

```yaml
version: '3.8'
services:
  bkpnsync:
    image: acaranta/backup_n_sync:latest
    ports:
      - "8080:8080"  # Health check port
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    # ... rest of configuration
```

## Docker Compose Example

```yaml
version: '3.8'
services:
  bkpnsync:
    image: acaranta/backup_n_sync:latest
    volumes:
      # Configuration files (read-only)
      - /srv/backupsconf/bns:/config/bns/:ro
      # Rclone configuration must not be readonly
      - /srv/backupsconf/rclone/config/rclone:/config/rclone
      # Temporary backup directory (only needs space for 1 backup)
      - /srv/backups:/backups
      # Source data to backup (read-only recommended)
      - /srv/dockervolumes:/data:ro
    environment:
      - SKIPFIRSTRUN=false
      - WAKEUPTIME=09:20
      - HOSTID=my-server
      - SRC_VOL_BASE=/data
      - BKP_BASE_DIR=/backups
      - MAXBKP=7
      - RCL_TARGET=MyCloudStorage
      - RCL_PREFIX=Backups
      - RCL_SUFFIX=dockervolumes
    restart: unless-stopped
```

## Configuration Files

### `/config/bns/backup_vols.txt`

List of volume names to backup (one per line). Lines starting with `#` are ignored.

```
volume1
volume2
# volume3 - commented out
volume4
```

### Global Scripts (optional)

#### `/config/bns/backup_pre_script.sh`

Bash script executed **once before** the entire backup cycle starts. Useful for global setup tasks.

```bash
#!/bin/bash
# Example: global notification
echo "Starting backup cycle" | mail -s "Backup Started" admin@example.com
```

#### `/config/bns/backup_post_script.sh`

Bash script executed **once after** the entire backup cycle completes. Useful for cleanup or notifications.

```bash
#!/bin/bash
# Example: global cleanup or notification
echo "Backup cycle completed" | mail -s "Backup Complete" admin@example.com
```

**Behavior**:
- If global prescript fails, backup continues anyway (logs warning)
- If global postscript fails, error is logged (logs warning)

### Volume-Specific Scripts (optional)

Each volume can have its own pre/post scripts located within the volume's directory:

#### `<volume_path>/.bkpnsync/prescript.sh`

Bash script executed **before backing up** this specific volume. Useful for database dumps or volume-specific preparation.

```bash
#!/bin/bash
# Example: dump PostgreSQL database for this volume
docker exec my-postgres-container pg_dump -U user mydb > /data/myvolume/dump.sql
```

#### `<volume_path>/.bkpnsync/postscript.sh`

Bash script executed **after successfully backing up** this specific volume. Useful for cleanup tasks.

```bash
#!/bin/bash
# Example: remove temporary dump file
rm -f /data/myvolume/dump.sql
```

**Behavior**:
- If volume prescript fails, **that volume's backup is skipped** (other volumes continue)
- If volume postscript fails, error is logged but process continues (logs warning)
- The `.bkpnsync` directory **is included** in the backup archive

**Example structure**:
```
/data/
  ├── volume1/
  │   ├── .bkpnsync/
  │   │   ├── prescript.sh
  │   │   └── postscript.sh
  │   └── ... (volume data)
  └── volume2/
      └── ... (volume data, no scripts)
```
