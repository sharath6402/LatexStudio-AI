# TeXStudio AI (web frontend)

A browser-based LaTeX editor with AI-assisted authoring, live PDF compilation,
and per-user cloud projects. This is the **frontend only** — a set of static
HTML pages served by a small FastAPI app. All compilation and AI logic is
provided by the separate [`LatexEditorBackEnd`](../LatexEditorBackEnd) service.

## Features

- **Monaco-based LaTeX editor** with a file explorer (multi-file/multi-folder
  projects, drag-and-drop image/file uploads, `.tex`/`.bib`/`.cls`/`.sty` support).
- **PDF compilation**, rendered directly in an in-page PDF viewer, via the backend's `/compile` endpoint.
- **AI-assisted editing** via the backend's Qwen-powered endpoints:
  - Repair broken LaTeX using the compiler's error output.
  - Look up mathematical notation/symbols for selected text.
  - Agentic command bar — natural-language instructions ("add a 3x4 table comparing X and Y") that insert or remove LaTeX blocks (tables, figures, equations, lists) at the cursor.
- **Sign in with email/password or Google**, via Firebase Authentication.
- **Accounts & projects** via Firebase Authentication + Firestore, so each user's projects are saved and listed on a dedicated projects page.
- **Image hosting** through Cloudinary (unsigned upload preset) for images referenced in compiled documents.
- Light/dark theme toggle and MathJax live math rendering in the editor.

## Project structure

| Path | Description |
| --- | --- |
| `main.py` | FastAPI app: serves the static pages (`/`, `/login`, `/projects`, `/editor`) and `firebase-init.js`. No compile/AI logic lives here. |
| `login.html` | Sign in / sign up page (Firebase Auth, email/password + Google). |
| `projects.html` | Project dashboard — create, open, and delete projects (Firestore). |
| `editor.html` | Main LaTeX editor: Monaco editor, file explorer, AI panel, agent command bar, PDF preview. Calls the backend directly via the `API_BASE` constant near the top of its script. |
| `firebase-init.js` | Firebase app initialization and shared auth/Firestore/Storage helpers, served at `/firebase-init.js`. |

## How it works

1. `main.py` serves the static pages and mounts the project directory at `/static`. It has no knowledge of LaTeX compilation or AI — those requests go straight from the browser to the backend.
2. `editor.html` posts to `${API_BASE}/repair`, `/notation`, `/agent/edit`, and `/compile` — set `API_BASE` (near the top of the second `<script>` block) to wherever you're running `LatexEditorBackEnd`.
3. The editor persists project files/state in Firestore and Firebase Storage per authenticated user; the projects page lists/creates/deletes those projects.

## Getting started

### Prerequisites

- Python 3.10+
- A running instance of [`LatexEditorBackEnd`](../LatexEditorBackEnd) (locally or tunneled).
- A Firebase project (Authentication + Firestore + Storage) and a Cloudinary account.

### Install dependencies

```bash
pip install fastapi uvicorn
```

### Configure Firebase, Google Sign-In & Cloudinary

- `firebase-init.js` has a `firebaseConfig` object with placeholder values —
  replace them with your own project's config (Firebase Console → Project
  Settings → General → Your apps), and enable Email/Password and Google
  sign-in under Authentication → Sign-in method. Set up Firestore/Storage
  security rules for per-user projects.
- `editor.html` has a `CLOUDINARY` object (`cloudName`, `uploadPreset`) near
  the image-upload code — set these to your own Cloudinary cloud name and an
  **unsigned** upload preset.
- `editor.html` has an `API_BASE` constant — point it at your running
  `LatexEditorBackEnd` instance (e.g. `http://localhost:8000`, or a tunnel URL).

### Run the server

```bash
uvicorn main:app --reload --port 5000
```

Then open `http://localhost:5000` in your browser (redirects to the sign-in page).

## Security notes

- CORS is wide open (`allow_origins=["*"]`) in the backend's `main.py`
  equivalent, which is convenient for local development but should be
  restricted before any public deployment.
- Firebase web config (`apiKey` etc.) is not a traditional secret — access is
  controlled by Firebase Security Rules and authorized-domains, not by
  keeping the config hidden — but you should still use your own project's
  values rather than someone else's.
