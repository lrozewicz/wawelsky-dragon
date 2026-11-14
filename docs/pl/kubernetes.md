# Uruchomienie na Kubernetesie

[English](../en/kubernetes.md)

Wawelsky Dragon działa na Kubernetesie na tych samych obrazach co stos Docker Compose. Przykładowe manifesty są w
[`deploy/kubernetes/`](../../deploy/kubernetes/): zwykły YAML z plikiem `kustomization.yaml`, bez charta Helm
i bez operatora. Odwzorowują konfigurację, na której projekt sam działa produkcyjnie; potraktuj je jako punkt wyjścia
i dopasuj pamięć masową, zasoby i ingress do swojego klastra.

## Co jest wdrażane

| Składnik | Rodzaj | Obraz | Rola |
| --- | --- | --- | --- |
| `web` | Deployment | `wawelsky/web` | SPA i reverse proxy do `api` i `mcp`; jedyny składnik za Ingressem |
| `api` | Deployment | `wawelsky/backend` | FastAPI; init container wykonuje migracje, zasiew modeli domyślnych i zakłada konto administratora |
| `worker` | Deployment | `wawelsky/backend` | kolejka zadań (parsowanie, embedding); startuje po gotowości `api` |
| `mcp` | Deployment | `wawelsky/backend` | serwer MCP (opcjonalny) |
| `searxng` | Deployment | `wawelsky/searxng` | wyszukiwanie w internecie dla Agenta (opcjonalne) |
| `mariadb` | StatefulSet | `mariadb:11.8.9` | jedyna baza: metadane, wektory, indeksy pełnotekstowe, kolejka zadań, cache |

Dwa wolumeny: baza (`data-mariadb-0`, 20 GiB) i dokumenty (`wawelsky-dragon-data`, 20 GiB, montowany jako `/data`
w `api` i `worker`). Wszystkie kontenery aplikacji działają bez roota, z systemem plików tylko do odczytu.

## Wymagania

- Kubernetes 1.27 lub nowszy, `kubectl` z Kustomize (wbudowany), węzły x86-64.
- Domyślna StorageClass i kontroler Ingress.
- Około 4 GiB pamięci w żądaniach i 9,5 GiB w limitach przy wartościach z przykładu (MariaDB 3 GiB, worker 4 GiB,
  API 1,5 GiB). Dobór rozmiaru bazy: [Pierwsze kroki](getting-started.md#dobór-zasobów).
- Bramka zgodna z OpenAI do czatu i embeddingów (np. LiteLLM, OpenRouter, vLLM albo serwer llama.cpp).

## Instalacja

1. **Wybierz obrazy.** Każde wydanie jest publikowane w GitHub Container Registry:

   | Obraz | Uruchamia |
   | --- | --- |
   | `ghcr.io/lrozewicz/wawelsky-dragon/backend` | `api`, `worker`, `mcp` |
   | `ghcr.io/lrozewicz/wawelsky-dragon/web` | `web` |
   | `ghcr.io/lrozewicz/wawelsky-dragon/searxng` | `searxng` |

   Wydanie `v0.2.2` ma tagi `0.2.2` (dokładna wersja), `0.2` (najnowsza poprawka tej linii) i `latest`. Sekcja
   `images:` w `deploy/kubernetes/kustomization.yaml` przypina wszystkie trzy obrazy do jednej wersji: ustaw `newTag`
   na wybrane [wydanie](https://github.com/lrozewicz/wawelsky-dragon/releases) i trzymaj trzy tagi równe.

   Jeśli wolisz własny build, zbuduj i wypchnij obrazy z katalogu głównego repozytorium, a ich nazwy wpisz w `newName`:

   ```bash
   REG=registry.example.com/wawelsky; TAG=0.2.2
   docker build -t $REG/backend:$TAG --target runtime backend
   docker build -t $REG/web:$TAG --target runtime frontend
   docker build -t $REG/searxng:$TAG --target runtime docker/searxng
   for i in backend web searxng; do docker push $REG/$i:$TAG; done
   ```

   Przy prywatnym rejestrze dodaj `imagePullSecrets` do Deploymentów albo do domyślnego ServiceAccount przestrzeni nazw.

2. **Ustaw adres.** Zamień `dragon.example.com` w `ingress.yaml` oraz w `WD_PUBLIC_BASE_URL` (`config.yaml`).
   Odkomentuj `ingressClassName`, blok TLS i adnotacje pasujące do Twojego kontrolera.

3. **Utwórz sekrety.** Skopiuj szablon i uzupełnij go; komentarze podają polecenie dla każdej wartości losowej.

   ```bash
   cd deploy/kubernetes
   cp secret.example.yaml secret.yaml      # uzupełnionego pliku nie commituj
   kubectl apply -f namespace.yaml
   kubectl -n wawelsky-dragon apply -f secret.yaml
   ```

   `WD_CRYPTO_KEY` szyfruje dane zapisane w bazie. Zachowaj kopię i nigdy nie zmieniaj go na działającej instalacji.

4. **Wdróż.**

   ```bash
   kubectl apply -k .
   kubectl -n wawelsky-dragon rollout status deploy/wawelsky-dragon-api --timeout=5m
   kubectl -n wawelsky-dragon get pods
   ```

   Pierwszy start trwa minutę lub dwie: MariaDB się inicjalizuje, init container `migrate` w `api` tworzy schemat
   (restartuje się, dopóki baza nie przyjmuje połączeń), potem gotowość osiągają `worker` i `web`.

5. **Sprawdź działanie.**

   ```bash
   kubectl -n wawelsky-dragon port-forward svc/web 8080:80
   curl -fsS http://localhost:8080/healthz              # web działa i widzi API
   curl -fsS http://localhost:8080/health/ready         # baza dostępna, schemat aktualny
   ```

   Następnie otwórz adres z kroku 2 i zaloguj się na konto administratora.

## Konfiguracja

- Ustawienia jawne są w ConfigMapie `wawelsky-dragon-config` (`config.yaml`); można tam dodać każdą zmienną
  z [`.env.example`](../../.env.example). Po zmianie zrestartuj pody:
  `kubectl -n wawelsky-dragon rollout restart deploy/wawelsky-dragon-api deploy/wawelsky-dragon-worker`.
- Zmienne `WD_LLM_DEFAULT_*` służą tylko do zasiewu modeli przy pierwszym uruchomieniu. Późniejsze zmiany robi się
  w aplikacji (Ustawienia → Modele).
- Ustawienia MariaDB są w ConfigMapie `mariadb-config`. Trzymaj `innodb_buffer_pool_size` na poziomie ok. 75% limitu
  pamięci StatefulSetu.

## Pamięć masowa i skalowanie

- Wolumen dokumentów jest `ReadWriteOnce`, dlatego `worker.yaml` przypina workera do węzła poda `api`, a oba
  Deploymenty mają strategię `Recreate`. Przy klasie `ReadWriteMany` to powiązanie można usunąć.
- `api` zostaw w jednej replice, chyba że wyniesiesz migracje poza jego init container; `web`, `mcp` i `searxng` są
  bezstanowe i można je skalować.
- StatefulSet to pojedyncza instancja MariaDB bez kopii zapasowych. Na produkcji dodaj kopie obu wolumenów (np.
  [mariadb-operator](https://github.com/mariadb-operator/mariadb-operator) dla bazy i Velero dla `/data`);
  procedury: [kopie i odtwarzanie](../runbooks/backup-restore.md).

## Ingress

Wgrywane pliki bywają duże (proxy `web` przyjmuje do `WD_MAX_UPLOAD_MB`, w przykładzie 1024 MB), a odpowiedzi czatu są
strumieniowane, więc podnieś limity kontrolera Ingress:

- ingress-nginx: `nginx.ingress.kubernetes.io/proxy-body-size: 1024m` oraz
  `nginx.ingress.kubernetes.io/proxy-read-timeout: "600"`;
- Traefik: domyślnie bez limitu rozmiaru; przy TLS na wejściu `websecure` dodaj
  `traefik.ingress.kubernetes.io/router.entrypoints: websecure` i `traefik.ingress.kubernetes.io/router.tls: "true"`.

## Modele lokalne na GPU

Zakładka „Ten serwer” (Ustawienia → GPU), która uruchamia modele przez agenta GPU, wymaga gniazda Dockera i jest
dostępna tylko w stosie Compose. Na Kubernetesie serwery modeli uruchamiasz samodzielnie, w klastrze albo poza nim
(vLLM albo serwer llama.cpp dla czatu, embeddingów i OCR), i rejestrujesz je w aplikacji jako dostawcę
`OpenAI-API-Compatible`.

## Aktualizacja i wycofanie

Zmień `newTag` w `kustomization.yaml` na nowe wydanie i ponownie uruchom `kubectl apply -k .`.
Init container `api` wykona migracje schematu przed startem nowej wersji. Aby wycofać zmianę, ustaw poprzedni tag;
migracje nie są cofane, więc najpierw sprawdź, czy poprzednia wersja działa z nowym schematem.

## Diagnostyka

| Objaw | Gdzie patrzeć |
| --- | --- |
| `api` zostaje w `Init:Error` lub `Init:CrashLoopBackOff` | `kubectl -n wawelsky-dragon logs deploy/wawelsky-dragon-api -c migrate` (połączenie z bazą, sekrety) |
| `worker` czeka w `Init` | `api` nie jest gotowe (`/health/ready`) |
| `worker` ma stan `Pending` | musi trafić na węzeł poda `api`; sprawdź wolne zasoby tego węzła |
| `worker` dostaje `OOMKilled` przy parsowaniu | podnieś limit pamięci albo zmniejsz `WD_PARSE_PROCESSES` |
| Wgranie pliku kończy się kodem 413 | limit rozmiaru w kontrolerze Ingress |
| Brak wyników wyszukiwania internetowego | pod `searxng`; pusty wynik niczego innego nie blokuje |
