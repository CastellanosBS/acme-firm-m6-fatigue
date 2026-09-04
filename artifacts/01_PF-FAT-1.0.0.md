---
artifact_id: PF-FAT-1.0.0
artifact_version: 1.0.0
package_id: IFATIGUE-INFRA6-M6
package_version: 1.1.0
origin_class: generated_for_doctoral_instance
status: candidate_materialized_pending_T04_clean_reproduction
source_derivations:
  - DL-FST-001
  - DL-FST-002
  - DL-FST-003
  - DL-FST-004
  - DL-FST-005
  - DL-FST-006
  - DL-FST-007
  - DL-FST-CONFIDENCE-DOMAIN-001
  - DL-FST-CONFIDENCE-TYPE-001
  - DL-FST-008
  - DL-FST-009
  - DL-FST-010
  - DL-FST-011
  - DL-FST-012
  - DL-FST-013
  - DL-FST-014
  - DL-FST-015
  - DL-FST-016
  - DL-LIM-003
---

# Perfil del factor de influencia: fatiga cognitiva

## identity

El factor operacional es `cognitive_fatigue`, pertenece a la familia cognitiva y su estado corresponde al estudiante. La valoración que recibe la influencia pertenece al tutor. Esta separación de perspectivas es parte del contrato: el estado no representa fatiga del tutor y `coping_potential` no representa conducta de afrontamiento del estudiante.

Este documento es una materialización nueva de la instancia doctoral, no un artefacto histórico recuperado. El responsable nominal, la titularidad y la licencia no se infieren aquí; permanecen sujetos al cierre de propiedad intelectual del paquete.

## operational_definition

La fatiga cognitiva se representa como una condición transitoria mediante el nivel operacional `z = factor_state.level`. `z` es una cadena decimal IFM6-DEC-v1 dentro del intervalo cerrado `[0,1]`. En esta instancia, el estado entra directamente desde una fixture sintética de conformidad. No se implementa un estimador a partir de participantes, sensores, tiempos de respuesta, errores, pupilometría u otras señales humanas.

La definición permite probar el mecanismo de incorporación de un estado ya disponible; no valida una escala, un procedimiento de medición ni una relación causal universal entre fatiga y emoción.

## construct_boundary

La representación queda limitada a `cognitive_fatigue` como factor de la instancia F6. No identifica ni equipara automáticamente atención, carga cognitiva, distracción, desempeño, somnolencia o diagnóstico clínico. Tampoco convierte indicadores potenciales de esos fenómenos en mediciones válidas de fatiga.

El artefacto especifica el contrato del estado que consumiría la integración. El diseño, calibración y validación de un estimador humano quedan fuera de esta versión.

## state

El estado válido contiene exactamente los campos siguientes:

| Campo | Contrato |
|---|---|
| `level` | Cadena decimal IFM6-DEC-v1 en `[0,1]`, extremos incluidos. |
| `confidence` | Cadena decimal IFM6-DEC-v1 en `[0,1]`; la admisibilidad exige `confidence >= 0.5`. |
| `observed_at` | Marca RFC 3339 en UTC con forma `YYYY-MM-DDTHH:MM:SSZ`. |
| `source_id` | Cadena JSON NFC no vacía y con al menos un carácter no blanco; no se recorta ni normaliza silenciosamente. |
| `state_schema_version` | Versión exacta `1.0.0`. |

Campos ausentes, tipos incompatibles, valores fuera de dominio o propiedades adicionales activan el comportamiento fail-closed definido por el contrato.

## neutrality

El valor neutro operacional es `z = 0`. Con un estado admisible y una basal válida, ese valor hace que la transformación conserve `coping_potential` y, por localidad, las otras cinco coordenadas. Neutralidad computacional no significa ausencia clínica de fatiga ni certifica que el estudiante no experimente fatiga.

## confidence

`confidence` usa el mismo dominio técnico `[0,1]` y el mismo tipo de cadena decimal que `level`, pero expresa una propiedad diferente. Un valor válido para el tipo y el dominio es admisible solo si es al menos `0.5`. Un valor menor produce `FACTOR_CONFIDENCE_BELOW_MIN`; un valor fuera de `[0,1]` produce `FACTOR_CONFIDENCE_OUT_OF_RANGE` y no genera además el diagnóstico de umbral bajo.

La confianza es parte del contrato sintético de la instancia; no se presenta como probabilidad calibrada ni como estimación psicométrica.

## temporality

La ejecución recibe `evaluation_time` de forma inyectada y no consulta el reloj del sistema en la lógica probada. La edad se calcula como:

`age_seconds = evaluation_time - factor_state.observed_at`.

Ambas marcas deben ser válidas y estar en UTC. Una marca inválida impide aplicar comprobaciones temporales dependientes.

## freshness

El estado se considera obsoleto cuando `age_seconds >= 300`; el límite de 300 segundos pertenece a la región inválida. Se toleran como máximo cinco segundos hacia el futuro; el estado es inválido cuando `factor_state.observed_at - evaluation_time > 5 seconds`.

Un estado obsoleto o demasiado futuro no se modula. El sistema se abstiene y conserva la basal.

## failures

La validación ocurre después de validar la basal anfitriona. Si la basal falla, el proceso rechaza antes de inspeccionar el factor. Si la basal es válida pero el factor falla, la disposición es `abstained`, la salida conserva la basal y puede producirse una traza de abstención.

Los códigos diagnósticos autorizados, en prioridad fija, son:

1. `HOST_BASELINE_MISSING_FIELD`
2. `HOST_BASELINE_TYPE_INVALID`
3. `HOST_BASELINE_OUT_OF_RANGE`
4. `FACTOR_STATE_MISSING`
5. `FACTOR_STATE_TYPE_INVALID`
6. `FACTOR_LEVEL_MISSING`
7. `FACTOR_LEVEL_TYPE_INVALID`
8. `FACTOR_LEVEL_OUT_OF_RANGE`
9. `FACTOR_CONFIDENCE_MISSING`
10. `FACTOR_CONFIDENCE_TYPE_INVALID`
11. `FACTOR_CONFIDENCE_OUT_OF_RANGE`
12. `FACTOR_CONFIDENCE_BELOW_MIN`
13. `FACTOR_OBSERVED_AT_MISSING`
14. `FACTOR_OBSERVED_AT_INVALID`
15. `FACTOR_STATE_STALE`
16. `FACTOR_STATE_FROM_FUTURE`
17. `FACTOR_SOURCE_ID_MISSING`
18. `FACTOR_SOURCE_ID_TYPE_INVALID`
19. `FACTOR_SCHEMA_VERSION_MISSING`
20. `FACTOR_SCHEMA_VERSION_TYPE_INVALID`
21. `FACTOR_SCHEMA_VERSION_UNSUPPORTED`
22. `PUBLISHED_SUBSET_AMBIGUOUS`

Los diagnósticos representan clases de falla, se deduplican y se ordenan por esa prioridad. Las reglas de no cascada evitan añadir errores dependientes cuando falta un campo o su tipo o formato ya es inválido.

## governance

La corrida de referencia utiliza exclusivamente fixtures sintéticas y declara `empirical_support: none`. No emplea datos de participantes ni datos personales en el cómputo. La identidad administrativa del autor, cuando se incorpore al paquete, no forma parte de la lógica.

Esta ausencia de datos humanos no autoriza afirmar automáticamente una exención ética institucional. Cualquier adaptación con personas, sensores o registros reales deberá definir finalidad, minimización, base de legitimación, acceso, retención, seguridad, anonimización o seudonimización y revisión ética aplicable antes de recolectar o procesar datos.

## limits

- El artefacto no acredita validez de constructo, clínica, poblacional o psicométrica.
- No se implementó ni calibró un estimador humano.
- El dominio `[0,1]`, el umbral de confianza y las ventanas temporales son decisiones de ingeniería de esta instancia.
- La relación autorizada con `coping_potential` no prueba que la fatiga cause una emoción ni que el efecto sea universal.
- La corrida sintética acredita conformidad técnica interna; la reproducción limpia T04 y toda evaluación externa permanecen separadas.

## traceability

La definición doctoral del factor y su perspectiva proceden de `spec/thesis/f6_specification_rc01.json`; el contrato de campos, confianza, tiempo, fallas y prioridad diagnóstica procede de `spec/decisions/engineering_v1.1.0.json`; el alcance de datos y ética se conserva mediante `DL-LIM-003`. La lista cerrada de derivaciones del front matter es la autoridad de trazabilidad de este artefacto y corresponde a M1 dentro de la preparación de M6.

