---
artifact_id: "MOD-FAT-COP-1.0.0|IF-GA-EF-1.0.0"
artifact_version: 1.0.0
package_id: IFATIGUE-INFRA6-M6
package_version: 1.1.0
origin_class: generated_for_doctoral_instance
status: candidate_materialized_pending_T04_clean_reproduction
source_derivations:
  - DL-BIND-RESOLVED-001
  - DL-BIND-RESOLVED-002
  - DL-BIND-RESOLVED-003
  - DL-BIND-RESOLVED-004
  - DL-RUL-SELECT-001
  - DL-DIAG-AGGREGATION-001
  - DL-REP-007
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
---

# Realización del modulador e interfaz GA–EF

Este artefacto reúne dos responsabilidades documentales sin confundirlas: `MOD-FAT-COP-1.0.0` ejecuta la transformación autorizada e `IF-GA-EF-1.0.0` controla el intercambio entre `general_appraisal` y `emotional_filter`.

## modules

La realización de referencia reside en `src/ifatigue_infra6/`:

| Módulo | Responsabilidad |
|---|---|
| `model.py` | Identificadores, orden de coordenadas, bindings, prioridad diagnóstica y registros inmutables. |
| `canonical_json.py` | Perfil IFM6-JSON-v1, cadenas decimales, serialización canónica y SHA-256. |
| `contract.py` | Validación fail-closed de basal, estado y configuración resuelta. |
| `host.py` | Copia ordenada del vector, partición crisp y comparación de coordenadas protegidas. |
| `modulator.py` | Fórmula decimal, clamp y comprobación de localidad. |
| `rules.py` | Adaptadores source-specific y evaluación del subconjunto publicado. |
| `trace.py` | Ensamblaje de `trace_core`, versiones, política y `trace_id`. |
| `runner.py` | Orquestación pura en memoria y separación resultado/traza/rechazo. |
| `__init__.py` | Superficie pública mínima de la implementación. |

La persistencia y la comparación se delegan a scripts externos al núcleo. La lógica determinista no requiere red, aleatoriedad ni reloj del sistema.

## api

La operación principal es `evaluate_scenario(scenario, config) -> ExecutionOutcome`. Consume una fixture ya validada por esquema y la configuración resuelta, y devuelve en memoria:

- `result`: registro de disposición y salida;
- `trace`: traza de modulación o abstención para S00–S14;
- `rejection`: registro previo a modulación para S15.

Las operaciones auxiliares expuestas incluyen validación de basal y factor, modulación de `coping_potential`, clasificación crisp y validación del `trace_id`. No existe una API que autorice escribir las coordenadas protegidas.

## flow

El orden obligatorio es:

1. verificar el manifiesto fuente congelado;
2. validar la configuración resuelta;
3. validar la basal anfitriona;
4. si la basal es válida, validar el estado del factor;
5. si ambos contratos son válidos, evaluar la fórmula y preservar la máscara;
6. cuando el escenario lo declara, clasificar antes y después con el subconjunto publicado;
7. crear el resultado y, salvo rechazo anfitrión, la traza;
8. validar esquemas, oráculos, conteos y correspondencias.

Una falla en cualquier predecesor detiene los nodos que dependen de él.

## validation

La basal se valida primero y debe contener exactamente seis cadenas decimales en `[0,1]`. Si falla, no se inspecciona el factor. El estado se valida por contenedor y después por los campos `level`, `confidence`, `observed_at`, `source_id` y `state_schema_version`.

Las reglas de no cascada suprimen diagnósticos dependientes de un campo ausente o de tipo/formato inválido. La configuración se rehúsa si divergen la máscara, los cuatro bindings, `lambda`, el orden anfitrión, la prioridad diagnóstica, la temporalidad, la neutralidad o el perfil decimal.

## diagnostics

Los códigos diagnósticos forman un conjunto completo de clases detectadas independientemente, deduplicado por código y ordenado por la prioridad fija 1–22. Nunca se ordenan alfabéticamente ni por orden accidental de descubrimiento.

La basal produce únicamente diagnósticos `HOST_*`. Si existe alguno, la disposición es `rejected` y se aplica el cortocircuito anfitrión. Para el factor, un contenedor ausente o no objeto impide descender; en campos individuales, ausencia, tipo, dominio y dependencias temporales no se acumulan en cascada. La ambigüedad del subconjunto publicado solo se evalúa cuando ambos contratos son válidos.

## modulation

La realización resuelve exactamente:

- `coping_potential` desde `host.baseline.coping_potential`;
- `lambda` desde `influence.parameters.lambda`;
- `z` desde `factor_state.level`;
- el resultado hacia `output.coping_potential`.

Evalúa `clamp(coping_in * (1 - 0.3 * z), 0, 1)` con precisión decimal 50, normaliza la cadena resultante y compara las cinco coordenadas protegidas. Si alguna cambia, la realización falla en lugar de emitir una salida silenciosamente contaminada.

## classification_before_after

Solo S14 activa la clasificación acotada antes/después. El payload simbólico anfitrión coincide con la fila consistente de ira publicada. Con `coping_potential = 0.35`, la clasificación basal es `unclassified_by_published_subset`; con `z = 1`, la salida es `0.245`, entra en la banda `null` y la clasificación posterior es `anger` mediante `RULE-ANGER-2018B-CONSISTENT`.

Este recorrido verifica continuidad técnica entre modulación y una regla seleccionada. No demuestra que la fatiga cause ira ni completa la taxonomía emocional del anfitrión.

## traces

Existe una receta uno-a-uno para S00–S14. Cada traza cerrada contiene envoltura, diagnósticos y exactamente nueve componentes de `trace_core`: `event`, `state`, `baseline`, `output`, `policy`, `mask`, `formula`, `classification` y `versions`.

`trace_id` es el SHA-256 hexadecimal en minúsculas de los bytes UTF-8 del `trace_core` serializado por IFM6-JSON-v1, sin LF terminal. Se excluyen el propio identificador y metadatos volátiles. Antes del ensamblaje, los cinco campos consumidos del resultado se proyectan desde el resultado validado; los oráculos se usan para comparar igualdad, nunca como fuente de esos valores.

La corrida de referencia observada materializó 15 trazas, una por escenario S00–S14. Sus hashes de archivo se verifican desde el inventario de descendientes y el manifiesto de la etapa correspondiente; no se duplican como constantes en este documento para evitar divergencia de autoridades.

## rejection

S15 contiene una basal fuera de dominio. El anfitrión rechaza en la fase `host_baseline`, emite `HOST_BASELINE_OUT_OF_RANGE`, no valida el factor, no intenta modulación ni clasificación, no crea `S15.trace.json` y produce `traces/reference_run/rejections/S15.rejection.json`.

El rechazo no se cuenta como traza de modulación. Cualquier aparición de `traces/reference_run/S15.trace.json` viola el contrato.

## commands

Desde la raíz del paquete, la secuencia reproducible es:

```sh
python3 -I -B -X utf8 scripts/verify_manifest.py --root . --manifest manifests/SOURCE_SHA256.txt
python3 -I -B -X utf8 scripts/regenerate_evidence.py --root .
python3 -I -B -X utf8 scripts/compare_outputs.py --root .
```

La regeneración ejecuta de forma transaccional los 16 escenarios y los 18 métodos de prueba. Los runners individuales aceptan `--output-root` para escribir en staging; la edición manual de descendientes está prohibida.

## execution_status

La corrida `RUN-T03-REFERENCE-001` fue ejecutada sobre un manifiesto fuente verificado y registró 16/16 comparaciones con oráculo, 18/18 pruebas aprobadas, 15 trazas y un rechazo previo a modulación. La distribución observada fue cinco `modulated`, tres `applied_no_change`, siete `abstained` y un `rejected`.

Estos resultados son evidencia de conformidad sintética interna para la versión y topología declaradas. No sustituyen la reproducción limpia T04, una evaluación empírica, una revisión externa ni evidencia de utilidad o generalización.

