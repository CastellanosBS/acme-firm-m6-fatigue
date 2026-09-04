# Vista humana de decisiones

## Autoridad y uso

Este documento resume las decisiones registradas en `PROVENANCE.json` para facilitar revisión humana. No reemplaza los objetos completos, sus localizadores ni sus bases de aprobación. Ante cualquier diferencia, `PROVENANCE.json` y `sources/DERIVATION_LEDGER.csv` son las autoridades legibles por máquina.

Los estados `imported_approved_decision`, `approved_by_author` y `approved_under_standing_authorization` conservan la distinción del registro canónico. `superseded_by_T03-RP-012` identifica una decisión histórica que ya no es normativa.

## Decisiones importadas de T01

| ID | Estado | Síntesis operativa |
|---|---|---|
| `T01-AF-002` | `imported_approved_decision` | F5, si se ejecuta, solo puede aportar A1 y A3 en las dimensiones examinadas; no A2 ni A5. |
| `T01-AF-008` | `imported_approved_decision` | Normalizar `Expectation` como `Expectedness` y `Goal Orientation` como `Goal Conduciveness`, sin añadir variables ni alterar funciones. |
| `T01-AF-011` | `imported_approved_decision` | F6 representa la interfaz versionada de salida de General Appraisal; no reproduce su cálculo psicológico ni su código completo. |
| `T01-AF-012` | `imported_approved_decision` | GEA es referencia histórica; mientras el archivo exacto esté ausente no se afirma auditoría directa, 37 columnas ni dimensiones completas. |
| `T01-AF-015` | `imported_approved_decision` | Contar 15 trazas de modulación/abstención y registrar por separado el rechazo previo de S15. |
| `T01-AF-016` | `imported_approved_decision` | Retirar 44.766 microsegundos por invocación por falta de un benchmark reproducible. |
| `T01-AF-021` | `imported_approved_decision` | Limitar F6 a este caso, versión y topología; episodios externos futuros constituyen evidencia nueva. |
| `T01-AF-022` | `imported_approved_decision` | F3 es principalmente A2, con A3 parcial, y no A4. |
| `T01-AF-023` | `imported_approved_decision` | F4 es A3 y A4-ilustrativo; los artefactos o resultados ausentes se presentan como reportados, no verificados. |
| `T01-AF-028` | `imported_approved_decision` | A5 permanece ausente; un estudio futuro solo podría aportarlo según su diseño, ejecución y resultados. |
| `T01-AF-029` | `imported_approved_decision` | M0--M6 son definiciones normativas internas, no certificación externa ni logro por definición. |

## Decisiones de construcción T03

| ID | Estado | Síntesis operativa |
|---|---|---|
| `T03-PR-001` | `approved_by_author` | Conservar `IFATIGUE-INFRA6-M6` y construir un paquete nuevo `1.1.0` con fecha, procedencia y hashes reales. |
| `T03-AV-002` | `approved_under_standing_authorization` | Mantener los identificadores internos `1.0.0`; la materialización será verificable solo al completar T03 y superar T04. |
| `T03-QG-003` | `approved_by_author` | Someter recomendaciones a control interno multidisciplinario y privilegiar factibilidad científica, técnica, ética, jurídica y reproductiva. |
| `T03-TM-004` | `approved_by_author` | Calcular edad desde `observed_at`; tolerar hasta 5 s futuros; declarar obsoleto desde 300 s inclusive; S13 se abstiene. |
| `T03-RS-005` | `approved_under_standing_authorization` | Separar capas publicadas, decisiones, tesis y enlaces; usar adaptadores exactos por fuente, preservar reglas y excluir conflictos sin corregirlos; fijar fórmula, máscara y enlaces F6. |
| `T03-BL-006` | `approved_under_standing_authorization` | Usar fixtures sintéticos S00--S15, tiempo lógico fijo, metadatos completos, oráculos independientes congelados antes de implementar y regresión simbólica separada. |
| `T03-RP-007` | `superseded_by_T03-RP-012` | Perfil reproducible preliminar; se conserva como historial y no rige cuando difiere de `T03-RP-012`. |
| `T03-DL-008` | `approved_under_standing_authorization` | Exigir trazabilidad granular, vocabularios cerrados, referencias resolubles y estados de materialización verificables en el libro de derivación. |
| `T03-CT-009` | `approved_under_standing_authorization` | Fijar contrato del factor, dominios, validación primero del anfitrión, abstención para fallos del factor, rechazo del anfitrión y diagnósticos ordenados sin cascada. |
| `T03-EX-010` | `approved_under_standing_authorization` | Excluir de ejecución GEA, el paquete histórico y valores no autorizados de antecedentes; separar contexto publicado de decisiones de la instancia. |
| `T03-QA-011` | `approved_under_standing_authorization` | Fijar 16 escenarios, 16 oráculos, 18 pruebas, 15 trazas, un rechazo, esquemas cerrados, independencia de oráculos y criterio binario de la corrida. |
| `T03-QG-014` | `approved_under_standing_authorization` | Definir un gate interno de seis perspectivas, hallazgos trazables, objeto revisado con hash y validadores obligatorios; no confundirlo con F5, pares externos o T04. |
| `T03-RP-012` | `approved_under_standing_authorization` | Establecer perfiles canónicos de texto, JSON, CSV, decimal, manifiestos y ZIP, runtime aislado y reproducción limpia T04. |
| `T03-MP-013` | `approved_under_standing_authorization` | Fijar receta, cobertura, enlaces, grafo acíclico, registros de generadores, orden de gates y bloqueo ante cualquier precondición fallida. |
| `T03-CIT-015` | `approved_under_standing_authorization` | Registrar a Sergio Castellanos Bustamante como autor académico mínimo para metadatos internos, sustentado en la portada; omitir ORCID, correo, DOI, URL y licencia, y reconfirmar los metadatos públicos en T05. Esta identificación no decide titularidad, licencia ni coautoría pública. |

## Corrección operacional aprobada

`T03.3-8-COR-001` aprobó cambiar dos sondas de mutación de `UT-018` de `0.11` a `0.12` después de comprobar que los valores anteriores eran operaciones nulas. El primer intento fallido promovió cero archivos. La fuente se volvió a congelar antes de repetir la corrida. Esta aprobación es un evento operacional documentado en el cierre de T03.3-8; no se inventa como una decisión adicional de `PROVENANCE.json`.

## Decisión todavía abierta

`T05-IP-001` permanece sin resolver. Requiere confirmar titularidad del autor, política institucional, posibles derechos de coautores o patrocinadores y términos separados para código, documentación y contenido. Hasta su resolución:

- `LICENSE_PROPOSED.md` no concede derechos;
- no existe licencia efectiva;
- `CITATION.cff` queda materializado solo con autor, título, tipo y versión mínimos, sin ORCID, correo, DOI, URL ni licencia; esos metadatos requieren reconfirmación antes de su uso público;
- no se afirma depósito ni liberación pública.
