# CST antenna → web 3D model

The interactive antenna in the **Academic project** card (`assets/models/cst-antenna.glb`, plus
`cst-antenna.js`, a base64 copy the page loads so it also works when opened from a folder) is the
geometry of `FYP 3rd stage with para.cst`. It was rebuilt from the project file itself, without
CST installed and without modifying the project.

## How it was produced

1. **Unpack** – a `.cst` file is a ZIP archive with renamed signatures. `extract_cst.py` reads it
   (read-only) and writes the contents to `extracted/`.
2. **Replay the modelling history** – `Model/3D/ModelHistory.json` holds every modelling step
   (bricks, boolean add/subtract, translations, 90°/180° rotations, WCS moves) and
   `Model/Parameters.json` the final parameter values. `replay.py` runs those steps with exact
   box geometry.
3. **Resolve picks** – steps that position the WCS by clicking a vertex, edge or face refer to
   entity IDs inside CST's kernel. CST caches each picked entity, with its history step and ID, in
   `Model/3D/Model.bwc` (ACIS SAT text). `picks.py` reads that cache, so every pick uses the real
   picked coordinates.
4. **Verify** – while replaying, each cached pick is checked against the rebuilt solid: 96 of 97
   land exactly on it. The remaining one refers to the original feed stub, whose length parameter
   `fl` is 0 in the final design. The bounding boxes of the substrate, ground plane and feed
   networks match the boxes CST stored in `Model/3D/Model.fct` to 0.1 µm.
5. **Export** – `build_antenna.py` builds a watertight surface for each solid (no internal faces)
   and writes the GLB (millimetres, Y-up, board centred at the origin).

## Contents of the model

| Node | Material (from the CST project) | Size |
| --- | --- | --- |
| substrate | FR-4 (lossy) | 34 × 34 × 0.8 mm |
| ground plane | Copper (annealed) | 34 × 34 × 0.035 mm |
| feed network 1–4 | Copper (annealed) | two slotted patches and feed line each |
| parasitic patch | Copper (annealed) | 12 × 12 × 0.035 mm |

## Regenerating after a design change

Requires Python 3 with NumPy.

```
python extract_cst.py "C:\Users\kumar\Downloads\FYP 3rd stage with para\FYP 3rd stage with para.cst" extracted
python build_antenna.py ..\..\assets\models\cst-antenna.glb ..\..\assets\models\cst-antenna.js
```

The pick cache only contains entities that were picked while the project was edited, so open and
save the project in CST after changing it, then run the two commands again.
