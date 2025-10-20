#!/bin/bash

# ============================================================================
# Database Backup Script
# ============================================================================
# This script performs automated backups of MySQL or PostgreSQL databases
# Supports: MySQL and PostgreSQL database servers
# Runs inside Docker container - expects database clients to be available
# ============================================================================

set -o pipefail

# ============================================================================
# Configuration and Environment Variables
# ============================================================================

# Required environment variables
REQUIRED_VARS=("DB_HOST" "DB_USER" "DB_PASS")

# Optional environment variables with defaults
DB_TYPE="${DB_TYPE:-mysql}"
DB_PORT="${DB_PORT:-}"
MAXBKP="${MAXBKP:-7}"
BKP_DBGROUP="${BKP_DBGROUP:-SQLDumps}"

# Set default port based on DB_TYPE if not specified
if [ -z "${DB_PORT}" ]; then
    case "${DB_TYPE}" in
        mysql)
            DB_PORT=3306
            ;;
        postgresql|postgres)
            DB_TYPE="postgresql"
            DB_PORT=5432
            ;;
        *)
            echo "ERROR: Unsupported DB_TYPE '${DB_TYPE}'. Supported types: mysql, postgresql"
            exit 1
            ;;
    esac
fi

# ============================================================================
# Validation Functions
# ============================================================================

validate_required_vars() {
    local missing_vars=()

    for var in "${REQUIRED_VARS[@]}"; do
        if [ -z "${!var}" ]; then
            missing_vars+=("${var}")
        fi
    done

    if [ ${#missing_vars[@]} -gt 0 ]; then
        echo "ERROR: Required environment variables not set:"
        for var in "${missing_vars[@]}"; do
            echo "  - ${var}"
        done
        exit 1
    fi
}

log_info() {
    echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S') - $*"
}

log_error() {
    echo "[ERROR] $(date '+%Y-%m-%d %H:%M:%S') - $*" >&2
}

log_warn() {
    echo "[WARN] $(date '+%Y-%m-%d %H:%M:%S') - $*"
}

# ============================================================================
# Directory and Timestamp Setup
# ============================================================================

setup_environment() {
    # Set HOSTID
    if [ -z "${HOSTID}" ]; then
        export HOSTID=$(hostname)
        log_info "HOSTID not set, using hostname: ${HOSTID}"
    fi

    # Set BKPDIR
    if [ -z "${BKPDIR}" ]; then
        if [ -z "${BKP_BASE_DIR}" ]; then
            export BKPDIR="/srv/vockerdolumes/backups2Dropbox/${HOSTID}"
        else
            export BKPDIR="${BKP_BASE_DIR}/${HOSTID}"
        fi
        log_info "BKPDIR set to: ${BKPDIR}"
    fi

    # Set timestamp
    if [ -z "${RUNTMSTP}" ]; then
        export RUNTMSTP=$(date +%Y%m%d)
        log_info "RUNTMSTP set to: ${RUNTMSTP}"
    fi
}

# ============================================================================
# Database-specific Functions
# ============================================================================

get_mysql_databases() {
    local dblist
    dblist=$(mysql -h "${DB_HOST}" -P "${DB_PORT}" -u"${DB_USER}" -p"${DB_PASS}" -e "SHOW DATABASES" 2>/dev/null | \
             awk '{print $1}' | \
             grep -iv '^Database$' | \
             grep -v '^information_schema$' | \
             grep -v '^performance_schema$' | \
             grep -v '^mysql$' | \
             grep -v '^sys$' | \
             grep .)
    echo "${dblist}"
}

get_postgresql_databases() {
    local dblist
    PGPASSWORD="${DB_PASS}" dblist=$(psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -t -c "SELECT datname FROM pg_database WHERE datistemplate = false;" 2>/dev/null | \
             sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | \
             grep -v '^postgres$' | \
             grep -v '^template0$' | \
             grep -v '^template1$' | \
             grep .)
    echo "${dblist}"
}

backup_mysql_database() {
    local dbname="$1"
    local output_file="$2"

    mysqldump -h "${DB_HOST}" -P "${DB_PORT}" -u"${DB_USER}" -p"${DB_PASS}" \
              --add-drop-database \
              --column-statistics=0 \
              -B "${dbname}" 2>/dev/null > "${output_file}"
    return $?
}

backup_postgresql_database() {
    local dbname="$1"
    local output_file="$2"

    PGPASSWORD="${DB_PASS}" pg_dump -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" \
              --clean \
              --if-exists \
              "${dbname}" 2>/dev/null > "${output_file}"
    return $?
}

# ============================================================================
# Backup and Cleanup Functions
# ============================================================================

cleanup_old_backups() {
    local backup_dir="$1"
    local dbname="$2"
    local pattern="${backup_dir}/*__${dbname}_dump.sql*"

    log_info "Cleaning old backups to keep only ${MAXBKP} backup files for ${dbname}"

    # Get list of backup files, sorted newest first
    local bkp_files=($(ls -t ${pattern} 2>/dev/null))
    local n=${MAXBKP}

    for file in "${bkp_files[@]}"; do
        if [ "$n" -le 0 ]; then
            rm -f "$file"
            log_info "  Removed: $(basename "$file")"
        else
            log_info "  Keeping: $(basename "$file")"
            ((n--))
        fi
    done
}

perform_backup() {
    local success_count=0
    local error_count=0
    local backup_dir="${BKPDIR}/${BKP_DBGROUP}/${DB_HOST}"

    # Create backup directory
    mkdir -p "${backup_dir}" 2>/dev/null

    if [ ! -d "${backup_dir}" ]; then
        log_error "Failed to create backup directory: ${backup_dir}"
        return 1
    fi

    log_info "Starting ${DB_TYPE} backup for ${DB_HOST}:${DB_PORT}"
    log_info "Backup directory: ${backup_dir}"
    log_info "Backup group: ${BKP_DBGROUP}"

    # Get list of databases based on type
    local dblist
    case "${DB_TYPE}" in
        mysql)
            dblist=$(get_mysql_databases)
            ;;
        postgresql)
            dblist=$(get_postgresql_databases)
            ;;
    esac

    if [ -z "${dblist}" ]; then
        log_error "No databases found or failed to connect to ${DB_TYPE} server at ${DB_HOST}:${DB_PORT}"
        return 1
    fi

    log_info "Found databases: $(echo ${dblist} | wc -w)"

    # Backup each database
    for dbname in ${dblist}; do
        log_info "Processing database: ${dbname}"

        local output_file="${backup_dir}/${RUNTMSTP}_${DB_HOST}__${dbname}_dump.sql"

        # Perform backup based on type
        case "${DB_TYPE}" in
            mysql)
                backup_mysql_database "${dbname}" "${output_file}"
                ;;
            postgresql)
                backup_postgresql_database "${dbname}" "${output_file}"
                ;;
        esac

        if [ $? -eq 0 ] && [ -f "${output_file}" ] && [ -s "${output_file}" ]; then
            # Compress the backup
            gzip -f "${output_file}"
            if [ $? -eq 0 ]; then
                log_info "  Successfully backed up and compressed: ${dbname}"
                ((success_count++))
            else
                log_error "  Failed to compress backup for: ${dbname}"
                ((error_count++))
            fi
        else
            log_error "  Failed to backup database: ${dbname}"
            rm -f "${output_file}" 2>/dev/null
            ((error_count++))
            continue
        fi

        # Cleanup old backups
        cleanup_old_backups "${backup_dir}" "${dbname}"
    done

    # Print summary
    log_info "Backup completed - Success: ${success_count}, Errors: ${error_count}"

    return ${error_count}
}

# ============================================================================
# Rclone Sync Function
# ============================================================================

sync_to_rclone() {
    local source_dir="${BKPDIR}/${BKP_DBGROUP}"

    # Sanity checks for rclone upload
    if [ -z "${RCL_TARGET}" ] || [ -z "${RCL_PREFIX}" ] || [ -z "${RCL_SUFFIX}" ]; then
        log_warn "Skipping rclone upload - required environment variables not set"
        [ -z "${RCL_TARGET}" ] && log_warn "  - RCL_TARGET is not set"
        [ -z "${RCL_PREFIX}" ] && log_warn "  - RCL_PREFIX is not set"
        [ -z "${RCL_SUFFIX}" ] && log_warn "  - RCL_SUFFIX is not set"
        return 0
    fi

    # Check if source directory exists
    if [ ! -d "${source_dir}" ]; then
        log_error "Source directory does not exist: ${source_dir}"
        return 1
    fi

    local remote_path="${RCL_TARGET}:${RCL_PREFIX}/${HOSTID}/${RCL_SUFFIX}/${BKP_DBGROUP}"
    log_info "Uploading backups to rclone remote: ${remote_path}"

    rclone sync "${source_dir}" "${remote_path}"

    if [ $? -eq 0 ]; then
        log_info "Successfully synced to rclone remote"
        return 0
    else
        log_error "Failed to sync to rclone remote"
        return 1
    fi
}

# ============================================================================
# Main Execution
# ============================================================================

main() {
    log_info "==================================================================="
    log_info "Database Backup Script Starting"
    log_info "==================================================================="

    # Validate required environment variables
    validate_required_vars

    # Setup environment
    setup_environment

    log_info "Configuration:"
    log_info "  DB_TYPE: ${DB_TYPE}"
    log_info "  DB_HOST: ${DB_HOST}"
    log_info "  DB_PORT: ${DB_PORT}"
    log_info "  DB_USER: ${DB_USER}"
    log_info "  BKP_DBGROUP: ${BKP_DBGROUP}"
    log_info "  MAXBKP: ${MAXBKP}"
    log_info "  HOSTID: ${HOSTID}"

    # Perform backup
    perform_backup
    local backup_exit_code=$?

    # Sync to rclone if configured
    sync_to_rclone
    local rclone_exit_code=$?

    log_info "==================================================================="
    log_info "Database Backup Script Finished"
    log_info "==================================================================="

    # Exit with error if either backup or rclone failed
    if [ ${backup_exit_code} -ne 0 ]; then
        exit ${backup_exit_code}
    elif [ ${rclone_exit_code} -ne 0 ]; then
        exit ${rclone_exit_code}
    fi

    exit 0
}

# Run main function
main
