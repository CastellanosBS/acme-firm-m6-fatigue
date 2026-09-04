# Registro de cambios

Los cambios se registran con fechas reales del proceso. Este archivo no reconstruye retrospectivamente un historial de versiones ausente.

## 1.1.0 — 2026-09-04

La capa de publicación deriva del candidato aprobado mediante
`T03.3-10-CAN-001` y de la reproducción limpia aprobada mediante `T04-RL-001`.
Activa Apache-2.0 y CC-BY-4.0 por alcance; incorpora autor, contacto, créditos,
repositorio previsto, metadatos de cita, notas de versión y el reporte T04.

No cambia fórmula, parámetros, implementación productiva, configuración
ejecutada, escenarios, oráculos, pruebas, resultados, trazas, tolerancias ni
límites epistémicos. El DOI reservado de la versión es
`10.5281/zenodo.22313152`. El commit, el tag y el hash del ZIP se fijan en el
expediente externo al sellar el candidato exacto de publicación.

## 1.1.0-candidate — 2026-09-04

Primera materialización verificable del candidato reconstruido `IFATIGUE-INFRA6-M6`. No es una actualización binaria ni una sustitución del paquete histórico `v1.0.0`, que no estuvo disponible.

### Incorporado

- registro canónico de fuentes, procedencia y libro de derivación;
- especificaciones publicadas preservadas, decisiones doctorales, enlaces y configuración resuelta;
- esquemas cerrados, dieciséis escenarios sintéticos y dieciséis oráculos independientes congelados;
- implementación Python con biblioteca estándar, dieciocho pruebas catalogadas y generación transaccional;
- corrida de referencia identificada en `PACKAGE_METADATA.json#/source_snapshot/run_id`: 16/16 coincidencias, 18/18 pruebas, 15 trazas y un rechazo previo a modulación;
- siete artefactos documentales y documentación operativa de T03.3-9;
- finalización determinista T03.3-10 con `BUILD_RECORD`, manifiesto final y
  distribución ZIP verificable. La aceptación canónica del hash resultante se
  conserva en el expediente externo de cierre, sin modificar el candidato.

### Corregido durante T03.3-8

El primer intento de la corrida no promovió archivos porque `UT-018` falló. El diagnóstico comprobó que dos sondas asignaban `0.11` a campos que ya contenían `0.11`; por tanto, no modificaban el núcleo de traza. Mediante la aprobación específica `T03.3-8-COR-001` se cambiaron únicamente esas dos sondas a `0.12`, se volvió a congelar la fuente y se repitió la corrida. No cambiaron la fórmula, los parámetros, la implementación productiva, los escenarios, los oráculos ni las tolerancias.

### Corregido durante T03.3-10

La primera tentativa de finalización expuso que el validador interpretaba
`PACKAGE_METADATA.json` como inventario vivo y rechazaba los dos nodos finales
aunque sus bytes y el ZIP fueran íntegros. Se corrigió la transición para
mantener esa metadata como instantánea T03.3-9, aceptar únicamente el par final
completo y determinista, y rechazar estados parciales, manipulados o no
canónicos. La fuente y todos sus descendientes criptográficos se recongelaron y
regeneraron. La corrección no cambió fórmula, parámetros, implementación
productiva, escenarios, oráculos, tolerancias ni límites epistémicos.

### Evaluaciones posteriores

- T04: reproducción limpia fuera del árbol de referencia;
- F5: panel externo, sin uso como evidencia M6;
- T05: decisión de propiedad intelectual, licencia efectiva, reconfirmación de los metadatos públicos de `CITATION.cff` y eventual depósito.

En ese estado candidato todavía no existían etiqueta Git, DOI, licencia activa
ni liberación pública; la capa T05 posterior registra esos elementos sin
reescribir retrospectivamente el expediente T03.
