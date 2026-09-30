# Release Process

## Checklist for new releases

1. **Update version in `ute_addon/config.yaml`**
   ```yaml
   version: "X.Y.Z"
   ```

2. **Update both changelogs**
   - Add a dated section to the root `CHANGELOG.md` for GitHub releases.
   - Add a section with the exact version to `ute_addon/CHANGELOG.md`; this is the file shown by Home Assistant.
   - Document all changes (Added/Changed/Fixed/Removed)
   - The automated verification rejects a version that lacks this add-on changelog entry.

3. **Commit changes**
   ```bash
   git add -A
   git commit -m "chore: Release vX.Y.Z"
   ```

4. **Create and push tag**
   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z - Description"
   git push origin main
   git push origin vX.Y.Z
   ```

5. **Create GitHub Release**
   ```bash
   gh release create vX.Y.Z --title "vX.Y.Z - Title" --notes-file CHANGELOG_EXCERPT.md
   ```
   Or copy the relevant CHANGELOG section to the release notes.

## Validation for dated Energy releases

- Run `UTE_TEST_IMAGE=hacs-ute:verify ./scripts/verify_addon.sh` (exact image, unit tests, Chromium startup/cleanup).
- CI also starts a separate Core 2026.9.4 using `scripts/fixtures/core-configuration.yaml` and runs `scripts/verify_energy_core.py`. This verifies real Recorder rows, local-day changes, corrections, idempotency and legacy preservation using explicitly synthetic fixtures.
- The Core fixture listens only on `127.0.0.1:18123`; the verifier refuses an already-onboarded instance unless a private token file for that exact loopback URL is supplied. Never point release probes at production.
- Core 2026.9 HTTP configuration requires explicit promotion after checking the endpoint; otherwise the test server can auto-revert/restart after five minutes. The verifier promotes only its isolated endpoint and reads back the HTTP settings.
- If credentials are locally available, run a private real-UTE probe in the built add-on image and import only into isolated Core. Check each actual UTE consumption date, monthly/day reconciliation, sensor read-back and ledger reload. Do not commit credentials, private account IDs or consumption captures.
- Commit only the explicit release files. Preserve unrelated/untracked files such as local `spikes/`.
- Push a candidate branch and wait for both CI jobs to pass before fast-forwarding `main`, pushing the annotated tag and publishing the release. Verify remote commit/tag/version and read back the exact GitHub release.

## Version numbering

- **Major (X)**: Breaking changes
- **Minor (Y)**: New features, backward compatible
- **Patch (Z)**: Bug fixes, backward compatible
