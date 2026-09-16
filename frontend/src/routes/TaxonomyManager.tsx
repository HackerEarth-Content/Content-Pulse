import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api";
import { Async, Banner } from "../components/ui";
import { useApi } from "../hooks/useApi";

/** Utils > Skill Taxonomy — the master (category, tag) list the MCQ
 * Reviewer's Skill Tag Coverage check reads live from the DB. An edit here
 * applies to the very next review, no deploy needed. */
export function TaxonomyManager() {
  const groups = useApi(() => api.taxonomy(), []);
  const [category, setCategory] = useState("");
  const [tag, setTag] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function add() {
    if (!category.trim() || !tag.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await api.addTaxonomyTag(category.trim(), tag.trim());
      setTag("");
      groups.reload();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: number, label: string) {
    if (!confirm(`Remove "${label}"?`)) return;
    setError(null);
    try {
      await api.removeTaxonomyTag(id);
      groups.reload();
    } catch (e) {
      setError(e as ApiError);
    }
  }

  return (
    <>
      <div className="util-page-head">
        <Link className="btn btn-secondary" to="/utils">← Back</Link>
        <span className="util-page-title">Skill Taxonomy</span>
      </div>
      <p className="tab-blurb">
        Add or remove tags from the taxonomy the MCQ Reviewer checks Skill/topic tags against.
      </p>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-title">Add a tag</div>
        <div className="btn-row" style={{ marginTop: 8, flexWrap: "wrap" }}>
          <input
            className="field" placeholder="Category (e.g. Programming Languages)"
            aria-label="Category"
            value={category} onChange={(e) => setCategory(e.target.value)}
            style={{ minWidth: 240 }}
          />
          <input
            className="field" placeholder="Tag (e.g. Rust)"
            aria-label="Tag"
            value={tag} onChange={(e) => setTag(e.target.value)}
            style={{ minWidth: 160 }}
          />
          <button className="btn btn-primary" disabled={saving || !category.trim() || !tag.trim()} onClick={add}>
            {saving ? "Adding…" : "+ Add tag"}
          </button>
        </div>
        {error ? <Banner tone="error">{error.message}</Banner> : null}
      </div>

      <Async
        loading={groups.loading}
        error={groups.error}
        data={groups.data}
        empty={{ title: "No taxonomy tags yet", hint: "Add the first one above." }}
      >
        {(items) => (
          <div className="reveal-stagger" style={{ display: "grid", gap: 12 }}>
            {items.map((g) => (
              <div className="card" key={g.category}>
                <div className="card-title">{g.category}</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                  {g.tags.map((t) => (
                    <span key={t.id} className="pill" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                      {t.tag}
                      <button
                        className="btn-icon" title={`Remove ${t.tag}`} aria-label={`Remove ${t.tag}`}
                        onClick={() => remove(t.id, t.tag)}
                      >
                        ✕
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Async>
    </>
  );
}
