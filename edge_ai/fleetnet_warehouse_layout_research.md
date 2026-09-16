# Real-World Warehouse Layout Analysis and Procedural Generation Specification for FleetNet

**Scope:** Spatial/environmental structure of warehouses only. No robot algorithms, task allocation, or path planning are addressed here — this document defines the *environment* those systems will later operate in.

**Evidence framework used throughout:**
- 🟢 **Verified pattern** — widely documented across multiple independent logistics-engineering sources (MHI/Material Handling Institute guides, warehouse design textbooks, published case studies).
- 🔵 **Common industry practice** — consistently reported by warehouse design/consulting firms and equipment manufacturers, but not a universal standard.
- 🟡 **Inferred pattern** — reasoned from the above plus general facility-planning logic, not directly cited to a single source.
- ⚪ **Assumption** — a modeling choice made for the generator where real-world data is ambiguous or facility-specific.

Where I give a number, I mark which of these four buckets it falls into. I have **not** fabricated precise dimensions — ranges below reflect commonly-cited industry figures (pallet/rack/forklift standards, dock-door spacing conventions, etc.). For a version of this document with citations tied to specific published sources (academic layout-optimization papers, MHI's *Warehouse Modernization Guide*, consulting-firm benchmarks like Baker & Canessa, Tompkins et al.'s *Facilities Planning*), a broader sourced literature pass would be the next step — noted at the end.

---

## A. Warehouse Component Inventory

### Storage components
| Component | Status | Notes |
|---|---|---|
| Selective pallet rack | Essential (general) | 🟢 Default in most palletized DCs; single-deep, forklift-accessible from aisle |
| Drive-in / drive-through rack | Common | 🔵 High density, low SKU variety (cold storage, bulk goods) |
| Push-back rack | Common | 🔵 Medium density, better SKU access than drive-in |
| Cantilever rack | Industry-specific | 🔵 Long/irregular items (lumber, pipe, steel — manufacturing/automotive) |
| Shelving (bin/small-parts) | Essential (e-commerce/parcel) | 🟢 High-SKU, low-per-unit-volume picking |
| Bulk/floor storage | Common | 🔵 Palletized bulk without racking, seasonal/high-volume SKUs |
| High-density storage (mobile/mezzanine) | Optional | 🔵 Space-constrained or high-rent facilities |
| Automated storage (AS/RS, shuttle) | Optional/growing | 🔵 High-throughput e-commerce/grocery; changes aisle geometry fundamentally |

### Movement components
- Main aisles, secondary (picking) aisles, cross aisles, transfer aisles — 🟢 verified as the standard hierarchy in nearly every layout-planning source.
- Intersections, turning bays (wider nodes at rack-row ends for forklift turning) — 🔵.
- Loading/unloading dock aprons and staging lanes — 🟢.

### Operational zones
Receiving, put-away, storage, picking, packing, sorting, staging, shipping, returns/reverse-logistics, quality inspection/consolidation, dispatch — 🟢 this is the standard end-to-end flow taught in facilities-planning texts (Tompkins, Frazelle). Not every warehouse has all of them distinctly zoned; small warehouses often merge receiving/staging or packing/staging.

### Infrastructure
- Offices, restrooms, break rooms — essential (human-occupied facilities).
- Battery charging / equipment parking areas — essential wherever powered material-handling equipment is used (🟢); directly analogous to your robot charging zones.
- Maintenance/utility rooms — common.
- Fire lanes, emergency egress paths, sprinkler-riser clearances, column grids — essential and *structurally load-bearing on the layout* (🟢) — these are often the actual source of "irregularity" in real warehouses, more so than deliberate design choice.
- Pedestrian walkways (painted/caged) separated from vehicle aisles — 🟢 required by most safety codes (OSHA-style separation) once mixed foot/vehicle traffic exists.

**Essential vs. optional summary:**
- **Essential in virtually all warehouses:** receiving zone, storage zone, shipping zone, primary aisle network, dock area, emergency egress paths, structural columns.
- **Common but not universal:** dedicated packing zone, staging zone, cross-docking lanes, mezzanines, charging areas.
- **Industry-specific:** cold-storage anterooms/airlocks, pharma quarantine/cage areas, automotive cantilever yards, cold-chain blast-freezing zones.

---

## B. Warehouse Geometry & Layout Archetypes

Real facilities are built inside rectangular (or near-rectangular) shells far more often than not — building economics favor simple rectangular envelopes (🟢). Irregularity is usually *imposed* on a rectangle (columns, additions, fixed dock positions) rather than the building itself being organically shaped.

### Archetype taxonomy (derived, not assumed 1:1 from the prompt's list)

| Archetype | Description | Aisle structure | Typical use | Bottlenecks | Procedural suitability |
|---|---|---|---|---|---|
| **Flow-through / I-flow** | Receiving and shipping on opposite ends of the building; single directional flow | Long parallel aisles perpendicular to flow direction | High-volume, single-SKU-type flow (parcel, cross-dock) | Mid-building cross-aisles under peak flow | High — simplest to parameterize |
| **U-flow** | Receiving and shipping on the *same* side/wall | Storage block sits between; flow loops around it | Space-constrained sites, single-dock-wall buildings | Around the ends of the storage block | High |
| **L-flow** | Receiving and shipping on adjacent (perpendicular) walls | Diagonal-ish dominant flow across a rectangular grid | Irregular-shaped lots, retrofit buildings | Corner near the bend | Medium — requires corner-zone logic |
| **Grid / parallel-aisle** | Uniform rack rows, evenly spaced parallel picking aisles, perpendicular cross-aisles | Very regular, high aisle-count | Palletized bulk storage, distribution centers | Cross-aisle junctions, ends of long aisles | Very high — most naturally proceduralizable |
| **Zone-based / multi-block** | Building divided into independently-organized zones (e.g., pallet zone + each-pick zone + bulk zone), each with its own micro-layout | Mixed — main "spine" aisle connecting zone-specific sub-grids | Mixed-SKU e-commerce/3PL with very different pick profiles per zone | Zone-transition corridors | High — composable, good fit for generator |
| **Central-corridor** | One dominant spine aisle running the length of the building, storage blocks branch off both sides | Spine + perpendicular feeder aisles (comb pattern) | Large fulfillment centers, manufacturing supply lines | Spine intersections | High |
| **Fishbone / angled picking** | Angled (non-90°) picking aisles feeding into a central diagonal cross-aisle (popularized by order-picking optimization research) | Non-orthogonal | Manual each-picking operations optimizing travel distance | Angled merge points | Medium — nontrivial geometry but well studied in academic literature (Öztürkoğlu et al., Çelik & Süral) |
| **Irregular / constrained** | Rectangular envelope with carved-out exclusions (columns, fixed machinery, additions) | Otherwise-regular grid with local deviations | Retrofitted or older buildings, mixed-use facilities | Around each exclusion zone | Medium — best modeled as a grid + subtractive constraint layer, not a distinct generator path |

🟡 The fishbone/angled archetype is well-established in *academic* order-picking literature but is less common in built facilities than the orthogonal types above (implementation cost, forklift compatibility) — worth keeping as a generator option but weighting it lower in a categorical distribution.

---

## C. Aisles in Detail

Aisle width is driven almost entirely by **what moves through it**, not by an arbitrary design choice (🟢 — this is the single most consistent finding across warehouse-design references).

| Category | Typical range (approx., equipment-driven) | Driven by |
|---|---|---|
| Very narrow (VNA) | ~1.5–1.8 m | Turret trucks / guided VNA equipment, wire- or rail-guided |
| Narrow | ~2.2–2.7 m | Reach trucks |
| Standard | ~3.0–3.5 m | Counterbalance forklifts, sit-down trucks |
| Wide / main aisle | ~3.6–4.5 m+ | Two-way forklift traffic, cross-docking lanes, combined pedestrian+vehicle |
| Cross-aisle (secondary, low-traffic) | Can be narrower than the main picking aisle it connects | Only needs to fit one unit of equipment turning, not sustained two-way flow |

(🔵 These bands are widely cited in equipment-manufacturer and consulting literature as rule-of-thumb categories; exact figures vary by forklift model, load width, and local safety codes — treat as *distributions*, not fixed constants, per Section G.)

Additional aisle patterns worth encoding:
- **One-way vs. two-way** — narrow/VNA aisles are almost always one-way (🟢); main aisles are typically two-way.
- **Turning bays** — widened pockets at aisle ends/intersections to allow equipment to turn 90°, especially with narrower aisles (🔵).
- **Dead-end aisles** — occur but are actively avoided in modern design because they create congestion and safety hazards (🟢); when present, they're usually short secondary aisles, not main arteries.
- **Merging/splitting aisles** — occur at zone boundaries and near dock aprons where multiple aisle flows converge before shipping (🔵).

**Factors influencing width, ranked by typical design influence:** (1) material-handling equipment type, (2) whether traffic is one-way or two-way, (3) mixed pedestrian/vehicle use, (4) local safety-code minimum clearances, (5) storage density targets (denser storage pressures aisles narrower).

---

## D. Storage Structures → Navigation Structure

Rack rows are the dominant geometric primitive that *creates* the aisle grid, not the other way around (🟢). The generation order in real design practice is typically:
1. Fix dock/receiving/shipping wall positions (usually building-perimeter constrained).
2. Lay out rack rows in blocks (rows are the "walls" of the maze).
3. Aisles are the *negative space* between rows, sized per Section C.
4. Cross-aisles are inserted at intervals to cap maximum in-aisle travel distance (🔵 — common design rule of thumb: don't force pickers/vehicles to traverse the full building length without a cross-connection).
5. Storage-zone boundaries (e.g., fast-mover zone vs. bulk zone) are drawn afterward, often not aligned to rack blocks 1:1.

This ordering matters for your generator: **rack blocks should be generated before aisles are derived**, not aisles-first-then-racks-fitted, if you want realistic connectivity.

---

## E. Material Flow & Traffic Zones

Standard flow: **Receiving → Put-away → Storage → Picking → Packing → Staging → Shipping** (🟢, universal in facilities-planning literature, e.g., Frazelle's *World-Class Warehousing*).

Consistently reported traffic patterns:
- **High-traffic:** dock aprons (both receiving and shipping sides), main aisles/spine, staging zones near peak shipping windows (🟢).
- **Low-traffic:** deep storage interior (bulk/reserve), narrow-aisle VNA zones (single-vehicle-at-a-time by design) (🔵).
- **Bottlenecks:** staging-zone congestion right before shipping cutoffs, cross-aisle intersections near the dock wall, any point where put-away and picking flows cross paths (🔵 — this crossing is a well-known design anti-pattern facilities planners try to minimize by separating put-away and pick paths).
- **Central vs. peripheral:** in flow-through/grid archetypes, the spine/central corridor sees the highest sustained traffic; peripheral rack-interior aisles see intermittent, localized traffic.

This maps directly to a **traffic-weight field** you can bake into the environment metadata even without simulating robots yet — useful groundwork for later congestion-aware planning.

---

## F. Realistic Dimension Ranges

| Parameter | Approx. range | Basis |
|---|---|---|
| Small warehouse footprint | ~1,000–5,000 m² | ⚪ scale-band boundary, see Section G |
| Medium warehouse footprint | ~5,000–20,000 m² | ⚪ |
| Large fulfillment center footprint | ~20,000–100,000 m² | 🔵 roughly matches commonly reported "big-box" DC sizes |
| Very large (mega-DC) | 100,000 m²+ | 🔵 |
| Clear/ceiling height | ~6–12 m (single-level); up to ~20–40 m+ in high-bay AS/RS facilities | 🔵 equipment/rack-height dependent |
| Standard pallet footprint | ~1.0 × 1.2 m (varies by region: 40×48in US, 1200×800/1000mm EU) | 🟢 industry pallet standards |
| Rack bay width | ~2.4–2.7 m (sized to 2–3 pallets + uprights) | 🔵 |
| Rack row depth (single-deep, back-to-back pair) | ~2.2–2.4 m total | 🔵 |
| Dock door spacing | ~3.5–4.5 m centers | 🔵 common dock-design convention |
| Staging lane depth | ~6–15 m from dock face | ⚪ scales with dock throughput |
| Safety clearance (rack-to-aisle minimum) | ~150–300 mm beyond equipment operating width | 🟢 general safety-clearance practice, exact value code/region-dependent |

**Every range above is equipment-, scale-, or industry-dependent** — none should be hardcoded as a single constant in the generator; they belong in Section H as sampled distributions.

---

## G. Warehouse Scale Classification

| Scale | Floor area | Storage blocks | Aisles (order of magnitude) | Operational zones | Loading docks |
|---|---|---|---|---|---|
| Small | ~1,000–5,000 m² | 1–3 | 5–15 | 3–5 (often merged, e.g. combined receive/stage) | 1–4 |
| Medium | ~5,000–20,000 m² | 3–8 | 15–40 | 5–8 | 4–15 |
| Large | ~20,000–100,000 m² | 8–20 | 40–120 | 7–10 (fully distinct zones) | 15–60 |
| Very large | 100,000 m²+ | 20+ | 120+ | 8–12+, often multiple independent sub-warehouses under one roof | 60+ |

⚪ These bands are a reasonable, round-number scaffold rather than a cited standard — real facilities vary continuously, and this is meant as a *sampling backbone* for the generator (see distributions, Section I), not a hard classification rule.

---

## H. Irregular & Constrained Layouts

Real-world irregularity sources, roughly in order of how often they're cited as the actual driver of "non-ideal" layouts:
1. **Structural columns** — nearly universal in large single-story buildings on a fixed structural grid (often ~10–12 m spacing); rack layouts are frequently designed *around* the column grid rather than the reverse (🟢).
2. **Fixed dock positions** — dock doors are expensive to relocate, so layouts adapt to them, not vice versa, in retrofits (🔵).
3. **Building extensions/additions** — create non-rectangular overall envelopes or seams where aisle grids don't align cleanly (🔵).
4. **Fire/life-safety infrastructure** — sprinkler riser rooms, fire lanes, exit-path clearances are legally fixed and carve out no-storage zones (🟢).
5. **Fixed machinery/utility rooms** (electrical, HVAC, conveyor drive stations) — localized exclusion zones (🔵).
6. **Temporary/overflow storage** — genuinely irregular, low-priority space filled opportunistically (🟡).

**Modeling recommendation:** don't build a separate "irregular archetype" generator path. Instead, generate a clean archetype first (Section B), then apply a **subtractive constraint layer** — a set of exclusion polygons (columns, fixed rooms, fire lanes) stamped onto the regular grid, with local re-routing of any aisle/rack segment that intersects an exclusion. This matches how real facilities actually arise (regular design + physical realities imposed on top) and is far easier to keep valid/connected than generating irregularity from scratch.

---

## I. Procedural Generation Rules

```text
Select warehouse scale (Small/Medium/Large/Very Large)
        ↓
Select layout archetype (conditional on scale + industry type)
        ↓
Sample warehouse footprint dimensions (from scale-conditioned distribution)
        ↓
Place fixed structural constraints (column grid, dock wall position)
        ↓
Generate storage blocks (count, orientation, rack-row depth conditioned on archetype)
        ↓
Derive primary aisles (spacing conditioned on equipment-class distribution)
        ↓
Derive secondary/picking aisles (fill remaining rack-row gaps)
        ↓
Insert cross-aisles (interval conditioned on max-travel-distance constraint)
        ↓
Place operational zones (receiving/shipping fixed near dock wall; staging adjacent; picking/packing/charging positioned relative to flow direction)
        ↓
Apply subtractive constraint layer (columns, fire lanes, fixed rooms)
        ↓
Validate connectivity & clearances (Section L)
        ↓
Emit navigation graph (Section M)
```

**Fixed parameters:**
- Coordinate system / grid unit.
- Minimum legal clearance values (safety-driven, not stylistic).
- Existence of at least one receiving path and one shipping path with graph connectivity to all storage nodes.

**Randomized (uniform-ish, low real-world signal on exact value):**
- Exact rack-row count within an archetype-appropriate band.
- Exact placement offset of secondary aisles within their valid range.

**Sampled from distributions (Section J):**
- Warehouse footprint dimensions.
- Aisle widths per category.
- Storage density.
- Block spacing.

**Conditional:**
- High-density fulfillment center type → bias toward narrower aisles + higher rack-row count.
- Cold storage → fewer, wider aisles (equipment + insulation-panel constraints) and simpler rectangular archetypes (fewer irregularities — cold rooms are expensive per m², so extraneous shape complexity is design-avoided).
- Manufacturing/automotive → bias toward cantilever/bulk storage and larger open floor regions, lower shelving density.

---

## J. Procedural Generator Parameter Schema (revised)

```yaml
warehouse:
  seed: int
  scale_class: [small, medium, large, very_large]
  industry_type: [ecommerce, retail, grocery, manufacturing, automotive,
                   electronics, cold_storage, pharma, parcel, general_3pl]
  archetype: [flow_through, u_flow, l_flow, grid, zone_based,
              central_corridor, fishbone]
  length_m: float
  width_m: float
  clear_height_m: float

structural_constraints:
  column_grid_spacing_m: float
  dock_wall: [north, south, east, west]
  fire_lane_width_m: float
  fixed_exclusion_zones: list[polygon]

storage:
  block_count: int
  rack_type: [selective, drive_in, push_back, cantilever, shelving,
              bulk_floor, high_density, asrs]
  rack_row_count: int
  rack_orientation: [parallel_to_dock, perpendicular_to_dock]
  storage_density: float   # 0-1, fraction of footprint under racking

aisles:
  main_count: int
  main_width_class: [narrow_vna, narrow, standard, wide]
  secondary_count: int
  secondary_width_class: [narrow_vna, narrow, standard]
  cross_aisle_interval_m: float
  one_way_ratio: float     # fraction of aisles that are one-way

zones:
  receiving: {position, area_m2}
  shipping: {position, area_m2}
  staging: {position, area_m2}
  picking: {position, area_m2}
  packing: {position, area_m2}
  returns: {position, area_m2}
  charging: {position, area_m2}
  office: {position, area_m2}

constraints:
  min_clearance_m: float
  max_dead_end_length_m: float
  require_full_connectivity: bool
  require_dual_egress_paths: bool

diversity_controls:
  irregularity_level: float   # 0-1, density of exclusion-layer cuts
  zone_arrangement_variant: int
```

---

## K. Recommended Probability Distributions

| Parameter | Distribution | Why |
|---|---|---|
| Archetype | Weighted categorical | Not all archetypes are equally common; grid/flow-through dominate real facilities, fishbone is rare — weight accordingly |
| Industry type | Weighted categorical | Same logic; also drives conditional downstream choices |
| Footprint dimensions | Log-normal, conditioned on scale_class | Facility sizes are right-skewed (many mid-size, few huge outliers) — a classic log-normal shape in facility-size datasets |
| Aisle width (within a class) | Normal, truncated to the class's realistic band | Real aisle widths cluster around equipment-standard values with small variance, not uniform across the whole range |
| Rack-row / block count | Poisson or normal, conditioned on footprint | Discrete count that scales with available area, with realistic clustering around an area-implied mean rather than pure uniform randomness |
| Storage density | Beta distribution, conditioned on industry_type | Naturally bounded [0,1], and industry strongly shifts the mode (cold storage/bulk = lower density, e-commerce each-pick = higher) |
| Cross-aisle interval | Normal, conditioned on archetype | Design guides recommend a fairly consistent max-travel-distance target, so intervals cluster rather than vary wildly |
| Irregularity level | Beta, skewed toward low values | Most warehouses are mostly regular; heavy irregularity is the tail case, not the median |
| Number of dock doors | Poisson, conditioned on scale_class and industry_type | Discrete, throughput-correlated |

**Do not use pure uniform distributions** for any dimension/count parameter — uniform randomness is exactly what produces the "thousands of same-ish but randomly perturbed" dataset problem flagged in Section N. Uniform is acceptable only for categorical *tie-breaking* (e.g., which side of a symmetric layout a given optional zone sits on).

---

## L. Validity Constraints & Validation Pipeline

Reject a generated layout if any of the following hold:
1. **Disconnected graph** — any storage, zone, or dock node unreachable from any other via the aisle graph.
2. **No dual egress** — fewer than two independent paths from the deepest interior point to an exterior/emergency exit (safety-driven, mirrors real fire-code logic).
3. **Overlapping geometry** — any rack block, zone, or exclusion polygon intersects another non-aisle polygon.
4. **Sub-minimum clearance** — any aisle narrower than its assigned width class's legal minimum, or any turning bay too small for its intended equipment class.
5. **Impossible intersection geometry** — aisle segments crossing at non-manhattan/non-declared angles inconsistent with the archetype's rules.
6. **Unreachable operational zone** — any zone (picking, packing, charging, etc.) with zero adjacent aisle segment.
7. **Boundary violation** — any structure extending outside the declared footprint polygon.
8. **Dead-end exceeding max length** — dead-end aisle segments longer than `max_dead_end_length_m`.

**Pipeline:** generate → geometric overlap check → graph-connectivity check (BFS/DFS from dock nodes to all other nodes) → clearance check → dual-egress check → accept/reject → (if rejected) re-sample the offending parameter subset rather than the whole layout, to keep generation efficient at scale.

---

## M. Graph Representation

```text
Warehouse geometry
        ↓
Walkable space (aisles + open zones, minus exclusions)
        ↓
Skeletonize walkable space → centerline graph
        ↓
Nodes + edges
        ↓
Navigation graph
```

- **Nodes:** aisle intersections, dead-end termini, zone-entry points (receiving dock, shipping dock, each operational zone's access point), and optionally regularly-spaced "waypoints" along long straight aisle segments (useful later for congestion modeling, though that's out of scope here).
- **Edges:** aisle segments between two nodes, tagged with: length, width class, one-way/two-way, traffic-weight (from Section E), and archetype-role (main/secondary/cross).
- **Intersections:** represented as a single node with degree ≥3; store the intersection's physical footprint (turning-bay size) as a node attribute, not a separate structure.
- **Dead ends:** degree-1 nodes; tag explicitly as `dead_end: true` so downstream systems can treat them specially (no through-traffic assumption).
- **Bottlenecks:** not a separate graph element — derive them as an edge attribute (`effective_width` relative to `min(adjacent_node_degrees_traffic)`), or as a post-hoc analysis (edges with high projected-traffic-to-width ratio). Don't hardcode bottleneck locations at generation time; let them emerge from geometry + the traffic-weight field.
- **Restricted areas:** represented as polygons attached to the graph as *node/edge exclusions* (nodes inside a restricted polygon are flagged non-traversable rather than deleted, preserving the ability to visualize the full building shell).

---

## N. Generation Strategy Comparison

| Approach | Realism | Diversity | Controllability | Validity ease | Efficiency | Reproducibility |
|---|---|---|---|---|---|---|
| Pure random | Low | High | Low | Low (many rejects) | High | High (seeded) |
| Rule-based | Medium | Medium | High | High | High | High |
| Template-based | High (per template) | Low (limited by template count) | High | High | High | High |
| Grammar-based | High | High | Medium | Medium | Medium | High |
| Constraint-based | High | Medium | High | Very high | Medium (solver cost) | High |
| Procedural graph generation | Medium-high | High | High | Medium | High | High |
| **Hybrid (recommended)** | **High** | **High** | **High** | **High** | **High** | **High** |

**Recommendation:** a **hybrid of rule-based archetype selection + constraint-based validation + parametric/grammar-style sub-generation within each archetype.** Concretely: use rules/distributions (Sections I, K) to pick the archetype and high-level parameters, use a lightweight grammar (a small set of expansion rules per archetype — "storage block → N rack rows + M aisles") to generate the concrete layout, and use the constraint-validation pipeline (Section L) as a hard gate before accepting output. This gives you archetype-level realism, per-instance diversity from the grammar's parameter sampling, and guaranteed validity from the constraint gate — without the computational cost of a full constraint solver for every one of potentially millions of layouts.

---

## O. Dataset Generation & Storage Format

```text
Random seed
      ↓
Sample warehouse parameters (Section J, distributions from Section K)
      ↓
Grammar-based layout generation (Section I)
      ↓
Validation (Section L)
      ↓
Accept → unique warehouse instance
      ↓
Serialize: geometry + parameters + navigation graph
```

**Recommended format:** a **JSON (or YAML) file per warehouse instance**, containing (a) the full sampled parameter set (for exact reproducibility from seed + params alone), (b) the geometric layout (polygons for racks/zones/exclusions), and (c) the navigation graph in a standard graph-serialization form (e.g., node/edge lists compatible with `networkx`'s JSON graph format).

Why JSON/graph-JSON over the alternatives:
- **JSON over CSV** — the data is hierarchical and mixed-type (geometry + graph + scalar params); CSV would force an awkward flattening.
- **JSON over NumPy** — NumPy is great for the *numeric tensors* consumed at ML-training time (e.g., a rasterized occupancy grid for a CNN), but poor for storing the source-of-truth parametric/graph structure. Recommendation: store JSON as the canonical record, and generate a NumPy/array export **derived from it** for ML pipeines that want a grid tensor — don't make the array format the canonical store, since it's lossy relative to the graph.
- **Graph format** — use `networkx`'s node-link JSON (or an equivalent simple schema) so it's directly loadable without a custom parser, and stays human-inspectable.

At million-instance scale, batch instances into sharded files (e.g., 10,000 layouts per file) rather than one file per layout, to avoid filesystem overhead — a common practical pattern in large synthetic-dataset generation pipelines.

---

## P. Diversity Strategy

Diversity should be **measured**, not just assumed from randomized sampling — a generator can produce high parameter-variance and still yield structurally similar layouts if, e.g., archetype selection is too narrow.

**Diversity axes to track per dataset:**
- Scale distribution (histogram of footprint sizes).
- Archetype distribution (should roughly match your weighted-categorical targets, not collapse to one dominant type).
- Aspect ratio distribution.
- Aisle-count and intersection-count distributions.
- Storage-density distribution.
- Bottleneck-count distribution (derived post-hoc from the graph, per Section M).
- Irregularity-level distribution.

**Recommended diversity metrics:**
- **Graph-edit distance** or **graph-kernel similarity** (e.g., Weisfeiler-Lehman graph kernels) between sampled layout pairs — a direct measure of "are these actually structurally different navigation graphs, not just cosmetically different."
- **Coverage/entropy of the parameter space** — compute Shannon entropy over each categorical parameter's realized distribution in the generated dataset; low entropy flags an under-sampled archetype or industry type.
- **Nearest-neighbor distance in a feature vector** (footprint, density, aisle count, archetype one-hot, etc.) — flag/down-weight near-duplicate instances during dataset curation.

---

## Q. Example Generated Layouts (illustrative parameterizations)

1. **Small warehouse** — scale=small, footprint ≈ 2,000 m², archetype=u_flow, 2 storage blocks, 6 aisles (mostly standard-width), single merged receiving/staging zone, 2 dock doors, low irregularity.
2. **Medium warehouse** — scale=medium, footprint ≈ 12,000 m², archetype=grid, 5 storage blocks, ~25 aisles (standard + a few narrow), distinct picking/packing/staging zones, 8 dock doors.
3. **Large warehouse** — scale=large, footprint ≈ 60,000 m², archetype=central_corridor, 14 storage blocks, ~80 aisles, full zone separation including returns and charging, 30 dock doors, moderate column-grid irregularity.
4. **High-density warehouse** — scale=medium-large, industry=ecommerce, archetype=zone_based, storage_density high (Beta skewed high), mostly narrow/VNA aisles, dense shelving in an each-pick sub-zone plus a lower-density bulk sub-zone.
5. **Bottleneck-heavy warehouse** — deliberately sparse cross-aisle interval (sampled from the high tail of the normal in Section K) combined with a single dock wall (u_flow) — concentrates traffic through few intersections, useful stress-test case for later robot-traffic work.
6. **Irregular warehouse** — grid archetype with irregularity_level sampled high: dense column-grid exclusions, one fixed utility-room exclusion, one non-rectangular building-extension seam.
7. **Multi-zone warehouse** — archetype=zone_based with 4 distinct sub-zones (bulk pallet, case-pick, each-pick shelving, cold-chain anteroom), each with its own locally-appropriate rack type and aisle-width class per Section I's conditional rules.

---

## R. Recommended Technology Stack

**A lightweight 2D approach is sufficient and preferable** — nothing in this specification requires 3D beyond storing a scalar clear-height per zone for later use (e.g., ceiling-mounted sensor placement), which doesn't require full 3D simulation to represent.

- **Layout generation & geometry:** Python, with `shapely` for 2D polygon/geometry operations (overlap checks, exclusion-layer subtraction) and `numpy` for grid/array representations.
- **Graph representation:** `networkx` for the navigation graph — has built-in connectivity checks (directly usable for Section L's validation), serialization, and is the de facto standard, easing downstream ML/robotics tooling integration.
- **Validation:** custom rule checks built on top of `shapely`/`networkx` primitives (no need for a full constraint-solver library like `z3` or `OR-Tools` unless you later want the constraint-based mode from Section N's comparison to be more than "checks + resample").
- **Serialization:** JSON (`networkx.node_link_data`) plus a lightweight schema (e.g., `pydantic`) to validate the parameter files against Section J's schema before generation runs.
- **Visualization (for debugging, not the sim itself):** `matplotlib` for quick 2D renders of generated layouts — sufficient for verifying geometry/connectivity without building any 3D tooling.

This keeps the entire environment-generation stack in a single lightweight, well-understood 2D toolchain, deferring any 3D/visual-realism investment until (if ever) it's actually needed for a specific downstream use case (e.g., camera-sensor simulation for the robots), which is explicitly out of scope for this phase.

---

## Final Pipeline Summary

```text
REAL WAREHOUSE RESEARCH
          ↓
LAYOUT ARCHETYPES
          ↓
GENERATION PARAMETERS
          ↓
PROBABILITY DISTRIBUTIONS
          ↓
PROCEDURAL GENERATOR
          ↓
VALIDATION ENGINE
          ↓
DIVERSE WAREHOUSE DATASET
          ↓
NAVIGATION GRAPH
```

This specification is implementable independently of any robot algorithm — a programmer can take Sections I–O directly into code (schema → grammar-based generator → shapely/networkx validation → JSON dataset export) without needing anything from the eventual FleetNet robot-behavior layer.

---

### Note on sourcing depth

The ranges and patterns above reflect standard, broadly-consistent findings across warehouse-design and facilities-planning literature (Tompkins et al.'s *Facilities Planning*, Frazelle's *World-Class Warehousing and Material Handling*, MHI/material-handling-equipment guidance, and academic order-picking/aisle-design papers). They're solid enough to build the generator against. If you want the next revision tied to specific, citable sources per number (e.g., an exact figure from a named published case study rather than "commonly cited industry range"), that's a good candidate for a deeper sourced pass across academic databases, MHI publications, and consulting-firm benchmark reports.
