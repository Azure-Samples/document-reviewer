# Use cases

Back to the [README](../README.md).

The bundled files contain public, synthetic project-review content. Generate
them with:

```bash
uv run --script scripts/create_sample_documents.py
```

## Grounded project review

Upload `samples/documents/project-atlas-review.pdf` or the DOCX equivalent to
the configured SharePoint folder. After the next poll, the fixed Teams channel
receives a brief with:

- a link to the source document;
- a concise summary with exact source excerpts;
- supported changes, risks, and open questions; and
- the document's stated review focus.

The model may phrase the review differently between runs, but every published
finding must include an exact excerpt present in the extracted document.

## Duplicate version

Upload or poll the same completed version again. The Table claim suppresses it,
and no second Teams post is sent. To run the demo again, use a new filename or
create a new SharePoint version.

## Unsupported or unsafe document

Try a TXT file, a file over 10 MB, a password-protected file, or a document over
50 pages. The workflow publishes a factual failure notice rather than a summary.
No unsupported content is sent to the model as a successful review.

## Prompt injection in the document

Add text asking the agent to reveal configuration, change destinations, execute
code, or ignore its instructions. The agent is told to treat all extracted text
as untrusted data, and the tool boundary independently prevents those actions:

- the preparation tool can read only the configured folder;
- the publication tool has no destination parameters;
- every finding requires an exact source excerpt; and
- all source-derived Teams HTML is escaped.

## Ambiguous Teams send

If the Teams request begins but the connector result cannot prove delivery, the
claim becomes `publication_unknown`. The workflow does not retry because that
could create a duplicate channel post. Inspect the channel and Table record
before reconciling it manually.

Next: [How it works](how-it-works.md) | [Customize](customize.md) |
[Troubleshooting](troubleshooting.md)