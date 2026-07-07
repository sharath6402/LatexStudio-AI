const vscode = require('vscode');
const path = require('path');
const fs = require('fs');
const http = require('http');
const https = require('https');

const TEX_EXTS = ['.tex', '.bib', '.cls', '.sty'];
const IMAGE_MIME = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.pdf': 'application/pdf',
};

let panel;

function activate(context) {
  const disposable = vscode.commands.registerCommand(
    'latexAiPreview.compileAndPreview',
    () => compileAndPreview(context)
  );
  context.subscriptions.push(disposable);
}

async function compileAndPreview(context) {
  const editor = vscode.window.activeTextEditor;
  if (!editor || path.extname(editor.document.uri.fsPath).toLowerCase() !== '.tex') {
    vscode.window.showErrorMessage('Open a .tex file to preview.');
    return;
  }

  const entryPath = editor.document.uri.fsPath;
  const dir = path.dirname(entryPath);
  const entryName = path.basename(entryPath);

  const files = {};
  const images = {};

  let entries;
  try {
    entries = fs.readdirSync(dir);
  } catch (err) {
    vscode.window.showErrorMessage(`Could not read project folder: ${err.message}`);
    return;
  }

  for (const name of entries) {
    const full = path.join(dir, name);
    if (!fs.statSync(full).isFile()) continue;
    const ext = path.extname(name).toLowerCase();

    if (TEX_EXTS.includes(ext)) {
      const openDoc = vscode.workspace.textDocuments.find((d) => d.uri.fsPath === full);
      files[name] = openDoc ? openDoc.getText() : fs.readFileSync(full, 'utf8');
    } else if (IMAGE_MIME[ext]) {
      const data = fs.readFileSync(full);
      images[name] = `data:${IMAGE_MIME[ext]};base64,${data.toString('base64')}`;
    }
  }

  const backendUrl = vscode.workspace
    .getConfiguration('latexAiPreview')
    .get('backendUrl', 'http://127.0.0.1:8000');

  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: 'LaTeX AI: Compiling…' },
    async () => {
      try {
        const pdfBuffer = await postCompile(`${backendUrl}/compile`, JSON.stringify({
          files,
          images,
          entry: entryName,
        }));
        showPdfPreview(context, pdfBuffer, entryName);
      } catch (err) {
        vscode.window.showErrorMessage(`LaTeX compile failed: ${err.message}`);
      }
    }
  );
}

function postCompile(url, body) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : http;
    const req = mod.request(
      url,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(body),
        },
      },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          const buf = Buffer.concat(chunks);
          if (res.statusCode !== 200) {
            let msg = `HTTP ${res.statusCode}`;
            try {
              const parsed = JSON.parse(buf.toString('utf8'));
              msg = parsed.log || msg;
            } catch {
              // response wasn't JSON; keep the generic HTTP status message
            }
            reject(new Error(msg));
          } else {
            resolve(buf);
          }
        });
      }
    );
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

function showPdfPreview(context, pdfBuffer, title) {
  if (!panel) {
    panel = vscode.window.createWebviewPanel(
      'latexAiPreview',
      'LaTeX Preview',
      vscode.ViewColumn.Beside,
      { enableScripts: true, retainContextWhenHidden: true }
    );
    panel.onDidDispose(() => {
      panel = undefined;
    });
  } else {
    panel.reveal(vscode.ViewColumn.Beside, true);
  }
  panel.title = `Preview: ${title}`;

  const mediaDir = vscode.Uri.file(path.join(context.extensionPath, 'media'));
  const pdfJsUri = panel.webview.asWebviewUri(vscode.Uri.joinPath(mediaDir, 'pdf.min.js'));
  const workerUri = panel.webview.asWebviewUri(vscode.Uri.joinPath(mediaDir, 'pdf.worker.min.js'));

  panel.webview.html = getHtml(panel.webview.cspSource, pdfJsUri, workerUri, pdfBuffer.toString('base64'));
}

function getHtml(cspSource, pdfJsUri, workerUri, base64Pdf) {
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${cspSource} data:; style-src ${cspSource} 'unsafe-inline'; script-src ${cspSource} 'unsafe-inline';">
<style>
  html, body { margin:0; padding:0; height:100%; background:#525659; }
  #container { width:100%; height:100vh; overflow:auto; text-align:center; }
  canvas { margin:10px auto; display:block; box-shadow:0 0 8px rgba(0,0,0,0.5); }
  #status { color:#ddd; font-family:sans-serif; padding:20px; }
</style>
</head>
<body>
<div id="status">Rendering PDF…</div>
<div id="container"></div>
<script src="${pdfJsUri}"></script>
<script>
  const pdfjsLib = window['pdfjsLib'];
  pdfjsLib.GlobalWorkerOptions.workerSrc = "${workerUri}";

  const raw = atob("${base64Pdf}");
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);

  const statusEl = document.getElementById('status');
  const container = document.getElementById('container');

  pdfjsLib.getDocument({ data: bytes }).promise.then(async (pdf) => {
    statusEl.style.display = 'none';
    for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
      const page = await pdf.getPage(pageNum);
      const viewport = page.getViewport({ scale: 1.3 });
      const canvas = document.createElement('canvas');
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      container.appendChild(canvas);
      const ctx = canvas.getContext('2d');
      await page.render({ canvasContext: ctx, viewport }).promise;
    }
  }).catch((err) => {
    statusEl.textContent = 'Failed to render PDF: ' + err.message;
  });
</script>
</body>
</html>`;
}

function deactivate() {}

module.exports = { activate, deactivate };
