# Troubleshooting

Back to the [README](../README.md).

## No event after an upload

The SharePoint trigger polls every five minutes. Confirm that:

- both Connector Namespace connections are connected;
- the trigger is enabled and provisioned successfully;
- the uploaded file is directly inside the configured folder; and
- the upload is a new filename or SharePoint version.

The postdeploy script preserves an existing trigger's polling state. Re-run
`azd hooks run postdeploy` to create a missing trigger; set
`FORCE_CONNECTOR_TRIGGER_UPDATE=true` only when intentionally changing its
configuration.

## Connector authorization fails

Open [Connector Namespaces](https://connectors.azure.com/) with the customer
identity and reauthorize the affected connection. The SharePoint identity needs
read access to the configured folder. The Teams identity needs membership and
post permission in the configured standard channel.

Setting runtime URLs or rerunning `azd up` does not grant delegated Microsoft
365 consent.

## "The document could not be retrieved from SharePoint"

Check the following in order:

1. `SHAREPOINT_SITE_URL` ends at the site and contains no library path.
2. `SHAREPOINT_FOLDER_PATH` is decoded, starts with `/`, and includes the
   library URL segment such as `/Shared Documents/...`.
3. `SHAREPOINT_LIBRARY_NAME` is the library title, commonly `Documents`.
4. The SharePoint connection is authorized by an identity that can open the
   exact file.
5. The deployed app uses the locked `azure-connectors` version from
   `src/uv.lock` and includes the binary-safe compatibility transport.

Run the focused retrieval tests before changing route encoding or identifiers:

```bash
cd src
uv run pytest ../tests/test_connector_clients.py ../tests/test_prepare_review_document.py
```

## No Teams message

Look for one of these expected outcomes in Application Insights or
`azd monitor --logs`:

- `document_prepare_ready`: extraction succeeded and publication should follow;
- `document_prepare_failed`: a factual failure publication should follow;
- `document_prepare_skipped`: the version was already claimed or in progress;
- `document_publish_completed`: Teams accepted the review or failure notice;
- `document_publish_failed`: Teams rejected the send before delivery began.

If the claim is `publication_unknown`, inspect the channel before taking manual
action. Automatic retry is intentionally disabled because it could duplicate a
message.

## Reusing the sample produces no message

A completed file version is suppressed by design. Rename the generated file or
create a new SharePoint version. Deleting and recreating the trigger does not
clear Table claims and would discard useful polling state.

## Deployment fails during role assignment or startup

Role assignments can take several minutes to propagate. Retry `azd up` after
propagation. For a code-only retry use `azd deploy api`.

Confirm Python 3.13 is installed and that packaging regenerated
`src/requirements.txt`:

```bash
cd src
uv python install 3.13
uv sync --locked
uv lock --check
```

## Model deployment errors

The template currently provisions the model in `eastus2`. Check model quota and
capacity for the subscription, and confirm the `FOUNDRY_MODEL*` values describe
an available catalog version and deployment.

## Local Function host

Connector Namespace has no local emulator. Unit tests are the supported local
workflow. To inspect tool discovery and host startup:

```bash
cd src
cp local.settings.json.sample local.settings.json
uv sync --locked
azurite --silent --location ../.azurite  # terminal A
uv run func start                        # terminal B
```

Fill the deployed Foundry, connector, Document Intelligence, and Table endpoints
in `local.settings.json`. The Function host can start locally, but real connector
events still arrive only at the deployed Function.

If Core Tools imports the wrong Python on Windows, disable Microsoft Store
`python.exe` and `python3.exe` App execution aliases, open a new terminal, and
start the host with `uv run func start` from `src/`.

## Privacy-safe diagnostics

Keep `ENABLE_SENSITIVE_DATA=false` and `logger: false`. Diagnose with event
counts, status categories, durations, and dependency result codes. Do not print
raw trigger payloads, connector metadata values, file bytes, extracted Markdown,
tool arguments/results, generated reviews, or Teams message bodies.

Next: [Deploy](deploy.md) | [How it works](how-it-works.md)