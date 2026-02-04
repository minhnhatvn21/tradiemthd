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
    # Lưu điểm thành chuỗi để giữ nguyên format (vd: "8.0 9.0")
    ddg_tx = Column(String(100), nullable=True)  
    ddg_gk = Column(String(50), nullable=True)
    ddg_ck = Column(String(50), nullable=True)
    dtb_mon = Column(String(50), nullable=True) # Điểm trung bình
    
    hoc_ky = Column(String(20), nullable=False) # HK1, HK2, CaNam
    khoi = Column(Integer, nullable=False)
    nam_hoc = Column(String(20))

Base.metadata.create_all(engine)

# Tạo Admin mặc định
try:
    if not session.query(User).filter_by(so_cccd='admin').first():
        admin = User(so_cccd='admin', ho_ten='Quản Trị Viên', is_admin=True, is_active_account=True)
        admin.set_password('admin123')
        session.add(admin)
        session.commit()
except Exception: session.rollback()

# --- 2. HÀM XỬ LÝ (LOGIC MỚI) ---
def clean_val(val):
    if pd.isna(val) or str(val).strip() == '': return None
    return str(val).strip()

def process_vnedu_upload(df, khoi, hoc_ky_selected, nam_hoc):
    """
    Xử lý file điểm thông minh:
    - Tự động tìm dòng header chứa tên các cột điểm.
    - Xử lý khác biệt giữa file HK1/HK2 và file Cả Năm (CN).
    """
    row_count, col_count = df.shape
    students_found = 0
    scores_added = 0
    
    progress_bar = st.progress(0)
    
    for r in range(row_count):
        if r % 50 == 0: progress_bar.progress(min(r / row_count, 1.0))
        
        for c in range(col_count):
            val = str(df.iat[r, c]).strip()
            
            # 1. Tìm "Mã HS"
            if "Mã HS" in val:
                ma_hs = ""
                # TH1: "Mã HS : 123" cùng 1 ô
                if ":" in val and len(val.split(':')[-1].strip()) > 3:
                    ma_hs = val.split(':')[-1].strip()
                # TH2: Mã số nằm ở các ô bên phải
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
                if not student: continue
                students_found += 1
                
                # 2. Tìm dòng tiêu đề (Header Row)
                # Quét xuống dưới dòng Mã HS tối đa 5 dòng để tìm chữ "Môn học"
                header_row_idx = -1
                col_mon_idx = -1
                
                for k in range(1, 6):
                    if r + k >= row_count: break
                    # Quét ngang dòng này xem có chữ "Môn" không
                    for check_c in range(col_count):
                         cell_val = str(df.iat[r + k, check_c]).strip().lower()
                         if "môn" in cell_val and "học" in cell_val:
                             header_row_idx = r + k
                             col_mon_idx = check_c
                             break
                    if header_row_idx != -1: break
                
                if header_row_idx == -1: continue # Không tìm thấy bảng điểm của HS này
                
                # 3. Map cột dựa trên Header tìm được
                # Tìm index các cột quan trọng trong dòng header
                col_tx = -1
                col_gk = -1
                col_ck = -1
                col_tb = -1
                
                # Quét dòng header để tìm vị trí cột
                for check_c in range(col_count):
                    header_txt = str(df.iat[header_row_idx, check_c]).strip().lower()
                    
                    if hoc_ky_selected in ['HK1', 'HK2']:
                        # Logic cho file Học kỳ
                        if "đđgtx" in header_txt: col_tx = check_c
                        elif "đđggk" in header_txt: col_gk = check_c
                        elif "đđgck" in header_txt: col_ck = check_c
                        elif header_txt == "tb" or "tbm" in header_txt: col_tb = check_c
                    else:
                        # Logic cho file Cả năm (CN)
                        if "cả năm" in header_txt: col_tb = check_c 
                        # File CN thường chỉ lấy cột TB Cả năm, bỏ qua các cột thành phần thi lại/kỳ 1/kỳ 2 nếu ko cần thiết
                
                # 4. Duyệt các dòng điểm (Dưới header)
                start_data_row = header_row_idx + 1
                for i in range(20): # Tối đa 20 môn
                    curr = start_data_row + i
                    if curr >= row_count: break
                    
                    mon_hoc = str(df.iat[curr, col_mon_idx]).strip()
                    if not mon_hoc or mon_hoc.lower() in ['nan', ''] or "kết quả" in mon_hoc.lower(): break
                    if mon_hoc.isdigit(): continue # Bỏ qua cột STT
                    
                    # Lấy giá trị
                    val_tx = clean_val(df.iat[curr, col_tx]) if col_tx != -1 else None
                    val_gk = clean_val(df.iat[curr, col_gk]) if col_gk != -1 else None
                    val_ck = clean_val(df.iat[curr, col_ck]) if col_ck != -1 else None
                    val_tb = clean_val(df.iat[curr, col_tb]) if col_tb != -1 else None
                    
                    # Nếu file Cả Năm, chỉ cần lưu TB Cả năm vào cột dtb_mon
                    
                    # Lưu DB
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
        return "⚠️ Không tìm thấy Mã HS nào. Kiểm tra xem file User đã upload chưa?", "warning"
    return f"✅ Xử lý xong {students_found} HS. Cập nhật {scores_added} dòng điểm.", "success"


# --- 3. GIAO DIỆN HỌC SINH (UPDATED) ---
def student_interface(user):
    st.markdown(f"### 👋 Xin chào, **{user.ho_ten}**")
    st.caption(f"Mã HS: {user.ma_hs} | Lớp: {user.lop_hoc if user.lop_hoc else '--'}")
    
    if st.button("Đăng xuất", key="logout_btn"):
        st.session_state.logged_in = False
        st.rerun()

    if user.check_password('123456'):
        st.warning("⚠️ Mật khẩu mặc định không an toàn.")
        with st.form("change_pass"):
            p1 = st.text_input("Mật khẩu mới", type="password")
            p2 = st.text_input("Xác nhận mật khẩu", type="password")
            if st.form_submit_button("Đổi mật khẩu"):
                if p1 == p2 and len(p1) >= 6:
                    user.set_password(p1)
                    session.commit()
                    st.success("Đổi mật khẩu thành công! Vui lòng đăng nhập lại.")
                    st.session_state.logged_in = False
                    st.rerun()
                else:
                    st.error("Mật khẩu không khớp hoặc quá ngắn.")
        return

    st.divider()

    # --- BỘ LỌC XEM ĐIỂM ---
    # 1. Lấy danh sách Năm học có dữ liệu của HS này
    avail_years = session.query(Score.nam_hoc).filter_by(student_id=user.id).distinct().all()
    list_years = [y[0] for y in avail_years if y[0]]
    
    if not list_years:
        st.info("📭 Hiện chưa có dữ liệu điểm nào.")
        return

    # Sắp xếp năm học mới nhất lên đầu
    list_years.sort(reverse=True)
    
    col_filter1, col_filter2 = st.columns(2)
    with col_filter1:
        selected_year = st.selectbox("📅 Chọn Năm Học", list_years)
    
    # 2. Lấy danh sách Học kỳ dựa trên Năm đã chọn
    avail_semesters = session.query(Score.hoc_ky).filter_by(student_id=user.id, nam_hoc=selected_year).distinct().all()
    # Map tên hiển thị cho đẹp
    map_sem = {'HK1': 'Học kỳ 1', 'HK2': 'Học kỳ 2', 'CaNam': 'Cả Năm'}
    reverse_map = {v: k for k, v in map_sem.items()}
    
    list_sems_raw = [s[0] for s in avail_semesters if s[0]]
    list_sems_display = [map_sem.get(s, s) for s in list_sems_raw]
    
    # Sắp xếp thứ tự hiển thị: HK1 -> HK2 -> Cả Năm
    order_sem = ['Học kỳ 1', 'Học kỳ 2', 'Cả Năm']
    list_sems_display.sort(key=lambda x: order_sem.index(x) if x in order_sem else 99)

    with col_filter2:
        selected_sem_display = st.selectbox("book: Chọn Học Kỳ", list_sems_display)
        selected_sem_raw = reverse_map.get(selected_sem_display, selected_sem_display)

    # --- HIỂN THỊ BẢNG ĐIỂM ---
    scores = session.query(Score).filter_by(
        student_id=user.id, 
        nam_hoc=selected_year, 
        hoc_ky=selected_sem_raw
    ).all()

    if scores:
        st.subheader(f"Bảng điểm {selected_sem_display} - Năm {selected_year}")
        
        # Chuẩn bị data hiển thị
        data_show = []
        for s in scores:
            item = {"Môn học": s.mon_hoc}
            if selected_sem_raw in ['HK1', 'HK2']:
                item["ĐG Thường xuyên"] = s.ddg_tx
                item["ĐG Giữa kỳ"] = s.ddg_gk
                item["ĐG Cuối kỳ"] = s.ddg_ck
                item["Trung bình Môn"] = s.dtb_mon
            else:
                # Cả năm chỉ hiện cột TB
                item["Trung bình Cả năm"] = s.dtb_mon
            data_show.append(item)
            
        st.dataframe(pd.DataFrame(data_show), use_container_width=True, hide_index=True)
    else:
        st.warning("Không tìm thấy dữ liệu.")


# --- 4. GIAO DIỆN ADMIN ---
def admin_interface():
    st.title("👨‍🏫 Quản Trị Hệ Thống")
    if st.button("Đăng xuất"):
        st.session_state.logged_in = False
        st.rerun()

    tab1, tab2, tab3 = st.tabs(["📤 Upload Dữ Liệu", "✅ Kích Hoạt Tài Khoản", "🗂️ Quản Lý Chung"])

    with tab1:
        st.subheader("1. Danh sách Học sinh (Excel)")
        f_acc = st.file_uploader("File Account (So_CCCD, Ma_HS, Ho_Ten...)", key="u_acc")
        if f_acc and st.button("Xử lý Account"):
            try:
                df = pd.read_excel(f_acc)
                df.columns = [str(c).strip() for c in df.columns]
                cols = {c.lower(): c for c in df.columns}
                if 'so_cccd' not in cols or 'ma_hs' not in cols:
                    st.error("File thiếu cột So_CCCD hoặc Ma_HS")
                else:
                    count = 0
                    for _, row in df.iterrows():
                        cccd = str(row[cols['so_cccd']]).strip().replace('.0', '')
                        ma_hs = str(row[cols['ma_hs']]).strip().replace('.0', '')
                        name = row.get(cols.get('ho_ten', 'Ho_Ten'), 'HS')
                        lop = str(row.get(cols.get('lop', 'Lop'), ''))
                        
                        u = session.query(User).filter_by(so_cccd=cccd).first()
                        if not u:
                            u = User(so_cccd=cccd, ma_hs=ma_hs, ho_ten=name, lop_hoc=lop)
                            u.set_password('123456')
                            session.add(u)
                            count += 1
                        else:
                            u.ma_hs = ma_hs
                            u.lop_hoc = lop
                    session.commit()
                    st.success(f"Đã cập nhật {count} tài khoản.")
            except Exception as e: st.error(f"Lỗi: {e}")
        
        st.divider()
        st.subheader("2. Bảng điểm vnEdu")
        c1, c2, c3 = st.columns(3)
        with c1: khoi = st.selectbox("Khối", [10, 11, 12])
        # Thêm lựa chọn Cả Năm
        with c2: ky = st.selectbox("Loại điểm", ["HK1", "HK2", "CaNam"]) 
        with c3: nam = st.text_input("Năm học", "2025-2026")

        f_scores = st.file_uploader("Upload file điểm (hỗ trợ nhiều file)", accept_multiple_files=True, key="u_scr")
        if f_scores and st.button("Lưu Điểm"):
            for f in f_scores:
                try:
                    engine_read = 'xlrd' if f.name.endswith('.xls') else 'openpyxl'
                    df = pd.read_excel(f, header=None, engine=engine_read)
                    msg, status = process_vnedu_upload(df, khoi, ky, nam)
                    if status == "success": st.success(f"{f.name}: {msg}")
                    else: st.warning(f"{f.name}: {msg}")
                except Exception as e: st.error(f"Lỗi file {f.name}: {e}")

    with tab2:
        st.subheader("Kích hoạt nhanh")
        users = session.query(User).filter(User.is_admin == False).all()
        if users:
            df_u = pd.DataFrame([{"ID": u.id, "Active": u.is_active_account, "Mã HS": u.ma_hs, "Tên": u.ho_ten, "Lớp": u.lop_hoc} for u in users])
            edited = st.data_editor(df_u, hide_index=True, column_config={"ID": None, "Active": st.column_config.CheckboxColumn(default=False)})
            if st.button("Lưu Trạng Thái"):
                for _, row in edited.iterrows():
                    u = session.query(User).get(row["ID"])
                    u.is_active_account = row["Active"]
                session.commit()
                st.success("Đã lưu!")
                st.rerun()
        else: st.info("Chưa có user nào.")

    with tab3:
        if st.button("🗑️ Reset Dữ Liệu"):
            session.query(Score).delete()
            session.query(User).filter(User.is_admin == False).delete()
            session.commit()
            st.warning("Database đã được làm sạch.")
            st.rerun()

# --- MAIN ---
st.set_page_config(page_title="EduScore", page_icon="🎓")

if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_id' not in st.session_state: st.session_state.user_id = None
if 'is_admin' not in st.session_state: st.session_state.is_admin = False

if not st.session_state.logged_in:
    # Login form
    _, c, _ = st.columns([1,2,1])
    with c:
        st.title("🎓 Đăng Nhập")
        cccd = st.text_input("Tên đăng nhập")
        pwd = st.text_input("Mật khẩu", type="password")
        if st.button("Đăng nhập", type="primary"):
            u = session.query(User).filter_by(so_cccd=cccd).first()
            if u and u.check_password(pwd):
                if not u.is_active_account and not u.is_admin:
                    st.error("Tài khoản chưa kích hoạt.")
                else:
                    st.session_state.logged_in = True
                    st.session_state.user_id = u.id
                    st.session_state.is_admin = u.is_admin
                    st.rerun()
            else:
                st.error("Sai thông tin.")
else:
    if st.session_state.is_admin:
        admin_interface()
    else:
        u = session.query(User).get(st.session_state.user_id)
        student_interface(u)
