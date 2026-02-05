import streamlit as st
import pandas as pd
import re
from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, Text
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from werkzeug.security import generate_password_hash, check_password_hash

# ==========================================
# 1. CẤU HÌNH DATABASE
# ==========================================
Base = declarative_base()
engine = create_engine('sqlite:///database.db', connect_args={'check_same_thread': False})
Session = sessionmaker(bind=engine)
session = Session()

class User(Base):
    __tablename__ = 'user'
    id = Column(Integer, primary_key=True)
    so_cccd = Column(String(20), unique=True, nullable=False)
    ma_hs = Column(String(20), unique=True, nullable=True)
    ho_ten = Column(String(100), nullable=False)
    password_hash = Column(String(200))
    is_admin = Column(Boolean, default=False)
    nien_khoa = Column(String(20)) 
    login_status = Column(String(20), default="5") 
    
    scores = relationship('Score', backref='student', lazy=True)
    assessments = relationship('Assessment', backref='student', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Score(Base):
    __tablename__ = 'score'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    mon_hoc = Column(String(50), nullable=False)
    ddg_tx = Column(String(100)) 
    ddg_gk = Column(String(50))
    ddg_ck = Column(String(50))
    dtb_mon = Column(String(50))
    hoc_ky = Column(String(20)) 
    nam_hoc = Column(String(20)) 
    khoi = Column(Integer)

class Assessment(Base):
    __tablename__ = 'assessment'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    nam_hoc = Column(String(20))
    kq_hoc_tap = Column(String(50)) 
    kq_ren_luyen = Column(String(50))
    danh_hieu = Column(String(100))
    nhan_xet = Column(Text)

Base.metadata.create_all(engine)

# Admin mặc định
if not session.query(User).filter_by(so_cccd='admin').first():
    admin = User(so_cccd='admin', ho_ten='Quản Trị Viên', is_admin=True, nien_khoa="System", login_status="full")
    admin.set_password('admin123')
    session.add(admin)
    session.commit()

# ==========================================
# 2. XỬ LÝ FILE EXCEL (AUTO PARSER)
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
                user = session.query(User).filter_by(ma_hs=ma_hs).first()
                if not user: continue 
                
                khoi = calculate_grade(user.nien_khoa, nam_hoc)
                if khoi == 0: continue
                
                students_updated += 1
                header_row = -1; col_mon = -1
                for k in range(1, 9):
                    if r + k >= row_count: break
                    for check_c in range(col_count):
                        txt = str(df.iat[r+k, check_c]).lower()
                        if "môn" in txt and "học" in txt:
                            header_row = r + k; col_mon = check_c; break
                    if header_row != -1: break
                
                if header_row == -1: continue

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

                    score = session.query(Score).filter_by(student_id=user.id, mon_hoc=mon, nam_hoc=nam_hoc, hoc_ky=hoc_ky).first()
                    if not score:
                        score = Score(student_id=user.id, mon_hoc=mon, nam_hoc=nam_hoc, hoc_ky=hoc_ky, khoi=khoi)
                        session.add(score)
                    score.ddg_tx = v_tx; score.ddg_gk = v_gk; score.ddg_ck = v_ck; score.dtb_mon = v_tb
                    curr += 1; last_row = curr

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
                        ass = session.query(Assessment).filter_by(student_id=user.id, nam_hoc=nam_hoc).first()
                        if not ass:
                            ass = Assessment(student_id=user.id, nam_hoc=nam_hoc); session.add(ass)
                        ass.kq_hoc_tap = k_ht; ass.kq_ren_luyen = k_rl; ass.danh_hieu = dh; ass.nhan_xet = nx

    session.commit()
    progress.empty()
    return f"Xử lý xong {students_updated} HS. ({nam_hoc} - {hoc_ky})", "success"

# ==========================================
# 3. GIAO DIỆN HỌC SINH
# ==========================================

def render_html_grade_table(scores, loai_ky):
    if loai_ky == "CaNam": headers = ["Môn học", "TB Cả Năm"]
    else: headers = ["Môn học", "ĐĐGtx (TX)", "ĐĐGgk (GK)", "ĐĐGck (CK)", "TB Môn"]

    rows_html = ""
    for s in scores:
        if loai_ky == "CaNam":
            rows_html += f"<tr><td>{s.mon_hoc}</td><td>{s.dtb_mon or '-'}</td></tr>"
        else:
            rows_html += f"<tr><td>{s.mon_hoc}</td><td style='white-space:normal; min-width:100px'>{s.ddg_tx or ''}</td><td>{s.ddg_gk or ''}</td><td>{s.ddg_ck or ''}</td><td>{s.dtb_mon or ''}</td></tr>"
            
    thead = "".join([f"<th>{h}</th>" for h in headers])
    css = """<style>.g-cont {overflow-x:auto; margin-bottom:15px; border:1px solid #ddd; border-radius:8px; background:white;} .vn-tbl {width:100%; border-collapse:collapse; font-family:sans-serif; font-size:14px; min-width:500px;} .vn-tbl th, .vn-tbl td {padding:10px; border:1px solid #ddd; text-align:center; white-space:nowrap;} .vn-tbl th {background:#f8f9fa; color:#333; font-weight:bold;} .vn-tbl th:first-child, .vn-tbl td:first-child {position:sticky; left:0; background:#fff; z-index:5; text-align:left; border-right:2px solid #ccc;} .vn-tbl th:first-child {background:#f8f9fa; z-index:6;} .vn-tbl td:last-child {color:#d32f2f; font-weight:bold; background:#fffde7;}</style>"""
    return f"{css}<div class='g-cont'><table class='vn-tbl'><thead><tr>{thead}</tr></thead><tbody>{rows_html}</tbody></table></div>"

def student_ui(user):
    st.markdown(f"### 👋 Xin chào, {user.ho_ten}")
    
    # ----------------------------------------------------
    # TÍNH NĂNG: KIỂM TRA MẬT KHẨU MẶC ĐỊNH (123456)
    # ----------------------------------------------------
    if user.check_password("123456"):
        st.warning("⚠️ CẢNH BÁO: Bạn đang sử dụng mật khẩu mặc định.")
        st.info("🔒 Để bảo mật thông tin điểm số, bạn BẮT BUỘC phải đổi mật khẩu mới để tiếp tục.")
        
        with st.form("change_pass_form"):
            st.write("---")
            new_p = st.text_input("Mật khẩu mới", type="password")
            conf_p = st.text_input("Nhập lại mật khẩu mới", type="password")
            if st.form_submit_button("Đổi mật khẩu & Xem điểm", type="primary"):
                if new_p != conf_p:
                    st.error("Mật khẩu xác nhận không khớp.")
                elif len(new_p) < 6:
                    st.error("Mật khẩu phải dài hơn 6 ký tự.")
                elif new_p == "123456":
                    st.error("Không được đặt trùng với mật khẩu mặc định!")
                else:
                    user.set_password(new_p)
                    session.commit()
                    st.success("Đổi mật khẩu thành công! Vui lòng đăng nhập lại.")
                    st.session_state.logged_in = False
                    st.rerun()
        return # DỪNG KHÔNG CHO XEM ĐIỂM NẾU CHƯA ĐỔI PASS
    # ----------------------------------------------------

    c1, c2, c3 = st.columns([1.5, 1.5, 1.2])
    c1.info(f"🆔 Mã HS: **{user.ma_hs}**")
    c2.info(f"📅 Niên khóa: **{user.nien_khoa}**")
    
    is_full = (user.login_status == "full")
    st_text = "Vô hạn" if is_full else f"Còn {user.login_status} lần"
    st_color = "green" if is_full else "orange"
    c3.markdown(f"<div style='background:#fff; border:1px solid {st_color}; padding:8px; border-radius:5px; text-align:center; color:{st_color}; font-weight:bold'>Login: {st_text}</div>", unsafe_allow_html=True)

    if st.button("Đăng xuất"):
        st.session_state.logged_in = False
        st.rerun()
    st.divider()

    try:
        start_year = int(user.nien_khoa.split('-')[0])
        years_map = {10: f"{start_year}-{start_year+1}", 11: f"{start_year+1}-{start_year+2}", 12: f"{start_year+2}-{start_year+3}"}
    except: st.error("Lỗi niên khóa HS."); return

    t10, t11, t12 = st.tabs(["Lớp 10", "Lớp 11", "Lớp 12"])
    
    for grade, tab in zip([10, 11, 12], [t10, t11, t12]):
        with tab:
            target_nam = years_map[grade]
            st.caption(f"Năm học: {target_nam}")
            
            hk1 = session.query(Score).filter_by(student_id=user.id, nam_hoc=target_nam, hoc_ky="HK1").all()
            hk2 = session.query(Score).filter_by(student_id=user.id, nam_hoc=target_nam, hoc_ky="HK2").all()
            cn = session.query(Score).filter_by(student_id=user.id, nam_hoc=target_nam, hoc_ky="CaNam").all()
            ass = session.query(Assessment).filter_by(student_id=user.id, nam_hoc=target_nam).first()

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
                st.markdown(f"""<div style="background:#e3f2fd; padding:15px; border-radius:8px; border-left:5px solid #2196f3; margin-top:10px;"><h4 style="margin:0; color:#0d47a1">📝 Đánh giá cuối năm</h4><p style="margin:5px 0"><b>Học lực:</b> {ass.kq_hoc_tap or '--'} &nbsp;|&nbsp; <b>Hạnh kiểm:</b> {ass.kq_ren_luyen or '--'}</p><p style="margin:5px 0"><b>Danh hiệu:</b> <span style="color:red; font-weight:bold">{ass.danh_hieu or '--'}</span></p><p style="margin:5px 0; font-style:italic">"{ass.nhan_xet or ''}"</p></div>""", unsafe_allow_html=True)

# ==========================================
# 4. ADMIN UI
# ==========================================
def admin_ui():
    st.title("⚙️ Trang Quản Trị")
    if st.button("Đăng xuất"): st.session_state.logged_in = False; st.rerun()

    tab1, tab2 = st.tabs(["📤 Upload Dữ Liệu", "👥 Quản Lý User"])

    with tab1:
        st.subheader("1. Import User (Excel)")
        st.caption("Cột cần thiết: CCCD, Ma_HS, Ho_Ten, Nien_Khoa (2023-2026)")
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
                    
                    u = session.query(User).filter_by(so_cccd=cccd).first()
                    if not u:
                        u = User(so_cccd=cccd, ma_hs=ma, ho_ten=ten, nien_khoa=khoa, login_status="5")
                        u.set_password('123456')
                        session.add(u); cnt += 1
                    else: u.ma_hs = ma; u.nien_khoa = khoa
                session.commit(); st.success(f"Đã cập nhật {cnt} user.")
            except Exception as e: st.error(f"Lỗi: {e}")

        st.divider(); st.subheader("2. Upload Điểm (Auto-Detect)")
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
        st.subheader("Phân Quyền & Reset Mật Khẩu")
        users = session.query(User).filter(User.is_admin == False).all()
        if users:
            data = []
            for u in users:
                data.append({
                    "ID": u.id, "Mã HS": u.ma_hs, "Họ Tên": u.ho_ten, "Niên khóa": u.nien_khoa,
                    "Full Access": (u.login_status == "full"),
                    "Số lần": u.login_status if u.login_status != "full" else "---",
                    "Reset Pass (123456)": False
                })
            df_users = pd.DataFrame(data)
            edited_df = st.data_editor(
                df_users,
                column_config={
                    "ID": None,
                    "Full Access": st.column_config.CheckboxColumn("Không giới hạn?", default=False),
                    "Reset Pass (123456)": st.column_config.CheckboxColumn("Reset Mật Khẩu?", default=False, help="Tích vào để đặt lại mật khẩu về 123456"),
                    "Số lần": st.column_config.TextColumn("Lượt còn lại", disabled=True)
                },
                disabled=["Mã HS", "Họ Tên", "Niên khóa"],
                hide_index=True, use_container_width=True
            )
            
            if st.button("Lưu Thay Đổi"):
                c_full = 0; c_reset = 0
                for idx, row in edited_df.iterrows():
                    u_id = row['ID']; u_db = session.query(User).get(int(u_id))
                    if u_db:
                        # Logic Full
                        is_full = row['Full Access']
                        cur_full = (u_db.login_status == "full")
                        if is_full and not cur_full: u_db.login_status = "full"; c_full += 1
                        elif not is_full and cur_full: u_db.login_status = "5"; c_full += 1
                        
                        # Logic Reset Pass
                        if row['Reset Pass (123456)']:
                            u_db.set_password('123456')
                            c_reset += 1
                session.commit()
                st.success(f"Cập nhật quyền: {c_full} HS. Reset mật khẩu: {c_reset} HS.")
                st.rerun()

# ==========================================
# 5. MAIN
# ==========================================
def main():
    st.set_page_config(page_title="EduScore Pro", page_icon="🎓", layout="wide")
    if 'logged_in' not in st.session_state: st.session_state.logged_in = False
    if 'user_id' not in st.session_state: st.session_state.user_id = None
    if 'is_admin' not in st.session_state: st.session_state.is_admin = False

    if not st.session_state.logged_in:
        c1, c2, c3 = st.columns([1,1.5,1])
        with c2:
            st.title("🎓 Tra Cứu Điểm")
            with st.form("login"):
                u = st.text_input("Số CCCD")
                p = st.text_input("Mật khẩu", type="password")
                if st.form_submit_button("Đăng nhập", type="primary"):
                    user = session.query(User).filter_by(so_cccd=u).first()
                    if user and user.check_password(p):
                        allow = False
                        if user.is_admin or user.login_status == "full": allow = True
                        else:
                            try:
                                c = int(user.login_status)
                                if c > 0: allow = True; user.login_status = str(c-1); session.commit()
                                else: st.error("🚫 Hết lượt truy cập! Liên hệ GVCN.")
                            except: st.error("Lỗi tài khoản")
                        
                        if allow:
                            st.session_state.logged_in = True; st.session_state.user_id = user.id; st.session_state.is_admin = user.is_admin; st.rerun()
                    else: st.error("Sai thông tin!")
    else:
        if st.session_state.is_admin: admin_ui()
        else: student_ui(session.query(User).get(st.session_state.user_id))

if __name__ == "__main__":
    main()
