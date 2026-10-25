# Zapewnianie narzędzi wyroczni: bun w wersji WD_BUN_VERSION i uv.
# Plik jest źródłowany (przez verify-lib.sh) — bez set -e, bez exit, bez cd; błędy przez return 1 + stderr.

# $HOME/.local/bin na początek PATH, bez duplikatu — tam trafia bun z `npm i -g --prefix "$HOME/.local"`.
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) export PATH="$HOME/.local/bin:$PATH" ;;
esac

WD_BUN_VERSION=1.4.2

# Bun dokładnie w wersji WD_BUN_VERSION; gdy brak lub inna wersja — instaluje przez npm i sprawdza ponownie.
ensure_bun() {
  local found
  found="$(bun --version 2>/dev/null)" || found=""
  if [ "$found" = "$WD_BUN_VERSION" ]; then
    return 0
  fi
  npm i -g --prefix "$HOME/.local" "bun@$WD_BUN_VERSION" >&2
  hash -r
  found="$(bun --version 2>/dev/null)" || found=""
  if [ "$found" != "$WD_BUN_VERSION" ]; then
    if [ -n "$found" ]; then
      echo "ensure-tools: bun $found zamiast $WD_BUN_VERSION po instalacji" >&2
    else
      echo "ensure-tools: bun brak zamiast $WD_BUN_VERSION po instalacji" >&2
    fi
    return 1
  fi
  return 0
}

WD_GITLEAKS_VERSION=8.30.1
WD_GITLEAKS_SHA256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
WD_GITLEAKS_URL="https://github.com/gitleaks/gitleaks/releases/download/v$WD_GITLEAKS_VERSION/gitleaks_${WD_GITLEAKS_VERSION}_linux_x64.tar.gz"

# Gitleaks dokładnie w wersji WD_GITLEAKS_VERSION; gdy brak lub inna wersja — pobiera z wydania,
# weryfikuje sha256 i instaluje do $HOME/.local/bin, po czym sprawdza ponownie. Bez sieci → return 1.
ensure_gitleaks() {
  local found tmp
  found="$(gitleaks version 2>/dev/null)" || found=""
  if [ "$found" = "$WD_GITLEAKS_VERSION" ]; then
    return 0
  fi
  tmp="$(mktemp -d)" || { echo "ensure-tools: mktemp nie powiódł się" >&2; return 1; }
  if ! curl -fsSL --max-time 120 -o "$tmp/gl.tgz" "$WD_GITLEAKS_URL"; then
    echo "ensure-tools: brak sieci albo pobranie gitleaks nie powiodło się" >&2
  elif ! echo "$WD_GITLEAKS_SHA256  $tmp/gl.tgz" | sha256sum -c -; then
    echo "ensure-tools: suma kontrolna gitleaks nie zgadza się" >&2
  elif ! tar -xzf "$tmp/gl.tgz" -C "$tmp" gitleaks; then
    echo "ensure-tools: rozpakowanie gitleaks nie powiodło się" >&2
  elif ! mkdir -p "$HOME/.local/bin"; then
    echo "ensure-tools: brak katalogu $HOME/.local/bin" >&2
  elif ! install -D -m 755 "$tmp/gitleaks" "$HOME/.local/bin/gitleaks"; then
    echo "ensure-tools: instalacja gitleaks nie powiodła się" >&2
  else
    rm -rf "$tmp"
    hash -r
    found="$(gitleaks version 2>/dev/null)" || found=""
    if [ "$found" = "$WD_GITLEAKS_VERSION" ]; then
      return 0
    fi
    echo "ensure-tools: gitleaks ${found:-brak} zamiast $WD_GITLEAKS_VERSION po instalacji" >&2
    return 1
  fi
  rm -rf "$tmp"
  return 1
}

# Obecność uv; instalacja uv nie należy do wyroczni (brak = czerwień kroku uv sync).
ensure_uv() {
  if uv --version >/dev/null 2>&1; then
    return 0
  fi
  echo "ensure-tools: brak uv w PATH" >&2
  return 1
}
