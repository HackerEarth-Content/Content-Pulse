import { Link } from "react-router-dom";
import { SectionHeading } from "../components/ui";

interface UtilTool {
  to: string;
  title: string;
  blurb: string;
  icon: JSX.Element;
}

const icon = (d: string) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" width="26" height="26">
    <path d={d} />
  </svg>
);

const TOOLS: UtilTool[] = [
  {
    to: "/utils/mcq-reviewer",
    title: "MCQ Reviewer",
    blurb: "Upload a bulk MCQ workbook and get an AI-reviewed quality report — ambiguity, distractor quality, complexity match, and skill-tag coverage.",
    icon: icon("M9 12l2 2 4-4M12 3a9 9 0 100 18 9 9 0 000-18z"),
  },
  {
    to: "/utils/taxonomy",
    title: "Skill Taxonomy",
    blurb: "Manage the master skill/topic tag list the Utils checks question tags against.",
    icon: icon("M4 6h16M4 12h10M4 18h7"),
  },
  {
    to: "/utils/event-review",
    title: "Event Question Review",
    blurb: "Paste an event URL, see which library questions still need review, and track L1/L2 sign-off.",
    icon: icon("M11 19a8 8 0 100-16 8 8 0 000 16zM21 21l-4.35-4.35"),
  },
];

/** Landing page for the Utils tab — a small, growing set of setter tools.
 * Each card is a plain link, so a tool's own screen owns the back button and
 * the browser's normal history rather than living behind a modal. */
export function Utils() {
  return (
    <>
      <SectionHeading title="Utils" color="var(--accent-indigo)" />
      <p className="tab-blurb">Tools for setter</p>

      <div className="grid cols-3 reveal-stagger">
        {TOOLS.map((tool) => (
          <Link key={tool.title} to={tool.to} className="card util-card" title={tool.title}>
            <span className="util-card-icon">{tool.icon}</span>
            <span className="card-title">{tool.title}</span>
            <span className="card-sub">{tool.blurb}</span>
          </Link>
        ))}

        <div className="card util-card util-card-soon" aria-disabled>
          <span className="util-card-icon">{icon("M12 8v4l3 3M12 3a9 9 0 100 18 9 9 0 000-18z")}</span>
          <span className="card-title">More on the way</span>
          <span className="card-sub">Additional setter utilities land here as they're built.</span>
        </div>
      </div>
    </>
  );
}
