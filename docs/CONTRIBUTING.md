# Contributing

Thanks for your interest. This project is small and opinionated — keep that in mind when proposing changes.

## Local dev — daemon

```bash
git clone https://github.com/Petr1t/jellyfin_seerr_loading_screen.git
cd jellyfin_seerr_loading_screen/jslsd
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check . && pytest
```

Run against your real Sonarr/Radarr:

```bash
export JSLSD_SONARR_URL=http://localhost:8989
export JSLSD_SONARR_API_KEY=your_key
export JSLSD_RADARR_URL=http://localhost:7878
export JSLSD_RADARR_API_KEY=your_key
python -m jslsd
# now curl http://localhost:7000/api/coming-soon
```

## Local dev — plugin

```bash
cd plugin
dotnet restore
dotnet build -c Release
# output: bin/Release/net8.0/Jellyfin.Plugin.SeerrLoadingScreen.dll
```

To smoke-test inside a real Jellyfin: copy the `.dll` + a hand-crafted `meta.json` into `/config/plugins/Seerr Loading Screen_<version>/`, restart Jellyfin.

## Style

- **Python:** ruff defaults, type hints required for public surfaces, black-compatible formatting.
- **C#:** stock dotnet formatting, no var-when-possible religion.
- **Commits:** present-tense, lowercase, no trailing dot. Imperative mood ("add x", not "added x" or "adds x").

## What we want help with

(See README's "hard problems" section.)

In particular: if you have a multi-user Jellyfin setup, your real-world feedback on the user-filtering logic would be valuable. Open an issue describing your setup before diving in.

## What we will reject

- New external dependencies without a clear reason. Each one is a maintenance burden.
- Architectural rewrites. The split between daemon and plugin is intentional.
- Features that conflict with the project goals (see ROADMAP "non-goals").
- Cosmetic-only PRs that don't fix a bug or improve clarity.

## License

By contributing you agree to license your code under GPL-2.0.
