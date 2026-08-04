@minLength(1)
param name string

@minLength(1)
param location string

param tags object = {}

@minLength(1)
param sharepointConnectionName string

@minLength(1)
param teamsConnectionName string

@minLength(1)
param functionPrincipalId string

param deployerPrincipalId string = ''

@minLength(1)
param tenantId string

resource connectorNamespace 'Microsoft.Web/connectorGateways@2026-05-01-preview' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

resource sharepointConnection 'Microsoft.Web/connectorGateways/connections@2026-05-01-preview' = {
  parent: connectorNamespace
  name: sharepointConnectionName
  properties: {
    connectorName: 'sharepointonline'
    displayName: 'SharePoint document review source'
  }
}

resource teamsConnection 'Microsoft.Web/connectorGateways/connections@2026-05-01-preview' = {
  parent: connectorNamespace
  name: teamsConnectionName
  properties: {
    connectorName: 'teams'
    displayName: 'Microsoft Teams document review announcements'
  }
}

resource sharepointNamespaceAccessPolicy 'Microsoft.Web/connectorGateways/connections/accessPolicies@2026-05-01-preview' = {
  parent: sharepointConnection
  name: 'namespace-trigger'
  properties: {
    principal: {
      type: 'ActiveDirectory'
      identity: {
        objectId: connectorNamespace.identity.principalId
        tenantId: tenantId
      }
    }
  }
}

resource sharepointFunctionAccessPolicy 'Microsoft.Web/connectorGateways/connections/accessPolicies@2026-05-01-preview' = {
  parent: sharepointConnection
  name: 'functionapp-mi'
  properties: {
    principal: {
      type: 'ActiveDirectory'
      identity: {
        objectId: functionPrincipalId
        tenantId: tenantId
      }
    }
  }
}

resource teamsFunctionAccessPolicy 'Microsoft.Web/connectorGateways/connections/accessPolicies@2026-05-01-preview' = {
  parent: teamsConnection
  name: 'functionapp-mi'
  properties: {
    principal: {
      type: 'ActiveDirectory'
      identity: {
        objectId: functionPrincipalId
        tenantId: tenantId
      }
    }
  }
}

resource sharepointDeployerAccessPolicy 'Microsoft.Web/connectorGateways/connections/accessPolicies@2026-05-01-preview' = if (!empty(deployerPrincipalId)) {
  parent: sharepointConnection
  name: 'deployer'
  properties: {
    principal: {
      type: 'ActiveDirectory'
      identity: {
        objectId: deployerPrincipalId
        tenantId: tenantId
      }
    }
  }
}

resource teamsDeployerAccessPolicy 'Microsoft.Web/connectorGateways/connections/accessPolicies@2026-05-01-preview' = if (!empty(deployerPrincipalId)) {
  parent: teamsConnection
  name: 'deployer'
  properties: {
    principal: {
      type: 'ActiveDirectory'
      identity: {
        objectId: deployerPrincipalId
        tenantId: tenantId
      }
    }
  }
}

output name string = connectorNamespace.name
output principalId string = connectorNamespace.identity.principalId
output sharepointConnectionName string = sharepointConnection.name
output sharepointConnectionRuntimeUrl string = sharepointConnection.properties.connectionRuntimeUrl
output teamsConnectionName string = teamsConnection.name
output teamsConnectionRuntimeUrl string = teamsConnection.properties.connectionRuntimeUrl
