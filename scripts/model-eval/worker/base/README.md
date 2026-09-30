# tk

Small utilities used by the ops dashboard: durations, pagination, text reports,
money formatting and a tiny HTTP client.

## Development

```sh
.venv/bin/python -m pytest -q
```

## Configuration

`load_config()` reads a dict (usually parsed from `tk.json`):

- `base_url` (required): the API root, e.g. `https://api.example.com`
- `retries` (default `3`): extra attempts after a `ConnectionError`

## CLI

```sh
tk list --page 2 --per-page 10 items.txt
tk post --base-url https://api.example.com /jobs '{"name": "nightly"}'
```
