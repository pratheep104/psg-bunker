import math
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np

def _extract_name_from_soup(soup):
    """Helper to find the student name in a BeautifulSoup parsed page"""
    # Try common label/span IDs where name appears
    for label_id in ["lblWelcomeStudName", "lblName", "lblStudentName",
                     "lblWelcome", "lblStudName", "lblstudname",
                     "Label1", "lbl_StuName", "lbl_stuname"]:
        elem = soup.find(id=label_id)
        if elem and elem.get_text(strip=True):
            name = elem.get_text(strip=True)
            # Clean up "Welcome, Name" patterns
            if "welcome" in name.lower():
                name = name.split(",", 1)[-1].strip().rstrip("!").strip()
            if name and len(name) > 1 and not name.replace(" ", "").isdigit():
                return name

    # Search all spans, labels, divs for welcome text with name
    for tag in soup.find_all(["span", "label", "div", "td"]):
        text = tag.get_text(strip=True)
        if not text:
            continue
        text_lower = text.lower()
        if "welcome" in text_lower and len(text) > 8 and len(text) < 100:
            if "," in text:
                name = text.split(",", 1)[1].strip().rstrip("!").strip()
            else:
                for prefix in ["Welcome ", "welcome ", "WELCOME "]:
                    if text.startswith(prefix):
                        name = text[len(prefix):].strip().rstrip("!").strip()
                        break
                else:
                    continue
            if name and len(name) > 1 and not name.replace(" ", "").isdigit():
                return name
    return None

def return_attendance(username, pwd):
    try:
        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        # ---- New portal login (/studzone/) ----
        login_page_url = "https://ecampus.psgtech.ac.in/studzone/"
        r = session.get(login_page_url, headers=headers)
        soup = BeautifulSoup(r.text, 'html.parser')

        # Extract the anti-forgery token
        token_input = soup.find("input", {"name": "__RequestVerificationToken"})
        token = token_input["value"] if token_input else ""

        payload = {
            "rollno": username,
            "password": pwd,
            "chkterms": "on",
            "__RequestVerificationToken": token
        }

        login_response = session.post(login_page_url, data=payload, headers=headers, allow_redirects=True)

        # Check if login failed — if we're still on the login page
        login_soup = BeautifulSoup(login_response.text, 'html.parser')
        if login_soup.find("input", {"id": "rollno"}) and login_soup.find("input", {"id": "password"}):
            return "Invalid Password"

        # Try to extract student name from post-login page
        student_name = _extract_name_from_soup(login_soup)

        # ---- Get attendance from new portal ----
        attendance_url = "https://ecampus.psgtech.ac.in/studzone/Attendance/StudentPercentage"
        page = session.get(attendance_url, headers=headers)
        soup = BeautifulSoup(page.text, 'html.parser')

        # Also try extracting name from attendance page if not found yet
        if not student_name:
            student_name = _extract_name_from_soup(soup)
        student_info = {
            "name": student_name or "",
            "registerNumber": username,
            "department": "",
            "semester": "",
            "section": ""
        }

        try:
            info_row = soup.find(
                "div",
                class_="row border mt-3 p-3 rounded p-2 bg-light shadow-sm"
            )

            if info_row:
                cols = info_row.find_all("div", class_="col-md-3")

                for col in cols:
                    text = col.get_text(separator=" ", strip=True)

                    if "Name" in text:
                        parts = text.split(":")
                        if len(parts) > 1:
                            student_info["name"] = parts[-1].strip()

                    elif "Program" in text:
                        parts = text.split(":")
                        if len(parts) > 1:
                            student_info["department"] = parts[-1].strip()

                    elif "Sem No" in text:
                        parts = text.split(":")
                        if len(parts) > 1:
                            student_info["semester"] = parts[-1].strip()

        except Exception:
            pass
        # Find the attendance table — try DataTables table or any table with attendance data
        table = soup.find("table", {"class": "table"})
        if not table:
            table = soup.find("table", {"id": lambda x: x and "dataTable" in str(x).lower()})
        if not table:
            # Try finding any table with attendance-like headers
            for t in soup.find_all("table"):
                t_text = t.get_text()
                if "Course Code" in t_text or "Attendance" in t_text:
                    table = t
                    break
        if not table:
            return [], session, student_name

        data = []
        # Extract header row
        thead = table.find("thead")
        if thead:
            header_row = thead.find("tr")
            if header_row:
                header_cols = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
                data.append(header_cols)

        # Extract data rows
        tbody = table.find("tbody")
        rows_parent = tbody if tbody else table
        for row in rows_parent.find_all("tr"):
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if cols and any(cols):
                data.append(cols)

        # ---- Also login to old portal for timetable/course plan ----
        old_session = requests.Session()
        try:
            old_login_url = "https://ecampus.psgtech.ac.in/studzone2/"
            r2 = old_session.get(old_login_url, headers=headers)
            old_soup = BeautifulSoup(r2.text, 'html.parser')
            viewstate = old_soup.select("#__VIEWSTATE")[0]["value"]
            eventvalidation = old_soup.select("#__EVENTVALIDATION")[0]["value"]
            viewstategen = old_soup.select("#__VIEWSTATEGENERATOR")[0]["value"]
            old_payload = {
                "__VIEWSTATE": viewstate,
                "__VIEWSTATEGENERATOR": viewstategen,
                "__EVENTVALIDATION": eventvalidation,
                "txtusercheck": username,
                "txtpwdcheck": pwd,
                "abcd3": "Login"
            }
            old_session.post(old_login_url, data=old_payload, headers=headers)
        except:
            old_session = session  # Fallback to new session

        return data, old_session, student_name, student_info

    except Exception as e:
        return f"Error: {str(e)}"

def get_course_plan(session):
    """Get course plan with course titles"""
    try:
        course_url = "https://ecampus.psgtech.ac.in/studzone2/AttWfStudTimtab.aspx"
        page = session.get(course_url)
        soup = BeautifulSoup(page.text, 'html.parser')

        table = soup.find("table", {"id": "TbCourDesc"})
        if not table:
            return {}

        course_mapping = {}
        for row in table.find_all("tr")[1:]:  # Skip header
            cols = [ele.text.strip() for ele in row.find_all("td")]
            if len(cols) >= 2:
                course_mapping[cols[0]] = cols[1]

        return course_mapping
    except:
        return {}

def get_student_name(session):
    """Get student name from the eCampus portal"""
    try:
        # Try multiple pages where the name might appear
        urls = [
            "https://ecampus.psgtech.ac.in/studzone2/",
            "https://ecampus.psgtech.ac.in/studzone2/CAaborali498.aspx",
            "https://ecampus.psgtech.ac.in/studzone2/AttWfPercView.aspx",
            "https://ecampus.psgtech.ac.in/studzone2/AttWfStudTimtab.aspx",
        ]

        for url in urls:
            try:
                page = session.get(url, timeout=5)
                soup = BeautifulSoup(page.text, 'html.parser')

                # Try common label/span IDs where name appears
                for label_id in ["lblWelcomeStudName", "lblName", "lblStudentName",
                                 "lblWelcome", "lblStudName", "lblstudname",
                                 "Label1", "lbl_StuName", "lbl_stuname"]:
                    elem = soup.find(id=label_id)
                    if elem and elem.get_text(strip=True):
                        name = elem.get_text(strip=True)
                        # Clean up "Welcome, Name" patterns
                        if "welcome" in name.lower():
                            name = name.split(",", 1)[-1].strip().rstrip("!").strip()
                        if name and len(name) > 1 and not name.replace(" ", "").isdigit():
                            return name

                # Search all spans, labels, divs for welcome text with name
                for tag in soup.find_all(["span", "label", "div", "td"]):
                    text = tag.get_text(strip=True)
                    if not text:
                        continue
                    text_lower = text.lower()
                    # Look for "Welcome, Name" or "Welcome Name" patterns
                    if "welcome" in text_lower and len(text) > 8 and len(text) < 100:
                        # Try splitting by comma
                        if "," in text:
                            name = text.split(",", 1)[1].strip().rstrip("!").strip()
                        else:
                            # Try removing "Welcome" prefix
                            for prefix in ["Welcome ", "welcome ", "WELCOME "]:
                                if text.startswith(prefix):
                                    name = text[len(prefix):].strip().rstrip("!").strip()
                                    break
                            else:
                                continue
                        if name and len(name) > 1 and not name.replace(" ", "").isdigit():
                            return name

            except:
                continue

        return None
    except:
        return None

def get_timetable(session):
    """Get full weekly timetable from the timetable page"""
    try:
        timetable_url = "https://ecampus.psgtech.ac.in/studzone2/AttWfStudTimtab.aspx"
        page = session.get(timetable_url)
        soup = BeautifulSoup(page.text, 'html.parser')

        # Try to find the timetable grid table (usually has id like TbTimtab or similar)
        timetable_table = None
        # Look for tables that contain day names (Mon, Tue, etc.)
        for table in soup.find_all("table"):
            table_text = table.get_text()
            if any(day in table_text for day in ["MON", "TUE", "WED", "THU", "FRI", "Mon", "Tue", "Wed", "Thu", "Fri"]):
                # Skip the course description table
                if table.get("id") == "TbCourDesc":
                    continue
                timetable_table = table
                break

        if not timetable_table:
            return {"headers": [], "rows": []}

        # Extract headers and rows
        headers = []
        rows = []
        all_rows = timetable_table.find_all("tr")

        for i, row in enumerate(all_rows):
            cells = row.find_all(["th", "td"])
            cell_texts = [cell.get_text(strip=True) for cell in cells]

            if not any(cell_texts):  # Skip empty rows
                continue

            # Skip rows that are just a single number (stray row counts from HTML)
            if len(cell_texts) == 1 and cell_texts[0].isdigit():
                continue

            # Skip rows with very few cells compared to expected timetable width
            if headers and len(cell_texts) < 2:
                continue

            if i == 0 or (not headers and cell_texts):
                headers = cell_texts
            else:
                if any(cell_texts):  # Only add non-empty rows
                    # Ensure row has the same number of columns as headers
                    if headers and len(cell_texts) != len(headers):
                        # Pad or trim to match header length
                        while len(cell_texts) < len(headers):
                            cell_texts.append("")
                        cell_texts = cell_texts[:len(headers)]
                    rows.append(cell_texts)

        return {"headers": headers, "rows": rows}
    except:
        return {"headers": [], "rows": []}

def data_json(data, course_plan=None):
    response = []
    for item in data[1:]:
        if len(item) < 8:
            continue

        try:
            total_hours = int(item[1])
            exception_hour = int(item[2]) if item[2] else 0
            total_present = int(item[4])
            # Column 5 = real attendance percentage
            real_percentage = float(item[5])
            # Column 7 = attendance percentage with medical exception
            percentage_with_medical = float(item[7]) if len(item) > 7 and item[7] else real_percentage
        except (ValueError, IndexError):
            continue

        temp = {
            "name": item[0],
            "course_title": course_plan.get(item[0], item[0]) if course_plan else item[0],
            "total_hours": total_hours,
            "exception_hour": exception_hour,
            "total_present": total_present,
            "percentage_of_attendance": real_percentage,
            "percentage_with_medical": percentage_with_medical,
            "attendance_from": item[8] if len(item) > 8 else "",
            "attendance_to": item[9] if len(item) > 9 else ""
        }

        # Calculate bunk/attend based on REAL attendance
        if temp['percentage_of_attendance'] < 75:
            temp['class_to_attend'] = math.ceil(
                (0.75 * temp['total_hours'] - temp['total_present']) / 0.25
            )
        else:
            temp['class_to_bunk'] = math.floor(
                (temp['total_present'] - 0.75 * temp['total_hours']) / 0.75
            )

        response.append(temp)
    return response

