import streamlit as st
import pandas as pd
import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from werkzeug.security import generate_password_hash, check_password_hash

# --- 1. CẤU HÌNH DATABASE ---
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
    is_active_account = Column(Boolean, default=False)
    khoi_lop = Column(Integer, default=10)
    lop_hoc = Column(String(20), nullable=True)
    nam_hoc = Column(String(20))
    scores = relationship('Score', backref='student', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Score(Base):
    __tablename__ = 'score'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    mon_hoc = Column(String(50), nullable=False)
    ddg_tx = Column(String(100), nullable=True)  
    ddg_gk = Column(String(50), nullable=True)
    ddg_ck = Column(String(50), nullable=True)
    dtb_mon = Column(String(50), nullable=True)
    
    hoc_ky = Column(String(20), nullable=False)
    khoi = Column(Integer, nullable=False)
    nam_hoc = Column(String(20))

Base.metadata.create_all(engine)

# Tạo Admin
try:
    if not session.query(User).filter_by(so_cccd='admin').first():
        admin = User(so_cccd='admin', ho_ten='Quản Trị Viên', is_admin=True, is_active_account=True)
        admin.set_password('admin123')
        session.add(admin)
        session.commit()
except Exception: session.rollback()

# --- 2. HÀM XỬ LÝ (CÓ DEBUG CHI TIẾT) ---
def clean_val(val):
    if pd.isna(val) or str(val).strip() == '': return None
    # Xử lý trường hợp số float như 9.6 bị thành 9.60000001
    s = str(val).strip()
    if s.endswith('.0'): s = s[:-2]
    return s

def process_vnedu_upload(df, khoi, hoc_ky_selected, nam_hoc):
    row_count, col_count = df.shape
    students_found = 0
    scores_added = 0
    
    # Khu vực hiển thị log debug cho người dùng thấy
    debug_container = st.expander(f"🔍 Xem chi tiết quá trình xử lý file (Click để mở)", expanded=True)
    
    with debug_container:
        st.write(f"Đang xử lý file... Kích thước: {row_count} dòng, {col_count} cột.")
        st.write(f"Thông tin áp dụng: Khối {khoi} | {hoc_ky_selected} | Năm {nam_hoc}")

    progress_bar = st.progress(0)
    
    for r in range(row_count):
        if r % 50 == 0: progress_bar.progress(min(r / row_count, 1.0))
        
        for c in range(col_count):
            val = str(df.iat[r, c]).strip()
            
            # TÌM MÃ HS
            if "Mã HS" in val:
                ma_hs = ""
                if ":" in val and len(val.split(':')[-1].strip()) > 3:
                    ma_hs = val.split(':')[-1].strip()
                else:
                    for offset in range(1, 5): 
                        if c + offset < col_count:
                            candidate = str(df.iat[r, c + offset]).strip()
                            if len(candidate) > 4 and candidate[0].isdigit(): 
                                ma_hs = candidate
                                break
                
                if not ma_hs: continue
                if ma_hs.endswith('.0'): ma_hs = ma_hs[:-2]

                student = session.query(User).filter_by(ma_hs=ma_hs).first()
                if not student:
                    # Debug: Báo nếu không tìm thấy User
                    # with debug_container: st.warning(f"⚠️ Bỏ qua Mã HS {ma_hs} (Chưa tạo tài khoản)")
                    continue
                
                students_found += 1
                
                # TÌM HEADER
                header_row_idx = -1
                col_mon_idx = -1
                
                # Quét 5 dòng dưới Mã HS để tìm chữ "Môn học"
                for k in range(1, 6):
                    if r + k >= row_count: break
                    for check_c in range(col_count):
                         cell_val = str(df.iat[r + k, check_c]).strip().lower()
                         if "môn" in cell_val and "học" in cell_val:
                             header_row_idx = r + k
                             col_mon_idx = check_c
                             break
                    if header_row_idx != -1: break
                
                if header_row_idx == -1: 
                    with debug_container: st.error(f"❌ Mã HS {ma_hs}: Không tìm thấy dòng tiêu đề 'Môn học' ở dưới.")
                    continue
                
                # MAP CỘT
                col_tx = -1
                col_gk = -1
                col_ck = -1
                col_tb = -1
                
                for check_c in range(col_count):
                    header_txt = str(df.iat[header_row_idx, check_c]).strip().lower()
                    if hoc_ky_selected in ['HK1', 'HK2']:
                        if "đđgtx" in header_txt: col_tx = check_c
                        elif "đđggk" in header_txt: col_gk = check_c
                        elif "đđgck" in header_txt: col_ck = check_c
                        elif header_txt == "tb" or "tbm" in header_txt: col_tb = check_c
                    else: # CaNam
                        if "cả năm" in header_txt: col_tb = check_c 

                # Debug: In ra nếu là học sinh đầu tiên tìm thấy để kiểm tra cột
                if students_found == 1:
                    with debug_container:
                        st.info(f"✅ Đã tìm thấy HS đầu tiên: {ma_hs}. Header dòng {header_row_idx}.")
                        st.write(f"Mapping cột: TX={col_tx}, GK={col_gk}, CK={col_ck}, TB={col_tb}")

                # LẤY ĐIỂM
                start_data_row = header_row_idx + 1
                for i in range(20): 
                    curr = start_data_row + i
                    if curr >= row_count: break
                    
                    mon_hoc = str(df.iat[curr, col_mon_idx]).strip()
                    if not mon_hoc or mon_hoc.lower() in ['nan', ''] or "kết quả" in mon_hoc.lower(): break
                    if mon_hoc.isdigit(): continue
                    
                    val_tx = clean_val(df.iat[curr, col_tx]) if col_tx != -1 else None
                    val_gk = clean_val(df.iat[curr, col_gk]) if col_gk != -1 else None
                    val_ck = clean_val(df.iat[curr, col_ck]) if col_ck != -1 else None
                    val_tb = clean_val(df.iat[curr, col_tb]) if col_tb != -1 else None
                    
                    # Debug: In ra điểm Toán của HS đầu tiên để check
                    if students_found == 1 and "Toán" in mon_hoc:
                         with debug_container:
                             st.write(f"👉 Thử đọc điểm {mon_hoc}: TX=[{val_tx}] | GK=[{val_gk}] | CK=[{val_ck}]")

                    # LƯU DB
                    score = session.query(Score).filter_by(
                        student_id=student.id, mon_hoc=mon_hoc, khoi=khoi, hoc_ky=hoc_ky_selected, nam_hoc=nam_hoc
                    ).first()
                    
                    if not score:
                        score = Score(student_id=student.id, mon_hoc=mon_hoc, khoi=khoi, hoc_ky=hoc_ky_selected, nam_hoc=nam_hoc)
                        session.add(score)
                    
                    score.ddg_tx = val_tx
                    score.ddg_gk = val_gk
                    score.ddg_ck = val_ck
                    score.dtb_mon = val_tb
                    scores_added += 1

    session.commit()
    progress_bar.empty()
    
    if students_found == 0:
        return "⚠️ Không tìm thấy Mã HS nào khớp với Tài khoản.", "warning"
    return f"✅ Đã xử lý {students_found} HS. Cập nhật thành công {scores_added} dòng điểm.", "success"

# --- 3. GIAO DIỆN HỌC SINH ---
def student_interface(user):
    st.markdown(f"### 👋 Xin chào, **{user.ho_ten}**")
    st.caption(f"Mã HS: {user.ma_hs} | Niên khóa dữ liệu: {user.nam_hoc}")
    
    if st.button("Đăng xuất"):
        st.session_state.logged_in = False
        st.rerun()

    # Bộ lọc
    avail_years = session.query(Score.nam_hoc).filter_by(student_id=user.id).distinct().all()
    list_years = [y[0] for y in avail_years if y[0]]
    list_years.sort(reverse=True)
    
    if not list_years:
        st.info("📭 Chưa có dữ liệu điểm.")
        return

    c1, c2 = st.columns(2)
    with c1: s_year = st.selectbox("Năm học", list_years)
    
    # Lấy học kỳ có dữ liệu của năm đó
    avail_sems = session.query(Score.hoc_ky).filter_by(student_id=user.id, nam_hoc=s_year).distinct().all()
    raw_sems = [s[0] for s in avail_sems if s[0]]
    
    # Map tên hiển thị
    map_sem = {'HK1': 'Học kỳ 1', 'HK2': 'Học kỳ 2', 'CaNam': 'Cả Năm'}
    display_sems = [map_sem.get(k, k) for k in raw_sems]
    
    with c2: s_sem_display = st.selectbox("Học kỳ", display_sems)
    
    # Dịch ngược lại để query DB
    rev_map = {v: k for k, v in map_sem.items()}
    s_sem_raw = rev_map.get(s_sem_display, s_sem_display)

    # Query
    scores = session.query(Score).filter_by(student_id=user.id, nam_hoc=s_year, hoc_ky=s_sem_raw).all()
    
    if scores:
        data = []
        for s in scores:
            item = {"Môn": s.mon_hoc}
            if s_sem_raw in ['HK1', 'HK2']:
                item["TX"] = s.ddg_tx
                item["GK"] = s.ddg_gk
                item["CK"] = s.ddg_ck
                item["TB Môn"] = s.dtb_mon
            else:
                item["TB Cả Năm"] = s.dtb_mon
            data.append(item)
        st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
    else:
        st.warning("Không có dữ liệu.")

# --- 4. GIAO DIỆN ADMIN ---
def admin_interface():
    st.title("👨‍🏫 Quản Trị Hệ Thống")
    if st.button("Đăng xuất"):
        st.session_state.logged_in = False
        st.rerun()

    tab1, tab2 = st.tabs(["📤 Upload Dữ Liệu", "🔧 Công Cụ"])

    with tab1:
        st.subheader("1. Danh sách Học sinh")
        f_acc = st.file_uploader("File Account", key="u_acc")
        if f_acc and st.button("Xử lý Account"):
            try:
                df = pd.read_excel(f_acc)
                df.columns = [str(c).strip() for c in df.columns]
                cols = {c.lower(): c for c in df.columns}
                if 'so_cccd' not in cols or 'ma_hs' not in cols:
                    st.error("Thiếu cột So_CCCD hoặc Ma_HS")
                else:
                    c = 0
                    for _, row in df.iterrows():
                        cccd = str(row[cols['so_cccd']]).strip().replace('.0', '')
                        ma = str(row[cols['ma_hs']]).strip().replace('.0', '')
                        name = row.get(cols.get('ho_ten', 'Ho_Ten'), 'HS')
                        if not session.query(User).filter_by(so_cccd=cccd).first():
                            session.add(User(so_cccd=cccd, ma_hs=ma, ho_ten=name, is_active_account=True, password_hash=generate_password_hash('123456')))
                            c+=1
                    session.commit()
                    st.success(f"Thêm {c} user.")
            except Exception as e: st.error(str(e))
        
        st.divider()
        st.subheader("2. Upload Điểm")
        c1, c2, c3 = st.columns(3)
        with c1: khoi = st.selectbox("Khối", [10, 11, 12])
        with c2: ky = st.selectbox("Loại điểm", ["HK1", "HK2", "CaNam"]) 
        with c3: nam = st.text_input("Năm học", "2025-2026")

        f_scr = st.file_uploader("File Điểm", accept_multiple_files=True, key="u_scr")
        if f_scr and st.button("Lưu Điểm"):
            for f in f_scr:
                try:
                    eng = 'xlrd' if f.name.endswith('.xls') else 'openpyxl'
                    df = pd.read_excel(f, header=None, engine=eng)
                    msg, stt = process_vnedu_upload(df, khoi, ky, nam)
                    if stt == 'success': st.success(f"{f.name}: {msg}")
                    else: st.warning(f"{f.name}: {msg}")
                except Exception as e: st.error(f"{f.name}: {e}")

    with tab2:
        if st.button("🗑️ Reset All Data"):
            session.query(Score).delete()
            session.query(User).filter(User.is_admin == False).delete()
            session.commit()
            st.success("Đã xóa sạch!")
            st.rerun()

# --- MAIN ---
st.set_page_config(page_title="EduScore")
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_id' not in st.session_state: st.session_state.user_id = None
if 'is_admin' not in st.session_state: st.session_state.is_admin = False

if not st.session_state.logged_in:
    st.title("Đăng Nhập")
    u = st.text_input("User")
    p = st.text_input("Pass", type="password")
    if st.button("Login"):
        user = session.query(User).filter_by(so_cccd=u).first()
        if user and user.check_password(p):
            st.session_state.logged_in = True
            st.session_state.user_id = user.id
            st.session_state.is_admin = user.is_admin
            st.rerun()
        else: st.error("Sai thông tin")
else:
    if st.session_state.is_admin: admin_interface()
    else: student_interface(session.query(User).get(st.session_state.user_id))
