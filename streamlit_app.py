import streamlit as st
import pandas as pd
import re
from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, Text
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from werkzeug.security import generate_password_hash, check_password_hash

# ==========================================
# 1. CẤU HÌNH DATABASE & MODELS
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
    
    # Niên khóa: VD "2023-2026" (QUAN TRỌNG: Dùng để tính Lớp)
    nien_khoa = Column(String(20)) 
    
    # "full" = Vô hạn, số (vd "5") = Số lần còn lại
    login_status = Column(String(20), default="full") 
    
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
    # Lưu chuỗi để giữ nguyên format (VD: "8.0 9.0")
    ddg_tx = Column(String(100)) 
    ddg_gk = Column(String(50))
    ddg_ck = Column(String(50))
    dtb_mon = Column(String(50))
    
    hoc_ky = Column(String(20)) # HK1, HK2, CaNam
    nam_hoc = Column(String(20)) 
    khoi = Column(Integer) # 10, 11, 12

class Assessment(Base):
    """Lưu đánh giá cuối năm: Hạnh kiểm, Học lực, Danh hiệu"""
    __tablename__ = 'assessment'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    nam_hoc = Column(String(20))
    kq_hoc_tap = Column(String(50)) 
    kq_ren_luyen = Column(String(50))
    danh_hieu = Column(String(100))
    nhan_xet = Column(Text)

Base.metadata.create_all(engine)

# Tạo Admin mặc định
if not session.query(User).filter_by(so_cccd='admin').first():
    admin = User(so_cccd='admin', ho_ten='Quản Trị Viên', is_admin=True, nien_khoa="System", login_status="full")
    admin.set_password('admin123')
    session.add(admin)
    session.commit()

# ==========================================
# 2. HÀM XỬ LÝ LOGIC (AUTO-PARSER)
# ==========================================

def clean_str(val):
    if pd.isna(val) or str(val).strip() == '': return None
    s = str(val).strip()
    return s.replace('.0', '') if s.endswith('.0') and len(s) > 2 else s

def detect_file_info(df):
    """Tự động đọc Năm học và Học kỳ từ nội dung file Excel"""
    # Lấy 15 dòng đầu để quét header
    content = df.head(15).to_string()
    
    # 1. Tìm năm học (VD: 2023 - 2024 hoặc 2023-2024)
    year_match = re.search(r'(\d{4})\s*-\s*(\d{4})', content)
    nam_hoc = f"{year_match.group(1)}-{year_match.group(2)}" if year_match else None
    
    # 2. Tìm học kỳ
    if "Học kỳ 1" in content or "HỌC KỲ 1" in content:
        hoc_ky = "HK1"
    elif "Học kỳ 2" in content or "HỌC KỲ 2" in content:
        hoc_ky = "HK2"
    else:
        # Mặc định là Cả Năm nếu không thấy chữ HK1/HK2
        hoc_ky = "CaNam"
        
    return nam_hoc, hoc_ky

def calculate_grade(student_nien_khoa, file_nam_hoc):
    """Tính Lớp (10, 11, 12) dựa trên Niên khóa HS và Năm học của file"""
    try:
        start_student = int(student_nien_khoa.split('-')[0])
        start_file = int(file_nam_hoc.split('-')[0])
        delta = start_file - start_student
        
        if delta == 0: return 10
        elif delta == 1: return 11
        elif delta == 2: return 12
        else: return 0 
    except:
        return 0

def process_upload_auto(df):
    """Hàm xử lý thông minh: Tự tìm Mã HS, tự tìm Môn, tự lấy điểm"""
    nam_hoc, hoc_ky = detect_file_info(df)
    if not nam_hoc:
        return "❌ Không tìm thấy thông tin 'Năm học' (cần dòng chữ dạng 'Năm học 20xx - 20xx').", "error"

    row_count, col_count = df.shape
    students_updated = 0
    progress = st.progress(0)
    
    for r in range(row_count):
        if r % 50 == 0: progress.progress(min(r / row_count, 1.0))
        
        for c in range(col_count):
            val = str(df.iat[r, c]).strip()
            
            # --- TÌM MÃ HS ---
            if "Mã HS" in val:
                ma_hs = ""
                # TH1: Chung ô (Mã HS : 123)
                if ":" in val and len(val.split(':')[-1].strip()) > 3:
                    ma_hs = val.split(':')[-1].strip()
                # TH2: Lệch ô bên phải
                else:
                    for k in range(1, 5):
                        if c + k < col_count:
                            cand = str(df.iat[r, c + k]).strip()
                            if len(cand) > 4 and cand[0].isdigit():
                                ma_hs = cand; break
                
                if not ma_hs: continue
                ma_hs = ma_hs.replace('.0', '')
                
                # Tìm User trong DB
                user = session.query(User).filter_by(ma_hs=ma_hs).first()
                if not user: continue 
                
                # Tính Khối lớp
                khoi = calculate_grade(user.nien_khoa, nam_hoc)
                if khoi == 0: continue 
                
                students_updated += 1
                
                # --- TÌM HEADER BẢNG ĐIỂM ---
                header_row = -1
                col_mon = -1
                
                # Quét 7 dòng dưới Mã HS để tìm dòng tiêu đề
                for k in range(1, 8):
                    if r + k >= row_count: break
                    for check_c in range(col_count):
                        txt = str(df.iat[r+k, check_c]).lower()
                        if "môn" in txt and "học" in txt:
                            header_row = r + k
                            col_mon = check_c
                            break
                    if header_row != -1: break
                
                if header_row == -1: continue

                # --- MAP CỘT ĐIỂM ---
                col_tx = col_gk = col_ck = col_tb = -1
                for cc in range(col_count):
                    h_txt = str(df.iat[header_row, cc]).lower()
                    if hoc_ky == "CaNam":
                        if "cả năm" in h_txt: col_tb = cc
                    else:
                        if "tx" in h_txt: col_tx = cc
                        elif "gk" in h_txt: col_gk = cc
                        elif "ck" in h_txt: col_ck = cc
                        elif h_txt == "tb" or "tbm" in h_txt: col_tb = cc
                
                # --- ĐỌC ĐIỂM ---
                curr = header_row + 1
                last_score_row = curr 
                
                for _ in range(20): # Tối đa 20 môn
                    if curr >= row_count: break
                    mon = str(df.iat[curr, col_mon]).strip()
                    
                    # Điều kiện dừng
                    if not mon or mon.lower() in ['nan', ''] or "kết quả" in mon.lower() or "xếp loại" in mon.lower():
                        last_score_row = curr
                        break
                    if mon.isdigit(): continue 

                    # Lấy giá trị điểm
                    v_tx = clean_str(df.iat[curr, col_tx]) if col_tx != -1 else None
                    v_gk = clean_str(df.iat[curr, col_gk]) if col_gk != -1 else None
                    v_ck = clean_str(df.iat[curr, col_ck]) if col_ck != -1 else None
                    v_tb = clean_str(df.iat[curr, col_tb]) if col_tb != -1 else None
                    
                    # Lưu vào DB (Upsert)
                    score = session.query(Score).filter_by(
                        student_id=user.id, mon_hoc=mon, nam_hoc=nam_hoc, hoc_ky=hoc_ky
                    ).first()
                    
                    if not score:
                        score = Score(student_id=user.id, mon_hoc=mon, nam_hoc=nam_hoc, hoc_ky=hoc_ky, khoi=khoi)
                        session.add(score)
                    
                    score.ddg_tx = v_tx
                    score.ddg_gk = v_gk
                    score.ddg_ck = v_ck
                    score.dtb_mon = v_tb
                    
                    curr += 1
                    last_score_row = curr

                # --- TÌM ĐÁNH GIÁ (CHỈ FILE CẢ NĂM) ---
                if hoc_ky == "CaNam":
                    kq_ht = kq_rl = danh_hieu = nhan_xet = None
                    # Quét 15 dòng dưới bảng điểm
                    for k in range(15):
                        check_r = last_score_row + k
                        if check_r >= row_count: break
                        
                        # Gom text dòng lại
                        row_vals = [str(df.iat[check_r, cx]) for cx in range(col_count) if pd.notna(df.iat[check_r, cx])]
                        row_text = " | ".join(row_vals)
                        
                        # Parse KQHT, KQRL, Danh hiệu
                        if "KQHT" in row_text or "Học lực" in row_text:
                            parts = row_text.split('|')
                            for p in parts:
                                if "KQHT" in p or "Học lực" in p:
                                    kq_ht = p.split(':')[-1].strip()
                                if "KQRL" in p or "Hạnh kiểm" in p:
                                    kq_rl = p.split(':')[-1].strip()
                                if "Danh hiệu" in p:
                                    danh_hieu = p.split(':')[-1].strip()
                        
                        if "Nhận xét" in row_text:
                             nhan_xet = row_text.split(':')[-1].strip()

                    # Lưu Assessment
                    if kq_ht or kq_rl or danh_hieu:
                        ass = session.query(Assessment).filter_by(student_id=user.id, nam_hoc=nam_hoc).first()
                        if not ass:
                            ass = Assessment(student_id=user.id, nam_hoc=nam_hoc)
                            session.add(ass)
                        
                        ass.kq_hoc_tap = kq_ht
                        ass.kq_ren_luyen = kq_rl
                        ass.danh_hieu = danh_hieu
                        ass.nhan_xet = nhan_xet

    session.commit()
    progress.empty()
    return f"Đã xử lý {students_updated} học sinh. Lớp: {10 + (int(nam_hoc.split('-')[0]) - int(user.nien_khoa.split('-')[0])) if students_updated > 0 else 'Unk'} ({nam_hoc})", "success"

# ==========================================
# 3. GIAO DIỆN HỌC SINH (MOBILE RESPONSIVE)
# ==========================================

def render_html_grade_table(scores, loai_ky):
    """Tạo bảng HTML Sticky Column chuẩn hiển thị Mobile"""
    if loai_ky == "CaNam":
        headers = ["Môn học", "TB Cả Năm"]
    else:
        headers = ["Môn học", "ĐĐGtx (TX)", "ĐĐGgk (GK)", "ĐĐGck (CK)", "TB Môn"]

    # CSS Sticky Column
    table_style = """
    <style>
        .grade-container { overflow-x: auto; margin-bottom: 15px; border: 1px solid #ddd; border-radius: 8px; }
        table.vnedu-table { width: 100%; border-collapse: collapse; font-family: sans-serif; font-size: 14px; min-width: 500px; }
        .vnedu-table th, .vnedu-table td { padding: 10px; border: 1px solid #ddd; text-align: center; white-space: nowrap; }
        .vnedu-table th { background: #f8f9fa; color: #333; font-weight: bold; }
        /* Sticky Column Môn Học */
        .vnedu-table th:first-child, .vnedu-table td:first-child {
            position: sticky; left: 0; background: #fff; z-index: 10;
            text-align: left; border-right: 2px solid #ccc; font-weight: 500;
        }
        .vnedu-table th:first-child { background: #f8f9fa; z-index: 11; }
        /* Cột TB đậm màu */
        .vnedu-table td:last-child { color: #d32f2f; font-weight: bold; background: #fffde7; }
        /* Text wrap cho cột TX */
        .vnedu-table td:nth-child(2) { white-space: normal; min-width: 120px; }
    </style>
    """

    rows_html = ""
    for s in scores:
        if loai_ky == "CaNam":
            rows_html += f"<tr><td>{s.mon_hoc}</td><td>{s.dtb_mon or '-'}</td></tr>"
        else:
            rows_html += f"""
            <tr>
                <td>{s.mon_hoc}</td>
                <td>{s.ddg_tx or ''}</td>
                <td>{s.ddg_gk or ''}</td>
                <td>{s.ddg_ck or ''}</td>
                <td>{s.dtb_mon or ''}</td>
            </tr>
            """

    thead = "".join([f"<th>{h}</th>" for h in headers])
    return f"{table_style}<div class='grade-container'><table class='vnedu-table'><thead><tr>{thead}</tr></thead><tbody>{rows_html}</tbody></table></div>"

def student_ui(user):
    st.markdown(f"### 👋 Xin chào, {user.ho_ten}")
    
    # Header Info
    c1, c2, c3 = st.columns([1.5, 1.5, 1])
    c1.info(f"🆔 Mã HS: **{user.ma_hs}**")
    c2.info(f"📅 Niên khóa: **{user.nien_khoa}**")
    
    status_text = "Vô hạn" if user.login_status == "full" else f"Còn {user.login_status} lần"
    c3.warning(f"🔑 Login: **{status_text}**")

    if st.button("Đăng xuất", key="logout"):
        st.session_state.logged_in = False
        st.rerun()
    
    st.divider()

    # Tính toán năm học
    try:
        start_year = int(user.nien_khoa.split('-')[0])
        years_map = {
            10: f"{start_year}-{start_year+1}",
            11: f"{start_year+1}-{start_year+2}",
            12: f"{start_year+2}-{start_year+3}"
        }
    except:
        st.error("Lỗi dữ liệu niên khóa. Liên hệ Admin.")
        return

    # TABS 3 NĂM
    t10, t11, t12 = st.tabs([f"Lớp 10", f"Lớp 11", f"Lớp 12"])
    
    for grade, tab in zip([10, 11, 12], [t10, t11, t12]):
        with tab:
            target_nam = years_map[grade]
            st.caption(f"Năm học: {target_nam}")
            
            # Get Data
            hk1 = session.query(Score).filter_by(student_id=user.id, nam_hoc=target_nam, hoc_ky="HK1").all()
            hk2 = session.query(Score).filter_by(student_id=user.id, nam_hoc=target_nam, hoc_ky="HK2").all()
            cn = session.query(Score).filter_by(student_id=user.id, nam_hoc=target_nam, hoc_ky="CaNam").all()
            ass = session.query(Assessment).filter_by(student_id=user.id, nam_hoc=target_nam).first()

            if not (hk1 or hk2 or cn):
                st.info("📭 Chưa có dữ liệu.")
                continue
            
            # Render Tables
            if hk1:
                st.markdown("**🍂 Học kỳ 1**")
                st.markdown(render_html_grade_table(hk1, "HK1"), unsafe_allow_html=True)
            if hk2:
                st.markdown("**🌸 Học kỳ 2**")
                st.markdown(render_html_grade_table(hk2, "HK2"), unsafe_allow_html=True)
            if cn:
                st.markdown("**🏆 Cả năm**")
                st.markdown(render_html_grade_table(cn, "CaNam"), unsafe_allow_html=True)
            
            # Assessment Box
            if ass:
                st.markdown(f"""
                <div style="background:#e3f2fd; padding:15px; border-radius:8px; border-left:5px solid #2196f3; margin-top:10px;">
                    <h4 style="margin:0; color:#0d47a1">📝 Đánh giá cuối năm</h4>
                    <p style="margin:5px 0"><b>Học lực:</b> {ass.kq_hoc_tap or '--'} &nbsp;|&nbsp; <b>Hạnh kiểm:</b> {ass.kq_ren_luyen or '--'}</p>
                    <p style="margin:5px 0"><b>Danh hiệu:</b> <span style="color:red; font-weight:bold">{ass.danh_hieu or '--'}</span></p>
                    <p style="margin:5px 0; font-style:italic">"{ass.nhan_xet or ''}"</p>
                </div>
                """, unsafe_allow_html=True)

# ==========================================
# 4. GIAO DIỆN ADMIN (QUẢN TRỊ)
# ==========================================
def admin_ui():
    st.title("⚙️ Trang Quản Trị")
    if st.button("Đăng xuất"):
        st.session_state.logged_in = False
        st.rerun()

    tab1, tab2 = st.tabs(["📤 Upload Dữ Liệu", "👥 Quản Lý User"])

    with tab1:
        st.subheader("1. Danh sách Học sinh")
        st.caption("Excel cần cột: CCCD, Ma_HS, Ho_Ten, Nien_Khoa (VD: 2023-2026), Trang_Thai ('full' hoặc số)")
        
        f_acc = st.file_uploader("Chọn file User", key="acc")
        if f_acc and st.button("Import User"):
            try:
                df = pd.read_excel(f_acc)
                # Map cột mềm dẻo
                df.columns = [str(c).strip().lower() for c in df.columns]
                col_map = {}
                for c in df.columns:
                    if "cccd" in c: col_map['cccd'] = c
                    if "mã" in c or "ma_hs" in c: col_map['ma'] = c
                    if "tên" in c: col_map['ten'] = c
                    if "niên" in c or "khoa" in c: col_map['khoa'] = c
                    if "trạng" in c or "status" in c: col_map['stt'] = c
                
                cnt = 0
                for _, row in df.iterrows():
                    cccd = str(row[col_map.get('cccd', 'so_cccd')]).strip().replace('.0','')
                    ma = str(row[col_map.get('ma', 'ma_hs')]).strip().replace('.0','')
                    ten = row[col_map.get('ten', 'ho_ten')]
                    khoa = str(row[col_map.get('khoa', 'nien_khoa')]).strip()
                    stt = str(row[col_map.get('stt', 'full')]).strip() if 'stt' in col_map else 'full'
                    if stt == 'nan': stt = 'full'
                    
                    u = session.query(User).filter_by(so_cccd=cccd).first()
                    if not u:
                        u = User(so_cccd=cccd, ma_hs=ma, ho_ten=ten, nien_khoa=khoa, login_status=stt)
                        u.set_password('123456')
                        session.add(u)
                        cnt += 1
                    else:
                        u.ma_hs = ma; u.nien_khoa = khoa; u.login_status = stt
                session.commit()
                st.success(f"Đã import {cnt} user mới!")
            except Exception as e: st.error(f"Lỗi: {e}")

        st.divider()
        st.subheader("2. Upload Điểm (Auto-Detect)")
        st.caption("Kéo thả file HK1, HK2, Cả năm. Hệ thống tự đọc Năm học & Học kỳ.")
        
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
        users = session.query(User).filter(User.is_admin == False).all()
        if users:
            data = [{"CCCD": u.so_cccd, "Tên": u.ho_ten, "Khóa": u.nien_khoa, "Lượt": u.login_status} for u in users]
            st.dataframe(pd.DataFrame(data), use_container_width=True)
            if st.button("Reset Login = Full"):
                for u in users: u.login_status = "full"
                session.commit()
                st.success("Xong!"); st.rerun()

# ==========================================
# 5. MAIN APP
# ==========================================
def main():
    st.set_page_config(page_title="EduScore Pro", page_icon="🎓", layout="wide")
    
    if 'logged_in' not in st.session_state: st.session_state.logged_in = False
    if 'user_id' not in st.session_state: st.session_state.user_id = None
    if 'is_admin' not in st.session_state: st.session_state.is_admin = False

    if not st.session_state.logged_in:
        c1, c2, c3 = st.columns([1,1.5,1])
        with c2:
            st.title("🎓 Tra Cứu Điểm THPT")
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
                                if c > 0: 
                                    allow = True; user.login_status = str(c-1); session.commit()
                                else: st.error("Hết lượt truy cập!")
                            except: st.error("Lỗi tài khoản")
                        
                        if allow:
                            st.session_state.logged_in = True
                            st.session_state.user_id = user.id
                            st.session_state.is_admin = user.is_admin
                            st.rerun()
                    else: st.error("Sai thông tin!")
    else:
        if st.session_state.is_admin: admin_ui()
        else: student_ui(session.query(User).get(st.session_state.user_id))

if __name__ == "__main__":
    main()
