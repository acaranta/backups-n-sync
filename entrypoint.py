#!/usr/bin/env python3
"""
Backup and Sync - Entrypoint/Scheduler
Handles scheduled execution of backup tasks
"""

import os
import sys
import time
from datetime import datetime, timedelta
import subprocess


def log(message):
    """Print log message with timestamp"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def parse_time(time_str):
    """Parse time string in format HH:MM"""
    try:
        return datetime.strptime(time_str, '%H:%M').time()
    except ValueError:
        log(f"ERROR: Invalid time format: {time_str} (expected HH:MM)")
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
    log("=" * 50)
    log("Starting backup cycle")
    log("=" * 50)

    start_time = time.time()

    try:
        result = subprocess.run(
            [sys.executable, '/usr/local/bin/backups_n_sync.py'],
            check=True
        )
        elapsed = time.time() - start_time
        log("=" * 50)
        log(f"Backup cycle completed successfully in {elapsed:.2f}s")
        log("=" * 50)
        return True
    except subprocess.CalledProcessError as e:
        elapsed = time.time() - start_time
        log("=" * 50)
        log(f"ERROR: Backup cycle failed after {elapsed:.2f}s")
        log("=" * 50)
        return False


def main():
    """Main entrypoint logic"""
    wakeup_time_str = os.environ.get('WAKEUPTIME', '')
    skip_first_run = os.environ.get('SKIPFIRSTRUN', 'false').lower() in ('true', '1', 'yes')

    if not wakeup_time_str:
        # Run once and exit
        log("WAKEUPTIME is not set, running once")
        run_backup()
        return

    # Parse wakeup time
    wakeup_time = parse_time(wakeup_time_str)
    log(f"Scheduler started with wakeup time: {wakeup_time_str}")

    # Check if we should run immediately
    if not skip_first_run:
        now = datetime.now().time()
        if now >= wakeup_time:
            log("Current time is past wakeup time, running backup now")
            run_backup()

    # Main loop
    while True:
        next_run = get_next_run_time(wakeup_time)
        now = datetime.now()
        sleep_seconds = (next_run - now).total_seconds()

        log(f"Next backup scheduled for: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
        log(f"Going to sleep for {int(sleep_seconds)}s")

        time.sleep(sleep_seconds)

        # Run the backup
        run_backup()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        log("Received interrupt signal, shutting down")
        sys.exit(0)
    except Exception as e:
        log(f"FATAL ERROR: {e}")
        sys.exit(1)
