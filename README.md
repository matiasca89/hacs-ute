# UTE Consumo - Home Assistant Add-on

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Add-on de Home Assistant para obtener datos de consumo de energía eléctrica desde el portal de autoservicio de UTE (Uruguay).

## Instalación

### Como Add-on de Home Assistant

1. En Home Assistant, ve a **Configuración** → **Complementos** → **Tienda de complementos**
2. Menú ⋮ → **Repositorios**
3. Agregar: `https://github.com/matiasca89/hacs-ute`
4. Buscar **"UTE Consumo"** e instalar
5. Configurar credenciales en la pestaña **Configuración**
6. Iniciar el add-on

## Características

- **Energía Punta**: Consumo en horario punta (kWh)
- **Energía Fuera de Punta**: Consumo en horario fuera de punta (kWh)
- **Energía Total**: Consumo total del período (kWh)
- **Eficiencia**: Porcentaje de consumo fuera de punta
- **Período de Facturación**: Rango de fechas del período actual

## Requisitos

- Home Assistant 2024.1 o superior
- Cuenta de UTE con acceso al portal de autoservicio
- Playwright instalado en el sistema

## Instalación

### HACS (Recomendado)

1. Abre HACS en Home Assistant
2. Ve a "Integraciones"
3. Haz clic en los tres puntos en la esquina superior derecha
4. Selecciona "Repositorios personalizados"
5. Añade `https://github.com/matiasca89/hacs-ute` como repositorio de tipo "Integración"
6. Busca "UTE Consumo" e instálalo
7. Reinicia Home Assistant

### Manual

1. Copia la carpeta `custom_components/ute_consumo` a tu directorio `config/custom_components/`
2. Reinicia Home Assistant

## Configuración

1. Ve a **Configuración** → **Dispositivos y servicios**
2. Haz clic en **Añadir integración**
3. Busca **UTE Consumo Energía**
4. Ingresa tus credenciales:
   - **Usuario**: Tu usuario de UTE (cédula o email)
   - **Contraseña**: Tu contraseña de UTE
   - **ID de Cuenta (NIS)**: El número de cuenta/NIS que aparece en tu factura

## Sensores

| Sensor | Descripción | Unidad |
|--------|-------------|--------|
| `sensor.ute_energia_peak_energy` | Consumo en horario punta | kWh |
| `sensor.ute_energia_off_peak_energy` | Consumo fuera de punta | kWh |
| `sensor.ute_energia_total_energy` | Consumo total | kWh |
| `sensor.ute_energia_efficiency` | Eficiencia (% fuera de punta) | % |
| `sensor.ute_energia_billing_period` | Período de facturación | - |

## Dashboard de Energía

Los sensores de energía son compatibles con el dashboard de energía de Home Assistant. Para configurarlo:

1. Ve a **Configuración** → **Dashboards** → **Energía**
2. En "Consumo de la red", añade los sensores de energía

## Notas

- Los datos se actualizan cada hora por defecto
- El scraper utiliza Playwright para navegar el sitio de UTE
- La eficiencia indica qué porcentaje del consumo fue en horario fuera de punta (más económico)

## Troubleshooting

### Error de autenticación
- Verifica que tus credenciales sean correctas
- Asegúrate de que puedes acceder a https://autoservicio.ute.com.uy manualmente

### Error de conexión
- Verifica tu conexión a internet
- El sitio de UTE puede estar temporalmente no disponible

### Playwright no encontrado
Asegúrate de tener Playwright instalado:
```bash
pip install playwright
playwright install chromium
```

## Licencia

MIT License - Ver [LICENSE](LICENSE) para más detalles.
