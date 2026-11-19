targetScope = 'subscription'

@minLength(1)
@maxLength(64)
param environmentName string

@description('Region for the shared services.')
param location string

@description('Model region; defaults to the shared-services region.')
param modelLocation string = ''

param modelName string = 'gpt-5.6-luna'
param modelVersion string = '2026-07-09'
param modelSku string = 'GlobalStandard'

@minValue(1)
@description('Model capacity units, subject to the selected model and subscription quota.')
param modelCapacity int = 100

@description('Image references saved by azd after publishing. Empty on the first deployment.')
param mcpImage string = ''
param dashboardImage string = ''
param adminImage string = ''
param agent42Image string = ''

var tags = {
  'azd-env-name': environmentName
}

resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module services './shared-services.bicep' = {
  name: 'shared-services'
  scope: rg
  params: {
    location: location
    tags: tags
    modelLocation: empty(modelLocation) ? location : modelLocation
    modelName: modelName
    modelVersion: modelVersion
    modelSku: modelSku
    modelCapacity: modelCapacity
    mcpImage: mcpImage
    dashboardImage: dashboardImage
    adminImage: adminImage
    agent42Image: agent42Image
  }
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = services.outputs.registryEndpoint
output AZURE_CONTAINER_APPS_ENVIRONMENT_NAME string = services.outputs.environmentName
output SERVICE_MCP_NAME string = services.outputs.mcpName
output SERVICE_DASHBOARD_NAME string = services.outputs.dashboardName
output SERVICE_ADMIN_NAME string = services.outputs.adminName
output SERVICE_AGENT42_NAME string = services.outputs.agent42Name
output GAME_MCP_URL string = '${services.outputs.mcpUrl}/san-francisco/mcp'
output GAME_SERVER_URL string = services.outputs.mcpUrl
output DASHBOARD_URL string = '${services.outputs.dashboardUrl}/san-francisco/dashboard'
output ADMIN_URL string = services.outputs.adminUrl
output AGENT42_URL string = services.outputs.agent42Url
output AGENT42_CARD_URL string = '${services.outputs.agent42Url}/.well-known/agent-card.json'
