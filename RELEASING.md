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

## Version numbering

- **Major (X)**: Breaking changes
- **Minor (Y)**: New features, backward compatible
- **Patch (Z)**: Bug fixes, backward compatible
