import streamlit as st
import pandas as pd
import uuid
import os
import shutil
from datetime import datetime
import plotly.express as px

# =========================
# CONFIG
# =========================
st.set_page_config(page_title="Barber Shop Ledger", layout="wide")

CSV_FILE = "shop_data.csv"
BACKUP_FILE = "shop_data_backup.csv"

REQUIRED_COLS = [
    "ID",
    "Date",
    "Time",
    "Barber_Name",
    "Customer_Name",
    "Service_Type",
    "Cost",
    "Role",
]

SERVICE_TYPES = ["Haircut", "Beard Trim", "Full Service", "Line Up", "Product"]
ROLES = ["Employee", "Owner"]


# =========================
# HELPER FUNCTIONS
# =========================
def generate_unique_id() -> str:
    """Generate collision-resistant ID with timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return f"{timestamp}-{str(uuid.uuid4())[:4]}"


def convert_df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def create_backup():
    """Create backup of current CSV file."""
    if os.path.exists(CSV_FILE):
        try:
            shutil.copy2(CSV_FILE, BACKUP_FILE)
        except OSError as e:
            st.warning(f"Could not create backup: {e}")


def load_data() -> pd.DataFrame:
    """Loads data from CSV if it exists, with backup fallback."""
    if os.path.exists(CSV_FILE):
        try:
            df = pd.read_csv(CSV_FILE)
            for col in REQUIRED_COLS:
                if col not in df.columns:
                    df[col] = pd.NA
            return df[REQUIRED_COLS]
        except Exception as e:
            st.error(f"Error loading {CSV_FILE}: {e}")
            if os.path.exists(BACKUP_FILE):
                try:
                    st.info("Loading from backup...")
                    return pd.read_csv(BACKUP_FILE)
                except Exception:
                    pass
            return pd.DataFrame(columns=REQUIRED_COLS)
    return pd.DataFrame(columns=REQUIRED_COLS)


def save_entry_to_disk(entry: dict):
    """Appends a single new entry to the CSV file with backup."""
    try:
        create_backup()
        df_entry = pd.DataFrame([entry])
        needs_header = not os.path.exists(CSV_FILE) or os.path.getsize(CSV_FILE) == 0
        df_entry.to_csv(CSV_FILE, mode="a", header=needs_header, index=False)
    except Exception as e:
        st.error(f"Failed to save entry: {e}")
        raise


def overwrite_disk_with_session() -> bool:
    """Overwrites the CSV with current session state."""
    try:
        create_backup()
        st.session_state.ledger.to_csv(CSV_FILE, index=False)
        return True
    except Exception as e:
        st.error(f"Failed to save: {e}")
        return False


def normalize_ledger(df_in: pd.DataFrame) -> pd.DataFrame:
    """Ensures types are correct for analytics."""
    if df_in.empty:
        return pd.DataFrame(columns=REQUIRED_COLS)

    df = df_in.copy()
    for c in REQUIRED_COLS:
        if c not in df.columns:
            df[c] = pd.NA
    df = df[REQUIRED_COLS]

    df["Cost"] = pd.to_numeric(df["Cost"], errors="coerce")
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Time"] = df["Time"].astype(str)
    df["Role"] = df["Role"].fillna("Employee").astype(str)
    df["Service_Type"] = df["Service_Type"].fillna("Haircut").astype(str)
    df = df.dropna(subset=["Date", "Cost"])
    df["Barber_Name"] = df["Barber_Name"].astype(str).str.strip().str.title()
    df["Customer_Name"] = df["Customer_Name"].astype(str).str.strip().str.title()
    return df


def get_clean_ledger() -> pd.DataFrame:
    return normalize_ledger(st.session_state.ledger)


def get_month_window(anchor_date: pd.Timestamp) -> tuple:
    month_start = anchor_date.normalize().replace(day=1)
    month_end = month_start + pd.offsets.MonthBegin(1)
    return month_start, month_end


def validate_entry(barber: str, customer: str, cost: float, entry_date) -> tuple:
    """Returns (is_valid, errors, warnings)."""
    errors = []
    warnings = []

    if not barber:
        errors.append("Barber name is required")
    if not customer:
        errors.append("Customer name is required")
    if cost <= 0:
        errors.append("Cost must be greater than $0")

    if cost > 500:
        warnings.append(f"Cost of ${cost:.2f} is unusually high")
    if 0 < cost < 5:
        warnings.append(f"Cost of ${cost:.2f} is unusually low")
    if entry_date > datetime.now().date():
        warnings.append("Date is in the future")

    return (len(errors) == 0, errors, warnings)


def add_entry_to_ledger(entry: dict):
    """Add entry to session state and persist to disk."""
    st.session_state.ledger = pd.concat(
        [st.session_state.ledger, pd.DataFrame([entry])],
        ignore_index=True,
    )
    try:
        save_entry_to_disk(entry)
        st.success(f"Entry added for {entry['Customer_Name']}!")
    except Exception:
        st.warning("Added to session but failed to save to disk.")


# =========================
# SESSION STATE INIT
# =========================
if "ledger" not in st.session_state:
    st.session_state.ledger = load_data()

# =========================
# SIDEBAR NAV
# =========================
st.sidebar.title("Shop Navigation")
page = st.sidebar.radio(
    "Go to",
    ["New Entry", "View & Manage Ledger", "Merge Ledgers", "Analytics", "Owner Dashboard", "Help & Guide"],
)

# Status indicator
if not st.session_state.ledger.empty:
    st.sidebar.success(f"{len(st.session_state.ledger)} records loaded")
    if os.path.exists(CSV_FILE):
        mod_time = datetime.fromtimestamp(os.path.getmtime(CSV_FILE))
        st.sidebar.caption(f"Last saved: {mod_time.strftime('%m/%d %H:%M')}")
else:
    st.sidebar.info("No data yet")

# =========================
# PAGE: NEW ENTRY
# =========================
if page == "New Entry":
    st.title("New Transaction")

    # Handle pending entries that had warnings
    if "pending_entry" in st.session_state and "pending_warnings" in st.session_state:
        st.warning("Pending entry has warnings:")
        for w in st.session_state.pending_warnings:
            st.caption(f"  - {w}")

        col_confirm, col_cancel = st.columns(2)
        with col_confirm:
            if st.button("Confirm & Save", type="primary", use_container_width=True):
                add_entry_to_ledger(st.session_state.pending_entry)
                del st.session_state.pending_entry
                del st.session_state.pending_warnings
                st.rerun()
        with col_cancel:
            if st.button("Discard", use_container_width=True):
                del st.session_state.pending_entry
                del st.session_state.pending_warnings
                st.rerun()

    else:
        with st.form("new_entry_form", clear_on_submit=True):
            col1, col2 = st.columns(2)

            with col1:
                entry_date = st.date_input("Date", value=datetime.now().date(), help="Date the service was performed. Defaults to today.")
                entry_time = st.time_input("Time", value=datetime.now().time(), help="Time of the appointment or walk-in.")
                barber_name = st.text_input("Barber Name", placeholder="e.g. David", help="First name of the barber who performed the service.")
                role = st.selectbox("Role", ROLES, help="'Owner' = shop owner's own cuts. 'Employee' = cuts by staff (commission applies).")

            with col2:
                customer_name = st.text_input("Customer Name", placeholder="e.g. John Doe", help="Customer's name. For product-only sales, leave blank to auto-fill 'Walk-In'.")
                service = st.selectbox("Service", SERVICE_TYPES, help="Type of service: Haircut, Beard Trim, Full Service (cut + beard), Line Up, or Product sale.")
                cost = st.number_input("Cost ($)", min_value=0.0, step=1.0, format="%.2f", help="Amount charged. Costs over $500 or under $5 will trigger a warning.")

            submitted = st.form_submit_button("Add to Ledger", use_container_width=True, type="primary")

        if submitted:
            barber_clean = (barber_name or "").strip().title()
            customer_clean = (customer_name or "").strip().title()

            if service == "Product" and not customer_clean:
                customer_clean = "Walk-In"

            is_valid, errors, warnings = validate_entry(
                barber_clean, customer_clean, cost, entry_date
            )

            if errors:
                for err in errors:
                    st.error(err)
            else:
                new_entry = {
                    "ID": generate_unique_id(),
                    "Date": str(entry_date),
                    "Time": str(entry_time),
                    "Barber_Name": barber_clean,
                    "Customer_Name": customer_clean,
                    "Service_Type": service,
                    "Cost": float(cost),
                    "Role": role,
                }

                if warnings:
                    st.session_state.pending_entry = new_entry
                    st.session_state.pending_warnings = warnings
                    st.rerun()
                else:
                    add_entry_to_ledger(new_entry)

# =========================
# PAGE: VIEW & MANAGE
# =========================
elif page == "View & Manage Ledger":
    st.title("Current Ledger")

    if st.session_state.ledger.empty:
        st.info("No entries yet. Add your first transaction!")
    else:
        st.dataframe(
            st.session_state.ledger,
            use_container_width=True,
            height=400,
        )

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Download")
            csv_bytes = convert_df_to_csv_bytes(st.session_state.ledger)
            st.download_button(
                label="Download Ledger as CSV",
                data=csv_bytes,
                file_name=f"barber_ledger_{datetime.now().date()}.csv",
                mime="text/csv",
                use_container_width=True,
                help="Downloads your full ledger as a .csv file you can open in Excel or Google Sheets.",
            )

        with col2:
            st.subheader("Sync to Disk")
            st.caption("Click after merging or deleting to save changes permanently.")
            if st.button("Save Changes to Disk", use_container_width=True, help="Overwrites the saved file with your current session data. A backup is created automatically."):
                if overwrite_disk_with_session():
                    st.success("Saved to disk!")
                    st.rerun()

        # Delete functionality
        st.markdown("---")
        st.subheader("Delete Entry")

        display_options = []
        ids = []
        for _, row in st.session_state.ledger.iterrows():
            try:
                date_str = pd.to_datetime(row["Date"]).strftime("%m/%d/%y")
            except (ValueError, TypeError):
                date_str = str(row["Date"])[:10]

            label = (
                f"{date_str} | {row['Barber_Name']} | "
                f"{row['Customer_Name']} | ${row['Cost']:.2f} | {row['Service_Type']}"
            )
            display_options.append(label)
            ids.append(row["ID"])

        if display_options:
            selected_idx = st.selectbox(
                "Select entry to delete",
                options=range(len(ids)),
                format_func=lambda x: display_options[x],
                help="Pick an entry from the dropdown, then click Delete. Format: Date | Barber | Customer | Cost | Service.",
            )

            col_a, col_b = st.columns([1, 3])
            with col_a:
                if st.button("Delete", type="secondary", use_container_width=True):
                    id_to_delete = ids[selected_idx]
                    st.session_state.ledger = st.session_state.ledger[
                        st.session_state.ledger["ID"] != id_to_delete
                    ]
                    if overwrite_disk_with_session():
                        st.success("Entry deleted!")
                        st.rerun()

            with col_b:
                st.caption("Deletion is permanent. A backup is created automatically.")

# =========================
# PAGE: MERGE LEDGERS
# =========================
elif page == "Merge Ledgers":
    st.title("Merge Shop Ledgers")
    st.info("Upload CSV files from other barbers to combine them with your ledger.")

    uploaded_files = st.file_uploader(
        "Upload CSV files", type=["csv"], accept_multiple_files=True,
        help="Select one or more .csv files. Each file must have these columns: ID, Date, Time, Barber_Name, Customer_Name, Service_Type, Cost, Role.",
    )

    if uploaded_files:
        st.write(f"Files selected: {len(uploaded_files)}")

        if st.button("Merge Files", use_container_width=True, type="primary"):
            dfs = [st.session_state.ledger.copy()]

            for file in uploaded_files:
                try:
                    df_temp = pd.read_csv(file)

                    missing_cols = set(REQUIRED_COLS) - set(df_temp.columns)
                    if missing_cols:
                        st.error(f"{file.name} missing columns: {missing_cols}")
                        continue

                    dfs.append(df_temp)
                    st.success(f"{file.name} validated ({len(df_temp)} records)")

                except Exception as e:
                    st.error(f"Error reading {file.name}: {e}")

            if len(dfs) > 1:
                merged_df = pd.concat(dfs, ignore_index=True)

                if "ID" not in merged_df.columns:
                    merged_df["ID"] = pd.NA

                # Generate missing IDs
                missing_id_mask = merged_df["ID"].isna() | (
                    merged_df["ID"].astype(str).str.strip() == ""
                )
                if missing_id_mask.any():
                    st.info(f"Generating IDs for {missing_id_mask.sum()} records")
                    merged_df.loc[missing_id_mask, "ID"] = [
                        generate_unique_id() for _ in range(missing_id_mask.sum())
                    ]

                # Deduplicate
                before = len(merged_df)
                merged_df = merged_df.drop_duplicates(subset=["ID"], keep="first")
                after = len(merged_df)

                if before > after:
                    st.info(f"Removed {before - after} duplicate entries")

                st.session_state.ledger = merged_df

                if overwrite_disk_with_session():
                    st.success(f"Merged {len(merged_df)} records and saved!")
                    st.dataframe(merged_df.tail(20), use_container_width=True)
                else:
                    st.warning("Merged but failed to save to disk")
            else:
                st.warning("No valid files to merge")

# =========================
# PAGE: ANALYTICS
# =========================
elif page == "Analytics":
    st.title("Analytics")

    if st.session_state.ledger.empty:
        st.warning("No data available. Add entries or upload a ledger.")
    else:
        try:
            df = get_clean_ledger()

            if df.empty:
                st.warning("No valid data after cleaning.")
            else:
                st.subheader("Time Window")
                today = pd.Timestamp.today()
                month_choice = st.date_input("Select Month", value=today.date(), help="Pick any date — the app will show the full month that date falls in.")
                month_start, month_end = get_month_window(pd.Timestamp(month_choice))

                df_month = df[(df["Date"] >= month_start) & (df["Date"] < month_end)]

                if df_month.empty:
                    st.warning(f"No transactions in {month_start.strftime('%B %Y')}.")
                else:
                    total_rev = float(df_month["Cost"].sum())
                    total_tx = len(df_month)
                    avg_price = float(df_month["Cost"].mean())
                    service_count = int((df_month["Service_Type"] != "Product").sum())

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Total Revenue", f"${total_rev:,.2f}")
                    m2.metric("Transactions", f"{total_tx:,}")
                    m3.metric("Avg Price", f"${avg_price:,.2f}")
                    m4.metric("Services (no Product)", f"{service_count:,}")

                    st.markdown("---")

                    c1, c2 = st.columns(2)

                    with c1:
                        st.subheader("Revenue by Barber")
                        barber_rev = (
                            df_month.groupby("Barber_Name", as_index=False)["Cost"]
                            .sum()
                            .sort_values("Cost", ascending=False)
                        )
                        fig_pie = px.pie(barber_rev, values="Cost", names="Barber_Name", hole=0.4)
                        st.plotly_chart(fig_pie, use_container_width=True)

                    with c2:
                        st.subheader("Daily Revenue")
                        daily_rev = (
                            df_month.groupby("Date", as_index=False)["Cost"]
                            .sum()
                            .sort_values("Date")
                        )
                        fig_line = px.line(daily_rev, x="Date", y="Cost", markers=True)
                        st.plotly_chart(fig_line, use_container_width=True)

                    st.markdown("---")

                    c3, c4 = st.columns(2)

                    with c3:
                        st.subheader("Service Mix")
                        service_mix = (
                            df_month.groupby("Service_Type", as_index=False)["Cost"]
                            .sum()
                            .sort_values("Cost", ascending=False)
                        )
                        fig_bar = px.bar(service_mix, x="Service_Type", y="Cost")
                        st.plotly_chart(fig_bar, use_container_width=True)

                    with c4:
                        st.subheader("Busiest Hours")
                        df_month_copy = df_month.copy()
                        df_month_copy["Hour"] = pd.to_datetime(
                            df_month_copy["Time"], errors="coerce"
                        ).dt.hour
                        hourly = (
                            df_month_copy.groupby("Hour", as_index=False)
                            .size()
                            .rename(columns={"size": "Transactions"})
                        )
                        fig_hours = px.bar(hourly, x="Hour", y="Transactions")
                        st.plotly_chart(fig_hours, use_container_width=True)

        except Exception as e:
            st.error(f"Analytics error: {e}")
            st.info("Check your ledger data for issues.")

# =========================
# PAGE: OWNER DASHBOARD
# =========================
elif page == "Owner Dashboard":
    st.title("Owner Profit & Projections")

    if st.session_state.ledger.empty:
        st.warning("No data available.")
    else:
        try:
            df = get_clean_ledger()

            if df.empty:
                st.warning("No valid data.")
            else:
                st.sidebar.markdown("### Owner Settings")
                rent = st.sidebar.number_input("Rent ($)", value=1500.0, min_value=0.0, step=50.0, help="Monthly rent for the shop space.")
                utilities = st.sidebar.number_input(
                    "Utilities ($)", value=300.0, min_value=0.0, step=25.0, help="Monthly utilities cost (electric, water, internet, etc.)."
                )
                commission_rate = st.sidebar.slider("Commission %", 0, 100, 30, help="Percentage of employee revenue kept by the owner.") / 100.0

                today = pd.Timestamp.today()
                month_choice = st.date_input("Select Month", value=today.date())
                month_start, month_end = get_month_window(pd.Timestamp(month_choice))

                df_month = df[(df["Date"] >= month_start) & (df["Date"] < month_end)]

                if df_month.empty:
                    st.warning(f"No transactions in {month_start.strftime('%B %Y')}.")
                else:
                    owner_data = df_month[df_month["Role"].str.lower() == "owner"]
                    employee_data = df_month[df_month["Role"].str.lower() == "employee"]

                    owner_rev = float(owner_data["Cost"].sum())
                    emp_rev = float(employee_data["Cost"].sum())
                    comm_rev = emp_rev * commission_rate

                    gross = owner_rev + comm_rev
                    expenses = float(rent + utilities)
                    net = gross - expenses

                    st.subheader(f"{month_start.strftime('%B %Y')} Financials")

                    c1, c2, c3 = st.columns(3)
                    c1.success(f"**Gross Income:** ${gross:,.2f}")
                    c1.caption(f"Owner: ${owner_rev:,.2f}  \nCommission: ${comm_rev:,.2f}")

                    c2.error(f"**Overhead:** -${expenses:,.2f}")
                    c2.caption(f"Rent: ${rent:,.2f}  \nUtilities: ${utilities:,.2f}")

                    if net >= 0:
                        c3.success(f"**Net Profit:** ${net:,.2f}")
                    else:
                        c3.error(f"**Net Loss:** ${net:,.2f}")

                    # Export summary
                    summary_data = {
                        "Month": [month_start.strftime("%Y-%m")],
                        "Owner_Revenue": [owner_rev],
                        "Employee_Revenue": [emp_rev],
                        "Commission": [comm_rev],
                        "Gross": [gross],
                        "Expenses": [expenses],
                        "Net_Profit": [net],
                    }
                    summary_df = pd.DataFrame(summary_data)

                    csv_summary = convert_df_to_csv_bytes(summary_df)
                    st.download_button(
                        label="Download Financial Summary",
                        data=csv_summary,
                        file_name=f"owner_summary_{month_start.strftime('%Y-%m')}.csv",
                        mime="text/csv",
                    )

                    st.markdown("---")
                    st.subheader("Projections")

                    daily_rev = df_month.groupby("Date")["Cost"].sum()

                    if not daily_rev.empty:
                        active_days = len(daily_rev)
                        daily_avg = daily_rev.mean()
                        proj_30 = daily_avg * 30

                        total_rev = float(df_month["Cost"].sum())
                        owner_pct = owner_rev / total_rev if total_rev > 0 else 0
                        emp_pct = emp_rev / total_rev if total_rev > 0 else 0

                        proj_owner_30 = proj_30 * owner_pct
                        proj_emp_30 = proj_30 * emp_pct
                        proj_comm_30 = proj_emp_30 * commission_rate
                        proj_gross_30 = proj_owner_30 + proj_comm_30
                        proj_net_30 = proj_gross_30 - expenses

                        p1, p2, p3 = st.columns(3)
                        p1.metric("Active Days", f"{active_days:,}")
                        p2.metric("Avg Daily Revenue", f"${daily_avg:,.2f}")
                        p3.metric("Projected 30-Day Revenue", f"${proj_30:,.2f}")

                        st.info(f"Projected 30-Day Net Profit: **${proj_net_30:,.2f}**")

                        # Forecast chart
                        dates = pd.date_range(
                            start=df_month["Date"].max() + pd.Timedelta(days=1),
                            periods=30,
                        )
                        forecast = pd.DataFrame(
                            {"Date": dates, "Projected Revenue": [daily_avg] * 30}
                        )
                        fig = px.bar(
                            forecast,
                            x="Date",
                            y="Projected Revenue",
                            title="Next 30 Days Forecast",
                        )
                        st.plotly_chart(fig, use_container_width=True)

        except Exception as e:
            st.error(f"Dashboard error: {e}")

# =========================
# PAGE: HELP & GUIDE
# =========================
elif page == "Help & Guide":
    st.title("Help & Guide")
    st.write("Everything you need to know about using the Barber Shop Ledger.")

    with st.expander("Getting Started", expanded=True):
        st.markdown("""
**First time here?** Follow these steps:

1. Go to **New Entry** in the sidebar
2. Fill in the barber name, customer name, service type, and cost
3. Click **Add to Ledger** — your transaction is saved instantly
4. Head to **Analytics** or **Owner Dashboard** to see your numbers

Your data is saved to a local CSV file (`shop_data.csv`) so it persists between sessions.
A backup (`shop_data_backup.csv`) is created automatically before every save.
""")

    with st.expander("New Entry — Adding Transactions"):
        st.markdown("""
| Field | What to enter |
|---|---|
| **Date** | Defaults to today. Change it for backdated entries. |
| **Time** | Defaults to now. Useful for tracking peak hours. |
| **Barber Name** | The barber who performed the service. Names are auto-capitalized. |
| **Role** | **Owner** = the shop owner's own cuts (full revenue). **Employee** = staff cuts (commission applies on the Owner Dashboard). |
| **Customer Name** | The client's name. For product-only sales, leave blank and it auto-fills as "Walk-In". |
| **Service** | Haircut, Beard Trim, Full Service (cut + beard), Line Up, or Product. |
| **Cost** | The amount charged. Warnings appear for amounts over $500 or under $5 — you can still confirm and save. |

**Warnings vs. Errors:**
- **Errors** (red) block the save — fix them first (e.g. missing barber name)
- **Warnings** (yellow) ask you to confirm — the entry may be valid but looks unusual
""")

    with st.expander("View & Manage Ledger"):
        st.markdown("""
- **View** all entries in a scrollable table
- **Download** your ledger as a CSV to open in Excel or Google Sheets
- **Save Changes to Disk** — click this after deleting or merging entries to make changes permanent
- **Delete Entry** — select a transaction from the dropdown and click Delete. A backup is created first.

**Tip:** The table is sortable — click any column header to sort.
""")

    with st.expander("Merge Ledgers"):
        st.markdown("""
Use this when multiple barbers keep separate CSV files and you want to combine them.

**How it works:**
1. Upload one or more `.csv` files
2. Each file must have the required columns: ID, Date, Time, Barber_Name, Customer_Name, Service_Type, Cost, Role
3. Click **Merge Files** — duplicates are removed automatically using the ID column
4. The merged result is saved to disk immediately

**Use case:** Each barber tracks their own transactions on their phone, then the owner merges everything at the end of the week.
""")

    with st.expander("Analytics"):
        st.markdown("""
Charts and metrics for any month you select.

- **Total Revenue** — sum of all transactions that month
- **Transactions** — number of entries
- **Avg Price** — average cost per transaction
- **Services (no Product)** — count of service-only entries (excludes product sales)

**Charts:**
- **Revenue by Barber** — donut chart showing each barber's share
- **Daily Revenue** — line chart of income over the month
- **Service Mix** — bar chart of revenue by service type
- **Busiest Hours** — bar chart showing which hours have the most traffic
""")

    with st.expander("Owner Dashboard"):
        st.markdown("""
Profit calculations and 30-day projections for the shop owner.

**Sidebar settings** (only visible on this page):
- **Rent** — your monthly rent
- **Utilities** — electric, water, internet, etc.
- **Commission %** — the cut you keep from employee revenue (e.g. 30% means you keep 30 cents of every dollar employees bring in)

**Financials breakdown:**
- **Gross Income** = Owner's own revenue + Commission from employees
- **Overhead** = Rent + Utilities
- **Net Profit** = Gross Income - Overhead

**Projections** use your average daily revenue to estimate the next 30 days, split by the same owner/employee ratio.
""")

    with st.expander("FAQ"):
        st.markdown("""
**Q: Where is my data stored?**
A: In a file called `shop_data.csv` in the same folder as the app. A backup called `shop_data_backup.csv` is created before every save.

**Q: Can I edit an entry?**
A: Not directly — delete the wrong entry and re-add it with the correct info.

**Q: What happens if I close the browser?**
A: Your data is safe on disk. When you reopen the app, it loads from the CSV file automatically.

**Q: Can multiple people use this at the same time?**
A: Each person should keep their own CSV and use **Merge Ledgers** to combine them. Simultaneous writes to the same file could cause conflicts.

**Q: How do I reset everything?**
A: Delete `shop_data.csv` and `shop_data_backup.csv`, then refresh the app.
""")
