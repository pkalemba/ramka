#!/bin/bash
# Kopiuje wtyczke i jej config.json do katalogu wtyczek SwiftBara.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN="plexamp.5s.py"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Ten instalator jest przeznaczony dla macOS." >&2
  exit 1
fi

PLUGIN_DIR="${1:-}"
if [[ -z "${PLUGIN_DIR}" ]]; then
  for domain in com.ameba.SwiftBar com.matryer.xbar com.matryer.BitBar; do
    PLUGIN_DIR="$(defaults read "${domain}" PluginDirectory 2>/dev/null || true)"
    [[ -n "${PLUGIN_DIR}" ]] && break
  done
fi
if [[ -z "${PLUGIN_DIR}" ]]; then
  echo "Nie znalazlem katalogu wtyczek SwiftBara." >&2
  echo "Uruchom SwiftBar i wskaz katalog, albo podaj go recznie: ./install.sh ~/.swiftbar-plugins" >&2
  exit 1
fi

mkdir -p "${PLUGIN_DIR}"
install -m 755 "${HERE}/${PLUGIN}" "${PLUGIN_DIR}/${PLUGIN}"
echo "Wtyczka:      ${PLUGIN_DIR}/${PLUGIN}"

CONFIG_FILE="${PLUGIN_DIR}/config.json"
if [[ -f "${CONFIG_FILE}" ]]; then
  echo "Konfiguracja: ${CONFIG_FILE} (juz istnieje, nie ruszam)"
else
  install -m 600 "${HERE}/config.example.json" "${CONFIG_FILE}"
  echo "Konfiguracja: ${CONFIG_FILE} - wpisz w niej swoj token Plex."
fi

# SwiftBar probuje uruchomic kazdy plik z katalogu wtyczek - config.json ma omijac.
IGNORE_FILE="${PLUGIN_DIR}/.swiftbarignore"
if ! grep -qxF "config.json" "${IGNORE_FILE}" 2>/dev/null; then
  echo "config.json" >> "${IGNORE_FILE}"
fi

echo "Na koniec: SwiftBar -> Refresh all"
