# Backup & Sync

A Docker container for automated backups with rclone synchronization.

## Features

* **Scheduled backups**: Runs at a specific time every day (`$WAKEUPTIME`)
* **Volume-based backups**: Creates daily tar.gz archives of directories listed in `/config/bns/backup_vols.txt` (one per line)
* **Efficient storage**: Backups are uploaded to rclone target and removed from local storage immediately
* **Remote retention**: Retention policy (`MAXBKP`) is applied directly on the rclone target, not locally
* **Pre-backup scripts**: Optional bash script execution before backups (`/config/bns/backup_pre_script.sh`)
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

| Variable | Default | Description |
|----------|---------|-------------|
| `HOSTID` | hostname | Identifier for this host (used in backup paths) |
| `WAKEUPTIME` | - | Daily backup time in HH:MM format (e.g., "09:20"). If not set, runs once and exits |
| `SKIPFIRSTRUN` | false | Skip first run if current time is past WAKEUPTIME |
| `SRC_VOL_BASE` | /data | Base directory containing volumes to backup |
| `BKP_BASE_DIR` | /backups | Temporary local directory for backups (only used during upload) |
| `MAXBKP` | 7 | Maximum number of backups to retain on rclone target |
| `RCL_TARGET` | - | Rclone remote name (required) |
| `RCL_PREFIX` | Backups | Prefix path on rclone target |
| `RCL_SUFFIX` | dockervolumes | Suffix path on rclone target |

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
      - /srv/backupsconf/rclone/config/rclone:/config/rclone:ro
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

### `/config/bns/backup_pre_script.sh` (optional)

Bash script executed before backups. Useful for database dumps or other pre-backup tasks.

```bash
#!/bin/bash
# Example: dump MySQL database
mysqldump -h db-host -u user -ppassword mydb > /data/mydb/dump.sql
```
