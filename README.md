# LatexStudio AI

An AI-assisted LaTeX editor: a browser-based editor with live PDF compilation
and AI features (repair, notation lookup, agentic snippet insertion), plus a
VS Code extension that renders the same compile pipeline inline in the editor.

## Components

| Folder | What it is |
| --- | --- |
| [`LatexEditorBackEnd/`](LatexEditorBackEnd/) | The backend service: FastAPI app exposing `/compile`, `/repair`, `/notation`, `/agent/edit`, `/health`. Runs `pdflatex`/`bibtex` and a locally-loaded Qwen coder model. |
| [`LatexStudio-AI-master/`](LatexStudio-AI-master/) | The web frontend: static pages (login, project dashboard, Monaco-based editor) served by a small FastAPI app. Talks to the backend over HTTP. |
| [`vscode-latex-preview/`](vscode-latex-preview/) | A VS Code extension that compiles the currently open `.tex` project via the backend and renders the resulting PDF in a side panel (`Ctrl+Shift+O`). |

## Architecture

```
┌─────────────────────┐        ┌──────────────────────────┐
│  LatexStudio-AI-     │        │                          │
│  master (frontend)   │──────► │  LatexEditorBackEnd      │
│  login/editor pages  │  HTTP  │  (FastAPI + pdflatex +   │
└─────────────────────┘        │   Qwen model)            │
                                 └──────────────────────────┘
┌─────────────────────┐                  ▲
│ vscode-latex-preview │──────────────────┘
│ (VS Code extension)  │        HTTP
└─────────────────────┘
```

Both the web frontend and the VS Code extension are independent clients of
the same backend — neither embeds compilation or model logic itself.

## Getting started

### 1. Backend

```bash
cd LatexEditorBackEnd
pip install fastapi uvicorn httpx pydantic transformers torch
python LatexEditorBackend.py
```

Requires a LaTeX distribution (`pdflatex`, `bibtex`) on your `PATH` — e.g.
MiKTeX or TeX Live. The AI model (`Qwen/Qwen2.5-Coder-1.5B-Instruct`) is
lazy-loaded on first `/repair`, `/notation`, or `/agent/edit` call, so
`/compile` and `/health` work immediately without waiting on it (or a GPU).

See [`LatexEditorBackEnd/README.md`](LatexEditorBackEnd/README.md) for full
endpoint documentation.

### 2. Web frontend

```bash
cd LatexStudio-AI-master
pip install fastapi uvicorn
uvicorn main:app --reload --port 5000
```

Before running, fill in your own Firebase config in `firebase-init.js` and
Cloudinary config in `editor.html` (see that folder's README). Then open
`http://localhost:5000`.

### 3. VS Code extension (optional)

See [`vscode-latex-preview/README.md`](vscode-latex-preview/README.md) for
setup and usage — it lets you compile and preview a `.tex` file's PDF
directly inside VS Code, independent of the web frontend.

## Notes on this repo

- `projectFolder/` (a personal thesis-proposal draft used while developing
  this project) is intentionally excluded via `.gitignore` and not part of
  this repository.
- The original prototype notebooks (`LatexEditorBackend.ipynb`) are excluded
  as well — they're superseded by `LatexEditorBackEnd/LatexEditorBackend.py`
  and contained a since-revoked ngrok auth token.
- Firebase/Cloudinary values in the frontend are placeholders — fill in your
  own project's credentials before running it (see that folder's README).
