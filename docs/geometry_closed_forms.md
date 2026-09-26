# Closed forms for E9c's exact check

Written on 2026-09-23, before the check first ran (re-registration 3 of E9c, `CHANGELOG_EXPERIMENTS.md`).
E9c compares the vertex count N, the edge count E and the graph diameter D (in hops) of every level built up to
400,000 vertices with the forms below: integer equality, no tolerance.

The gasket and S(p, n) forms are published results. The Vicsek and carpet forms are derived here by hand from
the construction rules in `XON_SIM_GEOMETRY_V1_2.md` §2–3, not from the builder code. What was already known
when this was written is listed at the end. A closed form was found for all four geometries, so none falls back
to an unverified ratio trend.

L is the builder's level: the number of subdivisions of the seed.

| Geometry | Cells | N_L | E_L | D_L | Levels checked |
|---|---|---|---|---|---|
| gasket | 3^L | (3^(L+1) + 3) / 2 | 3^(L+1) | 2^L | 0–11 |
| S(p, n), n = L + 1 | p^L | p^n | p (p^n − 1) / 2 | 2^n − 1 | 0–8 (p = 4) |
| Vicsek (plus) | 5^L | 2·5^L + 2 | 3·5^L + 1 | 3^L + 1 | 0–7 |
| carpet | 8^L | (44·8^L + 56·3^L + 40) / 35 | (12·8^L + 8·3^L) / 5 | 2·3^L | 0–6 |

Cells are the leaf triangles (gasket), the smallest p-cliques (S(p, n)) and the leaf squares (Vicsek, carpet).
They are reported with the ratio sequence, not judged.

## Gasket

Construction (the V1 convention): level 0 is a triangle, and each subdivision splits every leaf triangle into
its three corner triangles. So level L+1 is three copies of level L, each pair sharing one corner vertex and no
edge.

- **N.** N_0 = 3 and N_(L+1) = 3 N_L − 3, so N_L = (3^(L+1) + 3) / 2.
- **E.** Every edge lies in exactly one leaf triangle: E_L = 3 · 3^L.
- **D.** Induction on the claim that corners are 2^L apart and no pair is farther. The copies meet only at
  their shared corners. A path between corners of two copies goes through their shared corner (2^L + 2^L) or
  through the third copy (3 · 2^L), so corners of level L+1 are 2^(L+1) apart. Vertices in one copy are at most
  2^L apart. Vertices u, v in different copies are at most d(u, s) + d(s, v) ≤ 2^L + 2^L apart, where s is the
  corner the two copies share.

These are the Sierpiński triangle graphs; Hinz, Klavžar and Zemljič (2017, *A survey and classification of
Sierpiński-type graphs*, Discrete Applied Mathematics 217) give the same forms.

## S(p, n)

Published (Klavžar and Milutinović 1997), for words of n letters: N = p^n, E = p (p^n − 1) / 2, and diameter
2^n − 1, the distance between the extreme vertices i^n and j^n. The builder's level L is S(p, L + 1): its seed
is K_p = S(p, 1). E follows from the recursive description: S(p, n+1) is p copies of S(p, n) plus one bridge
edge per pair of copies, so E_(n+1) = p E_n + p (p − 1) / 2 with E_1 = p (p − 1) / 2. E9 uses p = 4.

## Vicsek (plus variant) and carpet: common facts

Construction (`XON_SIM_GEOMETRY_V1_2.md` §3.1–3.2): level 0 is the unit square; each subdivision splits every
leaf square into a 3×3 block and keeps 5 of the 9 sub-squares (Vicsek: the center and the four edge midpoints)
or 8 of them (carpet: all but the center). Vertices are cell corners and edges are cell sides, merged where
cells meet (§2).

- **Grid units.** Scaling level L by 3^L makes the cells unit squares at integer positions (i, j), 0 ≤ i, j < 3^L.
  Each subdivision appends one base-3 digit to i and one to j, so a cell exists if and only if, at every digit
  position, the pair of digits is a kept position: Vicsek needs one of the two digits to be 1; the carpet
  forbids both being 1.
- **Copies.** The first digit pair picks a sub-square of the 3×3 block and the remaining digits are a level-L
  address. So level L+1 is copies of level L, one in each kept sub-square.
- **Manhattan bound.** Every edge is a unit step along one axis, so d(u, v) ≥ M(u, v), where
  M(u, v) = |u_x − v_x| + |u_y − v_y| in grid units.

## Vicsek

- **Cells.** 5^L.
- **Where copies meet.** Only one cell of level L touches the right side of its bounding square: i = 3^L − 1
  has every digit 2, so every digit of j must be 1. The same holds on each side, and these four "tip cells" sit
  at the middle of the sides. At level L+1 each arm copy meets the center copy along their facing tip sides,
  which coincide: 2 vertices and 1 edge per junction.
  - For L ≥ 1 the arm copies do not touch each other: the corner cells of a bounding square have digits that
    are all 0 or 2, so they do not exist.
  - For L = 0 two neighboring arms share one corner point. That point also lies on both of their junction
    sides, so it is still subtracted exactly as the count below assumes.
- **N.** N_0 = 4 and N_(L+1) = 5 N_L − 8, so N_L − 2 = 5 (N_(L−1) − 2) and N_L = 2·5^L + 2.
- **E.** E_0 = 4 and E_(L+1) = 5 E_L − 4, so E_L = 3·5^L + 1.
- **D = 3^L + 1.** Write n = 3^L and m = (n − 1) / 2.
  - The central row (j = m) and column (i = m) are complete, because m has every digit 1. The tip sides are
    left {(0, m), (0, m+1)}, right {(n, m), (n, m+1)}, bottom {(m, 0), (m+1, 0)} and top {(m, n), (m+1, n)}.
  - (a) **Lower bound.** (0, m) and (n, m+1) are vertices with M = n + 1.
  - (b) **Between tip sides**, along the central row and column:
    - Opposite tip sides: vertices at the same height are n apart, the other pairs n + 1.
    - Adjacent tip sides: the four pairs are n − 1, n, n and n + 1 apart. For example, from (0, m+1) to (m, n)
      is n − 1, along y = m + 1 and then x = m.
    - So from any tip-side vertex, some vertex of every other tip side is within n, and all of its vertices are
      within n + 1.
  - (c) **Every vertex is within n of each tip side** (of some vertex on it). Induction:
    - Level 0, where n = 1, is immediate.
    - At level L+1 (side 3n), take the outer tip side T of arm copy A. A vertex of A is within n of T, inside A.
    - A vertex of the center copy C reaches the junction with A within n, then T across A within n (b, opposite
      sides): 2n in total.
    - A vertex of another arm copy reaches its junction with C within n, crosses C to the junction with A
      within n (b), then reaches T within n: 3n in total.
  - (d) **Upper bound at level L+1:**
    - Two vertices of the same copy are at most n + 1 apart, by induction: distances only shrink in the larger
      graph.
    - A vertex of an arm copy and one of C: at most n to the junction (c), plus the diameter n + 1 of C.
    - Vertices of two different arms: at most n + (n + 1) + n, by (c) and (b).
    - So D_(L+1) = 3n + 1 = 3^(L+1) + 1.

## Carpet

- **Cells.** 8^L.
- **Outer boundary.** The whole outer boundary of every level is present. At level 0 it is the square. At level
  L+1 it is made of outer sides of the copies, present by induction; so are the copy sides that face the empty
  center.
- **Hole borders.** A removed square is the center of a block. Its four sides are cell sides of the other eight
  sub-blocks, whose boundary cells always exist, because later removals only take centers.
- **Where copies meet.** The 8 pairs of copies that are neighbors around the ring share a whole side: 3^L + 1
  vertices and 3^L edges. The 4 pairs that touch diagonally next to the center share one point, which also
  lies on the two shared sides of the copy between them. By inclusion–exclusion (−1 for the diagonal pair,
  +1 for the triple), these points need no extra correction.
- **N.** N_0 = 4 and N_(L+1) = 8 N_L − 8 (3^L + 1), so N_L = (44·8^L + 56·3^L + 40) / 35. Substituting shows
  the recurrence holds, and N_0 = 140 / 35 = 4.
- **E.** E_0 = 4 and E_(L+1) = 8 E_L − 8·3^L, so E_L = (12·8^L + 8·3^L) / 5.
- **D = 2·3^L.**
  - (a) **Lower bound.** Opposite corners have M = 2·3^L.
  - (b) **Every vertex u has a path of length M(u, c) to each outer corner c.** At every vertex u ≠ c, one of
    the (at most two) unit steps toward c is an edge:
    - If u lies on an outer side through c, the step along that side is an edge.
    - Otherwise, consider the cell Q that has corner u and lies toward c. If Q exists, both steps are sides
      of Q.
    - If Q does not exist, it lies in a removed square H. A vertex is never strictly inside H, so u is on H's
      border. If u is a corner of H, both steps toward c run along H's sides. If u is inside a side of H, the
      step along that side runs toward c. H's sides are edges (hole borders, above).
  - (c) **Upper bound at level L+1** (side 3n, n = 3^L):
    - **Coarse grid.** The lines x, y ∈ {0, n, 2n, 3n} are present within the square (they are copy sides), so
      two points of that coarse grid are exactly M apart.
    - **Via corners.** For u in copy A and v in a different copy B, pick a corner a of A and a corner b of B.
      Then d(u, v) ≤ M(u, a) + M(a, b) + M(b, v), by (b) inside A and inside B.
    - **Choosing corners per coordinate.** Take each coordinate of a and b on the sides where A and B face each
      other. That coordinate is then monotone if A and B are in different columns (rows), and costs at most n
      if they share a column (row).
    - **Cases.** d(u, v) ≤ 3n + 3n when A and B differ in both row and column, and ≤ n + 3n otherwise. Within
      one copy the distance is at most 2n, by induction.
    - So D_(L+1) = 6n = 2·3^(L+1).

## Values checked

<!-- machine-read by tests/test_closed_forms.py: geometry, L, cells, N, E, D -->

**gasket**

| L | Cells | N | E | D |
|---|---|---|---|---|
| 0 | 1 | 3 | 3 | 1 |
| 1 | 3 | 6 | 9 | 2 |
| 2 | 9 | 15 | 27 | 4 |
| 3 | 27 | 42 | 81 | 8 |
| 4 | 81 | 123 | 243 | 16 |
| 5 | 243 | 366 | 729 | 32 |
| 6 | 729 | 1,095 | 2,187 | 64 |
| 7 | 2,187 | 3,282 | 6,561 | 128 |
| 8 | 6,561 | 9,843 | 19,683 | 256 |
| 9 | 19,683 | 29,526 | 59,049 | 512 |
| 10 | 59,049 | 88,575 | 177,147 | 1,024 |
| 11 | 177,147 | 265,722 | 531,441 | 2,048 |

**sierpinski_p** (p = 4)

| L | Cells | N | E | D |
|---|---|---|---|---|
| 0 | 1 | 4 | 6 | 1 |
| 1 | 4 | 16 | 30 | 3 |
| 2 | 16 | 64 | 126 | 7 |
| 3 | 64 | 256 | 510 | 15 |
| 4 | 256 | 1,024 | 2,046 | 31 |
| 5 | 1,024 | 4,096 | 8,190 | 63 |
| 6 | 4,096 | 16,384 | 32,766 | 127 |
| 7 | 16,384 | 65,536 | 131,070 | 255 |
| 8 | 65,536 | 262,144 | 524,286 | 511 |

**vicsek**

| L | Cells | N | E | D |
|---|---|---|---|---|
| 0 | 1 | 4 | 4 | 2 |
| 1 | 5 | 12 | 16 | 4 |
| 2 | 25 | 52 | 76 | 10 |
| 3 | 125 | 252 | 376 | 28 |
| 4 | 625 | 1,252 | 1,876 | 82 |
| 5 | 3,125 | 6,252 | 9,376 | 244 |
| 6 | 15,625 | 31,252 | 46,876 | 730 |
| 7 | 78,125 | 156,252 | 234,376 | 2,188 |

**carpet**

| L | Cells | N | E | D |
|---|---|---|---|---|
| 0 | 1 | 4 | 4 | 2 |
| 1 | 8 | 16 | 24 | 6 |
| 2 | 64 | 96 | 168 | 18 |
| 3 | 512 | 688 | 1,272 | 54 |
| 4 | 4,096 | 5,280 | 9,960 | 162 |
| 5 | 32,768 | 41,584 | 79,032 | 486 |
| 6 | 262,144 | 330,720 | 630,312 | 1,458 |

## Known when this was written

- **Vertex recurrences.** The builder's vertex-count predictions contain the Vicsek and carpet vertex
  recurrences above; I had read them before writing this. The derivations here do not use them. The edge and
  diameter forms appear nowhere in the code.
- **Earlier measurements.** Earlier runs measured N at the E9 levels, and diameters by double sweeps, which are
  lower bounds:
  - Vicsek 730 and 2,188 at levels 6 and 7, and the carpet 486 and 1,458 at levels 5 and 6.
  - On the gasket (up to level 12) and S(4, n) (up to level 9), the sweep diameters equal the published forms.
- **Exact diameters so far.** Exact diameters were certified only while choosing the algorithm, on the gasket
  (levels 5–9) and S(4, n) (levels 3–5), never on Vicsek or the carpet.
