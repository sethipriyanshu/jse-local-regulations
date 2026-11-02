// JSE Local Regulations: all Azure resources for one environment (dev or prod).
//
// What gets created:
//   - Log Analytics + Container Apps environment
//   - Container Registry (images pulled through a managed identity)
//   - Storage account with a private blob container for snapshots and exports
//   - Azure SQL logical server + serverless database (auto-pauses when idle)
//   - Container App "api" (FastAPI and the built frontend, scales to zero)
//   - Container Apps Job "worker" (daily monitor on a cron)
//   - Container Apps Job "migrate" (manual trigger; run on every deploy)
//
// Deploy with scripts/deploy.sh (see infra/README.md).

targetScope = 'resourceGroup'

@description('Short environment name used in resource names.')
@allowed(['dev', 'prod'])
param env string = 'dev'

param location string = resourceGroup().location

@description('Image tag to run. The first deploy uses a public placeholder until our image is pushed.')
param image string = 'mcr.microsoft.com/k8se/quickstart:latest'

@description('SQL administrator login for the logical server.')
param sqlAdminLogin string = 'jseregsadmin'

@secure()
param sqlAdminPassword string

@secure()
@description('Shared passcode for the admin view (MVP stand-in for login).')
param adminPasscode string

@secure()
param sessionSecret string = newGuid()

@description('Daily monitor schedule, UTC cron. 11:00 UTC = 6 AM Eastern (standard time).')
param dailyCron string = '0 11 * * *'

var prefix = 'jseregs-${env}'
var compact = replace(prefix, '-', '')
var suffix = uniqueString(resourceGroup().id)
var dbName = 'jse_regs'
// The placeholder image listens on 80; ours on 8000. Jobs are not run until our image is set.
var usesOurImage = !startsWith(image, 'mcr.microsoft.com/')

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-id'
  location: location
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: take('${compact}${suffix}', 50)
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

// AcrPull for the app identity.
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, identity.id, 'acrpull')
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: take('${compact}${suffix}', 24)
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'regs'
}

resource sqlServer 'Microsoft.Sql/servers@2023-08-01-preview' = {
  name: '${prefix}-sql-${suffix}'
  location: location
  properties: {
    administratorLogin: sqlAdminLogin
    administratorLoginPassword: sqlAdminPassword
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
  }
}

// Allows traffic from Azure services (Container Apps). Add your own IP in the
// portal if you want to connect from a laptop.
resource sqlAllowAzure 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = {
  parent: sqlServer
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

resource sqlDb 'Microsoft.Sql/servers/databases@2023-08-01-preview' = {
  parent: sqlServer
  name: dbName
  location: location
  sku: { name: 'GP_S_Gen5', tier: 'GeneralPurpose', family: 'Gen5', capacity: 1 }
  properties: {
    autoPauseDelay: 60
    minCapacity: json('0.5')
    maxSizeBytes: 34359738368 // 32 GB
  }
}

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

var databaseUrl = 'mssql+pymssql://${sqlAdminLogin}:${uriComponent(sqlAdminPassword)}@${sqlServer.properties.fullyQualifiedDomainName}:1433/${dbName}'
var storageConn = 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'

var secrets = [
  { name: 'database-url', value: databaseUrl }
  { name: 'storage-conn', value: storageConn }
  { name: 'admin-passcode', value: adminPasscode }
  { name: 'session-secret', value: sessionSecret }
]

var appEnv = [
  { name: 'ENV', value: env }
  { name: 'DATABASE_URL', secretRef: 'database-url' }
  { name: 'STORAGE_CONNECTION_STRING', secretRef: 'storage-conn' }
  { name: 'ADMIN_PASSCODE', secretRef: 'admin-passcode' }
  { name: 'SESSION_SECRET', secretRef: 'session-secret' }
]

var registries = [ { server: acr.properties.loginServer, identity: identity.id } ]

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-api'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  dependsOn: [acrPull]
  properties: {
    managedEnvironmentId: cae.id
    configuration: {
      ingress: { external: true, targetPort: usesOurImage ? 8000 : 80, transport: 'auto' }
      secrets: secrets
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'api'
          image: image
          env: appEnv
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 2 }
    }
  }
}

resource worker 'Microsoft.App/jobs@2024-03-01' = {
  name: '${prefix}-worker'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  dependsOn: [acrPull]
  properties: {
    environmentId: cae.id
    configuration: {
      triggerType: 'Schedule'
      scheduleTriggerConfig: { cronExpression: dailyCron, parallelism: 1, replicaCompletionCount: 1 }
      replicaTimeout: 3600
      replicaRetryLimit: 1
      secrets: secrets
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'worker'
          image: image
          command: ['python', '-m', 'app.worker', 'daily']
          env: appEnv
          resources: { cpu: json('1.0'), memory: '2Gi' }
        }
      ]
    }
  }
}

resource migrate 'Microsoft.App/jobs@2024-03-01' = {
  name: '${prefix}-migrate'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  dependsOn: [acrPull]
  properties: {
    environmentId: cae.id
    configuration: {
      triggerType: 'Manual'
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      replicaTimeout: 600
      replicaRetryLimit: 0
      secrets: secrets
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'migrate'
          image: image
          command: ['python', '-m', 'app.bootstrap']
          env: appEnv
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
    }
  }
}

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output apiName string = api.name
output workerJobName string = worker.name
output migrateJobName string = migrate.name
output appUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output sqlServerFqdn string = sqlServer.properties.fullyQualifiedDomainName
