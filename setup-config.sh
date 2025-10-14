# Example configuration files structure
# Create these directories and files before running docker-compose

# Directory structure:
# ./config/
# ├── bns/
# │   ├── backup_vols.txt
# │   ├── backup_pre_script.sh (optional)
# │   └── backup_post_script.sh (optional)
# ├── rclone/
# │   └── rclone.conf
# ├── prometheus/ (optional)
# │   └── prometheus.yml
# └── grafana/ (optional)
#     ├── dashboards/
#     └── datasources/

echo "Creating configuration directories..."
mkdir -p config/{bns,rclone,prometheus,grafana/{dashboards,datasources}}
mkdir -p backups

echo "Creating example backup volumes list..."
cat > config/bns/backup_vols.txt << 'EOF'
# List of Docker volumes to backup (one per line)
# Lines starting with # are ignored

# Example volumes - replace with your actual volumes
myapp_data
database_data
wordpress_data
nextcloud_data

# You can comment out volumes temporarily
# test_volume
EOF

echo "Creating example pre-script..."
cat > config/bns/backup_pre_script.sh << 'EOF'
#!/bin/bash
# Global pre-backup script
# Executed once before the entire backup cycle

echo "Starting backup cycle at $(date)"

# Example: Stop containers that need clean shutdown
# docker stop myapp-container

# Example: Send notification
# curl -X POST "https://api.telegram.org/bot<token>/sendMessage" \
#      -d "chat_id=<chat_id>&text=Backup cycle started on $(hostname)"
EOF

echo "Creating example post-script..."
cat > config/bns/backup_post_script.sh << 'EOF'
#!/bin/bash
# Global post-backup script
# Executed once after the entire backup cycle

echo "Backup cycle completed at $(date)"

# Example: Restart containers
# docker start myapp-container

# Example: Send notification with results
# curl -X POST "https://api.telegram.org/bot<token>/sendMessage" \
#      -d "chat_id=<chat_id>&text=Backup cycle completed on $(hostname)"
EOF

echo "Making scripts executable..."
chmod +x config/bns/*.sh

echo "Creating example rclone config..."
cat > config/rclone/rclone.conf << 'EOF'
# Rclone configuration file
# Configure your cloud storage provider here
# 
# Example configurations:

# For AWS S3:
# [MyCloudStorage]
# type = s3
# provider = AWS
# region = us-east-1
# access_key_id = YOUR_ACCESS_KEY
# secret_access_key = YOUR_SECRET_KEY

# For Google Drive:
# [MyCloudStorage]
# type = drive
# client_id = YOUR_CLIENT_ID
# client_secret = YOUR_CLIENT_SECRET
# token = YOUR_TOKEN

# For Dropbox:
# [MyCloudStorage]
# type = dropbox
# token = YOUR_TOKEN

# For local/network storage:
# [MyCloudStorage]
# type = local
# nounc = true

# IMPORTANT: Replace 'MyCloudStorage' with your actual remote name
# and configure the appropriate settings for your storage provider
EOF

echo "Creating Prometheus configuration (optional)..."
cat > config/prometheus/prometheus.yml << 'EOF'
global:
  scrape_interval: 30s
  evaluation_interval: 30s

scrape_configs:
  - job_name: 'backups-n-sync'
    static_configs:
      - targets: ['backups-n-sync:8080']
    metrics_path: '/metrics'
    scrape_interval: 30s
EOF

echo "Creating Grafana datasource (optional)..."
cat > config/grafana/datasources/prometheus.yml << 'EOF'
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
EOF

echo ""
echo "Configuration files created successfully!"
echo ""
echo "Next steps:"
echo "1. Configure your rclone remote in config/rclone/rclone.conf"
echo "2. Update config/bns/backup_vols.txt with your actual volumes"
echo "3. Adjust environment variables in docker-compose.yml"
echo "4. Run: docker-compose up -d"
echo ""
echo "Optional monitoring stack:"
echo "5. Run: docker-compose --profile monitoring up -d"
echo "6. Access Grafana at http://localhost:3000 (admin/admin)"
echo "7. Access Prometheus at http://localhost:9090"
echo ""
echo "Health check endpoint will be available at:"
echo "http://localhost:8080/health"
echo "http://localhost:8080/metrics"
echo "http://localhost:8080/ready"