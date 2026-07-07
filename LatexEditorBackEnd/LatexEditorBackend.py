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

import base64
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from typing import Optional

import httpx
import torch
import uvicorn
from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer

# ── Model setup (lazy-loaded on first /repair, /notation or /agent/edit call) ─
MODEL_NAME = "Qwen/Qwen2.5-Coder-1.5B-Instruct"

_tokenizer = None
_model = None
_model_load_error = None


def _get_model():
    """Load the tokenizer/model on first use so the server can start (and
    endpoints like /compile can be used) without waiting on the download."""
    global _tokenizer, _model, _model_load_error
    if _model is None:
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
class CompileRequest(BaseModel):
    files: dict[str, str]  # { "main.tex": "...", "chapters/intro.tex": "..." }
    images: dict[str, str] = {}  # { "figures/plot.png": "https://cloudinary..." }
    entry: str = "main.tex"
    projectId: Optional[str] = None


def _safe_join(base: str, rel: str) -> Optional[str]:
    """Join rel onto base, returning None if it would escape base."""
    rel = rel.replace("\\", "/").lstrip("/")
    full = os.path.normpath(os.path.join(base, rel))
    if os.path.commonpath([os.path.abspath(base), os.path.abspath(full)]) != os.path.abspath(base):
        return None
    return full


@app.post("/compile")
async def compile_latex(request: CompileRequest, background_tasks: BackgroundTasks):
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # ── Write every text file at its relative path ───────────────────
            for filename, content in request.files.items():
                path = _safe_join(tmpdir, filename)
                if path is None:
                    return JSONResponse(
                        status_code=400,
                        content={"success": False, "log": f"Unsafe path: {filename}"},
                    )
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)

            # ── Resolve images: either data: URIs (inline base64) or remote URLs ──
            if request.images:
                async with httpx.AsyncClient(timeout=30) as client:
                    for img_name, img_url in request.images.items():
                        path = _safe_join(tmpdir, img_name)
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
                            # Non-fatal: log but continue — pdflatex will report
                            # a missing image rather than crashing the server
                            print(f"[compile] Could not resolve {img_name}: {img_err}")

            # ── Ensure entry file exists ──────────────────────────────────────
            entry = request.entry.replace("\\", "/").lstrip("/")
            entry_path = _safe_join(tmpdir, entry)
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

            # ── Run pdflatex (twice for cross-references) ────────────────────
            compile_log = ""
            result = None

            for pass_num in range(2):
                result = subprocess.run(
                    ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", entry_base],
                    cwd=entry_dir,
                    capture_output=True,
                    text=True,
                )
                compile_log += f"\n{'─' * 40} Pass {pass_num + 1} {'─' * 40}\n"
                compile_log += result.stdout
                compile_log += result.stderr

                if result.returncode != 0:
                    break

            # ── Run bibtex if .bib files present and first pass succeeded ─────
            bib_files = [f for f in request.files if f.endswith(".bib")]
            if bib_files and result and result.returncode == 0:
                bib_result = subprocess.run(
                    ["bibtex", os.path.splitext(entry_base)[0]],
                    cwd=entry_dir,
                    capture_output=True,
                    text=True,
                )
                compile_log += f"\n{'─' * 40} BibTeX {'─' * 40}\n"
                compile_log += bib_result.stdout
                compile_log += bib_result.stderr

                # Two more pdflatex passes to resolve bibliography references
                for pass_num in range(2):
                    result = subprocess.run(
                        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", entry_base],
                        cwd=entry_dir,
                        capture_output=True,
                        text=True,
                    )
                    compile_log += f"\n{'─' * 40} Bib Pass {pass_num + 1} {'─' * 40}\n"
                    compile_log += result.stdout
                    compile_log += result.stderr

                    if result.returncode != 0:
                        break

            # ── Check output ──────────────────────────────────────────────────
            pdf_file = os.path.join(entry_dir, os.path.splitext(entry_base)[0] + ".pdf")

            if result is None or result.returncode != 0 or not os.path.exists(pdf_file):
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "log": compile_log},
                )

            # ── Copy PDF to a stable path, return it, then clean up ───────────
            output_dir = os.path.join(tempfile.gettempdir(), "latex_output")
            os.makedirs(output_dir, exist_ok=True)

            final_pdf = os.path.join(output_dir, f"{uuid.uuid4()}.pdf")
            shutil.copy2(pdf_file, final_pdf)

            def cleanup(path=final_pdf):
                if os.path.exists(path):
                    os.remove(path)

            background_tasks.add_task(cleanup)
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
