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
osint list                            # investigations; * is the current one
osint use 1a2b                        # make one current (its id, the start of it, or its name)
osint show                            # its results, follow-up lookups under the one they came from
osint entities --type email           # identifiers found in it
osint modules --ready                 # what can run now
osint lookup someone@example.com      # pick the modules to run, then see what each one answers
osint lookup someone@example.com -m holehe,gravatar   # the same, naming the modules
osint lookup someone@example.com -m holehe -d         # start it and return (--detach)
osint follow                          # wait for the running lookups and show their answers
osint jobs                            # running and recent lookups
osint export -o case.zip              # the case as a .zip; --report for the HTML report
osint logout                          # --everywhere also ends the browser sessions
```

- Lookups are saved to the **current investigation**, the same one the web app records
  into. `osint use` changes it there too.
- `osint lookup` asks which modules to run: space ticks one, enter starts them. Nothing
  is ticked at first, because some cost money (their cost is shown); modules that need
  setup are listed with what to add, and can't be ticked.
- It then waits for each lookup and prints its answer, every field. Lookups that stream
  (username search, OSINT Industries, plugins, VK history) print what they find as it
  arrives, like the web page. Ctrl+C stops waiting, not the lookups: `osint follow`
  shows them again.
- Without a terminal (a script, a pipe) it doesn't ask: `-m` names the modules, and
  without `-m` it only lists them. With `--json` it prints every job and its saved result
  once all have finished.
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
