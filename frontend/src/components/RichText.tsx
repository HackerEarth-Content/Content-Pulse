import { useEffect, useRef } from "react";
import { sanitizeHtml } from "../richtext";

/** Bold / italic / bullet list, nothing else — see richtext.ts for why this
 * isn't a rich-text library and why its output is sanitized both ways. */
export function RichText({
  value, onChange, readOnly, placeholder,
}: {
  value: string;
  onChange?: (html: string) => void;
  readOnly?: boolean;
  placeholder?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  // Only push an external value in when the user isn't actively editing —
  // otherwise every keystroke's onChange -> value round-trip fights the
  // caret position and the cursor jumps to the start on each character.
  useEffect(() => {
    const el = ref.current;
    if (!el || document.activeElement === el) return;
    const clean = sanitizeHtml(value);
    if (el.innerHTML !== clean) el.innerHTML = clean;
  }, [value]);

  if (readOnly) {
    const clean = sanitizeHtml(value);
    return clean ? (
      <div className="richtext-readonly" dangerouslySetInnerHTML={{ __html: clean }} />
    ) : (
      <span className="muted">—</span>
    );
  }

  const exec = (command: string) => document.execCommand(command);

  return (
    <div className="richtext-field">
      <div className="richtext-toolbar">
        <button type="button" onMouseDown={(e) => e.preventDefault()}
                onClick={() => exec("bold")} aria-label="Bold" title="Bold">
          <strong>B</strong>
        </button>
        <button type="button" onMouseDown={(e) => e.preventDefault()}
                onClick={() => exec("italic")} aria-label="Italic" title="Italic">
          <em>i</em>
        </button>
        <button type="button" onMouseDown={(e) => e.preventDefault()}
                onClick={() => exec("insertUnorderedList")} aria-label="Bullet list" title="Bullet list">
          •&nbsp;list
        </button>
      </div>
      <div
        ref={ref}
        className="field richtext"
        contentEditable
        data-placeholder={placeholder}
        onInput={(e) => onChange?.(sanitizeHtml(e.currentTarget.innerHTML))}
        suppressContentEditableWarning
      />
    </div>
  );
}
