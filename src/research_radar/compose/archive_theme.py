"""Static visual theme for the public research archive."""

ARCHIVE_CSS = """
:root {
  color-scheme: light;
  --ink: #18343a;
  --body: #2f4247;
  --muted: #4f6569;
  --accent: #2f766f;
  --accent-soft: #e9f1ef;
  --line: #d5dfdc;
  --paper: #ffffff;
  --ground: #f4f7f6;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--ground);
  color: var(--body);
  font: 16px/1.78 Georgia, "Times New Roman", serif;
  text-align: left;
}
a { color: #1f625d; text-decoration-thickness: 1px; text-underline-offset: 3px; }
a:hover { color: #164944; }
a:focus-visible, summary:focus-visible {
  outline: 3px solid #74a9a3;
  outline-offset: 3px;
}
img { display: block; max-width: 100%; height: auto; }
.rr-skip {
  position: absolute;
  left: 16px;
  top: -60px;
  z-index: 10;
  padding: 8px 12px;
  background: var(--ink);
  color: white;
}
.rr-skip:focus { top: 12px; }
.rr-site-header {
  border-bottom: 1px solid var(--line);
  background: rgba(244, 247, 246, 0.96);
}
.rr-site-bar {
  max-width: 1120px;
  min-height: 64px;
  margin: 0 auto;
  padding: 0 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
}
.rr-brand {
  color: var(--ink);
  font-size: 15px;
  font-weight: 750;
  letter-spacing: 0;
  text-decoration: none;
}
.rr-site-nav { display: flex; gap: 20px; font-size: 13px; }
.rr-site-nav a { color: var(--muted); text-decoration: none; }
.rr-home, .rr-report { max-width: 1120px; margin: 0 auto; padding: 46px 28px 72px; }
.rr-eyebrow, .rr-meta, .rr-stat, .rr-toc, figcaption, summary {
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
}
.rr-eyebrow {
  margin: 0 0 10px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}
h1, h2, h3, h4 { color: var(--ink); letter-spacing: 0; }
h1 { margin: 0; font-size: 48px; line-height: 1.08; }
h2 { margin: 0 0 20px; font-size: 30px; line-height: 1.2; }
h3 { margin: 0 0 12px; font-size: 24px; line-height: 1.28; }
h4 { margin: 30px 0 8px; font-size: 20px; line-height: 1.35; }
p { margin: 10px 0 16px; }
.rr-lede { max-width: 760px; margin-top: 16px; color: #50666a; font-size: 19px; line-height: 1.65; }
.rr-home-latest {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
  gap: 42px;
  align-items: center;
  padding: 20px 0 44px;
  border-bottom: 1px solid var(--line);
}
.rr-home-latest h1 { font-size: 42px; }
.rr-home-latest h1 a { color: var(--ink); text-decoration: none; }
.rr-home-latest.rr-no-media { grid-template-columns: minmax(0, 760px); }
.rr-home-latest-media {
  min-height: 260px;
  background: #e2ebe9;
  border: 1px solid #c7d5d2;
  overflow: hidden;
}
.rr-home-latest-media img {
  width: 100%; height: 100%; min-height: 260px; object-fit: contain; background: white;
}
.rr-stats { display: flex; flex-wrap: wrap; gap: 10px 20px; margin: 22px 0 0; }
.rr-stat { color: var(--muted); font-size: 13px; }
.rr-recent { padding-top: 38px; }
.rr-report-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 28px 36px; }
.rr-list-item { padding-top: 14px; border-top: 1px solid #9eb1ad; }
.rr-list-item:first-child { border-top: 3px solid var(--accent); }
.rr-list-item h2 { margin-bottom: 8px; font-size: 22px; }
.rr-list-item p { margin: 6px 0; }
.rr-meta { color: var(--muted); font-size: 13px; line-height: 1.5; }
.rr-report-hero { max-width: 850px; margin: 0 auto 42px; }
.rr-report-layout {
  display: grid;
  grid-template-columns: 180px minmax(0, 720px);
  gap: 42px;
  justify-content: center;
  align-items: start;
}
.rr-toc {
  position: sticky; top: 22px; border-top: 2px solid var(--ink);
  padding-top: 12px; font-size: 13px;
}
.rr-toc strong { color: var(--ink); }
.rr-toc ol { margin: 8px 0 0; padding: 0; list-style: none; }
.rr-toc li { margin: 7px 0; line-height: 1.45; }
.rr-toc a { color: var(--muted); text-decoration: none; }
.rr-mobile-toc { display: none; }
.rr-report-main { min-width: 0; }
.rr-section { margin: 0 0 52px; scroll-margin-top: 20px; }
.rr-section > h2 { padding-top: 16px; border-top: 1px solid var(--line); }
.rr-summary {
  padding: 18px 0; border-top: 3px solid var(--accent);
  border-bottom: 1px solid var(--line);
}
.rr-summary p { margin: 4px 0; }
.rr-deep { margin: 0 0 64px; padding-top: 18px; border-top: 4px solid var(--accent); }
.rr-deep + .rr-deep { margin-top: 72px; }
.rr-deep > h3 { font-size: 28px; }
.rr-deep > h3 a { color: var(--ink); }
.rr-figure { margin: 30px 0 34px; }
.rr-figure img { width: 100%; border: 1px solid var(--line); background: white; }
figcaption { margin-top: 10px; color: var(--muted); font-size: 13px; line-height: 1.55; }
.rr-figure-note { margin-top: 8px; color: #496065; font-size: 15px; }
.rr-diagram {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
  margin: 24px 0 30px;
  padding: 14px;
  border: 1px solid #c9d7d4;
  background: var(--accent-soft);
}
.rr-diagram h4 { grid-column: 1 / -1; margin: 0 0 4px; font-size: 16px; }
.rr-diagram span { min-width: 0; padding: 12px; background: white; font-size: 14px; }
.rr-diagram strong { display: block; margin-bottom: 4px; color: var(--ink); }
.rr-source-group { margin: 28px 0; }
.rr-source-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 26px; }
.rr-source { padding-top: 12px; border-top: 1px solid var(--line); }
.rr-source h4 { margin: 0 0 6px; font-size: 17px; }
.rr-source p { margin: 5px 0; font-size: 15px; }
.rr-seen { padding-left: 22px; }
.rr-seen li { margin: 8px 0; padding-left: 4px; }
details.rr-evidence, details.rr-reference-group {
  margin: 12px 0;
  padding: 12px 0;
  border-top: 1px solid var(--line);
}
summary { cursor: pointer; color: var(--ink); font-size: 14px; font-weight: 650; }
blockquote {
  margin: 16px 0; padding: 4px 0 4px 18px;
  border-left: 3px solid #94aaa6; color: #42585d;
}
blockquote p { margin: 7px 0; }
code, .rr-formula { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.rr-empty { padding: 32px 0; color: var(--muted); }
.rr-footer {
  max-width: 1120px;
  margin: 0 auto;
  padding: 24px 28px 42px;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font: 13px/1.6 -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
}
@media (max-width: 820px) {
  .rr-site-bar, .rr-home, .rr-report, .rr-footer { padding-left: 18px; padding-right: 18px; }
  .rr-site-bar { min-height: 56px; }
  .rr-site-nav { gap: 13px; }
  .rr-home, .rr-report { padding-top: 30px; }
  h1, .rr-home-latest h1 { font-size: 34px; }
  .rr-home-latest { grid-template-columns: 1fr; gap: 24px; }
  .rr-home-latest-media { min-height: 190px; }
  .rr-home-latest-media img { min-height: 190px; }
  .rr-report-list, .rr-source-list { grid-template-columns: 1fr; }
  .rr-report-layout { display: block; }
  .rr-toc { display: none; }
  .rr-mobile-toc {
    display: block; margin: 0 0 34px; padding: 12px 0;
    border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
  }
  .rr-mobile-toc ol { padding-left: 22px; }
  .rr-deep > h3 { font-size: 24px; }
  .rr-diagram { grid-template-columns: 1fr; }
}
"""
