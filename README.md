# MCP Bridge Newtone

Free extension for **BetterFL MCP Bridge** that lets an AI assistant drive Image-Line Newtone inside
FL Studio: load audio into Newtone on a mixer track, read the detected notes, pitch-correct them to a
scale, edit single notes, render the result and place it in the playlist.

| Tool | What it does |
|---|---|
| `fl_newtone_load` | Load an audio file into Newtone on a mixer track and wait for the note analysis |
| `fl_newtone_notes` | List the notes: timing, detected/current pitch, shift, drift, volume, formant, vibrato |
| `fl_newtone_correct` | Pitch-correct to a scale (`"D minor"`, `"F# major"`, `"chromatic"`, ...) with amount and variation |
| `fl_newtone_edit` | Edit single notes |
| `fl_newtone_render` | Render the edited audio to a WAV and optionally place it in the playlist |
| `fl_newtone_command` | Engine commands: undo, redo, select, quantize time, cut/copy/paste, save MIDI, ... |
| `fl_newtone_project` / `fl_newtone_state` / `fl_newtone_state_set` | Project XML and saved state (debugging) |

Needs a BetterFL Bridge build with the native Newtone functions; with an older bridge every tool
answers with a "restart FL" error.

## Development

`extension.py` is generated: edit `src/ntcodec.py` (state / project XML codec) and `src/tools.py`
(live tools), then run `python build.py`.

## Install

Requires **BetterFL MCP Bridge** (FL Studio plugin) with **extension API 1**. Releases are signed
`.bflx` bundles; the bridge only installs bundles signed with BetterFL's key.

- From the assistant: `fl_extension_install` with `id = "mcp-bridge-newtone"` downloads the latest release
  (`https://github.com/BetterInc/mcp-bridge-newtone/releases/latest/download/mcp-bridge-newtone.bflx` + `.sig`), verifies and loads it.
- The BetterFL MCP Bridge installer zip already contains the latest release.
- Development copy: `powershell -File install.ps1` (runs `build.py`, copies to `%LOCALAPPDATA%\BetterFL\extensions\mcp-bridge-newtone`); then `fl_reload`.

`fl_extensions` lists the loaded extensions and their tools.

## Releasing

Push a tag `v<version>` matching `manifest.json`'s `version`. GitHub Actions builds `extension.py`
(when there is a `build.py`), packs `mcp-bridge-newtone.bflx` with `tools/pack.py`, signs it with the
`EXTENSION_SIGNING_KEY` repository secret and publishes `mcp-bridge-newtone.bflx` + `mcp-bridge-newtone.bflx.sig` as a release.
The signing key is never stored in this repository.

## License

MIT, see [LICENSE](LICENSE).
