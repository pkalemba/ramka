#!/bin/bash
# Kopiuje wtyczke do katalogu wtyczek SwiftBara i tworzy szkielet konfiguracji.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN="plexamp.5s.py"
CONFIG_DIR="${HOME}/.config/plexamp-menubar"
CONFIG_FILE="${CONFIG_DIR}/config.json"

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
echo "Wtyczka: ${PLUGIN_DIR}/${PLUGIN}"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  mkdir -p "${CONFIG_DIR}"
  install -m 600 "${HERE}/config.example.json" "${CONFIG_FILE}"
  echo "Konfiguracja: ${CONFIG_FILE} - wpisz w niej swoj token Plex."
else
  echo "Konfiguracja juz istnieje: ${CONFIG_FILE} (nie ruszam)"
fi

echo "Na koniec: SwiftBar -> Refresh all"
