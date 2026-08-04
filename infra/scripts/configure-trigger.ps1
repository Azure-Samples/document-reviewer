# Post-deployment: register SharePoint GetOnNewFileItems for the document review agent.

$ErrorActionPreference = "Stop"
$functionName = "document_review_announcer"
$operationName = "GetOnNewFileItems"
$triggerName = "sharepoint-document-review-on-new-file"
$keyTimeoutSeconds = if ($env:CONNECTOR_KEY_TIMEOUT_SECONDS) {
    [int]$env:CONNECTOR_KEY_TIMEOUT_SECONDS
} else {
    600
}

function Get-OutputValue {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Outputs,
        [Parameter(Mandatory = $true)]
        [string[]]$Names
    )

    foreach ($name in $Names) {
        $property = $Outputs.PSObject.Properties[$name]
        if ($property -and "$($property.Value)".Trim()) {
            return "$($property.Value)".Trim()
        }
    }
    return ""
}

$outputs = azd env get-values --output json | ConvertFrom-Json
$subscriptionId = Get-OutputValue $outputs @("AZURE_SUBSCRIPTION_ID")
$resourceGroup = Get-OutputValue $outputs @("AZURE_RESOURCE_GROUP", "RESOURCE_GROUP")
$functionAppName = Get-OutputValue $outputs @("AZURE_FUNCTION_APP_NAME", "SERVICE_API_NAME")
$connectorNamespace = Get-OutputValue $outputs @("CONNECTOR_NAMESPACE_NAME")
$sharepointConnection = Get-OutputValue $outputs @("SHAREPOINT_CONNECTION_NAME")
$sharepointSiteUrl = Get-OutputValue $outputs @("SHAREPOINT_SITE_URL")
$sharepointLibraryName = Get-OutputValue $outputs @("SHAREPOINT_LIBRARY_NAME")
$sharepointFolderPath = Get-OutputValue $outputs @("SHAREPOINT_FOLDER_PATH")

if (
    -not $subscriptionId -or
    -not $resourceGroup -or
    -not $functionAppName -or
    -not $connectorNamespace -or
    -not $sharepointConnection -or
    -not $sharepointSiteUrl -or
    -not $sharepointLibraryName -or
    -not $sharepointFolderPath
) {
    throw "Required azd outputs are missing. Configure the environment and deploy first."
}

$extension = az extension show --name connector-namespace --query name --output tsv 2>$null
if ($LASTEXITCODE -ne 0 -or -not $extension) {
    throw "The connector-namespace Azure CLI extension is required. Install it from https://aka.ms/connector-namespace-cli-install."
}

az connector-namespace trigger show `
    --resource-group $resourceGroup `
    --namespace $connectorNamespace `
    --name $triggerName `
    --query name `
    --output tsv 2>$null | Out-Null
$triggerExists = $LASTEXITCODE -eq 0
$forceTriggerUpdate = "$($env:FORCE_CONNECTOR_TRIGGER_UPDATE)".Trim() -in @("1", "true", "yes")
if ($triggerExists -and -not $forceTriggerUpdate) {
    Write-Host "SharePoint new-file trigger already exists; leaving its polling state unchanged."
    exit 0
}
$triggerCommand = if ($triggerExists) { "update" } else { "create" }

Write-Host "Waiting for the Function connector extension to finish indexing."
$deadline = (Get-Date).AddSeconds($keyTimeoutSeconds)
$connectorKey = ""
while ((Get-Date) -lt $deadline) {
    $keyResult = az functionapp keys list `
        --resource-group $resourceGroup `
        --name $functionAppName `
        --query systemKeys.connector_extension `
        --output tsv 2>$null
    if ($LASTEXITCODE -eq 0 -and $keyResult) {
        $connectorKey = "$keyResult".Trim()
        break
    }
    Start-Sleep -Seconds 10
}
if (-not $connectorKey) {
    throw "The connector_extension system key was not created in time. Check Function startup logs and retry."
}

$encodedKey = [Uri]::EscapeDataString($connectorKey)
$callbackUrl = "https://${functionAppName}.azurewebsites.net/runtime/webhooks/connector?functionName=${functionName}&code=${encodedKey}"

$connectionFile = New-TemporaryFile
$notificationFile = New-TemporaryFile
$parametersFile = New-TemporaryFile
$metadataFile = New-TemporaryFile
try {
    @{
        connectorName = "sharepointonline"
        connectionName = $sharepointConnection
    } | ConvertTo-Json -Compress | Set-Content -Path $connectionFile -Encoding utf8

    @{
        callbackUrl = $callbackUrl
        httpMethod = "Post"
    } | ConvertTo-Json -Compress | Set-Content -Path $notificationFile -Encoding utf8

    @(
        @{ name = "dataset"; value = $sharepointSiteUrl },
        @{ name = "table"; value = $sharepointLibraryName },
        @{ name = "folderPath"; value = $sharepointFolderPath }
    ) | ConvertTo-Json -Compress | Set-Content -Path $parametersFile -Encoding utf8

    @{
        destinationType = "functionApp"
        functionAppName = $functionAppName
        functionAppResourceGroup = $resourceGroup
        functionAppSubscriptionId = $subscriptionId
        functionName = $functionName
        recurrenceFrequency = "Minute"
        recurrenceInterval = "5"
    } | ConvertTo-Json -Compress | Set-Content -Path $metadataFile -Encoding utf8

    az connector-namespace trigger $triggerCommand `
        --resource-group $resourceGroup `
        --namespace $connectorNamespace `
        --name $triggerName `
        --connection-details "@$($connectionFile.FullName)" `
        --operation-name $operationName `
        --parameters "@$($parametersFile.FullName)" `
        --notification-details "@$($notificationFile.FullName)" `
        --metadata "@$($metadataFile.FullName)" `
        --state Enabled `
        --description "SharePoint GetOnNewFileItems -> document_review_announcer" `
        --output none
    if ($LASTEXITCODE -ne 0) {
        throw "SharePoint trigger registration failed."
    }
} finally {
    Remove-Item `
        $connectionFile, $notificationFile, $parametersFile, $metadataFile `
        -ErrorAction SilentlyContinue
}

Write-Host "SharePoint new-file trigger configured."
Write-Host "Authorize the SharePoint and Teams connections in https://connectors.azure.com/ before testing."
