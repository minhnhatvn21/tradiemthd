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
    ddg_gk = Column(Float, nullable=True)
    ddg_ck = Column(Float, nullable=True)
    dtb_mon = Column(Float, nullable=True)
    hoc_ky = Column(String(10), nullable=False)
    khoi = Column(Integer, nullable=False)
    nam_hoc = Column(String(20))

# Tạo bảng
Base.metadata.create_all(engine)

# Tạo Admin mặc định nếu chưa có
try:
    if not session.query(User).filter_by(so_cccd='admin').first():
        admin = User(so_cccd='admin', ho_ten='Quản Trị Viên', is_admin=True, is_active_account=True)
        admin.set_password('admin123')
        session.add(admin)
        session.commit()
except Exception:
    session.rollback()

# --- 2. HÀM XỬ LÝ DỮ LIỆU ---
def clean_float(val):
    try:
        if pd.isna(val) or str(val).strip() == '': return None
        return float(val)
    except: return None

def clean_str(val):
    if pd.isna(val) or str(val).strip() == '': return ""
    return str(val).strip()

def process_vnedu_upload(df, khoi, hoc_ky, nam_hoc):
    row_count, col_count = df.shape
    students_found = 0
    scores_added = 0
    
    progress_bar = st.progress(0)
    
    # Duyệt qua từng dòng để tìm học sinh
    for r in range(row_count):
        if r % 50 == 0: progress_bar.progress(min(r / row_count, 1.0))
        
        for c in range(col_count):
            val = str(df.iat[r, c]).strip()
            
            # TÌM NEO: "Mã HS"
            if "Mã HS" in val:
                ma_hs = ""
                # TH1: "Mã HS : 123" nằm chung 1 ô
                if ":" in val and len(val.split(':')[-1].strip()) > 3:
                    ma_hs = val.split(':')[-1].strip()
                # TH2: Mã số nằm ở các ô bên phải (quét 4 ô tiếp theo)
                else:
                    for offset in range(1, 5): 
                        if c + offset < col_count:
                            candidate = str(df.iat[r, c + offset]).strip()
                            # Mã HS thường dài > 4 ký tự và là số
                            if len(candidate) > 4 and candidate[0].isdigit(): 
                                ma_hs = candidate
                                break
                
                if not ma_hs: continue
                if ma_hs.endswith('.0'): ma_hs = ma_hs[:-2]

                # Tìm User trong DB
                student = session.query(User).filter_by(ma_hs=ma_hs).first()
                if not student: continue
                
                students_found += 1
                
                # --- THUẬT TOÁN TỰ DÒ CỘT ĐIỂM (FIX LỖI) ---
                # Mặc định dòng tiêu đề môn học nằm dưới dòng Mã HS khoảng 3 dòng (Row 7 -> Row 10)
                header_row = r + 3 
                col_mon = c # Mặc định cột Môn trùng cột Mã HS (theo hình bạn gửi)
                
                # Quét nhẹ xung quanh để tìm chính xác cột "Môn học"
                if header_row < row_count:
                    for offset in [-1, 0, 1]: # Kiểm tra trái, phải, giữa
                        if 0 <= c + offset < col_count:
                            header_val = str(df.iat[header_row, c + offset]).strip().lower()
                            if "môn" in header_val:
                                col_mon = c + offset
                                break
                
                # Suy ra các cột điểm khác từ cột Môn
                col_tx = col_mon + 1
                col_gk = col_mon + 2
                col_ck = col_mon + 3
                col_tb = col_mon + 4
                
                # Bắt đầu lấy điểm (Dữ liệu bắt đầu ngay sau dòng header)
                start_row_data = header_row + 1
                
                for i in range(15): # Lấy tối đa 15 môn
                    curr_row = start_row_data + i
                    if curr_row >= row_count: break
                    
                    mon_hoc = str(df.iat[curr_row, col_mon]).strip()
                    
                    # Điều kiện dừng
                    if not mon_hoc or mon_hoc.lower() in ['nan', ''] or "kết quả" in mon_hoc.lower(): break
                    if mon_hoc.lower() == "môn học" or mon_hoc.isdigit(): continue
                    
                    # Lấy điểm
                    val_tx = clean_str(df.iat[curr_row, col_tx])
                    val_gk = clean_float(df.iat[curr_row, col_gk])
                    val_ck = clean_float(df.iat[curr_row, col_ck])
                    val_tb = clean_float(df.iat[curr_row, col_tb])
                    
                    # Lưu DB
                    score = session.query(Score).filter_by(
                        student_id=student.id, mon_hoc=mon_hoc, khoi=khoi, hoc_ky=hoc_ky
                    ).first()
                    
                    if not score:
                        score = Score(student_id=student.id, mon_hoc=mon_hoc, khoi=khoi, hoc_ky=hoc_ky, nam_hoc=nam_hoc)
                        session.add(score)
                    
                    score.ddg_tx = val_tx
                    score.ddg_gk = val_gk
                    score.ddg_ck = val_ck
                    score.dtb_mon = val_tb
                    scores_added += 1

    session.commit()
    progress_bar.empty()
    if students_found == 0:
        return f"⚠️ Không tìm thấy HS nào khớp Mã HS trong file. Hãy kiểm tra lại Tài khoản!", "warning"
    return f"✅ Đã cập nhật điểm cho {students_found} học sinh ({scores_added} đầu điểm).", "success"

# --- 3. GIAO DIỆN CHÍNH ---
def main():
    st.set_page_config(page_title="EduScore", page_icon="🎓", layout="wide")
    
    # Session State
    if 'logged_in' not in st.session_state: st.session_state.logged_in = False
    if 'user_id' not in st.session_state: st.session_state.user_id = None
    if 'is_admin' not in st.session_state: st.session_state.is_admin = False

    # --- MÀN HÌNH LOGIN ---
    if not st.session_state.logged_in:
        col1, col2, col3 = st.columns([1,2,1])
        with col2:
            st.title("🎓 Đăng Nhập Hệ Thống")
            with st.form("login"):
                cccd = st.text_input("Tên đăng nhập / CCCD")
                pwd = st.text_input("Mật khẩu", type="password")
                if st.form_submit_button("Đăng nhập", type="primary"):
                    try:
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
                            st.error("Sai thông tin đăng nhập!")
                    except Exception as e:
                        st.error(f"Lỗi kết nối CSDL: {e}. Vui lòng thử lại sau giây lát.")
        return

    # --- MÀN HÌNH ADMIN ---
    if st.session_state.is_admin:
        st.title("👨‍🏫 Trang Quản Trị")
        if st.button("Đăng xuất", type="secondary"):
            st.session_state.logged_in = False
            st.rerun()
            
        tab1, tab2, tab3 = st.tabs(["📤 UPLOADER", "✅ KÍCH HOẠT", "🗂️ DỮ LIỆU"])
        
        with tab1:
            st.subheader("1. Upload Danh Sách & Tạo Tài Khoản")
            f_acc = st.file_uploader("File DS Học sinh (xlsx)", key="u_acc")
            if f_acc and st.button("Xử lý Tài Khoản"):
                try:
                    df = pd.read_excel(f_acc)
                    df.columns = [str(c).strip() for c in df.columns]
                    cols = {c.lower(): c for c in df.columns}
                    if 'so_cccd' not in cols or 'ma_hs' not in cols:
                        st.error("File thiếu cột So_CCCD hoặc Ma_HS")
                    else:
                        c_ok = 0
                        for _, row in df.iterrows():
                            cccd = str(row[cols['so_cccd']]).strip().replace('.0', '')
                            ma_hs = str(row[cols['ma_hs']]).strip().replace('.0', '')
                            name = row.get(cols.get('ho_ten', 'Ho_Ten'), 'HS')
                            lop = str(row.get(cols.get('lop', 'Lop'), ''))
                            
                            if not session.query(User).filter_by(so_cccd=cccd).first():
                                u = User(so_cccd=cccd, ma_hs=ma_hs, ho_ten=name, lop_hoc=lop)
                                u.set_password('123456')
                                session.add(u)
                                c_ok += 1
                        session.commit()
                        st.success(f"Đã thêm {c_ok} tài khoản.")
                except Exception as e: st.error(f"Lỗi: {e}")

            st.divider()
            st.subheader("2. Upload Điểm vnEdu")
            c1, c2, c3 = st.columns(3)
            with c1: khoi = st.selectbox("Khối", [10, 11, 12])
            with c2: ky = st.selectbox("Kỳ", ["HK1", "HK2"])
            with c3: nam = st.text_input("Năm", "2025-2026")
            
            f_scores = st.file_uploader("File Điểm (Chọn nhiều file)", accept_multiple_files=True, key="u_scr")
            if f_scores and st.button("Xử lý Điểm"):
                for f in f_scores:
                    try:
                        # Đọc file (hỗ trợ cả xls và xlsx)
                        engine_read = 'xlrd' if f.name.endswith('.xls') else 'openpyxl'
                        df = pd.read_excel(f, header=None, engine=engine_read)
                        msg, status = process_vnedu_upload(df, khoi, ky, nam)
                        if status == "success": st.success(f"{f.name}: {msg}")
                        else: st.warning(f"{f.name}: {msg}")
                    except Exception as e: st.error(f"Lỗi file {f.name}: {e}")

        with tab2: # Tab Kích hoạt
            st.subheader("Kích hoạt tài khoản")
            filter_st = st.radio("Trạng thái:", ["Chưa kích hoạt", "Đã kích hoạt"], horizontal=True)
            is_active_filter = (filter_st == "Đã kích hoạt")
            
            users = session.query(User).filter(User.is_admin == False, User.is_active_account == is_active_filter).all()
            if users:
                data = [{"ID": u.id, "Kích hoạt": u.is_active_account, "Mã HS": u.ma_hs, "Tên": u.ho_ten, "Lớp": u.lop_hoc} for u in users]
                df_u = pd.DataFrame(data)
                edited = st.data_editor(df_u, key="editor", hide_index=True, column_config={"ID": None})
                
                if st.button("Lưu Thay Đổi"):
                    for _, row in edited.iterrows():
                        u = session.query(User).get(row["ID"])
                        u.is_active_account = row["Kích hoạt"]
                    session.commit()
                    st.success("Đã lưu!")
                    st.rerun()
            else: st.info("Không có dữ liệu.")

        with tab3: # Tab Dữ liệu
            if st.button("🗑️ Xóa toàn bộ dữ liệu (Reset)"):
                session.query(Score).delete()
                session.query(User).filter(User.is_admin == False).delete()
                session.commit()
                st.warning("Đã xóa sạch!")
                st.rerun()

    # --- MÀN HÌNH HỌC SINH ---
    else:
        u = session.query(User).get(st.session_state.user_id)
        st.info(f"Xin chào: {u.ho_ten} | Mã HS: {u.ma_hs}")
        if st.button("Đăng xuất"):
            st.session_state.logged_in = False
            st.rerun()
            
        # Đổi pass
        if u.check_password('123456'):
            st.warning("Vui lòng đổi mật khẩu mặc định!")
            new_p = st.text_input("Mật khẩu mới", type="password")
            if st.button("Đổi mật khẩu"):
                u.set_password(new_p)
                session.commit()
                st.success("Xong! Đăng nhập lại nhé.")
                st.session_state.logged_in = False
                st.rerun()
            return

        # Xem điểm
        tabs = st.tabs(["Lớp 10", "Lớp 11", "Lớp 12"])
        for i, t in enumerate(tabs, 10):
            with t:
                scores = session.query(Score).filter_by(student_id=u.id, khoi=i).all()
                if scores:
                    data = [{"Môn": s.mon_hoc, "Kỳ": s.hoc_ky, "TX": s.ddg_tx, "GK": s.ddg_gk, "CK": s.ddg_ck, "TB": s.dtb_mon} for s in scores]
                    st.dataframe(pd.DataFrame(data), use_container_width=True)
                else: st.caption("Chưa có điểm.")

if __name__ == "__main__":
    main()
