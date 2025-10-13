#!/usr/bin/env python3
"""
Backup and Sync - Main backup logic
Creates tar.gz backups, uploads to rclone, and manages remote retention policy
"""

import os
import sys
import logging
import subprocess
from datetime import datetime
import re
import time


# Custom exception classes for better error categorization
class BackupError(Exception):
    """Base exception for backup operations"""
    pass


class RcloneError(BackupError):
    """Exception for rclone-related errors"""
    pass


class BackupCreationError(BackupError):
    """Exception for backup creation errors"""
    pass


class RetentionPolicyError(BackupError):
    """Exception for retention policy errors"""
    pass


class ScriptExecutionError(BackupError):
    """Exception for pre/post script execution errors"""
    pass


# Configure logging for Docker-friendly output
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stdout,
    force=True
)
# Ensure immediate flushing
logging.root.handlers[0].setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
logging.root.handlers[0].flush = lambda: sys.stdout.flush()

logger = logging.getLogger(__name__)


def log(message):
    """Print log message with timestamp"""
    logger.info(message)
    sys.stdout.flush()


def run_command(cmd, check=True, capture_output=False, retries=0, retry_delay=1):
    """Run a shell command with retry support
    
    Args:
        cmd: Command to execute
        check: Raise exception on error
        capture_output: Capture and return output
        retries: Number of retry attempts (0 = no retries)
        retry_delay: Base delay between retries in seconds (exponential backoff)
    
    Returns:
        Command output if capture_output=True, None otherwise
    """
    last_error = None
    
    for attempt in range(retries + 1):
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
                # Stream output in real-time to stdout/stderr
                subprocess.run(
                    cmd,
                    shell=True,
                    check=check,
                    stdout=sys.stdout,
                    stderr=sys.stderr
                )
                sys.stdout.flush()
                sys.stderr.flush()
                return None
        except subprocess.CalledProcessError as e:
            last_error = e
            if attempt < retries:
                # Calculate exponential backoff delay
                delay = retry_delay * (2 ** attempt)
                log(f"WARNING: Command failed (attempt {attempt + 1}/{retries + 1}): {cmd}")
                if capture_output and e.stderr:
                    log(f"WARNING: {e.stderr}")
                log(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                log(f"ERROR: Command failed after {retries + 1} attempts: {cmd}")
                if capture_output and e.stderr:
                    log(f"ERROR: {e.stderr}")
                raise
    
    # Should not reach here, but just in case
    if last_error and check:
        raise last_error


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
        log("Found prescript ... running it")
        try:
            run_command(f"bash {prescript_path}")
        except subprocess.CalledProcessError as e:
            log(f"WARNING: Prescript failed with exit code {e.returncode}")
            log("Continuing with backup anyway...")
        except Exception as e:
            log(f"WARNING: Prescript failed: {e}")
            log("Continuing with backup anyway...")


def run_postscript(postscript_path):
    """Run post-backup script if it exists"""
    if os.path.exists(postscript_path):
        log("Found postscript ... running it")
        try:
            run_command(f"bash {postscript_path}")
        except subprocess.CalledProcessError as e:
            log(f"WARNING: Postscript failed with exit code {e.returncode}")
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
        except subprocess.CalledProcessError as e:
            log(f"ERROR: Volume-specific prescript failed for '{volume_name}' with exit code {e.returncode}")
            log(f"Skipping backup for volume '{volume_name}'")
            return False
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
        except subprocess.CalledProcessError as e:
            log(f"WARNING: Volume-specific postscript failed for '{volume_name}' with exit code {e.returncode}")
        except Exception as e:
            log(f"WARNING: Volume-specific postscript failed for '{volume_name}': {e}")


def create_backup(source_path, backup_file):
    """Create a tar.gz backup of the source directory
    
    Raises:
        BackupCreationError: If backup creation fails
    """
    log(f"Creating backup: {backup_file}")

    try:
        # Create parent directory if needed
        os.makedirs(os.path.dirname(backup_file), exist_ok=True)

        # Create tar.gz using tar command (faster and preserves permissions better)
        run_command(f"tar czpf {backup_file} {source_path}")

        log(f"Backup created successfully: {backup_file}")
    except subprocess.CalledProcessError as e:
        raise BackupCreationError(f"Failed to create backup of {source_path}: {e}")
    except Exception as e:
        raise BackupCreationError(f"Unexpected error creating backup of {source_path}: {e}")


def upload_to_rclone(local_file, remote_path, rclone_target, max_retries=3):
    """Upload a file to rclone target with retry support
    
    Args:
        local_file: Path to local file to upload
        remote_path: Remote destination path
        rclone_target: Rclone remote name
        max_retries: Maximum number of retry attempts
    
    Raises:
        RcloneError: If upload fails after all retries
    """
    log(f"Uploading to {rclone_target}:{remote_path}")

    try:
        # Use rclone copy with retry support for transient network issues
        run_command(
            f"rclone copy {local_file} {rclone_target}:{remote_path}",
            retries=max_retries,
            retry_delay=2
        )
        log("Upload completed successfully")
    except subprocess.CalledProcessError as e:
        raise RcloneError(f"Failed to upload {local_file} to {rclone_target}:{remote_path} after {max_retries + 1} attempts: {e}")
    except Exception as e:
        raise RcloneError(f"Unexpected error uploading {local_file}: {e}")


def delete_local_backup(backup_file):
    """Delete local backup file after successful upload"""
    if os.path.exists(backup_file):
        os.remove(backup_file)
        log(f"Deleted local backup: {backup_file}")


def list_remote_backups(rclone_target, remote_dir, max_retries=2):
    """List backup files in remote directory with retry support
    
    Args:
        rclone_target: Rclone remote name
        remote_dir: Remote directory path
        max_retries: Maximum number of retry attempts
    
    Returns:
        List of backup filenames
    """
    try:
        # Use rclone lsf to list files with retry support
        output = run_command(
            f"rclone lsf {rclone_target}:{remote_dir}",
            capture_output=True,
            retries=max_retries,
            retry_delay=1
        )

        if not output:
            return []

        files = [f.strip() for f in output.split('\n') if f.strip()]
        return files
    except subprocess.CalledProcessError as e:
        log(f"WARNING: Could not list remote backups in {remote_dir}: {e}")
        return []
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
        except Exception:
            pass
    return None


def apply_retention_policy(rclone_target, remote_dir, max_backups):
    """Apply retention policy to remote backups
    
    Args:
        rclone_target: Rclone remote name
        remote_dir: Remote directory path
        max_backups: Maximum number of backups to keep
    
    Raises:
        RetentionPolicyError: If retention policy application fails critically
    """
    log(f"Applying retention policy (keeping {max_backups} backups)")

    try:
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
        deletion_errors = []
        for i, (filename, date) in enumerate(backups_with_dates):
            if i < max_backups:
                log(f"+Keeping '{filename}' ({date.strftime('%Y-%m-%d')})")
            else:
                log(f"-Removing '{filename}' ({date.strftime('%Y-%m-%d')})")
                try:
                    run_command(
                        f"rclone delete {rclone_target}:{remote_dir}/{filename}",
                        retries=2,
                        retry_delay=1
                    )
                except subprocess.CalledProcessError as e:
                    error_msg = f"Failed to delete {filename} after retries: {e}"
                    log(f"WARNING: {error_msg}")
                    deletion_errors.append(error_msg)
                except Exception as e:
                    error_msg = f"Failed to delete {filename}: {e}"
                    log(f"WARNING: {error_msg}")
                    deletion_errors.append(error_msg)
        
        if deletion_errors:
            log(f"WARNING: {len(deletion_errors)} file(s) failed to delete during retention policy")
            
    except Exception as e:
        # Don't fail the entire backup if retention policy has issues
        log(f"WARNING: Error applying retention policy: {e}")


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

            except BackupCreationError as e:
                log(f"ERROR: Failed to create backup for {volume}: {e}")
                # Clean up local file if it exists
                if os.path.exists(local_backup_path):
                    delete_local_backup(local_backup_path)
                continue
            except RcloneError as e:
                log(f"ERROR: Failed to upload backup for {volume}: {e}")
                # Clean up local file if it exists
                if os.path.exists(local_backup_path):
                    delete_local_backup(local_backup_path)
                continue
            except Exception as e:
                log(f"ERROR: Unexpected error backing up {volume}: {e}")
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
