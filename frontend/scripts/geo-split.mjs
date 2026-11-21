#!/usr/bin/env node
// Splits the PRG boundaries in data/ref/geo/*.geojson into per-level files the Monitoring map loads on demand.
//
//   public/geo/woj.json              16 voivodeships (one request on the landing page)
//   public/geo/pow/{woj}.json        powiats of one voivodeship (TERYT prefix, 2 digits)
//   public/geo/gmi/{pow}.json        gminas of one powiat (TERYT prefix, 4 digits)
//   public/geo/woj-labels.json       { "12": [lon, lat], ... } label point per voivodeship
//   public/geo/pow-centroids.json    { "1209": [lon, lat], ... } label point per powiat
//   public/geo/gmi-centroids.json    { "1209052": [lon, lat], ... } label point per gmina (pins and pills)
//
// No dependencies (Node 24 only). The source files are already topology-simplified, so this script
// only rounds coordinates, drops a few vertices (Douglas-Peucker, tolerance below) and drops properties
// the UI does not use. Run from the frontend folder: `node scripts/geo-split.mjs`. Outputs are committed.
//
// Properties kept: terc, name (and kind for gminas). Geometry is WGS84, as in the source.

import { mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(here, '../../data/ref/geo');
const OUT = resolve(here, '../public/geo');

const DECIMALS = 4; // about 8 m
const TOLERANCE = { woj: 0.004, pow: 0.0012, gmi: 0.0005 }; // degrees, applied on top of the source simplification

const round = (x) => Number(x.toFixed(DECIMALS));

// ---- Douglas-Peucker on one ring (keeps the closing point) ----
function sqSegDist(p, a, b) {
  let x = a[0];
  let y = a[1];
  let dx = b[0] - x;
  let dy = b[1] - y;
  if (dx !== 0 || dy !== 0) {
    const t = ((p[0] - x) * dx + (p[1] - y) * dy) / (dx * dx + dy * dy);
    if (t > 1) {
      x = b[0];
      y = b[1];
    } else if (t > 0) {
      x += dx * t;
      y += dy * t;
    }
  }
  dx = p[0] - x;
  dy = p[1] - y;
  return dx * dx + dy * dy;
}

function simplifyRing(ring, tol) {
  if (ring.length <= 5) return ring;
  const sq = tol * tol;
  const keep = new Uint8Array(ring.length);
  keep[0] = 1;
  keep[ring.length - 1] = 1;
  const stack = [[0, ring.length - 1]];
  while (stack.length) {
    const [first, last] = stack.pop();
    let max = sq;
    let idx = -1;
    for (let i = first + 1; i < last; i++) {
      const d = sqSegDist(ring[i], ring[first], ring[last]);
      if (d > max) {
        max = d;
        idx = i;
      }
    }
    if (idx > -1) {
      keep[idx] = 1;
      stack.push([first, idx], [idx, last]);
    }
  }
  const out = ring.filter((_, i) => keep[i]).map((c) => [round(c[0]), round(c[1])]);
  // a ring needs at least 4 positions to be valid; fall back to rounding only
  return out.length >= 4 ? out : ring.map((c) => [round(c[0]), round(c[1])]);
}

function simplifyGeometry(geom, tol) {
  if (geom.type === 'Polygon') {
    return { type: 'Polygon', coordinates: geom.coordinates.map((r) => simplifyRing(r, tol)) };
  }
  return {
    type: 'MultiPolygon',
    coordinates: geom.coordinates.map((poly) => poly.map((r) => simplifyRing(r, tol))),
  };
}

// ---- label point: pole of inaccessibility on the largest ring (grid search + refinement) ----
function ringArea(ring) {
  let a = 0;
  for (let i = 0, n = ring.length - 1; i < n; i++) a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
  return Math.abs(a / 2);
}

function inside(pt, ring) {
  let c = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > pt[1] !== yj > pt[1] && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
}

function distToRing(pt, ring) {
  let min = Infinity;
  for (let i = 0, n = ring.length - 1; i < n; i++) min = Math.min(min, sqSegDist(pt, ring[i], ring[i + 1]));
  return Math.sqrt(min);
}

function labelPoint(geom) {
  const polys = geom.type === 'Polygon' ? [geom.coordinates] : geom.coordinates;
  let best = polys[0];
  let bestA = -1;
  for (const p of polys) {
    const a = ringArea(p[0]);
    if (a > bestA) {
      bestA = a;
      best = p;
    }
  }
  const outer = best[0];
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of outer) {
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  }
  let cx = (minX + maxX) / 2;
  let cy = (minY + maxY) / 2;
  let bestD = -1;
  let w = maxX - minX;
  let h = maxY - minY;
  const N = 14;
  for (let round_ = 0; round_ < 4; round_++) {
    let nx = cx;
    let ny = cy;
    for (let i = 0; i <= N; i++) {
      for (let j = 0; j <= N; j++) {
        const pt = [cx - w / 2 + (w * i) / N, cy - h / 2 + (h * j) / N];
        if (!inside(pt, outer)) continue;
        if (best.slice(1).some((hole) => inside(pt, hole))) continue;
        const d = distToRing(pt, outer);
        if (d > bestD) {
          bestD = d;
          nx = pt[0];
          ny = pt[1];
        }
      }
    }
    cx = nx;
    cy = ny;
    w /= 3.5;
    h /= 3.5;
  }
  return [round(cx), round(cy)];
}

// ---- main ----
const load = (level) => JSON.parse(readFileSync(join(SRC, `${level}.geojson`), 'utf8')).features;

const toFeature = (f, level) => {
  const p = f.properties;
  const props = level === 'gmi' ? { terc: p.terc, name: p.name, kind: p.kind } : { terc: p.terc, name: p.name };
  return { type: 'Feature', properties: props, geometry: simplifyGeometry(f.geometry, TOLERANCE[level]) };
};

const write = (rel, data) => {
  const file = join(OUT, rel);
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify(data));
  return JSON.stringify(data).length;
};

rmSync(OUT, { recursive: true, force: true });
const fc = (features) => ({ type: 'FeatureCollection', features });
let total = 0;

// voivodeships
{
  const feats = load('woj');
  const labels = {};
  total += write('woj.json', fc(feats.map((f) => toFeature(f, 'woj'))));
  for (const f of feats) labels[f.properties.terc] = labelPoint(f.geometry);
  total += write('woj-labels.json', labels);
}

// powiats, grouped by voivodeship
{
  const groups = new Map();
  const labels = {};
  for (const f of load('pow')) {
    const key = f.properties.terc.slice(0, 2);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(toFeature(f, 'pow'));
    labels[f.properties.terc] = labelPoint(f.geometry);
  }
  for (const [key, feats] of groups) total += write(`pow/${key}.json`, fc(feats));
  total += write('pow-centroids.json', labels);
  console.log(`pow: ${groups.size} files`);
}

// gminas, grouped by powiat
{
  const groups = new Map();
  const labels = {};
  for (const f of load('gmi')) {
    const key = f.properties.terc.slice(0, 4);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(toFeature(f, 'gmi'));
    labels[f.properties.terc] = labelPoint(f.geometry);
  }
  for (const [key, feats] of groups) total += write(`gmi/${key}.json`, fc(feats));
  total += write('gmi-centroids.json', labels);
  console.log(`gmi: ${groups.size} files`);
}

console.log(`geo written to ${OUT}, ${(total / 1e6).toFixed(2)} MB total`);
