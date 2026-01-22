"""Constants for the UTE Consumo integration."""

DOMAIN = "ute_consumo"

# URLs
UTE_LOGIN_URL = "https://identityserver.ute.com.uy/Account/Login"
UTE_SELFSERVICE_URL = "https://autoservicio.ute.com.uy/SelfService/SSvcController"

# Config
CONF_ACCOUNT_ID = "account_id"

# Update interval (1 hour)
DEFAULT_SCAN_INTERVAL = 3600

# Attributes
ATTR_PEAK_ENERGY = "peak_energy"
ATTR_OFF_PEAK_ENERGY = "off_peak_energy"
ATTR_TOTAL_ENERGY = "total_energy"
ATTR_EFFICIENCY = "efficiency"
ATTR_FECHA_INICIAL = "fecha_inicial"
ATTR_FECHA_FINAL = "fecha_final"
ATTR_LAST_UPDATE = "last_update"
