# T04 — Reproducción limpia y verificación de M6

> **Nota de distribución T05.** Este documento reproduce el informe de cierre
> de T04 con esta aclaración editorial. Las rutas `audit/**`,
> `regenerated_evidence/**`, `baseline/**` y `reproduction/**` mencionadas más
> adelante son relativas al expediente externo T04 y no al repositorio público
> T05. El repositorio incorpora el dictamen, pero excluye las copias de trabajo
> y los registros redundantes del experimento.

## Estado

**CERRADO — REPRODUCCIÓN LIMPIA VERIFICADA Y APROBADA POR EL AUTOR.**

- Identificador externo de ejecución: `RUN-T04-CLEAN-001`.
- Inicio: `2026-09-04T19:47:40.756530Z`.
- Finalización: `2026-09-04T19:47:43.137293Z`.
- Resultado técnico: `pass`.
- Diferencias de membresía, tamaño o contenido: `0`.
- Variaciones de metadatos POSIX: `41` cambios `0644` a `0600`, aceptados
  como no sustantivos mediante `T04-FS-001`.

Este expediente documenta la reproducción limpia de la instancia
`IFATIGUE-INFRA6-M6`, versión `1.1.0`, etapa `candidate`. La tarea operativa se
identifica como T04 en las instrucciones maestras; corresponde a T3 en la
numeración legada del plan de cierre. La designación T04 es la autoridad usada
en rutas, registros y aprobación.

## Objeto reproducido

El único paquete sometido a ejecución fue el ZIP aprobado en
`T03.3-10-CAN-001`. El sidecar y el árbol T03 aprobado se utilizaron
exclusivamente como controles de identidad e inmutabilidad; no aportaron datos
ni parámetros a la regeneración:

| Propiedad | Valor |
|---|---|
| Archivo | `ACME_FIRM_M6_FATIGA_v1.1.0-candidate.zip` |
| Tamaño | 4 202 781 bytes |
| SHA-256 aprobado | `3d6329284793aa92f14c85c3e646c53004578d30134d16f9b308c9e67c42c69f` |
| SHA-256 observado antes y después | `3d6329284793aa92f14c85c3e646c53004578d30134d16f9b308c9e67c42c69f` |
| Sidecar | 107 bytes; SHA-256 `426c5f8eb1ebacda41486731710145a4950c045388cae10f4d74123fc474dbd7` |
| Entradas | 159 archivos regulares bajo una raíz única |
| Integridad ZIP | CRC, orden, rutas y perfil: `pass` |

La inspección previa rechazaba rutas absolutas, componentes `..`, nombres no
normalizados, duplicados, enlaces simbólicos, directorios y metadatos ZIP no
admitidos. La entrada satisfizo todos los controles.

## Protocolo ejecutado

Se generaron dos extracciones nuevas fuera del árbol T03:

1. `baseline/`: testigo intacto de los bytes extraídos;
2. `reproduction/`: única copia sobre la que se ejecutó la regeneración.

Antes de generar se comprobó que ambas extracciones coincidieran con los 159
archivos del árbol T03 aprobado. La copia de ejecución pasó el manifiesto final
y el snapshot fuente. Después se ejecutó la secuencia normativa sin modificar
código, configuración, parámetros, escenarios, oráculos, tolerancias o tiempo
lógico:

```text
python3 -I -B -X utf8 scripts/verify_manifest.py --root . --manifest manifests/SOURCE_SHA256.txt
python3 -I -B -X utf8 scripts/regenerate_evidence.py --root .
python3 -I -B -X utf8 scripts/compare_outputs.py --root .
```

La regeneración se efectuó mediante el orquestador transaccional. No se
ejecutaron directamente `run_scenarios.py` o `run_tests.py` contra el árbol, no
se reconstruyó el ZIP y no se invocó `build_release.py`.

La invocación externa completa se conserva en `audit/T04_INVOCATION.json`. El
orquestador T04 ejecutado tiene SHA-256
`5752f6b377edccbb318f9d8e6aed027e7cb9eb8439a9f7df19e3f4a8fa896c00`.

## Entorno observado

| Propiedad | Valor |
|---|---|
| Implementación | CPython |
| Versión | 3.12.13 |
| Sistema | Linux 6.18.35 |
| Arquitectura | `x86_64` |
| Locale efectivo | `LC_CTYPE=C.UTF-8`; las demás categorías `C` |
| Codificación preferida y del sistema de archivos | UTF-8 |
| Dependencias | Biblioteca estándar; no se instalaron paquetes |
| SHA-256 de `requirements.txt` | `9cbed7c481d651021ef4bad4146f172ed2419132f0d7648b4ddcd094b7fb32c1` |
| Red requerida por los comandos | Ninguna |
| Aleatoriedad y semilla | No hay aleatoriedad; semilla no aplicable |
| Tiempo lógico | Inyectado desde los escenarios: `2026-09-04T12:00:00Z` |
| Tolerancia canónica | `0.000000000001` |
| Zona horaria del proceso anfitrión | `Asia/Tokyo`; sin intervención en los resultados |

Las propiedades del entorno registradas por la receta T03 y relevantes para la
regeneración coinciden. Por ello, además de la comparación estructural permitida
para las dos observaciones de entorno, se exigió y obtuvo identidad byte a byte
también en esos archivos.

## Comandos y resultados

Los tiempos son observaciones monotónicas externas de T04; no se incorporan a
la evidencia determinista del candidato.

| Control | Código | Duración aproximada | `stderr` |
|---|---:|---:|---:|
| Manifiesto final del testigo | 0 | 56.980 ms | 0 bytes |
| Manifiesto final de la copia de ejecución, previo | 0 | 61.091 ms | 0 bytes |
| Snapshot fuente previo | 0 | 48.082 ms | 0 bytes |
| Regeneración transaccional | 0 | 342.993 ms | 0 bytes |
| Comparación funcional independiente del generador | 0 | 101.666 ms | 0 bytes |
| Validación del libro de derivación | 0 | 1 464.862 ms | 0 bytes |
| Validación de QA | 0 | 61.689 ms | 0 bytes |
| Snapshot fuente posterior | 0 | 45.720 ms | 0 bytes |
| Manifiesto final posterior | 0 | 56.785 ms | 0 bytes |

Los nueve comandos terminaron con código 0. La suma de sus duraciones externas
fue 2.239867618 segundos. El registro JSONL conserva comando, inicio, fin,
duración, código, tamaño y SHA-256 de cada salida estándar y de error; cada
`stdout` y `stderr` se conserva íntegro en un archivo separado.

## Resultados funcionales

| Control | Resultado |
|---|---:|
| Escenarios regenerados y conformes | 16/16 |
| Coincidencias con oráculos | 16/16 |
| Pruebas unitarias | 18/18 |
| Trazas con identificador válido | 15/15 |
| Rechazos previos a modulación | 1/1, escenario S15 |
| Disposiciones | 7 abstenciones, 3 aplicaciones sin cambio, 5 modulaciones y 1 rechazo |
| Archivos regenerados transaccionalmente | 41/41 |
| Hallazgos del comparador funcional | 0 |
| Hallazgos del libro de derivación | 0 errores, 0 advertencias, 0 informativos |
| QA interna revalidada | `pass`; 6 perspectivas, 8 hallazgos tratados y 2 validadores |

El identificador `RUN-T03-REFERENCE-001` permanece dentro de los 41 archivos
regenerados porque forma parte de la receta congelada que debía reproducirse.
`RUN-T04-CLEAN-001` identifica externamente este nuevo acto de reproducción.
Cambiar el identificador interno habría alterado artificialmente los bytes que
se buscaba verificar.

## Comparación de identidad

La comparación externa cubrió membresía, tamaños y SHA-256. No dependió de
`compare_outputs.py`, cuyo alcance principal es la conformidad funcional.

| Conjunto | Identidad obtenida | Agregado SHA-256 |
|---|---:|---|
| Salidas deterministas | 39/39 | `77839e3f9654a8ddebca593f1e49260111bd80f67d8b5daafa6750ccfb71156d` |
| Observaciones de entorno | 2/2 | incluidas en el agregado de 41 |
| Evidencia regenerada total | 41/41 | `64cf63cc2e5905a75e79eff35d537e6af192b43fe64a89fcf51b82920c25a9a8` |
| Archivos no regenerados | 118/118 | sin diferencias |
| Árbol completo | 159/159 | `e33dc85563171f667346e87f5e2e9ab44b816d86400003f3660378625dbfa318` |

El manifiesto fuente verificó 90/90 registros antes y después, con SHA-256
`a5ea9ac79dc4cd4de5556f22cfcae3542e6705034f2012b412ae1a803462b8b4`.
El manifiesto final verificó 158/158 registros antes y después, con SHA-256
`a05bc53c3bcbcbab1a26e5002a48a3eae390baa222f0ad5e4ca469d7d04d1d11`.

La matriz de comparación contiene 159 filas y cero estados distintos de
`identical`; ese estado se refiere a membresía, tamaño y SHA-256. El árbol T03 y
el ZIP aprobado conservaron su misma membresía y sus mismos bytes durante toda
la ejecución.

### Variación no sustantiva de permisos

Los 41 archivos regenerados quedaron con modo POSIX `0600`, mientras sus pares
del testigo conservan `0644`. La causa es la creación transaccional mediante
archivos temporales seguros (`mkstemp`) bajo el `umask` efectivo. La variación
no altera nombres, tamaños, contenidos, hashes, resultados, trazas ni capacidad
de ejecución, y no afecta plataformas que no conservan esos bits POSIX. El
paquete de entrega normaliza todos sus archivos regulares a `0644`.

El autor aprobó documentar esta observación como no sustantiva mediante
`T04-FS-001`; no se modificó el generador del candidato porque hacerlo habría
invalidado la identidad aprobada en T03.

### Observaciones de endurecimiento del orquestador

La auditoría independiente identificó cuatro mejoras futuras que no invalidan
esta ejecución:

1. el control ZIP debe exigir expresamente `S_ISREG`, aunque se verificó de
   forma independiente que las 159 entradas son archivos regulares;
2. los conteos declarados de 41 evidencias y su partición 39/2 deben derivarse
   íntegramente del inventario, aunque el recálculo independiente confirmó
   exactamente esos valores;
3. el orquestador debe volver a verificar el sidecar al finalizar, aunque su
   comprobación posterior volvió a confirmar el ZIP aprobado;
4. `T04_INVOCATION.json` es una atestación externa incorporada después de la
   corrida y se conserva explícitamente con esa clasificación.

Estas observaciones quedan registradas en `audit/T04_INDEPENDENT_QA.json`.

## Entregables del expediente

| Ruta | Función |
|---|---|
| `audit/T04_SUMMARY.json` | dictamen técnico canónico de la ejecución |
| `audit/T04_CLOSURE_RECORD.json` | decisiones del autor y cierre formal de T04 |
| `audit/T04_INDEPENDENT_QA.json` | auditoría independiente, observaciones y mitigaciones |
| `audit/T04_COMMAND_LOG.jsonl` | registro completo de los nueve comandos |
| `audit/T04_INVOCATION.json` | invocación externa y hash del orquestador T04 |
| `audit/commands/` | `stdout` y `stderr` íntegros por comando |
| `audit/T04_ENVIRONMENT.json` | entorno, dependencias, semilla y tolerancia |
| `audit/T04_ZIP_AUDIT.json` | identidad y seguridad de la entrada |
| `audit/T04_FILE_COMPARISON.csv` | comparación de los 159 archivos |
| `audit/T04_EVIDENCE_COMPARISON.json` | comparación específica de los 41 derivados |
| `audit/T04_BASELINE_TREE_SHA256.txt` | inventario testigo de 159 hashes |
| `audit/T04_REPRODUCED_TREE_SHA256.txt` | inventario posterior de 159 hashes |
| `regenerated_evidence/results/` | 20 resultados, incluida la matriz regenerada |
| `regenerated_evidence/traces/` | 15 trazas y el rechazo S15 regenerados |
| `regenerated_evidence/logs/` | tres logs internos deterministas |
| `regenerated_evidence/environment/` | dos observaciones internas del entorno |

Las dos extracciones completas permanecen preservadas como respaldo técnico de
la ejecución cerrada. El paquete de entrega reúne el expediente, los logs y los
41 archivos regenerados sin alterar el candidato T03.

## Dictamen y alcance

La ejecución satisface el criterio técnico de T04: una extracción nueva del
candidato aprobado reprodujo los resultados declarados sin diferencias de
membresía, tamaño o contenido. El dictamen acredita reproducibilidad de esta
instancia y conformidad de ingeniería dentro del alcance sintético A3--A4.

En conjunto, T03 y T04 permiten conservar M0--M6 para este caso, versión y
topología. No demuestran validez psicológica, generalización ni reutilización
externa del modelo.

La evidencia conserva como asuntos posteriores la validez psicológica del
constructo de fatiga, la causalidad fatiga--afrontamiento, la calibración con
participantes, la generalización, la portabilidad a entornos distintos, el panel
externo F5, el depósito y la liberación pública.

## Aprobaciones y cierre

El dictamen técnico inmutable es `audit/T04_SUMMARY.json`, de 1 456 bytes y
SHA-256:

`f6aef6844fe94f8f81c12e63d7d8b502acd15ee965e77305f7a2980aefaa2c90`

El autor emitió la decisión explícita:

**`APROBADO T04-FS-001 — DOCUMENTAR 0644→0600 COMO VARIACIÓN NO SUSTANTIVA`**

Asimismo, instruyó continuar hasta terminar T04 y adoptar las recomendaciones.
Con esa autorización se registra `T04-RL-001`, ligado al ZIP canónico y al
dictamen técnico anterior, y se declara **T04 cerrada**. Este cierre no inicia ni
autoriza por sí mismo T05.
