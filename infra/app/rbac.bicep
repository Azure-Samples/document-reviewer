param appInsightsName string
param managedIdentityPrincipalId string

var monitoringMetricsPublisherRoleId = '3913510d-42f4-4e42-8a64-420c390055eb'

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource monitoringPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(
    applicationInsights.id,
    managedIdentityPrincipalId,
    monitoringMetricsPublisherRoleId
  )
  scope: applicationInsights
  properties: {
    roleDefinitionId: resourceId(
      'Microsoft.Authorization/roleDefinitions',
      monitoringMetricsPublisherRoleId
    )
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}
