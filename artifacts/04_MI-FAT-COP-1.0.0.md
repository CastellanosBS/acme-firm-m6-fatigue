---
artifact_id: MI-FAT-COP-1.0.0
artifact_version: 1.0.0
package_id: IFATIGUE-INFRA6-M6
package_version: 1.1.0
origin_class: generated_for_doctoral_instance
status: candidate_materialized_pending_T04_clean_reproduction
source_derivations:
  - DL-MOD-001
  - DL-MOD-002
  - DL-MOD-003
  - DL-MOD-004
  - DL-MOD-005
  - DL-BIND-001
  - DL-BIND-002
  - DL-BIND-003
  - DL-BIND-004
  - DL-FST-011
  - DL-FST-012
  - DL-FST-013
  - DL-FST-014
  - DL-CAT-001
  - DL-CAT-002
  - DL-CAT-003
  - DL-CAT-004
---

# Modelo de influencia de fatiga sobre Coping Potential

## formula

La transformación aprobada es:

`coping_potential_out = clamp(coping_potential_in * (1 - lambda * z), 0, 1)`

El identificador ejecutable de la fórmula es `F6-COPING-MOD-001`. La implementación usa aritmética `Decimal` construida desde cadenas y no acepta valores binarios de punto flotante.

## bindings

Los cuatro enlaces son explícitos y cerrados:

| Símbolo o resultado | Ruta autorizada |
|---|---|
| `coping_potential_in` | `host.baseline.coping_potential` |
| `lambda` | `influence.parameters.lambda` |
| `z` | `factor_state.level` |
| `coping_potential_out` | `output.coping_potential` |

Un enlace ausente, implícito, duplicado o divergente invalida la configuración. El resultado no puede reutilizarse como entrada de la misma evaluación.

## parameter

El parámetro versionado es `lambda = 0.3`. Es una cadena decimal canónica y una decisión de diseño de la instancia. No procede de una calibración empírica, una estimación poblacional ni una optimización contra datos humanos.

## projection

El resultado aritmético se proyecta mediante `clamp(value, 0, 1)`. Primero se calcula el factor multiplicativo `1 - lambda * z`, después el producto crudo y finalmente el valor acotado. La proyección protege el rango de salida, pero no sustituye la validación previa de la basal ni del factor.

## domain

`coping_potential_in`, `z` y la salida pertenecen al intervalo cerrado `[0,1]`. `lambda` vale exactamente `0.3`. Las representaciones numéricas siguen IFM6-DEC-v1: cadenas decimales finitas, sin notación exponencial, sin `NaN` ni infinitos y con cero negativo normalizado a `0`.

La tolerancia de comparación es `0.000000000001` (`1e-12`). Se usa para juzgar correspondencia numérica en la evaluación; no amplía los dominios ni convierte entradas inválidas en válidas.

## neutrality

Para un estado admisible con `z = 0`, el factor multiplicativo es `1`, por lo que `coping_potential_out = coping_potential_in`. La igualdad se combina con la protección exacta de las otras cinco coordenadas. Esta propiedad es computacional y no expresa una conclusión clínica sobre ausencia de fatiga.

## monotonicity

Con `coping_potential_in` fijo y no negativo, `lambda = 0.3` y `z` creciente en `[0,1]`, la salida es monótona no creciente. En esta región el factor multiplicativo varía de `1` a `0.7`, por lo que la fórmula nunca aumenta `coping_potential`.

La monotonicidad es una propiedad verificable del mecanismo elegido. No demuestra una ley causal universal ni autoriza extrapolar dirección o magnitud a otros factores, poblaciones o anfitriones.

## temporality

La fórmula consume un único estado validado respecto del `evaluation_time` inyectado. La edad es `evaluation_time - observed_at`. Un estado con edad de al menos 300 segundos es obsoleto; una marca más de cinco segundos futura es inválida. La versión no define persistencia, interpolación, decaimiento entre eventos ni memoria longitudinal.

## abstention

La modulación solo se evalúa si la basal anfitriona y el estado del factor son válidos. Cualquier falla del factor —ausencia, tipo o dominio inválido, confianza menor que `0.5`, tiempo inválido, obsolescencia, futuro excesivo, fuente inválida o versión incompatible— produce `abstained`, conserva exactamente la basal y no evalúa la fórmula.

Una falla anfitriona no es abstención: produce rechazo antes de la validación del factor y no crea traza de modulación.

## coping_partition

La clasificación de `coping_potential` usa una partición crisp doctoral:

| Categoría | Predicado exacto |
|---|---|
| `null` | `coping_potential <= 0.3` |
| `approachable` | `coping_potential > 0.3 and coping_potential <= 0.7` |
| `highly_approachable` | `coping_potential > 0.7` |

Los límites `0.3` y `0.7` pertenecen, respectivamente, a `null` y `approachable`. Esta partición no es una función difusa histórica recuperada y no existe equivalencia positiva aprobada entre sus etiquetas y los valores lingüísticos publicados.

## transfer_limits

- El modelo está ligado a `cognitive_fatigue`, al anfitrión `ACME-INFRA6-RR-1.0.0`, a la perspectiva estudiante–tutor y al blanco `coping_potential`.
- `lambda = 0.3`, las ventanas temporales y la partición crisp son decisiones doctorales locales.
- La instancia no calibra incertidumbre ni propaga una distribución probabilística.
- No se permite sustituir cadenas decimales por floats, modificar bindings ni ampliar la máscara sin nueva versión y nueva evaluación.
- La conformidad sintética verifica propiedades del mecanismo, no efectividad pedagógica, utilidad, validez psicológica, generalización ni transferencia.
