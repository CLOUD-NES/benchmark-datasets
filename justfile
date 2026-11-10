# Build the CLOUD-NES datasets: `just <dataset>` builds all missing outputs, `just <dataset> <recipe> [args]` one.
# See lib.just for the BUCKET and FORCE environment variables.

set dotenv-load

mod ahn-dsm05 'datasets/ahn-dsm05/justfile'
mod bm-2024O-rgb 'datasets/bm-2024O-rgb/justfile'
mod brp-2025 'datasets/brp-2025/justfile'
mod knmi-tg1-5 'datasets/knmi-tg1-5/justfile'

[private]
default:
    @{{just_executable()}} --justfile {{justfile()}} --list --list-submodules
