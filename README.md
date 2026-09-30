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
6. Iniciar el add-on (requiere Home Assistant Core 2026.9 o posterior).
7. `import_statistics` habilita las estadísticas de Energía (default: `true`). Puede desactivarse para usar sólo los sensores de visualización.

## Sensores

### Consumo Acumulado (mes del último día completo disponible)

| Sensor | Descripción | Unidad |
|--------|-------------|--------|
| `sensor.ute_energia_punta` | Consumo acumulado en horario punta | kWh |
| `sensor.ute_energia_fuera_punta` | Consumo acumulado fuera de punta | kWh |
| `sensor.ute_energia_total` | Consumo total acumulado del mes | kWh |
| `sensor.ute_eficiencia` | % de consumo en horario fuera de punta | % |
| `sensor.ute_periodo` | Rango de fechas consultado, no necesariamente el período de facturación | - |

### Consumo Diario

| Sensor | Descripción | Unidad |
|--------|-------------|--------|
| `sensor.ute_diario_punta` | Consumo del día anterior en horario punta | kWh |
| `sensor.ute_diario_fuera_punta` | Consumo del día anterior fuera de punta | kWh |
| `sensor.ute_diario_total` | Consumo total del día anterior | kWh |

> Desde 1.4.0, los diarios provienen de consultas UTE por día, no de restar acumulados. El atributo `fecha_consumo` identifica el último día confirmado; si UTE se demora, puede no ser ayer. Se conserva ese último valor si una respuesta llega vacía o trae fechas más antiguas. Un dato nunca confirmado queda `unavailable`, nunca cero inventado. La primera carga consulta cada día del mes en la misma sesión autenticada y puede demorar más que versiones anteriores.
>
> El primer día del mes, el período consultado sigue siendo el mes anterior. Los sensores diarios y mensuales son para visualizar: no tienen `state_class` acumulativa, ya que UTE puede corregirlos hacia arriba o abajo.

## Horarios de UTE

- **Horario Punta**: 18:00 - 23:00 (más caro)
- **Horario Fuera de Punta**: 23:00 - 18:00 (más económico)

La **eficiencia** indica qué porcentaje de tu consumo fue en horario fuera de punta. Mayor eficiencia = menor costo.

## Dashboard de Energía

La app importa una **estadística externa nueva**, «UTE Consumo diario», con identificador `ute_consumo:energia_<hash_de_cuenta>`. El atributo `statistic_id` de `sensor.ute_energia_total` muestra el identificador exacto.

1. Actualizá y esperá una consulta exitosa y la confirmación de estadísticas en el registro.
2. **Configuración** → **Dashboards** → **Energía** → **Consumo de la red**.
3. Seleccioná **UTE Consumo diario** (estadística externa), no `sensor.ute_energia_total` ni los sensores diarios.
4. Retirá la fuente vieja de la configuración para no contar dos veces. Esto **no borra** sus estadísticas históricas.

La app no cambia tus preferencias de Energía ni borra/reescribe los sensores anteriores. Guarda un registro por fecha en `/data/ute_state.json`, aislado por cuenta. No reutiliza los `sum` de sensores/helpers antiguos. Conservá un backup completo de la app y de Home Assistant antes de actualizar; para volver atrás, restaurá ese backup, no sólo la imagen vieja.

**Resolución diaria:** la serie comienza en el primer día confirmado por UTE, sin inventar consumo de días anteriores. Cada total se guarda a medianoche de Uruguay en la fecha de consumo, aunque UTE lo publique después. Esto sirve para totales diarios/mensuales; **no es una medición horaria** ni permite calcular costos horarios exactos. Si falta un día intermedio, se detiene la importación en ese punto y se vuelve a consultarlo, sin rellenar huecos con cero; el registro distingue un prefijo verificado con días pendientes de una sincronización completa. Si se recuperan fechas anteriores y aún faltan días para recalcular estadísticas posteriores ya importadas, la app conserva esas estadísticas sin escribir nuevas filas hasta completar el hueco; no es motivo para descartar el registro recuperado. Los datos ya confirmados no se eliminan porque una consulta posterior venga vacía.

**Alcance del histórico:** la primera instalación recupera el mes consultado, no toda la historia de la cuenta. Después se conserva el registro y se vuelve a consultar desde el último mes continuo para recuperar atrasos/cortes y correcciones del período consultado. No se garantiza detectar correcciones de meses anteriores que ya no se consultan. Si el registro se pierde o se restaura una copia incompleta y HA tiene fechas fuera del registro recuperado, se rechaza la importación hasta restaurar un backup coherente. Una respuesta WebSocket exitosa sólo encola el trabajo: la app lee las filas de Recorder antes de confirmar la sincronización.

## Troubleshooting

### Error de autenticación
- Verificá que tus credenciales sean correctas en https://autoservicio.ute.com.uy

### Los sensores diarios no aparecen
- Revisá `fecha_consumo` y el registro: UTE puede no haber publicado el día solicitado.
- No es necesario esperar un cambio de medianoche; aparecen en la primera consulta diaria válida.
- Si Energía todavía no tiene datos, revisá si falta un día intermedio o falló la importación de estadísticas.

### El consumo no se actualiza
- Revisá los logs del addon en **Complementos** → **UTE Consumo** → **Registro**
- UTE puede tener demoras en actualizar los datos

## Licencia

MIT License
