-- Q1a: On-time delivery rate by supplier
WITH first_receipt AS (
  SELECT po_line_id, MIN(receipt_date) AS first_receipt_date
  FROM fact_goods_receipt
  GROUP BY po_line_id
)
SELECT
  s.supplier_name,
  COUNT(*) AS delivered_lines,
  SUM(CASE WHEN f.first_receipt_date <= p.promised_date THEN 1 ELSE 0 END) AS on_time_lines,
  ROUND(100.0 * SUM(CASE WHEN f.first_receipt_date <= p.promised_date THEN 1 ELSE 0 END)
        / COUNT(*), 1) AS otd_pct
FROM fact_purchase_order_line p
JOIN first_receipt f ON p.po_line_id = f.po_line_id
JOIN dim_supplier s  ON p.supplier_id = s.supplier_id
GROUP BY s.supplier_name
ORDER BY otd_pct;

-- Q1b: OTD by supplier and half-year
WITH first_receipt AS (
  SELECT po_line_id, MIN(receipt_date) AS first_receipt_date
  FROM fact_goods_receipt
  GROUP BY po_line_id
)
SELECT
  s.supplier_name,
  substr(p.promised_date, 1, 4) ||
    CASE WHEN substr(p.promised_date, 6, 2) <= '06' THEN '-H1' ELSE '-H2' END AS half_year,
  COUNT(*) AS delivered_lines,
  ROUND(100.0 * SUM(CASE WHEN f.first_receipt_date <= p.promised_date THEN 1 ELSE 0 END)
        / COUNT(*), 1) AS otd_pct
FROM fact_purchase_order_line p
JOIN first_receipt f ON p.po_line_id = f.po_line_id
JOIN dim_supplier s  ON p.supplier_id = s.supplier_id
GROUP BY s.supplier_name, half_year
ORDER BY s.supplier_name, half_year;

-- Q1c: OTIF by supplier and half-year
-- A PO line passes OTIF if the qty received by the promised date >= qty ordered.
-- Includes lines that were due but not delivered (they fail).
WITH received_by_promise AS (
  SELECT r.po_line_id, SUM(r.received_qty) AS qty_by_promise
  FROM fact_goods_receipt r
  JOIN fact_purchase_order_line p ON r.po_line_id = p.po_line_id
  WHERE r.receipt_date <= p.promised_date
  GROUP BY r.po_line_id
)
SELECT
  s.supplier_name,
  substr(p.promised_date, 1, 4) ||
    CASE WHEN substr(p.promised_date, 6, 2) <= '06' THEN '-H1' ELSE '-H2' END AS half_year,
  COUNT(*) AS due_lines,
  SUM(CASE WHEN COALESCE(o.qty_by_promise, 0) >= p.order_qty THEN 1 ELSE 0 END) AS otif_lines,
  ROUND(100.0 * SUM(CASE WHEN COALESCE(o.qty_by_promise, 0) >= p.order_qty THEN 1 ELSE 0 END)
        / COUNT(*), 1) AS otif_pct
FROM fact_purchase_order_line p
LEFT JOIN received_by_promise o ON p.po_line_id = o.po_line_id
JOIN dim_supplier s ON p.supplier_id = s.supplier_id
WHERE p.promised_date <= '2026-06-30'
GROUP BY s.supplier_name, half_year
ORDER BY s.supplier_name, half_year;
-- FINDING Q1: Pacific Board OTIF fell 84% -> 65% -> 60% (2025-H1 to 2026-H1).
-- OTD alone hid this (overdue undelivered lines and partials excluded).
-- Southern Board NZ (same grade, ~8.5% dearer) stayed at 94-100%.
-- Coral Fibre also weak (69-88%), but no clear trend.

-- Q2: Purchase Price Variance (PPV) by category and half-year
-- PPV = (actual unit price - standard cost) x qty. Positive = paid more than standard.
SELECT
  m.category_name,
  substr(p.po_date, 1, 4) ||
    CASE WHEN substr(p.po_date, 6, 2) <= '06' THEN '-H1' ELSE '-H2' END AS half_year,
  ROUND(SUM(p.line_amount), 0)                                   AS spend,
  ROUND(SUM((p.unit_price - m.std_cost) * p.order_qty), 0)       AS ppv,
  ROUND(100.0 * SUM((p.unit_price - m.std_cost) * p.order_qty)
        / SUM(m.std_cost * p.order_qty), 1)                      AS ppv_pct
FROM fact_purchase_order_line p
JOIN dim_material m ON p.material_id = m.material_id
GROUP BY m.category_name, half_year
ORDER BY m.category_name, half_year;
-- FINDING Q2: Coating PPV jumped from ~0% to ~9-10% from 2025-H2 (~$33k unfavourable).
-- All other categories within +/-1% of standard cost.
-- Standard cost for coatings is out of date -> renegotiate or update standard.

-- Q3: Dead stock - stock on hand at Jun 2026 with zero use in the last 6 months
WITH recent_use AS (
  SELECT material_id, SUM(actual_qty) AS qty_used_6m
  FROM fact_consumption
  WHERE month_date >= '2026-01-01'
  GROUP BY material_id
),
last_used AS (
  SELECT material_id, MAX(month_date) AS last_used_month
  FROM fact_consumption
  WHERE actual_qty > 0
  GROUP BY material_id
)
SELECT
  m.material_name,
  i.qty_on_hand,
  ROUND(i.stock_value, 0) AS stock_value,
  l.last_used_month
FROM fact_inventory_snapshot i
JOIN dim_material m   ON i.material_id = m.material_id
JOIN recent_use r     ON i.material_id = r.material_id
LEFT JOIN last_used l ON i.material_id = l.material_id
WHERE i.snapshot_month = '2026-06-01'
  AND r.qty_used_6m = 0
  AND i.qty_on_hand > 0
ORDER BY stock_value DESC;
-- FINDING Q3: 4 legacy lids unused since Jun 2025, holding ~$41k
-- = ~20% of total stock value ($202k). Candidates for write-off or clearance.

-- Q4: Stockout risk - materials below safety stock at Jun 2026
WITH received AS (
  SELECT po_line_id, SUM(received_qty) AS qty_received
  FROM fact_goods_receipt
  GROUP BY po_line_id
),
open_orders AS (
  SELECT
    p.material_id,
    SUM(p.order_qty - COALESCE(r.qty_received, 0))                   AS qty_on_order,
    SUM(CASE WHEN p.promised_date <= '2026-06-30' THEN 1 ELSE 0 END)  AS overdue_lines
  FROM fact_purchase_order_line p
  LEFT JOIN received r ON p.po_line_id = r.po_line_id
  WHERE p.line_status <> 'Closed'
  GROUP BY p.material_id
)
SELECT
  m.material_name,
  s.supplier_name,
  i.qty_on_hand,
  m.safety_stock,
  ROUND(100.0 * i.qty_on_hand / m.safety_stock, 0) AS pct_of_safety_stock,
  COALESCE(o.qty_on_order, 0)  AS qty_on_order,
  COALESCE(o.overdue_lines, 0) AS overdue_lines
FROM fact_inventory_snapshot i
JOIN dim_material m       ON i.material_id = m.material_id
JOIN dim_supplier s       ON m.primary_supplier_id = s.supplier_id
LEFT JOIN open_orders o   ON i.material_id = o.material_id
WHERE i.snapshot_month = '2026-06-01'
  AND i.qty_on_hand < m.safety_stock
ORDER BY pct_of_safety_stock;
-- FINDING Q4: 4 materials below safety stock at Jun 2026.
-- 3 of 4 come from the two weakest suppliers (Pacific Board x2, Coral Fibre),
-- each with an overdue open PO -> root cause is supplier delay (links to Q1).
-- Black Ink: no open PO -> reorder now.