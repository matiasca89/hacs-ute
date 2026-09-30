# Changelog

## 1.4.0

- Consultas por fecha de consumo real en hora de Uruguay; ya no se calcula el diario por delta del acumulado mensual.
- Estadísticas externas para Energía, con una serie nueva por cuenta y resolución diaria; no se modifica el histórico de sensores anteriores.
- Registro persistente de días, recuperación de días pendientes y correcciones sin duplicar consumo al reiniciar.
- Los datos ausentes quedan no disponibles, no se publican como ceros ni se interpretan descensos como resets.
- Los sensores diarios y mensuales se mantienen para visualizar; para Energía se debe seleccionar la nueva estadística «UTE Consumo diario» después de actualizar.
- Requiere Home Assistant Core 2026.9 o posterior. La importación puede desactivarse con `import_statistics: false`.

## 1.3.5

- Home Assistant can now display this changelog in the app update dialog.

## 1.3.4

- Retry temporary UTE network changes during login.
- Update daily consumption whenever UTE publishes a newer cumulative reading.

## 1.3.3

- Reduced the add-on image from 944 MB to 329 MB.
- Added automated build, test and Chromium smoke checks.

## 1.3.2

- Release Chromium memory between scrapes.
