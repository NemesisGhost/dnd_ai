import assert from "node:assert/strict";
import { test } from "node:test";
import { createZip, crc32 } from "../packaging/package.mjs";

test("crc32 matches the well-known reference values", () => {
  assert.equal(crc32(Buffer.from("")), 0x00000000);
  assert.equal(crc32(Buffer.from("123456789")), 0xcbf43926);
});

test("createZip produces a buffer with the correct local/central/end-of-central signatures", () => {
  const entries = [
    { path: "module.json", data: Buffer.from('{"id":"dnd-ai-adapter"}') },
    { path: "scripts/main.mjs", data: Buffer.from("export const x = 1;") },
  ];
  const zip = createZip(entries);

  // Local file header signature at the very start.
  assert.equal(zip.readUInt32LE(0), 0x04034b50);
  // End-of-central-directory signature is always the final 22 bytes.
  const eocd = zip.subarray(zip.length - 22);
  assert.equal(eocd.readUInt32LE(0), 0x06054b50);
  assert.equal(eocd.readUInt16LE(8), entries.length); // entries on this disk
  assert.equal(eocd.readUInt16LE(10), entries.length); // total entries
  // Central directory contains one 0x02014b50 signature per entry.
  const centralDirSignatures = countOccurrences(zip, Buffer.from([0x50, 0x4b, 0x01, 0x02]));
  assert.equal(centralDirSignatures, entries.length);
});

test("createZip is byte-for-byte reproducible across calls with the same input", () => {
  const entries = [{ path: "module.json", data: Buffer.from('{"id":"x"}') }];
  const first = createZip(entries);
  const second = createZip(entries);
  assert.deepEqual(first, second);
});

test("createZip embeds every file's exact bytes, retrievable by scanning entries", () => {
  const payload = Buffer.from("export const value = 42;\n");
  const zip = createZip([{ path: "scripts/main.mjs", data: payload }]);
  assert.ok(zip.includes(payload));
});

function countOccurrences(buffer, needle) {
  let count = 0;
  let index = buffer.indexOf(needle);
  while (index !== -1) {
    count += 1;
    index = buffer.indexOf(needle, index + 1);
  }
  return count;
}
