# Customize

Back to the [README](../README.md).

Keep the sample's trust boundary intact when adapting it: configuration chooses
the source and destination, deterministic tools enforce constraints, and the
agent interprets only the extracted document.

## Change the source or destination

Set a new SharePoint site, library, folder, team, or channel through the `azd`
environment values described in [Deploy](deploy.md), then run `azd up` to apply
the infrastructure and app-setting changes.

Do not add source paths or Teams destinations to either tool schema. Keeping
them out of model-controlled arguments prevents a document or generated tool
call from redirecting data.

## Change the review

Edit the Markdown body of
[`src/agents/document_review_announcer.agent.md`](../src/agents/document_review_announcer.agent.md).
The current contract asks for a summary plus supported changes, risks, open
questions, and review focus.

When adding a section:

1. Add a bounded field to the publication input model.
2. Require an exact evidence excerpt for each generated claim.
3. Validate that excerpt against the claim-bound source.
4. Escape all source-derived output before rendering Teams HTML.
5. Add preparation, validation, and HTML-escaping tests.

Redeploy instruction or tool changes with `azd deploy api`.

## Change document limits

The sample defaults are defined in [`src/config.py`](../src/config.py):

- 10 MB per document;
- 50 pages; and
- 200,000 extracted characters.

Raise limits only after evaluating Function memory, execution timeout, model
context, Document Intelligence cost, and the amount of untrusted content passed
to the model. Update the tests and operational guidance with any change.

## Add another file type

PDF and DOCX use Document Intelligence `prebuilt-layout`. To add a format:

1. Extend the allow-list in the preparation tool.
2. Confirm Document Intelligence accepts the media type and preserves useful
   structure.
3. Add a small synthetic fixture and extraction tests.
4. Keep size, page, and character bounds in place.

Do not pass an unsupported file directly to the model.

## Change the model

The Bicep parameters default to `gpt-5.4`. Override the deployment catalog name,
version, deployment name, and capacity through the corresponding `FOUNDRY_*`
`azd` values, then run `azd up`.

Model changes can alter review phrasing. The publication tool's exact-evidence
validation remains the deterministic quality boundary, so run the full suite and
repeat the synthetic document scenario after a model change.

## Upgrade preview packages

`azure-connectors` and the agents runtime are pinned because the sample contains
compatibility code for their current preview behavior. Update their exact
versions in `src/pyproject.toml`, then regenerate and test the deployment inputs:

```bash
cd src
uv lock
uv export --format requirements-txt --no-hashes --no-dev --no-emit-project --output-file requirements.txt
uv run pytest ../tests/test_connector_clients.py ../tests/test_trigger_payloads.py
uv run pytest
```

Inspect [`_connector_compat.py`](../src/document_review/_connector_compat.py) and
the trigger normalizer against the new SDK behavior. Remove a workaround only
after its regression test proves the upstream package now owns that behavior.

Next: [How it works](how-it-works.md) | [Deploy](deploy.md) |
[Troubleshooting](troubleshooting.md)