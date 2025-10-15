#!/usr/bin/env python3
"""
Backup and Sync - Entrypoint/Scheduler
Handles scheduled execution of backup tasks
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta
import subprocess
import signal

# Import health server
try:
    from health_server import start_health_server, update_state
    HEALTH_SERVER_AVAILABLE = True
except ImportError:
    HEALTH_SERVER_AVAILABLE = False
    def start_health_server(*args, **kwargs):
        pass
    def update_state(*args, **kwargs):
        pass

# Global flag for graceful shutdown
shutdown_requested = False
backup_in_progress = False


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


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global shutdown_requested
    
    signal_name = signal.Signals(signum).name
    
    if backup_in_progress:
        log(f"Received {signal_name}, waiting for current backup to complete...", 'warning',
            signal=signal_name)
        log("Press Ctrl+C again to force shutdown (may cause data corruption)", 'warning')
        shutdown_requested = True
        update_state(status='shutting_down', current_operation='graceful_shutdown')
    else:
        log(f"Received {signal_name}, shutting down immediately", 'info',
            signal=signal_name)
        update_state(status='stopped')
        sys.exit(0)


def log(message, level='info', **context):
    """Log message with specified level and optional context
    
    Args:
        message: Log message
        level: Log level (debug, info, warning, error, critical)
        **context: Additional context to include in message (e.g., time='09:20')
    """
    # Add context to message if provided
    if context:
        context_str = ' '.join(f'{k}={v}' for k, v in context.items())
        message = f"{message} [{context_str}]"
    
    log_func = getattr(logger, level.lower(), logger.info)
    log_func(message)
    sys.stdout.flush()


def parse_time(time_str):
    """Parse time string in format HH:MM"""
    try:
        return datetime.strptime(time_str, '%H:%M').time()
    except ValueError:
        log(f"Invalid time format: {time_str} (expected HH:MM)", 'error', 
            format_expected='HH:MM', format_received=time_str)
        sys.exit(1)


def get_next_run_time(target_time):
    """Calculate next run time based on target time"""
    now = datetime.now()
    target_datetime = datetime.combine(now.date(), target_time)

    # If target time has passed today, schedule for tomorrow
    if now.time() >= target_time:
        target_datetime += timedelta(days=1)

    return target_datetime


def run_backup():
    """Execute the backup script"""
    global backup_in_progress, shutdown_requested

    log("=" * 50, 'info')
    log("Starting backup cycle", 'info')
    log("=" * 50, 'info')

    # Update state - set backup_status to 1 (running) and time_until_next to 0
    update_state(
        status='running',
        current_operation='backup_cycle',
        backup_status=1,
        backup_time_until_next=0
    )
    backup_in_progress = True

    start_time = time.time()

    try:
        # Run subprocess with unbuffered output and real-time streaming
        subprocess.run(
            [sys.executable, '-u', '/usr/local/bin/backups_n_sync.py'],
            check=True,
            stdout=sys.stdout,
            stderr=sys.stderr,
            env={**os.environ, 'PYTHONUNBUFFERED': '1'}
        )
        elapsed = time.time() - start_time
        log("=" * 50, 'info')
        log(f"Backup cycle completed successfully in {elapsed:.2f}s", 'info', 
            duration_seconds=f"{elapsed:.2f}")
        log("=" * 50, 'info')
        
        # Update state on success - set backup_status to 0 (waiting)
        update_state(
            status='idle',
            last_backup_status='success',
            last_backup_time=datetime.now().isoformat(),
            last_duration=elapsed,
            current_operation=None,
            total_backups=lambda s: s.get('total_backups', 0) + 1,
            backup_status=0
        )
        
        backup_in_progress = False
        return True
    except subprocess.CalledProcessError as e:
        elapsed = time.time() - start_time
        log("=" * 50, 'error')
        log(f"Backup cycle failed after {elapsed:.2f}s", 'error', 
            duration_seconds=f"{elapsed:.2f}", exit_code=e.returncode)
        log("=" * 50, 'error')
        
        # Update state on failure - set backup_status to 0 (waiting)
        update_state(
            status='error',
            last_backup_status='failed',
            last_backup_time=datetime.now().isoformat(),
            last_duration=elapsed,
            last_error=f"Exit code {e.returncode}",
            current_operation=None,
            total_failures=lambda s: s.get('total_failures', 0) + 1,
            backup_status=0
        )
        
        backup_in_progress = False
        return False
    finally:
        backup_in_progress = False
        
        # Check if shutdown was requested during backup
        if shutdown_requested:
            log("Backup completed, proceeding with shutdown", 'info')
            update_state(status='stopped')
            sys.exit(0)


def main():
    """Main entrypoint logic"""
    global shutdown_requested
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    log("=" * 50, 'info')
    log("Backup and Sync - Starting", 'info')
    log("=" * 50, 'info')
    log("Signal handlers registered for graceful shutdown", 'debug')
    
    # Start health server if enabled
    health_port = int(os.environ.get('HEALTH_PORT', '8080'))
    enable_health = os.environ.get('ENABLE_HEALTH_SERVER', 'true').lower() in ('true', '1', 'yes')
    
    if enable_health:
        if HEALTH_SERVER_AVAILABLE:
            start_health_server(health_port)
            log(f"Health server enabled on port {health_port}", 'info', port=health_port)
        else:
            log("Health server requested but health_server.py not available", 'warning')
    
    # Initialize state
    update_state(
        status='starting',
        start_time=datetime.now().isoformat(),
        backup_status=0,
        backup_time_until_next=0
    )

    wakeup_time_str = os.environ.get('WAKEUPTIME', '')
    skip_first_run = os.environ.get('SKIPFIRSTRUN', 'false').lower() in ('true', '1', 'yes')

    now = datetime.now()
    log(f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S')}", 'info', 
        timestamp=now.strftime('%Y-%m-%d %H:%M:%S'))

    if not wakeup_time_str:
        # Run once and exit
        log("WAKEUPTIME is not set, running once", 'info')
        update_state(status='running', backup_status=1, backup_time_until_next=0)
        run_backup()
        update_state(status='completed', backup_status=0, backup_time_until_next=0)
        return

    # Parse wakeup time
    wakeup_time = parse_time(wakeup_time_str)
    log(f"Scheduler started with wakeup time: {wakeup_time_str}", 'info', 
        wakeup_time=wakeup_time_str)
    log(f"SKIPFIRSTRUN is {'enabled' if skip_first_run else 'disabled'}", 'info', 
        skip_first_run=skip_first_run)

    # Check if we should run immediately
    if not skip_first_run:
        now = datetime.now().time()
        if now >= wakeup_time:
            log("Current time is past wakeup time, running backup now", 'info')
            update_state(status='idle', backup_status=0, backup_time_until_next=0)
            run_backup()
        else:
            next_run = get_next_run_time(wakeup_time)
            wait_seconds = (next_run - datetime.now()).total_seconds()
            log("Current time is before wakeup time", 'info')
            log(f"Next backup scheduled for: {next_run.strftime('%Y-%m-%d %H:%M:%S')}", 'info',
                next_run=next_run.strftime('%Y-%m-%d %H:%M:%S'))
            log(f"Waiting {int(wait_seconds)}s ({int(wait_seconds/3600)}h {int((wait_seconds%3600)/60)}m) until first run", 'info',
                wait_seconds=int(wait_seconds))
            update_state(status='idle', backup_status=0, backup_time_until_next=int(wait_seconds))
    else:
        next_run = get_next_run_time(wakeup_time)
        wait_seconds = (next_run - datetime.now()).total_seconds()
        log("First run skipped (SKIPFIRSTRUN enabled)", 'info')
        log(f"Next backup scheduled for: {next_run.strftime('%Y-%m-%d %H:%M:%S')}", 'info',
            next_run=next_run.strftime('%Y-%m-%d %H:%M:%S'))
        log(f"Waiting {int(wait_seconds)}s ({int(wait_seconds/3600)}h {int((wait_seconds%3600)/60)}m) until next run", 'info',
            wait_seconds=int(wait_seconds))
        update_state(status='idle', backup_status=0, backup_time_until_next=int(wait_seconds))

    # Main loop
    while True:
        # Check for shutdown request
        if shutdown_requested:
            log("Shutdown requested, exiting main loop", 'info')
            update_state(status='stopped')
            sys.exit(0)
        
        next_run = get_next_run_time(wakeup_time)
        now = datetime.now()
        sleep_seconds = (next_run - now).total_seconds()

        log(f"Going to sleep for {int(sleep_seconds)}s", 'debug', 
            sleep_seconds=int(sleep_seconds))

        # Sleep in smaller intervals to check for shutdown and update metrics
        sleep_interval = 60  # Check every minute
        total_slept = 0
        while total_slept < sleep_seconds:
            if shutdown_requested:
                log("Shutdown requested during sleep, exiting", 'info')
                update_state(status='stopped')
                sys.exit(0)

            # Update time until next backup
            remaining_seconds = int(sleep_seconds - total_slept)
            update_state(backup_time_until_next=remaining_seconds)

            interval = min(sleep_interval, sleep_seconds - total_slept)
            time.sleep(interval)
            total_slept += interval

        # Run the backup if not shutting down
        if not shutdown_requested:
            run_backup()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        if backup_in_progress:
            log("Forced shutdown during backup - data may be corrupted", 'critical')
            update_state(status='stopped', last_error='Forced shutdown during backup')
        else:
            log("Received interrupt signal, shutting down", 'info')
            update_state(status='stopped')
        sys.exit(0)
    except Exception as e:
        log(f"FATAL ERROR: {e}", 'critical', error=str(e))
        update_state(status='error', last_error=str(e))
        sys.exit(1)
