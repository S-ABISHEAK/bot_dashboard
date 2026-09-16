# Warehouse Layout & Facility Design: A Sourced Specification Reference for the FleetNet Layout Generator

## TL;DR
- Warehouse spatial structure is highly regular and parameterizable: aisle widths, rack bay modules, column grids, dock spacing, and clear heights all cluster into well-documented numeric ranges suitable for procedural generation, and the academic "parallel-aisle multi-block" model (Roodbergen & de Koster, *IJPR* 39(9):1865–1883, 2001) plus the non-traditional fishbone/flying-V family (Gue & Meller, 2009) give a validated geometric taxonomy.
- The strongest sourced numbers: standard US GMA pallet 48×40 in (roughly 30–35% of all US pallet production); selective rack bay 96-in beam (two pallets) on 42-in-deep uprights; counterbalance aisle ~12–13 ft, reach-truck ~8.5–10 ft, VNA turret ~5.5–6.5 ft, crane AS/RS ~1.5 m; modern DC clear height 32–40 ft (crane AS/RS up to ~45 m); column bays ~50–56 ft; dock doors on 12-ft centers at roughly 1 per 10,000 sq ft.
- Direct precedent exists for procedurally/algorithmically generating warehouse environments for multi-robot research (Zhang et al. 2023, IJCAI '23; asprilo; RWARE), and the PCG literature supplies ready-made diversity metrics (expressive range analysis, and quality-diversity/MAP-Elites measures such as connected-component count and average task length).

## Key Findings
1. Three "textbook" material-flow archetypes (U-flow, I/through-flow, L-flow) dominate industry practice; academic literature adds the parallel-aisle multi-block grid and the non-traditional angled-aisle designs (flying-V, fishbone).
2. Aisle widths map cleanly to equipment class and are the single most reliable parametric input.
3. Structural geometry (column grid, rack module, dock spacing) is dictated by the 48×40 pallet and steel mill stock lengths, producing predictable irregularities.
4. Facility scale bands (small/medium/large/very-large) are loosely standardized but real; component counts scale with them.
5. Fire/egress codes and fixed columns/docks are the dominant sources of layout irregularity.
6. There is a small but directly relevant body of work on generating warehouse layouts for robotics/MAPF, with usable validation and diversity methods.

---

## Details

### Section A — Warehouse Components (essential / common / optional / industry-specific)

**Storage systems (verified inventory, multiple industry sources).** The standard racking families are: selective pallet rack (single-deep), double-deep, drive-in/drive-through, push-back, pallet-flow, carton-flow, cantilever, structural pallet rack, narrow-aisle/VNA rack, mobile rack, bulk/floor stacking, shelving, and automated storage/retrieval systems (AS/RS). This taxonomy is corroborated by SJF Material Handling, Damotech, and MH-USA.

Density/selectivity trade-offs (MH-USA comparison table): selective = 1 pallet deep, 100% selectivity, ~50–55% floor utilization; double-deep = 2 deep, ~60–65%; drive-in = 5–10+ deep, ~70–75%, LIFO; push-back = 2–6 deep, ~65–70%; pallet-flow = 5–20+ deep, ~70–75%, FIFO; cantilever = varies, ~55–65%. Push-back gives "up to 90% more storage" than selective per MH-USA (Advance Storage Products says up to 75%; **discrepancy noted** — figures range 60–90% depending on baseline). Drive-in utilization ~70–80% (Speedrack). Selective occupies ~45–50% of floor as usable storage.

**Classification for the generator:**
- *Essential (every warehouse):* at least one storage type (commonly selective rack or shelving), receiving area, shipping area, main travel aisle(s), pedestrian access/egress.
- *Common (most warehouses):* staging lanes, picking zone, packing area, put-away flow, cross-aisles, dock doors, offices, battery-charging/maintenance area.
- *Optional (scale/throughput dependent):* dedicated sortation, consolidation, returns/QA zone, mezzanine, VAS (value-added services), AS/RS.
- *Industry-specific:* temperature zones and buffered corridors (cold storage/pharma), quarantine/segregation (pharma), cantilever + outdoor yard (building materials/automotive long goods), hazmat rooms.

**Movement infrastructure:** main aisles, secondary/picking aisles, cross-aisles (front, back, and intermediate), intersections, and turning/maneuvering areas at aisle ends. Roodbergen & de Koster (2001) formalize the parallel-aisle + cross-aisle structure.

**Operational zones (verified across sources):** receiving, put-away, storage, forward pick, replenishment, packing, sortation, consolidation, staging, shipping/dispatch, returns, QA/inspection.

**Infrastructure:** charging areas, maintenance, offices, safety/PPE zones, emergency exits, restricted/hazmat areas, marked pedestrian walkways.

### Section B — Layout Archetypes (taxonomy)

**1. U-flow (U-shaped).** Receiving and shipping on the same wall; product flows in and loops back. Described by multiple sources (Camcode, SphereWMS, Lace Up Solutions) as the most common layout, especially for facilities under ~150,000 sq ft and for cross-docking. Advantages: shared docks, flexible labor, one truck yard, minimal handling. Disadvantage: dock-apron congestion at peak. Bottlenecks concentrate at the shared dock/staging area.

**2. I-flow / through-flow.** Receiving and shipping at opposite ends, straight-line flow. Best for high-volume, high-throughput operations with predictable SKU velocity; fully separates inbound/outbound. Disadvantage: longest internal travel, two yards, long footprint.

**3. L-flow.** Receiving and shipping on adjacent (perpendicular) walls. Suits corner sites and hard inbound/outbound separation; disadvantage is dead space in the corner.

**4. Parallel-aisle multi-block grid (academic canonical).** Roodbergen, K.J. & De Koster, R. (2001), "Routing methods for warehouses with multiple cross aisles," *International Journal of Production Research* 39(9):1865–1883 (DOI 10.1080/00207540110028128), building on Ratliff & Rosenthal (1983): storage racks in blocks separated by pick aisles and cross-aisles; cross-aisles at front, back, and optionally between blocks. A companion paper is "Routing order pickers in a warehouse with a middle aisle," *EJOR* 133(1):32–43. This is the reference geometry for order-picking optimization and the natural base grammar for procedural generation. Pohl et al. (2009) found the optimal central cross-aisle for dual-command lies between the center and the rear.

**5. Fishbone / flying-V (non-traditional angled aisle).** Gue & Meller (2009) proposed the flying-V (V-shaped cross-aisle, vertical picking aisles) and fishbone (angled picking aisles with two diagonal cross-aisles at ~45°/135°) for unit-load warehouses with a single pickup-and-deposit (P&D) point. **Reported savings (verbatim from Gue & Meller's NSF conference paper):** the flying-V "offers about 10% improvement over the traditional design," and the optimized fishbone "has expected travel distance 20.4 percent lower than an equivalent traditional warehouse." Öztürkoğlu, Gue & Meller (2014, *EJOR* 236:382–394) extended the approach to multiple P&D points, with angled designs achieving up to ~22.5% savings. **Caveats:** Pohl, Meller & Gue (2009) found the fishbone reduces *dual-command* travel by only 10–15% (benefits shrink markedly under task-interleaving); the classic result assumes a single central P&D point and single-command, random storage; the design sacrifices roughly 3% floor/density; and real deployment (Generac, 2007) raised in-facility safety concerns. Fishbone RMFS variants are now being studied for robotic mobile fulfillment (Zhao et al. 2024, *Expert Systems with Applications*, DOI 10.1016/j.eswa.2024.125166).

**6. Zone-based / central-corridor variants** exist as practical composites but are less formalized in academic literature — treat as inferred.

### Section C — Aisle Width Ranges by Equipment Class

**Regulatory note:** OSHA does NOT set a fixed numeric aisle width. 29 CFR 1910.176(a) requires "sufficient safe clearances"; the once-cited "3 ft wider than the widest equipment or 4 ft minimum" comes from a 1972 OSHA interpretation letter that has been **WITHDRAWN** (J.J. Keller). Egress minimum is 28 in at any point (1910.36(g)(2)); NFPA 101/IBC exit-access corridors are typically 44 in before occupant-load scaling. OSHA's forklift eTool notes conventional counterbalance rack systems "generally require about a 12-foot aisle width."

Sourced equipment ranges (converging across Toyota Forklift, MH-USA, Arker, Wolter, Xilin, Hup):
- **Standard / wide aisle (counterbalance):** ~12–13 ft (Toyota: 10.5 ft+; MH-USA: 11–13 ft; a 5,000-lb counterbalance may need 14–16 ft). Two-way counterbalance travel ~18–22 ft (BigRentz).
- **Narrow aisle (reach truck):** ~8.5–10.5 ft (Toyota 8.5–10.5; single reach ~9 ft, double reach ~10–10.5 ft per Arker). Metric: 2.3–2.8 m (Xilin).
- **Very narrow aisle (VNA turret / swing-reach):** ~5–7 ft (Toyota 5–7; MH-USA 5.5–6.5; guided order picker as tight as 4 ft 4 in per Arker). Metric: 1.5–1.8 m (Xilin); requires wire/rail guidance and a superflat floor (FF50+).
- **Crane AS/RS aisle:** ~1.5 m (~5 ft) per Mecalux; narrow-aisle crane patents cite 0.8–1.3 m.
- **One-way vs two-way:** one-way = equipment width + ~3 ft clearance; two-way = 2× equipment width + clearance (BigRentz, Warehouselines).

### Section D — Realistic Dimensions

**Pallets.** US GMA/North American standard: 48×40 in (1219×1016 mm), 6–6.5 in tall, ~33–48 lb empty, 2,500–4,600 lb dynamic load (WeAreWarp, FreightRun). This footprint is dominant — it accounts for roughly 30% of all wood pallets manufactured in the US (Packaging Revolution, 2026), with USDA Forest Service research cited at roughly 35% of US pallet production. Euro/EPAL (EUR-1): 1200×800 mm (47.24×31.50 in), ~25 kg, ~1,500 kg dynamic (EN 13698). Other footprints: 48×48 (drums), 42×42 (telecom/paint), 48×45 (automotive), 1200×1000 (ISO/industrial), 1100×1100 (Asia).

**Rack bay module.** Most common selective bay: 96-in beam holding two 48×40 GMA pallets, on 42-in-deep uprights (Warehouse1, Hammerhead, rackandshelf). Beam lengths: 96 in (2 pallets, most common), 108, 120, 144 in (3 pallets); less common 132/168. Upright depths 36/42/48 in. Bay heights 96–192+ in; upright heights 8 ft to 40+ ft. Rack depth 42 in gives ~3-in overhang front/back on a 48-in pallet, so actual aisle clearance is ~6 in narrower than the plan dimension (McGee).

**Clear/ceiling height.** Cushman & Wakefield: average new-warehouse clear height rose from 25 ft (1997) to 32 ft (2017) for buildings ≥300,000 sq ft; 36 ft common in mega-DCs, some >40 ft. CBRE (verbatim, Blaine Kelley, SVP Industrial & Logistics): "the average clearance for all warehouse properties CBRE has built has seen steady gains, rising from 30.19 feet in 2010 to 32.95 feet in 2016," and Kelley named 40 ft as the practical "magic number" ceiling. Per CBRE's 2018 analysis, warehouses built 2012–2017 averaged 184,693 sq ft with average clear height of 32.3 ft; 89% of 554 large US warehouses built since 2011 have 28–36 ft ceilings. Modern standard ~32 ft, trending to 36–40 ft. **Crane AS/RS high-bay:** minimum threshold ~12 m (Hörmann Intralogistics: "a warehouse with a height of over 12 meters"); practical maximum ~45 m (~145 ft) — converged on independently by Dematic ("up to 45 meters tall"), Mecalux ("up to 45 m high in aisles as narrow as 1.5 m wide"), Alstef, Unitechnik, and Daifuku ("up to 45 meters (145 feet) and sometimes higher"); Swisslog cites stacker cranes "up to 50m (164ft)"; Westfalia double-mast S/RMs up to ~140 ft. A concrete large example (Mecalux/Hayat clad-rack): 120 m long × 105 m wide × 46 m high, 15 aisles at 1,800 mm width, 161,000 pallet capacity.

**Dock doors.** Spaced at minimum 12 ft on center (14 ft recommended to reduce congestion; some modern facilities 14–16 ft); doors typically 9 ft wide × 9–10 ft high; dock height 48–52 in; apron/truck-court depth ~120–150 ft for 53-ft trailers (MBC, McGuire, Loading Dock Supply). **Dock-count convention:** ~1 dock door per 10,000 sq ft for standard distribution (Link Logistics, verbatim: "industry practice in typical distribution operations calls for roughly one dock door per 10,000 square feet"); Gross & Associates' Geoffrey Sisko (via *MH&L*) notes the trend has tightened toward ~7,500 sq ft/door. High-velocity e-commerce/cross-dock run ~1 per 3,000–5,000 sq ft; manufacturing/bulk/cold ~1 per 15,000–20,000 sq ft; modern Class-A efficiency benchmark ~1.5–2 doors per 10,000 sq ft (Klein Commercial). Real spec example: a 2020-vintage 350,000-sq-ft Inland Empire cross-dock has 80 dock doors (1 per 4,375 sq ft).

**Staging depth.** "First 100 feet" convention: dock-adjacent staging + transition zone commonly ~60–100 ft deep; speed bays near docks ≥60 ft.

**Safety clearances.** Egress route ≥28 in absolute (OSHA), ≥44 in typical exit-access corridor (NFPA/IBC), single-file pedestrian lane ~36 in. Aisle marking lines 2–6 in wide (29 CFR 1910.22(b)). Sprinkler clearance ≥18 in below heads.

### Section E — Warehouse Scale Classification

Bands are loosely standardized (cutoffs vary by source), but a workable consensus:
- **Small:** <25,000 sq ft (some sources 5,000–15,000). Local storage, last-mile, trade shops.
- **Medium:** ~25,000–100,000 sq ft. Regional distribution, manufacturing support.
- **Large:** 100,000–500,000 sq ft. National distribution/fulfillment.
- **Very large:** >500,000 sq ft; 3PL/e-commerce can exceed 1,000,000 sq ft.

US building-stock average is ~17,000–17,500 sq ft (dominated by many small buildings; ~69% under 10,000 sq ft, <1% over 500,000). New-construction average is much larger — CBRE's 2012–2017 cohort averaged 184,693 sq ft, and figures of 180,000–200,000 sq ft are commonly quoted for new build. This **bimodal picture (existing stock vs. new-build)** is important for realistic generation: sampling a single mean would misrepresent the population.

Component counts scale with area: dock doors via the ~1/10,000 sq ft rule; number of blocks/aisles/intersections scales with footprint and chosen archetype. **Precise published counts** of blocks/intersections per scale class were NOT found — treat aisle/block counts as inferred/derived from footprint ÷ (bay module + aisle) geometry.

### Section F — Material Flow & Traffic Patterns

High-traffic/bottleneck zones (multiple industry sources): dock aprons and the "first 100 feet," staging lanes, cross-aisle intersections, packing stations, and single high-velocity pick zones where put-away and pick traffic collide ("dock-lock" — Racklify). Design guidance consistently recommends: separate replenishment from active picking; place outbound staging adjacent to docks so freight doesn't cross pick lanes; route equipment around (not through) pick modules; use one-way loops for high-traffic paths; and install controlled pedestrian crossings with color-coded lanes (green pedestrian, yellow equipment, red staging) (ShipBob, JIT, 3PL best-practice sources). Zhang et al. (2023) empirically show that regularized human-designed layouts cause congestion at scale for large robot fleets.

### Section G — Irregular Layouts

**Column grids.** Steel mills produce members in ~40/50 ft lengths, so architects default to those; modern Class-A DCs cluster at 50×50 to 56 ft, with 50–54 ft most common (REJournals; Link Logistics 50×50–56+). Southern California survey: 52 ft (32-ft clear), 56×50 (36-ft clear), 56–60 ft for e-commerce (Chuck Berger). A column landing in a path of travel forces rack relocation and wasted area; 54-ft bays allow a 10-ft aisle for 48-in racking, while 50-ft bays cause a column to land in the travel path (Supply Chain Beyond, paraphrasing Jim Tompkins). Speed bays near docks ≥60 ft. Older/small-bay stock uses ≤24 ft; AS/RS clad-rack buildings use very wide clear-span.

**Fixed docks & retrofits.** Fixed dock positions, saw-tooth dock arrangements (space-constrained sites), building extensions, and legacy small-bay grids all create irregularity that breaks a clean rectangular grid.

**Fire/life-safety.** Max exit-access travel distance: 250 ft sprinklered / 200 ft unsprinklered for typical commercial; up to 400 ft for single-story sprinklered S-1/F-1 storage with ≥24-ft clear (IBC Table 1017.2 / NFSA). Exit separation ≥ ½ diagonal (⅓ if sprinklered). These force through-aisles/egress corridors that break otherwise-regular grids.

### Section H — Related Procedural Generation Literature & Diversity Metrics

**Direct precedents:**
- **Zhang, Fontaine, Bhatt, Nikolaidis & Li (2023), "Multi-Robot Coordination and Layout Design for Automated Warehousing," IJCAI '23, pp. 5503–5511 (DOI 10.24963/ijcai.2023/611; arXiv:2305.06436).** Represents a layout as a four-neighbor grid of tile types (shelf/black, endpoint/blue, workstation/pink, empty/white, home/orange), with formal *validity* and *well-formed* constraints (e.g., each shelf adjacent to ≥2 endpoints; endpoints/workstations mutually connected). Optimizes storage-area tiles with the quality-diversity algorithm MAP-Elites plus a DSAGE deep surrogate model, repairing invalid layouts via Mixed-Integer Linear Programming (MILP) to preserve exact shelf count. Objective = throughput from a lifelong-MAPF simulator; **diversity measures = number of connected shelf components and average task length.** Verbatim result: optimized layouts "(2) improve the scalability of the automated warehouses by doubling the number of robots in some cases, and (3) are capable of generating layouts with user-specified diversity measures." Source code is public.
- **asprilo** (Gebser et al.) — open framework for simulating automated warehouse scenarios with synthetic layout generation of varying compactness (used by DC-MRTA, arXiv:2209.02865).
- **RWARE / TA-RWARE** (semitable; uoe-agents) — configurable multi-robot warehouse gridworlds (size, agent count, rack layout); TA-RWARE is modeled on the Quicktron Quickbin warehouse.
- **"A novel framework for automated warehouse layout generation"** (2024) — parametric approach over grid size, stack height, robot count, and filling degree; validated against a discrete-event simulation of an RCS/RS with a limited-capacity queueing model.
- Synthetic warehouse scene generation in Blender for perception (arXiv:2103.09174) and Unreal/Isaac Sim procedural scenes (AgentWorld, arXiv:2508.07770) demonstrate rule-based/randomized-occupancy-map placement approaches.

**Generation approaches seen in the literature:** rule/grammar-based placement on occupancy maps; constraint-based repair (MILP); quality-diversity search (MAP-Elites/DSAGE); and queueing + discrete-event-simulation validation.

**Diversity/coverage metrics from PCG literature (applicable to spatial layouts):**
- **Expressive Range Analysis (ERA)** — Smith & Whitehead (2010): pick 2+ computable metrics as axes and plot generated artifacts as a heatmap to reveal generator bias/coverage. Widely used; refinements include metric-selection methods (Withington & Tokarchuk, FDG 2023) and constrained expressive range (Bazzaz & Cooper, 2025).
- **Quality-Diversity measures** (MAP-Elites archive cells) — e.g., connected-component counts and average path/task length (as operationalized in Zhang et al. 2023).
- **Entropy-based diversity measures** for generated scenarios (e.g., Sciencedirect S1875952124001277, RL scenario generation).
- **Graph-based comparison** (graph-edit distance / graph kernels) is used in PCG generative-space comparison work to compare structural artifacts — directly applicable if layouts are represented as aisle/intersection graphs (**inferred applicability; no warehouse-specific published use found**).

---

## Recommendations (for revising the FleetNet spec)

1. **Adopt the parallel-aisle multi-block grid (Roodbergen & de Koster) as the base generative grammar**, with U/I/L flow as dock-placement variants and fishbone/flying-V as an optional non-traditional mode. Parameterize: number of blocks, aisles per block, cross-aisle count/positions, and P&D/dock placement. *Threshold to change:* if the sim targets robotic mobile fulfillment (movable pods) rather than fixed racks, follow the fishbone-RMFS variant (Zhao et al. 2024) or abandon pattern regularity entirely per Zhang et al. (2023).
2. **Drive geometry from the pallet + rack module.** Use 48×40 in pallet, 96-in bay (2 pallets), 42-in upright depth as defaults; expose EU 1200×800 as an alternate. Snap the column grid to 50–56 ft and flag/relocate racks when a column would land in an aisle (subtract ~6 in from plan aisle width for pallet overhang).
3. **Parameterize aisle width by equipment class** with the sourced ranges (counterbalance 12–13 ft; reach 8.5–10 ft; VNA 5.5–6.5 ft; crane AS/RS ~1.5 m), and support one-way vs two-way multipliers (2× equipment width + clearance).
4. **Sample scale from a bimodal distribution** reflecting existing stock (~17k sq ft) vs. new-build (~185k sq ft) rather than a single mean; set dock-door count via the ~1/10,000 sq ft rule scaled by industry type (3,000–5,000 for e-commerce/cross-dock; 15,000–20,000 for cold/manufacturing) with doors on 12–14 ft centers.
5. **Model irregularity explicitly:** inject a fixed column grid, fixed/saw-tooth docks, egress corridors (≤250 ft travel distance to an exit, ≥44-in corridors), and optional retrofit "seams."
6. **Validate diversity with ERA + QD measures** (connected shelf components, average task length, plus aisle-graph metrics), mirroring Zhang et al. (2023). Benchmark generator coverage against a 2D expressive-range heatmap before scaling the dataset.

**Additional benchmarks that would change these recommendations:** if the simulation targets purely robotic crane/shuttle AS/RS, switch defaults to crane-aisle (~1.5 m) geometry and high-bay heights (12–45 m), and drop human-ergonomic aisle minimums and egress-corridor logic for the automated storage block; if targeting cold-storage/pharma, add temperature zoning and buffered corridors as first-class components with quarantine/segregation zones.

## Caveats
- **Evidence tiers.** (1) *Verified with a specific cited source:* pallet dimensions and market share, rack bay modules, aisle-width equipment ranges, clear-height trends (CBRE/C&W with named figures), column grids, dock spacing/counts, fishbone/flying-V savings (Gue & Meller, 10% and 20.4%), the Roodbergen & de Koster grid, and the Zhang et al. generation method and doubling result. (2) *Common industry practice (multiple corroborating sources):* U/I/L archetype descriptions, scale bands, the ~1-dock-per-10,000-sq-ft rule, bottleneck locations, AS/RS max height ~45 m. (3) *Inferred:* block/intersection counts per scale class (derived from geometry, not published); graph-edit-distance applicability to warehouse layouts. (4) *Assumption / weakly sourced:* zone-based/central-corridor as formal archetypes; some density percentages (push-back "up to 90%") vary by source.
- Many web sources are vendor/consultant marketing; where possible these were cross-checked against academic papers, standards (OSHA/NFPA/IBC/EN 13698), and REIT/brokerage research (CBRE, Cushman & Wakefield, Link Logistics, Prologis).
- **OSHA has NO fixed aisle-width number** — any "OSHA minimum aisle width" claim elsewhere traces to a withdrawn 1972 interpretation letter.
- Dock-ratio and AS/RS-height figures come largely from vendors/CRE guides rather than a single primary big-4 brokerage report; treat them as convergent industry consensus, not a single authority.
- Conflicts flagged inline: clear-height averages differ by dataset (building stock vs. large new-build); push-back density 60–90%; VNA lower bound 4 ft 4 in (guided order picker) vs 5.5 ft (unguided/turret); fishbone savings 20%+ single-command but only 10–15% dual-command.