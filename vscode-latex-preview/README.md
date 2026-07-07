# LaTeX AI Preview (VS Code extension)

Compile and preview a LaTeX project directly inside VS Code — no separate
PDF viewer window, no manual `pdflatex` invocation. Compilation is delegated
to the [`LatexEditorBackEnd`](../LatexEditorBackEnd) service, so this
extension itself has no LaTeX toolchain dependency; it just needs network
access to a running backend.

## What it does

1. You open a `.tex` file and press **`Ctrl+Shift+O`**.
2. The extension collects every `.tex`, `.bib`, `.cls`, `.sty`, and image
   (`.png`/`.jpg`/`.jpeg`/`.pdf`) file in that file's folder. For any of
   those files that are currently open in an editor tab, it uses the live
   (possibly unsaved) buffer content instead of what's on disk.
3. It `POST`s all of that to the backend's `/compile` endpoint (images are
   sent as inline base64 `data:` URIs, since they're local files rather than
   URLs).
4. The returned PDF is rendered in a Webview panel beside your editor, using
   a bundled copy of [pdf.js](https://mozilla.github.io/pdf.js/) — no
   internet connection needed at preview time, and no external PDF viewer
   required.

If compilation fails, the backend's compiler log is shown as an error
notification instead of a blank/broken preview.

## Requirements

- A running instance of `LatexEditorBackEnd` (see the
  [backend README](../LatexEditorBackEnd/README.md) for setup). It does the
  actual `pdflatex`/`bibtex` work — this extension only talks HTTP to it.
- VS Code 1.85+.

## Install & run (development mode)

This extension isn't published to the Marketplace — run it from source:

```bash
cd vscode-latex-preview
npm install
```

Then in VS Code:

1. Open this folder (`vscode-latex-preview`) as a workspace.
2. Press **F5** (or Run → Start Debugging). This uses the checked-in
   `.vscode/launch.json`, which launches an **Extension Development Host**
   window with the extension active.
3. In that new window, open any `.tex` file.
4. Press **`Ctrl+Shift+O`** to compile and preview it.

> `.vscode/launch.json` points at a specific local project folder
> (`d:\project\LatexEditorAi\projectFolder` by default) for convenience while
> developing — edit the `args` array in that file to point at your own `.tex`
> project, or just open a different folder manually in the Extension
> Development Host window before testing.

## Configuration

One setting, under **Settings → Extensions → LaTeX AI Preview** (or directly
in `settings.json`):

| Setting | Default | Description |
| --- | --- | --- |
| `latexAiPreview.backendUrl` | `http://127.0.0.1:8000` | Base URL of your running `LatexEditorBackEnd` instance. Change this if the backend runs on a different host/port, or behind a tunnel. |

## Keybinding

| Command | Default keybinding | When |
| --- | --- | --- |
| `LaTeX AI: Compile and Preview` | `Ctrl+Shift+O` | A `.tex` file is focused in the active editor |

The keybinding only applies when `editorLangId == latex`. This extension
contributes its own minimal `latex` language association for `.tex` files, so
it works even without another LaTeX extension installed — though if you
already use one (e.g. LaTeX Workshop), that's fine too; VS Code allows
multiple extensions to associate the same language ID.

You can also trigger the same command from the editor toolbar (the preview
icon in the top-right of a `.tex` file's tab) or via the Command Palette
(`LaTeX AI: Compile and Preview`), and rebind the keyboard shortcut from
**Keyboard Shortcuts** (`Ctrl+K Ctrl+S`) if `Ctrl+Shift+O` conflicts with
something else in your setup.

## How rendering works internally

`pdf.js`'s prebuilt legacy UMD bundle (`media/pdf.min.js` +
`media/pdf.worker.min.js`, copied from the `pdfjs-dist` npm package) is
loaded inside the Webview via a `<script>` tag, exposing a `window.pdfjsLib`
global. The extension base64-encodes the compiled PDF and passes it into the
Webview's HTML, where it's decoded and rendered page-by-page onto `<canvas>`
elements. This avoids depending on any native OS PDF viewer or an internet
connection at preview time.

## Known limitations

- Only files in the **same folder** as the active `.tex` file are sent to
  the backend — nested subfolders referenced via relative paths (e.g.
  `\input{chapters/intro}`) aren't currently walked recursively.
- No incremental/SyncTeX support (no click-to-jump between source and PDF).
- No auto-recompile on save — you trigger it manually each time.
