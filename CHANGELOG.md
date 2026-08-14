# Changelog

All notable changes to this project will be documented in this file.

## [1.3.1] - 2026-08-14

### Fixed
- Create the persistent state directory before writing daily consumption data, so the add-on also runs correctly when `/data` is initially absent.

### Verified
- End-to-end run with a real UTE scrape and an emulated Home Assistant Supervisor: all sensor updates were accepted and state persistence succeeded.

## [1.3.0] - 2026-08-14

### Changed
- Simplified the repository to the Home Assistant add-on only; removed the unused HACS custom integration and duplicate standalone scraper.
- Reuse the Chromium process across polling cycles while creating a clean browser context for every UTE session and retry.
- Centralized scraper timeouts, retry delays, and Chromium flags.
- Simplified sensor publishing through a single declarative definition and made daily-state writes atomic.

### Fixed
- Retain the Playwright Python client explicitly in the add-on image, pinned to its Chromium base-image version.

### Added
- Unit tests for daily consumption and monthly-counter reset calculations.

## [1.2.3] - 2026-08-13

### Fixed
- Do not wait for UTE's unreliable post-submit navigation; verify login by waiting directly for the authenticated-session indicator.
- Recreate the entire browser context between failed login attempts, clearing stalled redirects and identity-provider session state.

## [1.2.2] - 2026-08-12

### Fixed
- Submit UTE login through the explicit **Ingresar** button instead of pressing Enter in the password field.
- Wait for the authenticated session indicator rather than `networkidle`, which can time out while UTE keeps background requests open.
- Recreate the page before retrying a failed login to avoid retrying against a stale identity-provider state.

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
