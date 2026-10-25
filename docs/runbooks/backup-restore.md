# Runbook — kopia zapasowa, odtworzenie i rotacja `WD_CRYPTO_KEY`

Podstawa: `docs/architecture/11-infrastruktura.md` §6, §8, §12; kontrakt WP E5-3 (`work/wp/E5-3/CONTRACT.md`).
Zakres: poziom **B1 (fizyczny)** — baza MariaDB + wolumen `app-data`. Kopia logiczna (B2) jest poza zakresem v1.0.
Skrypty działają na hoście z Dockerem (potrzebne: `docker compose`, `jq`, `sha256sum`, `find`); `zstd` i `tar` są w obrazie `mariadb`.

## 0. Co jest w kopii, a czego nie ma
| W kopii | Poza kopią (zabezpiecz osobno) |
|---|---|
| dump bazy `db-<ts>.sql.zst` (`mariadb-dump --single-transaction --routines --hex-blob`) | **`.env`** — a w nim `WD_CRYPTO_KEY`, `WD_SECRET_KEY`, hasła DB |
| tar wolumenu `data-<ts>.tar.zst` (oryginały dokumentów) | konfiguracja reverse proxy / Keycloaka |
| `manifest-<ts>.json`: wersja WD, `alembic_version`, nazwa bazy, sha256 i rozmiary plików | |

Zaszyfrowane sekrety (klucze dostawców, sekrety integracji, tokeny API) są w dumpie **zaszyfrowane** — bez dokładnie tego
`WD_CRYPTO_KEY`, którym je zaszyfrowano, nie da się ich odczytać po odtworzeniu. Kopię `.env` trzymaj w menedżerze sekretów
(nie obok kopii bazy).

## 1. Backup
```
cd /opt/wawelsky-dragon          # katalog z docker-compose.yml i .env
scripts/backup.sh --out /var/backups/wd --retain-days 14
```
- Ostatnia linia wyjścia: `BACKUP_TS=<ts>` (np. `20261002T021500Z`). Kod ≠ 0 = kopia niepełna (niepełne pliki są usuwane).
- Parametry: `--compose-file` (dom. `docker-compose.yml`), `--project`, `--db-service` (dom. `mariadb`), `--data-volume` (dom. `app-data`), `--retain-days N` (dom. 14; `0` = bez retencji).
- Retencja kasuje wyłącznie pliki `db-*.sql.zst`, `data-*.tar.zst`, `manifest-*.json` starsze niż N dni w katalogu `--out`.
- Dump jest spójny (`--single-transaction`), więc backup można robić na działającym stosie; wolumen `app-data` kopiowany jest bez zatrzymania — pliki wgrane w trakcie kopiowania mogą się nie załapać (dla ścisłej spójności zatrzymaj `api` i `worker` na czas kopii: `docker compose stop api worker`).

### Cron hosta (codziennie 02:15)
```
15 2 * * * cd /opt/wawelsky-dragon && scripts/backup.sh --out /var/backups/wd --retain-days 14 >> /var/log/wd-backup.log 2>&1
```
Skrypt nie wypisuje sekretów. Monitoruj kod wyjścia i świeżość najnowszego `manifest-*.json` (np. alarm, gdy starszy niż 26 h).
Kopie poza hostem (rsync/S3) to osobny krok operacyjny — skrypt ich nie wysyła.

## 2. Restore
Odtworzenie **zastępuje** bazę i zawartość wolumenu `app-data`.
```
cd /opt/wawelsky-dragon
scripts/restore.sh --out /var/backups/wd --ts 20261002T021500Z
```
Kolejność (skrypt): weryfikacja sha256 plików i wersji schematu → start `mariadb` → zatrzymanie `api`/`worker`/`web` → `DROP DATABASE` + import dumpu →
wyczyszczenie i rozpakowanie wolumenu → `migrate` → start `api`/`worker` → sprawdzenie `/health/ready`. Ostatnia linia: `RESTORE_OK <ts>`.

| Kod | Znaczenie | Działanie |
|---|---|---|
| 0 | OK | sprawdź logowanie i dokument w UI |
| 3 | `sha256 mismatch: <plik>` | kopia uszkodzona — nic nie zostało zmienione; weź starszą kopię |
| 4 | `backup is newer than image` | obraz aplikacji starszy niż schemat kopii — uruchom nowszą wersję obrazu i powtórz |
| 2 | błędne argumenty | `scripts/restore.sh` bez argumentów wypisze użycie |

Na **świeżej** instalacji: `docker compose --env-file .env up -d --wait mariadb` (albo pozwól skryptowi), skopiuj `.env` z kopii sekretów
(ten sam `WD_CRYPTO_KEY`!), potem `restore.sh`.

## 3. Test odtworzenia (CI / nocny)
`tools/dev/backup-restore-test.sh` — na stosie testowym worktree tworzy dane (dataset z dokumentem, czat, instancję dostawcy z kluczem,
integrację z sekretem), robi backup, kasuje stos (`down -v`), stawia świeży, odtwarza i porównuje liczniki tabel, sha256 dokumentu
oraz odczyt sekretów; potem testuje rotację klucza. Jest krokiem `backup-restore` w `./.claude/verify-full.sh`.

## 4. Rotacja `WD_CRYPTO_KEY`
Rotacja przeszyfrowuje cztery kolumny (`api_keys.token_enc`, `models.api_key_enc`, `provider_instances.api_key_enc`,
`integrations.secret_enc`) w **jednej transakcji** z zachowaniem AAD. Błąd odszyfrowania któregokolwiek wiersza = rollback i kod 1 (baza nietknięta).
Nowy klucz podawany jest **wyłącznie zmienną środowiskową** `WD_CRYPTO_KEY_NEW` (nigdy argumentem).

1. Zatrzymaj ruch: `docker compose stop api worker web`.
2. **Backup** (sekcja 1) — zapisz `BACKUP_TS`. Zachowaj też dotychczasowy `.env`.
3. Wygeneruj nowy klucz, bez wypisywania: `NEW="$(openssl rand -hex 32)"; export WD_CRYPTO_KEY_NEW="$NEW"`.
4. Próba: `docker compose run --rm --no-deps -e WD_CRYPTO_KEY_NEW migrate python -m app.tools.rotate_crypto_key --dry-run` → `OK (dry-run)`
   i liczby wierszy na kolumnę (nic nie jest zapisywane). Kod 1 + `cannot decrypt <tabela>.<kolumna> id=<id>` = ten wiersz nie daje się odszyfrować
   obecnym kluczem — wyjaśnij, zanim przejdziesz dalej.
5. Rotacja: to samo polecenie bez `--dry-run` → `OK`, kod 0.
6. Podmień klucz w `.env` (`WD_CRYPTO_KEY=<nowy>`; np. `sed -i "s/^WD_CRYPTO_KEY=.*/WD_CRYPTO_KEY=$NEW/" .env`, `chmod 600 .env`), zaktualizuj kopię `.env` w menedżerze sekretów, `unset WD_CRYPTO_KEY_NEW NEW`.
7. Start: `docker compose up -d --wait`. Sprawdź w UI (administracja) test połączenia instancji dostawcy i integracji SharePoint.
8. Awaria po kroku 5 (np. zły `.env`): przywróć stary `.env` i `scripts/restore.sh --ts <BACKUP_TS>` z kroku 2 (kopia ma sekrety zaszyfrowane starym kluczem).

Uwaga: nie uruchamiaj rotacji dwa razy z tym samym `WD_CRYPTO_KEY_NEW` na już zrotowanej bazie — drugi przebieg nie odszyfruje wierszy starym kluczem (kod 1, rollback).
`WD_SECRET_KEY` rotuje się osobno (unieważnia access tokeny) i nie wymaga tej procedury.

## 5. Rozwiązywanie problemów
| Objaw | Przyczyna | Działanie |
|---|---|---|
| `backup.sh`: „brak wolumenu” | zła `--project` lub `--data-volume` | `docker volume ls --filter label=com.docker.compose.project=<projekt>` |
| restore: `/health/ready` 503 | `migrate` nie przeszedł albo brak `innodb_ft_min_token_size=2` | logi `docker compose logs migrate mariadb`; obraz `wawelsky/mariadb` ma właściwą konfigurację |
| po restore „cannot decrypt” przy teście połączenia | `.env` z innym `WD_CRYPTO_KEY` niż w chwili backupu | przywróć właściwy `.env` (kopia sekretów) |
| brak miejsca w `--out` | zbyt długa retencja | zmniejsz `--retain-days`; sprawdź `df -h` |
