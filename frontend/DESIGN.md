# PROJECT TERRA — Frontend Design System Specification

> **Source of Truth**: Extracted from the Figma design file `Project-Terra` (`FwvCycGFxG7gIlk4WOa6QL`), covering `02 · Brand identity` (`5:513`), `PROJECT TERRA · Earth intelligence` (`5:110`), `TERRA · Ecosystem comparison` (`14:2`), `TERRA · Analytical UI components` (`14:11`), responsive comparison views (`14:2713` at 1024 px, `14:2714` at 390 px), and analytical state frames (`14:7465`, `14:7570`, `14:7649`, `14:7726`).
>
> All documented tokens and rules reflect values explicitly defined in Figma. Design parameters that are not yet defined in Figma are marked as **[Unresolved in Figma]** with their interim engineering fallback.

---

## 1. Brand Identity & Visual Direction

### Brand Positioning
- **Identity Theme**: *The Connected Planet — Earth systems. In perspective.*
- **Taglines**:
  - Primary: `EARTH SYSTEM INTELLIGENCE` / `Earth intelligence`
  - Secondary: `A precise identity for planetary intelligence. Orbital motion meets layered Earth systems.`
  - Context: `NASA SPACE APPS CHALLENGE 2026` · `Orbital path / Contour layers / Connected systems`

### Logo & Symbol Lockups
The brand mark is the **Terra orbital contour symbol** (`terra-symbol`), pairing an orbital path with layered terrestrial contours. Six official lockups are specified in `02 · Brand identity` (`5:514`):

1. **Primary Lockup (`01 / PRIMARY LOCKUP`)**:
   - **Symbol**: Terra teal (`#159B91`) orbital contour mark.
   - **Overline**: `PROJECT` in `Inter Medium`, uppercase, letter-spacing `0.24em` (`1.77px` at `7.36px` / `1.4px` at `7px` in navbar), Deep slate (`#192F3A`) or muted slate (`#73858D`).
   - **Wordmark**: `TERRA` in `Inter Semi Bold`, Deep slate (`#192F3A`), tight tracking (`-0.04em`).
   - **Surface**: Light field (`#F3F7F8` or `#FFFFFF`).
2. **Reverse Lockup (`02 / REVERSE LOCKUP`)**:
   - One-color white (`#FFFFFF`) symbol and wordmark on a Deep slate (`#192F3A`) field, with `#A8C0C7` secondary metadata text.
3. **Compact Wordmark (`03 / COMPACT WORDMARK`)**:
   - Standalone `TERRA` wordmark (`Inter Semi Bold`, `#192F3A`, tracking `-0.04em`) for narrow navigation and editorial contexts.
4. **Icon-Only (`04 / ICON-ONLY`)**:
   - Standalone `#159B91` symbol (`36×36 px` in navigation headers, `28×28 px` in compact headers).
5. **Monochrome (`05 / MONOCHROME`)**:
   - Single-ink Deep slate (`#192F3A`) symbol and wordmark for print and scientific reports.
6. **Favicon (`06 / FAVICON`)**:
   - `32 px` container: `#159B91` rounded square (`border-radius: 11px` at 48 px preview) with white symbol.
   - `16 px` container: `#192F3A` rounded square (`border-radius: 5px` at 22 px preview) with white symbol.

---

## 2. Design Philosophy & Visual Principles

1. **Scientific Clarity Over Decoration**: High-contrast light surfaces (`#FCFDFE`, `#FFFFFF`, `#F3F7F8`) prioritize legibility of dense statistical tables, confidence intervals, and multi-layer cartography.
2. **Explicit Provenance & Epistemic Humility**:
   - Every chart, map, and metric card surfaces its statistical method (e.g., `OLS · Seasonally adjusted`, `Seasonal Mann–Kendall + Sen’s slope`), baseline window (`Baseline 2001–2010`), sample coverage (`96.8% · 300 months · Quality screened`), and data product (`NASA MODIS Terra / MOD11C3`).
   - Synthetic or illustrative datasets are explicitly badged (`Example data`, `SYNTHETIC DATA · Research demonstration`, `Concept demonstration · Not for operational decisions`).
   - Correlation findings explicitly state `Correlation does not establish causation` (`α = 0.05 · No causal attribution`).
3. **Consistent Region Identity**:
   - **Primary / Region A**: Terra teal (`#159B91`).
   - **Comparison / Region B**: Signal blue (`#3193CE`).
   - **Warming / Positive Thermal Anomaly / Stress**: Trend coral (`#C77F6D`).
4. **Refined Glass & Hairline Framing**:
   - Floating map overlays use translucent white (`rgba(255, 255, 255, 0.93)`) with `backdrop-filter: blur(10px)` and subtle slate-tinted borders (`#DFE9EC`, `#E3EBEE`).

---

## 3. Color Palette & Semantic Color Tokens

### 3.1 Core Brand Swatches (`02 · Brand identity`)

| Swatch Name | Hex | RGB | Role |
|---|---|---|---|
| **Cloud** | `#FCFDFE` | `rgb(252, 253, 254)` | Primary page canvas and analytics workspace background |
| **Mist** | `#F3F7F8` | `rgb(243, 247, 248)` | Secondary surface, search input fill, timeline bar, neutral pills |
| **Deep slate** | `#192F3A` | `rgb(25, 47, 58)` | Primary ink, headings, high-emphasis numerals, dark lockup surface |
| **Terra teal** | `#159B91` | `rgb(21, 155, 145)` | Brand accent, primary interactive fill, active tab indicator, Region A series |
| **Signal blue** | `#3193CE` | `rgb(49, 147, 206)` | Secondary analytical accent, cooling scale pole, Region B series |
| **Trend coral** | `#C77F6D` | `rgb(199, 127, 109)` | Warming trend indicator, negative NDVI correlation pole |

### 3.2 Extended UI & Semantic Tokens (Extracted from UI Frames)

```css
:root {
  /* Canvas & Surfaces */
  --color-bg-canvas: #fcfdfe;
  --color-bg-surface: #ffffff;
  --color-bg-mist: #f3f7f8;
  --color-bg-observatory: #f0f5f6;
  --color-bg-glass: rgba(255, 255, 255, 0.93);
  --color-bg-inverse: #192f3a;

  /* Brand & Analytical Accents */
  --color-brand-teal: #159b91;
  --color-brand-teal-hover: #12877e; /* [Unresolved in Figma] Derived 8% darken for hover */
  --color-signal-blue: #3193ce;
  --color-trend-coral: #c77f6d;

  /* Tinted Accent Surfaces */
  --color-teal-subtle: #eff8f7;
  --color-teal-badge: #eff7f6;
  --color-teal-insight-bg: #f1f8f7;
  --color-teal-insight-pill: #e2f0ed;
  --color-teal-active-tool: #edf7f5;
  --color-blue-subtle: #eef6fb;

  /* Text & Ink Hierarchy */
  --color-text-primary: #192f3a;
  --color-text-secondary: #536e77;
  --color-text-muted: #637983;
  --color-text-subtle: #73858d;
  --color-text-map-label: #91a3ab;
  --color-text-disabled: #91a3aa;
  --color-text-on-dark: #ffffff;
  --color-text-on-dark-muted: #a8c0c7;

  /* Borders & Dividers */
  --color-border-subtle: #e3ebee;
  --color-border-default: #dde7eb;
  --color-border-card: #dee7ea;
  --color-border-control: #d7e2e6;
  --color-border-glass: #dfe9ec;
  --color-border-teal: #cce7e3;
  --color-border-teal-insight: #d8eae7;
  --color-border-teal-divider: #d6e8e4;

  /* Semantic Status & Diagnostics */
  --color-status-success-bg: #eaf5f1;
  --color-status-success-text: #177965;
  --color-status-warning-bg: #faf7ef;
  --color-status-warning-pill: #f8f0e0;
  --color-status-warning-border: #e5dabe;
  --color-status-warning-text: #8a672f;
  --color-status-error-bg: #fbf6f3;
  --color-status-error-border: #e9d5cb;
  --color-status-error-text: #a45f4d;

  /* Track & Control Fills */
  --color-track-neutral: #ebf0f2;
  --color-control-disabled-bg: #e8eef0;
}
```

---

## 4. Typography

### Font Family
- **Primary Typeface**: `'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`
- **Weights Used in Figma**:
  - `400` (Regular)
  - `500` (Medium)
  - `600` (Semi Bold)
- **Numeric Formatting**: Tabular numerals (`font-variant-numeric: tabular-nums`) for statistical tables, coordinates, p-values, and timeline bounds.

### Typographic Scale & Hierarchy

| Style Role | Size | Weight | Tracking | Color | Figma Source Example |
|---|---|---|---|---|---|
| **Brand Hero Display** | `68px` | `600` | `-2.72px` (`-0.04em`) | `#192F3A` | `5:528` (`TERRA` brand sheet) |
| **Editorial Display** | `49px` | `500` | `0` | `#192F3A` | `5:525` (`Earth systems. In perspective.`) |
| **Workspace State Title** | `28px` | `600` | `0` | `#192F3A` | `14:7631` (`Preparing matched observations`) |
| **Page / Section Header** | `24px` | `500`–`600` | `0` | `#192F3A` | `5:219` (`A warming planet, in focus.`) |
| **KPI Metric Value (Large)** | `25px` | `500` | `0` | `#192F3A` | `5:285` (`+0.26`, `p < 0.001`, `96.8`) |
| **KPI Metric Value (Range)** | `22px` | `500` | `0` | `#192F3A` | `5:290` (`0.22 — 0.30`) |
| **TRI Score Display** | `35px` | `600` | `0` | `#159B91` / `#3193CE` | `14:2631` (`65.1`, `80.9`) |
| **Wordmark (Navbar)** | `20px`–`23px` | `600` | `0` | `#192F3A` | `5:121` (`23px`), `14:54` (`20px`) |
| **Map Callout Value** | `17px` | `500` | `0` | `#192F3A` | `5:238` (`+0.31°C / decade`) |
| **Workspace Bar Title** | `15px` | `600` | `0` | `#192F3A` | `5:269` (`Analysis workspace`) |
| **Insight Headline / Panel Title** | `14px` | `600` | `0` | `#192F3A` | `5:391` (`A persistent warming signal`) |
| **Navigation Link / Section Subhead** | `12px`–`13px` | `400`–`600` | `0` | `#192F3A` / `#536D77` | `5:125` (`13px`), `14:56` (`12px`) |
| **Card Title** | `12px`–`13px` | `600` | `0` | `#192F3A` | `5:303` (`Land surface temperature anomaly`) |
| **Body / Control Value** | `11px`–`12px` | `400`–`500` | `0` | `#192F3A` / `#536E77` | `5:392`, `5:173`, `14:21` |
| **Section Overline / Eyebrow** | `9px`–`10px` | `600` | `1.0px`–`1.08px` | `#73858D` / `#159B91` | `5:147` (`DATA EXPLORER`), `5:218` (`EARTH OBSERVATORY`) |
| **KPI Card Eyebrow** | `8px` | `600` | `0.4px` | `#73858D` | `5:284` (`WARMING TREND`) |
| **Table / Axis / Provenance Caption** | `8px`–`9px` | `400`–`500` | `0` | `#73858D` / `#637983` | `5:304`, `5:511`, `5:348` |

---

## 5. Spacing System & Layout Grid

### Base Spatial Unit
- **8 px Spacing System** (explicitly noted in `14:11`: `Reusable local components · Inter · 8 px spacing system`), supplemented by `4px`, `6px`, `10px`, `12px`, `14px`, `16px`, `20px`, `24px`, `32px`, and `48px` increments.

### Viewport Canvases & Structural Grids
1. **Homepage (`PROJECT TERRA · Earth intelligence`, `5:110`) — `1440 × 1000 px`**:
   - **Top Navigation Bar**: `1440 × 72 px`, `24px` horizontal padding, `1px` bottom border (`#E3EBEE`).
   - **Earth Observatory Stage**: `1440 × 504 px` (`#F0F5F6` background):
     - Left floating **Dataset Explorer** card: `264 × 456 px` at `left: 24px, top: 22px`.
     - Central **Natural Earth Map Canvas**: `1055 × 405 px` at `left: 300px, top: 78px`.
     - Right floating **Map Tools** bar: `50 × 264 px` at `right: 26px (left: 1364px), top: 22px`.
     - Bottom-right **Trend Color Legend**: `316 × 61 px` at `left: 1012px, top: 418px`.
   - **Analytics Workspace**: `1440 × 424 px` (`#FCFDFE` background, `24px` horizontal margin):
     - **KPI Row**: 4 equal cards of `336 × 80 px` with `16px` horizontal gap (`336 * 4 + 16 * 3 = 1392 px`, spanning `left: 24px` to `1416px`).
     - **Charts & Insights Row**: `top: 154px`, height `196 px`, `14px` horizontal gap:
       - Time-series card: `678 × 196 px`
       - Correlation matrix card: `294 × 196 px`
       - Terra intelligence card: `390 × 196 px`
     - **Timeline Controls Bar**: `1390 × 40 px` at `top: 362px, left: 24px`.
     - **Provenance Footer Line**: `top: 410px`, `8px` caption text on left and right.

2. **Analytical Comparison Workspace (`TERRA · Ecosystem comparison`, `14:2`) — `1600 × 1200 px`**:
   - **Top Navigation Bar**: `1600 × 64 px`, `20px` horizontal padding, `1px` bottom border (`#DDE7EB`).
   - **Analysis Context Header**: `1600 × 86 px`.
   - **3-Column Analytical Layout** (`20px` outer margin, `16px` column gap):
     - Left Configuration Rail: `252 px` fixed width (`14:5`).
     - Center Analytical Stack: `1000 px` width (`Geospatial comparison` `410px`, `Temporal analysis` `260px`, `Statistical analysis` `142px`, `16px` vertical gaps).
     - Right Resilience Assessment Rail: `276 px` width (`14:9`).
     - Bottom Data Provenance Table: `1292 × 166 px` spanning center + right columns (`1000 + 16 + 276 = 1292 px`).

---

## 6. Border Radii, Shadows & Elevation

### Border Radii
- `--radius-xs: 2px` — Progress tracks, range slider handles (`6×28 px`), scale bars.
- `--radius-sm: 3px` — Correlation heatmap cells (`47×21 px`), checkbox indicators (`16×16 px`), legend gradient bar.
- `--radius-md: 5px`–`6px` — Buttons (`36px` height), form fields, status badges, keyboard shortcut badge (`4px`), AI badge (`5px`).
- `--radius-lg: 7px`–`8px` — Search bar (`8px`), dataset card (`8px`), selector controls (`7px`), timeline bar (`8px`).
- `--radius-xl: 10px` — KPI cards, chart panels, provenance cards, map callout preview, legend card.
- `--radius-2xl: 12px`–`14px` — Floating glass Dataset Explorer (`14px`), map tools bar (`12px`), brand showcase cards (`12px`–`14px`).
- `--radius-pill: 16px`–`18px` — Observation period pill (`16px` on `32px` height), account menu pill (`18px` on `36px` height), region badge (`12px` on `24px` height).

### Shadows & Backdrop Filters
- **Floating Glass Panel (`Dataset explorer`, `5:146`)**:
  - `background: rgba(255, 255, 255, 0.93)`
  - `backdrop-filter: blur(10px)`
  - `border: 1px solid #DFE9EC`
  - `box-shadow: 0px 6px 24px 0px rgba(26, 51, 59, 0.07)`
- **Map Region Callout (`Amazon trend preview`, `5:236`)**:
  - `background: #FFFFFF`
  - `border: 1px solid #D8E6E7`
  - `box-shadow: 0px 4px 16px 0px rgba(26, 51, 59, 0.07)`
- **Analytics Workspace Top Elevation (`5:113`)**:
  - `border-top: 1px solid #E3EBEE`
  - `box-shadow: 0px -4px 10px 0px rgba(26, 51, 59, 0.04)`
- **Standard Analytical Cards**:
  - Flat `1px solid #E3EBEE` or `#DEE7EA` on `#FFFFFF` with `0` drop shadow to keep visual noise minimal.

---

## 7. Component Styling & Variants

### 7.1 Buttons (`14:20` & `5:278`)
- **Primary Button (`14:14`)**:
  - Height: `36px`, padding: `0 16px`, border-radius: `6px`.
  - Background: `#159B91`, text: `#FFFFFF`, `Inter Semi Bold 12px`.
- **Secondary Button (`14:16`)**:
  - Height: `36px`, padding: `0 16px`, border-radius: `6px`.
  - Background: `#FFFFFF`, border: `1px solid #D7E2E6`, text: `#192F3A`, `Inter Semi Bold 12px`.
- **Disabled Button (`14:18`)**:
  - Height: `36px`, padding: `0 16px`, border-radius: `6px`.
  - Background: `#E8EEF0`, border: `none`, text: `#91A3AA`, `Inter Semi Bold 12px`, `cursor: not-allowed`.
- **Compact Utility Button (`Export analysis`, `5:278`)**:
  - Height: `31px`, border-radius: `7px`, background: `#FFFFFF`, border: `1px solid #E3EBEE`, icon `15×15 px` + `Inter Medium 11px` `#192F3A`.

### 7.2 Inputs, Selectors & Fields
- **Global Search Input (`5:129`)**:
  - `282 × 34 px`, border-radius: `8px`, background: `#F3F7F8`, icon `16×16 px` at `left: 11px`, placeholder `Inter Regular 11px #73858D`, shortcut badge `⌘ K` (`27 × 19 px`, `#FFFFFF`, border `1px solid #E3EBEE`, `rounded-4px`, `9px #73858D`).
- **Compact Selector Dropdown (`Variable selector` `5:163`, `Region selector` `5:170`)**:
  - `228 × 38 px`, border-radius: `7px`, background: `#FFFFFF`, border: `1px solid #E3EBEE`, leading icon `16–17 px`, label `Inter Medium 10–11px #192F3A`, trailing chevron `14×14 px`.
- **Labeled Analysis Field (`14:21`)**:
  - `220 × 64 px`, border-radius: `6px`, background: `#FFFFFF`, border: `1px solid #D7E2E6`.
  - Top label: `Inter Medium 10px #637983` (`top: 8px, left: 11px`).
  - Value: `Inter Medium 12px #192F3A` (`top: 30px, left: 11px`) with right chevron.

### 7.3 Cards, Badges & Analytical Controls
- **Selected Dataset Item (`5:152`)**:
  - `236 × 54 px`, border-radius: `8px`, background: `#EFF8F7`, border: `1px solid #CCE7E3`, dataset icon `21×21 px`, title `Inter Semi Bold 12px #192F3A`, metadata `Inter Regular 9px #73858D`, right check icon `15×15 px`.
- **Data Layer Toggle Row (`14:30`)**:
  - `220 × 42 px`, border-radius: `6px`, active background `#F0F8F6` (inactive `#F4F7F8`), `16×16 px` rounded-`3px` checkbox (`#159B91` when checked), title `Inter Semi Bold 11px #192F3A`, resolution subtitle `Inter Regular 9px #637983`.
- **Region AOI Card (`14:25`)**:
  - `220 × 98 px`, border-radius: `6px`.
  - Region A variant: background `#F0F8F6`, border `1px solid #CBE4DE`, overline `REGION` in `Inter Semi Bold 10px #159B91`.
  - Region B variant: background `#EEF6FB`, border `1px solid #C8DFEE`, overline `REGION` in `Inter Semi Bold 10px #3193CE`.
- **Status Label / Pill (`14:35`, `5:270`, `5:389`, `14:2627`)**:
  - Quality Screened: `#EAF5F1` fill, `#177965` text (`10px Medium`, `rounded-6px`).
  - Region Scope Pill: `#EFF7F6` fill, `#159B91` text (`10px Medium`, `rounded-12px`, `24px` height).
  - AI Generated Pill: `#E2F0ED` fill, `#159B91` text (`7px Semi Bold`, uppercase, `rounded-5px`).
  - Experimental Pill: `#F8F0E0` fill, `#8A672F` text (`8px Semi Bold`, uppercase, `rounded-4px`).
- **KPI Metric Card (`5:283`–`5:297`)**:
  - `336 × 80 px`, `rounded-10px`, `#FFFFFF`, border `1px solid #E3EBEE`.
  - Overline (`8px Semi Bold #73858D`, tracking `0.4px`), primary value (`22px–25px Medium #192F3A`) with inline unit (`10px Regular #73858D`), bottom status line (`9px Regular` in semantic color `#C77F6D`, `#159B91`, or `#73858D`).
- **Resilience Component Row (`14:37`)**:
  - `248 × 60 px`, label `12px Medium #192F3A`, weight percentage `10px Regular #637983` right-aligned, dual horizontal bars (`5px` height, `rounded-2px`, `#EBF0F2` track, `#159B91` Region A bar, `#3193CE` Region B bar).

### 7.4 Navigation & Panels
- **Homepage Navigation (`5:111`)**:
  - `72 px` height, `#FFFFFF` background, `1px solid #E3EBEE` bottom border.
  - Brand lockup (`36×36 px` symbol + `PROJECT` / `TERRA` + vertical divider + `Earth intelligence` subtitle).
  - Primary links (`Explore`, `Workspaces`, `Methodology` / application route links) with `2px` `#159B91` bottom active bar (`top: 69px`).
  - Right utilities: Global search (`282×34 px`), Notifications bell (`18×18 px`), Researcher account pill (`64×36 px`, `rounded-18px`, `#F3F7F8`).
- **Analytical Workspace Navigation (`14:3`)**:
  - `64 px` height, `#FFFFFF` background, `1px solid #DDE7EB` bottom border.
  - Compact brand lockup (`36×36 px` symbol + `TERRA` `20px Semi Bold`).
  - Route items (`Overview`, `Explore`, `Comparative Analysis`, `Assessments`, `Reports`, `Data Sources`) in `12px Medium #536D77`; active route in `12px Semi Bold #159B91` with a `3px` `#159B91` bottom indicator (`top: 61px`).
  - Right context: `RESEARCH WORKSPACE` (`10px Medium #637983`) and `Researcher ⌄` account pill (`114×34 px`, `rounded-6px`, `#F3F7F8`).
- **Timeline Controls Bar (`5:397`)**:
  - `1390 × 40 px`, `rounded-8px`, `#F3F7F8`.
  - Play button (`29×28 px`, `#FFFFFF`, border `1px solid #DFE8EB`, `rounded-6px`), start year (`2001`), monthly observation histogram (`1060×30 px`) bracketed by dual range handles (`6×28 px`, `#FFFFFF`, border `1px solid #159B91`, `rounded-2px`), end year (`2025`), vertical divider (`1×24 px #DDE7E9`),cadence selector (`Monthly` + chevron).

---

## 8. Iconography & Asset Usage

- **Icon Style**: Monoline vector icons with `1.3px`–`1.6px` stroke weight, rounded caps and joins.
- **Standard Sizes**:
  - `12×12 px` to `14×14 px`: Dropdown chevrons (`1bc83.svg`, `d06b9.svg`), timeline interval chevron (`25f9a.svg`).
  - `15×15 px` to `18×18 px`: Search (`acb4b.svg`), collapse chevron (`6212d.svg`), checkmarks (`3cd6e.svg`), variable/region icons (`53a46.svg`, `98285.svg`, `b2de5.svg`), download (`a173d.svg`), notifications (`90159.svg`), AI trend icon (`53a45.svg`), mobile menu trigger (`da108.svg`).
  - `20×20 px`: Map tool icons (`cff72.svg` Layers, `615e4.svg` Region selection, `0231e.svg` Locate, `d4ebb.svg` Zoom in, `ac2f2.svg` Zoom out, `a9891.svg` Fullscreen).
  - `21×21 px`: Dataset cylinder (`8958f.svg`), researcher avatar (`bf024.svg`).
  - `36×36 px`: Navigation Terra orbital contour symbol (`669b9.svg`).
- **Asset Integrity Rules**:
  - All Figma vector assets live locally under `frontend/public/assets/figma/` and retain their intrinsic SVG `viewBox` and aspect ratios.

---

## 9. Responsive Behavior & Breakpoints

Extracted from the three responsive comparison frames in Figma (`14:2` Desktop, `14:2713` Tablet, `14:2714` Mobile) and the component rules note in `14:11`:

| Breakpoint Tier | Figma Reference Width | CSS Media Query Range | Layout & Navigation Adaptation |
|---|---|---|---|
| **Desktop (Wide)** | `1440 px` (Home) / `1600 px` (Analysis) | `>= 1200px` | Full horizontal top navigation, fixed left configuration / dataset explorer rail (`252px`–`264px`), multi-column analytical grid (4 KPI cards + 3-column lower deck). |
| **Tablet** | `1024 px` (`14:2713`) | `768px – 1199px` | Top navigation condenses to `60px` height with compact `32×32 px` menu drawer button (`#F3F7F8`, `rounded-5px`); 2-column KPI grid; collapsible/stacked configuration rail; charts stack or wrap into 2 columns while retaining units and legends. |
| **Mobile** | `390 px` (`14:2714`) | `< 768px` | `60px` compact header with hamburger menu (`14:2736`), `16px` horizontal viewport padding (`358px` content column), single-column vertical stack for explorer controls, map canvas (`284px` height), KPI cards, and charts. |

---

## 10. Interactive & Analytical States

### 10.1 Interactive Control States
- **Active / Selected**:
  - Navigation link: `#159B91` text (`Semi Bold`) + `2px` or `3px` bottom bar in `#159B91`.
  - Dataset / Region card: `#EFF8F7` or `#F0F8F6` background with `#CCE7E3` / `#CBE4DE` border.
  - Map tool button: `#EDF7F5` background (`38×38 px`, `rounded-8px`) with `#159B91` icon.
- **Disabled (`14:18`)**:
  - `#E8EEF0` fill, `#91A3AA` label, non-interactive.
- **Hover & Focus-Visible**:
  - **[Unresolved in Figma]** (Figma frames show resting, selected, and disabled states, plus prototype modal triggers, but do not define separate hover or keyboard focus-ring frames).
  - **Engineering Standard**:
    - Hover on secondary buttons / interactive cards: border transitions from `#E3EBEE` / `#D7E2E6` to `#B8CCD2`, subtle background shift to `#F8FAFB`.
    - Hover on primary `#159B91` buttons: `#12877E`.
    - Keyboard `:focus-visible`: `2px solid #159B91` outline with `2px` offset.

### 10.2 Analytical Workspace States (Explicitly Designed in Figma)
1. **Empty / Unconfigured State (`14:7465` / `14:7556`)**:
   - Eyebrow: `COMPARATIVE ANALYSIS / EMPTY` (`10px Semi Bold #159B91`).
   - Heading: `Choose two regions to begin` (`28px Semi Bold #192F3A`).
   - Numbered onboarding steps (`01 Choose Region A`, `02 Choose Region B`, `03 Select an event, dates and observation layers`), primary CTA (`Use sample regions`) and secondary CTA (`Configure regions`), plus safeguard note: `No observations loaded. Nothing will be inferred before two valid regions are selected.`
2. **Loading / Processing State (`14:7570` / `14:7629`)**:
   - Eyebrow: `COMPARATIVE ANALYSIS / LOADING` (`10px Semi Bold #159B91`).
   - Heading: `Preparing matched observations` (`28px Semi Bold #192F3A`).
   - Determinate progress bar (`830 × 7 px`, `#E6EEF0` track, `#159B91` fill, `rounded-3px`) with status label (`58% · Aligning monthly composites`) and step checklist (`✓ Quality masks applied`, `↻ Matching monthly observations`, `03 Computing response & resilience`) + `Cancel analysis` secondary button.
3. **Error State (`14:7649` / `14:7708`)**:
   - Eyebrow: `COMPARATIVE ANALYSIS / ERROR` (`10px Semi Bold #A45F4D`).
   - Heading: `Precipitation could not be retrieved` (`28px Semi Bold #192F3A`).
   - Diagnostic container (`#FBF6F3` fill, `1px solid #E9D5CB`, `rounded-8px`) detailing error code (`DATA_FETCH_TIMEOUT`), `Failed source`, `Preserved` inputs, and `Not computed` outputs + `Retry processing` (Primary) and `Review data sources` (Secondary) actions.
4. **Insufficient Data State (`14:7726` / `14:7785`)**:
   - Eyebrow: `COMPARATIVE ANALYSIS / INSUFFICIENT DATA` (`10px Semi Bold #8A672F`).
   - Heading: `Not enough observations for comparison` (`28px Semi Bold #192F3A`).
   - Coverage eligibility table (`#FAF7EF` fill, `1px solid #E5DABE`, `rounded-8px`) highlighting ineligible regions in `#8A672F` with explicit threshold rule (`Required: ≥ 80% valid months and ≥ 12 valid post-event observations per region`) and withholding notice (`Mann–Kendall, Sen’s slope and TRI for Region B are withheld. No ranking is shown.`).

---

## 11. Map & Scientific Chart Visualization Conventions

### Geospatial Map Conventions
- **Projection & Grid**: Natural Earth / WGS 84 (`EPSG:4326`) with subtle graticule lines (`adcb7.svg`) and `0°` equator marker (`8px Regular #91A3AB`).
- **Continent & Ocean Typography**: Uppercase `Inter Medium 10px #91A3AB` (`NORTH AMERICA`, `PACIFIC OCEAN`, etc.).
- **Diverging Temperature Trend Scale (`5:261`)**:
  - `linear-gradient(90deg, #3193CE 0%, #A4CFCA 35%, #E8E9DB 50%, #DEB49F 75%, #C77F6D 100%)`
  - Domain labels: `−0.4`, `0`, `+0.8` (`°C / decade`).
- **NDVI Vegetation Density Scale (`14:6`)**:
  - Diverging/sequential dry-to-dense gradient (`0.0 · Sparse` to `1.0 · Dense`).
- **Hotspots & Region Selection**:
  - Hotspot markers: `28×28 px` translucent outer halo with `8×8 px` solid center dot (`#C77F6D` for warming anomalies, `#159B91` for cooling/vegetation).
  - Selected AOI boundary: Dashed `#159B91` polygon with subtle teal fill (`fc9a3.svg`), connected via angled leader line (`b0dcf.svg`) to a floating white metric card (`5:236`).

### Scientific Chart Conventions
- **Time-Series Anomaly Plot (`5:302`)**:
  - Solid `#159B91` line with vertex dots for **Observed** values.
  - Dashed `#3193CE` line for **OLS trend**.
  - Translucent `#3193CE` / `#DFEEF6` shaded band for **95% CI**.
  - Explicit axis units (`°C`) and baseline subtitle (`Annual display · Monthly OLS · Baseline 2001–2010`).
- **Cross-Variable Correlation Matrix (`5:336`)**:
  - `4 × 4` symmetric grid (`LST`, `NDVI`, `Precip.`, `Soil`), cell size `47 × 21 px`, `rounded-3px`.
  - Positive correlations (`r > 0`): Teal-tinted fills (`#E7F3F1` for `1.00`, `#C6E4DF` for `0.58`, `#B9DED7` for `0.66`, `#91C9BF` for `0.79`) with `#315F59` text.
  - Negative correlations (`r < 0`): Coral-tinted fills (`#E9D1C7` for `-0.62`, `#F0DFD7` for `-0.44`, `#ECD6CB` for `-0.57`) with `#805F51` text.
  - Scale bar: `linear-gradient(90deg, #D6AB97 0%, #F3F7F8 50%, #159B91 100%)` spanning `−1` to `+1`.

---

## 12. Motion & Interaction Principles

- **[Unresolved in Figma]**: Explicit easing curves and millisecond durations are not annotated in the static Figma frames.
- **Engineering Conventions**:
  - Use fast, non-distracting transitions (`150ms–200ms ease-out`) for panel collapsing, tab switching, hover states, and modal dialogs.
  - Avoid decorative bounce or long entrance animations that delay inspection of scientific data.
  - Respect `prefers-reduced-motion: reduce` by disabling non-essential transitions.

---

## 13. Accessibility Requirements

1. **Contrast & Legibility**:
   - Primary body text (`#192F3A` on `#FCFDFE` / `#FFFFFF`) achieves `> 13:1` contrast ratio (WCAG AAA).
   - Secondary text (`#536E77` and `#637983` on `#FFFFFF`) meets WCAG AA (`> 4.6:1`).
   - Correlation heatmap cells pair tinted backgrounds with darkened semantic ink (`#315F59` on teal cells, `#805F51` on coral cells) rather than white text.
2. **Non-Color Redundancy**:
   - Trend direction and statistical status are never communicated by color alone: directional arrows (`↑ Increasing`, `↑ Positive trend`), explicit p-values (`p < 0.001`), and text labels (`Significant`, `Insufficient`, `Complete`) accompany all color encodings.
3. **Semantic Landmarks & Keyboard Navigation**:
   - Use semantic `<header>`, `<nav>`, `<main>`, `<aside>`, and `<section>` landmarks.
   - All interactive controls (dataset selectors, map tool buttons, workspace tabs, timeline play/range controls, and route links) must be keyboard-focusable `<button>` or `<a>` elements with accessible `aria-label` or visible text.
