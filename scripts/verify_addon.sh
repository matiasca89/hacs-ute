#!/bin/sh
# Build and verify the exact image Home Assistant installs.
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
image_tag=${UTE_TEST_IMAGE:-hacs-ute:verify}

docker build -t "$image_tag" "$project_root/ute_addon"

docker run --rm -i --shm-size=256m \
  -v "$project_root/ute_addon:/app" -w /app "$image_tag" \
  python3 -m unittest discover -s tests -v

docker run --rm -i --shm-size=256m \
  -v "$project_root/ute_addon:/app" -w /app "$image_tag" python3 - <<'PY'
import asyncio

from ute_pkg.ute_scraper import UTEScraper


async def smoke_test() -> None:
    scraper = UTEScraper("user", "password", "account")
    browser = await scraper._ensure_browser()
    assert browser.is_connected()
    await scraper.close()
    assert scraper._browser is None
    assert scraper._playwright is None
    print("Chromium startup and cleanup: OK")


asyncio.run(smoke_test())
PY
