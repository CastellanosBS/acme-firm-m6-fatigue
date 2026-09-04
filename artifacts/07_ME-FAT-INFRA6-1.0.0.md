---
artifact_id: ME-FAT-INFRA6-1.0.0
artifact_version: 1.0.0
package_id: IFATIGUE-INFRA6-M6
package_version: 1.1.0
origin_class: generated_for_doctoral_instance
status: candidate_materialized_pending_T04_clean_reproduction
source_derivations:
  - DL-EVAL-001
  - DL-EVAL-002
  - DL-EVAL-003
  - DL-EVAL-004
  - DL-LIM-001
  - DL-LIM-002
  - DL-LIM-003
  - DL-LIM-004
  - DL-TRACE-SCHEMA
  - DL-TRACE-RESULT-PROJECTION-001
  - DL-TRACE-TEMPLATE-001
  - DL-TRACE-BINDING-S00
  - DL-TRACE-BINDING-S01
  - DL-TRACE-BINDING-S02
  - DL-TRACE-BINDING-S03
  - DL-TRACE-BINDING-S04
  - DL-TRACE-BINDING-S05
  - DL-TRACE-BINDING-S06
  - DL-TRACE-BINDING-S07
  - DL-TRACE-BINDING-S08
  - DL-TRACE-BINDING-S09
  - DL-TRACE-BINDING-S10
  - DL-TRACE-BINDING-S11
  - DL-TRACE-BINDING-S12
  - DL-TRACE-BINDING-S13
  - DL-TRACE-BINDING-S14
  - DL-REC-TRACE-S00
  - DL-REC-TRACE-S01
  - DL-REC-TRACE-S02
  - DL-REC-TRACE-S03
  - DL-REC-TRACE-S04
  - DL-REC-TRACE-S05
  - DL-REC-TRACE-S06
  - DL-REC-TRACE-S07
  - DL-REC-TRACE-S08
  - DL-REC-TRACE-S09
  - DL-REC-TRACE-S10
  - DL-REC-TRACE-S11
  - DL-REC-TRACE-S12
  - DL-REC-TRACE-S13
  - DL-REC-TRACE-S14
---

# Matriz de evaluación de la instancia F6

## purpose

Esta matriz verifica la correspondencia interna entre perfiles, mapa, modelo, realización, contrato, escenarios, oráculos, resultados y trazas de `IFATIGUE-INFRA6-M6` versión `1.1.0`. Su alcance es conformidad sintética de contrato, determinismo, reproducibilidad técnica, localidad y trazabilidad.

No es un experimento con participantes, una evaluación de campo, una validación clínica o psicométrica, ni una prueba de utilidad, efectividad, adopción, generalización o transferencia.

## scenarios_16

`scenarios/catalog.json` congela exactamente 16 fixtures de entrada independientes. Todas declaran `fixture_class: synthetic_conformance_fixture`, `empirical_support: none` y el mismo tiempo lógico inyectado.

| Escenario | Estímulo principal | Cobertura esperada |
|---|---|---|
| S00 | `z=0`, basal `coping=0.6` | Neutralidad. |
| S01 | `z=0.2`, basal `coping=0.6` | Modulación baja. |
| S02 | `z=0.5`, basal `coping=0.6` | Modulación intermedia. |
| S03 | `z=0.8`, basal `coping=0.6` | Modulación alta. |
| S04 | `z=1`, basal `coping=0.6` | Extremo superior de fatiga. |
| S05 | `z=1`, basal `coping=0` | Límite inferior del dominio. |
| S06 | `z=0`, basal `coping=1` | Límite superior y neutralidad. |
| S07 | Estado ausente | Abstención segura. |
| S08 | Edad 301 s | Obsolescencia estricta. |
| S09 | `z=-0.01` | Nivel bajo fuera de dominio. |
| S10 | `z=1.01` | Nivel alto fuera de dominio. |
| S11 | `confidence=0.49` | Confianza insuficiente. |
| S12 | Estado 6 s futuro | Futuro sobre tolerancia. |
| S13 | Edad 300 s | Inclusión exacta del límite obsoleto. |
| S14 | `z=1`, basal `coping=0.35` y payload de ira | Continuidad modulación–clasificación. |
| S15 | Basal `coping=1.1` | Rechazo anfitrión previo a factor. |

## oracles_16

Existe un oráculo independiente por escenario en `oracles/S00.expected.json` a `oracles/S15.expected.json`. Los oráculos fueron congelados antes de la implementación, no importan valores desde producción y declaran disposición, diagnósticos, contrato de salida, expectativas de modulación, clasificación y existencia de traza o rechazo.

La comparación exige igualdad estructural y semántica según los esquemas y la tolerancia numérica `0.000000000001`. El oráculo no se usa como entrada del sistema ni como fuente para construir resultados o trazas.

## results_16

La corrida `RUN-T03-REFERENCE-001` produjo exactamente un resultado por escenario. Los 16 documentos validaron contra el esquema y coincidieron con sus 16 oráculos.

| Escenario | Disposición observada | Diagnóstico | `coping_potential` de salida |
|---|---|---|---:|
| S00 | `applied_no_change` | — | `0.6` |
| S01 | `modulated` | — | `0.564` |
| S02 | `modulated` | — | `0.51` |
| S03 | `modulated` | — | `0.456` |
| S04 | `modulated` | — | `0.42` |
| S05 | `applied_no_change` | — | `0` |
| S06 | `applied_no_change` | — | `1` |
| S07 | `abstained` | `FACTOR_STATE_MISSING` | `0.6` |
| S08 | `abstained` | `FACTOR_STATE_STALE` | `0.6` |
| S09 | `abstained` | `FACTOR_LEVEL_OUT_OF_RANGE` | `0.6` |
| S10 | `abstained` | `FACTOR_LEVEL_OUT_OF_RANGE` | `0.6` |
| S11 | `abstained` | `FACTOR_CONFIDENCE_BELOW_MIN` | `0.6` |
| S12 | `abstained` | `FACTOR_STATE_FROM_FUTURE` | `0.6` |
| S13 | `abstained` | `FACTOR_STATE_STALE` | `0.6` |
| S14 | `modulated` | — | `0.245` |
| S15 | `rejected` | `HOST_BASELINE_OUT_OF_RANGE` | No aplica |

La distribución observada es cinco `modulated`, tres `applied_no_change`, siete `abstained` y un `rejected`. Los valores se transcriben de los resultados materializados, no de un registro legacy.

## traces_15

S00–S14 materializaron exactamente 15 trazas. Cada una contiene los nueve componentes cerrados del `trace_core`; su `trace_id` es recomputable como SHA-256 del `trace_core` canónico IFM6-JSON-v1. Las trazas de abstención preservan la basal y registran fórmula nula; las trazas de modulación registran el cálculo; S14 registra además la transición de clasificación.

La relación escenario–resultado–traza es uno-a-uno para S00–S14. La identidad del manifiesto fuente aparece en los resúmenes de la corrida y debe coincidir en todos ellos. Los hashes de los 41 descendientes se obtienen de los bytes materializados durante el cierre y se conservan en el inventario de paquete; este artefacto evita duplicarlos como una segunda autoridad mutable.

## rejection_1

S15 produjo exactamente un registro separado: `traces/reference_run/rejections/S15.rejection.json`. El rechazo ocurrió en `host_baseline` con `HOST_BASELINE_OUT_OF_RANGE`; `factor_validation_performed`, `modulation_attempted`, `classification_attempted`, `modulation_trace` y `trace_id_present` son falsos.

No existe ni puede existir `traces/reference_run/S15.trace.json`. El rechazo se cuenta entre los 16 resultados, pero no entre las 15 trazas de modulación.

## tests_18

El catálogo fija exactamente 18 métodos `unittest`, todos ejecutados y aprobados, sin fallas, errores, omisiones, fallas esperadas ni éxitos inesperados:

| ID | Comprobación |
|---|---|
| UT-001 | Neutralidad en S00 y S06. |
| UT-002 | Correspondencia de fórmula en S01–S04 y S14. |
| UT-003 | Localidad y coordenadas protegidas en S00–S14. |
| UT-004 | Límites del dominio en S05 y S06. |
| UT-005 | Monotonicidad no creciente en S00–S04. |
| UT-006 | Abstención por factor ausente en S07. |
| UT-007 | Rechazo de `level` por debajo y por encima del dominio en S09/S10. |
| UT-008 | Umbral de confianza en S11. |
| UT-009 | Obsolescencia, futuro y límite temporal en S08/S12/S13. |
| UT-010 | Precedencia de validación anfitriona en S15 y variante local. |
| UT-011 | Orden, deduplicación y no cascada de diagnósticos múltiples. |
| UT-012 | Versión de esquema del factor no soportada. |
| UT-013 | Continuidad acotada con la regla de ira en S14. |
| UT-014 | Preservación de términos y contexto de tristeza 2018a en regresión simbólica. |
| UT-015 | Preservación y exclusión de la fila contradictoria 2018b. |
| UT-016 | Falla cerrada ante múltiples coincidencias publicadas. |
| UT-017 | Estabilidad del `trace_id` para el mismo núcleo. |
| UT-018 | Sensibilidad del `trace_id` a cada componente del núcleo. |

## invariants

| Invariante | Evidencia interna | Juicio T03 |
|---|---|---|
| Neutralidad | S00, S06 y UT-001 conservan la basal con `z=0`. | Cumple. |
| Dominio | S05/S06 cubren extremos; todas las salidas no rechazadas quedan en `[0,1]`; UT-004. | Cumple. |
| Localidad | Las cinco coordenadas protegidas son idénticas en S00–S14; UT-003. | Cumple. |
| Preservación semántica | Perspectiva estudiante–tutor, adapters exactos, tristeza simbólica, conflicto excluido y continuidad S14; UT-013–UT-016. | Cumple en el subconjunto declarado. |
| Trazabilidad | 15 `trace_id` recomputables, bindings uno-a-uno, proyección desde resultados y pruebas UT-017/UT-018. | Cumple. |

El juicio corresponde a la corrida sintética de referencia y no equivale a validación externa.

## judgement_rules

El resultado global solo es `pass` si se satisfacen simultáneamente los 16 oráculos, se ejecutan y aprueban los 18 métodos exactos, existen 15 trazas válidas y un rechazo separado, no existe S15.trace, coinciden los conteos y hashes registrados, se preservan los cinco invariantes y todos los comandos obligatorios terminan con código cero.

Una diferencia de escenario, esquema, oráculo, disposición, diagnóstico, salida, coordenada protegida, receta de traza, `trace_id`, conteo o prueba detiene el cierre. Los oráculos y la implementación no se ajustan después de observar una falla sin una nueva decisión, versión y repetición controlada.

## evidence_limits

- Evidencia permitida: instanciación, conformidad técnica, determinismo, reproducibilidad, localidad y trazabilidad para la versión y topología declaradas.
- Evidencia no proporcionada: utilidad, efectividad, adopción externa, generalización, evaluación de campo o transferencia.
- No participaron personas y no se procesaron datos personales; ello no implica por sí solo exención ética institucional para futuros estudios.
- `z`, `confidence`, `lambda`, ventanas temporales y categorías crisp no están calibrados psicométricamente.
- La reconstrucción anfitriona y el subconjunto de reglas no equivalen a toda InFra ni a un ACME histórico completo.
- La corrida T03 no sustituye la reproducción limpia T04 ni un panel experto externo.

## execution_status

Estado observado de `RUN-T03-REFERENCE-001`: `pass` en 16/16 escenarios y 18/18 pruebas; 16 resultados, 15 trazas, un rechazo, cuatro productos agregados de resultados, tres logs y dos registros de entorno, para un total directo de 41 descendientes de ejecución.

El tiempo lógico fue `2026-09-04T12:00:00Z`; no se registraron métricas de rendimiento. La ausencia deliberada de tiempos evita presentar como benchmark una medición sin protocolo reproducible. El paquete permanece candidato y pendiente de T04; por tanto, este estado no autoriza declarar todavía una conformidad M6 final reproducida desde entorno limpio.
