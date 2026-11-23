# osint: command-line client for the OSINT Toolkit

Lists investigations, shows their results and identifiers, starts background lookups and
exports cases, from a terminal. It talks to a running toolkit server over its HTTP API,
so everything it does shows up in the web app, and the other way round.

## Install

With [pipx](https://pipx.pypa.io) (or `uv tool install` with the same address), on Windows, macOS or Linux:

```bash
pipx install "git+https://github.com/ayxkaddd/Osint-ToolKit#subdirectory=cli"
```

If `osint` isn't found afterwards, run `pipx ensurepath` once and open a new terminal.

## Use

```bash
osint login http://127.0.0.1:8000     # asks for the admin email and password
osint list                            # investigations; ● is the current one
osint use 1a2b                        # make one current (its id, the start of it, or its name)
osint show                            # its results, follow-up lookups under the one they came from
osint entities --type email           # identifiers found in it
osint modules --ready                 # what can run now
osint lookup someone@example.com      # which modules can look it up (nothing starts)
osint lookup someone@example.com -m holehe,gravatar   # start them in the background
osint jobs                            # running and recent lookups
osint export -o case.zip              # the case as a .zip; --report for the HTML report
osint logout                          # --everywhere also ends the browser sessions
```

- Lookups are saved to the **current investigation**, the same one the web app records
  into. `osint use` changes it there too.
- `osint lookup` only starts modules named with `-m`, because some of them cost money.
- Read commands take `--json`: the server's answer on stdout and nothing else, ready for `jq`:
  `osint entities --type phone --json | jq -r '.entities[].value'`.
- The server address is the one you logged in to; `--url` or the `OSINT_URL` environment
  variable picks another.
- A login lasts 24 hours. When it runs out, commands say `Session expired, run osint login`.

The address and login token are kept in `config.json` in your user config folder (only you
can read it on Linux and macOS); `OSINT_CONFIG_DIR` puts it somewhere else.

## Development

```bash
pip install -e "cli[test]"
pytest cli/tests          # a fake server (httpx.MockTransport), no network
```
