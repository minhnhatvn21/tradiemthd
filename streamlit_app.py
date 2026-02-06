import streamlit as st
import pandas as pd
import re
import firebase_admin
from firebase_admin import credentials, firestore
from werkzeug.security import generate_password_hash, check_password_hash

# ==========================================
# 1. KẾT NỐI FIREBASE
# ==========================================
# Kiểm tra xem app đã kết nối chưa để tránh lỗi init lại
if not firebase_admin._apps:
    # Lấy thông tin từ Streamlit Secrets
    key_dict = dict(st.secrets["firebase"])
    cred = credentials.Certificate(key_dict)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ==========================================
# 2. CÁC HÀM XỬ LÝ DATABASE (NO-SQL)
# ==========================================

def get_user_by_cccd(cccd):
    # Tìm trong collection 'users'
    docs = db.collection('users').where('so_cccd', '==', cccd).stream()
    for doc in docs:
        data = doc.to_dict()
        data['id'] = doc.id # Lưu ID tài liệu để update
        return data
    return None

def create_or_update_user(cccd, ma_hs, ho_ten, nien_khoa, status="5"):
    existing = get_user_by_cccd(cccd)
    if existing:
        # Update
        db.collection('users').document(existing['id']).update({
            'ma_hs': ma_hs,
            'nien_khoa': nien_khoa
            # Không update password hay status để tránh reset quyền
        })
        return False # Không tạo mới
    else:
        # Create
        data = {
            'so_cccd': cccd,
            'ma_hs': ma_hs,
            'ho_ten': ho_ten,
            'nien_khoa': nien_khoa,
            'login_status': status,
            'is_admin': False,
            'password_hash': generate_password_hash('123456')
        }
        db.collection('users').add(data)
        return True # Đã tạo mới

def get_scores(user_id, nam_hoc, hoc_ky):
    # Tìm điểm theo user_id (là document ID của user trong firebase)
    docs = db.collection('scores').where('user_id', '==', user_id)\
             .where('nam_hoc', '==', nam_hoc)\
             .where('hoc_ky', '==', hoc_ky).stream()
    
    results = []
    for doc in docs:
        results.append(doc.to_dict())
    return results

def get_assessment(user_id, nam_hoc):
    docs = db.collection('assessments').where('user_id', '==', user_id)\
             .where('nam_hoc', '==', nam_hoc).stream()
    for doc in docs:
        return doc.to_dict()
    return None

# Tạo Admin mặc định nếu chưa có
admin_check = db.collection('users').where('so_cccd', '==', 'admin').get()
if not admin_check:
    db.collection('users').add({
        'so_cccd': 'admin',
        'ho_ten': 'Quản Trị Viên',
        'is_admin': True,
        'nien_khoa': 'System',
        'login_status': 'full',
        'password_hash': generate_password_hash('admin123')
    })

# ==========================================
# 3. XỬ LÝ FILE EXCEL (AUTO PARSER)
# ==========================================

def clean_str(val):
    if pd.isna(val) or str(val).strip() == '': return None
    s = str(val).strip()
    return s.replace('.0', '') if s.endswith('.0') and len(s) > 2 else s

def detect_file_info(df):
    content = df.head(15).to_string()
    year_match = re.search(r'(\d{4})\s*-\s*(\d{4})', content)
    nam_hoc = f"{year_match.group(1)}-{year_match.group(2)}" if year_match else None
    
    if "Học kỳ 1" in content or "HỌC KỲ 1" in content: hoc_ky = "HK1"
    elif "Học kỳ 2" in content or "HỌC KỲ 2" in content: hoc_ky = "HK2"
    else: hoc_ky = "CaNam"
    return nam_hoc, hoc_ky

def calculate_grade(student_nien_khoa, file_nam_hoc):
    try:
        start_s = int(student_nien_khoa.split('-')[0])
        start_f = int(file_nam_hoc.split('-')[0])
        delta = start_f - start_s
        return 10 + delta if 0 <= delta <= 2 else 0
    except: return 0

def process_upload_auto(df):
    nam_hoc, hoc_ky = detect_file_info(df)
    if not nam_hoc: return "❌ Không tìm thấy 'Năm học' trong file.", "error"

    row_count, col_count = df.shape
    students_updated = 0
    progress = st.progress(0)
    
    # Cache user để tránh query nhiều lần
    all_users = db.collection('users').stream()
    user_map = {doc.to_dict().get('ma_hs'): doc.id for doc in all_users}
    
    # Chuẩn bị batch write (ghi hàng loạt cho nhanh)
    batch = db.batch()
    batch_count = 0

    for r in range(row_count):
        if r % 50 == 0: progress.progress(min(r / row_count, 1.0))
        for c in range(col_count):
            val = str(df.iat[r, c]).strip()
            if "Mã HS" in val:
                ma_hs = ""
                if ":" in val and len(val.split(':')[-1].strip()) > 3:
                    ma_hs = val.split(':')[-1].strip()
                else:
                    for k in range(1, 6):
                        if c + k < col_count:
                            cand = str(df.iat[r, c + k]).strip()
                            if len(cand) > 4 and cand[0].isdigit():
                                ma_hs = cand; break
                
                if not ma_hs: continue
                ma_hs = ma_hs.replace('.0', '')
                
                # Check user từ map
                user_id = user_map.get(ma_hs)
                if not user_id: continue

                # Lấy info user để tính khối (phải query lẻ nếu ko cache hết info)
                # Để tối ưu, ở đây ta query lẻ nếu cần thiết, hoặc giả định user map có nien_khoa
                # Đơn giản hóa: Query lẻ user để lấy nien_khoa chính xác
                user_doc = db.collection('users').document(user_id).get()
                user_data = user_doc.to_dict()
                
                khoi = calculate_grade(user_data.get('nien_khoa'), nam_hoc)
                if khoi == 0: continue
                
                students_updated += 1
                
                # Tìm header
                header_row = -1; col_mon = -1
                for k in range(1, 9):
                    if r + k >= row_count: break
                    for check_c in range(col_count):
                        txt = str(df.iat[r+k, check_c]).lower()
                        if "môn" in txt and "học" in txt:
                            header_row = r + k; col_mon = check_c; break
                    if header_row != -1: break
                if header_row == -1: continue

                # Map cột
                col_tx = col_gk = col_ck = col_tb = -1
                for cc in range(col_count):
                    h_txt = str(df.iat[header_row, cc]).lower()
                    if hoc_ky == "CaNam":
                        if "cả năm" in h_txt: col_tb = cc
                        elif col_tb == -1 and ("tb" == h_txt or "tbm" in h_txt): col_tb = cc
                    else:
                        if "tx" in h_txt: col_tx = cc
                        elif "gk" in h_txt: col_gk = cc
                        elif "ck" in h_txt: col_ck = cc
                        elif h_txt == "tb" or "tbm" in h_txt: col_tb = cc
                
                # Đọc điểm
                curr = header_row + 1; last_row = curr
                for _ in range(25):
                    if curr >= row_count: break
                    mon = str(df.iat[curr, col_mon]).strip()
                    if not mon or mon.lower() in ['nan', ''] or "kết quả" in mon.lower() or "xếp loại" in mon.lower():
                        last_row = curr; break
                    if mon.isdigit(): continue

                    v_tx = clean_str(df.iat[curr, col_tx]) if col_tx != -1 else None
                    v_gk = clean_str(df.iat[curr, col_gk]) if col_gk != -1 else None
                    v_ck = clean_str(df.iat[curr, col_ck]) if col_ck != -1 else None
                    v_tb = clean_str(df.iat[curr, col_tb]) if col_tb != -1 else None
                    
                    if hoc_ky == "CaNam" and not v_tb: curr += 1; continue

                    # FIREBASE LOGIC: Tạo ID duy nhất cho điểm để update
                    score_id = f"{user_id}_{nam_hoc}_{hoc_ky}_{mon}"
                    score_ref = db.collection('scores').document(score_id)
                    
                    score_data = {
                        'user_id': user_id, 'mon_hoc': mon, 'nam_hoc': nam_hoc,
                        'hoc_ky': hoc_ky, 'khoi': khoi,
                        'ddg_tx': v_tx, 'ddg_gk': v_gk, 'ddg_ck': v_ck, 'dtb_mon': v_tb
                    }
                    batch.set(score_ref, score_data) # Upsert
                    batch_count += 1
                    curr += 1; last_row = curr
                
                # Đánh giá (Cả năm)
                if hoc_ky == "CaNam":
                    k_ht = k_rl = dh = nx = None
                    for k in range(15):
                        chk_r = last_row + k
                        if chk_r >= row_count: break
                        row_txt = " | ".join([str(df.iat[chk_r, cx]) for cx in range(col_count) if pd.notna(df.iat[chk_r, cx])])
                        if "KQHT" in row_txt or "Học lực" in row_txt:
                            parts = row_txt.split('|')
                            for p in parts:
                                if "KQHT" in p or "Học lực" in p: k_ht = p.split(':')[-1].strip()
                                if "KQRL" in p or "Hạnh kiểm" in p: k_rl = p.split(':')[-1].strip()
                                if "Danh hiệu" in p: dh = p.split(':')[-1].strip()
                        if "Nhận xét" in row_txt: nx = row_txt.split(':')[-1].strip()
                    
                    if k_ht or k_rl or dh:
                        ass_id = f"{user_id}_{nam_hoc}"
                        ass_ref = db.collection('assessments').document(ass_id)
                        ass_data = {
                            'user_id': user_id, 'nam_hoc': nam_hoc,
                            'kq_hoc_tap': k_ht, 'kq_ren_luyen': k_rl,
                            'danh_hieu': dh, 'nhan_xet': nx
                        }
                        batch.set(ass_ref, ass_data)
                        batch_count += 1

                # Commit batch mỗi 400 operations (Firebase limit 500)
                if batch_count >= 400:
                    batch.commit()
                    batch = db.batch()
                    batch_count = 0

    batch.commit() # Commit phần còn lại
    progress.empty()
    return f"Xử lý xong {students_updated} HS. ({nam_hoc} - {hoc_ky})", "success"

# ==========================================
# 4. UI HỌC SINH (GIỮ NGUYÊN GIAO DIỆN)
# ==========================================

def render_html_grade_table(scores, loai_ky):
    if loai_ky == "CaNam": headers = ["Môn học", "TB Cả Năm"]
    else: headers = ["Môn học", "ĐĐGtx (TX)", "ĐĐGgk (GK)", "ĐĐGck (CK)", "TB Môn"]

    rows_html = ""
    for s in scores:
        mon_div = f"<div class='mon-hoc'>{s.get('mon_hoc')}</div>"
        if loai_ky == "CaNam":
            rows_html += f"<tr><td>{mon_div}</td><td>{s.get('dtb_mon') or '-'}</td></tr>"
        else:
            rows_html += f"<tr><td>{mon_div}</td><td class='tx-col'>{s.get('ddg_tx') or ''}</td><td>{s.get('ddg_gk') or ''}</td><td>{s.get('ddg_ck') or ''}</td><td>{s.get('dtb_mon') or ''}</td></tr>"
            
    thead = "".join([f"<th>{h}</th>" for h in headers])
    css = """<style>.g-cont {overflow-x:auto; margin-bottom:15px; border:1px solid #c8e6c9; border-radius:8px; background:white;} table {width:100%; border-collapse:collapse; font-family:sans-serif; font-size:14px; min-width:100%;} th, td {padding:8px; border:1px solid #c8e6c9; text-align:center; vertical-align:middle; color:#2e7d32;} th {background:#e8f5e9; color:#1b5e20; font-weight:bold;} th:first-child, td:first-child {position:sticky; left:0; background:#fff; z-index:5; text-align:left; border-right:2px solid #a5d6a7; color:#1b5e20; font-weight:bold; width:90px; min-width:90px; max-width:90px;} th:first-child {background:#e8f5e9; z-index:6;} .mon-hoc {white-space:normal; word-wrap:break-word; line-height:1.3;} .tx-col {white-space:normal; min-width:90px;} td:last-child {background:#f1f8e9; font-weight:bold; color:#1b5e20;}</style>"""
    return f"{css}<div class='g-cont'><table><thead><tr>{thead}</tr></thead><tbody>{rows_html}</tbody></table></div>"

def student_ui(user_data):
    st.markdown(f"### 👋 Xin chào, <span style='color:#1b5e20'>{user_data['ho_ten']}</span>", unsafe_allow_html=True)
    
    # Check pass
    if check_password_hash(user_data['password_hash'], "123456"):
        st.warning("⚠️ CẢNH BÁO: Mật khẩu mặc định.")
        st.info("🔒 Vui lòng đổi mật khẩu mới để xem điểm.")
        with st.form("change_pass_form"):
            new_p = st.text_input("Mật khẩu mới", type="password")
            conf_p = st.text_input("Nhập lại", type="password")
            if st.form_submit_button("Lưu & Xem điểm", type="primary"):
                if new_p != conf_p: st.error("Mật khẩu không khớp.")
                elif len(new_p) < 6: st.error("Quá ngắn.")
                elif new_p == "123456": st.error("Không dùng lại pass cũ.")
                else:
                    new_hash = generate_password_hash(new_p)
                    db.collection('users').document(user_data['id']).update({'password_hash': new_hash})
                    st.success("Thành công! Đăng nhập lại."); st.session_state.logged_in = False; st.rerun()
        return

    c1, c2, c3 = st.columns([1.5, 1.5, 1.2])
    c1.caption(f"🆔 Mã HS: **{user_data['ma_hs']}**")
    c2.caption(f"📅 Niên khóa: **{user_data['nien_khoa']}**")
    
    is_full = (user_data['login_status'] == "full")
    st_text = "Vô hạn" if is_full else f"Còn {user_data['login_status']} lần"
    st_color = "#1b5e20" if is_full else "#e65100"
    c3.markdown(f"<div style='border:1px solid {st_color}; padding:5px; border-radius:5px; text-align:center; color:{st_color}; font-size:13px'>Login: {st_text}</div>", unsafe_allow_html=True)

    if st.button("Đăng xuất"): st.session_state.logged_in = False; st.rerun()
    st.divider()

    try:
        start_year = int(user_data['nien_khoa'].split('-')[0])
        years_map = {10: f"{start_year}-{start_year+1}", 11: f"{start_year+1}-{start_year+2}", 12: f"{start_year+2}-{start_year+3}"}
    except: st.error("Lỗi Niên khóa."); return

    t10, t11, t12 = st.tabs(["Lớp 10", "Lớp 11", "Lớp 12"])
    
    for grade, tab in zip([10, 11, 12], [t10, t11, t12]):
        with tab:
            target_nam = years_map[grade]
            st.caption(f"Năm học: {target_nam}")
            
            hk1 = get_scores(user_data['id'], target_nam, "HK1")
            hk2 = get_scores(user_data['id'], target_nam, "HK2")
            cn = get_scores(user_data['id'], target_nam, "CaNam")
            ass = get_assessment(user_data['id'], target_nam)

            if not (hk1 or hk2 or cn):
                st.info("📭 Chưa có dữ liệu.")
                continue
            
            if hk1:
                st.markdown("**🍂 Học kỳ 1**")
                st.markdown(render_html_grade_table(hk1, "HK1"), unsafe_allow_html=True)
            if hk2:
                st.markdown("**🌸 Học kỳ 2**")
                st.markdown(render_html_grade_table(hk2, "HK2"), unsafe_allow_html=True)
            if cn:
                st.markdown("**🏆 Cả năm**")
                st.markdown(render_html_grade_table(cn, "CaNam"), unsafe_allow_html=True)
            
            if ass:
                st.markdown(f"""<div style="background:#e8f5e9; padding:15px; border-radius:8px; border-left:5px solid #2e7d32; margin-top:10px; color:#1b5e20"><h4 style="margin:0">📝 Đánh giá cuối năm</h4><p style="margin:5px 0"><b>Học lực:</b> {ass.get('kq_hoc_tap') or '--'} &nbsp;|&nbsp; <b>Hạnh kiểm:</b> {ass.get('kq_ren_luyen') or '--'}</p><p style="margin:5px 0"><b>Danh hiệu:</b> <span style="color:#d32f2f; font-weight:bold">{ass.get('danh_hieu') or '--'}</span></p><p style="margin:5px 0; font-style:italic">"{ass.get('nhan_xet') or ''}"</p></div>""", unsafe_allow_html=True)

# ==========================================
# 5. ADMIN UI
# ==========================================
def admin_ui():
    st.title("⚙️ Quản Trị (Firebase)")
    if st.button("Đăng xuất"): st.session_state.logged_in = False; st.rerun()

    tab1, tab2 = st.tabs(["📤 Upload Dữ Liệu", "👥 Quản Lý User"])

    with tab1:
        st.subheader("1. Import User (Excel)")
        st.caption("Cột: CCCD, Ma_HS, Ho_Ten, Nien_Khoa (2023-2026)")
        f_acc = st.file_uploader("Chọn file User", key="acc")
        if f_acc and st.button("Import"):
            try:
                df = pd.read_excel(f_acc)
                df.columns = [str(c).strip().lower() for c in df.columns]
                col_map = {}
                for c in df.columns:
                    if "cccd" in c: col_map['cccd'] = c
                    if "mã" in c or "ma_hs" in c: col_map['ma'] = c
                    if "tên" in c: col_map['ten'] = c
                    if "niên" in c or "khoa" in c: col_map['khoa'] = c
                
                cnt = 0
                for _, row in df.iterrows():
                    cccd = str(row[col_map.get('cccd', 'so_cccd')]).strip().replace('.0','')
                    ma = str(row[col_map.get('ma', 'ma_hs')]).strip().replace('.0','')
                    ten = row[col_map.get('ten', 'ho_ten')]
                    khoa = str(row[col_map.get('khoa', 'nien_khoa')]).strip()
                    
                    if create_or_update_user(cccd, ma, ten, khoa):
                        cnt += 1
                st.success(f"Đã tạo mới {cnt} user.")
            except Exception as e: st.error(f"Lỗi: {e}")

        st.divider(); st.subheader("2. Upload Điểm")
        files = st.file_uploader("Chọn file điểm", accept_multiple_files=True, key="scr")
        if files and st.button("Xử lý Điểm"):
            for f in files:
                try:
                    eng = 'xlrd' if f.name.endswith('.xls') else 'openpyxl'
                    df = pd.read_excel(f, header=None, engine=eng)
                    msg, stt = process_upload_auto(df)
                    if stt == "success": st.success(f"✅ {f.name}: {msg}")
                    else: st.error(f"❌ {f.name}: {msg}")
                except Exception as e: st.error(f"Lỗi {f.name}: {e}")

    with tab2:
        st.subheader("Phân Quyền")
        # Lấy tối đa 100 user để demo (Firebase load all có thể chậm nếu đông)
        users_stream = db.collection('users').where('is_admin', '==', False).limit(100).stream()
        data = []
        for doc in users_stream:
            u = doc.to_dict()
            u['id'] = doc.id
            data.append({
                "ID": u['id'], "Mã HS": u.get('ma_hs'), "Họ Tên": u.get('ho_ten'),
                "Full Access": (u.get('login_status') == "full"),
                "Số lần": u.get('login_status') if u.get('login_status') != "full" else "---",
                "Reset Pass": False
            })
        
        if data:
            edited_df = st.data_editor(
                pd.DataFrame(data),
                column_config={
                    "ID": None,
                    "Full Access": st.column_config.CheckboxColumn("Không giới hạn?", default=False),
                    "Reset Pass": st.column_config.CheckboxColumn("Reset Mật Khẩu (123456)?", default=False),
                    "Số lần": st.column_config.TextColumn("Lượt còn lại", disabled=True)
                },
                disabled=["Mã HS", "Họ Tên"],
                hide_index=True, use_container_width=True
            )
            
            if st.button("Lưu Thay Đổi"):
                batch = db.batch()
                c_up = 0
                for idx, row in edited_df.iterrows():
                    ref = db.collection('users').document(row['ID'])
                    updates = {}
                    
                    # Logic Full
                    if row['Full Access']: updates['login_status'] = 'full'
                    else: updates['login_status'] = '5'
                    
                    # Logic Reset
                    if row['Reset Pass']:
                        updates['password_hash'] = generate_password_hash('123456')
                    
                    if updates:
                        batch.update(ref, updates)
                        c_up += 1
                batch.commit()
                st.success(f"Đã cập nhật {c_up} user!")
                st.rerun()

# ==========================================
# 6. MAIN
# ==========================================
def main():
    st.set_page_config(page_title="EduScore Pro", page_icon="🎓", layout="wide")
    if 'logged_in' not in st.session_state: st.session_state.logged_in = False
    if 'user_data' not in st.session_state: st.session_state.user_data = None

    if not st.session_state.logged_in:
        c1, c2, c3 = st.columns([1,1.5,1])
        with c2:
            st.title("🎓 Tra Cứu Điểm")
            with st.form("login"):
                u = st.text_input("Số CCCD")
                p = st.text_input("Mật khẩu", type="password")
                if st.form_submit_button("Đăng nhập", type="primary"):
                    user_data = get_user_by_cccd(u)
                    if user_data and check_password_hash(user_data.get('password_hash'), p):
                        allow = False
                        if user_data.get('is_admin') or user_data.get('login_status') == "full": allow = True
                        else:
                            try:
                                c = int(user_data.get('login_status'))
                                if c > 0:
                                    allow = True
                                    # Trừ lượt
                                    db.collection('users').document(user_data['id']).update({'login_status': str(c-1)})
                                    user_data['login_status'] = str(c-1) # Update local
                                else: st.error("🚫 Hết lượt truy cập!")
                            except: st.error("Lỗi tài khoản")
                        
                        if allow:
                            st.session_state.logged_in = True
                            st.session_state.user_data = user_data
                            st.rerun()
                    else: st.error("Sai thông tin!")
    else:
        if st.session_state.user_data.get('is_admin'): admin_ui()
        else: student_ui(st.session_state.user_data)

if __name__ == "__main__":
    main()
