---
artifact_id: PA-INFRA6-1.0.0
artifact_version: 1.0.0
package_id: IFATIGUE-INFRA6-M6
package_version: 1.1.0
origin_class: generated_for_doctoral_instance
status: candidate_materialized_pending_T04_clean_reproduction
source_derivations:
  - DL-HST-001
  - DL-HST-002
  - DL-HST-003
  - DL-HST-004
  - DL-HST-PUB-005
  - DL-HST-PUB-006
  - DL-HST-PUB-007
  - DL-HST-PUB-008
  - DL-HST-PUB-009
  - DL-HST-PUB-010
  - DL-HST-PUB-GAEF-2018A-PRODUCER
  - DL-HST-PUB-GAEF-2018A-BOUNDARY
  - DL-HST-PUB-GAEF-2018B-PRODUCER
  - DL-HST-PUB-GAEF-2018B-BOUNDARY
  - DL-HST-011
  - DL-HST-012
  - DL-HST-013
  - DL-HST-014
  - DL-HST-015
  - DL-HST-016
  - DL-HST-BND-SOURCE-MAP-2018A
  - DL-HST-BND-SOURCE-MAP-2018B
  - DL-HST-BND-SOURCE-MAP-POLICY-001
  - DL-LX-SOURCE-MAP-2018A
  - DL-LX-SOURCE-MAP-2018B
  - DL-LX-SOURCE-MAP-POLICY-001
  - DL-RUL-SELECT-001
---

# Perfil del ACME anfitrión InFra-6 reconstruido

## identity_and_provenance

El anfitrión de referencia es `ACME-INFRA6-RR-1.0.0`. Es una reconstrucción acotada a partir de la especificación publicada y de las decisiones doctorales necesarias para la instancia F6; no es código histórico recuperado, no reconstruye toda InFra y no acredita equivalencia con un motor fuzzy o una arquitectura completa.

Su propósito en el paquete es ofrecer una frontera anfitriona de seis coordenadas con la que pueda ejecutarse y auditarse la influencia monofactorial. La procedencia física de cada transcripción y adaptación está registrada en `sources/SOURCES.json` y `sources/DERIVATION_LEDGER.csv`.

## six_variables

La capa publicada conserva, sin reordenar ni reescribir, los seis nombres localizados en la fuente 2018a:

| Posición publicada | Lexema conservado |
|---:|---|
| 1 | `Expectedness` |
| 2 | `Desirability` |
| 3 | `Novelty` |
| 4 | `Goals conduciveness` |
| 5 | `Pleasure` |
| 6 | `Coping potential` |

Esta lista documenta nombres fuente. Por sí sola no proporciona una definición semántica exhaustiva ni autoriza una implementación retrospectiva de toda la publicación.

## doctoral_order

La API y la serialización de la reconstrucción doctoral usan exactamente este orden:

1. `expectedness`
2. `desirability`
3. `novelty`
4. `pleasure`
5. `goal_conduciveness`
6. `coping_potential`

El cambio de posición entre `Pleasure` y `Goals conduciveness` respecto de la lista publicada es una decisión explícita de la capa doctoral. No se atribuye ese orden canónico a la fuente de 2018.

## published_semantics

Las reglas publicadas se conservan con sus lexemas, capitalización, espacios y guiones originales. La reconstrucción utiliza solo el subconjunto declarado:

- `RULE-SADNESS-2018A` se mantiene como regresión simbólica aislada; no entra al ducto numérico F6.
- `RULE-ANGER-2018B-CONSISTENT` es la única fila de ira seleccionada para la continuidad acotada de S14.
- La fila 2018b cuya columna indica tristeza y cuyo consecuente indica ira se conserva como conflicto documental y se excluye de ejecución.
- Cero coincidencias producen `unclassified_by_published_subset`; más de una coincidencia produce `PUBLISHED_SUBSET_AMBIGUOUS` y falla de forma cerrada.

No se establece equivalencia implícita entre la etiqueta publicada `positive` y ninguna categoría crisp doctoral de `coping_potential`.

## doctoral_domain

La interfaz doctoral exige cardinalidad seis. Cada coordenada es una cadena decimal IFM6-DEC-v1 dentro de `[0,1]`, con ambos extremos incluidos. No se aceptan números binarios de punto flotante, valores no finitos, campos ausentes ni coordenadas adicionales.

El dominio es parte del contrato de esta reconstrucción; no se presenta como recuperación de funciones de pertenencia, unidades o rangos históricos no disponibles.

## baseline

Las basales de la corrida de referencia son fixtures sintéticas de conformidad con `empirical_support: none`. Permiten comparar la salida con oráculos congelados sin constituir observaciones de estudiantes, tutores o sistemas desplegados.

Una basal inválida se rechaza antes de validar el factor, modular o clasificar. El rechazo produce un resultado y un registro separado, pero no una traza de modulación.

## ga_ef_boundary

La frontera canónica de integración es:

| Rol | Término doctoral |
|---|---|
| Productor | `general_appraisal` |
| Punto de integración | `emotional_filter` |

La normalización se autoriza únicamente cuando el `source_id` y los términos fuente coinciden exactamente:

| Fuente | Productor publicado | Frontera publicada |
|---|---|---|
| `SRC-2018A-COGNITION-APPRAISAL` | `General Appraisal` | `Emotional Filter` |
| `SRC-2018B-FLEXIBLE-SCHEME` | `General Appraisal (GA)` | `Emotion Filter (EF)` |

No se permiten sustitución entre fuentes, inferencia de abreviaturas ni coincidencia aproximada.

## published_rules

La ruta de ejecución se limita a los fragmentos publicados materializados en `spec/published/`. La clasificación de S14 compara la basal y la salida contra la fila consistente de ira: antes de la modulación queda `unclassified_by_published_subset`; después, al ingresar en la banda `null`, queda `anger`. Las otras fixtures numéricas no se usan para completar una taxonomía emocional.

La regla de tristeza conserva su columna de causa, su antecedente de consecuencia y sus términos fuente en una prueba simbólica separada. Esta preservación verifica correspondencia documental, no adecuación psicológica externa.

## adapters

Los mapas ejecutables de antecedentes son exhaustivos y específicos por fuente:

| Fuente 2018a | Clave doctoral |
|---|---|
| `Coping potential (E)` | `coping_potential` |
| `Desirability(E)` | `desirability` |
| `Expectedness(E)` | `expectedness` |
| `Goal conduciveness (E)` | `goal_conduciveness` |
| `Novelty (E)` | `novelty` |
| `Pleasantness(E)` | `pleasure` |

| Fuente 2018b | Clave doctoral |
|---|---|
| `Coping potential (E)` | `coping_potential` |
| `Desirability (E)` | `desirability` |
| `Expectation (E)` | `expectedness` |
| `Goal-conduciveness (E)` | `goal_conduciveness` |
| `Novelty (E)` | `novelty` |
| `Pleasure (E)` | `pleasure` |

Una fuente desconocida, un lexema no exacto o un mapa ausente bloquean la resolución. Los adaptadores globales descriptivos no relajan estas reglas y la capa publicada nunca se modifica para aparentar homogeneidad retrospectiva.

## interfaces

La entrada anfitriona es un objeto cerrado de seis cadenas decimales en el orden doctoral. La salida conserva el mismo contrato y la misma cardinalidad. El flujo de la instancia es `evento -> valoración basal -> estado del factor -> valoración modulada -> clasificación publicada acotada -> traza`.

La única coordenada escribible por la influencia es `coping_potential`; las otras cinco son protegidas. La frontera rechaza la basal inválida antes de cualquier operación posterior y conserva un fallback explícito cuando el subconjunto publicado no clasifica.

## restrictions

- La reconstrucción no equivale al código, arquitectura o motor completo de InFra.
- La lista publicada de variables no se usa para atribuir semánticas o rangos no localizados.
- El orden, dominio decimal, partición crisp, adapters y fallback pertenecen a la capa doctoral.
- Los valores sintéticos no son datos empíricos ni calibración del anfitrión.
- Solo `coping_potential` puede cambiar directamente; un efecto posterior autorizado de clasificación no elimina la protección exacta de las otras coordenadas.
- M2 queda documentado para esta instancia, pero la afirmación acumulativa M6 permanece pendiente de la reproducción limpia T04.
