# Declaración de integración M0

## Identificación y estado

- Instancia conceptual: `IFATIGUE-INFRA6-M6`.
- Versión del paquete candidato: `1.1.0`.
- Artefactos internos: versión `1.0.0`.
- Naturaleza: reconstrucción doctoral nueva y trazable; no es recuperación del paquete histórico `v1.0.0` ni de su código.
- Estado de esta declaración: materializada en T03.3-9 para control interno.

M0 es una condición normativa interna, binaria y acumulativa de ACME-FIRM. Esta declaración no constituye certificación externa, validación empírica ni liberación pública, y no acredita por sí sola los niveles M1--M6.

## Problema de integración

La instancia especifica cómo introducir un estado externo de fatiga cognitiva transitoria en un anfitrión computacional de valoración sin alterar dimensiones no autorizadas, sin confundir una variable de ingeniería con una medición psicológica validada y sin atribuir al código histórico ausente propiedades que no pueden inspeccionarse.

## Factor de influencia

El factor es `cognitive_fatigue`. La implementación no estima fatiga: recibe un estado sintético externo cuyo nivel `z` es una cadena decimal canónica dentro de `[0,1]`. El estado incluye además confianza, instante de observación, identificador de fuente y versión de esquema. En la corrida de referencia, todos esos datos son fixtures sintéticos; no proceden de participantes ni de GEA.

## Modelo anfitrión

El anfitrión es `ACME-INFRA6-RR-1.0.0`, reconstruido a partir de especificaciones publicadas y de la especificación doctoral, no de código histórico. Su vector de valoración contiene, en este orden:

1. `expectedness`;
2. `desirability`;
3. `novelty`;
4. `pleasure`;
5. `goal_conduciveness`;
6. `coping_potential`.

La frontera de integración se ubica después de `general_appraisal` y antes de `emotional_filter`.

## Propósito y regla autorizada

El propósito es materializar y probar una integración local, determinista, explícita y trazable entre el estado sintético del factor y la salida del anfitrión. La única dimensión autorizada es `coping_potential`. Las otras cinco dimensiones están protegidas y deben conservarse exactamente.

La regla doctoral de esta instancia es:

\[
coping\_potential_{out} = \operatorname{clamp}\bigl(coping\_potential_{in}(1-\lambda z),0,1\bigr),
\qquad \lambda=0.3.
\]

Los enlaces ejecutables son cerrados:

| Rol | Enlace |
|---|---|
| `coping_potential` | `host.baseline.coping_potential` |
| `z` | `factor_state.level` |
| `lambda` | `influence.parameters.lambda` |
| `result` | `output.coping_potential` |

Un valor o enlace no declarado provoca cierre seguro; no se infieren destinos implícitos.

## Alcance de la evidencia

La contribución de esta instancia se restringe a A3--A4: construcción y evaluación técnica interna mediante escenarios y oráculos sintéticos. La corrida de referencia vigente, identificada en `PACKAGE_METADATA.json#/source_snapshot/run_id`, mostró conformidad contractual en 16/16 escenarios y 18/18 pruebas, con 15 trazas y un rechazo previo a modulación. Esa evidencia respalda instanciación, conformidad técnica y trazabilidad dentro de esta versión; no respalda utilidad, efectividad, adopción, generalización, evaluación de campo ni causalidad psicológica.

## Núcleo documental

La declaración se desarrolla mediante siete artefactos, sin equivalencia con archivos históricos recuperados:

| Nivel principal | Artefacto |
|---|---|
| M1 | `artifacts/01_PF-FAT-1.0.0.md` |
| M2 | `artifacts/02_PA-INFRA6-1.0.0.md` |
| M3 | `artifacts/03_MFV-FAT-COP-1.0.0.md` |
| M3 | `artifacts/04_MI-FAT-COP-1.0.0.md` |
| M3--M4 | `artifacts/05_MOD-FAT-COP-1.0.0_IF-GA-EF-1.0.0.md` |
| M4 | `artifacts/06_CI-FAT-INFRA6-1.0.0.md` |
| M5 | `artifacts/07_ME-FAT-INFRA6-1.0.0.md` |

Los siete documentos se materializan en T03.3-9. La construcción del `BUILD_RECORD`, del manifiesto final y del ZIP corresponde a T03.3-10; la reproducción limpia corresponde a T04. Por tanto, este documento no declara cierre M6, reproducción T04 ni liberación.
