# Mapa de fuentes y derivaciones

## Naturaleza del documento

Este archivo es una síntesis documental nueva con clase `generated_for_doctoral_instance`, contrastada con el registro canónico de fuentes, el libro de derivación y la procedencia del paquete. No es una salida ejecutada ni crea una autoridad nueva. En caso de diferencia, prevalecen `sources/SOURCES.json`, `sources/DERIVATION_LEDGER.csv` y `PROVENANCE.json`.

La instantánea documentada contiene ocho obras fuente, un contenedor mixto, catorce manifestaciones, treinta y una unidades de evidencia, siete registros de proceso y dos recursos no disponibles. Que una copia haya sido inspeccionada y tenga hash no implica licencia de redistribución, autenticidad editorial ni verdad científica.

## Obras fuente

| Identificador | Año | Obra | Papel en la reconstrucción | Límite principal |
|---|---:|---|---|---|
| `SRC-THESIS-CANONICAL` | 2026 | *ACME-FIRM: modelo de referencia para integrar factores de influencia en modelos computacionales de emoción basados en valoración* | Fuente doctoral normativa para F6, artefactos, contratos y límites | Manuscrito bajo evaluación; no se distribuye dentro del paquete |
| `SRC-2017-MODULATION` | 2017 | *Cognitive Modulation of Appraisal Variables in the Emotion Process of Autonomous Agents* | Antecedente publicado de modulación cognitiva | Dejó problemas abiertos; no prueba la instancia F6 actual |
| `SRC-2018A-COGNITION-APPRAISAL` | 2018 | *A Computational Model of Emotion Assessment Influenced by Cognition in Autonomous Agents* | Términos publicados, frontera General Appraisal/Emotional Filter y regresión simbólica acotada | No aporta la fórmula numérica doctoral ni sus parámetros |
| `SRC-2018B-FLEXIBLE-SCHEME` | 2018 | *A Flexible Scheme to Model the Cognitive Influence on Emotions in Autonomous Agents* | Esquema, pseudocódigo, adaptadores terminológicos y subconjunto simbólico acotado | Una fila conflictiva se conserva y se excluye de ejecución; no se corrige silenciosamente |
| `SRC-2019-BIASING-APPRAISAL` | 2019 | *A Mechanism for Biasing the Appraisal Process in Affective Agents* | Contexto histórico y prueba de concepto reportada | Java, jFuzzyLogic, PredictiveApriori y reglas históricas no son ejecutables de F6 |
| `SRC-2020-CHAPTER` | 2020 | *Configurable Appraisal Dimensions for Computational Models of Emotions of Affective Agents* | Metadatos bibliográficos | Solo se inspeccionó la envoltura bibliográfica; el texto completo no se usa para derivación científica |
| `SRC-2026-ACME-IFSG` | 2026 | *Systematic Guidelines for Extending the Appraisal Process in Computational Models of Emotion* | Linaje procedimental y guías de extensión | Coeficientes y métricas ilustrativos no se reutilizan como valores de F6 |
| `SRC-THESIS-HISTORICAL-2026-07-17` | 2026 | Versión histórica de la tesis, 2026-07-17 | Control histórico de cambios y contexto | No sustituye la tesis canónica ni prueba disponibilidad del paquete histórico |

## Contenedor mixto y manifestaciones

`CNT-MIXED-2019-2020` es un único contenedor entregado que reúne material correspondiente a 2019 y una envoltura bibliográfica de 2020. El segmento científico de 2019 y los metadatos de 2020 se registran por separado; el contenedor físico compartido no autoriza a tratar la envoltura de 2020 como texto completo inspeccionado.

Las catorce manifestaciones registran copias concretas —por ejemplo, fuentes LaTeX, PDF o segmentos— con sus localizadores y hashes cuando están disponibles. Los archivos fuente y los PDF no se redistribuyen en este candidato.

## Clases de transformación

| Capa | Uso permitido | Control |
|---|---|---|
| Fuente publicada | Preservar términos, fragmentos, reglas y estructura localizables | No incorporar decisiones doctorales a la capa publicada |
| Especificación doctoral | Definir el caso F6, la fórmula, el parámetro, el alcance y los límites | Identificar cada inferencia y decisión como doctoral |
| Adaptadores y decisiones | Resolver diferencias léxicas y estructurales de forma explícita | Coincidencia exacta por fuente; cierre seguro ante ambigüedad |
| Derivación automática | Producir configuración, resultados, trazas y resúmenes declarados como derivados | No editar manualmente salidas declaradas como derivadas |

La relación campo a campo se encuentra en `sources/DERIVATION_LEDGER.csv`. Las clases de afirmación (`explicit_source`, `doctoral_inference`, `generated_for_doctoral_instance`, `excluded_from_execution` y `pending_verification`) se definen en `PROVENANCE.json`.

## Recursos ausentes

| Recurso | Estado y consecuencia |
|---|---|
| `RES-GEA` | No disponible ni inspeccionado; no se usa para construir, calibrar, ejecutar, definir oráculos, probar o redistribuir. Las dimensiones o tamaños reportados en fuentes no se presentan como auditoría directa. |
| `RES-M6-V1-0-0` | Paquete histórico no disponible; no se copiaron bytes ni código y no se afirma continuidad binaria o material. |

La tesis canónica puede describir auditorías o resultados históricos, pero el presente paquete distingue lo reportado de lo directamente verificable. Ninguna propiedad de GEA ni del paquete histórico ausente se eleva aquí a observación propia.
