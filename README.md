# UTE Consumo - Home Assistant Add-on

Add-on de Home Assistant para obtener datos de consumo de energía eléctrica desde el portal de autoservicio de UTE (Uruguay).

## ⚠️ Importante: Datos a día vencido

Los datos de consumo que provee UTE son **a día vencido**. Esto significa que el consumo que ves corresponde hasta el día **anterior**. Por ejemplo, si hoy es 22 de enero, los datos mostrarán el consumo acumulado del 1 al 21 de enero.

## Instalación

1. En Home Assistant: **Configuración** → **Complementos** → **Tienda de complementos**
2. Menú ⋮ (tres puntos) → **Repositorios**
3. Agregar: `https://github.com/matiasca89/hacs-ute`
4. Buscar **"UTE Consumo"** e instalar
5. Ir a la pestaña **Configuración** e ingresar:
   - **Usuario**: Tu usuario de UTE (cédula o email)
   - **Contraseña**: Tu contraseña de UTE
   - **Account ID**: El número de cuenta/NIS de tu factura
   - **Scan Interval**: Intervalo de actualización en minutos (default: 60)
6. Iniciar el add-on

## Sensores

### Consumo Acumulado (mes actual)

| Sensor | Descripción | Unidad |
|--------|-------------|--------|
| `sensor.ute_energia_punta` | Consumo acumulado en horario punta | kWh |
| `sensor.ute_energia_fuera_punta` | Consumo acumulado fuera de punta | kWh |
| `sensor.ute_energia_total` | Consumo total acumulado del mes | kWh |
| `sensor.ute_eficiencia` | % de consumo en horario fuera de punta | % |
| `sensor.ute_periodo` | Período de facturación actual | - |

### Consumo Diario

| Sensor | Descripción | Unidad |
|--------|-------------|--------|
| `sensor.ute_diario_punta` | Consumo del día anterior en horario punta | kWh |
| `sensor.ute_diario_fuera_punta` | Consumo del día anterior fuera de punta | kWh |
| `sensor.ute_diario_total` | Consumo total del día anterior | kWh |

> **Nota**: Los sensores diarios calculan el delta entre días. Se actualizan cuando el addon detecta un cambio de día (medianoche hora Uruguay, UTC-3).

## Horarios de UTE

- **Horario Punta**: 18:00 - 23:00 (más caro)
- **Horario Fuera de Punta**: 23:00 - 18:00 (más económico)

La **eficiencia** indica qué porcentaje de tu consumo fue en horario fuera de punta. Mayor eficiencia = menor costo.

## Dashboard de Energía

Los sensores son compatibles con el Energy Dashboard de Home Assistant:

1. **Configuración** → **Dashboards** → **Energía**
2. En "Consumo de la red", añadir `sensor.ute_energia_total`

## Troubleshooting

### Error de autenticación
- Verificá que tus credenciales sean correctas en https://autoservicio.ute.com.uy

### Los sensores diarios no aparecen
- Los sensores diarios se crean después del primer cambio de día detectado
- Esperá 24 horas después de instalar el addon

### El consumo no se actualiza
- Revisá los logs del addon en **Complementos** → **UTE Consumo** → **Registro**
- UTE puede tener demoras en actualizar los datos

## Licencia

MIT License
