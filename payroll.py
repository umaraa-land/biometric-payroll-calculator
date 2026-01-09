import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime, timedelta

# --- Constants & Configuration ---
RATES_FILE = 'employee_rates.json'
DEFAULT_RATE_PER_MINUTE = 0.0  # Default to 0 so rates must be set manually

st.set_page_config(page_title="Payroll Calculator", layout="wide")

# --- Helper Functions ---

def load_rates():
    """Load employee rates from JSON file."""
    if os.path.exists(RATES_FILE):
        with open(RATES_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_rates(rates_dict):
    """Save employee rates to JSON file."""
    with open(RATES_FILE, 'w') as f:
        json.dump(rates_dict, f, indent=4)

def parse_html_report(uploaded_file):
    """
    Parses the biometric attendance HTML file.
    Extracts Date, ID, Name, and calculates First In/Last Out.
    """
    soup = BeautifulSoup(uploaded_file, 'lxml')
    # Find the main data table
    table = soup.find('table')
    if not table:
        return None
    
    rows = table.find_all('tr')
    data = []
    
    for row in rows:
        # Skip header rows or empty rows
        cols = row.find_all('td')
        if not cols or len(cols) < 5:
            continue
            
        # Check if it's a data row (usually has a date in the first column)
        date_str = cols[0].get_text(strip=True)
        try:
            # Validate if first col is a date YYYY-MM-DD
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            continue # Skip headers or non-data rows
            
        emp_id = cols[1].get_text(strip=True)
        name = cols[2].get_text(strip=True)
        
        # Collect all time columns (Index 3 onwards are time slots)
        times = []
        for col in cols[3:]:
            t_str = col.get_text(strip=True)
            if t_str and ':' in t_str:
                times.append(t_str)
        
        if times:
            first_in = min(times)
            last_out = max(times)
            
            # If only one punch exists, treat In/Out as same (0 duration) or handle as missing
            # For this logic, we use min/max. 
            
            data.append({
                'Date': date_str,
                'ID': emp_id,
                'Name': name,
                'First_In': first_in,
                'Last_Out': last_out
            })
            
    return pd.DataFrame(data)

def calculate_metrics(df, start_time, end_time, rates_db):
    """
    Calculates Late, Overtime, Duration, and Pay.
    """
    results = []
    
    # Convert shift times to comparable objects
    shift_start_dt = datetime.strptime(str(start_time), '%H:%M:%S').time()
    shift_end_dt = datetime.strptime(str(end_time), '%H:%M:%S').time()
    
    for _, row in df.iterrows():
        date_obj = datetime.strptime(row['Date'], '%Y-%m-%d').date()
        
        # Parse actual timestamps
        t_in = datetime.strptime(f"{row['Date']} {row['First_In']}", '%Y-%m-%d %H:%M:%S')
        t_out = datetime.strptime(f"{row['Date']} {row['Last_Out']}", '%Y-%m-%d %H:%M:%S')
        
        # Calculate Worked Duration
        duration = t_out - t_in
        total_minutes_worked = duration.total_seconds() / 60
        
        # --- Late Calculation ---
        # Late if Actual In > Shift Start
        shift_start_combined = datetime.combine(date_obj, shift_start_dt)
        late_seconds = (t_in - shift_start_combined).total_seconds()
        late_minutes = max(0, late_seconds / 60)
        
        # --- Overtime Calculation ---
        # Overtime if Actual Out > Shift End
        shift_end_combined = datetime.combine(date_obj, shift_end_dt)
        overtime_seconds = (t_out - shift_end_combined).total_seconds()
        overtime_minutes = max(0, overtime_seconds / 60)
        
        # --- Pay Calculation ---
        emp_id = row['ID']
        rate = rates_db.get(emp_id, DEFAULT_RATE_PER_MINUTE)
        
        # Basic pay logic: Total Worked Minutes * Rate
        # (You can modify this to exclude late time or pay extra for overtime if needed)
        daily_pay = total_minutes_worked * rate
        
        results.append({
            'Date': row['Date'],
            'ID': row['ID'],
            'Name': row['Name'],
            'Time In': row['First_In'],
            'Time Out': row['Last_Out'],
            'Worked (Hrs)': str(duration),
            'Late (mins)': round(late_minutes, 2),
            'Overtime (mins)': round(overtime_minutes, 2),
            'Total Pay (IQD)': round(daily_pay, 0)
        })
        
    return pd.DataFrame(results)

# --- UI Layout ---

st.title("💰 Employee Payroll System")
st.markdown("Upload your **attendance HTML** file to calculate hours and salaries.")

# 1. Sidebar Configuration
with st.sidebar:
    st.header("⚙️ Settings")
    
    st.subheader("Shift Schedule")
    shift_start = st.time_input("Official Start Time", value=datetime.strptime("08:00", "%H:%M").time())
    shift_end = st.time_input("Official End Time", value=datetime.strptime("17:00", "%H:%M").time())
    
    st.divider()
    
    st.subheader("Data Upload")
    uploaded_file = st.file_uploader("Upload report.html", type=['html', 'htm'])

# 2. Main Logic
rates_db = load_rates()

if uploaded_file:
    # Parse File
    raw_df = parse_html_report(uploaded_file)
    
    if raw_df is not None and not raw_df.empty:
        
        # Check for new employees and add to rates DB with default if missing
        unique_employees = raw_df[['ID', 'Name']].drop_duplicates()
        new_emps = False
        for _, emp in unique_employees.iterrows():
            if emp['ID'] not in rates_db:
                rates_db[emp['ID']] = DEFAULT_RATE_PER_MINUTE
                new_emps = True
        
        if new_emps:
            save_rates(rates_db)
            st.toast("New employees found! Default rates assigned.", icon="ℹ️")

        # Tabs for View
        tab1, tab2 = st.tabs(["📊 Daily Attendance & Pay", "👥 Employee Rates"])

        # --- TAB 1: Calculations ---
        with tab1:
            st.subheader(f"Attendance Report ({len(raw_df)} records)")
            
            # Calculate metrics
            processed_df = calculate_metrics(raw_df, shift_start, shift_end, rates_db)
            
            # Styling the dataframe for display
            st.dataframe(
                processed_df,
                column_config={
                    "Total Pay (IQD)": st.column_config.NumberColumn(
                        "Total Pay (IQD)",
                        format="%d IQD"
                    ),
                    "Late (mins)": st.column_config.NumberColumn(
                        format="%.1f m"
                    ),
                    "Overtime (mins)": st.column_config.NumberColumn(
                        format="%.1f m"
                    ),
                },
                use_container_width=True,
                hide_index=True
            )
            
            # Summary Metrics
            total_payout = processed_df['Total Pay (IQD)'].sum()
            total_ot = processed_df['Overtime (mins)'].sum()
            
            col1, col2 = st.columns(2)
            col1.metric("Total Payroll Cost", f"{total_payout:,.0f} IQD")
            col2.metric("Total Overtime Minutes", f"{total_ot:,.1f} min")
            
            # Export
            csv = processed_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Download CSV Report",
                csv,
                "payroll_report.csv",
                "text/csv",
                key='download-csv'
            )

        # --- TAB 2: Rate Management ---
        with tab2:
            st.subheader("Manage Pay Rates (Per Minute)")
            st.info("Edit the rates below. Changes are saved automatically.")
            
            # Prepare data for editor
            # We convert the dict to a DataFrame for easy editing
            rate_list = [{"ID": k, "Rate (IQD/min)": v} for k, v in rates_db.items()]
            # Create a mapping for Name (lookup from the uploaded file for context)
            id_name_map = raw_df.set_index('ID')['Name'].to_dict()
            
            # Add Names to the list for better UX
            for r in rate_list:
                r['Name'] = id_name_map.get(r['ID'], "Unknown")
                
            rate_df = pd.DataFrame(rate_list)
            # Reorder columns
            if not rate_df.empty:
                rate_df = rate_df[['ID', 'Name', 'Rate (IQD/min)']]
            
                edited_df = st.data_editor(
                    rate_df,
                    key="rate_editor",
                    num_rows="dynamic",
                    disabled=["ID", "Name"], # ID and Name shouldn't be edited here, usually
                    column_config={
                        "Rate (IQD/min)": st.column_config.NumberColumn(
                            min_value=0,
                            format="%.4f"
                        )
                    }
                )
                
                # Save button for explicit confirmation (or auto-save logic)
                if st.button("Save Rate Changes"):
                    new_rates = {}
                    for _, row in edited_df.iterrows():
                        new_rates[str(row['ID'])] = row['Rate (IQD/min)']
                    save_rates(new_rates)
                    st.success("Rates updated successfully!")
                    st.rerun()
            else:
                st.warning("No employee data found yet. Upload a report first.")

    else:
        st.error("Could not parse the table from the HTML file. Please check the format.")

else:
    st.info("👈 Please upload an HTML file from the sidebar to start.")