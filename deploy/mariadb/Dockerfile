# Obraz MariaDB z konfiguracją wawelsky (kontrakt WP E0-3 C1; K8-B p. 2 i 7 — cnf przez COPY, bez bind-mountów).

FROM mariadb:11.8.9

COPY --chmod=0644 wawelsky.cnf /etc/mysql/conf.d/wawelsky.cnf

# jemalloc zamiast malloc z glibc: glibc nie oddaje zwolnionej pamięci (fragmentacja) i RSS
# rośnie aż do OOM-kill przy równoległym retrievalu. Pomiar 05.11.2026 (dev, 45 retrievali
# po 9 naraz, Memory_used serwera stałe 1,32 GiB): RSS glibc 4,67 GiB, tcmalloc 3,24 GiB,
# jemalloc 2,68 GiB. Biblioteka jest w obrazie bazowym; ścieżka zależna od architektury.
RUN lib="$(find /usr/lib -name 'libjemalloc.so.2' | head -n 1)" \
 && test -n "$lib" \
 && ln -s "$lib" /usr/local/lib/libjemalloc.so.2
ENV LD_PRELOAD=/usr/local/lib/libjemalloc.so.2
