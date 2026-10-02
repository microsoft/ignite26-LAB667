# Workshop utilities

Run these commands from the repository root.

## Keep local Docker storage small

```bash
bash scripts/clean-local-docker.sh           # Preview only
bash scripts/clean-local-docker.sh --apply   # Remove old tags and trim cache
```

The [cleanup script](clean-local-docker.sh) retains the newest timestamped
`azd-deploy-*` image tag per workshop service/environment repository, including
registry-prefixed tags. It skips images referenced by any local container,
including stopped containers. Other project images and nondeployment tags
(such as `latest`) are not removed. No force-removal or volume cleanup is used.
It refuses nonlocal Docker endpoints.

Unused cache in Docker's default builder is trimmed toward **1 GB**. This cache
is shared across projects; subsequent builds may need to download/rebuild layers.
Active and image-shared layers can keep actual usage above that target.
Do not run cleanup concurrently with builds/deployments.

In Codespaces, the root `postdeploy` hook in [azure.yaml](../azure.yaml) runs this
automatically after deployment, including the deploy phase of `azd up`.
Cleanup errors are reported without failing an otherwise successful deployment.
Outside Codespaces, cleanup is manual. Requires Bash, jq, and Docker Buildx
with `--max-used-space` support. Azure registry images and deployed resources
are unaffected.

## Generate attendee indexes

```bash
python scripts/sync-to-skillable.py
```

The generator reads only numbered step files in [instructions/](../instructions/)
and writes [skillable.md](../instructions/skillable.md) and
[index.html](../instructions/index.html) there. It excludes the folder README.
The original Skillable hosting URLs are preserved; this command writes local
files only and does not publish them.

## Local game-server load test

[load_test.py](load_test.py) sends concurrent HTTP requests to a game server
at `http://127.0.0.1:8000`. Run it only against an instance intended for load
testing:

```bash
python scripts/load_test.py
```
