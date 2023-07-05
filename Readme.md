# Backup & Sync

This is a docker container developped for my backup need, not sure this can be useful to many people in the world lol:
The idea is to :
* have a container that starts at a specific time every day `$WAKEUPTIME` (yes like cron, but hell I did it my way)
* create a daily tar.gz of specific directories found in the mounted `/data` and listed in the `/bns/backup_vols.txt` (1 per line)
* theses tar.gz willl be stored in the mounted `/backups` directory under `$HOSTID` subdir (if HOTSID is not set it will use the container hostname, therefore ... specify it lol)
* it will only keep there a maximum of `MAXBKP` files (default is 7)
* finally, using rclone (with a configuration mounted in `/config/rclone/rclone.conf`) it will upload the contents of `/backups/$HOSTID` to `$RCL_TARGET:$RCL_PREFIX/$HOSTID/$RCL_SUFFIX`

Configure rclone out of this container, and mount its configuration.

# Compose example :
```
version: '2.4'
services:
  bkpnsync:
    image: acaranta/backup_n_sync:latest
    volumes:
      - /srv/backupsconf/bns:/config/bns/:ro 
      - /srv/backupsconf/rclone/config/rclone:/config/rclone:ro
      - /srv/backups:/backups
      - /srv/dockervolumes:/data:ro
    environment:
      - SKIPFIRSTRUN=false
      - WAKEUPTIME=09:20
      - HOSTID=testhostID
      - SRC_VOL_BASE=/data
      - BKP_BASE_DIR=/backups
      - MAXBKP=5
      - RCL_TARGET=DropboxService
      - RCL_PREFIX=Backups-test
      - RCL_SUFFIX=dockervolumes
```
