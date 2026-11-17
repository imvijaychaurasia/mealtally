# Upgrading

## The usual upgrade

1. Read the new version's section in [CHANGELOG.md](../CHANGELOG.md) and below.
2. Point `.env` at the new image: `MEALTALLY_IMAGE=ghcr.io/<owner>/mealtally:0.2.0`.
3. Update the repository files to the same version (the Compose file and scripts can change too):

   ```bash
   git fetch --tags && git checkout v0.2.0
   ```

4. Run:

   ```bash
   make upgrade
   ```

`make upgrade` pulls the new image, makes a database backup in `./backups/`, and restarts the services. The web
container applies database migrations when it starts and only then accepts requests. Expect a minute or two without
service, so upgrade outside meal times.

## If something goes wrong

Go back to the previous image and restore the backup that `make upgrade` made:

1. Set `MEALTALLY_IMAGE` back to the old version and `git checkout` the old tag.
2. Restore the backup taken just before the upgrade (migrations may have changed the tables):

   ```bash
   COMPOSE_FILE=compose.prod.yml make restore FILE=backups/mealtally-<time of the upgrade>.dump
   ```

3. Open an issue with the web container's log: `docker compose -f compose.prod.yml logs web`.

## Versions

Mealtally uses [Semantic Versioning](https://semver.org/). Before 1.0, a minor version (0.1 to 0.2) may need a manual
step, which is listed below. Upgrade one minor version at a time and read each section on the way. Patch versions
(0.1.0 to 0.1.1) never need one.

The database image (`MEALTALLY_POSTGRES_IMAGE`) changes only when the PostgreSQL major version changes, which needs
a dump and restore. The notes for that version say so.

## Version notes

### 0.1.0

The first release. Nothing to upgrade from.
