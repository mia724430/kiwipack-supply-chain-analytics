"""
KiwiPack Ltd - mock ERP data generator
--------------------------------------
Simulates 18 months of purchasing and warehouse activity for a fictional
Auckland paper cup manufacturer, then writes it out the way real systems
would hand it to an analyst:

  ERP exports:     vendor master, item master, purchase orders, goods receipts,
                   month-end stock, monthly consumption
  Planning file:   demand forecast (one column per month)
  Finance file:    budget by category (one column per month)
  control_totals:  figures your cleaned model should reconcile to

The files contain some typical data quality issues on purpose. Your job is to
clean them and model them into a star schema (in SQL and Power Query).

How the simulation works:
  1. Define suppliers and materials (master data).
  2. Create monthly demand (actual + forecast) with seasonality.
  3. Replay the warehouse day by day:
       - stock is consumed every day
       - when stock falls to the reorder point, a requisition -> PO is raised
       - the supplier delivers (sometimes late, sometimes partial)
  4. Record month-end stock.

Five business stories are built into the data:
  1. Pacific Board Co (China) becomes unreliable over time (OTIF falls).
  2. PE coating price rises ~12% from July 2025 (PPV + budget overrun).
  3. Four old lid styles stop selling after June 2025 (dead stock).
  4. Summer demand peak, and forecasts run consistently high (positive Bias).
  5. Southern Board NZ sells the same 280gsm grade ~8.5% dearer, but is very reliable.

Run:  python3 generate_data.py
Needs: pandas, numpy   (pip3 install pandas numpy)
"""

import calendar
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 0. Settings
# ---------------------------------------------------------------------------
SEED = 42                       # same seed = same data every run
START = date(2025, 1, 1)
END = date(2026, 6, 30)
OUTPUT_DIR = "raw_data"
Z_95 = 1.65                     # service level factor for 95%

rng = np.random.default_rng(SEED)


# ---------------------------------------------------------------------------
# 1. Master data: suppliers
# ---------------------------------------------------------------------------
# Each supplier has a behaviour profile used later in the simulation:
#   ontime_start / ontime_end : probability of delivering on time (changes over the period)
#   late_days                 : range of days late when a delivery is late
#   partial_start / _end      : probability of a partial (not-in-full) first delivery
#   defect_rate               : average share of received qty rejected by QC
suppliers = [
    # id,   name,                         country,     category,     ontime_s, ontime_e, late_days, partial_s, partial_e, defect
    ("S01", "Pacific Board Co",           "China",     "Paperboard", 0.97, 0.60, (5, 21), 0.03, 0.25, 0.030),
    ("S02", "Southern Board NZ",          "NZ",        "Paperboard", 0.98, 0.98, (1, 3),  0.01, 0.01, 0.004),
    ("S03", "Tasman Coatings",            "Australia", "Coating",    0.90, 0.90, (2, 10), 0.05, 0.05, 0.008),
    ("S04", "KiwiInk Ltd",                "NZ",        "Ink",        0.95, 0.95, (1, 5),  0.03, 0.03, 0.005),
    ("S05", "Dragon Lids Manufacturing",  "China",     "Lids",       0.85, 0.85, (4, 14), 0.06, 0.06, 0.015),
    ("S06", "Harbour Lids NZ",            "NZ",        "Lids",       0.94, 0.94, (1, 5),  0.03, 0.03, 0.006),
    ("S07", "Auckland Packaging Supplies","NZ",        "Packaging",  0.93, 0.93, (1, 6),  0.04, 0.04, 0.005),
    ("S08", "Coral Fibre Products",       "Australia", "Packaging",  0.90, 0.90, (2, 9),  0.05, 0.05, 0.008),
]
sup_cols = ["SupplierID", "SupplierName", "Country", "Category",
            "ontime_start", "ontime_end", "late_days",
            "partial_start", "partial_end", "defect_rate"]
sup_profile = pd.DataFrame(suppliers, columns=sup_cols).set_index("SupplierID")

# Standard lead time depends on where the supplier is
LEAD_TIME_BY_COUNTRY = {"NZ": 7, "Australia": 14, "China": 35}


# ---------------------------------------------------------------------------
# 2. Master data: materials
# ---------------------------------------------------------------------------
# base_monthly = typical monthly consumption (before seasonality)
# moq          = minimum order quantity
# flags: seasonal (follows cup demand), pe (hit by price rise), dead (stops selling mid-2025)
materials = [
    # id,     name,                              category,     uom,   std_cost, supplier, base_monthly, moq,  seasonal, pe,    dead
    ("M001", "Cupstock Paperboard 210gsm",      "Paperboard", "kg",   2.10,  "S01", 18000, 5000, True,  False, False),
    ("M002", "Cupstock Paperboard 280gsm",      "Paperboard", "kg",   2.35,  "S01", 22000, 5000, True,  False, False),
    ("M003", "Cupstock Paperboard 320gsm",      "Paperboard", "kg",   2.60,  "S01", 9000,  3000, True,  False, False),
    ("M004", "Cupstock Paperboard 280gsm (NZ)", "Paperboard", "kg",   2.55,  "S02", 7000,  1000, True,  False, False),
    ("M005", "Carton Board 400gsm",             "Paperboard", "kg",   2.45,  "S02", 6000,  1000, False, False, False),
    ("M006", "PE Coating Resin (LDPE)",         "Coating",    "kg",   3.80,  "S03", 4200,  1000, True,  True,  False),
    ("M007", "PE Coating Resin (HDPE)",         "Coating",    "kg",   4.10,  "S03", 1800,  500,  True,  True,  False),
    ("M008", "Aqueous Barrier Coating",         "Coating",    "kg",   6.50,  "S03", 900,   200,  True,  False, False),
    ("M009", "Water-based Ink Black",           "Ink",        "kg",   14.00, "S04", 320,   50,   True,  False, False),
    ("M010", "Water-based Ink Cyan",            "Ink",        "kg",   16.50, "S04", 180,   50,   True,  False, False),
    ("M011", "Water-based Ink Magenta",         "Ink",        "kg",   16.50, "S04", 170,   50,   True,  False, False),
    ("M012", "Water-based Ink Yellow",          "Ink",        "kg",   15.80, "S04", 160,   50,   True,  False, False),
    ("M013", "Water-based Ink White",           "Ink",        "kg",   12.40, "S04", 260,   50,   True,  False, False),
    ("M014", "PS Lid 80mm White",               "Lids",       "each", 0.028, "S05", 900000, 200000, True, False, False),
    ("M015", "PS Lid 90mm White",               "Lids",       "each", 0.032, "S05", 1100000,200000, True, False, False),
    ("M016", "PS Lid 90mm Black",               "Lids",       "each", 0.034, "S05", 600000, 200000, True, False, False),
    ("M017", "Fibre Lid 80mm",                  "Lids",       "each", 0.065, "S06", 300000, 50000,  True, False, False),
    ("M018", "Fibre Lid 90mm",                  "Lids",       "each", 0.072, "S06", 380000, 50000,  True, False, False),
    ("M019", "PS Sip Lid 80mm Clear (legacy)",  "Lids",       "each", 0.045, "S05", 150000, 100000, True, False, True),
    ("M020", "PS Sip Lid 90mm Clear (legacy)",  "Lids",       "each", 0.048, "S05", 180000, 100000, True, False, True),
    ("M021", "Dome Lid 95mm (legacy)",          "Lids",       "each", 0.060, "S06", 90000,  50000,  True, False, True),
    ("M022", "Flat Lid 95mm Printed (legacy)",  "Lids",       "each", 0.075, "S06", 70000,  50000,  True, False, True),
    ("M023", "Cup Sleeve Kraft 8-12oz",         "Packaging",  "each", 0.040, "S08", 250000, 50000,  True, False, False),
    ("M024", "Cup Sleeve Kraft 16oz",           "Packaging",  "each", 0.046, "S08", 150000, 50000,  True, False, False),
    ("M025", "Outer Carton 1000-cup",           "Packaging",  "each", 1.20,  "S07", 5200,  1000, True,  False, False),
    ("M026", "Outer Carton 500-cup",            "Packaging",  "each", 0.85,  "S07", 3800,  1000, True,  False, False),
    ("M027", "Polybag Inner Sleeve",            "Packaging",  "each", 0.012, "S07", 120000, 50000, True,  False, False),
    ("M028", "Stretch Wrap 500mm",              "Packaging",  "roll", 18.00, "S07", 140,   20,   False, False, False),
    ("M029", "Pallet Label Roll",               "Packaging",  "roll", 22.00, "S07", 60,    10,   False, False, False),
    ("M030", "Corner Board 50mm",               "Packaging",  "each", 0.55,  "S07", 2400,  500,  False, False, False),
]
mat_cols = ["MaterialID", "MaterialName", "Category", "UoM", "StandardCost",
            "PrimarySupplierID", "base_monthly", "MinOrderQty",
            "seasonal", "pe_price_rise", "dead_after_jun25"]
mat = pd.DataFrame(materials, columns=mat_cols)

# Lead time comes from the supplier's country
mat["StandardLeadTimeDays"] = mat["PrimarySupplierID"].map(
    lambda s: LEAD_TIME_BY_COUNTRY[sup_profile.loc[s, "Country"]])

# Safety stock and reorder point (planning parameters stored in the item master)
#   daily demand      = base_monthly / 30
#   daily std dev     = monthly std dev / sqrt(30); we assume monthly CV of 20%
#   safety stock      = Z x sigma_daily x sqrt(lead time)
#   reorder point     = daily demand x lead time + safety stock
daily_demand = mat["base_monthly"] / 30
sigma_daily = (mat["base_monthly"] * 0.20) / np.sqrt(30)
mat["SafetyStockQty"] = np.ceil(Z_95 * sigma_daily * np.sqrt(mat["StandardLeadTimeDays"]))
mat["ReorderPoint"] = np.ceil(daily_demand * mat["StandardLeadTimeDays"] + mat["SafetyStockQty"])


# ---------------------------------------------------------------------------
# 3. Monthly demand: actual and forecast
# ---------------------------------------------------------------------------
# NZ seasonality for cup-related materials: summer peak (Dec-Feb), winter dip (Jun-Aug)
SEASONALITY = {1: 1.30, 2: 1.25, 3: 1.10, 4: 0.95, 5: 0.90, 6: 0.85,
               7: 0.82, 8: 0.85, 9: 0.95, 10: 1.02, 11: 1.12, 12: 1.35}

months = pd.date_range(START, END, freq="MS")      # first day of each month
demand_rows = []
for _, m in mat.iterrows():
    for mo in months:
        season = SEASONALITY[mo.month] if m["seasonal"] else 1.0
        expected = m["base_monthly"] * season

        # Story 3: legacy lids stop selling after June 2025
        stopped = m["dead_after_jun25"] and mo >= pd.Timestamp(2025, 7, 1)
        actual = 0 if stopped else max(0, expected * rng.normal(1.0, 0.12))

        # Story 4: forecasts run high (planners add ~8-12% "just in case")
        # For legacy lids, planners keep forecasting for 3 months after sales stop
        if stopped and mo < pd.Timestamp(2025, 10, 1):
            forecast = expected * 0.8
        elif stopped:
            forecast = 0
        else:
            forecast = expected * rng.normal(1.10, 0.05)

        demand_rows.append({
            "MonthDate": mo.date(),
            "MaterialID": m["MaterialID"],
            "ForecastQty": round(forecast),
            "ActualQty": round(actual),
        })
demand = pd.DataFrame(demand_rows)
demand_lookup = demand.set_index(["MaterialID", "MonthDate"])


# ---------------------------------------------------------------------------
# 4. Day-by-day warehouse simulation
# ---------------------------------------------------------------------------
def progress(d):
    """0.0 at START, 1.0 at END - used to change supplier behaviour over time."""
    return (d - START).days / (END - START).days


def unit_price(m, order_date):
    """Actual price paid = standard cost +/- small noise, plus the story 2 price rise."""
    price = m["StandardCost"] * rng.normal(1.0, 0.02)
    if m["pe_price_rise"] and order_date >= date(2025, 7, 1):     # story 2
        price *= 1.12
    return round(price, 4)


po_lines, receipts, snapshots = [], [], []
po_counter, receipt_counter = 1, 1

# Starting stock: reorder point + half a month of January demand (a normal operating level)
on_hand = {r.MaterialID: r.ReorderPoint + 0.5 * r.base_monthly * (SEASONALITY[1] if r.seasonal else 1.0) for r in mat.itertuples()}
pipeline = {r.MaterialID: [] for r in mat.itertuples()}   # future deliveries: (date, qty, rejected, po_line_id)
on_order = {r.MaterialID: 0 for r in mat.itertuples()}

day = START
while day <= END:
    month_start = date(day.year, day.month, 1)
    days_in_month = calendar.monthrange(day.year, day.month)[1]

    for m in mat.itertuples():
        mid = m.MaterialID

        # 4a. Receive anything due today
        still_coming = []
        for (arrive, qty, rejected, line_id) in pipeline[mid]:
            if arrive == day:
                on_hand[mid] += qty - rejected
                on_order[mid] -= qty
            else:
                still_coming.append((arrive, qty, rejected, line_id))
        pipeline[mid] = still_coming

        # 4b. Consume today's share of the month's actual demand (stock can't go negative)
        daily_use = demand_lookup.loc[(mid, month_start), "ActualQty"] / days_in_month
        on_hand[mid] = max(0, on_hand[mid] - daily_use)

        # 4c. Reorder check on weekdays: stock position = on hand + on order
        if day.weekday() < 5 and on_hand[mid] + on_order[mid] <= m.ReorderPoint:
            forecast_month = demand_lookup.loc[(mid, month_start), "ForecastQty"]
            if forecast_month == 0:
                continue                                  # nobody plans to use it: don't buy
            target = m.ReorderPoint + forecast_month / 2  # order up to ROP + half a month of forecast
            qty = max(m.MinOrderQty, target - on_hand[mid] - on_order[mid])
            qty = int(np.ceil(qty / m.MinOrderQty) * m.MinOrderQty)   # round up to MOQ multiples

            sup = sup_profile.loc[m.PrimarySupplierID]
            p = progress(day)

            requisition_date = day
            approval_days = int(rng.integers(1, 4)) if rng.random() > 0.1 else int(rng.integers(7, 12))
            order_date = requisition_date + timedelta(days=approval_days)
            promised_date = order_date + timedelta(days=int(m.StandardLeadTimeDays))

            # Is the delivery on time? (probability moves from start to end value - story 1)
            ontime_prob = sup.ontime_start + (sup.ontime_end - sup.ontime_start) * p
            if rng.random() < ontime_prob:
                first_arrival = promised_date - timedelta(days=int(rng.integers(0, 3)))
            else:
                lo, hi = sup.late_days
                if m.PrimarySupplierID == "S01":          # story 1: delays also get longer over time
                    hi = int(hi * (1 + 1.5 * p))
                first_arrival = promised_date + timedelta(days=int(rng.integers(lo, hi + 1)))

            # Is it delivered in full? If not, the balance comes 7-21 days later
            partial_prob = sup.partial_start + (sup.partial_end - sup.partial_start) * p
            if rng.random() < partial_prob:
                first_qty = int(qty * rng.uniform(0.6, 0.9))
                deliveries = [(first_arrival, first_qty),
                              (first_arrival + timedelta(days=int(rng.integers(7, 22))), qty - first_qty)]
            else:
                deliveries = [(first_arrival, qty)]

            line_id = f"POL{po_counter:05d}"
            po_lines.append({
                "POLineID": line_id,
                "PONumber": f"PO{25000 + po_counter}",
                "RequisitionDate": requisition_date,
                "OrderDate": order_date,
                "PromisedDate": promised_date,
                "SupplierID": m.PrimarySupplierID,
                "MaterialID": mid,
                "OrderQty": qty,
                "UnitPrice": unit_price(mat.loc[mat.MaterialID == mid].iloc[0], order_date),
            })
            po_counter += 1

            for arrive, dqty in deliveries:
                rejected = int(round(dqty * max(0, rng.normal(sup.defect_rate, sup.defect_rate / 2))))
                pipeline[mid].append((arrive, dqty, rejected, line_id))
                if arrive <= END:                         # only record receipts inside the period
                    receipts.append({
                        "ReceiptID": f"GR{receipt_counter:06d}",
                        "POLineID": line_id,
                        "ReceiptDate": arrive,
                        "ReceivedQty": dqty,
                        "RejectedQty": rejected,
                    })
                    receipt_counter += 1
            on_order[mid] += qty

    # 4d. Month-end snapshot
    if day.day == calendar.monthrange(day.year, day.month)[1]:
        for m in mat.itertuples():
            snapshots.append({
                "SnapshotDate": day,
                "MaterialID": m.MaterialID,
                "OnHandQty": round(on_hand[m.MaterialID]),
                "UnitCost": m.StandardCost,
            })

    day += timedelta(days=1)


# ---------------------------------------------------------------------------
# 5. Turn the simulation into raw ERP-style exports
# ---------------------------------------------------------------------------
# In a real company you don't get a tidy star schema. You get exports from the
# ERP, a planning spreadsheet and a finance budget file - each in its own shape.
# This section writes the data the way those systems would hand it to you.

po = pd.DataFrame(po_lines)
gr = pd.DataFrame(receipts)
inv = pd.DataFrame(snapshots)
po = po[po["OrderDate"] <= END].copy()             # requisitions not yet turned into POs are dropped
gr = gr[gr["POLineID"].isin(po["POLineID"])]

# ERP-style codes
VENDOR_CODE = {s: f"V{1000 + i + 1}" for i, s in enumerate(sup_profile.index)}      # S01 -> V1001
ITEM_CODE = {m: f"RM-{1000 + int(m[1:])}" for m in mat["MaterialID"]}              # M001 -> RM-1001
COUNTRY_CODE = {"NZ": "NZ", "Australia": "AU", "China": "CN"}
ITEM_GROUP = {"Paperboard": "PB", "Coating": "CT", "Ink": "INK", "Lids": "LID", "Packaging": "PKG"}
UOM_CODE = {"kg": "KG", "each": "EA", "roll": "ROLL"}

def nz_date(d):
    """ERP exports dates as NZ-format text: dd/mm/yyyy."""
    return d.strftime("%d/%m/%Y")

# --- Vendor master -----------------------------------------------------------
vendors = pd.DataFrame({
    "VendorCode": [VENDOR_CODE[s] for s in sup_profile.index],
    "VendorName": sup_profile["SupplierName"].values,
    "Country": [COUNTRY_CODE[c] for c in sup_profile["Country"]],
    "PaymentTerms": ["60 days" if c != "NZ" else "20th month following" for c in sup_profile["Country"]],
    "Status": "Active",
})

# --- Item master -------------------------------------------------------------
items = pd.DataFrame({
    "ItemCode": mat["MaterialID"].map(ITEM_CODE),
    "Description": mat["MaterialName"],
    "ItemGroup": mat["Category"].map(ITEM_GROUP),
    "BaseUoM": mat["UoM"].map(UOM_CODE),
    "StdCost": mat["StandardCost"],
    "PrefVendor": mat["PrimarySupplierID"].map(VENDOR_CODE),
    "LeadTimeDays": mat["StandardLeadTimeDays"],
    "SafetyStock": mat["SafetyStockQty"].astype(int),
    "ReorderPoint": mat["ReorderPoint"].astype(int),
    "MOQ": mat["MinOrderQty"],
    "ItemStatus": np.where(mat["dead_after_jun25"], "Discontinued", "Active"),
})

# --- Purchase order export (header + lines flattened into one file) -----------
# One PO per supplier per order date; line numbers 10, 20, 30... (SAP style)
po = po.sort_values(["OrderDate", "SupplierID", "MaterialID"]).reset_index(drop=True)
po["po_key"] = po["SupplierID"] + po["OrderDate"].astype(str)
po_numbers = {k: f"45000{10000 + i}" for i, k in enumerate(po["po_key"].unique())}
po["PO Number"] = po["po_key"].map(po_numbers)
po["Line"] = (po.groupby("PO Number").cumcount() + 1) * 10
line_ref = po.set_index("POLineID")[["PO Number", "Line"]]

# Line status at the end of the period
received = gr.groupby("POLineID")["ReceivedQty"].sum()
rec_to_date = po["POLineID"].map(received).fillna(0)
status = np.select([rec_to_date >= po["OrderQty"], rec_to_date > 0], ["CL", "PR"], default="OP")

# Messy detail 1: vendor names typed differently on different POs
name_variants = {
    "S01": ["Pacific Board Co", "Pacific Board Co.", "PACIFIC BOARD CO", "Pacific Board Company"],
    "S05": ["Dragon Lids Manufacturing", "Dragon Lids Mfg", "Dragon Lids Manufacturing "],
    "S07": ["Auckland Packaging Supplies", "Auckland Packaging Supplies Ltd", "AKL Packaging Supplies"],
}
vendor_name = [rng.choice(name_variants[s]) if s in name_variants
               else sup_profile.loc[s, "SupplierName"] for s in po["SupplierID"]]

# Messy detail 2: unit of measure keyed inconsistently
uom_variants = {"kg": ["KG", "kg", "Kg"], "each": ["EA", "ea", "EACH"], "roll": ["ROLL", "RL"]}
mat_uom = po["MaterialID"].map(mat.set_index("MaterialID")["UoM"])
uom = [rng.choice(uom_variants[u]) for u in mat_uom]

# Messy detail 3: some POs raised without a requisition (blank requisition fields)
no_req = rng.random(len(po)) < 0.04

po_export = pd.DataFrame({
    "PO Number": po["PO Number"],
    "Line": po["Line"],
    "Requisition No": np.where(no_req, "", "PR" + (70000 + po.index).astype(str)),
    "Requisition Date": np.where(no_req, "", po["RequisitionDate"].map(nz_date)),
    "PO Date": po["OrderDate"].map(nz_date),
    "Vendor": po["SupplierID"].map(VENDOR_CODE),
    "Vendor Name": vendor_name,
    "Item": po["MaterialID"].map(ITEM_CODE),
    "Item Description": po["MaterialID"].map(mat.set_index("MaterialID")["MaterialName"]),
    "Order Qty": po["OrderQty"],
    "UoM": uom,
    "Unit Price": po["UnitPrice"],
    "Line Amount": (po["OrderQty"] * po["UnitPrice"]).round(2),
    "Currency": "NZD",
    "Confirmed Delivery": po["PromisedDate"].map(nz_date),
    "Line Status": status,
})

# Messy detail 4: a handful of rows duplicated by the export
dupes = po_export.sample(6, random_state=SEED)
po_export = pd.concat([po_export, dupes]).sort_values(["PO Number", "Line"]).reset_index(drop=True)

# --- Goods receipt export ------------------------------------------------------
gr = gr.sort_values("ReceiptDate").reset_index(drop=True)
grn_export = pd.DataFrame({
    "GRN No": ["GRN" + str(500000 + i) for i in range(len(gr))],
    "GRN Date": gr["ReceiptDate"].map(nz_date),
    "PO Number": gr["POLineID"].map(line_ref["PO Number"]),
    "PO Line": gr["POLineID"].map(line_ref["Line"]),
    "Item": gr["POLineID"].map(po.set_index("POLineID")["MaterialID"]).map(ITEM_CODE),
    "Qty Received": gr["ReceivedQty"],
    # Messy detail 5: rejected qty left blank when nothing was rejected
    "Qty Rejected": gr["RejectedQty"].replace(0, np.nan).astype("Int64"),
    "Warehouse": "AKL01",
})

# --- Month-end stock report (period as yyyymm number) ---------------------------
stock_export = pd.DataFrame({
    "Period": inv["SnapshotDate"].map(lambda d: d.year * 100 + d.month),
    "Item": inv["MaterialID"].map(ITEM_CODE),
    "Warehouse": "AKL01",
    "Qty On Hand": inv["OnHandQty"],
    "Std Cost": inv["UnitCost"],
})

# --- Monthly consumption (issues to production) from the ERP -------------------
consumption_export = pd.DataFrame({
    "Period": demand["MonthDate"].map(lambda d: d.year * 100 + d.month),
    "Item": demand["MaterialID"].map(ITEM_CODE),
    "Qty Issued": demand["ActualQty"],
})

# --- Demand forecast: planners' spreadsheet, one column per month (wide) -------
MONTH_LABEL = lambda d: d.strftime("%b-%y")          # e.g. Jan-25
fc = demand.copy()
fc["Month"] = fc["MonthDate"].map(MONTH_LABEL)
forecast_wide = fc.pivot(index="MaterialID", columns="Month", values="ForecastQty")
forecast_wide = forecast_wide[[MONTH_LABEL(m) for m in months]]            # keep calendar order
forecast_wide.insert(0, "Description", mat.set_index("MaterialID")["MaterialName"])
forecast_wide.index = forecast_wide.index.map(ITEM_CODE)
forecast_wide.index.name = "Item"

# --- Budget: finance's file, category x month (wide), finance's own names ------
# Messy detail 6: finance uses different category names from the ERP item groups
FINANCE_NAME = {"Paperboard": "Paperboard", "Coating": "Coatings", "Ink": "Inks",
                "Lids": "Lids & Closures", "Packaging": "Packaging Materials"}
bud = demand.merge(mat[["MaterialID", "Category", "StandardCost", "base_monthly",
                        "seasonal", "dead_after_jun25"]], on="MaterialID")
bud = bud[~(bud["dead_after_jun25"] & (pd.to_datetime(bud["MonthDate"]) >= "2025-07-01"))]
bud["season"] = [SEASONALITY[d.month] if s else 1.0 for d, s in zip(bud["MonthDate"], bud["seasonal"])]
bud["BudgetAmount"] = bud["base_monthly"] * bud["season"] * bud["StandardCost"]
bud["Month"] = bud["MonthDate"].map(MONTH_LABEL)
bud["Budget Category"] = bud["Category"].map(FINANCE_NAME)
budget_wide = (bud.pivot_table(index="Budget Category", columns="Month", values="BudgetAmount", aggfunc="sum")
                  .round(0).astype(int)[[MONTH_LABEL(m) for m in months]])


# ---------------------------------------------------------------------------
# 6. Control totals - what your cleaned model should reconcile to
# ---------------------------------------------------------------------------
clean_po = po_export.drop_duplicates()
last_period = stock_export["Period"].max()
last_stock = stock_export[stock_export["Period"] == last_period]
# Consumption value at standard cost is the COGS figure used for inventory turnover
cons_value = consumption_export.merge(items[["ItemCode", "StdCost"]], left_on="Item", right_on="ItemCode")
controls = pd.DataFrame([
    ("PO lines (after removing duplicates)", f"{len(clean_po)}"),
    ("Distinct PO numbers", f"{clean_po['PO Number'].nunique()}"),
    ("Total PO line amount NZD (after removing duplicates)", f"{clean_po['Line Amount'].sum():.2f}"),
    ("Goods receipt lines", f"{len(grn_export)}"),
    ("Goods receipt lines with a rejection", f"{grn_export['Qty Rejected'].notna().sum()}"),
    (f"Stock value at std cost, period {last_period} (NZD)",
     f"{(last_stock['Qty On Hand'] * last_stock['Std Cost']).sum():.2f}"),
    ("Consumption value at std cost, all periods (NZD)",
     f"{(cons_value['Qty Issued'] * cons_value['StdCost']).sum():.2f}"),
    ("Total budget NZD", f"{budget_wide.values.sum():.0f}"),
], columns=["Check", "Expected value"])


# ---------------------------------------------------------------------------
# 7. Save
# ---------------------------------------------------------------------------
os.makedirs(OUTPUT_DIR, exist_ok=True)
files = {
    "erp_vendor_master.csv": (vendors, False),
    "erp_item_master.csv": (items, False),
    "erp_purchase_orders.csv": (po_export, False),
    "erp_goods_receipts.csv": (grn_export, False),
    "erp_stock_on_hand_monthly.csv": (stock_export, False),
    "erp_consumption_monthly.csv": (consumption_export, False),
    "planning_demand_forecast.csv": (forecast_wide, True),
    "finance_budget.csv": (budget_wide, True),
    "control_totals.csv": (controls, False),
}
for name, (df, keep_index) in files.items():
    df.to_csv(os.path.join(OUTPUT_DIR, name), index=keep_index)
    print(f"{name:34s} {len(df):>5,} rows")
