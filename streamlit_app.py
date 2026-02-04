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
    
    # Niên khóa: VD "2023-2026" (Dùng để tính Lớp 10, 11, 12)
    nien_khoa = Column(String(20)) 
    
    # Trạng thái đăng nhập: "full" hoặc số lần còn lại (dạng string)
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
    # Lưu điểm dạng chuỗi để giữ format gốc
    ddg_tx = Column(String(100)) 
    ddg_gk = Column(String(50))
    ddg_ck = Column(String(50))
    dtb_mon = Column(String(50))
    
    hoc_ky = Column(String(20)) # HK1, HK2, CaNam
    nam_hoc = Column(String(20)) # VD: "2023-2024"
    khoi = Column(Integer) # 10, 11, 12 (Tự tính)

class Assessment(Base):
    """Bảng lưu đánh giá cuối năm (Hạnh kiểm, Học lực, Danh hiệu)"""
    __tablename__ = 'assessment'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('user.id'), nullable=False)
    nam_hoc = Column(String(20))
    kq_hoc_tap = Column(String(50)) # Tốt/Khá...
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
# 2. HÀM XỬ LÝ LOGIC (PARSER THÔNG MINH)
# ==========================================

def clean_str(val):
    if pd.isna(val) or str(val).strip() == '': return None
    s = str(val).strip()
    return s.replace('.0', '') if s.endswith('.0') and len(s) > 2 else s

def detect_file_info(df):
    """
    Đọc 10 dòng đầu của file Excel để tìm:
    1. Năm học (Regex: Năm học 2023 - 2024)
    2. Học kỳ (Học kỳ 1 / Học kỳ 2 / Nếu không thấy -> Cả năm)
    """
    content = df.head(10).to_string()
    
    # 1. Tìm năm học
    # Pattern: 20xx - 20xx hoặc 20xx-20xx
    year_match = re.search(r'(\d{4})\s*-\s*(\d{4})', content)
    nam_hoc = f"{year_match.group(1)}-{year_match.group(2)}" if year_match else None
    
    # 2. Tìm học kỳ
    if "Học kỳ 1" in content or "HỌC KỲ 1" in content:
        hoc_ky = "HK1"
    elif "Học kỳ 2" in content or "HỌC KỲ 2" in content:
        hoc_ky = "HK2"
    else:
        # Mặc định là Cả Năm nếu không tìm thấy chữ Học kỳ
        hoc_ky = "CaNam"
        
    return nam_hoc, hoc_ky

def calculate_grade(student_nien_khoa, file_nam_hoc):
    """
    Tính Khối (10, 11, 12) dựa trên Niên khóa HS và Năm học file.
    VD: HS niên khóa 2023-2026. File 2023-2024 -> Lớp 10.
    """
    try:
        start_student = int(student_nien_khoa.split('-')[0])
        start_file = int(file_nam_hoc.split('-')[0])
        delta = start_file - start_student
        
        if delta == 0: return 10
        elif delta == 1: return 11
        elif delta == 2: return 12
        else: return 0 # Không xác định hoặc ở lại lớp/vượt lớp
    except:
        return 0

def process_upload_auto(df):
    """
    Hàm xử lý đa năng: Tự động phát hiện mọi thứ
    """
    # 1. Phát hiện metadata từ header
    nam_hoc, hoc_ky = detect_file_info(df)
    if not nam_hoc:
        return "❌ Không tìm thấy thông tin 'Năm học' trong file (cần dòng chữ dạng 'Năm học 20xx - 20xx').", "error"

    row_count, col_count = df.shape
    students_updated = 0
    
    progress = st.progress(0)
    
    for r in range(row_count):
        if r % 50 == 0: progress.progress(min(r / row_count, 1.0))
        
        for c in range(col_count):
            val = str(df.iat[r, c]).strip()
            
            # --- TÌM HỌC SINH ---
            if "Mã HS" in val:
                ma_hs = ""
                # Logic lấy mã HS (chung ô hoặc lệch ô)
                if ":" in val and len(val.split(':')[-1].strip()) > 3:
                    ma_hs = val.split(':')[-1].strip()
                else:
                    for k in range(1, 5):
                        if c + k < col_count:
                            cand = str(df.iat[r, c + k]).strip()
                            if len(cand) > 4 and cand[0].isdigit():
                                ma_hs = cand; break
                
                if not ma_hs: continue
                ma_hs = ma_hs.replace('.0', '')
                
                # Check DB
                user = session.query(User).filter_by(ma_hs=ma_hs).first()
                if not user: continue # Bỏ qua nếu chưa tạo acc
                
                # Tự tính Khối
                khoi = calculate_grade(user.nien_khoa, nam_hoc)
                if khoi == 0: continue # Lỗi niên khóa
                
                students_updated += 1
                
                # --- TÌM BẢNG ĐIỂM (HEADER) ---
                header_row = -1
                col_mon = -1
                
                # Quét 6 dòng dưới Mã HS để tìm header
                for k in range(1, 7):
                    if r + k >= row_count: break
                    for check_c in range(col_count):
                        txt = str(df.iat[r+k, check_c]).lower()
                        if "môn" in txt and "học" in txt:
                            header_row = r + k
                            col_mon = check_c
                            break
                    if header_row != -1: break
                
                if header_row == -1: continue

                # --- XỬ LÝ ĐIỂM (SCORES) ---
                # Map cột
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
                
                # Đọc rows điểm
                curr = header_row + 1
                last_score_row = curr # Lưu vết để tìm đánh giá sau này
                
                for _ in range(20):
                    if curr >= row_count: break
                    mon = str(df.iat[curr, col_mon]).strip()
                    
                    # Điều kiện dừng đọc môn
                    if not mon or mon.lower() in ['nan', ''] or "kết quả" in mon.lower() or "xếp loại" in mon.lower():
                        last_score_row = curr
                        break
                    if mon.isdigit(): continue # Bỏ qua STT

                    # Lấy values
                    v_tx = clean_str(df.iat[curr, col_tx]) if col_tx != -1 else None
                    v_gk = clean_str(df.iat[curr, col_gk]) if col_gk != -1 else None
                    v_ck = clean_str(df.iat[curr, col_ck]) if col_ck != -1 else None
                    v_tb = clean_str(df.iat[curr, col_tb]) if col_tb != -1 else None
                    
                    # Upsert Score
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

                # --- XỬ LÝ ĐÁNH GIÁ (ASSESSMENT) - Chỉ file Cả Năm ---
                if hoc_ky == "CaNam":
                    # Quét tiếp từ dòng last_score_row xuống dưới để tìm KQHT, KQRL
                    kq_ht = kq_rl = danh_hieu = nhan_xet = None
                    
                    # Quét khoảng 10 dòng dưới bảng điểm
                    for k in range(10):
                        check_r = last_score_row + k
                        if check_r >= row_count: break
                        
                        # Gom text của cả dòng lại để search cho dễ
                        row_text = " | ".join([str(df.iat[check_r, cx]) for cx in range(col_count) if pd.notna(df.iat[check_r, cx])])
                        
                        # Tìm mẫu: KQHT: Tốt | KQRL: Tốt
                        if "KQHT" in row_text or "Học lực" in row_text or "Học tập" in row_text:
                            # Parse đơn giản
                            parts = row_text.split('|')
                            for p in parts:
                                if "KQHT" in p or "Học lực" in p or "Học tập" in p:
                                    kq_ht = p.split(':')[-1].strip()
                                if "KQRL" in p or "Hạnh kiểm" in p or "Rèn luyện" in p:
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
    return f"Đã xử lý {students_updated} học sinh. Năm: {nam_hoc} - {hoc_ky}", "success"


# ==========================================
# 3. GIAO DIỆN HỌC SINH (Student UI)
# ==========================================
def student_ui(user):
    # CSS tùy chỉnh cho đẹp
    st.markdown("""
    <style>
        .grade-card { background-color: #f0f2f6; padding: 20px; border-radius: 10px; margin-bottom: 20px; border-left: 5px solid #4CAF50; }
        .assessment-box { background-color: #e3f2fd; padding: 15px; border-radius: 8px; border: 1px solid #90caf9; }
        .metric-box { text-align: center; background: white; padding: 10px; border-radius: 5px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    </style>
    """, unsafe_allow_html=True)

    st.title(f"📚 Hồ Sơ Học Tập: {user.ho_ten}")
    
    # Header Info
    c1, c2, c3 = st.columns(3)
    c1.info(f"🆔 Mã HS: **{user.ma_hs}**")
    c2.info(f"📅 Niên khóa: **{user.nien_khoa}**")
    
    # Hiển thị số lượt đăng nhập còn lại
    status_text = "Không giới hạn" if user.login_status == "full" else f"Còn {user.login_status} lần"
    status_color = "green" if user.login_status == "full" or int(user.login_status) > 2 else "red"
    c3.markdown(f"<div style='background:#fff3cd; padding:15px; border-radius:5px; color:{status_color}; text-align:center; font-weight:bold'>🔑 Đăng nhập: {status_text}</div>", unsafe_allow_html=True)

    if st.button("Đăng xuất", type="primary"):
        st.session_state.logged_in = False
        st.rerun()
    
    st.divider()

    # TABS 3 NĂM HỌC
    # Tính toán năm học dựa trên niên khóa
    try:
        start_year = int(user.nien_khoa.split('-')[0])
        years_map = {
            10: f"{start_year}-{start_year+1}",
            11: f"{start_year+1}-{start_year+2}",
            12: f"{start_year+2}-{start_year+3}"
        }
    except:
        st.error("Lỗi dữ liệu niên khóa. Vui lòng liên hệ Admin.")
        return

    tab10, tab11, tab12 = st.tabs([f"Lớp 10 ({years_map[10]})", f"Lớp 11 ({years_map[11]})", f"Lớp 12 ({years_map[12]})"])

    for grade, tab in zip([10, 11, 12], [tab10, tab11, tab12]):
        with tab:
            target_nam_hoc = years_map[grade]
            
            # Lấy dữ liệu điểm
            scores_hk1 = session.query(Score).filter_by(student_id=user.id, nam_hoc=target_nam_hoc, hoc_ky="HK1").all()
            scores_hk2 = session.query(Score).filter_by(student_id=user.id, nam_hoc=target_nam_hoc, hoc_ky="HK2").all()
            scores_cn = session.query(Score).filter_by(student_id=user.id, nam_hoc=target_nam_hoc, hoc_ky="CaNam").all()
            assessment = session.query(Assessment).filter_by(student_id=user.id, nam_hoc=target_nam_hoc).first()

            if not (scores_hk1 or scores_hk2 or scores_cn):
                st.warning(f"Chưa có dữ liệu cho năm học {target_nam_hoc}")
                continue

            # --- PHẦN 1: BẢNG ĐIỂM CHI TIẾT ---
            col_hk1, col_hk2, col_cn = st.columns([1.2, 1.2, 0.8])
            
            with col_hk1:
                st.markdown("##### 🍂 Học kỳ 1")
                if scores_hk1:
                    df1 = pd.DataFrame([{"Môn": s.mon_hoc, "TB": s.dtb_mon, "Chi tiết": f"{s.ddg_tx or ''} | {s.ddg_gk or ''}"} for s in scores_hk1])
                    st.dataframe(df1, hide_index=True, use_container_width=True)
                else: st.caption("Chưa có")

            with col_hk2:
                st.markdown("##### 🌸 Học kỳ 2")
                if scores_hk2:
                    df2 = pd.DataFrame([{"Môn": s.mon_hoc, "TB": s.dtb_mon, "Chi tiết": f"{s.ddg_tx or ''} | {s.ddg_gk or ''}"} for s in scores_hk2])
                    st.dataframe(df2, hide_index=True, use_container_width=True)
                else: st.caption("Chưa có")
            
            with col_cn:
                st.markdown("##### 🏆 Cả năm")
                if scores_cn:
                    df3 = pd.DataFrame([{"Môn": s.mon_hoc, "TB": s.dtb_mon} for s in scores_cn])
                    st.dataframe(df3, hide_index=True, use_container_width=True)
                else: st.caption("Chưa có")

            # --- PHẦN 2: TỔNG KẾT & ĐÁNH GIÁ (CARD UI) ---
            st.write("")
            if assessment:
                st.markdown(f"""
                <div class="assessment-box">
                    <h4 style="margin-top:0; color:#1565c0">🏅 Tổng Kết Năm Học {target_nam_hoc}</h4>
                    <p><b>Học tập (KQHT):</b> {assessment.kq_hoc_tap or '---'} &nbsp;&nbsp;|&nbsp;&nbsp; 
                       <b>Rèn luyện (KQRL):</b> {assessment.kq_ren_luyen or '---'}</p>
                    <p><b>Danh hiệu:</b> <span style="color:#d32f2f; font-weight:bold">{assessment.danh_hieu or '---'}</span></p>
                    <p><i>Nhận xét: {assessment.nhan_xet or ''}</i></p>
                </div>
                """, unsafe_allow_html=True)

# ==========================================
# 4. GIAO DIỆN ADMIN (Admin UI)
# ==========================================
def admin_ui():
    st.title("⚙️ Trung Tâm Quản Trị")
    if st.button("Đăng xuất"):
        st.session_state.logged_in = False
        st.rerun()

    tab1, tab2 = st.tabs(["📤 Upload Dữ Liệu", "👥 Quản Lý Tài Khoản"])

    with tab1:
        st.subheader("1. Import Tài Khoản Học Sinh")
        st.caption("File Excel cần cột: So_CCCD, Ma_HS, Ho_Ten, Nien_Khoa (VD: 2023-2026), Trang_Thai ('full' hoặc số)")
        
        f_acc = st.file_uploader("Chọn file Danh sách lớp", key="acc")
        if f_acc and st.button("Cập nhật Tài Khoản"):
            try:
                df = pd.read_excel(f_acc)
                df.columns = [str(c).strip().lower() for c in df.columns]
                
                # Mapping cột mềm dẻo
                col_map = {c: c for c in df.columns} # Default
                for c in df.columns:
                    if "cccd" in c: col_map['cccd'] = c
                    if "mã" in c or "ma_hs" in c: col_map['ma'] = c
                    if "tên" in c: col_map['ten'] = c
                    if "niên" in c or "khoa" in c: col_map['khoa'] = c
                    if "trạng" in c or "status" in c: col_map['status'] = c

                count = 0
                for _, row in df.iterrows():
                    # Lấy dữ liệu an toàn
                    cccd = str(row[col_map.get('cccd', 'so_cccd')]).strip().replace('.0','')
                    ma = str(row[col_map.get('ma', 'ma_hs')]).strip().replace('.0','')
                    ten = row[col_map.get('ten', 'ho_ten')]
                    khoa = str(row[col_map.get('khoa', 'nien_khoa')]).strip()
                    # Mặc định là 'full' nếu không có cột status
                    stt = str(row[col_map.get('status', 'xx')]).strip() if 'status' in col_map else 'full'
                    if stt == 'nan': stt = 'full'

                    u = session.query(User).filter_by(so_cccd=cccd).first()
                    if not u:
                        u = User(so_cccd=cccd, ma_hs=ma, ho_ten=ten, nien_khoa=khoa, login_status=stt)
                        u.set_password('123456')
                        session.add(u)
                        count += 1
                    else:
                        u.ma_hs = ma
                        u.nien_khoa = khoa
                        u.login_status = stt
                
                session.commit()
                st.success(f"Đã cập nhật {count} tài khoản mới!")
            except Exception as e:
                st.error(f"Lỗi đọc file: {e}")

        st.divider()
        st.subheader("2. Upload Bảng Điểm (Auto-Detect)")
        st.caption("Chỉ cần kéo thả file (HK1, HK2, Cả năm). Hệ thống tự đọc Năm học & Học kỳ trong nội dung file.")
        
        files = st.file_uploader("Chọn các file điểm (có thể chọn nhiều file)", accept_multiple_files=True, key="scr")
        if files and st.button("Bắt đầu Xử lý Điểm"):
            for f in files:
                try:
                    eng = 'xlrd' if f.name.endswith('.xls') else 'openpyxl'
                    df = pd.read_excel(f, header=None, engine=eng)
                    msg, status = process_upload_auto(df)
                    if status == "success": st.success(f"✅ {f.name}: {msg}")
                    else: st.error(f"❌ {f.name}: {msg}")
                except Exception as e:
                    st.error(f"⚠️ Lỗi file {f.name}: {e}")

    with tab2:
        st.subheader("Danh sách User")
        users = session.query(User).filter(User.is_admin == False).all()
        if users:
            data = [{"CCCD": u.so_cccd, "Tên": u.ho_ten, "Niên khóa": u.nien_khoa, "Lượt Login": u.login_status} for u in users]
            st.dataframe(pd.DataFrame(data), use_container_width=True)
            
            if st.button("Reset tất cả lượt Login về Full"):
                for u in users: u.login_status = "full"
                session.commit()
                st.success("Đã reset!")
                st.rerun()

# ==========================================
# 5. HÀM MAIN
# ==========================================
def main():
    st.set_page_config(page_title="EduScore Pro", page_icon="🎓", layout="wide")
    
    if 'logged_in' not in st.session_state: st.session_state.logged_in = False
    if 'user_id' not in st.session_state: st.session_state.user_id = None
    if 'is_admin' not in st.session_state: st.session_state.is_admin = False

    if not st.session_state.logged_in:
        c1, c2, c3 = st.columns([1,1.5,1])
        with c2:
            st.markdown("<h1 style='text-align: center; color: #1565c0;'>🎓 CỔNG TRA CỨU ĐIỂM THPT</h1>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: center;'>Hệ thống tra cứu điểm số tập trung 3 năm học</p>", unsafe_allow_html=True)
            
            with st.form("login_form"):
                cccd = st.text_input("Số CCCD / Tên đăng nhập")
                pwd = st.text_input("Mật khẩu", type="password")
                btn = st.form_submit_button("Đăng nhập", type="primary", use_container_width=True)
                
                if btn:
                    user = session.query(User).filter_by(so_cccd=cccd).first()
                    if user and user.check_password(pwd):
                        # Logic kiểm tra số lần đăng nhập
                        allow_login = False
                        if user.is_admin:
                            allow_login = True
                        else:
                            if user.login_status == "full":
                                allow_login = True
                            else:
                                try:
                                    count = int(user.login_status)
                                    if count > 0:
                                        allow_login = True
                                        user.login_status = str(count - 1) # Trừ 1 lần
                                        session.commit()
                                    else:
                                        st.error("🚫 Bạn đã hết lượt truy cập cho phép.")
                                except:
                                    st.error("Lỗi trạng thái tài khoản.")

                        if allow_login:
                            st.session_state.logged_in = True
                            st.session_state.user_id = user.id
                            st.session_state.is_admin = user.is_admin
                            st.rerun()
                    else:
                        st.error("Sai thông tin đăng nhập")
    else:
        if st.session_state.is_admin:
            admin_ui()
        else:
            user = session.query(User).get(st.session_state.user_id)
            student_ui(user)

if __name__ == "__main__":
    main()
