import { strict as assert } from "node:assert";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { messages } from "./i18n";
import { PanelState, ResultChart } from "./ui";

test("line charts expose a localized accessible name and data description", () => {
  const markup = renderToStaticMarkup(
    <ResultChart
      rows={[{ month: "2030-01", total: 42 }]}
      mode="line"
      label="Grafik analitik operasional"
      description="Titik data: 1"
    />,
  );
  assert.match(markup, /role="img"/);
  assert.match(markup, /aria-label="Grafik analitik operasional"/);
  assert.match(markup, /<title>Grafik analitik operasional<\/title>/);
  assert.match(markup, /Titik data: 1/);
});

test("completed asynchronous panels announce that results are ready", () => {
  const markup = renderToStaticMarkup(
    <PanelState t={messages.id} emptyText=""><p>42</p></PanelState>,
  );
  assert.match(markup, /role="status"/);
  assert.match(markup, /aria-live="polite"/);
  assert.match(markup, /Hasil siap/);
});
