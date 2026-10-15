// ===============================================
// Creates: Microsoft Foundry (Account + Project)
// ===============================================

@description('The location where all resources will be deployed')
//param location string = 'swedencentral'
param location string = 'centralus'

@description('Public zip file containing the city guide content to upload into blob storage')
param cityGuideZipUrl string = 'https://lab667.blob.core.windows.net/cityguides/city-guide.zip'

@description('Bump this value to force the city guide upload deployment script to run again')
param cityGuideUploadForceUpdateTag string = 'v2'

// Variables for resource naming and configuration
var uniqueSuffix = uniqueString(resourceGroup().id)

var resourceNames = {
  microsoftFoundry: 'foundry-${uniqueSuffix}'
  microsoftFoundryProject: 'foundry-project-${uniqueSuffix}'
  searchService: 'search-${uniqueSuffix}'
  storageAccount: 'stor${uniqueSuffix}'
  cityGuideContainer: 'city-guide'
  cityGuideUploadIdentity: 'city-guide-upload-${uniqueSuffix}'
  cityGuideUploadScript: 'city-guide-upload-${uniqueSuffix}'
}

// ===============================================
// MICROSOFT FOUNDRY (Account + Project)
// ===============================================

@description('Microsoft Foundry account')
resource microsoftFoundryAccount 'Microsoft.CognitiveServices/accounts@2025-10-01-preview' = {
  name: resourceNames.microsoftFoundry
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: resourceNames.microsoftFoundry
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
    networkAcls: {
      defaultAction: 'Allow'
      virtualNetworkRules: []
      ipRules: []
    }
  }
  identity: {
    type: 'SystemAssigned'
  }
}

@description('Microsoft Foundry project')
resource microsoftFoundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-10-01-preview' = {
  parent: microsoftFoundryAccount
  name: resourceNames.microsoftFoundryProject
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

@description('gpt-5.6-luna model deployment')
resource llmModelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-10-01-preview' = {
  parent: microsoftFoundryAccount
  name: 'gpt-5.6-luna'
  dependsOn: [
    microsoftFoundryProject
  ]
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5.6-luna'
      version: '2026-07-09'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  sku: {
    name: 'GlobalStandard'
    capacity: 50
  }
}

@description('gpt-4.1-mini model deployment')
resource llmModelDeployment2 'Microsoft.CognitiveServices/accounts/deployments@2025-10-01-preview' = {
  parent: microsoftFoundryAccount
  name: 'gpt-4.1-mini'
  dependsOn: [
    llmModelDeployment
  ]
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4.1-mini'
      version: '2025-04-14'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  sku: {
    name: 'GlobalStandard'
    capacity: 50
  }
}

@description('text-embedding-3-small model deployment')
resource llmModelDeployment3 'Microsoft.CognitiveServices/accounts/deployments@2025-10-01-preview' = {
  parent: microsoftFoundryAccount
  name: 'text-embedding-3-small'
  dependsOn: [
    llmModelDeployment2
  ]
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-small'
      version: '1'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  sku: {
    name: 'GlobalStandard'
    capacity: 50
  }
}




// ===============================================
// AZURE AI SEARCH (backing store for Foundry IQ)
// ===============================================
@description('Azure AI Search service for Foundry IQ knowledge bases')
resource searchService 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: resourceNames.searchService
  location: location
  sku: {
    name: 'standard'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    semanticSearch: 'standard'
    publicNetworkAccess: 'enabled'
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http403'
      }
    }
  }
}

// ===============================================
// AZURE STORAGE (blob store for Foundry data)
// ===============================================

@description('Storage account for blob storage')
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: resourceNames.storageAccount
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      virtualNetworkRules: []
      ipRules: []
    }
  }
}

@description('Blob service for the storage account')
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
  properties: {}
}

@description('Blob container for city guide knowledge source files')
resource cityGuideContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: resourceNames.cityGuideContainer
  properties: {
    publicAccess: 'None'
  }
}

@description('Managed identity used to run the city guide upload deployment script')
resource cityGuideUploadIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: resourceNames.cityGuideUploadIdentity
  location: location
}

// ===============================================
// ROLE ASSIGNMENTS
// ===============================================

// An inline deployment keeps this file self-contained and resolves principal IDs before naming assignments.
#disable-next-line no-deployments-resources
resource roleAssignments 'Microsoft.Resources/deployments@2022-09-01' = {
  name: 'role-assignments-${uniqueString(deployment().name)}'
  properties: {
    mode: 'Incremental'
    expressionEvaluationOptions: {
      scope: 'inner'
    }
    parameters: {
      microsoftFoundryAccountName: {
        value: microsoftFoundryAccount.name
      }
      searchServiceName: {
        value: searchService.name
      }
      storageAccountName: {
        value: storageAccount.name
      }
      searchPrincipalId: {
        value: searchService.identity.principalId
      }
      projectPrincipalId: {
        value: microsoftFoundryProject.identity.principalId
      }
    }
    // Keep an object here: ARM deserializes template before evaluating expressions.
    // With inner scope, deployment() refers to this nested deployment. ARM exposes
    // its parameter values, but Bicep's deployment() type does not include them.
    template: {
      '$schema': 'https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#'
      contentVersion: '1.0.0.0'
      parameters: {
        microsoftFoundryAccountName: { type: 'string' }
        searchServiceName: { type: 'string' }
        storageAccountName: { type: 'string' }
        searchPrincipalId: { type: 'string' }
        projectPrincipalId: { type: 'string' }
      }
      resources: [
        {
          type: 'Microsoft.Authorization/roleAssignments'
          apiVersion: '2022-04-01'
          name: guid(
            resourceId('Microsoft.CognitiveServices/accounts', any(deployment()).properties.parameters.microsoftFoundryAccountName.value),
            any(deployment()).properties.parameters.searchPrincipalId.value,
            subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')
          )
          scope: resourceId('Microsoft.CognitiveServices/accounts', any(deployment()).properties.parameters.microsoftFoundryAccountName.value)
          properties: {
            roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')
            principalId: any(deployment()).properties.parameters.searchPrincipalId.value
            principalType: 'ServicePrincipal'
          }
        }
        {
          type: 'Microsoft.Authorization/roleAssignments'
          apiVersion: '2022-04-01'
          name: guid(
            resourceGroup().id,
            any(deployment()).properties.parameters.searchPrincipalId.value,
            subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1')
          )
          properties: {
            roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1')
            principalId: any(deployment()).properties.parameters.searchPrincipalId.value
            principalType: 'ServicePrincipal'
          }
        }
        {
          type: 'Microsoft.Authorization/roleAssignments'
          apiVersion: '2022-04-01'
          name: guid(
            resourceId('Microsoft.Search/searchServices', any(deployment()).properties.parameters.searchServiceName.value),
            any(deployment()).properties.parameters.projectPrincipalId.value,
            subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')
          )
          scope: resourceId('Microsoft.Search/searchServices', any(deployment()).properties.parameters.searchServiceName.value)
          properties: {
            roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')
            principalId: any(deployment()).properties.parameters.projectPrincipalId.value
            principalType: 'ServicePrincipal'
          }
        }
        {
          type: 'Microsoft.Authorization/roleAssignments'
          apiVersion: '2022-04-01'
          name: guid(
            resourceId('Microsoft.Search/searchServices', any(deployment()).properties.parameters.searchServiceName.value),
            any(deployment()).properties.parameters.projectPrincipalId.value,
            subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0')
          )
          scope: resourceId('Microsoft.Search/searchServices', any(deployment()).properties.parameters.searchServiceName.value)
          properties: {
            roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0')
            principalId: any(deployment()).properties.parameters.projectPrincipalId.value
            principalType: 'ServicePrincipal'
          }
        }
        {
          type: 'Microsoft.Authorization/roleAssignments'
          apiVersion: '2022-04-01'
          name: guid(
            resourceId('Microsoft.Storage/storageAccounts', any(deployment()).properties.parameters.storageAccountName.value),
            any(deployment()).properties.parameters.projectPrincipalId.value,
            subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
          )
          scope: resourceId('Microsoft.Storage/storageAccounts', any(deployment()).properties.parameters.storageAccountName.value)
          properties: {
            roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
            principalId: any(deployment()).properties.parameters.projectPrincipalId.value
            principalType: 'ServicePrincipal'
          }
        }
      ]
    }
  }
}

@description('Downloads the city guide zip and uploads the extracted files into the city-guide blob container')
resource uploadCityGuideContent 'Microsoft.Resources/deploymentScripts@2023-08-01' = {
  name: resourceNames.cityGuideUploadScript
  location: location
  kind: 'AzureCLI'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${cityGuideUploadIdentity.id}': {}
    }
  }
  properties: {
    azCliVersion: '2.60.0'
    cleanupPreference: 'OnSuccess'
    retentionInterval: 'P1D'
    timeout: 'PT30M'
    forceUpdateTag: '${cityGuideZipUrl}-${cityGuideUploadForceUpdateTag}'
    environmentVariables: [
      {
        name: 'CITY_GUIDE_ZIP_URL'
        value: cityGuideZipUrl
      }
      {
        name: 'STORAGE_ACCOUNT_NAME'
        value: storageAccount.name
      }
      {
        name: 'BLOB_CONTAINER_NAME'
        value: cityGuideContainer.name
      }
      {
        name: 'STORAGE_ACCOUNT_KEY'
        secureValue: storageAccount.listKeys().keys[0].value
      }
    ]
    scriptContent: '''
set -e

work_dir="/tmp/city-guide-content"
rm -rf "$work_dir"
mkdir -p "$work_dir/extracted"
export WORK_DIR="$work_dir"

python3 - <<'PY'
import os
import urllib.request
import zipfile

work_dir = os.environ["WORK_DIR"]
zip_url = os.environ["CITY_GUIDE_ZIP_URL"]
zip_path = os.path.join(work_dir, "city-guide.zip")
extract_dir = os.path.join(work_dir, "extracted")

urllib.request.urlretrieve(zip_url, zip_path)

extract_root = os.path.abspath(extract_dir)
with zipfile.ZipFile(zip_path) as archive:
    for member in archive.infolist():
        target = os.path.abspath(os.path.join(extract_dir, member.filename))
        if target != extract_root and not target.startswith(extract_root + os.sep):
            raise RuntimeError(f"Unsafe zip entry: {member.filename}")
    archive.extractall(extract_dir)
PY

az storage blob upload-batch \
  --account-name "$STORAGE_ACCOUNT_NAME" \
  --account-key "$STORAGE_ACCOUNT_KEY" \
  --destination "$BLOB_CONTAINER_NAME" \
  --source "$work_dir/extracted" \
  --overwrite true
'''
  }
}



// Add this output
@description('Azure AI Search endpoint for Foundry IQ knowledge bases')
output AZURE_SEARCH_ENDPOINT string = 'https://${searchService.name}.search.windows.net'

@description('Storage account blob endpoint')
output AZURE_STORAGE_BLOB_ENDPOINT string = storageAccount.properties.primaryEndpoints.blob

@description('Microsoft Foundry project endpoint in SDK format')
output MICROSOFT_FOUNDRY_PROJECT_ENDPOINT string = 'https://${microsoftFoundryAccount.name}.services.ai.azure.com/api/projects/${microsoftFoundryProject.name}'

@description('Microsoft Foundry project resource ID')
output MICROSOFT_FOUNDRY_PROJECT_ID string = microsoftFoundryProject.id

@description('Azure tenant ID for authentication flows')
output AZURE_TENANT_ID string = tenant().tenantId
