---
artifact_id: MFV-FAT-COP-1.0.0
artifact_version: 1.0.0
package_id: IFATIGUE-INFRA6-M6
package_version: 1.1.0
origin_class: generated_for_doctoral_instance
status: candidate_materialized_pending_T04_clean_reproduction
source_derivations:
  - DL-FST-002
  - DL-MAP-001
  - DL-MAP-002
  - DL-MAP-003
---

# Mapa factor–valoración: fatiga cognitiva y Coping Potential

## factor

El factor es `cognitive_fatigue`; su estado pertenece al estudiante y se representa por `factor_state.level`. En la instancia F6, el estado es una entrada sintética directa y no el resultado de un estimador humano.

## appraisal

El blanco pertenece al vector de valoración del tutor producido por el anfitrión `ACME-INFRA6-RR-1.0.0`. Este mapa autoriza una relación local con una sola dimensión. No declara que la fatiga determine el vector completo ni que una etiqueta emocional sea una medición de fatiga.

## perspective

| Elemento | Perspectiva fijada |
|---|---|
| Propietario del estado de fatiga | Estudiante |
| Propietario del appraisal | Tutor |
| Significado de `coping_potential` | Capacidad percibida por el tutor para responder pedagógicamente |

La relación es diádica: una condición atribuida al estudiante informa una coordenada de la valoración del tutor. No debe reinterpretarse como fatiga del tutor, como capacidad real del estudiante ni como comportamiento de afrontamiento del estudiante.

## authorized_variable

La única variable autorizada es `coping_potential`. La autorización significa que el modelo de influencia puede calcular un valor de salida para esa coordenada después de que la basal y el estado superen sus contratos.

El sentido operativo se limita a la transformación declarada en `MI-FAT-COP-1.0.0`. Este mapa no autoriza otras fórmulas, otros parámetros ni transferencia a un ACME distinto.

## protected_variables

Las variables protegidas son, en orden doctoral:

1. `expectedness`
2. `desirability`
3. `novelty`
4. `pleasure`
5. `goal_conduciveness`

Cada una debe conservar igualdad exacta entre basal y salida. La protección directa de estas coordenadas es compatible con que una clasificación posterior cambie de manera autorizada al consumir el nuevo `coping_potential`; ese efecto downstream no permite modificar las coordenadas protegidas.

## mask

La máscara cerrada es:

| Coordenada | Escribible |
|---|---:|
| `expectedness` | `false` |
| `desirability` | `false` |
| `novelty` | `false` |
| `pleasure` | `false` |
| `goal_conduciveness` | `false` |
| `coping_potential` | `true` |

En notación del orden doctoral, la máscara es `(0, 0, 0, 0, 0, 1)`.

## preconditions

- La basal anfitriona contiene exactamente las seis coordenadas, como cadenas decimales dentro de `[0,1]`.
- El estado del factor contiene todos los campos requeridos y satisface dominio, confianza, versión y vigencia.
- La perspectiva factor-estudiante/appraisal-tutor está preservada.
- La realización usa la fórmula, el parámetro y los bindings versionados de la instancia.
- La clasificación publicada, si se solicita, se realiza después de la modulación y solo con el subconjunto autorizado.

## postconditions

- Solo `output.coping_potential` puede diferir de `host.baseline.coping_potential`.
- Las cinco coordenadas protegidas son idénticas, byte por byte como cadenas canónicas, entre basal y salida.
- `coping_potential` permanece en `[0,1]`.
- Un estado neutro admisible conserva toda la basal.
- Una falla del factor produce abstención y basal sin cambios; una falla de la basal produce rechazo previo y no genera traza de modulación.
- Toda ejecución no rechazada registra máscara, basal y salida en una traza verificable.

## prohibitions

- Modificar directa o indirectamente una coordenada protegida dentro del modulador.
- Expandir la máscara por analogía, conveniencia de implementación o falta de datos.
- Invertir las perspectivas del estudiante y del tutor.
- Presentar `coping_potential` como afrontamiento observable del estudiante.
- Inferir que la relación es causal, universal o clínicamente válida.
- Aplicar el mapa si el estado falta, es inválido, obsoleto, demasiado futuro o no alcanza la confianza mínima.
- Sustituir la partición crisp doctoral por funciones difusas históricas no recuperadas.
- Transferir este mapa a otro factor, anfitrión, población o dominio sin nueva justificación, contrato y evaluación.

