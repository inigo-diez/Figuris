# ADR 0007 — Capa de evidencia: texto de las figuras con RapidOCR

- **Estado:** aceptada para la etapa 5 (2026-10-07); se revisará cuando haya una referencia de OCR para figuras rasterizadas.
- **Fecha:** 2026-10-07

## Contexto

El sistema no comprobaba los números que el modelo dice leer en una figura. Las afirmaciones «observado» tampoco apuntaban a una región concreta, solo a la figura o al panel. La revisión externa (docs/reviews/2026-10-07-revision-externa.md) propuso tratar el OCR como una **capa de evidencia**: cada texto con su caja, su confianza y su productor. También pidió medirlo (E03) antes de usarlo para invalidar afirmaciones.

Casi todas las figuras publicadas son una imagen rasterizada, sin texto en el PDF. Las figuras vectoriales sí tienen texto exacto, y ese texto sirve de referencia gratuita para medir el OCR.

Restricciones: licencia compatible con Apache-2.0, instalación con pip en Windows sin privilegios, sin PyTorch y funcionamiento sin conexión una vez instalado ([ADR 0005](0005-pdfium-heuristic-baseline-extractor.md)).

## Alternativas consideradas

- **Tesseract / OCRmyPDF:** necesita instalar un programa del sistema, fuera de pip. Queda como candidato si se instala.
- **PaddleOCR completo:** dependencia pesada (PaddlePaddle).
- **EasyOCR / docTR:** requieren PyTorch o TensorFlow.
- **RapidOCR:** Apache-2.0, sobre ONNX Runtime (MIT), con los modelos de PaddleOCR (Apache-2.0). Se instala con pip; descarga 31 MB de modelos una sola vez.
- **El propio modelo multimodal como OCR:** no sirve para verificar lo que ese mismo modelo afirma.

## Evidencia (E03, `scripts/eval/ocr_eval.py`, ejecución `evaluation/runs/20261007-104912-ocr-rapidocr-3.9.2-ac2fbc31`)

- **Referencia exacta:** el texto PDF de 17 figuras vectoriales de `dev` + `validation` (953 números, 709 palabras). Las figuras se renderizan como imagen y se leen con OCR.
- **Letras de panel:** las 185 cajas de panel humanas.

| | 150 ppp | **200 ppp** | 300 ppp |
|---|---:|---:|---:|
| Números leídos bien (sin signo) | 0,884 | **0,897** | 0,898 |
| Números leídos mal | 40 | **29** | 31 |
| Palabras leídas bien | 0,874 | 0,883 | 0,894 |
| Segundos por figura | 7,4 | 6,9 | 8,5 |

- **Letras de panel encontradas dentro de su panel:** 0,87; con mayúsculas y minúsculas exactas, 0,74.
- **Umbrales de detección 0,3** (en lugar de 0,5): más texto pequeño leído (0,90 → 0,92 en una muestra), a cambio de más sustituciones.
- **Fallos que no son del OCR:** exponentes que el PDF guarda como «104» para 10⁴, y subíndices químicos partidos. **Fallos reales:** texto muy pequeño, marcas de eje contiguas leídas como una sola («350400») y algún dígito o decimal perdido.

## Decisión

- **Capa de evidencia** (`sfi.extract.evidence`): cada figura guarda `tokens` con texto, caja normalizada, confianza y origen:
  - `pdf`: texto exacto del PDF;
  - `pdf-ocr`: capa de texto de un escaneado, con confianza 0,7;
  - `ocr:rapidocr-3.9.2`: lectura propia a 200 ppp, palabra a palabra.
  El OCR solo cede ante el texto exacto del PDF. La configuración del OCR forma parte de la identidad de cada ejecución.
- **Uso actual:**
  1. los números de afirmaciones «observado» o «inferencia» se enlazan con el sitio donde están impresos (`token_refs`), y la aplicación lo muestra;
  2. el aviso `number_not_in_figure` se calcula y se guarda, pero **no se muestra ni invalida**. Con una precisión de 0,90, en los 19 avisos iniciales casi todos eran fallos del OCR.
- **Activación:** `SFI_FIGURE_OCR=auto` (por defecto) usa el OCR si el extra `ocr` está instalado.

## Consecuencias y riesgos

- **No cumple el umbral de E03** (≥ 0,95 en figuras digitales). Por eso el OCR aporta pruebas a favor, no en contra.
- **Coste de tiempo:** unos 2–7 s por figura en CPU. Procesar un artículo de 16 figuras pasa de segundos a uno o dos minutos.
- **Medición incompleta:** la precisión medida es sobre figuras vectoriales renderizadas. En figuras rasterizadas reales, sobre todo escaneadas, será menor y aún no hay referencia.
- **Siguientes pasos:**
  - usar las letras de panel leídas (0,87) como anclas para separar paneles;
  - medir el OCR en figuras rasterizadas con una pequeña anotación;
  - comparar con Tesseract si se instala.
