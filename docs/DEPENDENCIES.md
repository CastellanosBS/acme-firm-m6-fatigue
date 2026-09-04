# Dependencias y entorno

## Dependencias de ejecución

El candidato usa únicamente la biblioteca estándar de Python. `requirements.txt` no declara paquetes de terceros. La lógica determinista no requiere red, fuentes de azar ni el reloj del sistema.

No son dependencias del paquete:

- GEA, que no está disponible ni se usa;
- el código o paquete histórico M6 `v1.0.0`, que no está disponible;
- los PDF, manuscritos y artículos fuente, que respaldan la procedencia pero no se cargan en ejecución;
- Java, jFuzzyLogic o PredictiveApriori mencionados en trabajos históricos.

## Entorno de la corrida de referencia

| Propiedad | Valor observado |
|---|---|
| Implementación | CPython |
| Versión | 3.12.13 |
| Sistema | Linux 6.18.35 |
| Arquitectura | `x86_64` |
| Codificación | UTF-8 |
| Base de datos Unicode normativa | 15.0.0 |
| Locale observado | `C.UTF-8` |
| Tiempo lógico inyectado | `2026-09-04T12:00:00Z` |
| Red | no utilizada |
| Azar | no utilizado |
| Reloj del sistema por la lógica probada | no utilizado |

Los indicadores de plataforma describen la corrida interna, no una garantía de portabilidad. T04 debe ejecutar una reproducción limpia y comparar las salidas declaradas; hasta entonces no se afirma compatibilidad fuera del entorno de referencia.

## Perfiles de representación

- Texto: UTF-8 sin BOM, NFC, solo LF, exactamente un LF final, sin NUL, CR ni espacios finales.
- JSON: `IFM6-JSON-v1`, una línea canónica, claves ordenadas, separadores compactos, `ensure_ascii=false`, sin NaN.
- Números reales: cadenas decimales `IFM6-DEC-v1`, nunca `float` binario; contexto `Decimal` con precisión 50 y `ROUND_HALF_EVEN`.
- Tolerancia canónica: `0.000000000001`.
- Trazas: `trace_id` es SHA-256 del `trace_core` JSON canónico, sin metadatos volátiles.
- Tiempo: UTC explícito suministrado por el escenario.

## Ejecución controlada

Los comandos normativos usan `python3 -I -B -X utf8`. `-I` aísla el entorno de usuario, `-B` evita bytecode dentro del paquete y `-X utf8` fija el modo UTF-8. El proyecto no declara un sistema de construcción instalable: se ejecuta mediante los scripts controlados del candidato.
