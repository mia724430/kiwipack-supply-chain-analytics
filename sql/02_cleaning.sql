-- Step 1: remove exact duplicate rows
SELECT COUNT(*) AS unique_lines
FROM (
	SELECT DISTINCT *
	FROM raw_purchase_orders rpo 
);

-- Step 2: remove duplicates, then convert dates to yyyy-mm-dd
WITH dedup AS (
	SELECT DISTINCT *
	FROM raw_purchase_orders rpo 
)
SELECT 
	"PO Number",
	"Line",
	"Requisition Date",
	substr(NULLIF("Requisition Date", ''), 7, 4) || '-' ||
	substr(NULLIF("Requisition Date", ''), 4, 2) || '-' ||
  	substr(NULLIF("Requisition Date", ''), 1, 2)  AS requisition_date,
  	substr("PO Date", 7, 4) || '-' || substr("PO Date", 4, 2) || '-' || substr("PO Date", 1, 2) AS po_date,
  	substr("Confirmed Delivery", 7, 4) || '-' || substr("Confirmed Delivery", 4, 2) || '-' || substr("Confirmed Delivery", 1, 2) AS promised_date
FROM dedup
LIMIT 10;

-- Step 3: dedup + dates + tidy columns
WITH dedup AS (
  SELECT DISTINCT *
  FROM raw_purchase_orders
)
SELECT
  CAST("PO Number" AS TEXT) || '-' || "Line"  AS po_line_id,
  CAST("PO Number" AS TEXT)                   AS po_number,
  "Line"                                      AS line_no,
  NULLIF("Requisition No", '')                AS requisition_no,
  substr(NULLIF("Requisition Date", ''), 7, 4) || '-' ||
  substr(NULLIF("Requisition Date", ''), 4, 2) || '-' ||
  substr(NULLIF("Requisition Date", ''), 1, 2) AS requisition_date,
  substr("PO Date", 7, 4) || '-' || substr("PO Date", 4, 2) || '-' || substr("PO Date", 1, 2) AS po_date,
  substr("Confirmed Delivery", 7, 4) || '-' || substr("Confirmed Delivery", 4, 2) || '-' || substr("Confirmed Delivery", 1, 2) AS promised_date,
  "Vendor"       AS vendor_code,
  "Item"         AS item_code,
  "Order Qty"    AS order_qty,
  "Unit Price"   AS unit_price,
  "Line Amount"  AS line_amount,
  CASE "Line Status"
    WHEN 'CL' THEN 'Closed'
    WHEN 'PR' THEN 'Partially Received'
    WHEN 'OP' THEN 'Open'
  END            AS line_status
FROM dedup;

-- Step 4: build clean_purchase_orders
DROP TABLE IF EXISTS clean_purchase_orders;
CREATE TABLE clean_purchase_orders AS
WITH dedup AS (
  SELECT DISTINCT *
  FROM raw_purchase_orders
)
SELECT
  CAST("PO Number" AS TEXT) || '-' || "Line"  AS po_line_id,
  CAST("PO Number" AS TEXT)                   AS po_number,
  "Line"                                      AS line_no,
  NULLIF("Requisition No", '')                AS requisition_no,
  substr(NULLIF("Requisition Date", ''), 7, 4) || '-' ||
  substr(NULLIF("Requisition Date", ''), 4, 2) || '-' ||
  substr(NULLIF("Requisition Date", ''), 1, 2) AS requisition_date,
  substr("PO Date", 7, 4) || '-' || substr("PO Date", 4, 2) || '-' || substr("PO Date", 1, 2) AS po_date,
  substr("Confirmed Delivery", 7, 4) || '-' || substr("Confirmed Delivery", 4, 2) || '-' || substr("Confirmed Delivery", 1, 2) AS promised_date,
  "Vendor"       AS vendor_code,
  "Item"         AS item_code,
  "Order Qty"    AS order_qty,
  "Unit Price"   AS unit_price,
  "Line Amount"  AS line_amount,
  CASE "Line Status"
    WHEN 'CL' THEN 'Closed'
    WHEN 'PR' THEN 'Partially Received'
    WHEN 'OP' THEN 'Open'
  END            AS line_status
FROM dedup;

-- Check clean_purchase_orders against control totals
SELECT
  COUNT(*)                    AS po_lines,        -- expect 670
  COUNT(DISTINCT po_number)   AS po_numbers,      -- expect 623
  ROUND(SUM(line_amount), 2)  AS total_amount,    -- expect 6380468.13
  COUNT(requisition_no)       AS lines_with_pr,   -- expect 642 (670 - 28)
  MIN(po_date)                AS earliest,        -- expect Jan 2025
  MAX(po_date)                AS latest           -- expect by Jun 2026
FROM clean_purchase_orders;

-- clean_purchase_orders: 670 lines, $6,380,468.13 - reconciled to control totals.

-- Build clean_goods_receipts
DROP TABLE IF EXISTS clean_goods_receipts;

CREATE TABLE clean_goods_receipts AS
SELECT
  "GRN No"                                      AS grn_no,
  CAST("PO Number" AS TEXT) || '-' || "PO Line" AS po_line_id,
  substr("GRN Date", 7, 4) || '-' || substr("GRN Date", 4, 2) || '-' || substr("GRN Date", 1, 2) AS receipt_date,
  "Qty Received"                                AS received_qty,
  COALESCE("Qty Rejected", 0)                   AS rejected_qty,
  "Qty Received" - COALESCE("Qty Rejected", 0)  AS accepted_qty
FROM raw_goods_receipts;

SELECT
  COUNT(*)                                    AS receipts,        -- expect 678
  SUM(CASE WHEN rejected_qty > 0 THEN 1 END)  AS with_rejection,  -- expect 583
  MIN(receipt_date)                           AS earliest,        -- expect 2025-01-xx
  MAX(receipt_date)                           AS latest           -- expect 2026-06-xx at the latest
FROM clean_goods_receipts;

SELECT COUNT(*) AS orphan_receipts               -- expect 0
FROM clean_goods_receipts r
LEFT JOIN clean_purchase_orders p ON r.po_line_id = p.po_line_id
WHERE p.po_line_id IS NULL;

-- Clean_vendor_master
DROP TABLE IF EXISTS clean_vendor_master;

CREATE TABLE clean_vendor_master AS
SELECT
  TRIM("VendorCode")  AS vendor_code,
  TRIM("VendorName")  AS vendor_name,
  CASE "Country"
    WHEN 'NZ' THEN 'New Zealand'
    WHEN 'AU' THEN 'Australia'
    WHEN 'CN' THEN 'China'
  END                 AS country,
  "PaymentTerms"      AS payment_terms
FROM raw_vendor_master;

SELECT 
	COUNT(*) AS vendors
FROM clean_vendor_master cvm;
	

-- Clean_item_master
DROP TABLE IF EXISTS clean_item_master;

CREATE TABLE clean_item_master AS
SELECT
  TRIM("ItemCode")    AS item_code,
  TRIM("Description") AS item_name,
  "ItemGroup"         AS item_group,
  "BaseUoM"           AS uom,
  "StdCost"           AS std_cost,
  "PrefVendor"        AS vendor_code,
  "LeadTimeDays"      AS lead_time_days,
  "SafetyStock"       AS safety_stock,
  "ReorderPoint"      AS reorder_point,
  "MOQ"               AS moq,
  "ItemStatus"        AS item_status
FROM raw_item_master;

SELECT 
	COUNT(*) AS items
FROM clean_item_master cim;

SELECT COUNT(*) AS orphan_vendors               -- expect 0
FROM clean_purchase_orders cpo 
LEFT JOIN clean_vendor_master cvm  ON cpo.vendor_code  = cvm.vendor_code 
WHERE cvm.vendor_code IS NULL;

-- Clean_stock_on_hand
DROP TABLE IF EXISTS clean_stock_on_hand;

CREATE TABLE clean_stock_on_hand AS
SELECT
  substr("Period", 1, 4) || '-' || substr("Period", 5, 2) || '-01' AS month_date,
  TRIM("Item")        AS item_code,
  "Qty On Hand"       AS qty_on_hand,
  "Std Cost"          AS std_cost,
  "Qty On Hand" * "Std Cost" AS stock_value
FROM raw_stock_on_hand;

-- Clean_consumption
DROP TABLE IF EXISTS clean_consumption;

CREATE TABLE clean_consumption AS
SELECT
  substr("Period", 1, 4) || '-' || substr("Period", 5, 2) || '-01' AS month_date,
  TRIM("Item")        AS item_code,
  "Qty Issued"        AS qty_issued
FROM raw_consumption;

-- Check angainst the control totals
SELECT ROUND(SUM(stock_value), 2) AS stock_value     -- expect 201932.36
FROM clean_stock_on_hand
WHERE month_date = '2026-06-01';

SELECT ROUND(SUM(c.qty_issued * i.std_cost), 2) AS consumption_value   -- expect 6702344.22
FROM clean_consumption c
JOIN clean_item_master i ON c.item_code = i.item_code;

-- Clean_category
DROP TABLE IF EXISTS clean_category;

CREATE TABLE clean_category (
  item_group       TEXT PRIMARY KEY,
  category_name    TEXT,
  budget_category  TEXT
);

INSERT INTO clean_category (item_group, category_name, budget_category) VALUES
  ('PB',  'Paperboard', 'Paperboard'),
  ('CT',  'Coating',    'Coatings'),
  ('INK', 'Ink',        'Inks'),
  ('LID', 'Lids',       'Lids & Closures'),
  ('PKG', 'Packaging',  'Packaging Materials');

SELECT COUNT(*) AS unmapped_items                 -- expect 0
FROM clean_item_master i
LEFT JOIN clean_category c ON i.item_group = c.item_group
WHERE c.item_group IS NULL;
