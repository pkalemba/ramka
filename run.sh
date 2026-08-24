#!/usr/bin/with-contenv bashio

# Wczytaj konfigurację z HA options.json i przekaż jako zmienne środowiskowe
export HA_URL=$(bashio::config 'ha_url')
export HA_TOKEN=$(bashio::config 'ha_token')
export KS_URL=$(bashio::config 'kubesavings_url')
export KS_TOKEN=$(bashio::config 'kubesavings_token')

bashio::log.info "Starting E-Paper Renderer on port 5000"
bashio::log.info "Home Assistant URL: ${HA_URL}"

exec python3 /app/app.py
