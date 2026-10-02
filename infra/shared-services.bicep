param location string
param tags object
param modelLocation string
param modelName string
param modelVersion string
param modelSku string
param modelCapacity int
param mcpImage string
param dashboardImage string
param adminImage string
param agent42Image string

var token = uniqueString(resourceGroup().id)
var mcpName = 'mcp-${token}'
var dashboardName = 'dashboard-${token}'
var adminName = 'admin-${token}'
var agent42Name = 'agent42-${token}'
var routesContainerName = 'agent42-routes'

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'acr${token}'
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'logs-${token}'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource containerEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${token}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${token}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowSharedKeyAccess: true
    // Existing clients and the dashboard read route PNG/JSON URLs anonymously.
    allowBlobPublicAccess: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource routes 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: routesContainerName
  properties: {
    publicAccess: 'Blob'
  }
}

resource maps 'Microsoft.Maps/accounts@2023-06-01' = {
  name: 'maps-${token}'
  location: 'global'
  tags: tags
  sku: {
    name: 'G2'
  }
  properties: {
    disableLocalAuth: false
  }
}

resource openai 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: 'aoai-${token}'
  location: modelLocation
  tags: tags
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: 'aoai-${token}'
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
  }
}

resource model 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: openai
  name: 'agent42'
  sku: {
    name: modelSku
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
    versionUpgradeOption: 'OnceCurrentVersionExpired'
  }
}

var storageConnection = 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'
var tableEnv = [
  {
    name: 'AZURE_TABLES_CONNECTION_STRING'
    secretRef: 'storage-connection'
  }
  {
    name: 'DEFAULT_GAME_SLUG'
    value: 'san-francisco'
  }
  {
    name: 'DEFAULT_GAME_NAME'
    value: 'Lost in San Francisco'
  }
]
var tableSecrets = {
  'storage-connection': storageConnection
}

module mcp './container-app.bicep' = {
  name: 'mcp'
  params: {
    name: mcpName
    serviceName: 'mcp'
    location: location
    tags: tags
    environmentId: containerEnvironment.id
    registryEndpoint: registry.properties.loginServer
    registryUsername: registry.name
    registryPassword: registry.listCredentials().passwords[0].value
    image: mcpImage
    port: 8000
    env: concat(tableEnv, [
      {
        name: 'MCP_HOST'
        value: '0.0.0.0'
      }
      {
        name: 'MCP_PORT'
        value: '8000'
      }
    ])
    secrets: tableSecrets
  }
}

module dashboard './container-app.bicep' = {
  name: 'dashboard'
  params: {
    name: dashboardName
    serviceName: 'dashboard'
    location: location
    tags: tags
    environmentId: containerEnvironment.id
    registryEndpoint: registry.properties.loginServer
    registryUsername: registry.name
    registryPassword: registry.listCredentials().passwords[0].value
    image: dashboardImage
    port: 8090
    env: concat(tableEnv, [
      {
        name: 'DASHBOARD_HOST'
        value: '0.0.0.0'
      }
      {
        name: 'DASHBOARD_PORT'
        value: '8090'
      }
      {
        name: 'AZURE_MAPS_KEY'
        secretRef: 'maps-key'
      }
      {
        name: 'MOVE_ROUTES_BASE_URL'
        value: '${storage.properties.primaryEndpoints.blob}${routes.name}'
      }
      {
        name: 'MOVE_BLOB_CONTAINER'
        value: routesContainerName
      }
    ])
    secrets: union(tableSecrets, {
      'maps-key': maps.listKeys().primaryKey
    })
  }
}

module admin './container-app.bicep' = {
  name: 'admin'
  params: {
    name: adminName
    serviceName: 'admin'
    location: location
    tags: tags
    environmentId: containerEnvironment.id
    registryEndpoint: registry.properties.loginServer
    registryUsername: registry.name
    registryPassword: registry.listCredentials().passwords[0].value
    image: adminImage
    port: 8080
    env: concat(tableEnv, [
      {
        name: 'ADMIN_PORT'
        value: '8080'
      }
      {
        name: 'ADMIN_COOKIE_SECURE'
        value: 'true'
      }
      {
        name: 'AZURE_MAPS_KEY'
        secretRef: 'maps-key'
      }
      {
        name: 'GAME_SERVER_URL'
        value: mcp.outputs.url
      }
      {
        name: 'DASHBOARD_URL'
        value: dashboard.outputs.url
      }
    ])
    secrets: union(tableSecrets, {
      'maps-key': maps.listKeys().primaryKey
    })
  }
}

module agent42 './container-app.bicep' = {
  name: 'agent42'
  params: {
    name: agent42Name
    serviceName: 'agent42'
    location: location
    tags: tags
    environmentId: containerEnvironment.id
    registryEndpoint: registry.properties.loginServer
    registryUsername: registry.name
    registryPassword: registry.listCredentials().passwords[0].value
    image: agent42Image
    port: 8042
    env: [
      {
        name: 'AGENT42_HOST'
        value: '0.0.0.0'
      }
      {
        name: 'AGENT42_PORT'
        value: '8042'
      }
      {
        name: 'AGENT42_PUBLIC_URL'
        value: 'https://${agent42Name}.${containerEnvironment.properties.defaultDomain}/'
      }
      {
        name: 'AGENT42_GEOCODE_BIAS'
        value: '-122.4194,37.7749'
      }
      {
        name: 'AZURE_OPENAI_ENDPOINT'
        value: openai.properties.endpoint
      }
      {
        name: 'AZURE_OPENAI_DEPLOYMENT_NAME'
        value: model.name
      }
      {
        name: 'AZURE_OPENAI_API_KEY'
        secretRef: 'openai-key'
      }
      {
        name: 'AZURE_MAPS_KEY'
        secretRef: 'maps-key'
      }
      {
        name: 'AGENT42_BLOB_CONNECTION_STRING'
        secretRef: 'storage-connection'
      }
      {
        name: 'AGENT42_BLOB_CONTAINER'
        value: routes.name
      }
    ]
    secrets: {
      'openai-key': openai.listKeys().key1
      'maps-key': maps.listKeys().primaryKey
      'storage-connection': storageConnection
    }
  }
}

output registryEndpoint string = registry.properties.loginServer
output environmentName string = containerEnvironment.name
output mcpName string = mcp.outputs.name
output dashboardName string = dashboard.outputs.name
output adminName string = admin.outputs.name
output agent42Name string = agent42.outputs.name
output mcpUrl string = mcp.outputs.url
output dashboardUrl string = dashboard.outputs.url
output adminUrl string = admin.outputs.url
output agent42Url string = agent42.outputs.url
