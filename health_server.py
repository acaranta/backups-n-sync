#!/usr/bin/env python3
"""
Health check and monitoring HTTP server
Provides endpoints for container orchestration and monitoring systems
"""

import os
import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

# Shared state file for metrics
STATE_FILE = '/tmp/backup_state.json'


def get_state():
    """Read current state from file"""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read state file: {e}")
    
    return {
        'status': 'starting',
        'last_backup_time': None,
        'last_backup_status': None,
        'total_backups': 0,
        'total_failures': 0,
        'current_operation': None,
        'volumes_backed_up': 0,
        'volumes_failed': 0,
        'last_error': None
    }


def update_state(**kwargs):
    """Update state with new values
    
    Supports callable values that receive current state and return new value.
    Example: update_state(total_backups=lambda s: s.get('total_backups', 0) + 1)
    """
    try:
        state = get_state()
        
        # Process callable values
        for key, value in kwargs.items():
            if callable(value):
                kwargs[key] = value(state)
        
        state.update(kwargs)
        
        # Create directory if needed
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to update state: {e}")


class HealthHandler(BaseHTTPRequestHandler):
    """HTTP request handler for health and metrics endpoints"""
    
    def log_message(self, format, *args):
        """Override to use our logger"""
        logger.debug(format % args)
    
    def do_GET(self):
        """Handle GET requests"""
        if self.path == '/health':
            self.handle_health()
        elif self.path == '/metrics':
            self.handle_metrics()
        elif self.path == '/ready':
            self.handle_ready()
        else:
            self.send_error(404, "Not Found")
    
    def handle_health(self):
        """Basic health check endpoint"""
        state = get_state()
        
        # Service is healthy if not in error state
        is_healthy = state.get('status') != 'error'
        
        response = {
            'status': 'healthy' if is_healthy else 'unhealthy',
            'timestamp': datetime.now().isoformat(),
            'current_operation': state.get('current_operation')
        }
        
        self.send_json_response(response, 200 if is_healthy else 503)
    
    def handle_ready(self):
        """Readiness check endpoint"""
        state = get_state()
        
        # Service is ready if it has completed at least one operation
        is_ready = state.get('status') in ['idle', 'running', 'completed']
        
        response = {
            'ready': is_ready,
            'timestamp': datetime.now().isoformat()
        }
        
        self.send_json_response(response, 200 if is_ready else 503)
    
    def handle_metrics(self):
        """Metrics endpoint with Prometheus-compatible format"""
        state = get_state()

        # Get hostid from environment
        hostid = os.environ.get('HOSTID', os.uname().nodename)

        # Calculate uptime
        start_time = state.get('start_time')
        if start_time:
            uptime_seconds = (datetime.now() - datetime.fromisoformat(start_time)).total_seconds()
        else:
            uptime_seconds = 0

        # Prometheus-style metrics with backuphost label
        metrics = []
        metrics.append('# HELP backup_total_count Total number of backup cycles completed')
        metrics.append('# TYPE backup_total_count counter')
        metrics.append(f'backup_total_count{{backuphost="{hostid}"}} {state.get("total_backups", 0)}')
        metrics.append('')

        metrics.append('# HELP backup_failure_count Total number of backup failures')
        metrics.append('# TYPE backup_failure_count counter')
        metrics.append(f'backup_failure_count{{backuphost="{hostid}"}} {state.get("total_failures", 0)}')
        metrics.append('')

        metrics.append('# HELP backup_volumes_success Number of volumes successfully backed up in last cycle')
        metrics.append('# TYPE backup_volumes_success gauge')
        metrics.append(f'backup_volumes_success{{backuphost="{hostid}"}} {state.get("volumes_backed_up", 0)}')
        metrics.append('')

        metrics.append('# HELP backup_volumes_failed Number of volumes that failed in last cycle')
        metrics.append('# TYPE backup_volumes_failed gauge')
        metrics.append(f'backup_volumes_failed{{backuphost="{hostid}"}} {state.get("volumes_failed", 0)}')
        metrics.append('')

        metrics.append('# HELP backup_last_duration_seconds Duration of last backup cycle in seconds')
        metrics.append('# TYPE backup_last_duration_seconds gauge')
        metrics.append(f'backup_last_duration_seconds{{backuphost="{hostid}"}} {state.get("last_duration", 0)}')
        metrics.append('')

        metrics.append('# HELP backup_last_success_timestamp Unix timestamp of last successful backup')
        metrics.append('# TYPE backup_last_success_timestamp gauge')
        last_success = state.get('last_backup_time')
        if last_success:
            try:
                timestamp = datetime.fromisoformat(last_success).timestamp()
                metrics.append(f'backup_last_success_timestamp{{backuphost="{hostid}"}} {timestamp}')
            except Exception:
                metrics.append(f'backup_last_success_timestamp{{backuphost="{hostid}"}} 0')
        else:
            metrics.append(f'backup_last_success_timestamp{{backuphost="{hostid}"}} 0')
        metrics.append('')

        metrics.append('# HELP backup_uptime_seconds Service uptime in seconds')
        metrics.append('# TYPE backup_uptime_seconds gauge')
        metrics.append(f'backup_uptime_seconds{{backuphost="{hostid}"}} {uptime_seconds}')
        metrics.append('')

        # Total size of last backup cycle
        metrics.append('# HELP backup_last_total_size Total size of last backup cycle in megabytes')
        metrics.append('# TYPE backup_last_total_size gauge')
        last_total_size_mb = state.get('last_total_size_mb', 0)
        metrics.append(f'backup_last_total_size{{backuphost="{hostid}"}} {last_total_size_mb}')
        metrics.append('')

        # Per-volume metrics with labels
        volume_states = state.get('volume_states', {})

        if volume_states:
            metrics.append('# HELP backup_volume_size Volume backup size in megabytes')
            metrics.append('# TYPE backup_volume_size gauge')
            for volume, info in volume_states.items():
                size_mb = info.get('size_mb', 0)
                metrics.append(f'backup_volume_size{{backuphost="{hostid}",volume="{volume}"}} {size_mb}')
            metrics.append('')

            metrics.append('# HELP backup_volume_state Volume backup state (0=success, 1=failed, 2=skipped)')
            metrics.append('# TYPE backup_volume_state gauge')
            for volume, info in volume_states.items():
                state_value = info.get('state', 2)  # Default to skipped
                metrics.append(f'backup_volume_state{{backuphost="{hostid}",volume="{volume}"}} {state_value}')
            metrics.append('')

            metrics.append('# HELP backup_volume_duration Duration of volume backup in seconds')
            metrics.append('# TYPE backup_volume_duration gauge')
            for volume, info in volume_states.items():
                duration = info.get('duration_seconds', 0)
                metrics.append(f'backup_volume_duration{{backuphost="{hostid}",volume="{volume}"}} {duration}')
            metrics.append('')

        # Send response
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4')
        self.end_headers()
        self.wfile.write('\n'.join(metrics).encode())
    
    def send_json_response(self, data, status_code=200):
        """Send JSON response"""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())


def start_health_server(port=8080):
    """Start the health check HTTP server in a background thread"""
    def run_server():
        try:
            server = HTTPServer(('0.0.0.0', port), HealthHandler)
            logger.info(f"Health server started on port {port}")
            server.serve_forever()
        except Exception as e:
            logger.error(f"Health server error: {e}")
    
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    logger.info(f"Health server thread started on port {port}")


if __name__ == '__main__':
    # For testing
    logging.basicConfig(level=logging.INFO)
    update_state(
        status='idle',
        start_time=datetime.now().isoformat(),
        total_backups=5,
        total_failures=1,
        volumes_backed_up=3,
        volumes_failed=0,
        last_duration=125.5
    )
    start_health_server(8080)
    
    # Keep main thread alive
    import time
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
