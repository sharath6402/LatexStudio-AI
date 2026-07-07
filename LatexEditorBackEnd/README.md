# LatexEditorBackEnd

The single canonical backend for the LaTeX editor project. A FastAPI service
that compiles LaTeX projects with `pdflatex`/`bibtex` and provides AI-assisted
editing features via a locally-loaded Qwen coder model. Both the web frontend
(`LatexStudio-AI-master`) and the VS Code extension (`vscode-latex-preview`)
are HTTP clients of this service — no compilation or model logic lives in
either of them.

## Prerequisites

- Python 3.10+
- A LaTeX distribution providing `pdflatex` and `bibtex` on your `PATH`
  (e.g. [MiKTeX](https://miktex.org/) or [TeX Live](https://tug.org/texlive/)).
- Optional but recommended for AI features: a CUDA-capable GPU. The model
  falls back to CPU (slow) if none is available.

## Install & run

```bash
pip install fastapi uvicorn httpx pydantic transformers torch
python LatexEditorBackend.py
```

This starts the server on `http://0.0.0.0:8000`. The AI model
(`Qwen/Qwen2.5-Coder-1.5B-Instruct`) is **lazy-loaded** on first use — the
server starts instantly and `/compile`/`/health` work right away without
waiting on a multi-GB model download.

To expose the server publicly (e.g. for the web frontend or VS Code extension
to reach it from elsewhere), tunnel it with your own tool of choice, for
example [ngrok](https://ngrok.com/):

```bash
ngrok http 8000
```

## API

| Method & path | Body | Returns |
| --- | --- | --- |
| `GET /health` | — | `{ status, model_loaded }` |
| `POST /repair` | `{ broken_code, error_context }` | `{ response }` — AI-corrected LaTeX |
| `POST /notation` | `{ selected_text }` | `{ response }` — JSON string with `symbol`/`latex`/`usage` |
| `POST /agent/edit` | `{ command, context_before, context_after }` | `{ snippet }` — LaTeX to insert at the cursor |
| `POST /compile` | `{ files, images, entry, projectId? }` | The compiled PDF, or `{ success: false, log }` on failure |

### `/compile` request shape

```jsonc
{
  "files": { "main.tex": "...", "chapters/intro.tex": "...", "refs.bib": "..." },
  "images": {
    // Either a remote URL...
    "figures/plot.png": "https://res.cloudinary.com/.../plot.png",
    // ...or an inline base64 data URI (used by the VS Code extension for local files)
    "logo.png": "data:image/png;base64,iVBORw0KG..."
  },
  "entry": "main.tex"
}
```

The server writes `files` to a temp directory (preserving relative paths),
resolves `images` (downloading URLs or decoding `data:` URIs), runs
`pdflatex` twice, then `bibtex` + two more `pdflatex` passes if any `.bib`
file is present, and streams back the resulting PDF. On failure it returns
the full compiler log so the caller can display it.

## Configuration

There's no config file — the model name and port are constants at the top
of `LatexEditorBackend.py`. CORS is wide open (`allow_origins=["*"]`) for
local development; restrict this before any public deployment.
