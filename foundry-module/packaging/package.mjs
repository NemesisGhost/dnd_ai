#!/usr/bin/env node
/**
 * Dependency-free packaging: zips `module.json` plus every runtime asset
 * directory (`scripts/`, `styles/`, `templates/`, `lang/`) into
 * `dist/foundry-dnd-ai-<version>.zip` — the reproducible "build" step
 * for a module that ships as native ES modules with no compilation.
 * Deliberately never includes `test/`, `build/`, `package.json`, or
 * `README.md` in the zip: those aren't part of what Foundry installs.
 *
 * Implements the ZIP format's STORE (uncompressed) method directly —
 * these are a handful of small text files, so compression buys nothing
 * worth a dependency (or hand-rolled DEFLATE) for. CRC-32 is the one
 * piece of real algorithmic work here; the table-based implementation
 * below is the standard, well-known one (IEEE 802.3 polynomial
 * 0xEDB88320), directly unit-tested in `test/package.test.mjs` against
 * known CRC-32 values.
 */

import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const MODULE_ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const RUNTIME_DIRS = ["scripts", "styles", "templates", "lang"];
const RUNTIME_FILES = ["module.json"];

const CRC32_TABLE = buildCrc32Table();

function buildCrc32Table() {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[n] = c >>> 0;
  }
  return table;
}

export function crc32(buffer) {
  let crc = 0xffffffff;
  for (let i = 0; i < buffer.length; i += 1) {
    crc = CRC32_TABLE[(crc ^ buffer[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function dosDateTime() {
  // Fixed, deterministic timestamp (2026-01-01 00:00:00) rather than
  // "now" — makes package output byte-for-byte reproducible across
  // runs, which is the whole point of calling this step "reproducible."
  return { time: 0, date: (2026 - 1980) << 9 | (1 << 5) | 1 };
}

/**
 * @param {{path: string, data: Buffer}[]} entries - `path` uses forward
 *   slashes, relative to the zip root (e.g. "scripts/main.mjs").
 * @returns {Buffer}
 */
export function createZip(entries) {
  const { time, date } = dosDateTime();
  const localChunks = [];
  const centralChunks = [];
  let offset = 0;

  for (const entry of entries) {
    const nameBytes = Buffer.from(entry.path, "utf8");
    const dataCrc = crc32(entry.data);
    const size = entry.data.length;

    const localHeader = Buffer.alloc(30);
    localHeader.writeUInt32LE(0x04034b50, 0);
    localHeader.writeUInt16LE(20, 4); // version needed
    localHeader.writeUInt16LE(0, 6); // flags
    localHeader.writeUInt16LE(0, 8); // method: STORE
    localHeader.writeUInt16LE(time, 10);
    localHeader.writeUInt16LE(date, 12);
    localHeader.writeUInt32LE(dataCrc, 14);
    localHeader.writeUInt32LE(size, 18); // compressed size
    localHeader.writeUInt32LE(size, 22); // uncompressed size
    localHeader.writeUInt16LE(nameBytes.length, 26);
    localHeader.writeUInt16LE(0, 28); // extra field length

    localChunks.push(localHeader, nameBytes, entry.data);

    const centralHeader = Buffer.alloc(46);
    centralHeader.writeUInt32LE(0x02014b50, 0);
    centralHeader.writeUInt16LE(20, 4); // version made by
    centralHeader.writeUInt16LE(20, 6); // version needed
    centralHeader.writeUInt16LE(0, 8); // flags
    centralHeader.writeUInt16LE(0, 10); // method: STORE
    centralHeader.writeUInt16LE(time, 12);
    centralHeader.writeUInt16LE(date, 14);
    centralHeader.writeUInt32LE(dataCrc, 16);
    centralHeader.writeUInt32LE(size, 20);
    centralHeader.writeUInt32LE(size, 24);
    centralHeader.writeUInt16LE(nameBytes.length, 28);
    centralHeader.writeUInt16LE(0, 30); // extra field length
    centralHeader.writeUInt16LE(0, 32); // comment length
    centralHeader.writeUInt16LE(0, 34); // disk number start
    centralHeader.writeUInt16LE(0, 36); // internal attributes
    centralHeader.writeUInt32LE(0, 38); // external attributes
    centralHeader.writeUInt32LE(offset, 42); // relative offset of local header

    centralChunks.push(centralHeader, nameBytes);

    offset += localHeader.length + nameBytes.length + entry.data.length;
  }

  const centralDirectory = Buffer.concat(centralChunks);
  const centralDirectoryOffset = offset;

  const endRecord = Buffer.alloc(22);
  endRecord.writeUInt32LE(0x06054b50, 0);
  endRecord.writeUInt16LE(0, 4); // disk number
  endRecord.writeUInt16LE(0, 6); // disk with central directory
  endRecord.writeUInt16LE(entries.length, 8); // entries on this disk
  endRecord.writeUInt16LE(entries.length, 10); // total entries
  endRecord.writeUInt32LE(centralDirectory.length, 12);
  endRecord.writeUInt32LE(centralDirectoryOffset, 16);
  endRecord.writeUInt16LE(0, 20); // comment length

  return Buffer.concat([...localChunks, centralDirectory, endRecord]);
}

async function collectFiles(rootDir, relativeDir) {
  const absoluteDir = path.join(rootDir, relativeDir);
  const dirents = await readdir(absoluteDir, { withFileTypes: true });
  const files = [];
  for (const dirent of dirents) {
    const relativePath = path.posix.join(relativeDir, dirent.name);
    if (dirent.isDirectory()) {
      files.push(...(await collectFiles(rootDir, relativePath)));
    } else if (dirent.isFile()) {
      files.push(relativePath);
    }
  }
  return files;
}

export async function buildPackageEntries(moduleRoot = MODULE_ROOT) {
  const relativePaths = [...RUNTIME_FILES];
  for (const dir of RUNTIME_DIRS) {
    const dirStat = await stat(path.join(moduleRoot, dir)).catch(() => null);
    if (dirStat?.isDirectory()) {
      relativePaths.push(...(await collectFiles(moduleRoot, dir)));
    }
  }
  relativePaths.sort(); // deterministic entry order
  const entries = [];
  for (const relativePath of relativePaths) {
    const data = await readFile(path.join(moduleRoot, relativePath));
    entries.push({ path: relativePath.split(path.sep).join("/"), data });
  }
  return entries;
}

async function main() {
  const moduleJson = JSON.parse(await readFile(path.join(MODULE_ROOT, "module.json"), "utf8"));
  const entries = await buildPackageEntries(MODULE_ROOT);
  const zipBuffer = createZip(entries);

  const distDir = path.join(MODULE_ROOT, "dist");
  await mkdir(distDir, { recursive: true });
  const outputPath = path.join(distDir, `foundry-dnd-ai-${moduleJson.version}.zip`);
  await writeFile(outputPath, zipBuffer);

  const sha256 = createHash("sha256").update(zipBuffer).digest("hex");
  console.log(`Packaged ${entries.length} files into ${outputPath} (${zipBuffer.length} bytes)`);
  console.log(`sha256: ${sha256}`);
}

// Windows argv[1] is a plain filesystem path ("C:\...") while
// import.meta.url is always a properly-encoded file:// URL
// ("file:///C:/...") — a naive string-concatenation comparison never
// matches on Windows. pathToFileURL() normalizes both sides to the same
// URL form regardless of platform.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
