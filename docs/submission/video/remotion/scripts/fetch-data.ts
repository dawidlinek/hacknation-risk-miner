/**
 * Snapshots the live numbers the captions quote, from the production API, into src/data.json.
 * Responsibility: every number on a title card comes from here (with its n), never typed by hand.
 * Fails loudly if a field is missing. Idempotency: overwrites src/data.json.
 */
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ORIGIN = process.env.ORIGIN ?? 'https://exante.linek.dev';
const out = join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'data.json');

const get = async (path: string): Promise<any> => {
  const r = await fetch(`${ORIGIN}${path}`, { headers: { 'user-agent': 'ex-ante-demo-video' } });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
};

const h = await get('/api/analytics/headline');
const need = (v: any, name: string): any => {
  if (v === undefined || v === null) throw new Error(`missing ${name}`);
  return v;
};
const mln = (amount: string) => Math.round(Number(amount) / 1e6);
const data = {
  fetchedAt: new Date().toISOString(),
  dataAsOf: need(h.data_as_of, 'data_as_of'),
  sentence: need(h.sentence, 'sentence'),
  completed: { value: need(h.completed.value, 'completed'), display: h.completed.display, n: h.completed.prov.n },
  lateShare: { value: need(h.late_share.value, 'late_share'), display: h.late_share.display, n: h.late_share.prov.n },
  delayDays: { value: need(h.delay_days_total.value, 'delay'), display: h.delay_days_total.display, n: h.delay_days_total.prov.n },
  overpaidMln: { value: mln(need(h.overpaid.money.amount, 'overpaid')), n: h.overpaid.prov.n, vat: h.overpaid.money.vat_basis },
  designBuild: h.chips.design_build,
  buildOnly: h.chips.build_only,
};
writeFileSync(out, `${JSON.stringify(data, null, 2)}\n`);
console.log(JSON.stringify(data, null, 2));
