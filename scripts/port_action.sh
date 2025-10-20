#!/bin/bash

PORTAINER_ENDPOINT="https://port.minixer.cloud"

# ====== Sanity check ======
if [[ -z "$ACTION" ]]; then
    echo "ERROR: ACTION variable must be set (e.g., start, stop, restart, pause, unpause, status, inspect, etc.)."
    exit 2
fi

# ====== Get endpoint ID ======
ENDPOINT_ID=$(curl -s -H "X-API-Key: $API_KEY" "$PORTAINER_ENDPOINT/api/endpoints" | jq -r ".[] | select(.Name==\"$TARGET_HOST\") | .Id")

if [ -z "$ENDPOINT_ID" ]; then
    echo "Host $TARGET_HOST not found"
    exit 3
fi

# ====== Get container ID ======
CONTAINER_ID=$(curl -s -H "X-API-Key: $API_KEY" "$PORTAINER_ENDPOINT/api/endpoints/$ENDPOINT_ID/docker/containers/json?all=1" | jq -r ".[] | select(.Names[]==\"/$TARGET_CONTAINER\") | .Id")

if [ -z "$CONTAINER_ID" ]; then
    echo "Container $TARGET_CONTAINER not found"
    exit 4
fi

# ====== Determine HTTP method and endpoint based on action ======
case "$ACTION" in
    status|inspect)
        # GET request for status/inspect
        HTTP_METHOD="GET"
        API_ENDPOINT="$PORTAINER_ENDPOINT/api/endpoints/$ENDPOINT_ID/docker/containers/$CONTAINER_ID/json"
        RESPONSE=$(curl -s -w "\n%{http_code}" -X "$HTTP_METHOD" -H "X-API-Key: $API_KEY" "$API_ENDPOINT")
        HTTP_STATUS=$(echo "$RESPONSE" | tail -n1)
        RESPONSE_BODY=$(echo "$RESPONSE" | sed '$d')
        
        if [[ "$HTTP_STATUS" == "200" ]]; then
            CONTAINER_STATE=$(echo "$RESPONSE_BODY" | jq -r '.State.Status')
            echo "Container '$TARGET_CONTAINER' status: $CONTAINER_STATE"
            exit 0
        else
            echo "Failed to get status of container '$TARGET_CONTAINER'. HTTP status: $HTTP_STATUS"
            exit 5
        fi
        ;;
    start|stop|restart|pause|unpause|kill)
        # POST request for control actions
        HTTP_METHOD="POST"
        API_ENDPOINT="$PORTAINER_ENDPOINT/api/endpoints/$ENDPOINT_ID/docker/containers/$CONTAINER_ID/$ACTION"
        HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X "$HTTP_METHOD" -H "X-API-Key: $API_KEY" "$API_ENDPOINT")
        
        if [[ "$HTTP_STATUS" == "204" ]]; then
            echo "Container '$TARGET_CONTAINER' ${ACTION}ed successfully."
            exit 0
        elif [[ "$HTTP_STATUS" == "304" ]]; then
            echo "Container '$TARGET_CONTAINER' already ${ACTION}ed (no change necessary)."
            exit 0
        else
            echo "Failed to ${ACTION} container '$TARGET_CONTAINER'. HTTP status: $HTTP_STATUS"
            exit 5
        fi
        ;;
    *)
        echo "ERROR: Unknown action '$ACTION'. Valid actions: start, stop, restart, pause, unpause, kill, status, inspect"
        exit 2
        ;;
esac
