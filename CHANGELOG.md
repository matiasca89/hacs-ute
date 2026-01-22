# Changelog

All notable changes to this project will be documented in this file.

## [1.1.0] - 2026-01-22

### Added
- Docker-based Home Assistant Add-on with Playwright support
- `repository.yaml` for HA add-on store
- Scraper runs in container with proper browser support
- Updates sensors via Supervisor API

### Fixed
- Calculate total energy from peak + off-peak when API returns 0
- Use `.first` for multiple matching elements in scraper
- Use `attached` state instead of `visible` for hidden elements

## [1.0.0] - 2026-01-22

### Added
- Initial release
- Playwright-based scraper for UTE self-service portal
- Sensors: peak, off-peak, total energy (kWh), efficiency (%)
- Config flow with credential validation
- Spanish and English translations
- Compatible with Home Assistant Energy Dashboard
