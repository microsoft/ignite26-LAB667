param name string
param serviceName string
param location string
param tags object
param environmentId string
param registryEndpoint string
param registryUsername string

@secure()
param registryPassword string

param image string
param port int
param env array

@secure()
param secrets object

var appSecrets = [for secret in items(secrets): {
  name: secret.key
  value: secrets[secret.key]
}]

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: union(tags, {
    'azd-service-name': serviceName
  })
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        allowInsecure: false
        targetPort: port
        transport: 'auto'
      }
      registries: [
        {
          server: registryEndpoint
          username: registryUsername
          passwordSecretRef: 'registry-password'
        }
      ]
      secrets: concat(appSecrets, [
        {
          name: 'registry-password'
          value: registryPassword
        }
      ])
    }
    template: {
      containers: [
        {
          name: serviceName
          image: empty(image) ? 'mcr.microsoft.com/dotnet/samples:aspnetapp' : image
          env: concat(env, [
            {
              // The provisioning placeholder must listen on the real service port.
              name: 'ASPNETCORE_HTTP_PORTS'
              value: string(port)
            }
          ])
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

output name string = app.name
output url string = 'https://${app.properties.configuration.ingress.fqdn}'
