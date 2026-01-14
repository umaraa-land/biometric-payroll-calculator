import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- Constants & Configuration ---
SHEET_NAME = 'employee_rates'  # Name of your Google Sheet
DEFAULT_RATE_PER_MINUTE = 0.0

st.set_page_config(page_title="Payroll Calculator", layout="wide")

# --- Translations Dictionary ---
TRANSLATIONS = {
    "en": {
        "title": "💰 Employee Payroll System",
        "subtitle": "Upload your **attendance HTML** file to calculate hours and salaries.",
        "settings": "⚙️ Settings",
        "language": "Language / اللغة",
        "shift_schedule": "Shift Schedule",
        "start_time": "Official Start Time",
        "end_time": "Official End Time",
        "data_upload": "Data Upload",
        "upload_label": "Upload report.html",
        "tab_daily": "📊 Daily Attendance & Pay",
        "tab_rates": "👥 Employee Rates",
        "report_header": "Attendance Report ({} records)",
        "col_pay": "Total Pay (IQD)",
        "col_late": "Late (mins)",
        "col_ot": "Overtime (mins)",
        "col_worked": "Worked (Hrs)",
        "col_in": "Time In",
        "col_out": "Time Out",
        "total_cost": "Total Payroll Cost",
        "total_ot_mins": "Total Overtime Minutes",
        "download_csv": "📥 Download CSV Report",
        "manage_rates": "Manage Pay Rates (Per Minute)",
        "rate_info": "Edit the rates below. Changes are saved to Google Sheets automatically.",
        "save_btn": "Save Rate Changes",
        "success_save": "Rates updated successfully!",
        "new_emps": "New employees found! Added to Google Sheet with default rates.",
        "error_parse": "Could not find the Attendance Table. Please ensure you saved the 'Report' frame, not the 'Menu'.",
        "upload_prompt": "👈 Please upload an HTML file from the sidebar to start.",
        "unknown": "Unknown",
        "gsheet_error": "Connection Error: Could not reach Google Sheets. Check your Secrets configuration."
    },
    "ar": {
        "title": "💰 نظام الرواتب والموظفين",
        "subtitle": "قم برفع ملف **HTML للحضور** لحساب الساعات والرواتب.",
        "settings": "⚙️ الإعدادات",
        "language": "Language / اللغة",
        "shift_schedule": "جدول الدوام",
        "start_time": "وقت البدء الرسمي",
        "end_time": "وقت الانتهاء الرسمي",
        "data_upload": "رفع البيانات",
        "upload_label": "ارفع ملف report.html",
        "tab_daily": "📊 الحضور والرواتب اليومية",
        "tab_rates": "👥 سعر دقيقة الموظف",
        "report_header": "تقرير الحضور ({} سجل)",
        "col_pay": "الراتب الكلي (د.ع)",
        "col_late": "تأخير (دقيقة)",
        "col_ot": "إضافي (دقيقة)",
        "col_worked": "ساعات العمل",
        "col_in": "وقت الدخول",
        "col_out": "وقت الخروج",
        "total_cost": "إجمالي الرواتب",
        "total_ot_mins": "إجمالي دقائق الإضافي",
        "download_csv": "📥 تحميل التقرير (CSV)",
        "manage_rates": "إدارة أسعار الدقائق",
        "rate_info": "قم بتعديل الأسعار أدناه. يتم حفظ التغييرات تلقائيًا في Google Sheets.",
        "save_btn": "حفظ التغييرات",
        "success_save": "تم تحديث الأسعار بنجاح!",
        "new_emps": "تم العثور على موظفين جدد! تمت إضافتهم إلى Google Sheet بأسعار افتراضية.",
        "error_parse": "لم يتم العثور على جدول الحضور. يرجى التأكد من حفظ 'التقرير' وليس القائمة الرئيسية.",
        "upload_prompt": "👈 يرجى رفع ملف HTML من القائمة الجانبية للبدء.",
        "unknown": "غير معروف",
        "gsheet_error": "خطأ اتصال: لا يمكن الوصول إلى Google Sheets. تأكد من إعدادات Secrets."
    }
}

# --- Google Sheets Helper Functions ---

def get_google_sheet_client():
    """Connect to Google Sheets using Streamlit Secrets"""
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    # Load credentials from Streamlit secrets
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

def load_rates_from_sheet():
    """Load employee rates from Google Sheet."""
    try:
        client = get_google_sheet_client()
        sheet = client.open(SHEET_NAME).sheet1
        # Get all records as a list of dicts
        records = sheet.get_all_records()
        
        # Convert to dictionary format {ID: Rate}
        rates_db = {}
        for row in records:
            # Ensure ID is treated as string to match HTML parse
            rates_db[str(row['ID'])] = float(row['Rate'])
        return rates_db
    except Exception as e:
        st.error(f"Google Sheets Error: {e}")
        return {}

def save_rates_to_sheet(rates_dict):
    """Save employee rates to Google Sheet (Full Rewrite for safety)."""
    try:
        client = get_google_sheet_client()
        sheet = client.open(SHEET_NAME).sheet1
        
        # Prepare data for upload
        # Header first
        data = [['ID', 'Rate']]
        for emp_id, rate in rates_dict.items():
            data.append([str(emp_id), rate])
            
        # Clear and update
        sheet.clear()
        sheet.update(range_name='A1', values=data)
        return True
    except Exception as e:
        st.error(f"Save Error: {e}")
        return False

# --- Helper Functions (Standard) ---

def parse_html_report(uploaded_file):
    """
    Parses the biometric attendance HTML file.
    Extracts Date, ID, Name, and calculates First In/Last Out.
    """
    try:
        soup = BeautifulSoup(uploaded_file, 'lxml')
    except Exception:
        uploaded_file.seek(0)
        content = uploaded_file.read().decode('windows-1252', errors='ignore')
        soup = BeautifulSoup(content, 'lxml')

    tables = soup.find_all('table')
    target_table = None
    
    for t in tables:
        headers_text = t.get_text().lower()
        if "id number" in headers_text and "date" in headers_text:
            target_table = t
            break
            
    if not target_table:
        return None
    
    rows = target_table.find_all('tr')
    data = []
    
    for row in rows:
        cols = row.find_all('td')
        if not cols or len(cols) < 5:
            continue
            
        date_str = cols[0].get_text(strip=True)
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            continue
            
        emp_id = cols[1].get_text(strip=True)
        name = cols[2].get_text(strip=True)
        
        times = []
        for col in cols[3:]:
            t_str = col.get_text(strip=True)
            if t_str and ':' in t_str:
                times.append(t_str)
        
        if times:
            first_in = min(times)
            last_out = max(times)
            
            data.append({
                'Date': date_str,
                'ID': emp_id,
                'Name': name,
                'First_In': first_in,
                'Last_Out': last_out
            })
            
    return pd.DataFrame(data)

def calculate_metrics(df, start_time, end_time, rates_db):
    results = []
    shift_start_dt = datetime.strptime(str(start_time), '%H:%M:%S').time()
    shift_end_dt = datetime.strptime(str(end_time), '%H:%M:%S').time()
    
    for _, row in df.iterrows():
        date_obj = datetime.strptime(row['Date'], '%Y-%m-%d').date()
        
        t_in = datetime.strptime(f"{row['Date']} {row['First_In']}", '%Y-%m-%d %H:%M:%S')
        t_out = datetime.strptime(f"{row['Date']} {row['Last_Out']}", '%Y-%m-%d %H:%M:%S')
        
        duration = t_out - t_in
        total_minutes_worked = duration.total_seconds() / 60
        
        shift_start_combined = datetime.combine(date_obj, shift_start_dt)
        late_seconds = (t_in - shift_start_combined).total_seconds()
        late_minutes = max(0, late_seconds / 60)
        
        shift_end_combined = datetime.combine(date_obj, shift_end_dt)
        overtime_seconds = (t_out - shift_end_combined).total_seconds()
        overtime_minutes = max(0, overtime_seconds / 60)
        
        emp_id = str(row['ID']) # Ensure string
        rate = rates_db.get(emp_id, DEFAULT_RATE_PER_MINUTE)
        daily_pay = total_minutes_worked * rate
        
        results.append({
            'Date': row['Date'],
            'ID': row['ID'],
            'Name': row['Name'],
            'First_In': row['First_In'],
            'Last_Out': row['Last_Out'],
            'Worked': str(duration),
            'Late': round(late_minutes, 2),
            'Overtime': round(overtime_minutes, 2),
            'Pay': round(daily_pay, 0)
        })
        
    return pd.DataFrame(results)

# --- UI Layout ---

with st.sidebar:
    lang_choice = st.radio("Language / اللغة", ["English", "العربية"], horizontal=True)
    lang_code = "en" if lang_choice == "English" else "ar"
    txt = TRANSLATIONS[lang_code]

    st.header(txt["settings"])
    st.subheader(txt["shift_schedule"])
    shift_start = st.time_input(txt["start_time"], value=datetime.strptime("08:00", "%H:%M").time())
    shift_end = st.time_input(txt["end_time"], value=datetime.strptime("17:00", "%H:%M").time())
    st.divider()
    st.subheader(txt["data_upload"])
    uploaded_file = st.file_uploader(txt["upload_label"], type=['html', 'htm'])

st.title(txt["title"])
st.markdown(txt["subtitle"])

# Load rates from Google Sheets
rates_db = load_rates_from_sheet()

if uploaded_file:
    raw_df = parse_html_report(uploaded_file)
    
    if raw_df is not None and not raw_df.empty:
        
        # Check for new employees
        unique_employees = raw_df[['ID', 'Name']].drop_duplicates()
        new_emps = False
        
        for _, emp in unique_employees.iterrows():
            str_id = str(emp['ID'])
            if str_id not in rates_db:
                rates_db[str_id] = DEFAULT_RATE_PER_MINUTE
                new_emps = True
        
        if new_emps:
            # Sync back to Google Sheets immediately if new people found
            save_rates_to_sheet(rates_db)
            st.toast(txt["new_emps"], icon="ℹ️")

        tab1, tab2 = st.tabs([txt["tab_daily"], txt["tab_rates"]])

        with tab1:
            st.subheader(txt["report_header"].format(len(raw_df)))
            processed_df = calculate_metrics(raw_df, shift_start, shift_end, rates_db)
            
            display_df = processed_df.copy()
            display_df.rename(columns={
                'First_In': txt["col_in"], 'Last_Out': txt["col_out"],
                'Worked': txt["col_worked"], 'Late': txt["col_late"],
                'Overtime': txt["col_ot"], 'Pay': txt["col_pay"]
            }, inplace=True)
            
            st.dataframe(
                display_df,
                column_config={
                    txt["col_pay"]: st.column_config.NumberColumn(format="%d IQD"),
                    txt["col_late"]: st.column_config.NumberColumn(format="%.1f m"),
                    txt["col_ot"]: st.column_config.NumberColumn(format="%.1f m"),
                },
                use_container_width=True,
                hide_index=True
            )
            
            total_payout = processed_df['Pay'].sum()
            total_ot = processed_df['Overtime'].sum()
            col1, col2 = st.columns(2)
            col1.metric(txt["total_cost"], f"{total_payout:,.0f} IQD")
            col2.metric(txt["total_ot_mins"], f"{total_ot:,.1f} min")
            
            csv = display_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(txt["download_csv"], csv, "payroll_report.csv", "text/csv")

        with tab2:
            st.subheader(txt["manage_rates"])
            st.info(txt["rate_info"])
            
            rate_list = [{"ID": k, "Rate": v} for k, v in rates_db.items()]
            id_name_map = raw_df.set_index('ID')['Name'].to_dict()
            
            # Ensure proper mapping even if ID types mismatch in map
            # Convert map keys to string
            str_id_name_map = {str(k): v for k, v in id_name_map.items()}

            for r in rate_list:
                r['Name'] = str_id_name_map.get(str(r['ID']), txt["unknown"])
                
            rate_df = pd.DataFrame(rate_list)
            
            if not rate_df.empty:
                rate_df = rate_df[['ID', 'Name', 'Rate']]
                
                edited_df = st.data_editor(
                    rate_df,
                    key="rate_editor",
                    num_rows="dynamic",
                    disabled=["ID", "Name"],
                    column_config={
                        "Rate": st.column_config.NumberColumn(label="Rate (IQD/min)", min_value=0, format="%.4f")
                    },
                    use_container_width=True
                )
                
                if st.button(txt["save_btn"]):
                    new_rates = {}
                    for _, row in edited_df.iterrows():
                        new_rates[str(row['ID'])] = row['Rate']
                    
                    if save_rates_to_sheet(new_rates):
                        st.success(txt["success_save"])
                        # Force reload of rates
                        rates_db = load_rates_from_sheet() 
                    else:
                        st.error("Failed to save to Google Sheets.")
            else:
                st.warning(txt["error_parse"])
    else:
        st.error(txt["error_parse"])
else:
    st.info(txt["upload_prompt"])
