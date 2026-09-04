# Notas de la versión 1.1.0

- Fecha de liberación: `2026-09-04`.
- DOI reservado de la versión: `10.5281/zenodo.22313152`.
- Repositorio: `CastellanosBS/acme-firm-m6-fatigue`.
- Versión Git: `v1.1.0`.
- Estado al sellar el candidato: borrador de Zenodo todavía no publicado.

## Naturaleza de la versión

Esta es la primera materialización pública preparada de
`IFATIGUE-INFRA6-M6`. Es una reconstrucción doctoral nueva y trazable; no es
una actualización binaria ni una continuación material del paquete histórico
`v1.0.0`, que no estuvo disponible.

## Contenido funcional

- siete artefactos documentales del núcleo M1--M5 y su empaquetado M6;
- especificación por capas, configuración resuelta y contratos cerrados;
- implementación en Python 3.12 sin dependencias de terceros;
- dieciséis escenarios sintéticos y dieciséis oráculos independientes;
- dieciocho pruebas unitarias catalogadas;
- dieciséis resultados, quince trazas y un rechazo previo a modulación;
- manifiestos, procedencia, instrucciones de ejecución y guía de adaptación.

## Verificación

La reproducción limpia `RUN-T04-CLEAN-001` volvió a generar la evidencia desde
una extracción fresca del ZIP candidato aprobado. Obtuvo 16/16 escenarios,
18/18 pruebas, 15/15 trazas y 1/1 rechazo, con cero diferencias de membresía,
tamaño o contenido en 159/159 archivos. El reporte completo está en
`docs/T04_CLEAN_REPRODUCTION.md`.

## Cambios respecto del candidato T03 aprobado

La capa T05 modifica únicamente archivos públicos de presentación y gobierno:

- activa Apache-2.0 y CC-BY-4.0 por alcance;
- incorpora autor, contacto, repositorio previsto y metadatos de cita;
- añade créditos, exclusiones y notas de versión;
- documenta la reproducción limpia T04;
- reemplaza el manifiesto del candidato por el manifiesto integral de la
  distribución pública.

No cambian la fórmula, los parámetros, la implementación productiva, la
configuración ejecutada, los escenarios, los oráculos, las pruebas, los
resultados, las trazas, las tolerancias ni los límites epistémicos. La
comparación externa del expediente T05 enumera cada archivo añadido, retirado,
modificado o idéntico y bloquea cualquier diferencia fuera de la lista
aprobada; esa evidencia de auditoría no forma parte del payload científico de
la distribución.

## Datos y alcance

Todos los datos de ejecución son sintéticos. GEA y cualquier material derivado
directamente de GEA están excluidos. La evidencia acredita conformidad
contractual reproducible dentro de A3--A4; no acredita validez psicológica,
clínica, causal o empírica, ni generalización o utilidad operacional.
