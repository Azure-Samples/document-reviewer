#!/usr/bin/env bash
# Post-deployment: register SharePoint GetOnNewFileItems for the document review agent.

set -euo pipefail

FUNCTION_NAME="document_review_announcer"
OPERATION_NAME="GetOnNewFileItems"
TRIGGER_NAME="sharepoint-document-review-on-new-file"
KEY_TIMEOUT_SECONDS="${CONNECTOR_KEY_TIMEOUT_SECONDS:-600}"
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required."
}

require_command az
require_command azd
require_command jq

outputs=$(azd env get-values --output json)
subscriptionId=$(printf '%s' "$outputs" | jq -r '.AZURE_SUBSCRIPTION_ID // empty')
resourceGroup=$(printf '%s' "$outputs" | jq -r '.AZURE_RESOURCE_GROUP // .RESOURCE_GROUP // empty')
functionAppName=$(printf '%s' "$outputs" | jq -r '.AZURE_FUNCTION_APP_NAME // .SERVICE_API_NAME // empty')
connectorNamespace=$(printf '%s' "$outputs" | jq -r '.CONNECTOR_NAMESPACE_NAME // empty')
sharepointConnection=$(printf '%s' "$outputs" | jq -r '.SHAREPOINT_CONNECTION_NAME // empty')
sharepointSiteUrl=$(printf '%s' "$outputs" | jq -r '.SHAREPOINT_SITE_URL // empty')
sharepointLibraryName=$(printf '%s' "$outputs" | jq -r '.SHAREPOINT_LIBRARY_NAME // empty')
sharepointFolderPath=$(printf '%s' "$outputs" | jq -r '.SHAREPOINT_FOLDER_PATH // empty')

[[ -n "$subscriptionId" ]] || fail "AZURE_SUBSCRIPTION_ID is missing."
[[ -n "$resourceGroup" ]] || fail "AZURE_RESOURCE_GROUP is missing. Run 'azd provision' first."
[[ -n "$functionAppName" ]] || fail "AZURE_FUNCTION_APP_NAME is missing. Run 'azd deploy' first."
[[ -n "$connectorNamespace" ]] || fail "CONNECTOR_NAMESPACE_NAME is missing. Run 'azd provision' first."
[[ -n "$sharepointConnection" ]] || fail "SHAREPOINT_CONNECTION_NAME is missing. Run 'azd provision' first."
[[ -n "$sharepointSiteUrl" ]] || fail "SHAREPOINT_SITE_URL is missing."
[[ -n "$sharepointLibraryName" ]] || fail "SHAREPOINT_LIBRARY_NAME is missing."
[[ -n "$sharepointFolderPath" ]] || fail "SHAREPOINT_FOLDER_PATH is missing."

if ! az extension show --name connector-namespace --query name --output tsv >/dev/null 2>&1; then
  fail "The connector-namespace Azure CLI extension is required. Install it from https://aka.ms/connector-namespace-cli-install."
fi

triggerCommand="create"
if az connector-namespace trigger show \
  --resource-group "$resourceGroup" \
  --namespace "$connectorNamespace" \
  --name "$TRIGGER_NAME" \
  --query name \
  --output tsv >/dev/null 2>&1; then
  forceTriggerUpdate=$(printf '%s' "${FORCE_CONNECTOR_TRIGGER_UPDATE:-false}" | tr '[:upper:]' '[:lower:]')
  if [[ "$forceTriggerUpdate" != "true" && "$forceTriggerUpdate" != "1" && "$forceTriggerUpdate" != "yes" ]]; then
    printf 'SharePoint new-file trigger already exists; leaving its polling state unchanged.\n'
    exit 0
  fi
  triggerCommand="update"
fi

printf 'Waiting for the Function connector extension to finish indexing.\n'
deadline=$(( $(date +%s) + KEY_TIMEOUT_SECONDS ))
connectorKey=""
while [[ $(date +%s) -lt $deadline ]]; do
  connectorKey=$(az functionapp keys list \
    --resource-group "$resourceGroup" \
    --name "$functionAppName" \
    --query systemKeys.connector_extension \
    --output tsv 2>/dev/null || true)
  if [[ -n "$connectorKey" ]]; then
    break
  fi
  sleep 10
done
[[ -n "$connectorKey" ]] || fail "The connector_extension system key was not created in time. Check Function startup logs and retry."

encodedKey=$(printf '%s' "$connectorKey" | jq -sRr @uri)
callbackUrl="https://${functionAppName}.azurewebsites.net/runtime/webhooks/connector?functionName=${FUNCTION_NAME}&code=${encodedKey}"

tempDirectory=$(mktemp -d)
chmod 700 "$tempDirectory"
connectionFile="${tempDirectory}/connection.json"
notificationFile="${tempDirectory}/notification.json"
parametersFile="${tempDirectory}/parameters.json"
metadataFile="${tempDirectory}/metadata.json"

cleanup() {
  rm -f "$connectionFile" "$notificationFile" "$parametersFile" "$metadataFile"
  rmdir "$tempDirectory" 2>/dev/null || true
}
trap cleanup EXIT

jq -n \
  --arg connection "$sharepointConnection" \
  '{connectorName:"sharepointonline",connectionName:$connection}' > "$connectionFile"
printf '{"callbackUrl":"%s","httpMethod":"Post"}\n' "$callbackUrl" > "$notificationFile"
jq -n \
  --arg site "$sharepointSiteUrl" \
  --arg library "$sharepointLibraryName" \
  --arg folder "$sharepointFolderPath" \
  '[
    {name:"dataset",value:$site},
    {name:"table",value:$library},
    {name:"folderPath",value:$folder}
  ]' > "$parametersFile"
jq -n \
  --arg functionApp "$functionAppName" \
  --arg resourceGroup "$resourceGroup" \
  --arg subscription "$subscriptionId" \
  --arg functionName "$FUNCTION_NAME" \
  '{
    destinationType:"functionApp",
    functionAppName:$functionApp,
    functionAppResourceGroup:$resourceGroup,
    functionAppSubscriptionId:$subscription,
    functionName:$functionName,
    recurrenceFrequency:"Minute",
    recurrenceInterval:"5"
  }' > "$metadataFile"

az connector-namespace trigger "$triggerCommand" \
  --resource-group "$resourceGroup" \
  --namespace "$connectorNamespace" \
  --name "$TRIGGER_NAME" \
  --connection-details "@${connectionFile}" \
  --operation-name "$OPERATION_NAME" \
  --parameters "@${parametersFile}" \
  --notification-details "@${notificationFile}" \
  --metadata "@${metadataFile}" \
  --state Enabled \
  --description "SharePoint GetOnNewFileItems -> document_review_announcer" \
  --output none

cleanup
trap - EXIT

printf 'SharePoint new-file trigger configured.\n'
printf 'Authorize the SharePoint and Teams connections in https://connectors.azure.com/ before testing.\n'
