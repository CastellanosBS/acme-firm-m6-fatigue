# Guía de adaptación sin conocimiento tácito

## Regla de partida

Este candidato no se presenta como un componente *plug-and-play*. Adaptar el factor, el anfitrión, la fórmula, una interfaz o una regla crea un nuevo episodio de diseño y evidencia. No se debe modificar el candidato congelado: se crea un identificador y una versión nuevos, se conservan las fuentes y se documenta cada decisión.

La fórmula, `lambda = 0.3`, el mapa hacia `coping_potential` y los umbrales de esta instancia no pueden copiarse a otro contexto sin una justificación científica y técnica independiente.

## Procedimiento mínimo

1. **Identificar el nuevo episodio.** Declare propósito, responsables, versión, contexto de uso y afirmaciones permitidas.
2. **Redactar M0.** Defina problema, factor, anfitrión, frontera, objetivo, alcance y exclusiones.
3. **Construir el perfil del factor.** Especifique constructo, estado, dominios, procedencia, calidad, temporalidad, ausencia y fallos.
4. **Construir el perfil del anfitrión.** Declare variables, semántica, dominios, orden, estado basal, propietario y frontera de integración.
5. **Aprobar el mapa de influencia.** Identifique destinos autorizados y dimensiones protegidas; cierre ante colisiones o enlaces ausentes.
6. **Especificar el modelo.** Declare fórmula, parámetros, unidades, límites, invariantes, neutralidad y composición.
7. **Realizar la implementación e interfaz.** Separe capas publicadas, decisiones, tesis y enlaces; versionelas y resuelva conflictos de forma explícita.
8. **Formalizar el contrato.** Defina validación, orden de diagnósticos, abstención, rechazo, trazas, entradas y salidas.
9. **Construir evaluación independiente.** Fije escenarios y oráculos antes de implementar; añada matriz, pruebas, trazas y criterios de fallo.
10. **Congelar y auditar.** Cree el manifiesto fuente, ejecute la corrida de referencia transaccional, complete control interno, empaquete en una tarea separada y realice reproducción limpia T04.

## Adaptación según el anfitrión

| Tipo de anfitrión | Elementos que deben especificarse | Riesgos y controles mínimos |
|---|---|---|
| Reglas simbólicas | Sintaxis, orden, prioridad, conflicto, dominio, estado basal y adaptadores de términos | Preservar semántica fuente; coincidencia exacta; probar cero, una y múltiples reglas; proteger variables no autorizadas |
| Proceso dinámico | Secuencia temporal, dependencias, estado, frecuencia de actualización y realimentación | Sincronización, frescura, latencia lógica, ciclos y estabilidad; registrar el instante efectivo de cada estado |
| Sistema difuso | Universo, funciones de pertenencia, cobertura, reglas, agregación, normalización y defuzzificación | Probar cobertura y fronteras; conservar significado de etiquetas; no inferir equivalencias lingüísticas |
| Arquitectura modular | API, esquema, versión, latencia, responsabilidad, política de error y observabilidad | Contrato explícito en la frontera; compatibilidad de versiones; aislamiento de fallos; trazabilidad extremo a extremo |
| Híbrido o aprendido | Punto interpretable de intervención, representación, incertidumbre, datos, límites y señales observables | Datos y deriva, fuera de distribución, explicabilidad, reproducibilidad, sesgo y trazas suficientes para diagnóstico |

## Propagación obligatoria de cambios

| Cambio | Objetos que deben revisarse o regenerarse | Controles que deben repetirse |
|---|---|---|
| Perfil del factor | Mapa, modelo, contrato y matriz | Admisibilidad, estado, neutralidad y semántica |
| Perfil del anfitrión | Mapa, implementación, interfaz, contrato y escenarios | Línea basal, compatibilidad, dimensiones protegidas y regresión |
| Mapa de influencia | Modelo, localidad, composición y matriz | Destinos, colisiones, máscara y protección |
| Modelo o parámetros | Modulador, contrato, escenarios y resultados | Dominios, invariantes, límites y oráculos independientes |
| Realización o interfaz | Contrato, trazas y ejecución | Esquemas, versiones, fallos y observabilidad |
| Contrato | Participantes, matriz y conformidad | Cobertura, diagnósticos y cierre seguro |
| Matriz de evaluación | Evidencia M5, afirmaciones y estado M6 | Independencia, cobertura, resultados y límites |

## Enlaces de la instancia actual

| Clave | Destino actual |
|---|---|
| `coping_potential` | `host.baseline.coping_potential` |
| `z` | `factor_state.level` |
| `lambda` | `influence.parameters.lambda` |
| `result` | `output.coping_potential` |

Estos enlaces son informativos para reproducir esta instancia, no valores predeterminados para otras.

## Casos que exigen trabajo adicional

La composición multifactorial no fue evaluada. Una adaptación con más de un factor debe especificar orden, simultaneidad, prioridad, interacción, conmutatividad, saturación, arbitraje y trazabilidad, además de escenarios para conflictos y efectos acumulados.

Una adaptación con datos de personas necesita revisión ética, jurídica y de protección de datos, instrumentos válidos y evidencia empírica separada. Una adaptación a otro ACME necesita un perfil, mapa, contrato, matriz y episodio de reproducción nuevos. Ninguna reutilización constituye evidencia hasta superar esos controles.
