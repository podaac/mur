# Shared environment for MUR cron scripts.
#
# Sourced by every run_*_cron.sh wrapper so the config file name lives in
# exactly one place. Override at invocation time when needed, e.g.:
#
#   MUR_CONFIG=config.staging.json /bin/bash ~/containerized-mur/run_mrva_cron.sh
#
# The `:=` form only assigns when the variable is unset, so existing
# overrides from cron entries or shell environments are preserved.

: "${MUR_CONFIG:=config.container.json}"
export MUR_CONFIG
