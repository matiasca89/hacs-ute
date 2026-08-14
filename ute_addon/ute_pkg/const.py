"""Constants for UTE scraper."""

UTE_LOGIN_URL = "https://identityserver.ute.com.uy/Account/Login"
UTE_SELFSERVICE_URL = "https://autoservicio.ute.com.uy/SelfService/SSvcController"

NAVIGATION_TIMEOUT_MS = 60_000
ELEMENT_TIMEOUT_MS = 30_000
LOGIN_RETRY_DELAYS_SECONDS = (30, 30)
CHROMIUM_ARGS = (
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
)
