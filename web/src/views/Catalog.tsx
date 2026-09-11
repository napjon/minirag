import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, mergeProductsById } from "../api";
import type { Copy } from "../i18n";
import { dynamicLabel } from "../i18n";
import { CATEGORIES, type Envelope, type Finding, type Product } from "../types";
import { DataTable, Field, FindingsTable, JsonBlock, PanelState, StatusBadge, WarningList } from "../ui";
import type { Capability } from "../capabilities";

const SEARCH_LIMIT = 20;

export function Catalog({ t, lang, capabilities, onTarget }: { t: Copy; lang: "en" | "id"; capabilities: Set<Capability>; onTarget: (type: string, id: string) => void }) {
  const [products, setProducts] = useState<Product[]>([]);
  const [picked, setPicked] = useState<Product[]>([]);
  const selectorProducts = useMemo(() => mergeProductsById(products, picked), [products, picked]);

  function togglePicked(product: Product) {
    setPicked((current) => {
      if (current.some((item) => item.id === product.id)) {
        return current.filter((item) => item.id !== product.id);
      }
      if (current.length >= 6) return current;
      return [...current, product];
    });
  }

  return (
    <div className="stack">
      {capabilities.has("products.search") ? <SearchPanel t={t} lang={lang} onItems={setProducts} onTarget={onTarget} /> : null}
      {capabilities.has("products.compare") ? <ComparePanel
        t={t}
        lang={lang}
        products={selectorProducts}
        selected={picked}
        onToggle={togglePicked}
        onTarget={onTarget}
      /> : null}
      {capabilities.has("products.references") ? <ReferencesPanel t={t} lang={lang} products={selectorProducts} onTarget={onTarget} /> : null}
      {capabilities.has("listing_checks") ? <ChecksPanel t={t} lang={lang} products={selectorProducts} onTarget={onTarget} /> : null}
    </div>
  );
}

function SearchPanel({
  t,
  lang,
  onItems,
  onTarget,
}: {
  t: Copy;
  lang: "en" | "id";
  onItems: (items: Product[]) => void;
  onTarget: (type: string, id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [minPrice, setMinPrice] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [location, setLocation] = useState("");
  const [availableOnly, setAvailableOnly] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [envelope, setEnvelope] = useState<Envelope<{ items: Product[] }> | null>(null);

  async function runSearch(body: Record<string, unknown>) {
    setLoading(true);
    setError(null);
    try {
      const result = await api.productSearch(body);
      setEnvelope(result);
      onItems(result.result?.items ?? []);
      onTarget("product_search", result.request_id);
    } catch (err) {
      setEnvelope(null);
      onItems([]);
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .productSearch({ query: "", limit: SEARCH_LIMIT, available_only: true })
      .then((result) => {
        if (cancelled) return;
        setEnvelope(result);
        onItems(result.result?.items ?? []);
      })
      .catch((err) => {
        if (cancelled) return;
        setEnvelope(null);
        onItems([]);
        setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // Initial catalog table only.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    await runSearch({
      query,
      category: category || null,
      min_price: minPrice || null,
      max_price: maxPrice || null,
      location: location || null,
      available_only: availableOnly,
      limit: SEARCH_LIMIT,
    });
  }

  const items = envelope?.result?.items ?? [];

  return (
    <section className="card">
      <h2>{t.products}</h2>
      <form className="form" onSubmit={onSubmit}>
        <div className="row wrap">
          <Field label={t.query}>
            <input value={query} onChange={(event) => setQuery(event.target.value)} />
          </Field>
          <Field label={t.category}>
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              <option value="">{t.anyCategory}</option>
              {CATEGORIES.map((item) => (
                <option key={item} value={item}>
                  {dynamicLabel(lang, item)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t.minPrice}>
            <input value={minPrice} onChange={(event) => setMinPrice(event.target.value)} inputMode="decimal" />
          </Field>
          <Field label={t.maxPrice}>
            <input value={maxPrice} onChange={(event) => setMaxPrice(event.target.value)} inputMode="decimal" />
          </Field>
          <Field label={t.location}>
            <input
              value={location}
              onChange={(event) => setLocation(event.target.value)}
              placeholder={t.anyLocation}
            />
          </Field>
          <label className="check">
            <input
              type="checkbox"
              checked={availableOnly}
              onChange={(event) => setAvailableOnly(event.target.checked)}
            />
            {t.availableOnly}
          </label>
          <button type="submit" className="primary" disabled={loading}>
            {t.runSearch}
          </button>
        </div>
      </form>
      <PanelState t={t} loading={loading} error={error} empty={!envelope} emptyText={t.emptySearch}>
        {envelope ? (
          <div className="result">
            <WarningList t={t} warnings={envelope.warnings} />
            <DataTable lang={lang}
              rows={items.map((item) => ({
                sku: item.sku,
                title: item.title,
                category: item.category,
                list_price: item.list_price,
                location: item.location,
                score: item.score,
                reasons: (item.reasons ?? []).join(", "),
              }))}
            />
          </div>
        ) : null}
      </PanelState>
    </section>
  );
}

function ComparePanel({
  t,
  lang,
  products,
  selected,
  onToggle,
  onTarget,
}: {
  t: Copy;
  lang: "en" | "id";
  products: Product[];
  selected: Product[];
  onToggle: (product: Product) => void;
  onTarget: (type: string, id: string) => void;
}) {
  const selectedIds = selected.map((item) => item.id);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [envelope, setEnvelope] = useState<Envelope<import("../types").CompareResult> | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const result = await api.productCompare(selectedIds);
      setEnvelope(result);
      onTarget("product_compare", result.request_id);
    } catch (err) {
      setEnvelope(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="card">
      <h2>{t.compare}</h2>
      <p className="muted">
        {t.selectProducts} — {selected.length} {t.selected}
      </p>
      <form className="form" onSubmit={onSubmit}>
        <ul className="check-list">
          {products.map((product) => (
            <li key={product.id}>
              <label>
                <input
                  type="checkbox"
                  checked={selectedIds.includes(product.id)}
                  onChange={() => onToggle(product)}
                />
                {product.sku} · {product.title}
              </label>
            </li>
          ))}
        </ul>
        <button type="submit" className="primary" disabled={loading || selected.length < 2}>
          {t.runCompare}
        </button>
      </form>
      <PanelState
        t={t}
        loading={loading}
        error={error}
        empty={!envelope}
        emptyText={t.emptyCompare}
      >
        {envelope?.result ? (
          <div className="result">
            <WarningList t={t} warnings={envelope.warnings} />
            {envelope.result.missing?.length ? (
              <p className="muted">
                {t.missing}: {envelope.result.missing.join(", ")}
              </p>
            ) : null}
            <DataTable lang={lang}
              rows={(envelope.result.products ?? []).map((item) => ({
                sku: item.sku,
                title: item.title,
                category: item.category,
                list_price: item.list_price,
                location: item.location,
                ...item.attributes,
              }))}
            />
          </div>
        ) : null}
      </PanelState>
    </section>
  );
}

function ReferencesPanel({
  t,
  lang,
  products,
  onTarget,
}: {
  t: Copy;
  lang: "en" | "id";
  products: Product[];
  onTarget: (type: string, id: string) => void;
}) {
  const [productId, setProductId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [envelope, setEnvelope] = useState<Envelope<Record<string, unknown>> | null>(null);

  useEffect(() => {
    if (!products.some((item) => item.id === productId)) {
      setProductId(products[0]?.id ?? "");
    }
  }, [products, productId]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const result = await api.productReferences(productId);
      setEnvelope(result);
      onTarget("product", productId);
    } catch (err) {
      setEnvelope(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  const result = envelope?.result ?? null;
  const status = String(result?.status ?? envelope?.status ?? "");

  return (
    <section className="card">
      <h2>{t.references}</h2>
      <form className="form row" onSubmit={onSubmit}>
        <Field label={t.products}>
          <select value={productId} onChange={(event) => setProductId(event.target.value)}>
            {products.map((product) => (
              <option key={product.id} value={product.id}>
                {product.sku} · {product.title}
              </option>
            ))}
          </select>
        </Field>
        <button type="submit" className="primary" disabled={loading || !productId}>
          {t.loadReferences}
        </button>
      </form>
      <PanelState t={t} loading={loading} error={error} empty={!envelope} emptyText={t.emptyRefs}>
        {result ? (
          <div className="result">
            <StatusBadge status={status} lang={lang} />
            <WarningList t={t} warnings={envelope?.warnings} />
            {"warning" in result && result.warning ? <p className="limitations">{String(result.warning)}</p> : null}
            {status === "range" ? (
              <p>
                {t.range}: {String(result.median)} ({String(result.q1)} – {String(result.q3)}) · n=
                {String(result.sample_count)}
              </p>
            ) : null}
            {status === "insufficient_comparables" ? <p>{t.insufficient}</p> : null}
            <JsonBlock value={result} />
          </div>
        ) : null}
      </PanelState>
    </section>
  );
}

function ChecksPanel({
  t,
  lang,
  products,
  onTarget,
}: {
  t: Copy;
  lang: "en" | "id";
  products: Product[];
  onTarget: (type: string, id: string) => void;
}) {
  const [productId, setProductId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [envelope, setEnvelope] = useState<Envelope<Finding[]> | null>(null);

  useEffect(() => {
    if (!products.some((item) => item.id === productId)) {
      setProductId(products[0]?.id ?? "");
    }
  }, [products, productId]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const result = await api.listingChecks(productId);
      setEnvelope(result);
      const first = result.result?.[0];
      onTarget("finding", first?.id ?? result.request_id);
    } catch (err) {
      setEnvelope(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  const findings = envelope?.result ?? [];

  return (
    <section className="card">
      <h2>{t.listingChecks}</h2>
      <form className="form row" onSubmit={onSubmit}>
        <Field label={t.products}>
          <select value={productId} onChange={(event) => setProductId(event.target.value)}>
            {products.map((product) => (
              <option key={product.id} value={product.id}>
                {product.sku} · {product.title}
              </option>
            ))}
          </select>
        </Field>
        <button type="submit" className="primary" disabled={loading || !productId}>
          {t.runChecks}
        </button>
      </form>
      <PanelState t={t} loading={loading} error={error} empty={!envelope} emptyText={t.emptyChecks}>
        {envelope ? (
          <div className="result">
            <WarningList t={t} warnings={envelope.warnings} />
            <FindingsTable t={t} lang={lang} findings={findings} />
          </div>
        ) : null}
      </PanelState>
    </section>
  );
}
