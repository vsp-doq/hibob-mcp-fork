# hibob-mcp-fork

Fork of [hibob-public-mcp](https://github.com/hibobio/hibob-public-mcp) with additional features.

## Changes from upstream (v0.4.0)

- **`humanReadable` parameter** on `hibob_people_search`: Pass `"REPLACE"` to get human-readable display names for list fields (e.g. `work.title`, `work.department`) instead of numeric IDs. Pass `"APPEND"` to get both.
- **`params` support** in `_hibob_api_call`: Query parameters are now forwarded to the HiBob API.

## Installation

```bash
pip install git+ssh://git@github.com/vsp-doq/hibob-mcp-fork.git
```

Or with uvx:
```bash
uvx --from git+ssh://git@github.com/vsp-doq/hibob-mcp-fork.git hibob-mcp-fork
```

## Configuration

Set the `HIBOB_API_TOKEN` environment variable with your HiBob API token (base64-encoded `serviceUserId:token`).

## License

MIT (same as upstream)
