# Storage & installer notes — recipe data (planned work)

Status: planning notes. Nothing here is implemented yet. Source context:
recipes live in a single SQLite file (`pantry.db`, tables `recipes` + `ingredients`
with `recipe_id` FK and `item_id` links into the items catalog).

## Current state

- Local dev: `backend/data/pantry.db` (env var `PANTRY_DB` overrides).
- Docker: `PANTRY_DB=/data/pantry.db` in-image, persisted via the **named volume**
  `pantry-data` (see `docker-compose.yml:8`, `Dockerfile` `VOLUME /data`).
- Risk: `docker compose down -v` or volume pruning deletes recipes silently. No
  backup exists. `docker compose up --build` (app updates) is safe; only additive
  schema migrations run (`init_db()` in `backend/app/db.py` uses
  `CREATE TABLE IF NOT EXISTS` + PRAGMA-checked `ALTER TABLE ADD COLUMN`).

## What to change for an installer

1. **Bind mount instead of named volume.** In `docker-compose.yml`, replace
   `pantry-data:/data` with `./data:/data` (host path next to the compose file,
   like the dev layout). Recipes then sit in a plain folder the user can back up
   with any file-based backup; container rebuilds/reinstalls never touch it.
   - Installs over existing named-volume setups need a one-time migrate step
     (copy `pantry.db` out of the old volume into `./data/`) — document it,
     don't auto-migrate in the installer.
2. **Backup on install.** Ship a default backup mechanism the installer enables:
   a `docker compose` sidecar or cron/systemd timer running
   `sqlite3 /data/pantry.db ".backup /data/backups/pantry-YYYYMMDD.db"` (safe
   against concurrent writes; `sqlite3` must exist in the image — add to
   `apt-get install` in the Dockerfile). Keep N recent backups, prune older ones.
3. **Recipe export file (format for the backup target).**
   - `GET /api/recipes/export` → JSON document: recipes with `title`, `source`,
     `base_portions`, `steps`, tags/times/cuisine/category (once phase 1 lands),
     and ingredients with `raw` + normalized `amount`/`unit` + item name as a
     *hint* (never `item_id`, so the file imports into a fresh DB).
   - `POST /api/recipes/import` accepting that file → restore/merge. Ingredient
     re-matching to the local catalog uses the existing suggestion/match UI.
   - This file is the human-readable, diff-friendly artifact for off-box backup
     (commit it, sync it, mail it); the SQLite snapshot is the full-state backup.
4. **Installer checklist (when one gets built):**
   - create `./data` on host, correct ownership for the container user
   - write `PANTRY_DB=/data/pantry.db` consistently (bind mount maps it 1:1)
   - surface/verify backup timer status; warn if `./data` isn't covered by a host backup
   - expose export/restore endpoints in first-run UI or docs

## Future-update safety (constraints for schema work)

- Keep migrations additive-only in `init_db()`; never `DROP`/retype columns
  without a migration step the installer runs first.
- Adding the phase-1 recipe columns (`prep_minutes`, `cook_minutes`,
  `total_minutes`, `cuisine`, `category`, `tags`, `created_at`) must follow the
  existing `ingredients.unit` pattern so old DBs upgrade in place losslessly.
