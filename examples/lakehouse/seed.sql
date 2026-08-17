-- The bronze layer: what the two shops and the CRM actually landed, before
-- bloomery touches anything. Every column name here is one a mapping names in
-- its `from:` — that correspondence is the whole contract between a bronze
-- table and a mapping.
--
-- Run through Trino:
--   docker exec -i bloomery-lakehouse-trino-1 trino -f /dev/stdin < seed.sql

CREATE SCHEMA IF NOT EXISTS iceberg.bronze;

DROP TABLE IF EXISTS iceberg.bronze.shopify__order_lines;
DROP TABLE IF EXISTS iceberg.bronze.woo__order_lines;
DROP TABLE IF EXISTS iceberg.bronze.crm__customers;

-- The platform shop. `gift_note` exists here and nowhere else, which is why
-- the other branch of the union projects a typed NULL for it.
CREATE TABLE iceberg.bronze.shopify__order_lines AS
SELECT * FROM (VALUES
  ('SH-1001', BIGINT '1', 'C-001', 'SKU-RED-M',   BIGINT '2', DECIMAL '39.98', '2026-01-04 10:15:00', 'happy birthday'),
  ('SH-1001', BIGINT '2', 'C-001', 'SKU-BLU-L',   BIGINT '1', DECIMAL '24.99', '2026-01-04 10:15:00', NULL),
  ('SH-1002', BIGINT '1', 'C-002', 'SKU-GRN-S',   BIGINT '3', DECIMAL '59.97', '2026-01-05 09:02:00', NULL),
  ('SH-1003', BIGINT '1', 'C-003', 'SKU-RED-M',   BIGINT '1', DECIMAL '19.99', '2026-02-11 16:40:00', 'gift wrap please')
) AS t (order_id, position, customer_id, variant_sku, quantity, line_total, created_at, gift_note);

-- The legacy shop being migrated away from. Different column names for the
-- same concepts, disjoint order ids, and no gift-note concept at all.
CREATE TABLE iceberg.bronze.woo__order_lines AS
SELECT * FROM (VALUES
  ('WOO-5001', BIGINT '1', 'C-002', 'SKU-BLU-L', BIGINT '1', DECIMAL '24.99', '2026-01-06 12:00:00'),
  ('WOO-5002', BIGINT '1', 'C-004', 'SKU-YEL-XL', BIGINT '2', DECIMAL '49.98', '2026-02-02 08:30:00'),
  ('WOO-5002', BIGINT '2', 'C-004', 'SKU-RED-M', BIGINT '1', DECIMAL '19.99', '2026-02-02 08:30:00')
) AS t (order_number, item_index, buyer_ref, product_sku, qty, line_amount, placed_at);

-- The CRM. `C-003` has an email that is not an address — the quality rule
-- flags that row rather than dropping it, so the count stays honest and the
-- flag travels into the quality mart.
--
-- The three `_`-prefixed columns are the ingestion-metadata contract an entity
-- that quarantines requires: a stable identity per source row, so a rejected
-- row can be pointed back at its origin and replayed.
CREATE TABLE iceberg.bronze.crm__customers AS
SELECT * FROM (VALUES
  ('C-001', 'ada@example.com',   'consumer', '2025-11-02 09:00:00', TIMESTAMP '2026-01-01 00:00:00', 'load-001', 'crm-1'),
  ('C-002', 'GRACE@EXAMPLE.COM', 'business', '2025-12-14 14:30:00', TIMESTAMP '2026-01-01 00:00:00', 'load-001', 'crm-2'),
  ('C-003', 'not-an-email',      'consumer', '2026-01-03 11:45:00', TIMESTAMP '2026-01-01 00:00:00', 'load-001', 'crm-3'),
  ('C-004', 'linus@example.com', 'business', '2026-01-20 17:05:00', TIMESTAMP '2026-01-01 00:00:00', 'load-001', 'crm-4'),
  -- `signed_up_at` cannot be parsed as a timestamp. bloomery generates a
  -- `coercible` rule per column for an entity in the quality system — "the
  -- projection is NULL although every source it read was not" — and that rule
  -- defaults to *quarantine*. So this row does not become a silent NULL and it
  -- does not join `silver.customer`: it lands in `silver.customer__reject`
  -- with its raw payload, ready to be replayed once the source is fixed.
  ('C-005', 'edsger@example.com', 'consumer', 'last tuesday', TIMESTAMP '2026-01-01 00:00:00', 'load-001', 'crm-5')
) AS t (id, email_address, segment, created_at, _ingested_at, _load_id, _source_row_id);
