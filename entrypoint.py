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
    log("=" * 50, 'info')
    log("Starting backup cycle", 'info')
    log("=" * 50, 'info')

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
        return True
    except subprocess.CalledProcessError as e:
        elapsed = time.time() - start_time
        log("=" * 50, 'error')
        log(f"Backup cycle failed after {elapsed:.2f}s", 'error', 
            duration_seconds=f"{elapsed:.2f}", exit_code=e.returncode)
        log("=" * 50, 'error')
        return False


def main():
    """Main entrypoint logic"""
    log("=" * 50, 'info')
    log("Backup and Sync - Starting", 'info')
    log("=" * 50, 'info')

    wakeup_time_str = os.environ.get('WAKEUPTIME', '')
    skip_first_run = os.environ.get('SKIPFIRSTRUN', 'false').lower() in ('true', '1', 'yes')

    now = datetime.now()
    log(f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S')}", 'info', 
        timestamp=now.strftime('%Y-%m-%d %H:%M:%S'))

    if not wakeup_time_str:
        # Run once and exit
        log("WAKEUPTIME is not set, running once", 'info')
        run_backup()
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
            run_backup()
        else:
            next_run = get_next_run_time(wakeup_time)
            wait_seconds = (next_run - datetime.now()).total_seconds()
            log("Current time is before wakeup time", 'info')
            log(f"Next backup scheduled for: {next_run.strftime('%Y-%m-%d %H:%M:%S')}", 'info',
                next_run=next_run.strftime('%Y-%m-%d %H:%M:%S'))
            log(f"Waiting {int(wait_seconds)}s ({int(wait_seconds/3600)}h {int((wait_seconds%3600)/60)}m) until first run", 'info',
                wait_seconds=int(wait_seconds))
    else:
        next_run = get_next_run_time(wakeup_time)
        wait_seconds = (next_run - datetime.now()).total_seconds()
        log("First run skipped (SKIPFIRSTRUN enabled)", 'info')
        log(f"Next backup scheduled for: {next_run.strftime('%Y-%m-%d %H:%M:%S')}", 'info',
            next_run=next_run.strftime('%Y-%m-%d %H:%M:%S'))
        log(f"Waiting {int(wait_seconds)}s ({int(wait_seconds/3600)}h {int((wait_seconds%3600)/60)}m) until next run", 'info',
            wait_seconds=int(wait_seconds))

    # Main loop
    while True:
        next_run = get_next_run_time(wakeup_time)
        now = datetime.now()
        sleep_seconds = (next_run - now).total_seconds()

        log(f"Going to sleep for {int(sleep_seconds)}s", 'debug', 
            sleep_seconds=int(sleep_seconds))

        time.sleep(sleep_seconds)

        # Run the backup
        run_backup()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        log("Received interrupt signal, shutting down", 'info')
        sys.exit(0)
    except Exception as e:
        log(f"FATAL ERROR: {e}", 'critical', error=str(e))
        sys.exit(1)
