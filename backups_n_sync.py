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

import hashlib
import tempfile
import shutil

# Import health server utilities
try:
    from health_server import update_state
    HEALTH_SERVER_AVAILABLE = True
except ImportError:
    HEALTH_SERVER_AVAILABLE = False
    def update_state(*args, **kwargs):
        pass


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
log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stdout,
    force=True
)
# Ensure immediate flushing
logging.root.handlers[0].setFormatter(
    logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
)
logging.root.handlers[0].flush = lambda: sys.stdout.flush()

logger = logging.getLogger(__name__)


def log(message, level='info', **context):
    """Log message with specified level and optional context
    
    Args:
        message: Log message
        level: Log level (debug, info, warning, error, critical)
        **context: Additional context to include in message (e.g., volume='vol1')
    """
    # Add context to message if provided
    if context:
        context_str = ' '.join(f'{k}={v}' for k, v in context.items())
        message = f"{message} [{context_str}]"
    
    log_func = getattr(logger, level.lower(), logger.info)
    log_func(message)
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
                log(f"Command failed (attempt {attempt + 1}/{retries + 1}): {cmd}", 'warning', 
                    retry_delay=f"{delay}s")
                if capture_output and e.stderr:
                    log(f"{e.stderr}", 'warning')
                log(f"Retrying in {delay} seconds...", 'warning')
                time.sleep(delay)
            else:
                log(f"Command failed after {retries + 1} attempts: {cmd}", 'error')
                if capture_output and e.stderr:
                    log(f"{e.stderr}", 'error')
                raise
    
    # Should not reach here, but just in case
    if last_error and check:
        raise last_error


def read_volumes_list(volumes_file):
    """Read list of volumes to backup from config file"""
    if not os.path.exists(volumes_file):
        log(f"Volumes file is missing: {volumes_file}", 'error', file=volumes_file)
        sys.exit(1)

    with open(volumes_file, 'r') as f:
        volumes = [
            line.strip()
            for line in f
            if line.strip() and not line.strip().startswith('#')
        ]

    log(f"Loaded {len(volumes)} volume(s) from configuration", 'debug', file=volumes_file)
    return volumes


def run_prescript(prescript_path):
    """Run pre-backup script if it exists"""
    if os.path.exists(prescript_path):
        log("Found prescript ... running it", 'info', script=prescript_path)
        try:
            run_command(f"bash {prescript_path}")
        except subprocess.CalledProcessError as e:
            log(f"Prescript failed with exit code {e.returncode}", 'warning', 
                script=prescript_path, exit_code=e.returncode)
            log("Continuing with backup anyway...", 'warning')
        except Exception as e:
            log(f"Prescript failed: {e}", 'warning', script=prescript_path)
            log("Continuing with backup anyway...", 'warning')


def run_postscript(postscript_path):
    """Run post-backup script if it exists"""
    if os.path.exists(postscript_path):
        log("Found postscript ... running it", 'info', script=postscript_path)
        try:
            run_command(f"bash {postscript_path}")
        except subprocess.CalledProcessError as e:
            log(f"Postscript failed with exit code {e.returncode}", 'warning',
                script=postscript_path, exit_code=e.returncode)
        except Exception as e:
            log(f"Postscript failed: {e}", 'warning', script=postscript_path)


def run_volume_prescript(volume_path, volume_name):
    """Run volume-specific pre-backup script if it exists"""
    prescript_path = os.path.join(volume_path, '.bkpnsync', 'prescript.sh')
    if os.path.exists(prescript_path):
        log("Found volume-specific prescript ... running it", 'info', 
            volume=volume_name, script=prescript_path)
        try:
            run_command(f"bash {prescript_path}")
            return True
        except subprocess.CalledProcessError as e:
            log(f"Volume-specific prescript failed with exit code {e.returncode}", 'error',
                volume=volume_name, exit_code=e.returncode)
            log("Skipping backup for volume", 'error', volume=volume_name)
            return False
        except Exception as e:
            log(f"Volume-specific prescript failed: {e}", 'error', volume=volume_name)
            log("Skipping backup for volume", 'error', volume=volume_name)
            return False
    return True


def run_volume_postscript(volume_path, volume_name):
    """Run volume-specific post-backup script if it exists"""
    postscript_path = os.path.join(volume_path, '.bkpnsync', 'postscript.sh')
    if os.path.exists(postscript_path):
        log("Found volume-specific postscript ... running it", 'info',
            volume=volume_name, script=postscript_path)
        try:
            run_command(f"bash {postscript_path}")
        except subprocess.CalledProcessError as e:
            log(f"Volume-specific postscript failed with exit code {e.returncode}", 'warning',
                volume=volume_name, exit_code=e.returncode)
        except Exception as e:
            log(f"Volume-specific postscript failed: {e}", 'warning', volume=volume_name)


def create_backup(source_path, backup_file):
    """Create a tar.gz backup of the source directory
    
    Raises:
        BackupCreationError: If backup creation fails
    """
    log("Creating backup", 'info', source=source_path, destination=backup_file)

    try:
        # Create parent directory if needed
        os.makedirs(os.path.dirname(backup_file), exist_ok=True)

        # Create tar.gz using tar command (faster and preserves permissions better)
        run_command(f"tar czpf {backup_file} {source_path}")

        # Get file size for logging
        size_bytes = os.path.getsize(backup_file)
        size_mb = size_bytes / (1024 * 1024)
        log("Backup created successfully", 'info', 
            file=backup_file, size_mb=f"{size_mb:.2f}")
        return size_bytes
    except subprocess.CalledProcessError as e:
        raise BackupCreationError(f"Failed to create backup of {source_path}: {e}")
    except Exception as e:
        raise BackupCreationError(f"Unexpected error creating backup of {source_path}: {e}")


def calculate_sha256(file_path):
    """Calculate SHA256 checksum of a file"""
    sha256 = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception as e:
        log(f"Failed to calculate SHA256: {e}", 'warning', file=file_path)
        return None

def verify_rclone(local_file, remote_path, rclone_target, max_retries=2):
    """Run rclone check to verify remote and local backup consistency"""
    try:
        # rclone check expects directories, so use parent dir and filter
        local_dir = os.path.dirname(local_file)
        remote_dir = f"{rclone_target}:{remote_path}"
        run_command(
            f"rclone check {local_dir} {remote_dir} --one-way --match '.*{os.path.basename(local_file)}'",
            retries=max_retries,
            retry_delay=2
        )
        log("rclone check passed", 'info', file=local_file, remote=remote_dir)
        return True
    except subprocess.CalledProcessError as e:
        log(f"rclone check failed: {e}", 'error', file=local_file, remote=remote_dir)
        return False
    except Exception as e:
        log(f"Unexpected error in rclone check: {e}", 'error', file=local_file, remote=remote_dir)
        return False

def test_restore(backup_file):
    """Test-restore: extract backup to temp dir and verify success"""
    temp_dir = tempfile.mkdtemp(prefix="bkpnsync_restore_")
    try:
        run_command(f"tar xzpf {backup_file} -C {temp_dir}")
        log("Test-restore succeeded", 'info', file=backup_file, restore_dir=temp_dir)
        shutil.rmtree(temp_dir)
        return True
    except Exception as e:
        log(f"Test-restore failed: {e}", 'error', file=backup_file, restore_dir=temp_dir)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False


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
    log("Uploading to remote", 'info', 
        target=f"{rclone_target}:{remote_path}", file=local_file)

    try:
        # Use rclone copy with retry support for transient network issues
        run_command(
            f"rclone copy {local_file} {rclone_target}:{remote_path}",
            retries=max_retries,
            retry_delay=2
        )
        log("Upload completed successfully", 'info', target=f"{rclone_target}:{remote_path}")
    except subprocess.CalledProcessError as e:
        raise RcloneError(f"Failed to upload {local_file} to {rclone_target}:{remote_path} after {max_retries + 1} attempts: {e}")
    except Exception as e:
        raise RcloneError(f"Unexpected error uploading {local_file}: {e}")


def delete_local_backup(backup_file):
    """Delete local backup file after successful upload"""
    if os.path.exists(backup_file):
        os.remove(backup_file)
        log("Deleted local backup", 'debug', file=backup_file)


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
        log(f"Could not list remote backups: {e}", 'warning', directory=remote_dir)
        return []
    except Exception as e:
        log(f"Could not list remote backups: {e}", 'warning', directory=remote_dir)
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
    log("Applying retention policy", 'info', max_backups=max_backups, directory=remote_dir)

    try:
        files = list_remote_backups(rclone_target, remote_dir)

        if not files:
            log("No remote backups found", 'info', directory=remote_dir)
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
                log("Keeping backup", 'info', file=filename, date=date.strftime('%Y-%m-%d'))
            else:
                log("Removing old backup", 'info', file=filename, date=date.strftime('%Y-%m-%d'))
                try:
                    run_command(
                        f"rclone delete {rclone_target}:{remote_dir}/{filename}",
                        retries=2,
                        retry_delay=1
                    )
                except subprocess.CalledProcessError as e:
                    error_msg = f"Failed to delete {filename} after retries: {e}"
                    log(error_msg, 'warning', file=filename)
                    deletion_errors.append(error_msg)
                except Exception as e:
                    error_msg = f"Failed to delete {filename}: {e}"
                    log(error_msg, 'warning', file=filename)
                    deletion_errors.append(error_msg)
        
        if deletion_errors:
            log(f"{len(deletion_errors)} file(s) failed to delete during retention policy", 'warning')
            
    except Exception as e:
        # Don't fail the entire backup if retention policy has issues
        log(f"Error applying retention policy: {e}", 'warning', directory=remote_dir)


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

    log(f"Host ID: {hostid}", 'info', hostid=hostid)
    log(f"Max backups to keep: {max_backups}", 'info', max_backups=max_backups)
    log(f"Base dir for volumes: {src_vol_base}", 'info', base_dir=src_vol_base)
    
    # Track volumes for metrics
    volumes_success = 0
    volumes_failed = 0
    failed_volumes = []  # Track which volumes failed and why
    successful_volumes = []  # Track successful backups

    # Check rclone config
    if not os.path.exists('/config/rclone/rclone.conf'):
        log("Rclone config missing in /config/rclone/rclone.conf", 'error', 
            file='/config/rclone/rclone.conf')
        sys.exit(1)
    else:
        log("Found Rclone config in /config/rclone/rclone.conf", 'debug')

    # Check rclone target
    if not rclone_target:
        log("RCL_TARGET is not set", 'error')
        sys.exit(1)

    # Check rclone prefix
    if not rclone_prefix:
        log("RCL_PREFIX is not set", 'error')
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
            log("No volumes to backup", 'warning')

        # Process each volume
        for volume in volumes:
            log("----------------------------------", 'info')
            
            # Update current operation
            update_state(current_operation=f"backing_up_{volume}")

            source_path = os.path.join(src_vol_base, volume)

            if not os.path.isdir(source_path):
                log("Volume/dir does not exist ... Skipping", 'warning', 
                    path=source_path, volume=volume)
                volumes_failed += 1
                failed_volumes.append({
                    'volume': volume,
                    'error': 'Directory does not exist',
                    'path': source_path
                })
                continue

            log("Directory exists", 'debug', path=source_path, volume=volume)

            # Run volume-specific prescript if it exists
            if not run_volume_prescript(source_path, volume):
                # Prescript failed, skip this volume
                volumes_failed += 1
                failed_volumes.append({
                    'volume': volume,
                    'error': 'Volume prescript failed',
                    'path': source_path
                })
                continue

            # Create temporary local backup
            temp_backup_dir = os.path.join(bkp_base_dir, hostid, volume)
            backup_filename = f"{volume}_{run_timestamp}.tar.gz"
            local_backup_path = os.path.join(temp_backup_dir, backup_filename)


            try:
                # Create the backup
                size_bytes = create_backup(source_path, local_backup_path)

                # Calculate SHA256
                sha256sum = calculate_sha256(local_backup_path)
                log("SHA256 checksum", 'info', file=local_backup_path, sha256=sha256sum)

                # Upload to rclone
                remote_base_path = f"{rclone_prefix}/{hostid}/{rclone_suffix}/{volume}"
                upload_to_rclone(local_backup_path, remote_base_path, rclone_target)

                # rclone check (verify upload)
                rclone_verified = verify_rclone(local_backup_path, remote_base_path, rclone_target)

                # Optional: test-restore
                restore_ok = test_restore(local_backup_path)

                # Log verification results
                log("Backup verification results", 'info',
                    file=local_backup_path,
                    sha256=sha256sum,
                    rclone_check=rclone_verified,
                    test_restore=restore_ok,
                    size_bytes=size_bytes)

                # Delete local backup after successful upload and verification
                delete_local_backup(local_backup_path)

                # Apply retention policy on remote
                apply_retention_policy(rclone_target, remote_base_path, max_backups)

                # Run volume-specific postscript if it exists
                run_volume_postscript(source_path, volume)

                # Track success
                volumes_success += 1
                successful_volumes.append({
                    'volume': volume,
                    'backup_file': backup_filename,
                    'remote_path': remote_base_path,
                    'sha256': sha256sum,
                    'rclone_check': rclone_verified,
                    'test_restore': restore_ok,
                    'size_bytes': size_bytes
                })

            except BackupCreationError as e:
                error_msg = str(e)
                log(f"Failed to create backup: {e}", 'error', volume=volume)
                volumes_failed += 1
                failed_volumes.append({
                    'volume': volume,
                    'error': f'Backup creation failed: {error_msg}',
                    'path': source_path
                })
                # Clean up local file if it exists
                if os.path.exists(local_backup_path):
                    delete_local_backup(local_backup_path)
                continue
            except RcloneError as e:
                error_msg = str(e)
                log(f"Failed to upload backup: {e}", 'error', volume=volume)
                volumes_failed += 1
                failed_volumes.append({
                    'volume': volume,
                    'error': f'Upload failed: {error_msg}',
                    'path': source_path
                })
                # Clean up local file if it exists
                if os.path.exists(local_backup_path):
                    delete_local_backup(local_backup_path)
                continue
            except Exception as e:
                error_msg = str(e)
                log(f"Unexpected error backing up volume: {e}", 'error', volume=volume)
                volumes_failed += 1
                failed_volumes.append({
                    'volume': volume,
                    'error': f'Unexpected error: {error_msg}',
                    'path': source_path
                })
                # Clean up local file if it exists
                if os.path.exists(local_backup_path):
                    delete_local_backup(local_backup_path)
                continue

    log("----------------------------------", 'info')
    log("Backup cycle completed", 'info')
    
    # Print summary report
    log("=" * 50, 'info')
    log("BACKUP SUMMARY REPORT", 'info')
    log("=" * 50, 'info')
    log(f"Total volumes processed: {volumes_success + volumes_failed}", 'info',
        total=volumes_success + volumes_failed)
    log(f"Successful backups: {volumes_success}", 'info', success=volumes_success)
    log(f"Failed backups: {volumes_failed}", 'info', failed=volumes_failed)
    

    if successful_volumes:
        log("", 'info')
        log("Successfully backed up volumes:", 'info')
        for item in successful_volumes:
            log(f"  ✓ {item['volume']}", 'info',
                volume=item['volume'],
                backup_file=item['backup_file'],
                sha256=item.get('sha256'),
                rclone_check=item.get('rclone_check'),
                test_restore=item.get('test_restore'),
                size_bytes=item.get('size_bytes'))

    if failed_volumes:
        log("", 'info')
        log("Failed volumes:", 'error')
        for item in failed_volumes:
            log(f"  ✗ {item['volume']}: {item['error']}", 'error',
                volume=item['volume'],
                error=item['error'])

    log("=" * 50, 'info')

    # Update metrics and health state with verification info
    update_state(
        volumes_backed_up=volumes_success,
        volumes_failed=volumes_failed,
        current_operation=None,
        last_error=failed_volumes[-1]['error'] if failed_volumes else None,
        last_verification=[{
            'volume': v['volume'],
            'sha256': v.get('sha256'),
            'rclone_check': v.get('rclone_check'),
            'test_restore': v.get('test_restore'),
            'size_bytes': v.get('size_bytes')
        } for v in successful_volumes]
    )

    # Run postscript if exists
    run_postscript(postscript)


if __name__ == '__main__':
    main()
