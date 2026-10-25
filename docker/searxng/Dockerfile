# Obraz searxng WD (kontrakt E6-3f C7) — obraz upstream z PRZYPIĘTYM tagiem + nasz settings.yml.
# Bez bind-mountów repo (K8-B p. 7): konfiguracja wchodzi do obrazu przez COPY.
# Tag zweryfikowany `docker pull` 2026-10-12 (digest sha256:76b0bf285aca014c7191fc4d9234c4bfb358624ac33d8883833d496c059ec072).

FROM searxng/searxng:2026.10.4-d48c4b555 AS runtime

COPY settings.yml /etc/searxng/settings.yml

# H11: obraz upstream startuje jako root (entrypoint zrzeka się uprawnień tylko przy FORCE_OWNERSHIP);
# uruchamiamy wprost jako użytkownika `searxng` (uid 977), właściciela /etc/searxng i /var/cache/searxng.
USER searxng
