# 3D Assets

Store GLB/glTF assets, textures, shelf models, and representative product models.

For the MVP, simple low-poly assets are preferred over photorealistic scenes.

## In use

The web app serves its models from `apps/web/public/models/`, so Vite copies them into the build. How to add one, and the size limits, are in `apps/web/README.md` (*Adding a stock model*).

| Pack | Files | Source | License |
| --- | --- | --- | --- |
| Snackies by loafbrr | `apps/web/public/models/snackies/snackies.glb`: 17 packs (cereal, cookies, chips, milk, juice), one per node. Repacked from the pack's glTF with `npx @gltf-transform/cli` `copy`, `resize --width 1024 --height 1024`, and `webp --quality 85`, each with `--vertex-layout separate` | https://opengameart.org/content/snackies | CC0 (`License.txt` next to the file). Credit is optional: "loafbrr". |
| Food Kit 2.0 by Kenney | `apps/web/public/models/kenney-food/`: `apple`, `bag`, `bag-flat`, `banana`, `bottle-oil`, `can`, `fish`, `honey`, `ice-cream-cup`, `lemon`, `meat-raw`, `meat-ribs`, `meat-sausage`, `orange`, `peanut-butter`, `popsicle` (`.glb`), and `Textures/colormap.png` | https://kenney.nl/assets/food-kit | CC0 1.0 (`License.txt` next to the files). Credit is optional: "Kenney (www.kenney.nl)". |
| Furniture Kit, Nature Kit, Mini Market, City Kit (Roads, Commercial, Suburban), Car Kit by Kenney | `apps/web/public/models/kenney-furniture/`, `kenney-nature/`, `kenney-mini-market/`, `kenney-city-roads/`, `kenney-city-commercial/`, `kenney-city-suburban/`, `kenney-car-kit/`: decor and street pieces as shipped. Each kit with a palette keeps its own `Textures/colormap.png` next to its GLBs | https://kenney.nl/assets | CC0 1.0 (`License.txt` in each folder). |
| Low Poly Vehicles Pack by Daniel Quevedo (bus) | `apps/web/public/models/quevedo-vehicles/bus.glb`: `Bus.fbx` converted to binary glTF with FBX2glTF, body, glass, and wheels recolored to sit with the Kenney pieces | https://opengameart.org/content/low-poly-vehicles-pack | CC0 (`License.txt` in the folder). |
| House Plants by Tiny Treats (Isa Lousberg) | `apps/web/public/models/tinytreats/`: `sansevieria`, `zz-plant` (`.glb`, texture embedded) | https://tinytreats.itch.io/house-plants (files from the Poly Pizza mirror) | CC0 1.0 (`License.txt` lists each source page). |
