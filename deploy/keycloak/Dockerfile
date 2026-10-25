# Obraz testowego Keycloaka z importem realm wawelsky-test (kontrakt WP E0-3 C11; realm przez COPY, bez bind-mountów).
# Tylko realm WD — obraz drugiego stosu testowego mieszka w private/ (kontrakt WP E5-6 §C3).

FROM quay.io/keycloak/keycloak:26.7.4

COPY realms/wawelsky-test.json /opt/keycloak/data/import/wawelsky-test.json
