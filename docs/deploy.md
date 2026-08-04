# Deploy to Azure

Back to the [README](../README.md).

`azd up` provisions the Azure resources, packages the Python Function app,
deploys it, registers the SharePoint trigger, and generates synthetic documents.
Customer-managed Microsoft 365 authorization remains a separate step.

## Prerequisites

- An Azure subscription with permission to create resources and role assignments
- [Azure Developer CLI (`azd`)](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd)
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)
- [uv](https://docs.astral.sh/uv/) and Python 3.13
- `jq` on macOS/Linux for the postdeploy trigger script
- A least-privileged Microsoft 365 identity that can read the selected
  SharePoint folder and post to the selected Teams channel

Install the preview Connector Namespace extension:

```bash
# macOS / Linux
curl -fsSL https://aka.ms/connector-namespace-cli-install | bash
```

```powershell
# Windows PowerShell
irm https://aka.ms/connector-namespace-cli-install-ps | iex
```

## Configure the environment

```bash
azd auth login
az login
azd env new document-review
azd env set AZURE_LOCATION eastus2
azd env set CONNECTOR_NAMESPACE_LOCATION westcentralus

azd env set SHAREPOINT_SITE_URL "https://<tenant>.sharepoint.com/sites/<site>"
azd env set SHAREPOINT_FOLDER_PATH "/Shared Documents/Document Reviews"
azd env set TEAMS_GROUP_ID "<team-guid>"
azd env set TEAMS_CHANNEL_ID "19:<channel-id>@thread.tacv2"
```

| Setting | Required | Purpose |
| --- | --- | --- |
| `AZURE_LOCATION` | Yes | Primary region; this sample currently supports `eastus2` |
| `CONNECTOR_NAMESPACE_LOCATION` | No | Preview connector region; defaults to `westcentralus` |
| `SHAREPOINT_SITE_URL` | Yes | Site URL without a library path, query, or fragment |
| `SHAREPOINT_LIBRARY_NAME` | No | Library title; defaults to `Documents` |
| `SHAREPOINT_FOLDER_PATH` | Yes | Decoded path after the site URL, beginning with `/` |
| `TEAMS_GROUP_ID` | Yes | Destination team GUID |
| `TEAMS_CHANNEL_ID` | Yes | Destination standard-channel ID |
| `FOUNDRY_MODEL` | No | Deployment name; defaults to `gpt-5.4` |
| `FOUNDRY_DEPLOYMENT_CAPACITY` | No | Model capacity in thousands of tokens per minute; defaults to `10` |

### Find the SharePoint values

Open the exact library folder in SharePoint. For a URL like:

```text
https://contoso.sharepoint.com/sites/Reviews/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2FReviews%2FShared%20Documents%2FDocument%20Reviews
```

use:

```bash
azd env set SHAREPOINT_SITE_URL "https://contoso.sharepoint.com/sites/Reviews"
azd env set SHAREPOINT_LIBRARY_NAME "Documents"
azd env set SHAREPOINT_FOLDER_PATH "/Shared Documents/Document Reviews"
```

URL-decode the `id` query value and remove the site prefix. It is normal for the
default library title to be `Documents` while its URL segment is
`Shared Documents`. Create the folder before deploying.

### Find the Teams values

In Teams, open the standard channel menu and select **Copy link**. For a link
like:

```text
https://teams.microsoft.com/l/channel/19%3Aabc123%40thread.tacv2/Reviews?groupId=11111111-2222-3333-4444-555555555555
```

use:

```bash
azd env set TEAMS_GROUP_ID "11111111-2222-3333-4444-555555555555"
azd env set TEAMS_CHANNEL_ID "19:abc123@thread.tacv2"
```

URL-decode the channel ID. The authorizing identity must be a team member with
permission to post.

## Provision and deploy

```bash
azd up
```

The command:

1. Provisions the resources in `infra/`.
2. Exports `src/requirements.txt` from `pyproject.toml` and `uv.lock`.
3. Deploys the Python 3.13 Function app.
4. Registers the `GetOnNewFileItems` SharePoint trigger.
5. Generates the synthetic PDF and DOCX under `samples/documents/`.

The postdeploy hook never opens or completes delegated OAuth consent.

## What gets deployed

- Python 3.13 Azure Functions app on Flex Consumption
- Microsoft Foundry account, project, and `gpt-5.4` deployment
- Azure AI Document Intelligence
- Storage account and `DocumentReviews` table for claims and status
- Application Insights and Log Analytics
- User-assigned managed identity and role assignments
- Connector Namespace with SharePoint and Teams connections

Storage shared-key access, anonymous Blob access, Foundry local auth, Document
Intelligence local auth, and App Service publishing credentials are disabled.

## Authorize Microsoft 365

The customer authorizes the connections after deployment:

1. Open [Connector Namespaces](https://connectors.azure.com/).
2. Select the deployed namespace and open **Connections**.
3. Authorize `sharepoint-document-source` with an identity that can read the
   configured folder.
4. Authorize `teams-review-announcements` with an identity that can post to the
   configured channel.
5. Wait until both connections show **Connected** or **Enabled**.

The deployment operator never receives the customer's consent links or tokens.

## Trigger lifecycle

The postdeploy script creates the trigger on a first deployment. On later
deployments it leaves the existing trigger and polling state unchanged. To apply
an intentional trigger configuration change, set:

```bash
azd env set FORCE_CONNECTOR_TRIGGER_UPDATE true
azd hooks run postdeploy
```

The same hook regenerates synthetic files locally. It never uploads them.

## Verify and redeploy

Upload a newly named generated document and allow up to five minutes for the
poll. Tail aggregate runtime logs with:

```bash
azd monitor --logs
```

After code or agent-instruction changes, deploy without reprovisioning:

```bash
azd deploy api
```

## Clean up

```bash
azd down --purge
```

Next: [Troubleshooting](troubleshooting.md) | [Customize](customize.md)