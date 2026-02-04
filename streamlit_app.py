import streamlit as st
import pandas as pd
import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from werkzeug.security import generate_password_hash, check_password_hash

# --- 1. CẤU HÌNH DATABASE ---
Base = declarative_base()
# check_same_thread=False để tránh lỗi khi dùng Streamlit
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
    is_active_account = Column(Boolean, default=False) # Trạng thái kích hoạt
    khoi_lop = Column(Integer, default=10)
    lop_hoc = Column(String(20), nullable=True) # Ví dụ: 10A1
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
    ddg_gk = Column(Float, nullable=True)
    ddg_ck = Column(Float, nullable=True)
    dtb_mon = Column(Float, nullable=True)
    hoc_ky = Column(String(10), nullable=False)
    khoi = Column(Integer, nullable=False)
    nam_hoc = Column(String(20))

Base.metadata.create_all(engine)

# Tạo Admin mặc định
if not session.query(User).filter_by(so_cccd='admin').first():
    admin = User(so_cccd='admin', ho_ten='Quản Trị Viên', is_admin=True, is_active_account=True)
    admin.set_password('admin123')
    session.add(admin)
    session.commit()

# --- 2. HÀM XỬ LÝ EXCEL (Logic quét lưới thông minh) ---
def clean_float(val):
    try:
        if pd.isna(val) or str(val).strip() == '': return None
        return float(val)
    except: return None

def clean_str(val):
    if pd.isna(val) or str(val).strip() == '': return ""
    return str(val).strip()

def process_vnedu_upload(df, khoi, hoc_ky, nam_hoc):
    """
    Thuật toán quét lưới: Tìm từ khóa 'Mã HS' bất kể vị trí,
    tự động suy ra cột điểm dựa trên vị trí tìm thấy.
    """
    row_count, col_count = df.shape
    students_found = 0
    scores_added = 0
    
    # Thanh tiến trình
    progress_bar = st.progress(0)
    status_text = st.empty()

    for r in range(row_count):
        # Update progress
        if r % 50 == 0: progress_bar.progress(min(r / row_count, 1.0))

        for c in range(col_count):
            val = str(df.iat[r, c]).strip()
            
            # 1. TÌM NEO: "Mã HS"
            if "Mã HS" in val:
                ma_hs = ""
                # TH1: "Mã HS : 123" chung 1 ô
                if ":" in val and len(val.split(':')[-1].strip()) > 3:
                    ma_hs = val.split(':')[-1].strip()
                # TH2: Mã số nằm ở các ô bên phải (do merge cell)
                else:
                    for offset in range(1, 5): # Quét 4 ô bên phải
                        if c + offset < col_count:
                            candidate = str(df.iat[r, c + offset]).strip()
                            if len(candidate) > 4: # Mã HS thường dài
                                ma_hs = candidate
                                break
                
                # Làm sạch Mã HS
                if not ma_hs: continue
                if ma_hs.endswith('.0'): ma_hs = ma_hs[:-2]

                # 2. TÌM USER TRONG DB
                student = session.query(User).filter_by(ma_hs=ma_hs).first()
                if not student: 
                    # Nếu chưa có HS, có thể bỏ qua hoặc tạo mới tùy logic
                    continue
                
                students_found += 1
                
                # 3. XÁC ĐỊNH VỊ TRÍ ĐIỂM
                # Quy luật vnEdu: Dòng điểm bắt đầu sau dòng Mã HS khoảng 4 dòng
                start_row = r + 4 
                
                # Quy luật cột: Nếu tìm thấy Mã HS ở cột C -> Môn(B), TX(C), GK(D), CK(E), TB(F)
                # Tức là: Cột Môn = c - 1
                col_mon = c - 1
                col_tx, col_gk, col_ck, col_tb = c, c+1, c+2, c+3

                # Quét dọc xuống để lấy danh sách môn
                for i in range(15): # Tối đa 15 môn
                    curr_row = start_row + i
                    if curr_row >= row_count: break
                    
                    mon_hoc = str(df.iat[curr_row, col_mon]).strip()
                    
                    # Điều kiện dừng
                    if not mon_hoc or mon_hoc.lower() in ['nan', ''] or "kết quả" in mon_hoc.lower(): break
                    if mon_hoc.lower() == "môn học" or mon_hoc.isdigit(): continue
                    
                    # Lấy giá trị điểm
                    val_tx = clean_str(df.iat[curr_row, col_tx])
                    val_gk = clean_float(df.iat[curr_row, col_gk])
                    val_ck = clean_float(df.iat[curr_row, col_ck])
                    val_tb = clean_float(df.iat[curr_row, col_tb])
                    
                    # Lưu vào DB (Update hoặc Insert)
                    score = session.query(Score).filter_by(
                        student_id=student.id, mon_hoc=mon_hoc, khoi=khoi, hoc_ky=hoc_ky
                    ).first()
                    
                    if not score:
                        score = Score(student_id=student.id, mon_hoc=mon_hoc, khoi=khoi, hoc_ky=hoc_ky, nam_hoc=nam_hoc)
                        session.add(score)
                    
                    # Cập nhật giá trị
                    score.ddg_tx = val_tx
                    score.ddg_gk = val_gk
                    score.ddg_ck = val_ck
                    score.dtb_mon = val_tb
                    scores_added += 1

    session.commit()
    progress_bar.empty()
    return f"✅ Xử lý xong: Tìm thấy {students_found} học sinh, cập nhật {scores_added} đầu điểm."

# --- 3. GIAO DIỆN ADMIN ---
def admin_page():
    st.title("👨‍🏫 Trang Quản Trị")
    
    # Nút đăng xuất góc phải
    col_main, col_logout = st.columns([8, 2])
    with col_logout:
        if st.button("Đăng xuất", type="primary"):
            st.session_state.logged_in = False
            st.rerun()

    # TẠO TABS GIỐNG HÌNH YÊU CẦU
    tab1, tab2, tab3 = st.tabs(["📤 UPLOADER", "✅ KÍCH HOẠT", "🗂️ DỮ LIỆU"])

    # --- TAB 1: UPLOAD ---
    with tab1:
        st.subheader("1. Upload Danh Sách Học Sinh (Tạo tài khoản)")
        file_acc = st.file_uploader("Chọn file Excel danh sách lớp", type=['xls', 'xlsx'], key="u_acc")
        
        if file_acc:
            if st.button("Xử lý file Tài khoản"):
                try:
                    df = pd.read_excel(file_acc)
                    # Chuẩn hóa header
                    df.columns = [str(c).strip() for c in df.columns]
                    cols = {c.lower(): c for c in df.columns}
                    
                    if 'so_cccd' not in cols or 'ma_hs' not in cols:
                        st.error("❌ File thiếu cột So_CCCD hoặc Ma_HS")
                    else:
                        count = 0
                        for index, row in df.iterrows():
                            cccd = str(row[cols['so_cccd']]).strip()
                            if cccd.endswith('.0'): cccd = cccd[:-2]
                            ma_hs = str(row[cols['ma_hs']]).strip()
                            if ma_hs.endswith('.0'): ma_hs = ma_hs[:-2]
                            ho_ten = row.get(cols.get('ho_ten', 'Ho_Ten'), 'Hoc Sinh')
                            lop = str(row.get(cols.get('lop', 'Lop'), '')) # Lấy cột Lớp nếu có
                            
                            # Kiểm tra user tồn tại
                            u = session.query(User).filter_by(so_cccd=cccd).first()
                            if not u:
                                u = User(so_cccd=cccd, ma_hs=ma_hs, ho_ten=ho_ten, lop_hoc=lop, is_active_account=False) # Mặc định chưa kích hoạt
                                u.set_password('123456')
                                session.add(u)
                                count += 1
                            else:
                                # Update thông tin nếu cần
                                u.ma_hs = ma_hs
                                u.lop_hoc = lop
                        
                        session.commit()
                        st.success(f"Đã thêm/cập nhật {count} tài khoản.")
                except Exception as e:
                    st.error(f"Lỗi: {e}")

        st.divider()
        
        st.subheader("2. Upload Bảng Điểm (vnEdu)")
        c1, c2, c3 = st.columns(3)
        with c1: khoi_in = st.selectbox("Khối", [10, 11, 12])
        with c2: ky_in = st.selectbox("Học kỳ", ["HK1", "HK2", "Ca_Nam"])
        with c3: nam_in = st.text_input("Năm học", "2025-2026")
        
        # Cho phép upload nhiều file cùng lúc
        files_score = st.file_uploader("Chọn file Điểm (Hỗ trợ nhiều file)", type=['xls', 'xlsx'], accept_multiple_files=True, key="u_score")
        
        if files_score:
            if st.button("Xử lý File Điểm"):
                for f in files_score:
                    try:
                        # Tự động chọn engine đọc file
                        engine_read = 'xlrd' if f.name.endswith('.xls') else 'openpyxl'
                        df = pd.read_excel(f, header=None, engine=engine_read)
                        
                        msg = process_vnedu_upload(df, khoi_in, ky_in, nam_in)
                        st.write(f"📄 File `{f.name}`: {msg}")
                    except Exception as e:
                        st.error(f"❌ Lỗi file `{f.name}`: {e}")

    # --- TAB 2: KÍCH HOẠT ---
    with tab2:
        st.subheader("Quản lý trạng thái tài khoản")
        
        # Bộ lọc
        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            search_name = st.text_input("Tìm theo tên hoặc Mã HS")
        with filter_col2:
            filter_status = st.selectbox("Trạng thái", ["Tất cả", "Chưa kích hoạt", "Đã kích hoạt"])

        # Query dữ liệu
        query = session.query(User).filter(User.is_admin == False)
        if search_name:
            query = query.filter((User.ho_ten.contains(search_name)) | (User.ma_hs.contains(search_name)))
        
        users = query.all()
        
        if not users:
            st.info("Không tìm thấy học sinh nào.")
        else:
            # Chuẩn bị dữ liệu cho Data Editor
            data = []
            for u in users:
                # Lọc trạng thái bằng Python (đơn giản hơn)
                if filter_status == "Chưa kích hoạt" and u.is_active_account: continue
                if filter_status == "Đã kích hoạt" and not u.is_active_account: continue
                
                data.append({
                    "Kích hoạt": u.is_active_account,
                    "Mã HS": u.ma_hs,
                    "Họ Tên": u.ho_ten,
                    "Lớp": u.lop_hoc,
                    "ID": u.id # Cột ẩn để định danh
                })
            
            df_users = pd.DataFrame(data)
            
            if not df_users.empty:
                # Hiển thị bảng cho phép chỉnh sửa
                edited_df = st.data_editor(
                    df_users,
                    column_config={
                        "Kích hoạt": st.column_config.CheckboxColumn(
                            "Kích hoạt",
                            help="Tick chọn để cho phép HS đăng nhập",
                            default=False,
                        ),
                        "ID": None # Ẩn cột ID
                    },
                    disabled=["Mã HS", "Họ Tên", "Lớp"],
                    hide_index=True,
                    use_container_width=True,
                    height=400
                )
                
                # Nút Lưu
                if st.button("Lưu Thay Đổi", type="primary"):
                    count_change = 0
                    # Duyệt qua dữ liệu đã sửa để update DB
                    for index, row in edited_df.iterrows():
                        u_id = row['ID']
                        new_status = row['Kích hoạt']
                        
                        # Tìm user và update
                        u_db = session.query(User).get(int(u_id))
                        if u_db and u_db.is_active_account != new_status:
                            u_db.is_active_account = new_status
                            count_change += 1
                    
                    session.commit()
                    st.success(f"Đã cập nhật trạng thái cho {count_change} học sinh!")
                    st.rerun() # Load lại trang
            else:
                st.info("Không có dữ liệu phù hợp bộ lọc.")

    # --- TAB 3: DỮ LIỆU ---
    with tab3:
        st.subheader("Dữ liệu điểm chi tiết")
        scores = session.query(Score).limit(100).all() # Demo 100 dòng
        if scores:
            data_score = [{
                "HS ID": s.student_id,
                "Môn": s.mon_hoc,
                "TX": s.ddg_tx,
                "GK": s.ddg_gk,
                "CK": s.ddg_ck,
                "TB": s.dtb_mon,
                "Kỳ": s.hoc_ky,
                "Năm": s.nam_hoc
            } for s in scores]
            st.dataframe(pd.DataFrame(data_score), use_container_width=True)
        else:
            st.info("Chưa có dữ liệu điểm.")
            if st.button("Xóa toàn bộ dữ liệu (Nguy hiểm)"):
                session.query(Score).delete()
                session.query(User).filter(User.is_admin == False).delete()
                session.commit()
                st.warning("Đã xóa sạch database!")
                st.rerun()

# --- 4. GIAO DIỆN HỌC SINH ---
def student_page(user_id):
    user = session.query(User).get(user_id)
    
    # Header đẹp
    st.info(f"🎓 **{user.ho_ten}** | Mã HS: {user.ma_hs} | Lớp: {user.lop_hoc or '---'}")
    
    if st.button("Đăng xuất"):
        st.session_state.logged_in = False
        st.rerun()

    if user.check_password('123456'):
        st.warning("⚠️ Mật khẩu mặc định không an toàn. Vui lòng đổi mật khẩu!")
        with st.form("change_pass"):
            p1 = st.text_input("Mật khẩu mới", type="password")
            p2 = st.text_input("Nhập lại", type="password")
            if st.form_submit_button("Đổi mật khẩu"):
                if p1 == p2 and len(p1) >= 6:
                    user.set_password(p1)
                    session.commit()
                    st.success("Thành công! Mời đăng nhập lại.")
                    st.session_state.logged_in = False
                    st.rerun()
                else:
                    st.error("Mật khẩu không khớp hoặc quá ngắn.")
        return

    # Xem điểm
    st.write("### 📊 Kết quả học tập")
    tab10, tab11, tab12 = st.tabs(["Lớp 10", "Lớp 11", "Lớp 12"])
    
    def show_grade(khoi_val):
        scores = session.query(Score).filter_by(student_id=user.id, khoi=khoi_val).all()
        if not scores:
            st.caption("Chưa có dữ liệu.")
            return
        
        # Chia theo học kỳ
        hk1 = [s for s in scores if s.hoc_ky == 'HK1']
        hk2 = [s for s in scores if s.hoc_ky == 'HK2']
        
        col_hk1, col_hk2 = st.columns(2)
        
        with col_hk1:
            st.markdown("#### Học kỳ 1")
            if hk1:
                df1 = pd.DataFrame([{
                    "Môn": s.mon_hoc, "TX": s.ddg_tx, "GK": s.ddg_gk, "CK": s.ddg_ck, "TB": s.dtb_mon
                } for s in hk1])
                st.dataframe(df1, hide_index=True, use_container_width=True)
        
        with col_hk2:
            st.markdown("#### Học kỳ 2")
            if hk2:
                df2 = pd.DataFrame([{
                    "Môn": s.mon_hoc, "TX": s.ddg_tx, "GK": s.ddg_gk, "CK": s.ddg_ck, "TB": s.dtb_mon
                } for s in hk2])
                st.dataframe(df2, hide_index=True, use_container_width=True)

    with tab10: show_grade(10)
    with tab11: show_grade(11)
    with tab12: show_grade(12)

# --- 5. MAIN APP ---
st.set_page_config(page_title="EduScore", page_icon="🎓", layout="wide")

if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_id' not in st.session_state: st.session_state.user_id = None
if 'is_admin' not in st.session_state: st.session_state.is_admin = False

if not st.session_state.logged_in:
    # Màn hình đăng nhập
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.title("🎓 Đăng Nhập")
        with st.form("login"):
            cccd = st.text_input("Tên đăng nhập / CCCD")
            pwd = st.text_input("Mật khẩu", type="password")
            if st.form_submit_button("Vào hệ thống", type="primary"):
                u = session.query(User).filter_by(so_cccd=cccd).first()
                if u and u.check_password(pwd):
                    if not u.is_active_account and not u.is_admin:
                        st.error("Tài khoản chưa được kích hoạt!")
                    else:
                        st.session_state.logged_in = True
                        st.session_state.user_id = u.id
                        st.session_state.is_admin = u.is_admin
                        st.rerun()
                else:
                    st.error("Sai thông tin!")
else:
    if st.session_state.is_admin:
        admin_page()
    else:
        student_page(st.session_state.user_id)