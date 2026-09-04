# Reproducibilidad

## Estados que no deben confundirse

| Estado | Significado | Situación actual |
|---|---|---|
| Fuente congelada | Conjunto de entradas, oráculos, generadores y validadores identificado por `SOURCE_SHA256.txt` | Registrado para la corrida T03 vigente |
| Corrida de referencia T03 | Generación transaccional dentro del candidato y comparación independiente | Ejecutada; sus identificadores canónicos están en `PACKAGE_METADATA.json` |
| Candidato finalizado T03.3-10 | `BUILD_RECORD`, manifiesto final y ZIP determinista | Materializado y verificado; la aprobación canónica se registra fuera de estos bytes |
| Reproducción limpia T04 | Extracción fresca, regeneración y comparación byte a byte fuera del árbol T03 | No ejecutada |

El hash, número de registros e identificador de corrida vigentes deben obtenerse de:

- `PACKAGE_METADATA.json#/source_snapshot/sha256`;
- `PACKAGE_METADATA.json#/source_snapshot/records`;
- `PACKAGE_METADATA.json#/source_snapshot/run_id`;
- `PACKAGE_METADATA.json#/source_snapshot/manifest_path`.

No se fija aquí un digest literal para impedir que una nueva congelación legítima quede documentada con el valor de una corrida anterior. El conjunto de evidencia de referencia se describe en `PACKAGE_METADATA.json#/reference_evidence`.

`PACKAGE_METADATA.json` es una instantánea T03.3-9 inmutable y previa a los dos
nodos finales. Por diseño conserva 155 archivos en su inventario y mantiene
`MANIFIESTO_SHA256.txt` y `manifests/BUILD_RECORD.json` en `pending_paths`, aun
cuando ambos estén presentes en un candidato finalizado. Esta forma evita
autorreferencias y ciclos de hashes. El estado posfinal se determina verificando
atómicamente el par, la pertenencia física de los 159 archivos y el manifiesto
de 158 registros; la decisión humana sobre ese hash se documenta en un registro
externo de cierre.

## Entorno de referencia

La corrida controlada registró CPython 3.12.13 sobre Linux 6.18.35 `x86_64`, UTF-8 y locale `C.UTF-8`. Utilizó solo la biblioteca estándar, sin red, azar ni reloj del sistema dentro de la lógica probada. El tiempo lógico fue inyectado como `2026-09-04T12:00:00Z`.

No se registraron métricas de duración. La cifra histórica de 44.766 microsegundos no forma parte de los resultados porque carecía de un protocolo reproducible de benchmark.

## Perfiles deterministas

1. Los textos usan UTF-8 sin BOM, NFC, LF exclusivo y exactamente un LF final.
2. `IFM6-JSON-v1` serializa una línea con claves ordenadas, separadores compactos, `ensure_ascii=false` y `allow_nan=false`.
3. Los reales son cadenas `IFM6-DEC-v1`, construidas con `Decimal` desde texto, precisión 50 y `ROUND_HALF_EVEN`; no pasan por `float`.
4. La tolerancia canónica es `0.000000000001`.
5. Los identificadores de traza son SHA-256 del `trace_core` JSON canónico y excluyen tiempo de ejecución, rutas absolutas y metadatos volátiles.
6. Escenarios y oráculos se fijan antes de implementar y la lógica productiva no importa oráculos.

## Secuencia de referencia

Desde la raíz de una copia controlada y con CPython 3.12:

```bash
python3 -I -B -X utf8 scripts/verify_manifest.py --root . --manifest manifests/SOURCE_SHA256.txt
python3 -I -B -X utf8 scripts/regenerate_evidence.py --root .
python3 -I -B -X utf8 scripts/compare_outputs.py --root .
```

La primera orden debe devolver código 0 antes de ejecutar cualquier generador. `regenerate_evidence.py` vuelve a verificar la fuente, produce escenarios y pruebas en un área temporal y solo promueve el conjunto completo si todo pasa. `compare_outputs.py` verifica después escenarios, oráculos, disposiciones, trazas, rechazo y pruebas sin editar la evidencia.

No ejecute directamente `run_scenarios.py` o `run_tests.py` contra la raíz para reemplazar la corrida canónica. No modifique a mano archivos bajo `results/reference_run/`, `traces/reference_run/`, `logs/reference_run/` o `environment/`.

## Conjunto esperado

La evidencia de referencia contiene 41 archivos:

| Grupo | Conteo | Desglose |
|---|---:|---|
| `results/reference_run/` | 20 | 16 resultados y 4 archivos de resumen, matriz y metadatos |
| `traces/reference_run/` | 16 | 15 trazas y 1 rechazo previo a modulación |
| `logs/reference_run/` | 3 | comandos, escenarios y pruebas |
| `environment/` | 2 | entorno estructurado y resumen de runtime |

El conteo y el SHA-256 agregado vigentes se leen de `PACKAGE_METADATA.json#/reference_evidence/expected_count` y `PACKAGE_METADATA.json#/reference_evidence/aggregate_sha256`. El resultado funcional esperado es 16/16 escenarios, 18/18 pruebas, 15 trazas válidas y un rechazo S15 sin traza de modulación.

## Procedimiento T04

T04 debe:

1. comprobar la integridad del ZIP y del manifiesto final producido en T03.3-10;
2. extraerlo en un directorio fresco, fuera del candidato T03 y de sus salidas de referencia;
3. registrar el entorno sin exigir que el texto de plataforma sea idéntico entre sistemas;
4. verificar el snapshot fuente antes de generar;
5. regenerar mediante el orquestador transaccional;
6. comparar byte a byte cada salida declarada reproducible y sus manifiestos;
7. detenerse ante cualquier diferencia y conservar ambos árboles para diagnóstico;
8. emitir un registro separado antes de marcar cualquier objeto `verified_t04`.

Las observaciones del entorno pueden variar legítimamente; resultados, contratos y demás salidas declaradas deben satisfacer la política de comparación aprobada. Hasta que exista ese registro, solo se afirma la corrida interna T03, no reproducción limpia.

## Política de fallos

Cualquier miembro ausente o inesperado, hash distinto, esquema inválido, cobertura incompleta, prueba fallida, discrepancia con un oráculo, traza inválida, rechazo incorrecto o comando no cero bloquea los nodos posteriores. Una modificación de fuente exige nueva decisión, congelación y corrida; nunca se ajusta un oráculo a posteriori para favorecer el resultado.
