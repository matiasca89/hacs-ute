## [ERR-20260814-001] pytest_unavailable

**Logged**: 2026-08-14T21:46:00Z
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
The host Python environment does not include pytest.

### Error
```
/usr/bin/python3: No module named pytest
```

### Context
- Command attempted: `python3 -m pytest -q tests`
- The add-on image remains the authoritative runtime environment.

### Resolution
- **Resolved**: 2026-08-14T21:46:00Z
- **Notes**: Used the standard-library unittest runner and image build validation instead.

---

## [ERR-20260814-006] e2e_state_directory_missing

**Logged**: 2026-08-14T22:10:00Z
**Priority**: medium
**Status**: resolved
**Area**: backend

### Summary
The add-on completed a live scrape but could not persist state when `/data` was absent in a standalone container.

### Error
```
Unable to save state: [Errno 2] No such file or directory: '/data/ute_state.tmp'
```

### Resolution
- **Resolved**: 2026-08-14T22:10:00Z
- **Notes**: Create the state directory before the atomic write and test the missing-directory case.

---

## [ERR-20260814-005] scraper_url_test_parameter

**Logged**: 2026-08-14T22:06:00Z
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
The new scraper URL test omitted the nested query-parameter brackets.

### Error
```
AssertionError: 'psId=98765' not found in generated UTE URL
```

### Resolution
- **Resolved**: 2026-08-14T22:06:00Z
- **Notes**: Assert the actual encoded query fragment `[psId]=98765`.

---

## [ERR-20260814-004] smoke_test_shell_syntax

**Logged**: 2026-08-14T21:49:00Z
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
The initial Chromium smoke-test one-liner used invalid Python syntax.

### Error
```
SyntaxError: invalid syntax
```

### Context
- An `async def` declaration cannot follow a semicolon in a Python one-liner.

### Resolution
- **Resolved**: 2026-08-14T21:49:00Z
- **Notes**: Re-ran the test using a heredoc script.

---

## [ERR-20260814-003] playwright_python_client_missing

**Logged**: 2026-08-14T21:48:00Z
**Priority**: medium
**Status**: resolved
**Area**: infra

### Summary
The Playwright Docker image supplies browsers but the tested image did not provide the Python package import.

### Error
```
ModuleNotFoundError: No module named 'playwright'
```

### Context
- The refactor removed the explicit `playwright` pip dependency under the assumption it was included by the base image.

### Resolution
- **Resolved**: 2026-08-14T21:48:00Z
- **Notes**: Restored the client dependency pinned to the base image version (1.49.0).

---

## [ERR-20260814-002] playwright_host_unavailable

**Logged**: 2026-08-14T21:47:00Z
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
The host does not install the add-on's Playwright runtime.

### Error
```
ModuleNotFoundError: No module named 'playwright'
```

### Context
- Standard-library tests import the add-on scraper.
- Playwright is provided by the Docker base image, not the host.

### Resolution
- **Resolved**: 2026-08-14T21:47:00Z
- **Notes**: Build and run the tests inside the add-on image.

---
## [ERR-20260815-001] docker_diagnostic_command

**Logged**: 2026-08-15T07:25:00Z
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
An inline Python diagnostic used an invalid one-line async function definition.

### Error
```
SyntaxError: invalid syntax
```

### Context
- Command attempted to define `async def` after semicolon-separated statements.

### Suggested Fix
Use a multiline Python script or a normal synchronous one-liner for diagnostics.

### Metadata
- Reproducible: yes
- Related Files: ute_addon/tests/test_main.py

### Resolution
- **Resolved**: 2026-08-15T07:25:00Z
- **Notes**: Replaced with a valid multiline lifecycle verification.

---

## [ERR-20260815-002] docker_slim_image_build

**Logged**: 2026-08-15T07:30:00Z
**Priority**: medium
**Status**: resolved
**Area**: infra

### Summary
Docker could not export the slim-image candidate because the host filesystem ran out of space.

### Error
```
failed to write compressed diff: no space left on device
```

### Context
- Building the Python slim + Chromium candidate locally.
- Host disk had 417 MB free; Docker reported 1.9 GB of reclaimable build cache.

### Suggested Fix
Prune only unused Docker build cache and test images, then repeat the full verification.

### Metadata
- Reproducible: yes
- Related Files: ute_addon/Dockerfile

### Resolution
- **Resolved**: 2026-08-15T07:34:00Z
- **Notes**: Removed only unused test images and build cache, then completed the verification.

---

## [ERR-20260815-003] slim_smoke_test_dependency

**Logged**: 2026-08-15T07:33:00Z
**Priority**: low
**Status**: resolved
**Area**: tests

### Summary
The slim image intentionally lacks the `pgrep` utility used by a diagnostic-only smoke test.

### Error
```
FileNotFoundError: [Errno 2] No such file or directory: 'pgrep'
```

### Context
- Chromium had already launched successfully.

### Suggested Fix
Assert browser startup and `UTEScraper.close()` state from Python rather than installing process-inspection tools.

### Metadata
- Reproducible: yes
- Related Files: ute_addon/Dockerfile

### Resolution
- **Resolved**: 2026-08-15T07:33:00Z
- **Notes**: The automated smoke test now uses only Python and Playwright.

---
