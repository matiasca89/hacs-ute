# Changelog

All notable changes to this project will be documented in this file.

## [1.2.1] - 2026-02-01

### Fixed
- Fix date range on the 1st of the month (use month of "yesterday" so `fecha_inicial` is never after `fecha_final`).

## [1.2.0] - 2026-01-22

### Added
- Daily consumption sensors calculated from cumulative values
  - `sensor.ute_diario_punta` - Daily peak energy
  - `sensor.ute_diario_fuera_punta` - Daily off-peak energy
  - `sensor.ute_diario_total` - Daily total energy
- Persistent state file to track day changes
- Automatic delta calculation on day change (Uruguay timezone UTC-3)
- Handles month resets correctly

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
