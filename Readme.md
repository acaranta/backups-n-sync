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

## Architecture (v2.0)

**Important change from v1.x**: This version uses a copy-based architecture instead of sync-based:

1. **Create**: Backup is created locally in `/backups` (temporary)
2. **Upload**: Backup is uploaded to rclone target using `rclone copy`
3. **Delete local**: Local backup is deleted immediately after successful upload
4. **Remote retention**: Old backups are deleted directly from the rclone target based on `MAXBKP`

**Benefits**: Local storage only needs space for one backup at a time, while the rclone target stores all retained backups.

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

**Final backup path**: `$RCL_TARGET:$RCL_PREFIX/$HOSTID/$RCL_SUFFIX/{volume_name}/`

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
