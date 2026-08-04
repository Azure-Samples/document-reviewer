# Contributing

Contributions and suggestions are welcome. Most contributions require agreement
to the Microsoft Contributor License Agreement at
https://cla.opensource.microsoft.com/.

## Workflow

1. Fork the repository and create a focused topic branch.
2. Keep preview compatibility code isolated and preserve the documented privacy
   and delivery guarantees.
3. Add or update tests for behavior changes.
4. Run the validation suite:

   ```bash
   cd src
   uv sync --locked
   uv run pytest
   uv lock --check
   ```

5. Open a pull request against `main` describing the motivation, security
   impact, and validation performed.

A CLA bot will indicate whether any additional agreement step is required.