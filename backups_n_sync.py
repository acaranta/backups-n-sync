#!/usr/bin/env python3
"""
Backup and Sync - Main backup logic
Creates tar.gz backups, uploads to rclone, and manages remote retention policy
"""

import os
import sys
import subprocess
import tarfile
from pathlib import Path
from datetime import datetime
import re


def log(message):
    """Print log message with timestamp"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def run_command(cmd, check=True, capture_output=False):
    """Run a shell command and return result"""
    try:
        if capture_output:
            result = subprocess.run(
                cmd,
                shell=True,
                check=check,
                capture_output=True,
                text=True
            )
            return result.stdout.strip()
        else:
            subprocess.run(cmd, shell=True, check=check)
            return None
    except subprocess.CalledProcessError as e:
        log(f"ERROR: Command failed: {cmd}")
        if capture_output and e.stderr:
            log(f"ERROR: {e.stderr}")
        raise


def read_volumes_list(volumes_file):
    """Read list of volumes to backup from config file"""
    if not os.path.exists(volumes_file):
        log(f"ERROR: Volumes file is missing: {volumes_file}")
        sys.exit(1)

    with open(volumes_file, 'r') as f:
        volumes = [
            line.strip()
            for line in f
            if line.strip() and not line.strip().startswith('#')
        ]

    return volumes


def run_prescript(prescript_path):
    """Run pre-backup script if it exists"""
    if os.path.exists(prescript_path):
        log(f"Found prescript ... running it")
        try:
            run_command(f"bash {prescript_path}")
        except Exception as e:
            log(f"WARNING: Prescript failed: {e}")
            log("Continuing with backup anyway...")


def run_postscript(postscript_path):
    """Run post-backup script if it exists"""
    if os.path.exists(postscript_path):
        log(f"Found postscript ... running it")
        try:
            run_command(f"bash {postscript_path}")
        except Exception as e:
            log(f"WARNING: Postscript failed: {e}")


def run_volume_prescript(volume_path, volume_name):
    """Run volume-specific pre-backup script if it exists"""
    prescript_path = os.path.join(volume_path, '.bkpnsync', 'prescript.sh')
    if os.path.exists(prescript_path):
        log(f"Found volume-specific prescript for '{volume_name}' ... running it")
        try:
            run_command(f"bash {prescript_path}")
            return True
        except Exception as e:
            log(f"ERROR: Volume-specific prescript failed for '{volume_name}': {e}")
            log(f"Skipping backup for volume '{volume_name}'")
            return False
    return True


def run_volume_postscript(volume_path, volume_name):
    """Run volume-specific post-backup script if it exists"""
    postscript_path = os.path.join(volume_path, '.bkpnsync', 'postscript.sh')
    if os.path.exists(postscript_path):
        log(f"Found volume-specific postscript for '{volume_name}' ... running it")
        try:
            run_command(f"bash {postscript_path}")
        except Exception as e:
            log(f"WARNING: Volume-specific postscript failed for '{volume_name}': {e}")


def create_backup(source_path, backup_file):
    """Create a tar.gz backup of the source directory"""
    log(f"Creating backup: {backup_file}")

    # Create parent directory if needed
    os.makedirs(os.path.dirname(backup_file), exist_ok=True)

    # Create tar.gz using tar command (faster and preserves permissions better)
    run_command(f"tar czpf {backup_file} {source_path}")

    log(f"Backup created successfully: {backup_file}")


def upload_to_rclone(local_file, remote_path, rclone_target):
    """Upload a file to rclone target"""
    log(f"Uploading to {rclone_target}:{remote_path}")

    # Use rclone copy to upload the file
    run_command(f"rclone -v --progress copy {local_file} {rclone_target}:{remote_path}")

    log(f"Upload completed successfully")


def delete_local_backup(backup_file):
    """Delete local backup file after successful upload"""
    if os.path.exists(backup_file):
        os.remove(backup_file)
        log(f"Deleted local backup: {backup_file}")


def list_remote_backups(rclone_target, remote_dir):
    """List backup files in remote directory"""
    try:
        # Use rclone lsf to list files
        output = run_command(
            f"rclone lsf {rclone_target}:{remote_dir}",
            capture_output=True
        )

        if not output:
            return []

        files = [f.strip() for f in output.split('\n') if f.strip()]
        return files
    except Exception as e:
        log(f"WARNING: Could not list remote backups: {e}")
        return []


def parse_backup_date(filename):
    """Extract date from backup filename (format: name_YYYYMMDD.tar.gz)"""
    match = re.search(r'_(\d{8})\.tar\.gz$', filename)
    if match:
        try:
            date_str = match.group(1)
            return datetime.strptime(date_str, '%Y%m%d')
        except:
            pass
    return None


def apply_retention_policy(rclone_target, remote_dir, max_backups):
    """Apply retention policy to remote backups"""
    log(f"Applying retention policy (keeping {max_backups} backups)")

    files = list_remote_backups(rclone_target, remote_dir)

    if not files:
        log("No remote backups found")
        return

    # Parse dates and sort by date (newest first)
    backups_with_dates = []
    for f in files:
        date = parse_backup_date(f)
        if date:
            backups_with_dates.append((f, date))

    backups_with_dates.sort(key=lambda x: x[1], reverse=True)

    # Keep max_backups newest, delete the rest
    for i, (filename, date) in enumerate(backups_with_dates):
        if i < max_backups:
            log(f"+Keeping '{filename}' ({date.strftime('%Y-%m-%d')})")
        else:
            log(f"-Removing '{filename}' ({date.strftime('%Y-%m-%d')})")
            try:
                run_command(f"rclone delete {rclone_target}:{remote_dir}/{filename}")
            except Exception as e:
                log(f"WARNING: Failed to delete {filename}: {e}")


def main():
    """Main backup logic"""
    # Read environment variables
    volumes_list = os.environ.get('VOLSLIST', '/config/bns/backup_vols.txt')
    prescript = os.environ.get('PRESCRIPT', '/config/bns/backup_pre_script.sh')
    postscript = os.environ.get('POSTSCRIPT', '/config/bns/backup_post_script.sh')
    src_vol_base = os.environ.get('SRC_VOL_BASE', '/data')
    bkp_base_dir = os.environ.get('BKP_BASE_DIR', '/backups')
    hostid = os.environ.get('HOSTID', os.uname().nodename)
    max_backups = int(os.environ.get('MAXBKP', '7'))
    rclone_target = os.environ.get('RCL_TARGET', '')
    rclone_prefix = os.environ.get('RCL_PREFIX', '')
    rclone_suffix = os.environ.get('RCL_SUFFIX', 'dockervolumes')
    sync_only = os.environ.get('SYNCONLY', '')

    log(f"Host ID: {hostid}")
    log(f"Max backups to keep: {max_backups}")
    log(f"Base dir for volumes: {src_vol_base}")

    # Check rclone config
    if not os.path.exists('/config/rclone/rclone.conf'):
        log("ERROR: Rclone config missing in /config/rclone/rclone.conf")
        sys.exit(1)
    else:
        log("Found Rclone config in /config/rclone/rclone.conf")

    # Check rclone target
    if not rclone_target:
        log("ERROR: RCL_TARGET is not set")
        sys.exit(1)

    # Check rclone prefix
    if not rclone_prefix:
        log("ERROR: RCL_PREFIX is not set")
        sys.exit(1)

    # Generate timestamp
    run_timestamp = datetime.now().strftime('%Y%m%d')

    # Run backup unless SYNCONLY is set
    if not sync_only:
        # Run prescript if exists
        run_prescript(prescript)

        # Read volumes list
        volumes = read_volumes_list(volumes_list)

        if not volumes:
            log("WARNING: No volumes to backup")

        # Process each volume
        for volume in volumes:
            log("----------------------------------")

            source_path = os.path.join(src_vol_base, volume)

            if not os.path.isdir(source_path):
                log(f"Volume/dir '{source_path}' does not exist ... Skipping")
                continue

            log(f"Directory '{source_path}' exists")

            # Run volume-specific prescript if it exists
            if not run_volume_prescript(source_path, volume):
                # Prescript failed, skip this volume
                continue

            # Create temporary local backup
            temp_backup_dir = os.path.join(bkp_base_dir, hostid, volume)
            backup_filename = f"{volume}_{run_timestamp}.tar.gz"
            local_backup_path = os.path.join(temp_backup_dir, backup_filename)

            try:
                # Create the backup
                create_backup(source_path, local_backup_path)

                # Upload to rclone
                remote_base_path = f"{rclone_prefix}/{hostid}/{rclone_suffix}/{volume}"
                upload_to_rclone(local_backup_path, remote_base_path, rclone_target)

                # Delete local backup after successful upload
                delete_local_backup(local_backup_path)

                # Apply retention policy on remote
                apply_retention_policy(rclone_target, remote_base_path, max_backups)

                # Run volume-specific postscript if it exists
                run_volume_postscript(source_path, volume)

            except Exception as e:
                log(f"ERROR: Failed to backup {volume}: {e}")
                # Clean up local file if it exists
                if os.path.exists(local_backup_path):
                    delete_local_backup(local_backup_path)
                continue

    log("----------------------------------")
    log("Backup cycle completed")

    # Run postscript if exists
    run_postscript(postscript)


if __name__ == '__main__':
    main()
