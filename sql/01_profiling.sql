-- Query 0: row count vs control total (expect 670 unique)
SELECT COUNT(*) FROM raw_purchase_orders;

-- Query 1: duplicate PO lines
SELECT "PO Number", "Line", COUNT(*) AS copies
FROM raw_purchase_orders
GROUP BY "PO Number", "Line"
HAVING COUNT(*) > 1;

SELECT *
FROM raw_purchase_orders rpo 
WHERE "PO Number" = 4500010142 AND "Line" = 20;
-- FINDING 1: 6 PO lines duplicated (exact copies, 676 rows → 670 unique).
-- Impact: would overstate spend. Fix: remove with SELECT DISTINCT.


-- Query 2: vendor name variations
SELECT "Vendor", "Vendor Name", COUNT(*) AS lines
FROM raw_purchase_orders
GROUP BY "Vendor", "Vendor Name"
ORDER BY "Vendor";
-- FINDING 2: vendor names inconsistent - 8 codes, 15 name variants
-- (V1001 x4, V1005 x3 incl. trailing space, V1007 x3).
-- Impact: grouping by name splits one supplier into several.
-- Fix: use Vendor code; take name from raw_vendor_master.

-- Query 3: UoM variations
SELECT "UoM", COUNT(*) AS lines
FROM raw_purchase_orders rpo 
GROUP BY "UoM";

SELECT
  CASE UPPER("UoM")
    WHEN 'EACH' THEN 'EA'
    WHEN 'RL'   THEN 'ROLL'
    ELSE UPPER("UoM")
  END AS clean_uom,
  COUNT(*) AS lines
FROM raw_purchase_orders
GROUP BY clean_uom;
-- FINDING 3: UoM inconsistent - 3 real units typed 8 ways
-- (KG/Kg/kg, EA/ea/EACH, ROLL/RL).
-- Impact: filters/grouping by UoM miss rows.
-- Fix: use BaseUoM from raw_item_master.

-- Query 4: POs without a requisition
SELECT COUNT(*) AS lines_without_pr
FROM raw_purchase_orders rpo 
WHERE "Requisition No" IS NULL OR "Requisition No" = '';

SELECT "PO Number", "Line", "Requisition No", "Requisition Date", "PO Date", "Vendor"
FROM raw_purchase_orders
WHERE "Requisition No" IS NULL OR "Requisition No" = '';
-- FINDING 4: 28 PO lines have no requisition (no PR No, no PR Date).
-- Meaning: missing, not zero - POs raised without approval.
-- Impact: would distort cycle time if treated as 0.
-- Fix: keep as NULL; exclude from cycle time; report as compliance KPI.

-- Query 5: receipts with no rejected qty recorded
SELECT COUNT(*) AS blank_rejected
FROM raw_goods_receipts
WHERE "Qty Rejected" IS NULL OR "Qty Rejected" = '';
-- FINDING 5: 95 receipts have blank Qty Rejected.
-- Meaning: zero (warehouse only records rejections when they happen).
-- Impact: NULL in calculations returns NULL (e.g. accepted qty).
-- Fix: COALESCE("Qty Rejected", 0).

-- Query 6: date range of PO Date
SELECT MIN("PO Date") AS earliest, MAX("PO Date") AS latest,
       typeof("PO Date") AS stored_as
FROM raw_purchase_orders;

SELECT "PO Date",
       substr("PO Date", 7, 4) || '-' || substr("PO Date", 4, 2) || '-' || substr("PO Date", 1, 2) AS iso_date
FROM raw_purchase_orders
LIMIT 5;

-- Query 7: look at the forecast structure
SELECT * FROM raw_forecast LIMIT 3;
SELECT * FROM raw_consumption LIMIT 3;

-- Query 8: can budget and ERP categories be matched?
SELECT DISTINCT "ItemGroup" FROM raw_item_master;
SELECT "Budget Category" FROM raw_budget;
