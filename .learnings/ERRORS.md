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
