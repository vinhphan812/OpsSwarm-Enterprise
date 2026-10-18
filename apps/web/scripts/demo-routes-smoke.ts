/**
 * Opens `/`, `/demo`, `/live` and `/live?twin=demo` of a hosted demo build (`VITE_ALLOW_DEMO=true`)
 * in headless Chromium and prints, per route, the data chip and demo banner on screen, every
 * request that went to the API origin, and whether Accept on the simulation sent a POST. It
 * saves a screenshot of each route, and prints a markdown table at the end.
 *
 *   npm run smoke:demo-routes -- [--dist <built dist>] [--out <dir>] [--api <origin>] [--port N]
 *
 * Without `--dist` it builds the app first, with `VITE_ALLOW_DEMO=true` and `VITE_API_BASE_URL`
 * set to `--api` (https://api.example.invalid by default, which does not resolve). Requests to
 * that origin are answered here instead: `GET /store`, `GET /simulations…` with the demo store
 * under the store id `smoke-stub` (so `/live` has a simulation to Accept), anything else is
 * aborted as the unreachable origin would be. The demo routes should send none of them.
 */
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, type Page, type Request } from "playwright";
import { demoCandidates } from "../src/fixtures/demo/candidates";
import { demoSimulation } from "../src/fixtures/demo/simulation";
import { demoStoreState } from "../src/fixtures/demo/store";

const WEB_ROOT = resolve(fileURLToPath(new URL("..", import.meta.url)));
const args = process.argv.slice(2);
const option = (name: string) => {
  const at = args.indexOf(name);
  return at >= 0 ? args[at + 1] : undefined;
};
const api = new URL(option("--api") ?? "https://api.example.invalid").origin;
const out = resolve(option("--out") ?? mkdtempSync(join(tmpdir(), "demo-routes-smoke-")));
const port = Number(option("--port") ?? 4319);
const site = `http://127.0.0.1:${port}`;
mkdirSync(out, { recursive: true });

/** The routes and the twin each should open on a hosted demo build. */
const ROUTES = [
  { path: "/", expected: "demo" },
  { path: "/demo", expected: "demo" },
  { path: "/live", expected: "live" },
  { path: "/live?twin=demo", expected: "live" },
] as const;

/** The stub behind the API origin: the demo store renamed, so it is not taken for the demo. */
function stubBody(path: string): unknown {
  const demo = demoStoreState();
  const store = { ...demo, store_id: "smoke-stub", products: demo.products.map((product) => ({ ...product, store_id: "smoke-stub" })) };
  const simulation = demoSimulation(store);
  if (path === "/store") return store;
  if (path === "/simulations") return { simulations: [{ simulation_id: simulation.simulation_id, status: simulation.status }] };
  if (path === `/simulations/${simulation.simulation_id}`) return simulation;
  if (path === `/simulations/${simulation.simulation_id}/candidates`) return { candidates: demoCandidates(store) };
  return null;
}

function build(): string {
  const dist = mkdtempSync(join(tmpdir(), "demo-routes-dist-"));
  console.log(`build: VITE_ALLOW_DEMO=true VITE_API_BASE_URL=${api} → ${dist}`);
  const result = spawnSync("npx", ["vite", "build", "--outDir", dist, "--emptyOutDir"], {
    cwd: WEB_ROOT,
    env: { ...process.env, VITE_ALLOW_DEMO: "true", VITE_API_BASE_URL: api },
    stdio: ["ignore", "ignore", "inherit"],
  });
  if (result.status !== 0) throw new Error("vite build failed");
  return dist;
}

async function preview(dist: string): Promise<ChildProcess> {
  const server = spawn("npx", ["vite", "preview", "--outDir", dist, "--port", String(port), "--strictPort", "--host", "127.0.0.1"], {
    cwd: WEB_ROOT,
    stdio: "ignore",
  });
  for (let tries = 0; tries < 60; tries += 1) {
    try {
      if ((await fetch(site)).ok) return server;
    } catch {
      // not up yet
    }
    await new Promise((done) => setTimeout(done, 500));
  }
  server.kill();
  throw new Error(`vite preview did not answer on ${site}`);
}

type Row = {
  path: string;
  expected: string;
  chip: string;
  banner: string;
  store: string;
  apiReads: string[];
  mutation: string;
  posts: string[];
  screenshot: string;
};

// Software GL keeps the main thread busy, so a read of the page gets a generous timeout.
async function textOf(page: Page, selector: string): Promise<string> {
  const element = page.locator(selector).first();
  if (!(await element.count())) return "—";
  // Child by child, so the banner reads "DEMO · Synthetic… · Open the live twin".
  const text = await element.evaluate(
    (node) => (node.children.length ? [...node.children].map((child) => child.textContent).join(" · ") : node.textContent),
    undefined,
    { timeout: 30_000 },
  );
  return (text ?? "").trim() || "—";
}

/** Switches to the Simulation view and presses Accept, if the page has a simulation to accept. */
async function accept(page: Page): Promise<string> {
  const simulation = page.getByRole("radio", { name: /^Simulation/ });
  try {
    await simulation.waitFor({ timeout: 20_000 });
    for (let tries = 0; await simulation.isDisabled(); tries += 1) {
      if (tries >= 40) throw new Error("no simulation open: the Simulation view stayed disabled");
      await page.waitForTimeout(500);
    }
    await simulation.click({ force: true, timeout: 10_000 });
    const button = page.getByRole("button", { name: "Accept", exact: true });
    await button.waitFor({ timeout: 20_000 });
    await button.click({ force: true, timeout: 10_000 });
  } catch (error) {
    return `no Accept pressed (${(error as Error).message.split("\n")[0]})`;
  }
  // Let the review settle and its toast show.
  await page.waitForTimeout(4000);
  return "Accept pressed";
}

async function run(page: Page, route: (typeof ROUTES)[number], index: number): Promise<Row> {
  const requests: Request[] = [];
  page.on("request", (request) => requests.push(request));
  await page.goto(`${site}${route.path}`, { waitUntil: "domcontentloaded" });
  await page.locator(".twin-header").waitFor({ timeout: 30_000 });
  // Two polls of the Live Twin and the simulation feed (TWIN_POLL_MS is 5 s).
  await page.waitForTimeout(11_000);

  const chip = await textOf(page, ".twin-header-source");
  const banner = await textOf(page, ".twin-demo-banner");
  const store = await textOf(page, ".twin-header-store");
  const name = route.path.replace(/[/?=]+/g, "_").replace(/^_|_$/g, "") || "root";
  const screenshot = join(out, `${index + 1}-${name}.png`);
  await page.screenshot({ path: screenshot, timeout: 120_000 });

  const before = requests.length;
  const mutation = await accept(page);
  const posts = requests
    .slice(before)
    .filter((request) => request.method() !== "GET")
    .map((request) => `${request.method()} ${request.url()}`);
  if (mutation === "Accept pressed") {
    await page.screenshot({ path: screenshot.replace(/\.png$/, "-after-accept.png"), timeout: 120_000 });
  }

  const apiReads = [
    ...new Set(
      requests
        .filter((request) => request.url().startsWith(api))
        .map((request) => `${request.method()} ${new URL(request.url()).pathname}`),
    ),
  ];
  return { path: route.path, expected: route.expected, chip, banner, store, apiReads, mutation, posts, screenshot };
}

const dist = option("--dist") ? resolve(option("--dist")!) : build();
const server = await preview(dist);
const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const rows: Row[] = [];
try {
  for (const [index, route] of ROUTES.entries()) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await context.route(`${api}/**`, async (request) => {
      const url = new URL(request.request().url());
      const body = request.request().method() === "GET" ? stubBody(url.pathname) : null;
      if (body === null) await request.abort("namenotresolved");
      else await request.fulfill({ json: body, headers: { "access-control-allow-origin": "*" } });
    });
    const page = await context.newPage();
    console.log(`open ${site}${route.path}`);
    const row = await run(page, route, index);
    console.log(JSON.stringify(row, null, 2));
    rows.push(row);
    await context.close();
  }
} finally {
  await browser.close();
  server.kill();
}

const opened = (row: Row) => (row.chip === "Demo data" ? "demo" : row.chip === "Live data" ? "live" : "?");
console.log(`\nbuild: ${dist} (VITE_ALLOW_DEMO=true, VITE_API_BASE_URL=${api}); screenshots: ${out}\n`);
console.log("| Route | Expected | Opened | Chip | Banner | Store | Requests to the API origin | Accept | Non-GET requests after Accept |");
console.log("|---|---|---|---|---|---|---|---|---|");
for (const row of rows) {
  const cells = [
    `\`${row.path}\``,
    row.expected,
    `${opened(row)}${opened(row) === row.expected ? "" : " (UNEXPECTED)"}`,
    row.chip,
    row.banner,
    row.store,
    row.apiReads.length ? row.apiReads.join(", ") : "none",
    row.mutation,
    row.posts.length ? row.posts.join(", ") : "none",
  ];
  console.log(`| ${cells.join(" | ")} |`);
}
process.exit(rows.every((row) => opened(row) === row.expected) ? 0 : 1);
