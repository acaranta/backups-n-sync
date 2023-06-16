#!/bin/bash

LOOPIT=true
if [ -z "${SKIPFIRSTRUN}" ]; then
    SKIPFIRSTRUN=true
fi

while [ "$LOOPIT" = true ]; do
    if [ -z "${WAKEUPTIME}" ]; then
        echo "WAKEUPTIME is not set, running once"
        LOOPIT=false
        time /usr/local/bin/backups_n_sync.sh

    else
        echo "Will wakeup at ${WAKEUPTIME}"
    fi
    
    
    if [ "$LOOPIT" = true ]; then
        if [ $current_time -ge $target_time ]; then
            if [ "$SKIPFIRSTRUN" = false ]; then
                time /usr/local/bin/backups_n_sync.sh
            else
                SKIPFIRSTRUN=false
            fi
            
        fi
        
        current_time=$(date +%s)
        target_time=$(date -d "${WAKEUPTIME}" +%s)
        # calculate duration of sleep
        sleep_duration=$((target_time - current_time))
        
        # sleep until next wake-up time
        echo "For now ... going to sleep for ${sleep_duration}s now until ${WAKEUPTIME}"
        sleep $sleep_duration
    fi
done