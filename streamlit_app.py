import streamlit as st
import pandas as pd
import uuid
import os
import shutil
import json
from datetime import datetime, time as dt_time
import plotly.express as px

# =========================
# CONFIG
# =========================
st.set_page_config(page_title="Barber Shop Ledger", layout="wide")

CSV_FILE = "shop_data.csv"
BACKUP_FILE = "shop_data_backup.csv"
USERS_FILE = "users.json"

REQUIRED_COLS = [
    "ID",
    "Date",
    "Time",
    "Barber_Name",
    "Customer_Name",
    "Service_Type",
    "Cost",
    "Role",
    "Duration_Min",
]

SERVICE_TYPES = ["Haircut", "Beard Trim", "Full Service", "Line Up", "Product"]
ROLES = ["Employee", "Owner"]
DURATION_OPTIONS = [15, 30, 45, 60, 75, 90, 105, 120]


# =========================
# USER MANAGEMENT
# =========================
def load_users() -> dict:
    """Load user accounts from JSON file."""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_users(users: dict):
    """Persist user accounts to JSON file."""
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)


def initialize_default_owner(users: dict) -> dict:
    """Ensure at least one owner account exists on first run."""
    if not any(u.get("role") == "owner" for u in users.values()):
        users["owner"] = {
            "password": "owner",
            "role": "owner",
            "display_name": "Owner",
        }
        save_users(users)
    return users


def authenticate(username: str, password: str, users: dict):
    """Returns the user dict if credentials match, else None."""
    user = users.get(username.lower().strip())
    if user and user["password"] == password:
        return user
    return None


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


def _read_csv_robust(path: str) -> pd.DataFrame:
    """Read a CSV, handling mismatched column counts gracefully."""
    try:
        return pd.read_csv(path)
    except Exception:
        # Column count mismatch — read without forcing column names, skip bad lines
        return pd.read_csv(path, on_bad_lines="skip")


def load_data() -> pd.DataFrame:
    """Loads data from CSV if it exists, with backup fallback."""
    if os.path.exists(CSV_FILE):
        try:
            df = _read_csv_robust(CSV_FILE)
            for col in REQUIRED_COLS:
                if col not in df.columns:
                    df[col] = pd.NA
            return df[REQUIRED_COLS]
        except Exception as e:
            st.error(f"Error loading {CSV_FILE}: {e}")
            if os.path.exists(BACKUP_FILE):
                try:
                    st.info("Loading from backup...")
                    return _read_csv_robust(BACKUP_FILE)
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

        # If file exists, check if the header matches current columns
        if not needs_header:
            with open(CSV_FILE, "r") as f:
                existing_header = f.readline().strip().split(",")
            if set(existing_header) != set(REQUIRED_COLS):
                # Header is stale — reload, add missing columns, rewrite
                df_existing = _read_csv_robust(CSV_FILE)
                for col in REQUIRED_COLS:
                    if col not in df_existing.columns:
                        df_existing[col] = pd.NA
                df_existing = df_existing[REQUIRED_COLS]
                df_existing.to_csv(CSV_FILE, index=False)

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
    df["Duration_Min"] = pd.to_numeric(df["Duration_Min"], errors="coerce").fillna(30).astype(int)
    return df


def get_clean_ledger() -> pd.DataFrame:
    return normalize_ledger(st.session_state.ledger)


def get_user_ledger() -> pd.DataFrame:
    """Return clean ledger filtered to the current user's visibility.
    Owner sees everything; barbers see only their own rows."""
    df = get_clean_ledger()
    if st.session_state.current_role == "owner":
        return df
    display = st.session_state.current_display_name
    return df[df["Barber_Name"].str.lower() == display.lower()]


def get_user_ledger_raw() -> pd.DataFrame:
    """Return raw session ledger filtered to the current user.
    Used for View & Manage operations on st.session_state.ledger."""
    df = st.session_state.ledger
    if st.session_state.current_role == "owner":
        return df
    display = st.session_state.current_display_name
    return df[df["Barber_Name"].astype(str).str.strip().str.lower() == display.lower()]


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


def round_time_to_nearest_15() -> dt_time:
    """Round current time to the nearest 15-minute mark."""
    now = datetime.now()
    minutes = now.minute
    remainder = minutes % 15
    if remainder < 8:
        rounded = minutes - remainder
    else:
        rounded = minutes + (15 - remainder)
    hour = now.hour
    if rounded >= 60:
        rounded = 0
        hour = (hour + 1) % 24
    return dt_time(hour, rounded)


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

if "users" not in st.session_state:
    st.session_state.users = load_users()
    st.session_state.users = initialize_default_owner(st.session_state.users)

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "current_user" not in st.session_state:
    st.session_state.current_user = None
if "current_role" not in st.session_state:
    st.session_state.current_role = None
if "current_display_name" not in st.session_state:
    st.session_state.current_display_name = None

# =========================
# LOGIN GATE
# =========================
if not st.session_state.logged_in:
    st.title("Barber Shop Ledger - Login")
    with st.form("login_form"):
        username = st.text_input("Username", placeholder="Enter your username")
        password = st.text_input("Password", type="password")
        login_btn = st.form_submit_button("Log In", use_container_width=True, type="primary")

    if login_btn:
        user = authenticate(username, password, st.session_state.users)
        if user:
            st.session_state.logged_in = True
            st.session_state.current_user = username.lower().strip()
            st.session_state.current_role = user["role"]
            st.session_state.current_display_name = user["display_name"]
            st.rerun()
        else:
            st.error("Invalid username or password.")
    st.stop()

# =========================
# SIDEBAR NAV
# =========================
st.sidebar.title("Shop Navigation")

# User info and logout
st.sidebar.markdown(f"Logged in as: **{st.session_state.current_display_name}** ({st.session_state.current_role})")
if st.sidebar.button("Logout", use_container_width=True):
    for key in ["logged_in", "current_user", "current_role", "current_display_name", "owner_authenticated"]:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()

st.sidebar.markdown("---")

# Build page list based on role
pages = ["New Entry", "View & Manage Ledger", "Analytics", "Help & Guide"]
if st.session_state.current_role == "owner":
    pages.insert(2, "Merge Ledgers")
    pages.insert(-1, "Owner Dashboard")
    pages.append("Manage Users")

page = st.sidebar.radio("Go to", pages)

# Status indicator — show only the user's own record count
user_record_count = len(get_user_ledger_raw())
if user_record_count > 0:
    st.sidebar.success(f"{user_record_count} records loaded")
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
                entry_time = st.time_input("Time", value=round_time_to_nearest_15(), step=900, help="Time of the appointment or walk-in. Rounded to nearest 15 min.")
                # Build barber name list from registered accounts
                barber_names = [u["display_name"] for u in st.session_state.users.values()]
                if st.session_state.current_role == "barber":
                    barber_name = st.selectbox(
                        "Barber Name", [st.session_state.current_display_name],
                        disabled=True,
                        help="Auto-filled from your account.",
                    )
                    role = st.selectbox("Role", ROLES, index=0, disabled=True, help="Employees are recorded as 'Employee' role.")
                else:
                    barber_name = st.selectbox("Barber Name", barber_names, help="Select the barber who performed the service.")
                    role = st.selectbox("Role", ROLES, help="'Owner' = shop owner's own cuts. 'Employee' = cuts by staff (commission applies).")

            with col2:
                customer_name = st.text_input("Customer Name", placeholder="e.g. John Doe", help="Customer's name. For product-only sales, leave blank to auto-fill 'Walk-In'.")
                service = st.selectbox("Service", SERVICE_TYPES, help="Type of service: Haircut, Beard Trim, Full Service (cut + beard), Line Up, or Product sale.")
                cost = st.number_input("Cost ($)", min_value=0.0, step=1.0, format="%.2f", help="Amount charged. Costs over $500 or under $5 will trigger a warning.")
                duration = st.selectbox("Duration", DURATION_OPTIONS, index=1, format_func=lambda m: f"{m} min", help="Length of service in 15-minute increments.")

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
                    "Duration_Min": int(duration),
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

    user_df = get_user_ledger_raw()

    if user_df.empty:
        st.info("No entries yet. Add your first transaction!")
    else:
        st.dataframe(
            user_df,
            use_container_width=True,
            height=400,
        )

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Download")
            csv_bytes = convert_df_to_csv_bytes(user_df)
            st.download_button(
                label="Download Ledger as CSV",
                data=csv_bytes,
                file_name=f"barber_ledger_{datetime.now().date()}.csv",
                mime="text/csv",
                use_container_width=True,
                help="Downloads your ledger as a .csv file you can open in Excel or Google Sheets.",
            )

        with col2:
            if st.session_state.current_role == "owner":
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
        for _, row in user_df.iterrows():
            try:
                date_str = pd.to_datetime(row["Date"]).strftime("%m/%d/%y")
            except (ValueError, TypeError):
                date_str = str(row["Date"])[:10]

            dur = row.get("Duration_Min", "")
            dur_str = f" | {int(dur)}min" if pd.notna(dur) and str(dur).strip() else ""
            label = (
                f"{date_str} | {row['Barber_Name']} | "
                f"{row['Customer_Name']} | ${row['Cost']:.2f} | {row['Service_Type']}{dur_str}"
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

    # Import CSV — available to all users
    st.markdown("---")
    st.subheader("Import Transactions from CSV")
    st.caption("Upload a CSV file to load old transactions into your ledger.")

    import_file = st.file_uploader(
        "Upload CSV file", type=["csv"], key="import_csv",
        help="CSV must have columns: Date, Customer_Name, Service_Type, Cost. Optional: Time, Role, Duration_Min.",
    )

    if import_file:
        try:
            df_import = pd.read_csv(import_file)

            # Check for minimum required columns
            min_cols = {"Date", "Customer_Name", "Service_Type", "Cost"}
            missing = min_cols - set(df_import.columns)
            if missing:
                st.error(f"Missing required columns: {missing}")
            else:
                # Force Barber_Name to logged-in user (barbers can't import for others)
                if st.session_state.current_role == "barber":
                    df_import["Barber_Name"] = st.session_state.current_display_name
                else:
                    # Owner: keep Barber_Name from file if present, else use owner's name
                    if "Barber_Name" not in df_import.columns:
                        df_import["Barber_Name"] = st.session_state.current_display_name

                # Fill optional columns with defaults
                if "Role" not in df_import.columns:
                    df_import["Role"] = "Employee"
                if "Time" not in df_import.columns:
                    df_import["Time"] = "12:00:00"
                if "Duration_Min" not in df_import.columns:
                    df_import["Duration_Min"] = 30

                # Generate unique IDs (ignore any existing ID column)
                df_import["ID"] = [generate_unique_id() for _ in range(len(df_import))]

                # Keep only required columns
                df_import = df_import[REQUIRED_COLS]

                st.write(f"Preview ({len(df_import)} rows):")
                st.dataframe(df_import.head(10), use_container_width=True)

                if st.button("Import All", type="primary", use_container_width=True):
                    st.session_state.ledger = pd.concat(
                        [st.session_state.ledger, df_import], ignore_index=True
                    )
                    if overwrite_disk_with_session():
                        st.success(f"Imported {len(df_import)} transactions!")
                        st.rerun()
                    else:
                        st.warning("Added to session but failed to save to disk.")
        except Exception as e:
            st.error(f"Error reading file: {e}")

# =========================
# PAGE: MERGE LEDGERS
# =========================
elif page == "Merge Ledgers":
    if st.session_state.current_role != "owner":
        st.error("Access denied. Owner account required.")
        st.stop()

    st.title("Merge Shop Ledgers")
    st.info("Upload CSV files from other barbers to combine them with your ledger.")

    uploaded_files = st.file_uploader(
        "Upload CSV files", type=["csv"], accept_multiple_files=True,
        help="Select one or more .csv files. Required columns: ID, Date, Time, Barber_Name, Customer_Name, Service_Type, Cost, Role. Duration_Min is optional.",
    )

    if uploaded_files:
        st.write(f"Files selected: {len(uploaded_files)}")

        if st.button("Merge Files", use_container_width=True, type="primary"):
            dfs = [st.session_state.ledger.copy()]

            for file in uploaded_files:
                try:
                    df_temp = pd.read_csv(file)

                    required_for_import = [c for c in REQUIRED_COLS if c != "Duration_Min"]
                    missing_cols = set(required_for_import) - set(df_temp.columns)
                    if missing_cols:
                        st.error(f"{file.name} missing columns: {missing_cols}")
                        continue

                    if "Duration_Min" not in df_temp.columns:
                        df_temp["Duration_Min"] = 30

                    df_temp = df_temp[REQUIRED_COLS]

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
            df = get_user_ledger()

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

                    avg_dur = float(df_month["Duration_Min"].mean()) if "Duration_Min" in df_month.columns else 0

                    m1, m2, m3, m4, m5 = st.columns(5)
                    m1.metric("Total Revenue", f"${total_rev:,.2f}")
                    m2.metric("Transactions", f"{total_tx:,}")
                    m3.metric("Avg Price", f"${avg_price:,.2f}")
                    m4.metric("Services (no Product)", f"{service_count:,}")
                    m5.metric("Avg Duration", f"{avg_dur:.0f} min")

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
    if st.session_state.current_role != "owner":
        st.error("Access denied. Owner account required.")
        st.stop()

    st.title("Owner Profit & Projections")

    # --- Password gate ---
    if "owner_authenticated" not in st.session_state:
        st.session_state.owner_authenticated = False

    if not st.session_state.owner_authenticated:
        st.info("This page is password-protected. Enter the owner password to continue.")
        with st.form("owner_login_form"):
            owner_pw = st.text_input("Password", type="password", help="Ask the shop owner for the dashboard password.")
            login_submit = st.form_submit_button("Unlock Dashboard", use_container_width=True, type="primary")
        if login_submit:
            if owner_pw == st.session_state.get("owner_password", "owner"):
                st.session_state.owner_authenticated = True
                st.rerun()
            else:
                st.error("Incorrect password.")
        with st.expander("How do I set or change the password?"):
            st.markdown("""
The default password is **owner**. To change it, use the sidebar option below.
""")
        with st.form("change_pw_form"):
            current_pw = st.text_input("Current Password", type="password")
            new_pw = st.text_input("New Password", type="password")
            confirm_pw = st.text_input("Confirm New Password", type="password")
            change_submit = st.form_submit_button("Change Password", use_container_width=True)
        if change_submit:
            if current_pw != st.session_state.get("owner_password", "owner"):
                st.error("Current password is incorrect.")
            elif not new_pw:
                st.error("New password cannot be empty.")
            elif new_pw != confirm_pw:
                st.error("New passwords do not match.")
            else:
                st.session_state.owner_password = new_pw
                st.success("Password changed! You can now log in with your new password.")

    elif st.session_state.ledger.empty:
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

    with st.expander("Login & Accounts", expanded=True):
        st.markdown("""
**Logging In:** Every user must log in before accessing the app. The owner sets up accounts for each barber.

**Account Types:**
- **Owner** — Full access to all entries, analytics, merging, and the Owner Dashboard. Can create and manage barber accounts.
- **Barber** — Sees only their own entries and analytics. Cannot access Merge Ledgers or the Owner Dashboard.

**First-time setup:** The default owner account is:
- Username: `owner`
- Password: `owner`

Change the owner password immediately after your first login via **Manage Users**.

**Barber name matching:** Each barber account has a "Display Name" that must match the barber's name as it appears in ledger entries. Names are Title Cased automatically.
""")

    with st.expander("Getting Started"):
        st.markdown("""
**First time here?** Follow these steps:

1. Log in with your account (owner sets up barber accounts via **Manage Users**)
2. Go to **New Entry** in the sidebar
3. Fill in the customer name, service type, and cost (barber name is auto-filled)
4. Click **Add to Ledger** — your transaction is saved instantly
5. Head to **Analytics** to see your numbers

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
| **Duration** | How long the service took, in 15-minute increments (15 min to 2 hrs). Defaults to 30 min. |

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
- **Avg Duration** — average service length in minutes

**Charts:**
- **Revenue by Barber** — donut chart showing each barber's share
- **Daily Revenue** — line chart of income over the month
- **Service Mix** — bar chart of revenue by service type
- **Busiest Hours** — bar chart showing which hours have the most traffic
""")

    with st.expander("Owner Dashboard"):
        st.markdown("""
Profit calculations and 30-day projections for the shop owner.

**Password protection:** This page requires a password to access. The default password is `owner`. You can change it from the login screen — enter your current password, then set a new one. The password resets when the app restarts.

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
A: Yes — each person logs in with their own account and sees only their own data. Note that simultaneous writes to the same CSV file could cause minor conflicts if two people save at the exact same moment.

**Q: How do I reset everything?**
A: Delete `shop_data.csv`, `shop_data_backup.csv`, and `users.json`, then refresh the app.

**Q: How do I keep employees out of the Owner Dashboard?**
A: Barber accounts cannot see the Owner Dashboard or Merge Ledgers pages at all. Additionally, the Owner Dashboard has its own separate password for extra protection.

**Q: What is the Duration field for?**
A: It tracks how long each service takes (in 15-minute steps). This helps identify which services are most time-efficient and shows up as "Avg Duration" on the Analytics page.
""")

# =========================
# PAGE: MANAGE USERS
# =========================
elif page == "Manage Users":
    if st.session_state.current_role != "owner":
        st.error("Access denied.")
        st.stop()

    st.title("Manage User Accounts")

    # --- Display existing users ---
    st.subheader("Current Accounts")
    users = st.session_state.users

    if users:
        user_rows = []
        for uname, udata in users.items():
            user_rows.append({
                "Username": uname,
                "Display Name": udata.get("display_name", ""),
                "Role": udata.get("role", ""),
            })
        st.dataframe(pd.DataFrame(user_rows), use_container_width=True)
    else:
        st.info("No accounts found.")

    # --- Add new barber account ---
    st.markdown("---")
    st.subheader("Add Barber Account")
    with st.form("add_user_form", clear_on_submit=True):
        new_username = st.text_input("Username", placeholder="e.g. david",
            help="Lowercase login name for the barber.")
        new_display = st.text_input("Display Name", placeholder="e.g. David",
            help="This must match how the barber's name appears in ledger entries (after Title Case).")
        new_password = st.text_input("Password", type="password",
            help="Initial password for the barber.")
        add_btn = st.form_submit_button("Create Account", use_container_width=True, type="primary")

    if add_btn:
        clean_username = new_username.lower().strip()
        if not clean_username:
            st.error("Username is required.")
        elif clean_username in st.session_state.users:
            st.error(f"Username '{clean_username}' already exists.")
        elif not new_display.strip():
            st.error("Display name is required.")
        elif not new_password:
            st.error("Password is required.")
        else:
            st.session_state.users[clean_username] = {
                "password": new_password,
                "role": "barber",
                "display_name": new_display.strip().title(),
            }
            save_users(st.session_state.users)
            st.success(f"Account '{clean_username}' created for {new_display.strip().title()}!")
            st.rerun()

    # --- Reset password ---
    st.markdown("---")
    st.subheader("Reset Password")
    if users:
        usernames = list(users.keys())
        selected_user = st.selectbox("Select user", usernames)
        with st.form("reset_pw_form"):
            reset_pw = st.text_input("New Password", type="password")
            reset_btn = st.form_submit_button("Reset Password", use_container_width=True)
        if reset_btn:
            if not reset_pw:
                st.error("Password cannot be empty.")
            else:
                st.session_state.users[selected_user]["password"] = reset_pw
                save_users(st.session_state.users)
                st.success(f"Password reset for '{selected_user}'.")

    # --- Delete account ---
    st.markdown("---")
    st.subheader("Delete Account")
    deletable = [u for u in users.keys() if users[u]["role"] != "owner"]
    if deletable:
        del_user = st.selectbox("Select account to delete", deletable, key="del_user_select")
        if st.button("Delete Account", type="secondary"):
            del st.session_state.users[del_user]
            save_users(st.session_state.users)
            st.success(f"Account '{del_user}' deleted.")
            st.rerun()
    else:
        st.info("No barber accounts to delete.")
