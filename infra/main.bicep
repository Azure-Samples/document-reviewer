targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the azd environment.')
param environmentName string

@description('Primary region for the Function app, storage, monitoring, Foundry, and Document Intelligence.')
@allowed([
  'eastus2'
])
param location string

@description('Region for preview Connector Namespace resources.')
@allowed([
  'westcentralus'
])
param connectorNamespaceLocation string = 'westcentralus'

@description('Object ID of the interactive deployment user.')
param principalId string

@description('SharePoint site URL monitored by the connector trigger.')
param sharepointSiteUrl string

@description('SharePoint document library monitored by the connector trigger.')
param sharepointLibraryName string = 'Documents'

@description('Required SharePoint folder path, including the document library path.')
param sharepointFolderPath string

@description('Fixed Microsoft Teams team/group ID for announcements.')
param teamsGroupId string

@description('Fixed standard Microsoft Teams channel ID for announcements.')
param teamsChannelId string

@description('Foundry model deployment name.')
param modelDeploymentName string = 'gpt-5.4'

@description('Foundry model catalog name.')
param modelName string = 'gpt-5.4'

@description('Foundry model version.')
param modelVersion string = '2026-03-05'

@minValue(1)
@maxValue(100)
@description('Foundry model capacity in thousands of tokens per minute.')
param modelCapacity int = 10

metadata name = 'Document Reviewer'
metadata description = 'Azure Functions Serverless Agents sample using SharePoint and Teams Connector Namespace connections.'

var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var connectorToken = toLower(uniqueString(subscription().id, environmentName, connectorNamespaceLocation))
var tags = {
  'azd-env-name': environmentName
  application: 'document-review-announcer'
}
var resourceGroupName = '${abbrs.resourcesResourceGroups}${environmentName}'
var functionAppName = '${abbrs.webSitesFunctions}doc-review-${resourceToken}'
var functionPlanName = '${abbrs.webServerFarms}doc-review-${resourceToken}'
var identityName = '${abbrs.managedIdentityUserAssignedIdentities}doc-review-${resourceToken}'
var storageAccountName = '${abbrs.storageStorageAccounts}${resourceToken}'
var logAnalyticsName = '${abbrs.operationalInsightsWorkspaces}doc-review-${resourceToken}'
var applicationInsightsName = '${abbrs.insightsComponents}doc-review-${resourceToken}'
var foundryAccountName = '${abbrs.cognitiveServicesAccounts}doc-review-${resourceToken}'
var foundryProjectName = 'proj-doc-review-${resourceToken}'
var documentIntelligenceName = '${abbrs.cognitiveServicesFormRecognizer}doc-review-${resourceToken}'
var connectorNamespaceName = '${abbrs.connectorNamespaces}doc-review-${connectorToken}'
var sharepointConnectionName = 'sharepoint-document-source'
var teamsConnectionName = 'teams-review-announcements'
var reviewTableName = 'DocumentReviews'
var deploymentStorageContainerName = 'deployment-package'
var storageBlobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
var storageQueueDataContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
var storageTableDataContributorRoleId = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'

resource rg 'Microsoft.Resources/resourceGroups@2024-11-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module identity 'app/identity.bicep' = {
  scope: rg
  name: 'managed-identity'
  params: {
    name: identityName
    location: location
    tags: tags
  }
}

module storage 'br/public:avm/res/storage/storage-account:0.32.0' = {
  scope: rg
  name: 'storage-account'
  params: {
    name: storageAccountName
    location: location
    tags: tags
    skuName: 'Standard_LRS'
    kind: 'StorageV2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
    minimumTlsVersion: 'TLS1_2'
    blobServices: {
      containers: [
        {
          name: deploymentStorageContainerName
          publicAccess: 'None'
        }
      ]
    }
    roleAssignments: [
      {
        roleDefinitionIdOrName: storageBlobDataOwnerRoleId
        principalId: identity.outputs.principalId
        principalType: 'ServicePrincipal'
      }
      {
        roleDefinitionIdOrName: storageQueueDataContributorRoleId
        principalId: identity.outputs.principalId
        principalType: 'ServicePrincipal'
      }
      {
        roleDefinitionIdOrName: storageTableDataContributorRoleId
        principalId: identity.outputs.principalId
        principalType: 'ServicePrincipal'
      }
    ]
  }
}

module reviewTable 'app/review-table.bicep' = {
  scope: rg
  name: 'review-table'
  params: {
    storageAccountName: storage.outputs.name
    tableName: reviewTableName
  }
}

module monitoring 'app/monitoring.bicep' = {
  scope: rg
  name: 'monitoring'
  params: {
    location: location
    tags: tags
    logAnalyticsName: logAnalyticsName
    applicationInsightsName: applicationInsightsName
  }
}

module foundry 'app/foundry.bicep' = {
  scope: rg
  name: 'foundry'
  params: {
    accountName: foundryAccountName
    projectName: foundryProjectName
    location: location
    tags: tags
    modelDeploymentName: modelDeploymentName
    modelName: modelName
    modelVersion: modelVersion
    deploymentCapacity: modelCapacity
    managedIdentityPrincipalId: identity.outputs.principalId
  }
}

module documentIntelligence 'app/document-intelligence.bicep' = {
  scope: rg
  name: 'document-intelligence'
  params: {
    name: documentIntelligenceName
    location: location
    tags: tags
    managedIdentityPrincipalId: identity.outputs.principalId
  }
}

module connectors 'app/connector-namespace.bicep' = {
  scope: rg
  name: 'connector-namespace'
  params: {
    name: connectorNamespaceName
    location: connectorNamespaceLocation
    tags: tags
    sharepointConnectionName: sharepointConnectionName
    teamsConnectionName: teamsConnectionName
    functionPrincipalId: identity.outputs.principalId
    deployerPrincipalId: principalId
    tenantId: tenant().tenantId
  }
}

module functionPlan 'app/plan.bicep' = {
  scope: rg
  name: 'flex-consumption-plan'
  params: {
    name: functionPlanName
    location: location
    tags: tags
  }
}

module rbac 'app/rbac.bicep' = {
  scope: rg
  name: 'rbac'
  params: {
    appInsightsName: monitoring.outputs.applicationInsightsName
    managedIdentityPrincipalId: identity.outputs.principalId
  }
}

module functionApp 'app/api.bicep' = {
  scope: rg
  name: 'function-app'
  params: {
    name: functionAppName
    location: location
    tags: tags
    applicationInsightsName: monitoring.outputs.applicationInsightsName
    appServicePlanId: functionPlan.outputs.id
    storageAccountName: storage.outputs.name
    deploymentStorageContainerName: deploymentStorageContainerName
    maximumInstanceCount: 10
    instanceMemoryMB: 2048
    runtimeName: 'python'
    runtimeVersion: '3.13'
    identityId: identity.outputs.id
    identityClientId: identity.outputs.clientId
    appSettings: {
      AZURE_FUNCTIONS_AGENTS_PROVIDER: 'foundry'
      FOUNDRY_PROJECT_ENDPOINT: foundry.outputs.projectEndpoint
      FOUNDRY_MODEL: foundry.outputs.modelDeploymentName
      AZURE_CLIENT_ID: identity.outputs.clientId
      AZURE_FUNCTIONS_AGENTS_REASONING_EFFORT: 'medium'
      AZURE_FUNCTIONS_AGENTS_REASONING_SUMMARY: 'concise'
      SHAREPOINT_SITE_URL: sharepointSiteUrl
      SHAREPOINT_LIBRARY_NAME: sharepointLibraryName
      SHAREPOINT_FOLDER_PATH: sharepointFolderPath
      SHAREPOINTONLINE_CONNECTION_RUNTIME_URL: connectors.outputs.sharepointConnectionRuntimeUrl
      TEAMS_CONNECTION_RUNTIME_URL: connectors.outputs.teamsConnectionRuntimeUrl
      TEAMS_GROUP_ID: teamsGroupId
      TEAMS_CHANNEL_ID: teamsChannelId
      DOCUMENT_INTELLIGENCE_ENDPOINT: documentIntelligence.outputs.endpoint
      DOCUMENT_REVIEW_TABLE_ENDPOINT: reviewTable.outputs.endpoint
      DOCUMENT_REVIEW_TABLE_NAME: reviewTable.outputs.name
      PYTHON_ENABLE_INIT_INDEXING: '1'
      ENABLE_MULTIPLATFORM_BUILD: 'true'
      ENABLE_SENSITIVE_DATA: 'false'
    }
  }
  dependsOn: [
    rbac
  ]
}

output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.applicationInsightsConnectionString
output AZURE_CLIENT_ID string = identity.outputs.clientId
output AZURE_FUNCTION_APP_NAME string = functionApp.outputs.SERVICE_API_NAME
output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_TENANT_ID string = tenant().tenantId
output CONNECTOR_NAMESPACE_LOCATION string = connectorNamespaceLocation
output CONNECTOR_NAMESPACE_NAME string = connectors.outputs.name
output DOCUMENT_INTELLIGENCE_ENDPOINT string = documentIntelligence.outputs.endpoint
output DOCUMENT_REVIEW_TABLE_ENDPOINT string = reviewTable.outputs.endpoint
output DOCUMENT_REVIEW_TABLE_NAME string = reviewTable.outputs.name
output FOUNDRY_MODEL string = foundry.outputs.modelDeploymentName
output FOUNDRY_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output RESOURCE_GROUP string = rg.name
output SERVICE_API_NAME string = functionApp.outputs.SERVICE_API_NAME
output SERVICE_API_URI string = 'https://${functionApp.outputs.SERVICE_API_HOSTNAME}'
output SHAREPOINT_CONNECTION_NAME string = connectors.outputs.sharepointConnectionName
output SHAREPOINT_FOLDER_PATH string = sharepointFolderPath
output SHAREPOINT_LIBRARY_NAME string = sharepointLibraryName
output SHAREPOINT_SITE_URL string = sharepointSiteUrl
output STORAGE_ACCOUNT_NAME string = storage.outputs.name
output TEAMS_CHANNEL_ID string = teamsChannelId
output TEAMS_CONNECTION_NAME string = connectors.outputs.teamsConnectionName
output TEAMS_GROUP_ID string = teamsGroupId
