// Make a new license key and print the command that registers it.
//   node tools/new-license.mjs "beta: wedding tester" [monthly cap]
// The key is shown once. Only its hash goes into the database.
import { createHash, randomInt } from "node:crypto";

const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // no 0/O or 1/I
const label = process.argv[2];
const cap = process.argv[3] ? Number(process.argv[3]) : null;
if (!label || /['"]/.test(label) || (cap !== null && !Number.isInteger(cap))) {
  console.error('usage: node tools/new-license.mjs "label without quotes" [monthly cap]');
  process.exit(1);
}
const group = () => Array.from({ length: 5 }, () => ALPHABET[randomInt(ALPHABET.length)]).join("");
const key = ["CULL", group(), group(), group(), group()].join("-");
const hash = createHash("sha256").update(key).digest("hex");
const sql = `INSERT INTO licenses (key_hash, label, monthly_cap) VALUES ('${hash}', '${label}', ${cap ?? "NULL"})`;
console.log(`License key (give this to the user):\n  ${key}\n`);
console.log(`Register it:\n  npx wrangler d1 execute cull --remote --command "${sql}"`);
