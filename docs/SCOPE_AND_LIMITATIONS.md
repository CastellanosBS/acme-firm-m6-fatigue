# Alcance y limitaciones

## Alcance positivo

La instancia `IFATIGUE-INFRA6-M6` materializa una reconstrucción doctoral nueva del caso F6 para comprobar, con evidencia sintética interna, que una influencia acotada puede integrarse de forma determinista, local y trazable en un vector de valoración de seis dimensiones.

La política de F6 es exacta: `authorized_scopes = [A3, A4]`, `A5 = false` y `evidence_kind = internal_synthetic_conformance`. Las afirmaciones DSR permitidas son únicamente:

- instanciación;
- conformidad técnica;
- trazabilidad.

Las dimensiones técnicas examinadas son determinismo, localidad y capacidad de reproducción definida por contrato. La corrida de referencia interna fue aceptada; la reproducción limpia e independiente de T04 permanece pendiente.

## Límites por contribución

| Contribución | Lectura admisible | Lectura no admisible |
|---|---|---|
| F1 | Restricción teórica: el afrontamiento depende de recursos y contexto | Fuente de parámetros ejecutables o prueba causal de la fórmula |
| F3 | Principalmente A2, con A3 parcial | A4 o evidencia de operación de campo |
| F4 | Linaje procedimental A3 y A4-ilustrativo | Reutilización de valores operativos o aplicación real verificada |
| F5 | Panel externo futuro que, según su diseño, solo podría aportar A1 y A3 | Evidencia ya ejecutada, A2 o A5 |
| F6 | A3--A4 internos y sintéticos para esta versión, caso y topología | A5, transferencia automática o evidencia de otros episodios |

M0--M6 son niveles normativos internos, binarios y acumulativos. No son una certificación externa y no se consideran satisfechos solo porque estén definidos. Cada estado exige evidencia material verificable de sus precondiciones.

## Afirmaciones prohibidas con la evidencia actual

El paquete no demuestra:

- utilidad, efectividad, superioridad o adopción externa;
- generalización, portabilidad a terceros o evaluación de campo;
- validez psicológica, causal, clínica, ecológica, poblacional, educativa o psicométrica;
- que `z` mida fatiga real o que `confidence` sea una probabilidad calibrada;
- que la fatiga cause la variación modelada en `coping_potential`;
- que ACME-FIRM mejore agentes o decisiones pedagógicas;
- composición multifactorial, interacción entre factores o políticas de resolución de conflictos entre módulos;
- equivalencia con el código o el paquete histórico `v1.0.0`.

## Exclusiones materiales y de ejecución

- El texto completo de la obra de 2020 no está disponible; su registro se limita a metadatos de la envoltura bibliográfica.
- Java, jFuzzyLogic, PredictiveApriori, reglas y resultados históricos de 2019 no forman parte del ejecutable F6.
- Los coeficientes, métricas y casos ilustrativos de 2026 no se reutilizan como parámetros de esta instancia.
- GEA está ausente y no se usa para construcción, calibración, ejecución, oráculos, pruebas ni redistribución.
- El paquete histórico M6 `v1.0.0` está ausente. La versión `1.1.0` no reutiliza sus bytes y no reclama continuidad material.
- Los PDF y manuscritos fuente no se incluyen en el paquete.

## Estado de las evaluaciones

La corrida de referencia vigente, cuyo identificador se registra en `PACKAGE_METADATA.json#/source_snapshot/run_id`, produjo 16/16 coincidencias con oráculos, 18/18 pruebas aprobadas, 15 trazas y un rechazo previo a modulación. Esto demuestra conformidad con contratos sintéticos congelados dentro del entorno y la topología declarados, no verdad empírica del constructo.

La finalización técnica T03.3-10 solo cierra la construcción determinista del
candidato y no amplía estas afirmaciones. La reproducción limpia T04, el panel
externo F5 y cualquier depósito o liberación pública siguen fuera del alcance de
este estado. Todo episodio externo futuro constituye evidencia nueva y requiere
especificación, pruebas y trazabilidad propias.
