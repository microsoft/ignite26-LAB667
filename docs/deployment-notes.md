# Deployment notes

For shared-service prerequisites, deployment commands, and access limitations,
see the [infrastructure guide](../infra/README.md). Attendee model access and
the Azure AI Search knowledge base are configured separately, as described in
the [workshop overview](workshop-overview.md).

## City-guide storage access

When Azure AI Search accesses city-guide blobs through a managed identity,
that identity needs the **Storage Blob Data Reader** role on the storage
containing the guide. See [managed identity access to Azure Storage](https://learn.microsoft.com/azure/search/search-howto-managed-identities-storage).
