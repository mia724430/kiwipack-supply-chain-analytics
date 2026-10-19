-- dim_supplier
DROP VIEW IF EXISTS dim_supplier;
CREATE VIEW dim_supplier AS
SELECT vendor_code AS supplier_id, vendor_name AS supplier_name, country
FROM clean_vendor_master;

-- dim_category
DROP VIEW IF EXISTS dim_category;
CREATE VIEW dim_category AS
SELECT item_group, category_name, budget_category
FROM clean_category;

-- dim_material: item master enriched with the category name
DROP VIEW IF EXISTS dim_material;
CREATE VIEW dim_material AS
SELECT
  i.item_code        AS material_id,
  i.item_name        AS material_name,
  i.item_group,
  c.category_name,
  i.uom,
  i.std_cost,
  i.vendor_code      AS primary_supplier_id,
  i.lead_time_days,
  i.safety_stock,
  i.reorder_point,
  i.moq,
  i.item_status
FROM clean_item_master i
LEFT JOIN clean_category c ON i.item_group = c.item_group;

SELECT COUNT(*) FROM dim_supplier;   -- expect 8
SELECT COUNT(*) FROM dim_category;   -- expect 5
SELECT * FROM dim_material LIMIT 5;  -- category_name should be filled in

-- fact_purchase_order_line (grain: one PO line)
DROP VIEW IF EXISTS fact_purchase_order_line;
CREATE VIEW fact_purchase_order_line AS
SELECT
  po_line_id, po_number, line_no, requisition_no,
  requisition_date, po_date, promised_date,
  vendor_code AS supplier_id,
  item_code   AS material_id,
  order_qty, unit_price, line_amount, line_status
FROM clean_purchase_orders;

-- fact_goods_receipt (grain: one delivery)
DROP VIEW IF EXISTS fact_goods_receipt;
CREATE VIEW fact_goods_receipt AS
SELECT
  grn_no AS receipt_id, po_line_id, receipt_date,
  received_qty, rejected_qty, accepted_qty
FROM clean_goods_receipts;

-- fact_inventory_snapshot (grain: one material per month-end)
DROP VIEW IF EXISTS fact_inventory_snapshot;
CREATE VIEW fact_inventory_snapshot AS
SELECT
  month_date AS snapshot_month, item_code AS material_id,
  qty_on_hand, std_cost, stock_value
FROM clean_stock_on_hand;

-- fact_consumption (grain: one material per month)
DROP VIEW IF EXISTS fact_consumption;
CREATE VIEW fact_consumption AS
SELECT month_date, item_code AS material_id, qty_issued AS actual_qty
FROM clean_consumption;

SELECT 'dim_supplier' AS object, COUNT(*) AS rows_count FROM dim_supplier
UNION ALL SELECT 'dim_category', COUNT(*) FROM dim_category
UNION ALL SELECT 'dim_material', COUNT(*) FROM dim_material
UNION ALL SELECT 'fact_purchase_order_line', COUNT(*) FROM fact_purchase_order_line
UNION ALL SELECT 'fact_goods_receipt', COUNT(*) FROM fact_goods_receipt
UNION ALL SELECT 'fact_inventory_snapshot', COUNT(*) FROM fact_inventory_snapshot
UNION ALL SELECT 'fact_consumption', COUNT(*) FROM fact_consumption;