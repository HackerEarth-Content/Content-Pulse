import { useMemo, useState } from "react";
import { PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer } from "recharts";
import { ApiError, api } from "../api";
import { Async, Banner, BarList, Card, SectionHeading, StatTile } from "../components/ui";
import { useApi } from "../hooks/useApi";
import type { Skill, SkillCategory, SkillGraphData, SkillRatings } from "../types";

const LEVEL_LABELS = ["", "Awareness", "Novice", "Practitioner", "Advanced", "Expert"];
const LEVEL_COLORS = ["var(--rating-1)", "var(--rating-2)", "var(--rating-3)", "var(--rating-4)", "var(--rating-5)"];
const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const CATEGORIES: { key: SkillCategory; label: string }[] = [
  { key: "tech", label: "Tech" },
  { key: "ai", label: "AI" },
  { key: "nontech", label: "Non-Tech" },
];

function LevelDot({ level, size = 14 }: { level: number; size?: number }) {
  return (
    <span
      style={{
        display: "inline-block", width: size, height: size, borderRadius: 4, flex: "none",
        background: level > 0 ? LEVEL_COLORS[level - 1] : "transparent",
        border: level > 0 ? "none" : "1px dashed var(--line)",
      }}
    />
  );
}

function LevelLegend() {
  return (
    <div className="skill-legend">
      {[1, 2, 3, 4, 5].map((l) => (
        <span key={l} className="skill-legend-item">
          <LevelDot level={l} size={10} />
          L{l} · {LEVEL_LABELS[l]}
        </span>
      ))}
    </div>
  );
}

function categoryAverages(skills: Skill[], ratings: SkillRatings) {
  return CATEGORIES.map((cat) => {
    const catSkills = skills.filter((s) => s.category === cat.key);
    // ponytail: unrated skills count as 0 in the denominator so averages reflect breadth, not just rated skills
    const avg = catSkills.length
      ? catSkills.reduce((sum, s) => sum + (ratings[s.id] ?? 0), 0) / catSkills.length
      : 0;
    return { subject: cat.label, value: Number(avg.toFixed(1)), fullMark: 5 };
  });
}

function CategoryRadar({ skills, ratings }: { skills: Skill[]; ratings: SkillRatings }) {
  const data = categoryAverages(skills, ratings);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <RadarChart data={data}>
        <PolarGrid stroke="var(--line)" />
        <PolarAngleAxis dataKey="subject" tick={{ fill: "var(--ink-3)", fontSize: 11 }} />
        <Radar dataKey="value" stroke="var(--accent-indigo)" fill="var(--accent-indigo)" fillOpacity={0.35} />
      </RadarChart>
    </ResponsiveContainer>
  );
}

/** A rated skill's full breakdown, one row per skill — used by both the
 * People tab (someone else's portfolio) and My Skills (your own, right
 * after saving). */
function Breakdown({ skills, ratings }: { skills: Skill[]; ratings: SkillRatings }) {
  const rated = skills
    .filter((s) => ratings[s.id] > 0)
    .map((s) => ({ ...s, level: ratings[s.id] }))
    .sort((a, b) => b.level - a.level);

  if (!rated.length) return <p className="hint">Nothing rated yet.</p>;

  return (
    <div className="skill-breakdown-list" style={{ display: "grid", gap: 6 }}>
      {rated.map((s) => (
        <div key={s.id} className="skill-row">
          <span className="skill-row-name">{s.name}</span>
          <div style={{ display: "flex", gap: 3 }}>
            {[1, 2, 3, 4, 5].map((l) => (
              <LevelDot key={l} level={l <= s.level ? l : 0} />
            ))}
          </div>
          <span className="hint">{LEVEL_LABELS[s.level]}</span>
        </div>
      ))}
    </div>
  );
}

function OverviewTab({ data }: { data: SkillGraphData }) {
  const [search, setSearch] = useState("");
  const { skills, members } = data;

  const catAverages = useMemo(() => {
    return CATEGORIES.map((cat) => {
      const catSkills = skills.filter((s) => s.category === cat.key);
      let sum = 0;
      const total = catSkills.length * members.length;
      members.forEach((m) =>
        catSkills.forEach((s) => {
          sum += m.ratings[s.id] ?? 0;
        })
      );
      return { ...cat, avg: total ? sum / total : 0 };
    });
  }, [skills, members]);

  const gaps = useMemo(() => {
    return skills
      .map((s) => ({ ...s, strong: members.filter((m) => (m.ratings[s.id] ?? 0) >= 4).length }))
      .filter((s) => s.strong <= 1)
      .sort((a, b) => a.strong - b.strong)
      .slice(0, 8);
  }, [skills, members]);

  const filteredSkills = skills.filter((s) => s.name.toLowerCase().includes(search.toLowerCase()));
  const activeExperts = members.filter((m) => skills.some((s) => (m.ratings[s.id] ?? 0) >= 4)).length;

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="stat-row stat-row--bare">
        {catAverages.map((c) => (
          <StatTile key={c.key} label={`${c.label} avg`} value={`${c.avg.toFixed(1)} / 5.0`} />
        ))}
        <StatTile label="Active experts" value={activeExperts} sub={`of ${members.length} rated`} />
        <StatTile label="Coverage gaps" value={gaps.length} sub="skills with ≤1 expert" />
      </div>

      {gaps.length ? (
        <Banner tone="warn">
          <strong>Bus-factor watch</strong> — fewer than 2 people at Advanced or above:
          <div className="skill-legend" style={{ marginTop: 8 }}>
            {gaps.map((g) => (
              <span key={g.id} className="pill pill-muted">
                {g.name} <span className="hint">· {g.strong} expert{g.strong !== 1 ? "s" : ""}</span>
              </span>
            ))}
          </div>
        </Banner>
      ) : null}

      <Card title="Skill Distribution Matrix" action={<LevelLegend />}>
        <input
          className="field"
          style={{ maxWidth: 220, marginBottom: 10 }}
          placeholder="Filter skills..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th style={{ width: "35%" }}>Skill</th>
                <th style={{ width: "15%" }}>Score</th>
                <th style={{ width: "50%" }}>Distribution heatmap</th>
              </tr>
            </thead>
            <tbody>
              {filteredSkills.map((s) => {
                const counts = [1, 2, 3, 4, 5].map(
                  (l) => members.filter((m) => (m.ratings[s.id] ?? 0) === l).length
                );
                const rated = counts.reduce((a, b) => a + b, 0);
                const score = rated
                  ? counts.reduce((sum, c, i) => sum + c * (i + 1), 0) / members.length
                  : 0;
                const peak = Math.max(1, ...counts);
                return (
                  <tr key={s.id}>
                    <td className="strong">{s.name}</td>
                    <td>
                      {rated ? (
                        <span className="heatmap-score" style={{ color: LEVEL_COLORS[Math.round(score) - 1] }}>
                          {score.toFixed(1)}
                        </span>
                      ) : (
                        <span className="hint">—</span>
                      )}
                    </td>
                    <td>
                      <div className="heatmap-row">
                        {counts.map((c, i) => (
                          <div
                            key={i}
                            className="heatmap-bar"
                            title={`L${i + 1} · ${LEVEL_LABELS[i + 1]}: ${c}`}
                            style={{ height: `${(c / peak) * 100}%`, background: LEVEL_COLORS[i] }}
                          />
                        ))}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function PeopleTab({ data }: { data: SkillGraphData }) {
  const { skills, members } = data;
  const [memberId, setMemberId] = useState(members[0]?.member_id);
  const member = members.find((m) => m.member_id === memberId) ?? members[0];
  if (!member) return <p className="hint">No one has rated any skills yet.</p>;

  const rated = skills.filter((s) => member.ratings[s.id] > 0);
  const strengths = rated.filter((s) => member.ratings[s.id] >= 4);
  const growth = rated.filter((s) => member.ratings[s.id] <= 2);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="skill-legend">
        {members.map((m) => (
          <button
            key={m.member_id}
            className={`pill pill-button ${m.member_id === member.member_id ? "" : "pill-muted"}`}
            onClick={() => setMemberId(m.member_id)}
          >
            {m.display_name.split(" ")[0]}
          </button>
        ))}
      </div>

      <div className="grid cols-2">
        <Card title="Category shape">
          <div style={{ height: 320 }}>
            <CategoryRadar skills={skills} ratings={member.ratings} />
          </div>
        </Card>
        <Card title={`${member.display_name} — ${rated.length} skills rated`} sub={member.role}>
          <p className="section-sub">Strengths (L4+)</p>
          <div className="skill-legend" style={{ marginBottom: 10 }}>
            {strengths.length
              ? strengths.map((s) => (
                  <span key={s.id} className="pill pill-muted">
                    <LevelDot level={member.ratings[s.id]} size={10} /> {s.name}
                  </span>
                ))
              : <span className="hint">None yet</span>}
          </div>
          <p className="section-sub">Growth areas (L1–L2)</p>
          <div className="skill-legend">
            {growth.length
              ? growth.map((s) => (
                  <span key={s.id} className="pill pill-muted">
                    <LevelDot level={member.ratings[s.id]} size={10} /> {s.name}
                  </span>
                ))
              : <span className="hint">None</span>}
          </div>
        </Card>
      </div>

      <Card title="Full breakdown">
        <Breakdown skills={skills} ratings={member.ratings} />
      </Card>
    </div>
  );
}

function SkillsTab({ data }: { data: SkillGraphData }) {
  const { skills, members } = data;
  const [cat, setCat] = useState<SkillCategory | "all">("all");
  const visible = skills.filter((s) => cat === "all" || s.category === cat);
  const [skillId, setSkillId] = useState(visible[0]?.id);
  const skill = skills.find((s) => s.id === skillId) ?? visible[0];
  if (!skill) return <p className="hint">No skills in the catalogue.</p>;

  const distribution = [1, 2, 3, 4, 5].map((l) => ({
    label: `L${l} · ${LEVEL_LABELS[l]}`,
    value: members.filter((m) => (m.ratings[skill.id] ?? 0) === l).length,
    color: LEVEL_COLORS[l - 1],
  }));
  const experts = members
    .filter((m) => (m.ratings[skill.id] ?? 0) >= 4)
    .sort((a, b) => b.ratings[skill.id] - a.ratings[skill.id]);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="skill-legend">
        {(["all", ...CATEGORIES.map((c) => c.key)] as const).map((k) => (
          <button
            key={k}
            className={`pill pill-button ${cat === k ? "" : "pill-muted"}`}
            onClick={() => setCat(k)}
          >
            {k === "all" ? "All" : CATEGORIES.find((c) => c.key === k)!.label}
          </button>
        ))}
      </div>
      <div className="skill-legend">
        {visible.map((s) => (
          <button
            key={s.id}
            className={`pill pill-button ${s.id === skill.id ? "" : "pill-muted"}`}
            onClick={() => setSkillId(s.id)}
          >
            {s.name}
          </button>
        ))}
      </div>

      <div className="grid cols-2">
        <Card title={`${skill.name} — level distribution`}>
          <div className="skill-distribution">
            <BarList items={distribution} max={Math.max(1, members.length)} />
          </div>
        </Card>
        <Card title="Who to ask (L4+)">
          {experts.length ? (
            <div style={{ display: "grid", gap: 8 }}>
              {experts.map((m) => (
                <div key={m.member_id} className="skill-row">
                  <span>{m.display_name}</span>
                  <LevelDot level={m.ratings[skill.id]} />
                  <span className="hint">L{m.ratings[skill.id]}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="hint">No one at Advanced or above yet.</p>
          )}
        </Card>
      </div>
    </div>
  );
}

function MySkillsTab({ me }: { me: { id: number; display_name: string; role: string } }) {
  const skills = useApi(() => api.skills(), []);
  const win = useApi(() => api.skillWindow(), []);
  const mine = useApi(() => api.mySkillRatings(), []);
  const [draft, setDraft] = useState<SkillRatings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);

  const ratings = draft ?? mine.data ?? {};

  function setLevel(skillId: number, level: number) {
    setSaved(false);
    setDraft({ ...ratings, [skillId]: level });
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const entries = Object.entries(ratings).map(([skill_id, level]) => ({
        skill_id: Number(skill_id), level,
      }));
      const result = await api.saveMySkillRatings(entries);
      setDraft(result);
      setSaved(true);
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Async loading={skills.loading || win.loading || mine.loading}
           error={skills.error || win.error || mine.error}
           data={skills.data}>
      {(skillList) => {
        const isOpen = win.data?.open ?? true;
        const openDays = (win.data?.open_weekdays ?? []).map((d) => WEEKDAY_LABELS[d]).join(", ");

        return (
          <div style={{ display: "grid", gap: 16 }}>
            {!isOpen ? (
              <Banner tone="warn">
                Skill entry isn't open today — an admin has set it to {openDays || "no days"}.
                You can still see your saved scores below.
              </Banner>
            ) : null}
            {error ? <Banner tone="error">{error.message}</Banner> : null}
            {saved ? <Banner tone="info">Saved.</Banner> : null}

            <Card title="What the levels mean">
              <LevelLegend />
            </Card>

            {CATEGORIES.map((cat) => (
              <Card key={cat.key} title={cat.label}>
                <div style={{ display: "grid", gap: 10 }}>
                  {skillList.filter((s) => s.category === cat.key).map((s) => {
                    const level = ratings[s.id] ?? 0;
                    return (
                      <div key={s.id} className="skill-entry-row">
                        <span className="skill-row-name">{s.name}</span>
                        <div className="skill-level-picker">
                          {[1, 2, 3, 4, 5].map((l) => (
                            <button
                              key={l}
                              className="skill-level-btn"
                              disabled={!isOpen}
                              aria-pressed={level === l}
                              onClick={() => setLevel(s.id, l)}
                              title={`L${l} · ${LEVEL_LABELS[l]}`}
                              style={
                                level === l
                                  ? { background: LEVEL_COLORS[l - 1], color: "#fff", borderColor: "transparent" }
                                  : undefined
                              }
                            >
                              {l}
                            </button>
                          ))}
                          <button
                            className="skill-clear-btn"
                            disabled={!isOpen || !level}
                            onClick={() => setLevel(s.id, 0)}
                            title="Clear this rating"
                          >
                            Clear
                          </button>
                        </div>
                        <span className="hint skill-level-caption">
                          {level ? `L${level} · ${LEVEL_LABELS[level]}` : "Not rated"}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </Card>
            ))}

            <button className="btn btn-primary" disabled={busy || !isOpen} onClick={save}>
              {busy ? "Saving…" : "Save my scores"}
            </button>

            <Card title={`${me.display_name}'s portfolio`}>
              <div className="grid cols-2">
                <div style={{ height: 320 }}>
                  <CategoryRadar skills={skillList} ratings={ratings} />
                </div>
                <Breakdown skills={skillList} ratings={ratings} />
              </div>
            </Card>
          </div>
        );
      }}
    </Async>
  );
}

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "people", label: "People" },
  { key: "skills", label: "Skills" },
  { key: "my-skills", label: "My Skills" },
] as const;
type Tab = (typeof TABS)[number]["key"];

export function SkillGraph({ me }: { me: { id: number; display_name: string; role: string } | null }) {
  const [tab, setTab] = useState<Tab>("overview");
  const graph = useApi(() => api.skillGraph(), []);

  return (
    <>
      <SectionHeading title="Skill Graph" color="var(--accent-indigo)" />

      <div className="nav drilldown-tabs" role="tablist" aria-label="Skill graph views">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            className={`nav-link${tab === t.key ? " active" : ""}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "my-skills" ? (
        me ? <MySkillsTab me={me} /> : (
          <Banner tone="warn">Your account isn't linked to a team member yet.</Banner>
        )
      ) : (
        <Async loading={graph.loading} error={graph.error} data={graph.data}
               empty={{ title: "No skills rated yet" }}>
          {(data) => (
            <>
              {tab === "overview" ? <OverviewTab data={data} /> : null}
              {tab === "people" ? <PeopleTab data={data} /> : null}
              {tab === "skills" ? <SkillsTab data={data} /> : null}
            </>
          )}
        </Async>
      )}
    </>
  );
}
