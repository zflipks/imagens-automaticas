const fs = require('fs').promises;
const path = require('path');
const crypto = require('crypto');

const IMAGE_EXTS = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.tiff'];
const IGNORED_DIRS = ['node_modules', '.git', '.github'];
const IGNORED_FILES = ['index.json']; // <-- ADICIONADO

async function walk(dir) {
  let results = [];
  const list = await fs.readdir(dir, { withFileTypes: true });
  for (const dirent of list) {
    const name = dirent.name;
    const full = path.join(dir, name);

    if (IGNORED_DIRS.includes(name)) continue;
    if (IGNORED_FILES.includes(name)) continue; // <-- ADICIONADO

    if (dirent.isDirectory()) {
      results = results.concat(await walk(full));
    } else {
      results.push(full);
    }
  }
  return results;
}

function isImage(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  return IMAGE_EXTS.includes(ext);
}

async function fileHash(filePath) {
  const buf = await fs.readFile(filePath);
  const hash = crypto.createHash('sha256').update(buf).digest('hex');
  return hash;
}

async function statSafe(p) {
  try {
    return await fs.stat(p);
  } catch (e) {
    return null;
  }
}

async function main() {
  const repoRoot = process.cwd();
  const allFiles = await walk(repoRoot);
  const imageFiles = allFiles.filter(isImage);

  const items = [];
  for (const f of imageFiles) {
    const rel = path.relative(repoRoot, f).replace(/\\/g, '/');
    const st = await statSafe(f);
    if (!st) continue;
    const hash = await fileHash(f);
    items.push({
      path: rel,
      size: st.size,
      mtime: st.mtime.toISOString(),
      sha256: hash
    });
  }

  // sort for deterministic output
  items.sort((a, b) => a.path.localeCompare(b.path));

  const outPath = path.join(repoRoot, 'index.json');
  const json = JSON.stringify({ generated_at: new Date().toISOString(), images: items }, null, 2) + '\n';
  await fs.writeFile(outPath, json, 'utf8');
  console.log(`Wrote ${items.length} images to index.json`);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
