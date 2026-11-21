# Deploying ex ante to linek.dev

Target: a Coolify Docker Compose resource on the database VM (`root@212.127.90.86`), built from GitHub on push,
the same way as Mieszkaniownik. Only `web` is public. Rehearsal: Sun 00:00 to 02:00. Final restore: 07:30, live by 08:15.

Files: `infra/docker-compose.prod.yml`, `infra/Dockerfile.web`, `infra/Caddyfile`, `infra/Dockerfile.backend` (api, worker, migrate),
`scripts/deploy/{dump_db,restore_db,sync_data}.sh`.

```
browser -> Coolify Traefik (TLS) -> web (Caddy: Vite build + /api proxy) -> api:8000 -> db:5432
                                                                    worker -> db
```

## 0. Decisions needed from you

1. **Domain.** Suggested: `exante.linek.dev` (`*.linek.dev` already resolves to 145.239.90.205).
2. **WCSS key on the server:** approved (section 9). Sovereign mode is optional; without it confidential uploads return 503.
3. A **separate restricted Gemini key** for the server (Generative Language API only, budget alert).
4. **Repo access.** The repo is private until Sun ~10:15. Coolify needs a GitHub deploy key or the GitHub app on `dawidlinek/hacknation-risk-miner` (same as for Mieszkaniownik).

## 1. Prepare the server (once)

```bash
ssh root@212.127.90.86 'mkdir -p /srv/exante/{pg,dump,data/raw,data/ref,exports,hf,config} && df -h /srv && free -g'
```

Check free disk: you need about 3 GB for the dump, about 12 GB for Postgres, about 4 GB for the PDFs.
Postgres 18 runs as uid 999 and initialises `/srv/exante/pg` itself on first start.

## 2. Create the Coolify resource

1. Project, **New resource**, **Docker Compose** (Git source: GitHub), repo `dawidlinek/hacknation-risk-miner`, branch `main`.
2. **Compose file location:** `infra/docker-compose.prod.yml`. Base directory `/`.
3. Server: the database VM. Network: the existing `coolify` network (the compose file declares it as external).
4. **Domain** on the `web` service only: `https://exante.linek.dev:80` (Caddy listens on 80, Traefik does TLS). Leave `db`, `api`, `worker`, `migrate` without a domain.
5. Environment variables (Coolify **Environment** tab; mark secrets as such):

| Variable | Value |
|---|---|
| `POSTGRES_PASSWORD` | long random string (secret) |
| `POSTGRES_USER`, `POSTGRES_DB` | optional, default `riskminer` |
| `RISKMINER_USERS` | not needed: login is one-click demo personas (juror, ekspert, administrator), no passwords. Leave empty |
| `RISKMINER_SESSION_SECRET` | `openssl rand -hex 32` (secret) |
| `RISKMINER_COOKIE_SECURE` | `true` (default) |
| `GEMINI_API_KEY` | the restricted server key (secret) |
| `WCSS_VLLM_KEY` | only if WCSS is allowed, else leave empty |
| `HF_TOKEN` | optional |
| `RISKMINER_BASIC_AUTH` | optional whole-site `user:password` during private preview, empty for the jury |

Feature flags, sensitivity routing and the LLM tasks table are not env vars: they live in `config.yaml` (section 3).
`SOURCE_COMMIT` (git sha) is filled by Coolify and shown as `GIT_SHA`.

Do **not** deploy yet if the `db` dir is empty and you want the dump restored first; the first deploy is fine though: `migrate` builds the schema and `restore_db.sh` replaces it afterwards.

## 3. Ship config and data (rsync, resumable)

```bash
scripts/deploy/sync_data.sh root@212.127.90.86 --dry-run   # check
scripts/deploy/sync_data.sh root@212.127.90.86             # ~3.1 GB docs_22 + data/ref + config
```

This sends `data/raw/docs_22`, `data/ref`, and `config/config.yaml` (falls back to `config.example.yaml`) to `/srv/exante/`.
An existing server config is not overwritten unless `--force-config`. Then edit `/srv/exante/config/config.yaml` on the server:

- Edits to this file take effect within about a second, with no restart or redeploy (the API re-reads it when its mtime or size changes; an unparsable file keeps the last good config). The file is mounted read-only in the containers, so edit it on the host.
- `features:` set exactly the flags that are finished (unfinished stay `false`).
- `api.cors_origins`: not needed, same origin. `api.serve_fixtures: false` so unfinished stubs answer 501 rather than fake data (check with the backend owners).
- `llm.demo_replay_fallback: false`.
- Sensitivity routing is the `llm.tasks` table: tasks without a `confidential:` entry refuse confidential input. Without WCSS, remove the `confidential:` entries (or keep them, the call then fails closed with the "model suwerenny niedostepny" message).
- If sovereign mode is used, set the two WCSS `base_url` values as in section 9.

Checking that the sync completed (both ends; `sync_data.sh` prints nothing about checksums):

```bash
# local
(cd data/raw/docs_22 && find . -type f | wc -l && du -sb . | cut -f1 && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)
(cd data/ref && find . -type f | wc -l && du -sb . | cut -f1 && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)
# server: run the same three commands inside /srv/exante/data/raw/docs_22 and /srv/exante/data/ref
ssh root@212.127.90.86 'cd /srv/exante/data/raw/docs_22 && find . -type f | wc -l && du -sb . | cut -f1 && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum'
```

The file count, byte size and the final hash must match on both ends. (`du -sb` counts directories too; a small difference in size with equal count and hash is fine.)
The server has no `rsync`, so `sync_data.sh` uses tar over ssh, which cannot resume. If it broke, just run it again: it overwrites files in place and the result is identical. To make it resumable and delta-only, install rsync on the server (`apt-get install -y rsync`) and re-run; the script then uses it automatically.

Never ship: `docs_sample`, `bzp_roads` raw, `data/archive`, `data/ocr`, `materials/bzp_kopia`. The viewer falls back to page text plus the source URL when a PDF is missing.

Run it during the rehearsal so the 07:30 run sends only the delta.

## 4. Dump locally, then restore

Local dev DB must be running (`docker compose -f infra/docker-compose.yml up -d db`).

```bash
scripts/deploy/dump_db.sh                      # data/snapshots/demo_freeze.dump; prints size and sha256
scripts/deploy/restore_db.sh root@212.127.90.86
```

`dump_db.sh`: `pg_dump -Fc --compress=zstd:3`, nothing excluded by default (`job` and `llm_call` are FK targets, so excluding them breaks `pg_restore`); `EXCLUDE_DATA="table1 table2"` skips the data of other tables, schema kept.
`restore_db.sh` copies the dump to `/srv/exante/dump`, prints the remote sha256 (compare with the local one), stops api and worker, drops and recreates the database, creates the extensions, runs `pg_restore -j 8 --no-owner --no-privileges`, runs `ANALYZE`, prints the alembic version and the notice count, and starts api and worker again. It asks for confirmation (`YES=1` skips). Measured on the rehearsal dump (2026-11-21, full national data, nothing excluded): `data/snapshots/demo_rehearsal_20261121_2110.dump`, 1.3 GB (1,300,349,471 bytes), dump 44 s, sha256 `825180793834630fc1ab55211760602298687f1a637608914b7c5ff2356e2a61`; 51 tables with data, `alembic_version` = `0009_review`, `0013_alerts` (the earlier 20:28 dump had a redundant `0008_question` row that made `alembic upgrade heads` fail with an overlap error; if you ever restored it, run `DELETE FROM alembic_version WHERE version_num = '0008_question';` and migrate). Restore time on the server is still to be measured. Plan for up to 15 min dump (more once embeddings are filled), a transfer at your uplink speed, 15 to 30 min restore (HNSW builds). Note the times in the rehearsal.

The first restore needs the `db` container to exist, so deploy the Coolify resource once before it.
After the restore the schema comes from the dump (`alembic_version` included); `migrate` on the next deploy is then a no-op or applies newer migrations.

Post-restore cleanup from verification section 4.3 (test audit rows) is not scripted here. Run it by hand through the db container if the lead asks for it:

```bash
ssh root@212.127.90.86 'docker exec -i $(docker ps -qf label=exante.role=db) psql -U riskminer riskminer'
```

## 5. Deploy and health checks

Coolify, **Deploy**. Order: `db` healthy, `migrate` completes, `api` healthy, `web` up. Then:

```bash
curl -fsS https://exante.linek.dev/api/health          # {"status":"ok","notices":N}
curl -fsSI https://exante.linek.dev/ | head -3          # 200, HTML
ssh root@212.127.90.86 'docker ps --format "{{.Names}}\t{{.Status}}" | grep -iE "exante|api-|worker-|web-|db-|migrate-"'
```

Public checks: `db`, `api`, `worker` must not appear in `docker ps` with a published port (`0.0.0.0:`), and `curl http://212.127.90.86:8000` and `:5432` must fail from outside.

## 6. Smoke test

1. Open the site: Monitoring and Nowa inwestycja load without login.
2. `POST /api/auth/login` through the UI as a demo persona (juror), the reviewer name shows in the header; cookie `rm_session` is `Secure`, `HttpOnly`.
3. A write route without login answers 401: `curl -i -X POST https://exante.linek.dev/api/review -H 'X-Requested-With: ex-ante'`.
4. **Flow 1:** Nowa inwestycja, pick a sample, run the analysis, open the report, open a source document PDF (served from `/srv/exante/data/raw/docs_22`).
5. **Export:** the CSV/Pakiet export downloads (needs `/srv/exante/exports` writable).
6. Zapytaj returns an answer (Gemini key works); logs show no 5xx.
7. Reload the page on a deep link (SPA fallback works), and check the browser console for failed `/api` calls.

Logs: Coolify UI, or `docker logs <container>` on the server.

## 7. Demo baseline and reset between jurors

Once the final restore is done and the demo data is final, record the baseline **on the server** (never on the local main DB):

```bash
scripts/deploy/demo_reset.sh root@212.127.90.86 baseline
```

(same thing through the API as an admin persona: `POST /api/admin/demo-baseline`).

Between jurors:

```bash
scripts/deploy/demo_reset.sh root@212.127.90.86 status   # decisions made since the baseline
scripts/deploy/demo_reset.sh root@212.127.90.86 reset    # asks for confirmation
```

API equivalents (admin session, header `X-Requested-With: ex-ante`): `GET /api/admin/demo-status`, `POST /api/admin/demo-reset` with `{"dry_run": true}` to preview, then without it.
Reset reverts review decisions, links, catalogue proposals and gold examples made after the baseline with compensating rows; `audit_log` stays append-only.
Not covered: analyses and questions created by visitors, monitoring watches, uploads.
This is a deliberate exception to "no reset during judging" below: use it between jurors, never to undo a juror's work while they are in the session.

## 8. Rollback and fallback ladder

1. **Bad code:** in Coolify redeploy the previous commit (Deployments tab, or revert on `main`). Takes 2 to 3 min; the DB is untouched.
2. **Bad data:** run `restore_db.sh` again with the last good dump. Only if the data is broken, never to undo jury actions (their edits are the evidence).
3. **Server down:** repoint the DNS record of `exante.linek.dev` to another host built from the same repo and dump, or start the cloudflared standby on the home host and post that URL.
4. **Everything down:** the fallback video, screenshots and the run instructions in the README.

## 9. Sovereign mode on the server (optional)

Optional: if WCSS is not up during judging, prod runs fine without it. Confidential uploads then return **503** `sovereign_unavailable` ("Model w Polsce jest niedostepny, dokument czeka w kolejce."), which is honest and acceptable; public input is unaffected (Gemini). Confidential input is never sent to Gemini. Owner of the details: session be-llm (source: `side-session-notes/.../sovereign-prod-relay.md`). The user approved a dedicated WCSS key on the server; nothing below is set up yet.

**What runs where.** On WCSS a SLURM job `rm-sovereign` (`~/riskminer-serve/serve.sbatch`, 1 H100) serves Bielik 11B as `bielik-11b` (node port 8000) and PLLuM 12B as `pllum-12b` (8001), and writes `$PD/riskminer-llm/serve/endpoint.txt`. The WCSS login node cannot reach compute node ports, so a plain `ssh -L` does not work. On the server host a `relay.py` (a byte pump via `srun --overlap` over one ControlMaster SSH connection) exposes the models on the docker bridge. It re-reads the endpoint file every minute, so a resubmitted job needs no restart. `relay.py` lives in the other HackNation repo (`hacknation-cyfryzacja-formularzy/deploy/wcss/relay.py`); copy it to `/opt/riskminer/relay.py` on the server (vendoring it into this repo is the user's call).

1. **Unprivileged user and key** (dedicated, revocable, no passphrase prompts):

```bash
useradd -m rmrelay
sudo -u rmrelay ssh-keygen -t ed25519 -f ~rmrelay/.ssh/wcss_relay -N '' -C 'exante-relay'
```

On WCSS add the public key to `~/.ssh/authorized_keys` as `from="<server public IP>",restrict ssh-ed25519 AAAA... exante-relay`. Revoke by deleting that line. Adding a key to the WCSS account is the account owner's step.

2. `~rmrelay/.ssh/config`:

```
Host wcss
  HostName ui.wcss.pl
  User <wcss user>
  IdentityFile ~/.ssh/wcss_relay
  IdentitiesOnly yes
  BatchMode yes
  NumberOfPasswordPrompts 0
  ServerAliveInterval 30
  ServerAliveCountMax 4
  ControlMaster auto
  ControlPath ~/.ssh/cm-%r@%h-%p
  ControlPersist 10m
```

Test once: `sudo -u rmrelay ssh wcss true` must return without any prompt. Never loop failed logins (repeated logins get the IP blocked, three failed password logins lock the account for 24 h).

3. **systemd unit** `/etc/systemd/system/riskminer-relay.service`:

```ini
[Unit]
Description=ex ante sovereign LLM relay (WCSS vLLM -> docker bridge)
After=network-online.target docker.service
Wants=network-online.target

[Service]
User=rmrelay
ExecStartPre=/bin/sh -c 'ssh -O check wcss 2>/dev/null || ssh -f -N wcss'
ExecStart=/usr/bin/python3 /opt/riskminer/relay.py --bind 172.17.0.1 --offset 100 --endpoint /lustre/pd03/hpc-dawlin1140-1773687823/riskminer-llm/serve/endpoint.txt
Restart=on-failure
RestartSec=120
StartLimitIntervalSec=3600
StartLimitBurst=5

[Install]
WantedBy=multi-user.target
```

`systemctl enable --now riskminer-relay`; logs `journalctl -u riskminer-relay -f`.

4. **Ports and firewall.** The relay listens on the docker bridge only: `172.17.0.1:8100` (bielik-11b) and `172.17.0.1:8101` (pllum-12b). Never bind 0.0.0.0.

```bash
ufw allow from 172.16.0.0/12 to 172.17.0.1 port 8100:8101 proto tcp
```

`api` and `worker` already have `extra_hosts: host.docker.internal:host-gateway`. If the Coolify network is not on the default bridge, use that bridge's gateway address for `--bind` and the ufw rule.

5. **Config on the server** (`/srv/exante/config/config.yaml`, `llm.providers`; models `sovereign: wcss_bielik:bielik-11b`, `sovereign_alt: wcss_pllum:pllum-12b` as in `config.example.yaml`):

```yaml
    wcss_bielik: {kind: openai_compatible, base_url: "http://host.docker.internal:8100/v1", api_key_env: WCSS_VLLM_KEY, data_location: "PL (WCSS Wroclaw)", sovereign: true}
    wcss_pllum:  {kind: openai_compatible, base_url: "http://host.docker.internal:8101/v1", api_key_env: WCSS_VLLM_KEY, data_location: "PL (WCSS Wroclaw)", sovereign: true}
```

6. **Key for the models.** `WCSS_VLLM_KEY` is a Coolify secret (api and worker), value = contents of `$PD/riskminer-llm/.api_key` on WCSS. Never in the image, compose file or logs. The relay does not need it.

**Verify**

```bash
ssh wcss 'squeue -u $USER -n rm-sovereign -o "%.10i %.8T %R"; cat /lustre/pd03/hpc-dawlin1140-1773687823/riskminer-llm/serve/endpoint.txt'
curl -s -H "Authorization: Bearer $WCSS_VLLM_KEY" http://172.17.0.1:8100/v1/models          # on the host
docker exec $(docker ps -qf label=exante.role=api) curl -s -H "Authorization: Bearer $WCSS_VLLM_KEY" http://host.docker.internal:8100/v1/models
curl -s -X POST -H 'X-Requested-With: ex-ante' -b <admin cookie> https://exante.linek.dev/api/settings/llm/providers/wcss_bielik/health
```

The last call runs the known-answer test; Ustawienia then shows `wcss_bielik` up with `kat_passed: true`. The gateway re-runs it (cached 60 s) before confidential calls.

**When WCSS is down.** All sovereign hops fail, so confidential input answers 503 `sovereign_unavailable`; Red Pen jobs end with status `sovereign_unavailable` per document. The WCSS job has a 12 h time limit; the relay waits for the next job's endpoint file. Cancel when not needed (shared GPU-hours): `ssh wcss scancel <jobid>`. The job (6385732 at the time of writing) was still pending, estimated start up to Mon 08:40.

## 10. Notes

- The repo goes public Sun ~10:15; nothing secret is in it. All secrets live in Coolify env and `/srv/exante/config`.
- Each push to `main` auto-deploys and replaces api, worker and web. Turn off auto-deploy in Coolify after the final deploy so a late commit cannot change the submitted app.
- No reset during judging. Uploads and expert edits persist in the DB and `/srv/exante/data`.
- Container healthchecks: db `pg_isready`, api `/api/health`, web `wget /`.
