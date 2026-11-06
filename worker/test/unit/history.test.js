// /history.json: D1-backed read-only history (docs/TOPICS.md). Fake D1 binding; no network.
import { describe, expect, it } from "vitest";
import worker from "../../src/index.js";

function fakeDb(rows, fail = false) {
  return {
    prepare: (sql) => ({
      bind: (limit) => ({
        all: async () => {
          if (fail) throw new Error("D1_ERROR: no such table: episodes");
          expect(sql).toMatch(/SELECT entry FROM episodes ORDER BY ts DESC LIMIT \?/);
          return { results: rows.slice(0, limit) };
        },
      }),
    }),
  };
}

const entry = (run_id, ts) => JSON.stringify({ run_id, ts, topic: "agent-harnesses", stories: [{ url: "https://x/" + run_id }] });

describe("/history.json", () => {
  it("returns the newest entries as JSON with CORS and no-store", async () => {
    const env = { DB: fakeDb([{ entry: entry("2", "2026-11-06T14:00:00Z") }, { entry: entry("1", "2026-11-06T11:00:00Z") }, { entry: "not json" }]) };
    const res = await worker.fetch(new Request("https://w/history.json?limit=5"), env);
    expect(res.status).toBe(200);
    expect(res.headers.get("access-control-allow-origin")).toBe("*");
    expect(res.headers.get("cache-control")).toBe("no-store");
    const body = await res.json();
    expect(body.count).toBe(2);
    expect(body.episodes.map((e) => e.run_id)).toEqual(["2", "1"]);
  });
  it("clamps limit and 404s without a binding, 503s on a database error", async () => {
    const res404 = await worker.fetch(new Request("https://w/history.json"), {});
    expect(res404.status).toBe(404);
    const res503 = await worker.fetch(new Request("https://w/history.json"), { DB: fakeDb([], true) });
    expect(res503.status).toBe(503);
    const rows = Array.from({ length: 300 }, (_, i) => ({ entry: entry(String(i), "2026-11-06T00:00:00Z") }));
    const big = await (await worker.fetch(new Request("https://w/history.json?limit=9999"), { DB: fakeDb(rows) })).json();
    expect(big.count).toBe(200);
  });
});
