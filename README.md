# IFATIGUE-INFRA6-M6 v1.1.0

Repositorio: `CastellanosBS/acme-firm-m6-fatigue`  
Autor de esta reconstrucción: Sergio Castellanos Bustamante  
Contacto: `scb.castellanos@gmail.com`  
Versión Git: `v1.1.0`  
Fecha de liberación: `2026-09-04`  
DOI reservado de esta versión: `10.5281/zenodo.22313152`  
Estado al sellar el candidato: borrador de Zenodo todavía no publicado

`IFATIGUE-INFRA6-M6` es una reconstrucción doctoral nueva y reproducible de
una instancia acotada de ACME-FIRM. Integra un estado sintético externo de
fatiga cognitiva en el vector de valoración `ACME-INFRA6-RR-1.0.0` y autoriza
modificar únicamente `coping_potential`.

Esta versión no recupera ni continúa materialmente el código o los bytes del
paquete histórico `v1.0.0`, que no estuvo disponible. Los siete artefactos
conservan los identificadores internos `1.0.0` declarados por la tesis. GEA y
cualquier material derivado directamente de GEA están excluidos.

## Tres capas que no deben confundirse

| Capa | Rutas principales | Naturaleza |
|---|---|---|
| Especificación publicada | `spec/published/` | Representaciones estructuradas y acotadas de elementos localizados en publicaciones citadas; no son copias de los artículos ni evidencia empírica nueva. |
| Reconstrucción reproducible | `src/`, `scripts/`, `commands/`, `schemas/`, `config/`, `tests/` | Implementación nueva construida para materializar y comprobar el contrato de la instancia; no es código histórico recuperado. |
| Instancia doctoral nueva | `spec/thesis/`, `spec/decisions/`, `artifacts/`, escenarios, oráculos y evidencia derivada | Especificación y evidencia sintética creadas para el caso F6 de la tesis. |

`PROVENANCE.json`, `PACKAGE_METADATA.json`, `sources/DECISIONS.md` y los
registros de construcción conservan deliberadamente el vocabulario
`candidate` y `T04 pending`: son instantáneas congeladas del cierre T03. El
estado posterior de verificación y publicación se documenta en
`docs/T04_CLEAN_REPRODUCTION.md`, `RELEASE_METADATA.json` y
`RELEASE_NOTES.md`; esos archivos no reescriben retrospectivamente el
expediente T03.

## Estado verificable

- versión del paquete: `1.1.0`;
- alcance: A3--A4, conformidad contractual sintética;
- corrida de referencia: 16/16 escenarios conformes, 18/18 pruebas, 15 trazas
  y un rechazo previo a modulación;
- reproducción limpia T04: aprobada, sin diferencias de membresía, tamaño o
  contenido en 159/159 archivos;
- dependencias: biblioteca estándar de CPython 3.12;
- datos personales o de participantes en el cálculo: ninguno;
- datos distribuidos: exclusivamente sintéticos y originales;
- licencia: Apache-2.0 para software y CC-BY-4.0 para documentación y material
  sintético, según `LICENSE_SCOPE.md`;
- revisión experta externa F5 y validación empírica: no realizadas y no
  afirmadas.

La reproducción T04 se identifica como `RUN-T04-CLEAN-001`. Confirmó 16/16
escenarios, 18/18 pruebas, 15 trazas, un rechazo y cero diferencias de bytes.
La variación de permisos POSIX `0644` a `0600` en 41 archivos regenerados fue
aceptada como no sustantiva mediante `T04-FS-001`; el ZIP de distribución
normaliza todos los archivos regulares a `0644`.

## Contenido

| Ruta | Contenido |
|---|---|
| `artifacts/` | Siete documentos del núcleo M1--M5 y sus relaciones con M6 |
| `spec/` y `config/` | Capas publicadas, decisiones, especificación doctoral, enlaces y configuración resuelta |
| `schemas/` | Contratos JSON y CSV cerrados |
| `scenarios/` y `oracles/` | Dieciséis entradas sintéticas y dieciséis expectativas independientes congeladas |
| `src/` | Implementación Python de la instancia |
| `tests/` | Dieciocho pruebas catalogadas y una regresión simbólica acotada |
| `results/`, `traces/`, `logs/`, `environment/` | Evidencia derivada de la corrida de referencia |
| `sources/` y `PROVENANCE.json` | Registro de fuentes, libro de derivación y decisiones T03 |
| `docs/` | Alcance, ética, dependencias, adaptación, reproducibilidad y reporte T04 |
| `manifests/` | Receta, topología, snapshot de fuentes y registro de construcción T03 |

`ARTIFACT_INDEX.json` registra los siete artefactos físicos. Las autoridades
de procedencia T03 son `sources/SOURCES.json`,
`sources/DERIVATION_LEDGER.csv` y `PROVENANCE.json`. La autoridad de la capa
de publicación T05 es `RELEASE_METADATA.json`.

## Regla de integración

La entrada `factor_state.level` es una cadena decimal `z` en `[0,1]`. El
paquete no estima fatiga. La transformación autorizada es:

\[
coping\_potential_{out}=\operatorname{clamp}\bigl(coping\_potential_{in}(1-0.3z),0,1\bigr).
\]

`expectedness`, `desirability`, `novelty`, `pleasure` y
`goal_conduciveness` están protegidas y deben permanecer idénticas. Un
anfitrión inválido se rechaza antes de modular; un estado de factor ausente o
inválido provoca abstención según el contrato.

## Verificación reproducible

Use CPython 3.12 desde la raíz de una extracción limpia del ZIP de la release:

```bash
python3 -I -B -X utf8 scripts/verify_manifest.py --root . --manifest MANIFIESTO_SHA256.txt
python3 -I -B -X utf8 scripts/verify_manifest.py --root . --manifest manifests/SOURCE_SHA256.txt
python3 -I -B -X utf8 scripts/regenerate_evidence.py --root .
python3 -I -B -X utf8 scripts/compare_outputs.py --root .
python3 -I -B -X utf8 scripts/verify_manifest.py --root . --manifest MANIFIESTO_SHA256.txt
```

La primera orden valida todos los bytes distribuidos. La segunda fija los 90
miembros de fuente ejecutable. La regeneración es transaccional y el comparador
comprueba escenarios, oráculos, resultados, trazas, rechazo y pruebas. No
edite manualmente las salidas derivadas.

`scripts/validate_derivation_ledger.py` y
`commands/validate_qa_verdict.py` son validadores de atestación ligados al
inventario y a los hashes del candidato T03 congelado. Es correcto que rechacen
la raíz pública T05, porque esta reemplaza archivos administrativos y añade la
capa de publicación. Sus ejecuciones satisfactorias sobre el candidato se
conservan en el expediente T04. Para la release T05, los controles normativos
son el manifiesto integral de la distribución, el snapshot de 90 fuentes, la
regeneración, la comparación funcional y la auditoría externa del diff cerrado.

El manifiesto total debe verificarse sobre una extracción del activo de la
release, no sobre un checkout con metadatos `.git`, porque esos metadatos no
forman parte del ZIP. Consulte `docs/REPRODUCIBILITY.md` y
`docs/T04_CLEAN_REPRODUCTION.md` para el contrato completo y la evidencia de
la ejecución limpia.

## Licencias, cita y créditos

El software se ofrece bajo Apache License 2.0. La documentación,
especificaciones, artefactos y material sintético se ofrecen bajo Creative
Commons Attribution 4.0 International. El mapa vinculante por ruta y las
exclusiones se encuentran en `LICENSE_SCOPE.md`; los textos íntegros están en
`LICENSES/`.

La autoría de esta reconstrucción y de la versión 1.1.0 corresponde a Sergio
Castellanos Bustamante. Las personas coautoras de las publicaciones
fundacionales se reconocen en `NOTICE` y `sources/SOURCES.json`; ese crédito
no las presenta como autoras ni mantenedoras de este paquete.

Use `CITATION.cff` para citar la versión. El DOI reservado de Zenodo es
`10.5281/zenodo.22313152`; identifica la versión fechada `2026-09-04` y se
vincula al ZIP definitivo mediante el expediente externo de liberación. La
reserva del DOI no acredita por sí sola que el depósito ya esté publicado,
accesible o resoluble.

## Límites de interpretación

La evidencia demuestra conformidad con escenarios y oráculos sintéticos
previamente definidos para esta versión y topología. No demuestra validez
psicológica o clínica de `z`, causalidad fatiga--afrontamiento, efectividad,
superioridad, utilidad operacional, adopción, portabilidad a otros ACMEs,
evaluación de campo o generalización.

La adaptación exige un nuevo episodio de especificación y evaluación. No se
deben copiar automáticamente la fórmula, `lambda = 0.3`, el mapa de variables
o los umbrales. Consulte `docs/ADAPTATION_GUIDE.md` y
`docs/DATA_ETHICS_AND_CONSTRUCT_VALIDITY.md`.
