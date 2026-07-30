"""
LaTeX Editor backend server.

Exposes:
- POST /repair    -> LLM-based LaTeX repair
- POST /notation  -> LLM-based mathematical notation lookup
- POST /agent/edit -> LLM-based snippet insertion for the in-editor agent
- POST /compile   -> pdflatex/bibtex compilation of a LaTeX project
- GET  /health    -> liveness + model-load status

This is the single canonical backend for the LaTeX editor project — the
frontend (LatexStudio-AI-master) only serves static pages and calls this
service over HTTP.
"""

import asyncio
import base64
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from typing import Optional

import httpx
import uvicorn
from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# ── Model setup (lazy-loaded on first /repair, /notation or /agent/edit call) ─
# torch/transformers are imported lazily too: they're multi-GB deps only
# needed by the AI endpoints, so /compile and /health can run on a box that
# doesn't have them installed at all.
MODEL_NAME = "Qwen/Qwen2.5-Coder-1.5B-Instruct"

_tokenizer = None
_model = None
_model_load_error = None


def _get_model():
    """Load the tokenizer/model on first use so the server can start (and
    endpoints like /compile can be used) without waiting on the download."""
    global _tokenizer, _model, _model_load_error
    if _model is None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        device_map = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32

        try:
            _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
            _model = AutoModelForCausalLM.from_pretrained(
                MODEL_NAME,
                dtype=dtype,
                device_map=device_map,
                trust_remote_code=True,
            )
            print(f"Model loaded successfully on {next(_model.parameters()).device}")
        except Exception as e:
            _model_load_error = str(e)
            print(f"[model] Failed to load Qwen model: {e}")
            raise

    return _tokenizer, _model


def query_qwen(prompt: str) -> str:
    tokenizer, model = _get_model()
    messages = [{"role": "user", "content": prompt}]

    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    inputs = tokenizer(text, return_tensors="pt")

    device = next(model.parameters()).device
    inputs = {k: v.to(device) for k, v in inputs.items()}

    outputs = model.generate(
        **inputs,
        max_new_tokens=1024,
        do_sample=False,
    )
    generated_tokens = outputs[0, inputs["input_ids"].shape[1]:]

    return tokenizer.decode(generated_tokens, skip_special_tokens=True)


# ── FastAPI app + CORS ────────────────────────────────────────────────────────
app = FastAPI(title="LaTeX Editor Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # frontend runs on a different origin/port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return JSONResponse({"status": "ok", "model_loaded": _model is not None})


# ── /repair ───────────────────────────────────────────────────────────────────
class LatexRequest(BaseModel):
    broken_code: str
    error_context: str = ""


@app.post("/repair")
def repair_latex(request: LatexRequest):
    start = time.time()

    prompt = f"""
You are a LaTeX repair assistant.
Return ONLY the corrected LaTeX code.

DO NOT:
- explain
- apologize
- add markdown
- add ```latex
- add comments
- add any text before or after the code
Broken Code:
{request.broken_code}

Compiler Error:
{request.error_context}

Return only corrected LaTeX.
"""
    response = query_qwen(prompt)
    print("Elapsed:", time.time() - start)

    return {"response": response}


# ── /notation ─────────────────────────────────────────────────────────────────
class HelpRequest(BaseModel):
    selected_text: str


@app.post("/notation")
def notation_help(request: HelpRequest):
    prompt = f"""
The user selected:

{request.selected_text}

Return the mathematical symbol or notation.

Respond in JSON:

{{
  "symbol":"",
  "latex":"",
  "usage":""
}}

Do not explain.
"""
    response = query_qwen(prompt)

    return {"response": response}


# ── /agent/edit ───────────────────────────────────────────────────────────────
class AgentEditRequest(BaseModel):
    command: str
    context_before: str = ""
    context_after: str = ""


@app.post("/agent/edit")
def agent_edit(request: AgentEditRequest):
    prompt = f"""You are a LaTeX editing assistant embedded in an editor.
The user gave this instruction: "{request.command}"

LaTeX text immediately before the cursor:
---
{request.context_before}
---

LaTeX text immediately after the cursor:
---
{request.context_after}
---

Return ONLY the LaTeX snippet to insert at the cursor to satisfy the instruction
(e.g. a table, figure, or equation block). If the instruction asks to remove
something, return an empty string.

DO NOT explain, add markdown fences, or add any text other than the snippet.

Snippet:"""
    response = query_qwen(prompt).strip()
    if response.startswith("```"):
        response = response.split("\n", 1)[-1]
        if response.endswith("```"):
            response = response[:-3]
    return {"snippet": response.strip()}


# ── /compile ──────────────────────────────────────────────────────────────────
# Overleaf-style incremental compilation: each projectId gets a persistent
# workspace instead of a fresh temp dir per request. We only rewrite files
# whose content actually changed (preserving mtimes on the rest), and hand
# the whole thing to latexmk, which inspects its own .fdb_latexmk/.aux state
# from the previous compile and reruns only the passes that are actually
# needed — rather than always doing a fixed "pdflatex x2 + bibtex + x2" from
# a clean slate. Missing packages are resolved automatically via tlmgr.
class CompileRequest(BaseModel):
    files: dict[str, str]  # { "main.tex": "...", "chapters/intro.tex": "..." }
    images: dict[str, str] = {}  # { "figures/plot.png": "https://cloudinary..." }
    entry: str = "main.tex"
    projectId: Optional[str] = None
    forceFull: bool = False  # wipe latexmk's cached build state and start clean


def _safe_join(base: str, rel: str) -> Optional[str]:
    """Join rel onto base, returning None if it would escape base."""
    rel = rel.replace("\\", "/").lstrip("/")
    full = os.path.normpath(os.path.join(base, rel))
    if os.path.commonpath([os.path.abspath(base), os.path.abspath(full)]) != os.path.abspath(base):
        return None
    return full


PROJECTS_ROOT = os.environ.get("LATEX_PROJECTS_DIR", os.path.join(tempfile.gettempdir(), "latex_projects"))
os.makedirs(PROJECTS_ROOT, exist_ok=True)

MANIFEST_NAME = ".compile_manifest.json"
MAX_MISSING_PACKAGE_ATTEMPTS = 5
COMPILE_TIMEOUT_SECONDS = 120

_MISSING_FILE_RE = re.compile(r"File `([^']+)' not found")
_MISSING_FILE_RE2 = re.compile(r"I can't find file `([^']+)'")

_project_locks: dict[str, asyncio.Lock] = {}
_project_locks_guard = asyncio.Lock()
_tlmgr_lock = asyncio.Lock()  # tlmgr's local package db isn't safe for concurrent installs


async def _project_lock(project_id: str) -> asyncio.Lock:
    async with _project_locks_guard:
        return _project_locks.setdefault(project_id, asyncio.Lock())


def _texbin_dir() -> Optional[str]:
    """Locate the user-space TeX Live bin dir (e.g. ~/texlive/2026/bin/x86_64-linux),
    installed without sudo so the server's own user can run tlmgr to fetch packages."""
    matches = sorted(glob.glob(os.path.expanduser("~/texlive/*/bin/*")))
    return matches[-1] if matches else None


def _compile_env() -> dict:
    env = os.environ.copy()
    texbin = _texbin_dir()
    if texbin:
        env["PATH"] = texbin + os.pathsep + env.get("PATH", "")
    return env


def _sync_project(project_dir: str, files: dict[str, str], images: dict[str, str]) -> dict[str, str]:
    """Write only files/images whose content changed since the last compile of
    this project, and remove ones dropped from the request — leaving
    latexmk's own generated artifacts untouched. Returns the subset of
    `images` that actually need (re)fetching."""
    manifest_path = os.path.join(project_dir, MANIFEST_NAME)
    prev: dict = {}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path) as f:
                prev = json.load(f)
        except (json.JSONDecodeError, OSError):
            prev = {}
    prev_files = prev.get("files", {})
    prev_images = prev.get("images", {})

    new_files: dict[str, str] = {}
    for filename, content in files.items():
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        new_files[filename] = digest
        path = _safe_join(project_dir, filename)
        if path is None:
            continue
        if prev_files.get(filename) != digest or not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

    new_images: dict[str, str] = {}
    changed_images: dict[str, str] = {}
    for img_name, img_url in images.items():
        digest = hashlib.sha256(img_url.encode("utf-8")).hexdigest()
        new_images[img_name] = digest
        path = _safe_join(project_dir, img_name)
        if path is None:
            continue
        if prev_images.get(img_name) != digest or not os.path.exists(path):
            changed_images[img_name] = img_url

    for filename in prev_files:
        if filename not in files:
            path = _safe_join(project_dir, filename)
            if path and os.path.exists(path):
                os.remove(path)
    for img_name in prev_images:
        if img_name not in images:
            path = _safe_join(project_dir, img_name)
            if path and os.path.exists(path):
                os.remove(path)

    with open(manifest_path, "w") as f:
        json.dump({"files": new_files, "images": new_images}, f)

    return changed_images


def _find_missing_files(log: str) -> list[str]:
    found = set(_MISSING_FILE_RE.findall(log)) | set(_MISSING_FILE_RE2.findall(log))
    return sorted(found)


async def _tlmgr_install_for(missing_file: str) -> Optional[str]:
    """Resolve a missing file (e.g. 'foo.sty') to the TeX Live package that
    provides it and install it via tlmgr. Returns the package name on
    success, None if it couldn't be resolved or installed."""
    env = _compile_env()
    async with _tlmgr_lock:
        try:
            search = await asyncio.to_thread(
                subprocess.run,
                ["tlmgr", "search", "--global", "--file", f"/{missing_file}"],
                capture_output=True, text=True, env=env, timeout=60,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

        pkg = None
        for line in search.stdout.splitlines():
            if line and not line.startswith((" ", "\t")) and line.endswith(":"):
                pkg = line[:-1].strip()
                break
        if not pkg:
            return None

        try:
            install = await asyncio.to_thread(
                subprocess.run,
                ["tlmgr", "install", pkg],
                capture_output=True, text=True, env=env, timeout=300,
            )
        except subprocess.TimeoutExpired:
            return None
        return pkg if install.returncode == 0 else None


async def _run_latexmk(entry_dir: str, entry_base: str, force: bool = False) -> tuple[int, str]:
    """force=True passes -g: without it, latexmk sees that main.tex hasn't
    changed since a previous fatal-error run and just replays the cached
    failure instead of retrying — which is exactly the case right after we've
    auto-installed a package that was missing on the prior attempt."""
    env = _compile_env()
    cmd = ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", "-file-line-error"]
    if force:
        cmd.append("-g")
    cmd.append(entry_base)
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            cwd=entry_dir,
            capture_output=True,
            text=True,
            env=env,
            timeout=COMPILE_TIMEOUT_SECONDS,
        )
        return result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired as e:
        return 1, f"Compilation timed out after {COMPILE_TIMEOUT_SECONDS}s\n{e.stdout or ''}{e.stderr or ''}"
    except FileNotFoundError:
        return 1, "latexmk not found on PATH — is the TeX Live install present under ~/texlive?"


@app.post("/compile")
async def compile_latex(request: CompileRequest, background_tasks: BackgroundTasks):
    use_persistent = bool(request.projectId)
    project_id = request.projectId or f"anon-{uuid.uuid4()}"
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", project_id)
    project_dir = os.path.join(PROJECTS_ROOT, safe_id)

    for filename in list(request.files) + list(request.images):
        if _safe_join(project_dir, filename) is None:
            return JSONResponse(
                status_code=400,
                content={"success": False, "log": f"Unsafe path: {filename}"},
            )

    lock = await _project_lock(safe_id)
    async with lock:
        try:
            os.makedirs(project_dir, exist_ok=True)

            if request.forceFull:
                env = _compile_env()
                await asyncio.to_thread(
                    subprocess.run, ["latexmk", "-C"], cwd=project_dir,
                    capture_output=True, text=True, env=env,
                )

            changed_images = _sync_project(project_dir, request.files, request.images)

            if changed_images:
                async with httpx.AsyncClient(timeout=30) as client:
                    for img_name, img_url in changed_images.items():
                        path = _safe_join(project_dir, img_name)
                        if path is None:
                            continue
                        try:
                            if img_url.startswith("data:"):
                                _, b64data = img_url.split(",", 1)
                                content = base64.b64decode(b64data)
                            else:
                                resp = await client.get(img_url)
                                resp.raise_for_status()
                                content = resp.content
                            os.makedirs(os.path.dirname(path), exist_ok=True)
                            with open(path, "wb") as f:
                                f.write(content)
                        except Exception as img_err:
                            # Non-fatal: log but continue — latexmk will report
                            # a missing image rather than crashing the server
                            print(f"[compile] Could not resolve {img_name}: {img_err}")

            entry = request.entry.replace("\\", "/").lstrip("/")
            entry_path = _safe_join(project_dir, entry)
            if entry_path is None or not os.path.exists(entry_path):
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "log": f"Entry file '{entry}' not found in submitted files.",
                    },
                )

            entry_dir = os.path.dirname(entry_path)
            entry_base = os.path.basename(entry)

            compile_log = ""
            returncode = 1
            attempted: set[str] = set()

            for attempt in range(MAX_MISSING_PACKAGE_ATTEMPTS + 1):
                returncode, run_log = await _run_latexmk(entry_dir, entry_base, force=attempt > 0)
                compile_log += f"\n{'─' * 40} latexmk (attempt {attempt + 1}) {'─' * 40}\n{run_log}"

                if returncode == 0:
                    break

                missing = [m for m in _find_missing_files(run_log) if m not in attempted]
                if not missing:
                    break  # a real compile error, not a missing-package problem

                resolved_any = False
                for missing_file in missing:
                    attempted.add(missing_file)
                    pkg = await _tlmgr_install_for(missing_file)
                    if pkg:
                        compile_log += f"\n[auto-install] installed '{pkg}' (provides '{missing_file}')\n"
                        resolved_any = True
                    else:
                        compile_log += f"\n[auto-install] could not resolve a package for '{missing_file}'\n"

                if not resolved_any:
                    break

            pdf_file = os.path.join(entry_dir, os.path.splitext(entry_base)[0] + ".pdf")

            if returncode != 0 or not os.path.exists(pdf_file):
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "log": compile_log},
                )

            output_dir = os.path.join(tempfile.gettempdir(), "latex_output")
            os.makedirs(output_dir, exist_ok=True)

            final_pdf = os.path.join(output_dir, f"{uuid.uuid4()}.pdf")
            shutil.copy2(pdf_file, final_pdf)

            def cleanup(path=final_pdf):
                if os.path.exists(path):
                    os.remove(path)

            background_tasks.add_task(cleanup)

            if not use_persistent:
                shutil.rmtree(project_dir, ignore_errors=True)

            return FileResponse(
                final_pdf,
                media_type="application/pdf",
                filename="document.pdf",
            )

        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"success": False, "log": str(e)},
            )


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
