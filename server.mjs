import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import express from 'express';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT) || 8080;
const HOST = process.env.HOST || '0.0.0.0';
const LOCK_PATH = path.join(ROOT, 'server.lock');

function pidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return err.code === 'EPERM';
  }
}

function readLockPid() {
  try {
    const n = Number(fs.readFileSync(LOCK_PATH, 'utf8').trim().split(/\s+/)[0]);
    return Number.isInteger(n) ? n : null;
  } catch {
    return null;
  }
}

function acquireLock() {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      fs.writeFileSync(LOCK_PATH, `${process.pid}\n`, { flag: 'wx' });
      return;
    } catch (err) {
      if (err.code !== 'EEXIST') throw err;
      const owner = readLockPid();
      if (owner && pidAlive(owner)) {
        console.error(`Already running (pid ${owner}). Refusing to start.`);
        process.exit(1);
      }
      try {
        fs.unlinkSync(LOCK_PATH);
      } catch (unlinkErr) {
        if (unlinkErr.code !== 'ENOENT') throw unlinkErr;
      }
    }
  }
  console.error(`Could not acquire ${LOCK_PATH}. Refusing to start.`);
  process.exit(1);
}

function releaseLock() {
  const owner = readLockPid();
  if (owner !== process.pid) return;
  try {
    fs.unlinkSync(LOCK_PATH);
  } catch (err) {
    if (err.code !== 'ENOENT') console.error(`Failed to remove lock: ${err.message}`);
  }
}

acquireLock();
process.on('exit', releaseLock);
for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(sig, () => process.exit(0));
}

function listGames() {
  return fs
    .readdirSync(ROOT, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith('.html'))
    .map((entry) => {
      const file = entry.name;
      const full = path.join(ROOT, file);
      const html = fs.readFileSync(full, 'utf8');
      const titleMatch = html.match(/<title>([^<]*)<\/title>/i);
      const title = titleMatch ? titleMatch[1].trim() : file;
      const stat = fs.statSync(full);
      return {
        file,
        href: `/${encodeURIComponent(file)}`,
        title,
        bytes: stat.size,
        mtime: stat.mtime,
      };
    })
    .sort((a, b) => a.title.localeCompare(b.title) || a.file.localeCompare(b.file));
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

function renderHome(games) {
  const cards = games
    .map(
      (g) => `
      <a class="card" href="${g.href}">
        <div class="play">Play</div>
        <h2>${escapeHtml(g.title)}</h2>
        <p class="meta"><code>${escapeHtml(g.file)}</code> · ${formatSize(g.bytes)}</p>
      </a>`
    )
    .join('');

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Game Arcade</title>
<style>
  :root {
    --bg: #12110f;
    --panel: #1c1a16;
    --ink: #f3ead7;
    --muted: #a89880;
    --line: #3a342c;
    --accent: #e8a23a;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; min-height: 100%; }
  body {
    font-family: ui-sans-serif, system-ui, "Segoe UI", sans-serif;
    background:
      radial-gradient(1200px 500px at 10% -10%, #2a2218 0%, transparent 55%),
      var(--bg);
    color: var(--ink);
    padding: 48px 24px 72px;
  }
  main { max-width: 920px; margin: 0 auto; }
  header { margin-bottom: 36px; }
  h1 { font-size: 2.1rem; letter-spacing: .04em; margin: 0 0 8px; }
  .sub { color: var(--muted); margin: 0; }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
    gap: 16px;
  }
  .card {
    display: block;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 20px 20px 18px;
    text-decoration: none;
    color: inherit;
    min-height: 148px;
    transition: transform .12s ease, border-color .12s ease;
  }
  .card:hover { transform: translateY(-2px); border-color: var(--accent); }
  .card h2 { margin: 10px 0 10px; font-size: 1.15rem; line-height: 1.3; }
  .play {
    display: inline-block;
    font-size: .72rem;
    font-weight: 700;
    letter-spacing: .12em;
    text-transform: uppercase;
    color: #1a1208;
    background: var(--accent);
    border-radius: 999px;
    padding: 3px 9px;
  }
  .meta { color: var(--muted); font-size: .85rem; margin: 0; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .empty { color: var(--muted); }
</style>
</head>
<body>
  <main>
    <header>
      <h1>Game Arcade</h1>
      <p class="sub">${games.length} game${games.length === 1 ? '' : 's'} in this folder</p>
    </header>
    ${games.length ? `<div class="grid">${cards}</div>` : '<p class="empty">No .html games found.</p>'}
  </main>
</body>
</html>`;
}

const app = express();

app.get('/', (_req, res) => {
  res.type('html').send(renderHome(listGames()));
});

app.use(express.static(ROOT, { index: false, dotfiles: 'ignore' }));

app.listen(PORT, HOST, () => {
  console.log(`Game arcade at http://127.0.0.1:${PORT}/`);
});
