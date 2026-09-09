# Especificación Técnica del Árbol de Nodos — Migración v1.0 → v2.0 (Definitiva)

**Estado:** v2.0 **aún no se ha implementado en producción**. Este documento reemplaza el borrador de v2.0 anterior: en vez de publicar esa versión y corregirla después con un parche v3, las correcciones ya identificadas se incorporan **directamente en el diseño de v2.0** antes de escribir una sola línea de código. No existirá una versión intermedia con los bugs conocidos.

**De dónde partimos (v1.0):** arreglo ambiguo `marks: [...]` para formato de texto, nombres heterogéneos (`alignment` vs `textAlign`), nodos inline mezclados sin jerarquía clara, hyperlinks y resaltado sin forma normalizada, sin protocolo de sincronización.

**A dónde llegamos (v2.0, este documento):** consolidación de formato en `style`, normalización camelCase estricta, jerarquía Bloque/Atómico/Inline explícita, **y además** representación única de hyperlinks, enum cerrado para resaltado, cascada de estilos por recorrido de ancestros, numeración con definición compartida, protocolo de sincronización, y nodos reservados para imagen inline y headers/footers.

---

## Índice

1. [Principios de diseño](#1-principios-de-diseño)
2. [Arquitectura global del árbol](#2-arquitectura-global-del-árbol)
3. [Cascada de estilos](#3-cascada-de-estilos)
4. [Catálogo completo de nodos](#4-catálogo-completo-de-nodos)
5. [Protocolo de sincronización](#5-protocolo-de-sincronización)
6. [Cobertura DOCX](#6-cobertura-docx)
7. [Documento de ejemplo completo](#7-documento-de-ejemplo-completo)
8. [Plan de migración de datos v1 → v2](#8-plan-de-migración-de-datos-v1--v2)
9. [JSON Schema y CI](#9-json-schema-y-ci)
10. [Checklist de validación](#10-checklist-de-validación)

---

## 1. Principios de diseño

1. **Una sola forma de representar cada concepto.** Nunca dos nodos o campos distintos para el mismo significado.
2. **El JSON nunca permite un valor que OOXML no pueda representar fielmente.** Enums cerrados donde Word tiene paleta cerrada; nunca string libre "por si acaso".
3. **La forma estática del árbol y el protocolo de cambios incrementales se diseñan juntos**, no el segundo como ocurrencia tardía.
4. **Todo lo reservado a futuro (imágenes, headers/footers) se declara ya en el esquema**, aunque no se implemente su render, para no requerir una v3 de migración de forma.

---

## 2. Arquitectura global del árbol

```
document (raíz)
 ├─ meta: { title, style_guide, author, version }
 ├─ global_style: { fontFamily, fontSize, lineHeight, pageMargin, ... }
 ├─ numbering_definitions: { [numId]: {...} }        ← nuevo respecto a v1
 ├─ headers_footers: { default_header, default_footer, first_page_different }  ← reservado
 └─ children: Array<BlockNode | AtomicNode>
      ├─ heading-1..5, paragraph, block-quote
      │      └─ children: Array<text | hyperlink | field | tab | footnote | image-inline>
      ├─ bulleted-list / numbered-list (referencia numId) → list-item → children
      ├─ table → table-row → table-cell → paragraph...
      └─ page-break, section-break, table-of-contents, image (atómicos, sin children)
```

**Categorías de nodo:**

| Categoría | Tipos |
|---|---|
| Bloque (con `children`) | `heading-1..5`, `paragraph`, `block-quote`, `bulleted-list`, `numbered-list`, `list-item`, `table`, `table-row`, `table-cell` |
| Atómico de bloque (sin `children`) | `page-break`, `section-break`, `table-of-contents`, `image` |
| Inline (dentro de párrafos) | `text` (hoja, sin `type`), `hyperlink`, `field`, `tab`, `footnote`, `endnote`, `image-inline` (reservado) |

---

## 3. Cascada de estilos

**Corrección clave vs. el borrador anterior:** no es una fórmula fija de 4 términos — es un recorrido de todos los ancestros reales del nodo, porque una celda de tabla tiene 6 niveles de herencia (`table → row → cell → paragraph → text`), no 4.

```
resolved_style(node) =
    system_defaults
    ⊕ document.global_style
    ⊕ ancestor_1.style   // ej: table.style
    ⊕ ancestor_2.style   // ej: table-row.style
    ⊕ ancestor_3.style   // ej: table-cell.style
    ⊕ ...                // cualquier bloque intermedio
    ⊕ node.style          // paragraph.style o text.style, lo más cercano a la hoja
```

Pseudocódigo del motor de renderizado:

```js
function resolveStyle(node, ancestorChain) {   // ancestorChain: raíz → nodo, en orden
  let style = { ...SYSTEM_DEFAULTS, ...document.global_style };
  for (const ancestor of ancestorChain) {
    if (ancestor.style) style = deepMerge(style, ancestor.style);
  }
  if (node.style) style = deepMerge(style, node.style);
  return style;
}
```

No se necesita ningún campo nuevo para esto — la jerarquía de `children` ya la representa. Es el algoritmo el que se implementa correctamente desde el inicio.

---

## 4. Catálogo completo de nodos

### 4.1 Nodo raíz (`document`)

```json
{
  "type": "document",
  "meta": {
    "title": "Fundamentos de Hardware y su Relación con la Programación de Sistemas",
    "style_guide": "APA7",
    "author": "Aram Musset",
    "version": "2.0"
  },
  "global_style": {
    "fontFamily": "Times New Roman, serif",
    "fontSize": "12pt",
    "color": "#000000",
    "lineHeight": 2.0,
    "pageSize": "letter",
    "orientation": "portrait",
    "pageMargin": { "top": "1in", "right": "1in", "bottom": "1in", "left": "1in" },
    "backgroundColor": "#ffffff",
    "showPageNumbers": true,
    "pageNumberPosition": "top-right"
  },
  "numbering_definitions": {},
  "headers_footers": {
    "default_header": { "children": [] },
    "default_footer": { "children": [] },
    "first_page_different": false
  },
  "children": []
}
```

`numbering_definitions` y `headers_footers` pueden ir vacíos/omitidos si el documento no los usa, pero **el esquema los declara desde v2.0** para que no haya que migrar la forma otra vez.

---

### 4.2 Encabezados y párrafos (`heading-1..5`, `paragraph`, `block-quote`)

Sin cambios de forma respecto al diseño original, salvo la regla de `section_type` (§4.2.1) y que sus `children` ahora pueden incluir `image-inline`.

```json
{
  "id": "node-101",
  "type": "paragraph",
  "section_type": "introduction",
  "style": {
    "textAlign": "justify",
    "lineHeight": 1.15,
    "spaceBefore": "0pt",
    "spaceAfter": "6pt",
    "indent": { "firstLine": "0.5in", "left": "0pt", "right": "0pt" }
  },
  "children": [
    { "text": "La " },
    { "text": "infraestructura", "style": { "bold": true } },
    { "text": " tecnológica contemporánea..." }
  ]
}
```

#### 4.2.1 Regla de `section_type`

- **Obligatorio** únicamente en nodos que son hijos directos de `document.children`.
- **No se serializa** en bloques anidados dentro de `table-cell`, `footnote`, `endnote`, `list-item` — heredan la sección de su ancestro de nivel superior para fines de lógica de negocio (TOC, numeración APA), sin duplicarla en cada nodo.

```json
// ✅ paragraph anidado en table-cell, sin section_type
{ "type": "table-cell", "children": [
  { "id": "node-303", "type": "paragraph", "style": { "textAlign": "center" }, "children": [...] }
]}
```

---

### 4.3 Listas (`bulleted-list`, `numbered-list`, `list-item`) — con numeración compartida

**Corrección vs. borrador anterior:** el nivel `listLevel` por ítem no basta para reinicio de numeración ni formatos multinivel — eso vive en una definición compartida referenciada por `numId`, igual que `numbering.xml` en OOXML.

```json
// document.numbering_definitions
{
  "numbering_definitions": {
    "num-1": {
      "type": "numbered",
      "levels": [
        { "level": 0, "format": "decimal", "suffix": ".", "startAt": 1 },
        { "level": 1, "format": "lowerLetter", "suffix": ")", "startAt": 1 }
      ]
    },
    "num-2": {
      "type": "bulleted",
      "levels": [
        { "level": 0, "bulletChar": "•" },
        { "level": 1, "bulletChar": "◦" }
      ]
    }
  }
}
```

```json
{
  "id": "node-200",
  "type": "numbered-list",
  "section_type": "body",
  "numId": "num-1",
  "children": [
    {
      "id": "node-201",
      "type": "list-item",
      "style": { "listLevel": 0 },
      "children": [ { "text": "Primer elemento de la lista." } ]
    }
  ]
}
```

Dos listas que deben **continuar** la misma numeración referencian el mismo `numId`; si deben **reiniciar**, usan `numId` distintos.

---

### 4.4 Tablas (`table`, `table-row`, `table-cell`)

Sin cambios de forma respecto al diseño original. La corrección que le aplica es la de la cascada de estilos (§3): el motor debe recorrer `table.style → table-row.style → table-cell.style → paragraph.style → text.style`, no una fórmula de 4 niveles.

```json
{
  "id": "node-300",
  "type": "table",
  "section_type": "body",
  "caption": "Tabla 1: Comparativa de rendimiento de memoria",
  "style": {
    "textAlign": "center",
    "width": "100%",
    "borders": {
      "top": { "style": "single", "size": "1pt", "color": "#000000" },
      "bottom": { "style": "single", "size": "1pt", "color": "#000000" }
    }
  },
  "children": [
    {
      "id": "node-301",
      "type": "table-row",
      "children": [
        {
          "id": "node-302",
          "type": "table-cell",
          "colSpan": 1,
          "rowSpan": 1,
          "style": { "width": "156pt", "backgroundColor": "#F2F2F2", "padding": "6pt" },
          "children": [
            {
              "id": "node-303",
              "type": "paragraph",
              "style": { "textAlign": "center" },
              "children": [ { "text": "Encabezado 1", "style": { "bold": true } } ]
            }
          ]
        }
      ]
    }
  ]
}
```

---

### 4.5 Nodos atómicos de bloque

#### A. `page-break`, `section-break`

```json
{ "id": "node-27", "type": "page-break", "section_type": "index" }
```

```json
{
  "id": "node-28",
  "type": "section-break",
  "section_type": "body",
  "metadata": { "breakType": "next-page" }
}
```

#### B. `table-of-contents`

```json
{
  "id": "node-26",
  "type": "table-of-contents",
  "section_type": "index",
  "style": { "marginLeft": "0pt" },
  "metadata": { "maxLevel": 3, "showPageNumbers": true }
}
```

#### C. `image` (bloque, reservado) e `image-inline` (nuevo, reservado)

```json
// bloque — imagen como elemento independiente en el flujo de children
{
  "id": "node-400",
  "type": "image",
  "section_type": "body",
  "src": "https://example.com/assets/cpu-architecture.png",
  "alt": "Diagrama de arquitectura interna de CPU",
  "caption": "Figura 1: Componentes del procesador",
  "style": { "width": "400pt", "height": "250pt", "textAlign": "center" }
}
```

```json
// inline — nuevo en v2.0, dentro de paragraph.children, para íconos en medio de una oración
{
  "id": "node-405",
  "type": "image-inline",
  "src": "https://example.com/assets/icon-cpu.png",
  "alt": "ícono de CPU",
  "style": { "width": "14pt", "height": "14pt" }
}
```

Ninguna de las dos formas de imagen implementa render todavía — solo se fija la forma para no requerir otra migración de esquema cuando se implemente.

---

### 4.6 Nodos hoja e inline

#### A. Fragmento de texto (`text`)

Nunca tiene `type` ni `children`. **`highlight` es ahora un enum cerrado**; para color de fondo arbitrario existe el campo nuevo `backgroundShading`.

```json
{
  "text": "Linus Torvalds",
  "style": {
    "bold": true,
    "italic": false,
    "underline": true,
    "strikethrough": false,
    "fontSize": "12pt",
    "fontFamily": "Times New Roman",
    "color": "#4F81BD",
    "highlight": "yellow",
    "backgroundShading": "#E8E8E8",
    "script": "none",
    "code": false
  }
}
```

`highlight` acepta únicamente: `"yellow" | "green" | "cyan" | "magenta" | "blue" | "red" | "darkBlue" | "darkCyan" | "darkGreen" | "darkMagenta" | "darkRed" | "darkYellow" | "darkGray" | "lightGray" | "black" | "white" | "none"` (mapea a `<w:highlight>`). `backgroundShading` acepta cualquier hex (mapea a `<w:shd>`, elemento distinto).

`script` acepta únicamente `"none" | "superscript" | "subscript"`.

**Ya no existe `text.link`** — ver §4.6.B, único mecanismo válido para hipervínculos.

#### B. Hipervínculos (`hyperlink`) — representación única

```json
{
  "id": "node-500",
  "type": "hyperlink",
  "metadata": { "url": "https://kernel.org", "tooltip": "Documentación oficial del kernel" },
  "children": [
    { "text": "Kernel de ", "style": { "color": "#0000FF", "underline": true } },
    { "text": "Linux", "style": { "color": "#0000FF", "underline": true, "bold": true } }
  ]
}
```

Un hipervínculo que cubre varios `text` con formato distinto se representa con varios hijos dentro del mismo nodo `hyperlink` — nunca repartiendo `link.url` en cada `text` suelto.

**Mapeo OOXML:** `hyperlink` → `<w:hyperlink r:id="rIdN">` con relación en `document.xml.rels`; cada `text` hijo → un `<w:r>` dentro.

#### C. Campos, tabuladores y notas (`field`, `tab`, `footnote`, `endnote`)

```json
{ "id": "node-501", "type": "field", "field_type": "PAGE" }
```

```json
{ "id": "node-502", "type": "tab" }
```

```json
{
  "id": "node-503",
  "type": "footnote",
  "metadata": { "noteId": "fn-1" },
  "children": [
    { "id": "node-504", "type": "paragraph", "children": [
      { "text": "Nota al pie explicativa sobre el procesador Intel 386." }
    ]}
  ]
}
```

**Regla de transformación obligatoria (no cambia la forma del nodo, sí el paso de generación):** `footnote.children`/`endnote.children` **no se serializan dentro de `document.xml`**. El generador docx debe extraer ese subárbol a `footnotes.xml`/`endnotes.xml`, referenciado por `metadata.noteId`, y dejar en el flujo principal solo `<w:footnoteReference w:id="{noteId}"/>`.

---

## 5. Protocolo de sincronización

**Por qué está aquí desde v2.0 y no como añadido posterior:** sin un formato de operación incremental, cada edición del frontend obliga a re-serializar el árbol completo — no escala con documentos largos y bloquea colaboración en tiempo real si eso entra al roadmap.

```json
{
  "op": "insert_node | delete_node | update_style | update_text | move_node | update_metadata",
  "node_id": "node-101",
  "path": "style.textAlign",
  "value": "center",
  "target_parent_id": "node-100",
  "position": 2,
  "timestamp": "2026-09-08T14:30:00Z",
  "actor": "frontend | backend | import-docx"
}
```

| Operación | Aplica a | Restricción |
|---|---|---|
| `insert_node` | cualquier bloque/inline | `target_parent_id` debe aceptar ese tipo como hijo válido |
| `delete_node` | cualquier nodo excepto `document` | — |
| `update_style` | cualquier nodo con `style` | `path` debe existir en el esquema de estilos de ese tipo |
| `update_text` | nodo `text` | solo modifica `text`, no `style` |
| `move_node` | cualquier bloque | no permite mover un nodo dentro de sí mismo o su descendiente |
| `update_metadata` | nodos con `metadata` (`field`, `footnote`, `section-break`, `hyperlink`) | — |

**Resolución de conflictos mínima viable:** last-write-wins por `node_id` + `path`, comparando `timestamp`. Los campos `actor`/`timestamp` son la base para migrar a OT/CRDT más adelante sin rediseñar el protocolo.

---

## 6. Cobertura DOCX

| Característica DOCX | Nodo JSON | Soporte |
|---|---|---|
| Alineación de párrafo | `paragraph.style.textAlign` | Completo |
| Interlineado/espaciado | `style.lineHeight/spaceBefore/spaceAfter` | Completo |
| Sangrías | `style.indent` | Completo |
| Formato de texto | `text.style` | Completo |
| Resaltado (paleta Word) | `text.style.highlight` | Completo |
| Sombreado de carácter (color libre) | `text.style.backgroundShading` | Completo |
| Hipervínculos | `hyperlink` | Completo, forma única |
| Tablas/celdas | `table`, `table-row`, `table-cell` | Completo |
| Numeración de listas (multinivel, reinicio) | `numbering_definitions` + `numId` | Completo |
| Encabezados H1-H5 | `heading-1..5` | Completo |
| Saltos página/sección | `page-break`, `section-break` | Completo |
| Notas al pie/final | `footnote`, `endnote` (extraídas a parte separada) | Completo |
| Campos | `field` | Completo |
| Imágenes de bloque | `image` | Forma definida, sin render |
| Imágenes inline | `image-inline` | Forma definida, sin render |
| Headers/footers de página | `headers_footers` | Forma definida, sin render |

---

## 7. Documento de ejemplo completo

```json
{
  "type": "document",
  "meta": {
    "title": "Fundamentos de Hardware y su Relación con la Programación de Sistemas",
    "style_guide": "APA7",
    "author": "Aram Musset",
    "version": "2.0"
  },
  "global_style": {
    "fontFamily": "Times New Roman, serif",
    "fontSize": "12pt",
    "color": "#000000",
    "lineHeight": 2.0,
    "pageSize": "letter",
    "orientation": "portrait",
    "pageMargin": { "top": "1in", "right": "1in", "bottom": "1in", "left": "1in" },
    "backgroundColor": "#ffffff",
    "showPageNumbers": true,
    "pageNumberPosition": "top-right"
  },
  "numbering_definitions": {},
  "headers_footers": {
    "default_header": { "children": [] },
    "default_footer": { "children": [] },
    "first_page_different": false
  },
  "children": [
    {
      "id": "node-34",
      "type": "heading-1",
      "section_type": "presentation",
      "style": { "textAlign": "center" },
      "children": [
        { "text": "Fundamentos de Hardware y su Relación con la Programación de Sistemas", "style": { "bold": true } }
      ]
    },
    {
      "id": "node-1",
      "type": "paragraph",
      "section_type": "presentation",
      "style": { "textAlign": "center" },
      "children": [ { "text": "arammusset7@gmail.com" } ]
    },
    { "id": "node-27", "type": "page-break", "section_type": "index" },
    {
      "id": "node-26",
      "type": "table-of-contents",
      "section_type": "index",
      "style": { "marginLeft": "0pt" },
      "metadata": { "maxLevel": 3, "showPageNumbers": true }
    },
    { "id": "node-28", "type": "page-break", "section_type": "index" },
    {
      "id": "node-100",
      "type": "heading-1",
      "section_type": "introduction",
      "style": { "textAlign": "left" },
      "children": [ { "text": "La evolución del desarrollo colaborativo", "style": { "fontSize": "14pt" } } ]
    },
    {
      "id": "node-101",
      "type": "paragraph",
      "section_type": "introduction",
      "style": { "textAlign": "justify", "lineHeight": 1.15 },
      "children": [
        { "text": "La " },
        { "text": "infraestructura", "style": { "bold": true } },
        { "text": " tecnológica contemporánea se sustenta sobre pilares de código abierto. En el centro se encuentra " },
        {
          "id": "node-102",
          "type": "hyperlink",
          "metadata": { "url": "https://medium.com/vineeth-vijayan/linus-torvald-0e942828b92d" },
          "children": [
            { "text": "Linus Torvalds", "style": { "bold": true, "underline": true, "color": "#4F81BD" } }
          ]
        },
        { "text": ", un " },
        { "text": "ingeniero", "style": { "fontSize": "24pt" } },
        { "text": " de software finlandés." }
      ]
    },
    {
      "id": "node-91",
      "type": "heading-1",
      "section_type": "sources",
      "children": [ { "text": "Referencias", "style": { "bold": true } } ]
    },
    {
      "id": "node-92",
      "type": "paragraph",
      "section_type": "sources",
      "metadata": { "docxImported": true },
      "style": { "textAlign": "left", "indent": { "hanging": "0.5in" } },
      "children": [ { "text": "Lenovo (2026). ¿Qué es una computadora de escritorio?." } ]
    }
  ]
}
```

Nótese el nodo `node-102`: es un `hyperlink` que envuelve el `text` "Linus Torvalds" — ya no un `text` suelto con `link.url`, que era la forma ambigua del borrador anterior.

---

## 8. Plan de migración de datos v1 → v2

Como v1 ya está en producción (documentos reales existentes) y v2 nunca se desplegó, la migración es directa desde v1, sin pasar por el diseño intermedio con bugs conocidos:

1. **Formato de texto:** convertir `marks: [{type, value}, ...]` a un único objeto `style {...}` por nodo `text`.
2. **Nombres de propiedades:** renombrar `alignment` → `style.textAlign`; auditar cualquier otro nombre heterogéneo de v1 y normalizar a camelCase según este documento.
3. **Hipervínculos:** si v1 tenía alguna forma de link en el `text` (suelto o vía `marks`), convertir directamente al nodo `hyperlink` único de §4.6.B — nunca pasar por una forma intermedia de "link suelto".
4. **Resaltado:** si v1 tenía resaltado con hex libre, decidir por nodo si corresponde `highlight` (paleta cerrada, mapea a resaltado real de Word) o `backgroundShading` (hex libre, mapea a sombreado de carácter).
5. **Listas:** crear `numbering_definitions` a partir del comportamiento visual existente en v1 (nivel de indentación, tipo de viñeta) y asignar `numId` a cada lista.
6. **`section_type`:** aplicar solo a hijos directos de `document.children`; no propagar a bloques anidados en tablas/notas/listas.
7. **Tablas:** migrar estructura `table/table-row/table-cell` tal cual, verificando que el resolver de estilos implemente el recorrido de ancestros de §3 desde el primer día (no la fórmula de 4 niveles).
8. **Notas al pie:** si v1 las serializaba inline, migrar el generador para extraerlas a `footnotes.xml` desde el primer commit de v2.
9. **Reservar, sin migrar datos:** `image-inline` y `headers_footers` quedan disponibles en el esquema aunque v1 no tuviera contenido equivalente.
10. **Protocolo de sincronización:** no es una migración de datos existentes — es la capa nueva que se construye en paralelo al soporte de "documento completo", para que la primera versión de v2 ya nazca con ambos modos.

---

## 9. JSON Schema y CI

Este markdown es la especificación humana. Debe existir, en el mismo repositorio y actualizado en el mismo PR que cualquier cambio a este documento, un `document.schema.json` (JSON Schema Draft 2020-12+) que:

- Declare como `enum` cerrado: `highlight`, `script`, `textAlign`, `breakType`, y cualquier otro campo que en OOXML sea una paleta/lista cerrada.
- Declare unidades permitidas por campo (`fontSize` solo `pt`; `pageMargin.*` solo `in`/`cm`; `lineHeight` numérico sin unidad).
- Se ejecute en CI, en backend y frontend, antes de cualquier serialización a `.docx` o guardado en base de datos.

---

## 10. Checklist de validación

- [ ] Ningún nodo `text` en el corpus migrado tiene la propiedad `link`
- [ ] Ningún `style.highlight` contiene `#` (todo hex libre está en `backgroundShading`)
- [ ] El resolver de estilos tiene test con tabla de 3 niveles de anidamiento y estilos distintos en cada nivel
- [ ] Existe test de reinicio de numeración entre dos listas con `numId` distintos
- [ ] El protocolo de operaciones cubre las 6 operaciones de §5 con test
- [ ] Ningún bloque anidado en `table-cell`/`footnote`/`list-item` serializa `section_type`
- [ ] `document.schema.json` existe y valida el documento de ejemplo de §7
- [ ] El generador docx extrae `footnote.children` a `footnotes.xml`, no lo deja inline
- [ ] `image-inline` y `headers_footers` están declarados en el schema aunque no tengan render implementado aún
