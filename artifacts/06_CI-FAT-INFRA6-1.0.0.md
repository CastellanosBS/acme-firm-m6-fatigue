---
artifact_id: CI-FAT-INFRA6-1.0.0
artifact_version: 1.0.0
package_id: IFATIGUE-INFRA6-M6
package_version: 1.1.0
origin_class: generated_for_doctoral_instance
status: candidate_materialized_pending_T04_clean_reproduction
source_derivations:
  - DL-HST-004
  - DL-HST-014
  - DL-HST-016
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
  - DL-DIAG-AGGREGATION-001
  - DL-MOD-005
  - DL-TRACE-SCHEMA
  - DL-TRACE-RESULT-PROJECTION-001
---

# Contrato de integración de fatiga con InFra-6

## data_contract

La basal anfitriona es un objeto cerrado de cardinalidad seis. Sus claves son `expectedness`, `desirability`, `novelty`, `pleasure`, `goal_conduciveness` y `coping_potential`; cada valor es una cadena decimal IFM6-DEC-v1 en `[0,1]`.

El estado del factor es un objeto cerrado con `level`, `confidence`, `observed_at`, `source_id` y `state_schema_version`. `level` y `confidence` son cadenas decimales en `[0,1]`; `observed_at` es RFC 3339 UTC; `source_id` es una cadena NFC no vacía con contenido no blanco; la versión exigida es `1.0.0`.

La salida no rechazada conserva el mismo contrato de seis coordenadas. Los documentos de resultado, traza y rechazo se validan contra sus respectivos JSON Schema cerrados.

## semantic_contract

`cognitive_fatigue` es un estado del estudiante. El appraisal es del tutor. `coping_potential` significa capacidad percibida por el tutor para responder pedagógicamente. Solo esa coordenada es escribible; las otras cinco son protegidas.

La fórmula, el parámetro, la partición crisp y la temporalidad son decisiones doctorales de la instancia. Los términos publicados se conservan en su capa y se normalizan solo mediante adapters exactos específicos por fuente.

## preconditions

- El paquete y la configuración corresponden a `IFATIGUE-INFRA6-M6` versión `1.1.0`.
- El manifiesto fuente ha sido construido y verificado antes de ejecutar.
- La basal satisface cardinalidad, claves, tipos y dominio.
- `evaluation_time` es una marca UTC inyectada.
- El estado satisface campos, dominio, confianza mínima, vigencia, fuente y versión.
- Los cuatro bindings y la máscara coinciden exactamente con la configuración resuelta.
- Los escenarios y oráculos están congelados e independientes de la función bajo prueba.

## postconditions

| Condición | Obligación de salida |
|---|---|
| Basal y factor válidos | Resultado válido; fórmula evaluada; seis coordenadas de salida; traza S00–S14. |
| Estado neutro válido | `applied_no_change`; basal conservada; traza con fórmula. |
| Factor inválido con basal válida | `abstained`; basal conservada; fórmula no evaluada; traza de abstención. |
| Basal inválida | `rejected`; factor no validado; modulación y clasificación no intentadas; registro de rechazo; ninguna traza de modulación. |

En toda salida no rechazada, las cinco coordenadas protegidas son exactamente iguales a la basal y `coping_potential` permanece en `[0,1]`.

## validation_order

El orden fijo es `host_baseline` y después `factor_state`. El cortocircuito anfitrión es vinculante: si existe cualquier diagnóstico `HOST_*`, solo se reportan diagnósticos anfitriones y se prohíben validación del factor, modulación, clasificación y creación de traza.

Dentro del factor se valida primero el contenedor y después los campos en este orden: `level`, `confidence`, `observed_at`, `source_id`, `state_schema_version`. Las comprobaciones dependientes solo se ejecutan si la presencia y el tipo o formato de su campo son válidos.

## failures

Las fallas anfitrionas son ausencia de coordenada, tipo/estructura inválida o valor fuera de rango. Las fallas del factor abarcan contenedor, presencia, tipo, dominio, confianza, formato temporal, vigencia, procedencia y versión. Una coincidencia múltiple del subconjunto publicado produce `PUBLISHED_SUBSET_AMBIGUOUS` después de superar ambos contratos.

El comportamiento es fail-closed. No existen coerciones de tipos, trimming de `source_id`, normalización Unicode silenciosa, defaults de bindings ni recuperación que modifique una basal inválida.

## diagnostics

El vocabulario consta exactamente de 22 códigos, desde `HOST_BASELINE_MISSING_FIELD` hasta `PUBLISHED_SUBSET_AMBIGUOUS`, en la prioridad declarada por `DL-FST-016`. La salida contiene el conjunto completo de clases independientemente detectables, sin duplicados y en orden fijo.

Reglas de no cascada relevantes:

- un campo ausente suprime diagnósticos de tipo, dominio y dependencias para ese campo;
- un tipo o formato inválido suprime umbrales y cálculos temporales dependientes;
- `confidence` fuera de `[0,1]` no añade `FACTOR_CONFIDENCE_BELOW_MIN`;
- una marca temporal inválida no añade obsolescencia ni futuro;
- un contenedor de factor ausente o no objeto no se recorre.

## tolerance

La tolerancia numérica de evaluación es `0.000000000001`. Se aplica al juicio de correspondencia donde el contrato lo declara. Las igualdades estructurales, los códigos y su orden, las versiones, las claves, la máscara, los bindings, las coordenadas protegidas y los hashes requieren igualdad exacta.

## versions

| Elemento | Versión o identificador |
|---|---|
| Paquete | `IFATIGUE-INFRA6-M6` `1.1.0` candidato |
| Artefactos internos | `1.0.0` |
| Anfitrión reconstruido | `ACME-INFRA6-RR-1.0.0` |
| Estado del factor | `1.0.0` |
| Esquema de escenario | `1.0.0` |
| Esquema de traza | `1.0.0` |
| Especificación resuelta | `1.1.0` |
| Contrato QA | `IFM6-QA-CONTRACT-1.0.0` |

Una modificación semántica exige revisar artefactos dependientes, incrementar la versión afectada y repetir las pruebas y evidencias impactadas.

## acceptance_criteria

La aceptación técnica interna de la corrida exige simultáneamente:

1. manifiesto fuente verificado antes de ejecutar;
2. 16 escenarios y 16 oráculos congelados con correspondencia uno-a-uno;
3. 16/16 resultados iguales a sus oráculos y válidos por esquema;
4. exactamente 15 trazas S00–S14 con `trace_id` recomputable;
5. exactamente un rechazo S15 y ausencia de `S15.trace.json`;
6. ejecución exacta de 18 métodos UT-001–UT-018 sin fallas, errores, omisiones ni éxitos inesperados;
7. neutralidad, dominio, localidad, preservación semántica y trazabilidad satisfechos;
8. validadores obligatorios con salida cero y ningún hallazgo abierto en el control interno.

La corrida T03 observada satisface los conteos de escenarios, resultados, trazas, rechazo y pruebas. La conformidad acumulativa M6 no se declara definitiva hasta completar el paquete, su dictamen interno y la reproducción limpia T04.
