@minLength(1)
param name string

@minLength(1)
param location string

param tags object = {}

resource plan 'Microsoft.Web/serverfarms@2024-11-01' = {
  name: name
  location: location
  tags: tags
  kind: 'functionapp'
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  properties: {
    reserved: true
  }
}

output id string = plan.id
output name string = plan.name
