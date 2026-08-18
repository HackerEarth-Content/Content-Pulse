/** Bold / italic / bullet-list only, backed by `document.execCommand` — a
 * three-button toolbar doesn't earn a rich-text library dependency.
 *
 * `execCommand` output (and worse, a paste) can carry arbitrary markup —
 * `<script>`, `onerror=`, `style="expression(...)"` — and this content is
 * shown to *other* people (a lead viewing someone else's weekly plan), so it
 * has to be sanitized before it's stored and again before it's rendered.
 * `DOMParser` never executes scripts or loads resources, so walking its
 * output is safe; only tags on the allow-list survive, and every attribute
 * is stripped from what's left (no href, no style, no on* handlers). */

const ALLOWED_TAGS = new Set(["B", "STRONG", "I", "EM", "UL", "OL", "LI", "BR", "DIV", "P", "SPAN"]);

export function sanitizeHtml(html: string): string {
  const doc = new DOMParser().parseFromString(html || "", "text/html");

  const walk = (node: Node) => {
    for (const child of Array.from(node.childNodes)) {
      if (child.nodeType === Node.ELEMENT_NODE) {
        const el = child as HTMLElement;
        // Sanitize descendants FIRST, before deciding whether `el` itself
        // survives. Unwrapping an element hoists its children into the
        // parent — if those children hadn't been sanitized yet, a nested
        // disallowed tag (`<svg><img onerror=...></svg>`) would ride out on
        // the hoist, since the child snapshot above was taken before any
        // mutation and a later sibling pass never revisits it.
        walk(el);
        if (!ALLOWED_TAGS.has(el.tagName)) {
          const parent = el.parentNode;
          if (parent) {
            while (el.firstChild) parent.insertBefore(el.firstChild, el);
            parent.removeChild(el);
          }
          continue;
        }
        for (const attr of Array.from(el.attributes)) el.removeAttribute(attr.name);
      } else if (child.nodeType !== Node.TEXT_NODE) {
        child.parentNode?.removeChild(child);
      }
    }
  };
  walk(doc.body);
  return doc.body.innerHTML;
}

/** True once sanitization strips it down to nothing (or it never had text). */
export function isBlankHtml(html: string): boolean {
  const doc = new DOMParser().parseFromString(html || "", "text/html");
  return !(doc.body.textContent ?? "").trim();
}
