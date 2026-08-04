# Synthetic samples

Generate a PDF and DOCX with the same public, synthetic review content:

```bash
uv run --script scripts/create_sample_documents.py
```

The files are written to `samples/documents/`. Upload either file to the
configured SharePoint folder after deployment and connector consent.

`trigger-event.json` documents the metadata shape expected from the SharePoint
properties-only trigger. It is a fixture, not a local Connector Namespace
emulator.
