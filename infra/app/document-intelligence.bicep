param name string
param location string = resourceGroup().location
param tags object = {}
param managedIdentityPrincipalId string

var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'

resource documentIntelligence 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: name
  location: location
  kind: 'FormRecognizer'
  sku: {
    name: 'S0'
  }
  tags: tags
  properties: {
    customSubDomainName: name
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource documentIntelligenceUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(
    documentIntelligence.id,
    managedIdentityPrincipalId,
    cognitiveServicesUserRoleId
  )
  scope: documentIntelligence
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      cognitiveServicesUserRoleId
    )
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output endpoint string = 'https://${name}.cognitiveservices.azure.com'
output name string = documentIntelligence.name
