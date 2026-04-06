# Supplementary Code: Integrated Planning & Machine-Level Scheduling (High-Mix Discrete Manufacturing)

This repository contains the experimental implementation accompanying the paper **"A Knowledge-Driven Constructive Heuristic for Profit-Oriented Scheduling in High Constrained Manufacturing Landscapes"**. It covers the co-design of **mid-term planning and machine-level scheduling** for **high-mix, low-volume** production environments: the planning layer allocates production, accessory co-production, and outsourcing under aggregated economic and capacity constraints; the scheduling layer enforces executability and stabilises per-machine daily behaviour through structure-aware procedures.

The paper abstract and full materials are available in the official publication. Code and supplementary materials are also synchronised with the following repository:

- [https://github.com/Layla12130/KDCH](https://github.com/Layla12130/KDCH)

---

## Repository Structure

| File | Description |
|------|-------------|
| `module_a_data.py` | **Data Layer**: Reads customer, asset, product, raw material, accessory, and order tables from Excel; normalises fields, order–product mappings, scheduling windows, and accessory requirements. |
| `module_b_scheduler.py` | **Daily Heuristic Scheduler (scheme-dependent)**: Allocates shell capacity per day across machine groups (GT150/GT130, etc.); aggregates daily accessory demand and output. |
| `module_c_changeover.py` | **Machine-Level Scheduling + Changeover**: Accounts for changeover via capacity deduction, avoiding overly conservative assumptions such as zero capacity on changeover days. |
| `module_d_gantt.py` | **Scheme D**: Implements one-machine–one-day–one-mold logic and Gantt chart generation (including ADPT adaptive capacity). |
| `module_e_economics.py` | **Economics & Profit**: Covers material/labour costs, selling prices and gross margins, and comparable cost–profit analysis across schemes (B/C/D); supports Chinese-font plotting. |
| `run_ablation_standalone.py` | **Standalone Ablation Script**: Loads data from `module_a_data`, constructs a **Greedy-NoPlan** baseline simulation, outputs metrics including on-time delivery (OTD) and accessory synchronisation accuracy (SyncAcc), and prints a comparison against **Scheme C** results reported in the paper. |
| `plot_ablation.py` | Plots comparative bar charts of ablation results (OTD, SyncAcc, profit margin, etc.); saved as `ablation_study_chart.png` by default. |
| `run_app.py` | Launches `app.py` in the same directory via Streamlit. |

---

## Dependencies

- Python 3.9+ (recommended)
- Core third-party libraries: `pandas`, `numpy`, `matplotlib`; `openpyxl` for Excel I/O; `streamlit` for the optional web interface.
```bash
pip install pandas numpy matplotlib openpyxl streamlit
```

---

## Data Format

The default data path is specified via `DEFAULT_PATH` in `module_a_data.py`. Alternatively, set the environment variable **`APS_XLS_PATH`** to point to your Excel file.

The Excel workbook must contain multiple sheets whose names match those expected by the modules — for example: **Customer List**, **Asset List**, **Product List**, **Raw Material Prices**, **Accessory List**, and **Order List**. Column names must be consistent with the `read_excel` calls and renaming logic within each module (e.g., due date, product code, mold type, heat-dissipation ring / stand installation flag).

In the economics module, parameters such as gross margin can be configured via environment variables — e.g., **`ECON_MARGIN`** (a decimal between 0 and 1). See the header of `module_e_economics.py` for details.

---

## Usage

Run all scripts from the project root directory.

Other modules are typically imported by higher-level scripts or `app.py`. When studying the algorithm directly, start from the data structure returned by `module_a_data.load_and_prepare()`, then pass it into `module_b_scheduler`, `module_c_changeover`, `module_d_gantt`, and/or `module_e_economics` as needed.

---

## Authors & License

Author and affiliation information is provided on the title page of the paper. Use of this code is subject to the license terms stated in the paper and on the repository release page.

---

## Notes

- This supplementary package focuses on **reproducible scripts and core modules**. If your local archive does **not** include `app.py` or a sample Excel file, please supply `run_app.py` and configure the data path via the environment variable described above before running.
