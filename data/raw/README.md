# KiwiPack Ltd - raw data extract

Data for Jan 2025 - Jun 2026, as received from three sources. All amounts in NZD.

| File | Source | One row per |
|---|---|---|
| erp_vendor_master.csv | ERP | Vendor |
| erp_item_master.csv | ERP | Item (raw material), incl. planning parameters |
| erp_purchase_orders.csv | ERP | PO line (header fields repeated on each line) |
| erp_goods_receipts.csv | ERP | Goods receipt line (a PO line can be received in several deliveries) |
| erp_stock_on_hand_monthly.csv | ERP | Item per month-end |
| erp_consumption_monthly.csv | ERP | Item per month (quantity issued to production) |
| planning_demand_forecast.csv | Planning team spreadsheet | Item, with one column per month |
| finance_budget.csv | Finance | Budget category, with one column per month |
| control_totals.csv | - | Figures the cleaned model should reconcile to |

Codes used in the ERP:

- Line Status: CL = closed (fully received), PR = partially received, OP = open
- ItemGroup: PB = paperboard, CT = coating, INK = ink, LID = lids, PKG = packaging
- Country: NZ, AU = Australia, CN = China
- Period: yyyymm (e.g. 202601 = January 2026)
- A receipt links to its PO line by PO Number + PO Line.
