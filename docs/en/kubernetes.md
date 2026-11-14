# Running on Kubernetes

[Polski](../pl/kubernetes.md)

Wawelsky Dragon runs on Kubernetes with the same images as the Docker Compose stack. Example manifests are in
[`deploy/kubernetes/`](../../deploy/kubernetes/): plain YAML with a `kustomization.yaml`, no Helm chart and no operator
required. They mirror the setup the project itself runs in production; treat them as a starting point and adjust
storage, resources and ingress to your cluster.

## What gets deployed

| Component | Kind | Image | Role |
| --- | --- | --- | --- |
| `web` | Deployment | `wawelsky/web` | SPA and reverse proxy to `api` and `mcp`; the only component behind the Ingress |
| `api` | Deployment | `wawelsky/backend` | FastAPI; an init container applies migrations, seeds the default models and creates the admin account |
| `worker` | Deployment | `wawelsky/backend` | job queue (parsing, embedding); starts after `api` is ready |
| `mcp` | Deployment | `wawelsky/backend` | MCP server (optional) |
| `searxng` | Deployment | `wawelsky/searxng` | web search for the Agent (optional) |
| `mariadb` | StatefulSet | `mariadb:11.8.9` | the only database: metadata, vectors, full-text indexes, job queue, cache |

Two volumes: the database (`data-mariadb-0`, 20 GiB) and the documents (`wawelsky-dragon-data`, 20 GiB, mounted at `/data`
in `api` and `worker`). All application containers run as a non-root user with a read-only root filesystem.

## Requirements

- Kubernetes 1.27 or newer, `kubectl` with Kustomize (built in), x86-64 nodes.
- A default StorageClass and an Ingress controller.
- About 4 GiB of memory requested and 9.5 GiB at the limits with the example values (MariaDB 3 GiB, worker 4 GiB,
  API 1.5 GiB). Database sizing: [Getting started](getting-started.md#sizing).
- An OpenAI-compatible gateway for chat and embeddings (for example LiteLLM, OpenRouter, vLLM or a llama.cpp server).

## Installation

1. **Choose the images.** Every release is published to GitHub Container Registry:

   | Image | Runs |
   | --- | --- |
   | `ghcr.io/lrozewicz/wawelsky-dragon/backend` | `api`, `worker`, `mcp` |
   | `ghcr.io/lrozewicz/wawelsky-dragon/web` | `web` |
   | `ghcr.io/lrozewicz/wawelsky-dragon/searxng` | `searxng` |

   Release `v0.2.2` has the tags `0.2.2` (exact version), `0.2` (latest patch of that line) and `latest`. The
   `images:` section of `deploy/kubernetes/kustomization.yaml` pins all three images to one version: set `newTag` to
   the [release](https://github.com/lrozewicz/wawelsky-dragon/releases) you want and keep the three tags equal.

   To run your own build instead, build and push the images from the repository root and put their names in `newName`:

   ```bash
   REG=registry.example.com/wawelsky; TAG=0.2.2
   docker build -t $REG/backend:$TAG --target runtime backend
   docker build -t $REG/web:$TAG --target runtime frontend
   docker build -t $REG/searxng:$TAG --target runtime docker/searxng
   for i in backend web searxng; do docker push $REG/$i:$TAG; done
   ```

   For a private registry add `imagePullSecrets` to the Deployments or to the namespace's default ServiceAccount.

2. **Set the address.** Replace `dragon.example.com` in `ingress.yaml` and in `WD_PUBLIC_BASE_URL` (`config.yaml`).
   Uncomment `ingressClassName`, the TLS block and the annotations that fit your controller.

3. **Create the secrets.** Copy the template and fill it in; the comments give the command for each random value.

   ```bash
   cd deploy/kubernetes
   cp secret.example.yaml secret.yaml      # do not commit the filled-in file
   kubectl apply -f namespace.yaml
   kubectl -n wawelsky-dragon apply -f secret.yaml
   ```

   `WD_CRYPTO_KEY` encrypts data stored in the database. Keep a copy and never change it on a running installation.

4. **Deploy.**

   ```bash
   kubectl apply -k .
   kubectl -n wawelsky-dragon rollout status deploy/wawelsky-dragon-api --timeout=5m
   kubectl -n wawelsky-dragon get pods
   ```

   The first start takes a minute or two: MariaDB initialises, the `migrate` init container of `api` creates the
   schema (it restarts until the database accepts connections), then `worker` and `web` become ready.

5. **Check that it works.**

   ```bash
   kubectl -n wawelsky-dragon port-forward svc/web 8080:80
   curl -fsS http://localhost:8080/healthz              # web is up and can reach the API
   curl -fsS http://localhost:8080/health/ready         # database reachable, schema up to date
   ```

   Then open the address from step 2 and log in with the admin account.

## Configuration

- Non-secret settings are in the ConfigMap `wawelsky-dragon-config` (`config.yaml`); every variable from
  [`.env.example`](../../.env.example) can be added there. After a change restart the pods:
  `kubectl -n wawelsky-dragon rollout restart deploy/wawelsky-dragon-api deploy/wawelsky-dragon-worker`.
- The `WD_LLM_DEFAULT_*` variables only seed the models on first start. Later changes are made in the app
  (Settings → Models).
- MariaDB settings are in the ConfigMap `mariadb-config`. Keep `innodb_buffer_pool_size` at about 75% of the memory
  limit of the StatefulSet.

## Storage and scaling

- The documents volume is `ReadWriteOnce`, so `worker.yaml` pins the worker to the node of the `api` pod and both
  Deployments use the `Recreate` strategy. With a `ReadWriteMany` storage class you can remove the affinity.
- Keep `api` at one replica unless you move the migrations out of its init container; `web`, `mcp` and `searxng` are
  stateless and can be scaled.
- The StatefulSet is a single MariaDB instance without backups. For production add backups of both volumes (for example
  [mariadb-operator](https://github.com/mariadb-operator/mariadb-operator) for the database and Velero for `/data`);
  procedures: [backup and restore](../runbooks/backup-restore.md).

## Ingress

Uploads can be large (the `web` proxy accepts up to `WD_MAX_UPLOAD_MB`, 1024 MB in the example) and chat answers are
streamed, so raise the limits of your ingress controller:

- ingress-nginx: `nginx.ingress.kubernetes.io/proxy-body-size: 1024m` and
  `nginx.ingress.kubernetes.io/proxy-read-timeout: "600"`;
- Traefik: no body limit by default; with TLS on the `websecure` entry point add
  `traefik.ingress.kubernetes.io/router.entrypoints: websecure` and `traefik.ingress.kubernetes.io/router.tls: "true"`.

## Local models on a GPU

The "This server" tab (Settings → GPU), which starts models through the GPU agent, needs the Docker socket and is
available only in the Compose stack. On Kubernetes run the model servers yourself, in the cluster or outside it (vLLM
or a llama.cpp server for chat, embeddings and OCR), and register them in the app as an `OpenAI-API-Compatible`
provider.

## Upgrade and rollback

Change `newTag` in `kustomization.yaml` to the new release and run `kubectl apply -k .` again. The `api`
init container applies the schema migrations before the new version starts. To roll back, set the previous tag;
migrations are not reverted, so check first that the previous version works with the new schema.

## Troubleshooting

| Symptom | Where to look |
| --- | --- |
| `api` stays in `Init:Error` or `Init:CrashLoopBackOff` | `kubectl -n wawelsky-dragon logs deploy/wawelsky-dragon-api -c migrate` (database connection, secrets) |
| `worker` waits in `Init` | `api` is not ready (`/health/ready`) |
| `worker` is `Pending` | it must be scheduled on the node of the `api` pod; check that node's free resources |
| `worker` gets `OOMKilled` while parsing | raise its memory limit or lower `WD_PARSE_PROCESSES` |
| Upload fails with 413 | body-size limit of the ingress controller |
| No web search results | the `searxng` pod; an empty result does not block anything else |
